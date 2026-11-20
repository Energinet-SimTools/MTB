# -*- coding: utf-8 -*-
'''
Front-end independent loading and analysis of MTB results, used by MTBViewer.py (no GUI code, so it can also be used
by other front ends, e.g. a Dash app, or by scripts).

It reads config.ini, the testcase sheet, figureSetup.csv and cursorSetup.csv, discovers the result files in the
[Simulation data paths] folders and loads the signals of a case from .psout, [compressed] .csv or .parquet files.
Whether a result file is EMT or RMS is determined by its signals, i.e. whether they match the emt_signal_* or the
rms_signal_* names in figureSetup.csv.
All loaded signals are named as in figureSetup.csv, e.g. 'MTB\\P_pu_PoC' (EMT) or 'meas\\s:ppoc_pu' (RMS).
'''
from __future__ import annotations

import bz2
import gzip
import io
import lzma
import os
import re
import warnings
import zipfile
from collections import OrderedDict
from configparser import ConfigParser
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from cursor_functions import (cursorDelta, cursorEnd, cursorGradMax, cursorGradMean, cursorGradMin, cursorMax,
                              cursorMean, cursorMin, cursorPeakOvershoot, cursorResponseDelay, cursorRiseFallTime,
                              cursorSettlingTime, cursorStart, formatCursorMetric)
from cursor_type import CursorType
from Figure import Figure
from Cursor import Cursor
from read_configs import readCursorSetup, readFigureSetup
from Result import ResultType

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')
np.seterr(divide='ignore', invalid='ignore')

EMT = 'EMT'
RMS = 'RMS'

RESULT_FILE_PATTERN = re.compile(r'^(\w+?)_([0-9]+)(?:\.csv)?\.(psout|inf|csv|zip|gz|bz2|xz|parquet)$', re.IGNORECASE)

# Signals required by genGuideResults() in addition to the figure signals
GUIDE_SIGNALS = ['MTB\\mtb_s_pref_pu', 'MTB\\mtb_s_pavail_pu', 'MTB\\mtb_s_qudroop', 'MTB\\mtb_s_sips_g',
                 'MTB\\mtb_s_sips_d', 'MTB\\mtb_s_qref', 'MTB\\pll_f_hz', 'MTB\\fft_pos_Vmag_pu']

# Cursor metrics that only need a single signal and therefore can be calculated for every trace
SIGNAL_METRICS = [CursorType.START, CursorType.END, CursorType.DELTA, CursorType.MIN, CursorType.MAX,
                  CursorType.MEAN, CursorType.GRAD_MIN, CursorType.GRAD_MAX, CursorType.GRAD_MEAN,
                  CursorType.RESPONSE, CursorType.RISE_FALL, CursorType.SETTLING, CursorType.OVERSHOOT]

SIGNAL_METRIC_LABELS = {CursorType.START: 'Start (A)', CursorType.END: 'End (B)', CursorType.DELTA: 'Delta',
                        CursorType.MIN: 'Min', CursorType.MAX: 'Max', CursorType.MEAN: 'Mean',
                        CursorType.GRAD_MIN: 'Grad min [/min]', CursorType.GRAD_MAX: 'Grad max [/min]',
                        CursorType.GRAD_MEAN: 'Grad mean [/min]', CursorType.RESPONSE: 'Response delay [s]',
                        CursorType.RISE_FALL: 'Rise/fall time [s]', CursorType.SETTLING: 'Settling time [s]',
                        CursorType.OVERSHOOT: 'Overshoot [%]'}

FIGURE_SETUP_COLUMNS = ['figure', 'title', 'units', 'emt_signal_1', 'emt_signal_2', 'emt_signal_3', 'rms_signal_1',
                        'rms_signal_2', 'rms_signal_3', 'down_sampling_method', 'gradient_threshold',
                        'include_in_case', 'exclude_in_case']


#-----------------------------------------------------------------------------#
# Configuration, testcases, figure and cursor setup
#-----------------------------------------------------------------------------#

