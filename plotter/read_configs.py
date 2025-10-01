from __future__ import annotations

from typing import Dict, List, Tuple
import csv
from Figure import Figure
from Cursor import Cursor
from collections import defaultdict
from configparser import ConfigParser
from down_sampling_method import DownSamplingMethod
from cursor_type import CursorType


class ReadConfig:
    def __init__(self) -> None:
        cp = ConfigParser()
        cp.read('config.ini')
        parsedConf = cp['config']
        self.resultsDir = parsedConf['resultsDir']
        self.genHTML = parsedConf.getboolean('genHTML')
        self.genImage = parsedConf.getboolean('genImage')
        self.genIdeal = parsedConf.getboolean('genIdeal')
        self.genCursorPDF = parsedConf.getboolean('genCursorPDF')
        self.genCursorHTML = parsedConf.getboolean('genCursorHTML')
        self.htmlColumns = parsedConf.getint('htmlColumns')
        assert self.htmlColumns > 0 or not self.genHTML
        self.imageColumns = parsedConf.getint('imageColumns')
        assert self.imageColumns > 0 or not self.genImage
        self.htmlCursorColumns = parsedConf.getint('htmlCursorColumns')
        assert self.htmlCursorColumns > 0 or not self.genCursorHTML
        self.imageFormat = parsedConf['imageFormat']
        self.threads = parsedConf.getint('threads')
        assert self.threads > 0
        self.testcaseSheet = parsedConf['testcaseSheet']
        self.simDataDirs : List[Tuple[str, str]] = list()
        simPaths = cp.items('Simulation data paths')
        for name, path in simPaths:
            self.simDataDirs.append((name, path))


def readFigureSetup(filePath: str) -> Dict[int, List[Figure]]:
    '''
    Read figure setup file.
    '''
    setup: List[Dict[str, str | List[int]]] = list()
    with open(filePath, newline='') as setupFile:
        setupReader = csv.DictReader(setupFile, delimiter=';')
        for row in setupReader:
            row['exclude_in_case'] = list(
                set([int(item.strip()) for item in row.get('exclude_in_case', '').split(',') if item.strip() != '']))
            row['include_in_case'] = list(
                set([int(item.strip()) for item in row.get('include_in_case', '').split(',') if item.strip() != '']))
            setup.append(row)

    figureList: List[Figure] = list()
    for figureStr in setup:
        figureList.append(
            Figure(int(figureStr['figure']),  # type: ignore
                   figureStr['title'],  # type: ignore
                   figureStr['units'],  # type: ignore
                   figureStr['emt_signal_1'],  # type: ignore
                   figureStr['emt_signal_2'],  # type: ignore
                   figureStr['emt_signal_3'],  # type: ignore
                   figureStr['rms_signal_1'],  # type: ignore
                   figureStr['rms_signal_2'],  # type: ignore
                   figureStr['rms_signal_3'],  # type: ignore
                   figureStr['gradient_threshold'],  # type: ignore
                   DownSamplingMethod.from_string(figureStr['down_sampling_method']),  # type: ignore
                   figureStr['include_in_case'],  # type: ignore
                   figureStr['exclude_in_case']))  # type: ignore

    defaultSetup = [fig for fig in figureList if fig.include_in_case == []]
    figDict: Dict[int, List[Figure]] = defaultdict(lambda: defaultSetup)

    for fig in figureList:
        if fig.include_in_case != []:
            for inc in fig.include_in_case:
                if not inc in figDict.keys():
                    figDict[inc] = defaultSetup.copy()
                figDict[inc].append(fig)
        else:
            for exc in fig.exclude_in_case:
                if not exc in figDict.keys():
                    figDict[exc] = defaultSetup.copy()
                figDict[exc].remove(fig)
    return figDict


def readCursorSetup(filePath: str) -> List[Cursor]:
    '''
    Read cursor setup file.
    '''
    setup: List[Dict[str, str | List]] = list()
    with open(filePath, newline='') as setupFile:
        setupReader = csv.DictReader(setupFile, delimiter=';')
        for row in setupReader:
            row['cursor_options'] = [CursorType.from_string(str(item.strip())) for item in row.get('cursor_options', '').split(',') if item.strip() != '']
            row['emt_signals'] = [str(item.strip()) for item in row.get('emt_signals', '').split(',') if item.strip() != '']
            row['rms_signals'] = [str(item.strip()) for item in row.get('rms_signals', '').split(',') if item.strip() != '']
            row['time_ranges'] = [float(item.strip()) for item in row.get('time_ranges', '').split(',') if item.strip() != '']
            setup.append(row)

    rankList: List[Cursor] = list()
    for rankStr in setup:
        rankList.append(
            Cursor(int(rankStr['rank']),  # type: ignore
                   str(rankStr['title']),
                   rankStr['cursor_options'],  # type: ignore
                   rankStr['emt_signals'],
                   rankStr['rms_signals'],
                   rankStr['time_ranges']))  # type: ignore
    return rankList