class ViewerConfig:
    '''
    The parts of the plotter config.ini used by the viewer. Relative paths are resolved relative to the config.ini folder.
    '''
    def __init__(self, configPath: str) -> None:
        if not os.path.isfile(configPath):
            raise FileNotFoundError(f'The config file "{configPath}" does not exist.')
        self.configPath = os.path.abspath(configPath)
        self.baseDir = os.path.dirname(self.configPath)
        cp = ConfigParser()
        cp.read(self.configPath)
        self.testcaseSheet = self.resolve(cp.get('config', 'testcaseSheet', fallback=''))
        self.simDataDirs: List[Tuple[str, str]] = []
        if cp.has_section('Simulation data paths'):
            self.simDataDirs = [(name, self.resolve(path)) for name, path in cp.items('Simulation data paths')]
        self.figureSetupPath = os.path.join(self.baseDir, 'figureSetup.csv')
        self.cursorSetupPath = os.path.join(self.baseDir, 'cursorSetup.csv')

    def resolve(self, path: str) -> str:
        if not path:
            return ''
        return path if os.path.isabs(path) else os.path.normpath(os.path.join(self.baseDir, path))


class Testcases:
    '''
    The 'Settings' and '<Casegroup> cases' (and optionally 'Custom cases') sheets of the testcase sheet
    '''
    def __init__(self, testcaseSheet: str) -> None:
        self.settingsDict: Dict = {}
        self.casesDf: Optional[pd.DataFrame] = None
        self.rankNameDict: Dict[int, str] = {}
        self.error: Optional[str] = None
        if not testcaseSheet or not os.path.isfile(testcaseSheet):
            self.error = f'The testcase sheet "{testcaseSheet}" does not exist. Case names, guide curves and case cursors are not available.'
            return
        try:
            settingsDf = pd.read_excel(testcaseSheet, sheet_name='Settings', header=0)
            self.settingsDict = dict(zip(settingsDf['Name'], settingsDf['Value']))
            caseGroup = self.settingsDict['Casegroup']
            casesDf = pd.read_excel(testcaseSheet, sheet_name=f'{caseGroup} cases', header=[0, 1]).iloc[:, :60]
            if self.settingsDict.get('Run custom cases', False):
                customCasesDf = pd.read_excel(testcaseSheet, sheet_name='Custom cases', header=[0, 1]).iloc[:, :60]
                casesDf = pd.concat([casesDf, customCasesDf], ignore_index=True)
            self.casesDf = casesDf
            self.rankNameDict = {int(rank): str(name) for rank, name in zip(casesDf['Case']['Rank'], casesDf['Case']['Name']) if pd.notna(rank)}
        except Exception as e:
            self.error = f'Could not read the testcase sheet "{testcaseSheet}": {e}'

    @property
    def pfFlatTime(self) -> float:
        return float(self.settingsDict.get('PF flat time', 0.0) or 0.0)

    @property
    def pscadInitTime(self) -> float:
        return float(self.settingsDict.get('PSCAD Initialization time', 0.0) or 0.0)

    def caseDf(self, rank: int) -> Optional[pd.DataFrame]:
        if self.casesDf is None:
            return None
        caseDf = self.casesDf[self.casesDf['Case']['Rank'] == rank]
        return caseDf if not caseDf.empty else None

    def caseName(self, rank: int) -> str:
        return self.rankNameDict.get(rank, '')


def readFigureSetupDf(path: str) -> pd.DataFrame:
    '''
    Read figureSetup.csv as a DataFrame of strings (used by the figure setup editor)
    '''
    df = pd.read_csv(path, sep=';', dtype=str, keep_default_na=False)
    for col in FIGURE_SETUP_COLUMNS:
        if col not in df.columns:
            df[col] = ''
    return df[~(df == '').all(axis=1)].reset_index(drop=True)


def writeFigureSetupDf(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, sep=';', index=False)


def figuresForRank(figureDict: Dict[int, List[Figure]], rank: int) -> List[Figure]:
    return figureDict.get(rank, figureDict.get(-1, []))


def figureSignals(figure: Figure, kind: str) -> List[str]:
    prefix = 'emt' if kind == EMT else 'rms'
    return [s for s in (getattr(figure, f'{prefix}_signal_{i}') for i in range(1, 4)) if s]


def cursorsForRank(cursorList: List[Cursor], rankName: str) -> List[Cursor]:
    return [c for c in cursorList if c.id == rankName]


def cursorPresetIntervals(cursors: List[Cursor]) -> List[Tuple[float, ...]]:
    '''
    Unique cursor time intervals from cursorSetup.csv, used as presets for the A and B cursors
    '''
    intervals = []
    for cursor in cursors:
        tr = cursor.time_ranges
        for i in range(len(tr) // 2):
            interval = (tr[2 * i], tr[2 * i + 1])
            if interval not in intervals:
                intervals.append(interval)
        if len(tr) % 2 == 1 and (tr[-1],) not in intervals:
            intervals.append((tr[-1],))
    return intervals


#-----------------------------------------------------------------------------#
# Result file discovery
#-----------------------------------------------------------------------------#

@dataclass
class ResultFile:
    group: str
    path: str
    projectName: str
    rank: int
    fmt: str            # 'psout', 'inf' (legacy), 'csv' or 'parquet'

    @property
    def shorthand(self) -> str:
        return f'{self.group}\\{self.projectName}'


def discoverResults(simDataDirs: List[Tuple[str, str]]) -> Tuple[Dict[int, List[ResultFile]], List[str]]:
    '''
    Find all <project>_<rank>.psout|.inf|.csv[.zip|.gz|.bz2|.xz]|.parquet files in the result folders.
    The .csv data files belonging to a legacy .inf file (<project>_<rank>[_<n>].csv) are not results by themselves.
    '''
    results: Dict[int, List[ResultFile]] = {}
    messages: List[str] = []
    for group, folder in simDataDirs:
        if not os.path.isdir(folder):
            messages.append(f"ERROR: The '{group}' folder in [Simulation data paths] does not exist: {folder}")
            continue
        found = 0
        fileNames = sorted(os.listdir(folder))
        infStems = [os.path.splitext(f)[0].lower() for f in fileNames if f.lower().endswith('.inf')]
        infDataFile = re.compile(r'^(' + '|'.join(re.escape(stem) for stem in infStems) + r')(_[0-9]+)?\.csv$') if infStems else None
        for fileName in fileNames:
            match = RESULT_FILE_PATTERN.match(fileName)
            if not match or (infDataFile is not None and infDataFile.match(fileName.lower())):
                continue
            ext = match.group(3).lower()
            fmt = ext if ext in ('psout', 'inf', 'parquet') else 'csv'
            rank = int(match.group(2))
            results.setdefault(rank, []).append(ResultFile(group, os.path.join(folder, fileName), match.group(1), rank, fmt))
            found += 1
        messages.append(f"Found {found} result file(s) in '{group}': {folder}")
    return dict(sorted(results.items())), messages


#-----------------------------------------------------------------------------#
# Result file loading
#-----------------------------------------------------------------------------#

@dataclass
class LoadedResult:
    file: ResultFile
    kind: str                                   # EMT or RMS
    data: pd.DataFrame                          # 'time' (not offset) + the requested signals that were found
    timeOffset: float                           # PSCAD initialisation time or PF flat time
    available: List[str] = field(default_factory=list)  # All signal names available in the file
    missing: List[str] = field(default_factory=list)    # Requested signals of the result's kind not found

    def time(self) -> np.ndarray:
        return self.data['time'].to_numpy() - self.timeOffset

    def has(self, signal: str) -> bool:
        return signal in self.data.columns


def _openText(path: str, encoding: str):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.zip':
        zf = zipfile.ZipFile(path)
        return io.TextIOWrapper(zf.open(zf.namelist()[0]), encoding=encoding, errors='replace')
    opener = {'.gz': gzip.open, '.bz2': bz2.open, '.xz': lzma.open}.get(ext, open)
    return opener(path, 'rt', encoding=encoding, errors='replace')


def detectCsvFormat(path: str) -> Tuple[str, str, object]:
    '''
    Detect the column separator, decimal separator and number of header rows (1 for PSCAD, 2 for PowerFactory)
    '''
    with _openText(path, 'utf-8') as f:
        firstLine, secondLine = f.readline(), f.readline()
    sep = ';' if ';' in firstLine else ','
    decimal = ',' if sep == ';' else '.'
    try:
        float(secondLine.split(sep)[0].strip().strip('"').replace(decimal, '.'))
        header = 0
    except ValueError:
        header = [0, 1]
    return sep, decimal, header


def _rmsColumnName(column: Tuple[str, str]) -> str:
    '''
    PowerFactory ('##meas', 's:ppoc_pu') -> 'meas\\s:ppoc_pu' (the inverse of process_results.getColNames)
    '''
    obj = str(column[0]).lstrip('#')
    return f'{obj}\\{column[1]}'


def _readTable(path: str, fmt: str) -> Tuple[pd.DataFrame, str]:
    '''
    Read a .csv or .parquet result file. Returns the DataFrame with 'time' as the first column and the
    structural kind (RMS for two header rows, i.e. PowerFactory, else EMT)
    '''
    if fmt == 'parquet':
        df = pd.read_parquet(path)
    else:
        sep, decimal, header = detectCsvFormat(path)
        try:
            df = pd.read_csv(path, sep=sep, decimal=decimal, header=header, compression='infer')
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=sep, decimal=decimal, header=header, compression='infer', encoding='latin-1')
    if isinstance(df.columns, pd.MultiIndex):
        names = ['time'] + [_rmsColumnName(c) for c in df.columns[1:]]
        structuralKind = RMS
    else:
        names = ['time'] + [str(c) for c in df.columns[1:]]
        structuralKind = EMT
    df.columns = names
    df = df.loc[:, ~pd.Index(names).duplicated()]
    return df.reset_index(drop=True), structuralKind


def _leaf(name: str) -> str:
    return name.split('\\')[-1]


def _resolveColumn(name: str, columns: List[str]) -> Optional[str]:
    '''
    Find the column for a figureSetup.csv signal name. The full signal path must match, e.g. 'MTB\\P_pu_PoC' or
    'PV\\Inverter\\P_pu' (EMT) and 'meas\\s:ppoc_pu' (RMS, the leading '#'s of the PowerFactory object are ignored)
    '''
    if name in columns:
        return name
    stripped = name.lstrip('#')
    return stripped if stripped in columns else None


def _classify(columns: List[str], emtNames: List[str], rmsNames: List[str], structuralKind: str) -> str:
    '''
    Determine whether a result is EMT or RMS from its signals
    '''
    emtScore = sum(_resolveColumn(n, columns) is not None for n in emtNames)
    rmsScore = sum(_resolveColumn(n, columns) is not None for n in rmsNames)
    if emtScore > rmsScore:
        return EMT
    if rmsScore > emtScore:
        return RMS
    return structuralKind


def _readPsout(path: str, requested: List[str]) -> Tuple[pd.DataFrame, List[str], List[str]]:
    '''
    Read the requested signals from a .psout file, opening it only once.
    MTB signals are always named 'MTB\\<signal>', also if the MTB is not placed on the main canvas.
    Signal arrays are available as '<name>_<n>'.
    Returns (data, available signal names, missing signal names)
    '''
    import mhi.psout
    from process_psout import getPsoutSignalRecords
    from process_results import findMtbPath, fromMtbSignalName, toMtbSignalName

    with mhi.psout.File(path) as psoutFile:
        run = psoutFile.run(0)
        records = getPsoutSignalRecords(psoutFile)
        mtbPath = findMtbPath(records)
        sizes = {p: r.num_calls for p, r in records.items()}
        available = []
        for p, n in sizes.items():
            name = toMtbSignalName(p, mtbPath)
            available.extend([name] if n <= 1 else [f'{name}_{i + 1}' for i in range(n)])

        def resolve(name: str) -> Optional[Tuple[str, int]]:
            signalPath = fromMtbSignalName(name, mtbPath)
            if signalPath in records:
                return signalPath, 0
            m = re.match(r'^(.*)_([0-9]+)$', signalPath)
            if m and m.group(1) in records and 1 <= int(m.group(2)) <= sizes[m.group(1)]:
                return m.group(1), int(m.group(2)) - 1
            return None

        columns: Dict[str, np.ndarray] = {}
        missing: List[str] = []
        time = None
        for name in requested:
            if name in columns:
                continue
            resolved = resolve(name)
            if resolved is None:
                missing.append(name)
                continue
            signalPath, idx = resolved
            traceCalls = list(records[signalPath].calls())
            trace = run.trace(traceCalls[idx])
            data = np.array(trace.data)
            if time is None:
                time = np.array(trace.domain.data)
            if data.shape != time.shape:
                missing.append(name)
                continue
            columns[name] = data

        if time is None and records:
            firstRecord = next(iter(records.values()))
            time = np.array(run.trace(next(iter(firstRecord.calls()))).domain.data)

    df = pd.DataFrame({'time': time if time is not None else np.array([]), **columns})
    return df, available, missing


def _readInf(path: str, requested: List[str]) -> Tuple[pd.DataFrame, List[str], List[str]]:
    '''
    Read a legacy (MTB 1.0) PSCAD .inf/.csv result. These signals have no path, i.e. each signal name is unique
    (see 'Use legacy Unit measurement signal naming' in config.ini), so the signals are matched on the last part of
    the figureSetup.csv name only, e.g. 'MTB\\P_pu_PoC' -> 'P_pu_PoC'.
    '''
    from read_and_write_functions import loadEMT

    table = loadEMT(path)
    columns = [str(c) for c in table.columns if c != 'time']
    selected = {'time': table['time'].to_numpy(dtype=float)}
    missing = []
    for name in requested:
        if _leaf(name) in columns:
            selected.setdefault(name, pd.to_numeric(table[_leaf(name)], errors='coerce').to_numpy())
        else:
            missing.append(name)
    return pd.DataFrame(selected), columns, missing


class ResultLoader:
    '''
    Loads results of a case with a small least-recently-used cache
    '''
    def __init__(self, cacheSize: int = 12) -> None:
        self.cacheSize = cacheSize
        self._cache: 'OrderedDict[Tuple, LoadedResult]' = OrderedDict()

    def clear(self) -> None:
        self._cache.clear()

    def load(self, resultFile: ResultFile, emtNames: List[str], rmsNames: List[str], testcases: Testcases) -> LoadedResult:
        key = (resultFile.path, os.path.getmtime(resultFile.path), tuple(emtNames), tuple(rmsNames))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        if resultFile.fmt == 'psout':
            data, available, missing = _readPsout(resultFile.path, emtNames)
            loaded = LoadedResult(resultFile, EMT, data, testcases.pscadInitTime, available, missing)
        elif resultFile.fmt == 'inf':
            data, available, missing = _readInf(resultFile.path, emtNames)
            loaded = LoadedResult(resultFile, EMT, data, testcases.pscadInitTime, available, missing)
        else:
            table, structuralKind = _readTable(resultFile.path, resultFile.fmt)
            columns = list(table.columns[1:])
            kind = _classify(columns, emtNames, rmsNames, structuralKind)
            requested = emtNames if kind == EMT else rmsNames
            selected = {'time': table['time'].to_numpy(dtype=float)}
            missing = []
            for name in requested:
                column = _resolveColumn(name, columns)
                if column is None:
                    missing.append(name)
                elif name not in selected:
                    selected[name] = pd.to_numeric(table[column], errors='coerce').to_numpy()
            offset = testcases.pscadInitTime if kind == EMT else testcases.pfFlatTime
            loaded = LoadedResult(resultFile, kind, pd.DataFrame(selected), offset, columns, missing)

        self._cache[key] = loaded
        while len(self._cache) > self.cacheSize:
            self._cache.popitem(last=False)
        return loaded


def requestedSignals(figures: List[Figure], cursors: List[Cursor]) -> Tuple[List[str], List[str]]:
    '''
    The EMT and RMS signals needed for the figures, the cursors and the guide curves of a case
    '''
    emt: List[str] = list(GUIDE_SIGNALS)
    rms: List[str] = []
    for fig in figures:
        emt.extend(figureSignals(fig, EMT))
        rms.extend(figureSignals(fig, RMS))
    for cursor in cursors:
        emt.extend(cursor.emt_signals)
        rms.extend(cursor.rms_signals)
    return list(dict.fromkeys(emt)), list(dict.fromkeys(rms))


#-----------------------------------------------------------------------------#
# Guide curves and cursor metrics
#-----------------------------------------------------------------------------#

@dataclass
class GuideTrace:
    figureTitle: str
    name: str
    time: np.ndarray
    values: np.ndarray


def computeGuides(loaded: LoadedResult, testcases: Testcases, rank: int) -> List[GuideTrace]:
    '''
    Calculate the guide curves for an EMT result using guide_functions.genGuideResults()
    '''
    from guide_functions import genGuideResults

    caseDf = testcases.caseDf(rank)
    if loaded.kind != EMT or caseDf is None or not testcases.settingsDict:
        return []
    result = SimpleNamespace(typ=ResultType.EMT_PSOUT)
    guide = genGuideResults(result, loaded.data.reset_index(drop=True), testcases.settingsDict, caseDf, testcases.pscadInitTime)
    traces = []
    for figTitle, signal in zip(guide['figs'][1:], guide['signals'][1:]):
        if signal in guide['data'].columns:
            traces.append(GuideTrace(figTitle, signal, guide['data']['time'].to_numpy(), guide['data'][signal].to_numpy(dtype=float)))
    return traces


def _fmt(value, digits: int = 4) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '-'
    if np.isnan(v):
        return '-'
    if np.isinf(v) or abs(v) >= 1e5 or (v != 0 and abs(v) < 1e-3):
        return f'{v:.{digits}g}'
    return f'{v:.{digits}f}'


def signalMetrics(t: np.ndarray, y: np.ndarray, tA: float, tB: float, options: List[CursorType]) -> Dict[CursorType, str]:
    '''
    Calculate single-signal cursor metrics between the A and B cursors using the cursor_functions
    '''
    t0, t1 = min(tA, tB), max(tA, tB)
    mask = (t >= t0) & (t <= t1)
    df = pd.DataFrame({'t': t[mask], 'y': y[mask]})
    interval: Tuple = ()
    out: Dict[CursorType, str] = {}
    if df.empty:
        return {o: '-' for o in options}
    for option in options:
        try:
            if option == CursorType.START:
                out[option] = _fmt(cursorStart(df, interval)[1])
            elif option == CursorType.END:
                out[option] = _fmt(cursorEnd(df, interval)[1])
            elif option == CursorType.DELTA:
                out[option] = _fmt(cursorDelta(df, interval))
            elif option == CursorType.MIN:
                yMin, tMin = cursorMin(df, interval)
                out[option] = f'{_fmt(yMin)} @ {tMin:.4f} s'
            elif option == CursorType.MAX:
                yMax, tMax = cursorMax(df, interval)
                out[option] = f'{_fmt(yMax)} @ {tMax:.4f} s'
            elif option == CursorType.MEAN:
                out[option] = _fmt(cursorMean(df, interval))
            elif option == CursorType.GRAD_MIN:
                out[option] = _fmt(cursorGradMin(df, interval))
            elif option == CursorType.GRAD_MAX:
                out[option] = _fmt(cursorGradMax(df, interval))
            elif option == CursorType.GRAD_MEAN:
                out[option] = _fmt(cursorGradMean(df, interval))
            elif option == CursorType.RESPONSE:
                out[option] = _fmt(cursorResponseDelay(df, interval))
            elif option == CursorType.RISE_FALL:
                out[option] = _fmt(cursorRiseFallTime(df, interval)[1])
            elif option == CursorType.SETTLING:
                out[option] = _fmt(cursorSettlingTime(df, interval, tol=2))
            elif option == CursorType.OVERSHOOT:
                out[option] = _fmt(cursorPeakOvershoot(df, interval)[0] * 100, 3)
        except Exception:
            out[option] = 'error'
    return out


def caseCursorMetrics(cursors: List[Cursor], loadedResults: List[LoadedResult], testcases: Testcases, rank: int,
                      tA: float, tB: float) -> pd.DataFrame:
    '''
    Calculate the cursorSetup.csv metrics of the case between the A and B cursors for all loaded results.
    Returns a DataFrame with the columns 'Cursor', 'Metric' and one column per result.
    '''
    caseDf = testcases.caseDf(rank)
    interval = (min(tA, tB), max(tA, tB))
    rows = []
    for cursor in cursors:
        for option in cursor.cursor_options:
            row = {'Cursor': cursor.title, 'Metric': option.name}
            for loaded in loadedResults:
                signals = cursor.emt_signals if loaded.kind == EMT else cursor.rms_signals
                if not signals or not all(loaded.has(s) for s in signals):
                    row[loaded.file.shorthand] = '-'
                    continue
                df = pd.DataFrame({'t': loaded.time(), **{s: loaded.data[s].to_numpy() for s in signals}})
                try:
                    row[loaded.file.shorthand] = formatCursorMetric(option, df, interval, testcases.settingsDict, caseDf)
                except Exception as e:
                    row[loaded.file.shorthand] = f'error: {e}'
            rows.append(row)
    return pd.DataFrame(rows)


def loadSetups(config: ViewerConfig) -> Tuple[Dict[int, List[Figure]], List[Cursor], List[str]]:
    '''
    Read figureSetup.csv and cursorSetup.csv next to config.ini
    '''
    messages = []
    figureDict: Dict[int, List[Figure]] = {-1: []}
    cursorList: List[Cursor] = []
    if os.path.isfile(config.figureSetupPath):
        try:
            figureDict = readFigureSetup(config.figureSetupPath)
        except Exception as e:
            messages.append(f'ERROR: Could not read {config.figureSetupPath}: {e}')
    else:
        messages.append(f'ERROR: {config.figureSetupPath} does not exist.')
    if os.path.isfile(config.cursorSetupPath):
        try:
            cursorList = readCursorSetup(config.cursorSetupPath)
        except Exception as e:
            messages.append(f'WARNING: Could not read {config.cursorSetupPath}: {e}')
    return figureDict, cursorList, messages
