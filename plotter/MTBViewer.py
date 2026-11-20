# -*- coding: utf-8 -*-
'''
MTBViewer (experimental) - interactive viewer for MTB EMT (PSCAD) and RMS (PowerFactory) results.
Its features, settings and behaviour may change in future releases.

    python MTBViewer.py [-c CONFIG] [-r RANK] [--export-png FILE] [--export-pdf FILE]

The plotter config.ini is used for the testcase sheet and the [Simulation data paths] folders, and figureSetup.csv and
cursorSetup.csv next to it for the figures and the case cursors. Result files can be .psout, [compressed] .csv or
.parquet; whether a result is EMT or RMS is determined by its signals.

Features:
    - Back/Next and a dropdown to select the test case (PgUp/PgDn or Alt+Left/Right)
    - One plot per figure with linked time axes, independent x/y zoom and per-source on/off switches
    - Guide curves calculated in memory (guide_functions.genGuideResults)
    - Two shared cursors, A and B, with selectable metrics for every visible trace and the cursorSetup.csv case metrics
    - A figure setup editor for figureSetup.csv with the signals found in the result files
    - Export of the current case to PNG/PDF and of the cursor tables to CSV
'''
from __future__ import annotations

import argparse
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import numpy as np
import pandas as pd

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    import pyqtgraph as pg
except ImportError:
    print('MTBViewer requires PySide6 and pyqtgraph. Install them with "pip install PySide6 pyqtgraph".')
    sys.exit(1)

from cursor_type import CursorType
from down_sampling_method import DownSamplingMethod
from Figure import Figure
from results_data import (EMT, FIGURE_SETUP_COLUMNS, RMS, SIGNAL_METRIC_LABELS, SIGNAL_METRICS, GuideTrace,
                            LoadedResult, ResultFile, ResultLoader, Testcases, ViewerConfig, caseCursorMetrics,
                            computeGuides, cursorPresetIntervals, cursorsForRank, discoverResults, figureSignals,
                            figuresForRank, loadSetups, readFigureSetupDf, requestedSignals, signalMetrics,
                            writeFigureSetupDf)

__version__ = '1.0'

# Same colour palette as plotter.colorMap()
PALETTE = ['#e6194B', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
           '#fabed4', '#469990', '#dcbeff', '#9A6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1',
           '#000075', '#a9a9a9', '#000000']
GUIDE_COLORS = ['#0a515d', '#057d7c', '#008b8b', '#03d7b6']
GUIDE_SOURCE = 'Guide'
CURSOR_COLORS = {'A': '#d62728', 'B': '#1f77b4'}
DEFAULT_METRICS = [CursorType.START, CursorType.END, CursorType.DELTA, CursorType.MIN, CursorType.MAX, CursorType.MEAN]

pg.setConfigOptions(antialias=False, background='w', foreground='k')


def leaf(name: str) -> str:
    return name.split('\\')[-1]


def sourceKey(loaded: LoadedResult) -> str:
    return f'{loaded.file.shorthand} [{loaded.kind}]'


#-----------------------------------------------------------------------------#
# Background loading
#-----------------------------------------------------------------------------#

@dataclass
class CaseData:
    rank: int
    loaded: List[LoadedResult] = field(default_factory=list)
    guides: Dict[str, List[GuideTrace]] = field(default_factory=dict)   # Source key -> guide traces
    messages: List[str] = field(default_factory=list)


class Bridge(QtCore.QObject):
    caseLoaded = QtCore.Signal(int, object)     # request id, CaseData


#-----------------------------------------------------------------------------#
# Plot panel
#-----------------------------------------------------------------------------#

class PlotPanel(QtWidgets.QFrame):
    '''
    One figure: a title, on/off switches per source and a pyqtgraph plot with the A and B cursors
    '''
    visibilityChanged = QtCore.Signal()

    def __init__(self, figure: Figure, parent=None) -> None:
        super().__init__(parent)
        self.figure = figure
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        self.titleLabel = QtWidgets.QLabel(f'<b>{figure.title}</b> [{figure.units}]')
        header.addWidget(self.titleLabel)
        header.addStretch()
        self.switchLayout = QtWidgets.QHBoxLayout()
        self.switchLayout.setSpacing(8)
        header.addLayout(self.switchLayout)
        layout.addLayout(header)

        self.plotWidget = pg.PlotWidget()
        self.plotItem = self.plotWidget.getPlotItem()
        self.plotItem.showGrid(x=True, y=True, alpha=0.3)
        self.plotItem.setLabel('bottom', 'Time [s]')
        self.plotItem.setLabel('left', f'[{figure.units}]')
        for axis in ('left', 'bottom'):
            self.plotItem.getAxis(axis).enableAutoSIPrefix(False)
        self.plotItem.getViewBox().setAutoVisible(y=True)     # Auto range y on the visible time range only
        self.legend = self.plotItem.addLegend(offset=(5, 5), labelTextSize='8pt', brush=(255, 255, 255, 190))
        self.plotWidget.setMinimumHeight(300)
        layout.addWidget(self.plotWidget)

        self.curves: Dict[str, List[pg.PlotDataItem]] = {}
        self.switches: Dict[str, QtWidgets.QCheckBox] = {}
        self.cursorLines: Dict[str, pg.InfiniteLine] = {}
        for name, color in CURSOR_COLORS.items():
            line = pg.InfiniteLine(pos=0.0, angle=90, movable=True, pen=pg.mkPen(color, width=1.5, style=Qt.DashLine),
                                   hoverPen=pg.mkPen(color, width=3), label=name,
                                   labelOpts={'position': 0.04, 'color': color, 'fill': (255, 255, 255, 200)})
            line.cursorName = name
            line.setZValue(100)
            self.plotItem.addItem(line, ignoreBounds=True)
            self.cursorLines[name] = line

    def addCurve(self, source: str, name: str, t: np.ndarray, y: np.ndarray, color: str, dashed: bool = False) -> None:
        pen = pg.mkPen(color, width=1.5, style=Qt.DashLine if dashed else Qt.SolidLine)
        item = self.plotItem.plot(t, y, pen=pen, name=name)
        item.setDownsampling(auto=True, method='peak')
        item.setClipToView(True)
        item.fullT, item.fullY, item.source, item.signalName = t, y, source, name
        item.visibleChanged.connect(self.visibilityChanged)
        self.curves.setdefault(source, []).append(item)
        if source not in self.switches:
            switch = QtWidgets.QCheckBox(source)
            switch.setChecked(True)
            swatch = QtGui.QPixmap(12, 12)
            swatch.fill(QtGui.QColor(color))
            switch.setIcon(QtGui.QIcon(swatch))
            switch.toggled.connect(lambda checked, s=source: self.setSourceVisible(s, checked))
            self.switchLayout.addWidget(switch)
            self.switches[source] = switch

    def finishLegend(self) -> None:
        '''
        One legend row per source, i.e. as many columns as the maximum number of traces of a source
        '''
        self.legend.setColumnCount(max([len(items) for items in self.curves.values()] + [1]))

    def setSourceVisible(self, source: str, visible: bool) -> None:
        for item in self.curves.get(source, []):
            item.setVisible(visible)
        if source in self.switches and self.switches[source].isChecked() != visible:
            self.switches[source].blockSignals(True)
            self.switches[source].setChecked(visible)
            self.switches[source].blockSignals(False)

    def visibleCurves(self) -> List[pg.PlotDataItem]:
        return [item for items in self.curves.values() for item in items if item.isVisible()]

    def setCursorsVisible(self, visible: bool) -> None:
        for line in self.cursorLines.values():
            line.setVisible(visible)


#-----------------------------------------------------------------------------#
# Cursor panel
#-----------------------------------------------------------------------------#

class CursorPanel(QtWidgets.QWidget):
    '''
    Cursor positions, metric selection and the cursor tables
    '''
    metricsChanged = QtCore.Signal()
    presetSelected = QtCore.Signal(float, float)
    cursorsToView = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        top = QtWidgets.QHBoxLayout()
        self.positionLabel = QtWidgets.QLabel()
        top.addWidget(self.positionLabel)
        top.addStretch()
        top.addWidget(QtWidgets.QLabel('Preset (cursorSetup.csv):'))
        self.presetCombo = QtWidgets.QComboBox()
        self.presetCombo.setMinimumWidth(160)
        self.presetCombo.activated.connect(self._presetActivated)
        top.addWidget(self.presetCombo)
        toViewButton = QtWidgets.QPushButton('Cursors to view')
        toViewButton.setToolTip('Move cursors A and B into the visible time range')
        toViewButton.clicked.connect(self.cursorsToView)
        top.addWidget(toViewButton)
        copyButton = QtWidgets.QPushButton('Copy table')
        copyButton.setToolTip('Copy the selected cursor table to the clipboard (paste into Excel)')
        copyButton.clicked.connect(self.copyTable)
        top.addWidget(copyButton)
        layout.addLayout(top)

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.metricList = QtWidgets.QListWidget()
        for option in SIGNAL_METRICS:
            item = QtWidgets.QListWidgetItem(SIGNAL_METRIC_LABELS[option])
            item.setData(Qt.UserRole, option)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if option in DEFAULT_METRICS else Qt.Unchecked)
            self.metricList.addItem(item)
        self.metricList.itemChanged.connect(lambda _: self.metricsChanged.emit())
        self.metricList.setMaximumWidth(220)
        splitter.addWidget(self.metricList)

        self.tables = QtWidgets.QTabWidget()
        self.signalTable = self._makeTable()
        self.caseTable = self._makeTable()
        self.tables.addTab(self.signalTable, 'Signals (A to B)')
        self.tables.addTab(self.caseTable, 'Case cursors (cursorSetup.csv, A to B)')
        splitter.addWidget(self.tables)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        self._presets: List[tuple] = []

    @staticmethod
    def _makeTable() -> QtWidgets.QTableWidget:
        table = QtWidgets.QTableWidget()
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        return table

    def selectedMetrics(self) -> List[CursorType]:
        return [self.metricList.item(i).data(Qt.UserRole) for i in range(self.metricList.count())
                if self.metricList.item(i).checkState() == Qt.Checked]

    def setPositions(self, tA: float, tB: float) -> None:
        self.positionLabel.setText(f'<b style="color:{CURSOR_COLORS["A"]}">A</b> = {tA:.4f} s &nbsp; '
                                   f'<b style="color:{CURSOR_COLORS["B"]}">B</b> = {tB:.4f} s &nbsp; '
                                   f'\u0394t = {tB - tA:.4f} s')

    def setPresets(self, intervals: List[tuple], tEnd: float) -> None:
        self._presets = [(i[0], i[1] if len(i) == 2 else tEnd) for i in intervals]
        self.presetCombo.clear()
        self.presetCombo.addItem('-' if intervals else '(none for this case)')
        for i in intervals:
            self.presetCombo.addItem(f'{i[0]} s : {i[1]} s' if len(i) == 2 else f'{i[0]} s : end')

    def _presetActivated(self, index: int) -> None:
        if 1 <= index <= len(self._presets):
            self.presetSelected.emit(*self._presets[index - 1])

    @staticmethod
    def fillTable(table: QtWidgets.QTableWidget, df: pd.DataFrame, colors: Optional[List[str]] = None) -> None:
        table.setUpdatesEnabled(False)
        table.clear()
        table.setRowCount(len(df))
        table.setColumnCount(len(df.columns))
        table.setHorizontalHeaderLabels([str(c) for c in df.columns])
        for r, row in enumerate(df.itertuples(index=False)):
            for c, value in enumerate(row):
                item = QtWidgets.QTableWidgetItem(str(value))
                if colors is not None and c == 1:
                    item.setForeground(QtGui.QColor(colors[r]))
                table.setItem(r, c, item)
        table.setUpdatesEnabled(True)

    def copyTable(self) -> None:
        table = self.tables.currentWidget()
        rows = ['\t'.join(table.horizontalHeaderItem(c).text() for c in range(table.columnCount()))]
        for r in range(table.rowCount()):
            rows.append('\t'.join(table.item(r, c).text() if table.item(r, c) else '' for c in range(table.columnCount())))
        QtWidgets.QApplication.clipboard().setText('\n'.join(rows))


#-----------------------------------------------------------------------------#
# Figure setup editor
#-----------------------------------------------------------------------------#

class SignalComboDelegate(QtWidgets.QStyledItemDelegate):
    '''
    Editable combo box with completion for the emt_signal_* and rms_signal_* columns
    '''
    def __init__(self, signalsProvider, parent=None) -> None:
        super().__init__(parent)
        self.signalsProvider = signalsProvider

    def createEditor(self, parent, option, index):
        combo = QtWidgets.QComboBox(parent)
        combo.setEditable(True)
        combo.addItem('')
        combo.addItems(self.signalsProvider(index.column()))
        combo.completer().setFilterMode(Qt.MatchContains)
        combo.completer().setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        return combo

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or '')

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText().strip())


class FigureSetupEditor(QtWidgets.QWidget):
    '''
    Editor for figureSetup.csv. Signals can be picked from the signals found in the result files of the current case.
    '''
    applied = QtCore.Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.path = ''
        self.columns: List[str] = list(FIGURE_SETUP_COLUMNS)
        self.availableSignals: Dict[str, List[str]] = {EMT: [], RMS: []}
        self._backupDone = False

        layout = QtWidgets.QVBoxLayout(self)
        buttons = QtWidgets.QHBoxLayout()
        for text, slot, tip in [('Add figure', self.addRow, 'Add an empty figure row'),
                                ('Delete figure', self.deleteRows, 'Delete the selected figure rows'),
                                ('Move up', lambda: self.moveRow(-1), 'Move the selected figure up'),
                                ('Move down', lambda: self.moveRow(1), 'Move the selected figure down'),
                                ('Revert', self.revert, 'Reload figureSetup.csv from disk'),
                                ('Save and apply', self.saveAndApply, 'Save figureSetup.csv (a .bak backup is made) and update the plots')]:
            button = QtWidgets.QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        self.pathLabel = QtWidgets.QLabel()
        buttons.addWidget(self.pathLabel)
        layout.addLayout(buttons)

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.table = QtWidgets.QTableWidget()
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegate(SignalComboDelegate(self._signalsForColumn, self.table))
        self.delegateDefault = QtWidgets.QStyledItemDelegate(self.table)
        splitter.addWidget(self.table)

        side = QtWidgets.QWidget()
        sideLayout = QtWidgets.QVBoxLayout(side)
        sideLayout.setContentsMargins(0, 0, 0, 0)
        sideLayout.addWidget(QtWidgets.QLabel('<b>Signals in the current case</b>'))
        kindLayout = QtWidgets.QHBoxLayout()
        self.emtRadio = QtWidgets.QRadioButton('EMT')
        self.rmsRadio = QtWidgets.QRadioButton('RMS')
        self.emtRadio.setChecked(True)
        self.emtRadio.toggled.connect(self.refreshSignalList)
        kindLayout.addWidget(self.emtRadio)
        kindLayout.addWidget(self.rmsRadio)
        kindLayout.addStretch()
        sideLayout.addLayout(kindLayout)
        self.filterEdit = QtWidgets.QLineEdit()
        self.filterEdit.setPlaceholderText('Filter, e.g. MTB\\ or pos_')
        self.filterEdit.textChanged.connect(self.refreshSignalList)
        sideLayout.addWidget(self.filterEdit)
        self.signalList = QtWidgets.QListWidget()
        sideLayout.addWidget(self.signalList)
        addButton = QtWidgets.QPushButton('Add ticked to selected figure')
        addButton.setToolTip('Fill the empty signal slots (max. 3) of the selected figure. The equivalent EMT/RMS signal is added if it is known from the other figures.')
        addButton.clicked.connect(self.addCheckedToSelected)
        sideLayout.addWidget(addButton)
        newButton = QtWidgets.QPushButton('New figure from ticked')
        newButton.clicked.connect(self.newFigureFromChecked)
        sideLayout.addWidget(newButton)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    # --- Data ---------------------------------------------------------------
    def load(self, path: str) -> None:
        self.path = path
        self.pathLabel.setText(path)
        df = readFigureSetupDf(path) if os.path.isfile(path) else pd.DataFrame(columns=FIGURE_SETUP_COLUMNS)
        self.columns = list(df.columns)
        self.table.clear()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setRowCount(len(df))
        for r, row in enumerate(df.itertuples(index=False)):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(value)))
        for c, col in enumerate(self.columns):
            if not ('_signal_' in col):
                self.table.setItemDelegateForColumn(c, self.delegateDefault)
        self.table.resizeColumnsToContents()

    def toDataFrame(self) -> pd.DataFrame:
        data = [[(self.table.item(r, c).text().strip() if self.table.item(r, c) else '') for c in range(len(self.columns))]
                for r in range(self.table.rowCount())]
        return pd.DataFrame(data, columns=self.columns)

    def setAvailableSignals(self, emt: List[str], rms: List[str]) -> None:
        self.availableSignals = {EMT: sorted(set(emt), key=str.lower), RMS: sorted(set(rms), key=str.lower)}
        self.refreshSignalList()

    def _signalsForColumn(self, column: int) -> List[str]:
        name = self.columns[column] if column < len(self.columns) else ''
        return self.availableSignals[EMT] if name.startswith('emt_') else self.availableSignals[RMS] if name.startswith('rms_') else []

    def refreshSignalList(self) -> None:
        kind = EMT if self.emtRadio.isChecked() else RMS
        text = self.filterEdit.text().lower()
        self.signalList.clear()
        for signal in self.availableSignals[kind]:
            if text in signal.lower():
                item = QtWidgets.QListWidgetItem(signal)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.signalList.addItem(item)

    def _checkedSignals(self) -> List[str]:
        return [self.signalList.item(i).text() for i in range(self.signalList.count())
                if self.signalList.item(i).checkState() == Qt.Checked]

    def _pairs(self) -> Dict[str, str]:
        '''
        EMT <-> RMS signal pairs from the figures, i.e. emt_signal_n and rms_signal_n of the same row
        '''
        df = self.toDataFrame()
        pairs = {}
        for _, row in df.iterrows():
            for i in range(1, 4):
                emt, rms = row.get(f'emt_signal_{i}', ''), row.get(f'rms_signal_{i}', '')
                if emt and rms:
                    pairs.setdefault(emt, rms)
                    pairs.setdefault(rms, emt)
        return pairs

    def _setCell(self, row: int, column: str, value: str) -> None:
        self.table.setItem(row, self.columns.index(column), QtWidgets.QTableWidgetItem(value))

    def _cell(self, row: int, column: str) -> str:
        item = self.table.item(row, self.columns.index(column))
        return item.text().strip() if item else ''

    def _fillRow(self, row: int, signals: List[str], kind: str) -> List[str]:
        pairs = self._pairs()
        prefix, other = ('emt', 'rms') if kind == EMT else ('rms', 'emt')
        skipped = []
        for signal in signals:
            slot = next((i for i in range(1, 4) if not self._cell(row, f'{prefix}_signal_{i}')), None)
            if slot is None:
                skipped.append(signal)
                continue
            self._setCell(row, f'{prefix}_signal_{slot}', signal)
            if signal in pairs and not self._cell(row, f'{other}_signal_{slot}'):
                self._setCell(row, f'{other}_signal_{slot}', pairs[signal])
        return skipped

    # --- Actions ------------------------------------------------------------
    def addRow(self) -> int:
        df = self.toDataFrame()
        numbers = pd.to_numeric(df['figure'], errors='coerce') if 'figure' in df else pd.Series(dtype=float)
        row = self.table.rowCount()
        self.table.insertRow(row)
        defaults = {'figure': str(int(numbers.max()) + 1 if numbers.notna().any() else 1),
                    'down_sampling_method': 'gradient', 'gradient_threshold': '0.5'}
        for c, col in enumerate(self.columns):
            self.table.setItem(row, c, QtWidgets.QTableWidgetItem(defaults.get(col, '')))
        self.table.selectRow(row)
        return row

    def deleteRows(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def moveRow(self, step: int) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if len(rows) != 1:
            return
        row, target = rows[0], rows[0] + step
        if not 0 <= target < self.table.rowCount():
            return
        for c in range(self.table.columnCount()):
            a, b = self.table.takeItem(row, c), self.table.takeItem(target, c)
            self.table.setItem(row, c, b)
            self.table.setItem(target, c, a)
        self.table.selectRow(target)

    def addCheckedToSelected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        signals = self._checkedSignals()
        if len(rows) != 1 or not signals:
            QtWidgets.QMessageBox.information(self, 'Figure setup', 'Select one figure row and tick one or more signals.')
            return
        skipped = self._fillRow(rows[0], signals, EMT if self.emtRadio.isChecked() else RMS)
        if skipped:
            QtWidgets.QMessageBox.warning(self, 'Figure setup', 'A figure has max. 3 signals per type. Not added:\n' + '\n'.join(skipped))

    def newFigureFromChecked(self) -> None:
        signals = self._checkedSignals()
        if not signals:
            QtWidgets.QMessageBox.information(self, 'Figure setup', 'Tick one or more signals.')
            return
        kind = EMT if self.emtRadio.isChecked() else RMS
        for start in range(0, len(signals), 3):
            row = self.addRow()
            self._setCell(row, 'title', leaf(signals[start]).split(':')[-1])
            self._fillRow(row, signals[start:start + 3], kind)

    def revert(self) -> None:
        self.load(self.path)

    def validate(self, df: pd.DataFrame) -> List[str]:
        errors = []
        for i, row in df.iterrows():
            label = f'Row {i + 1} ({row.get("title", "")})'
            try:
                int(row['figure'])
            except ValueError:
                errors.append(f'{label}: figure must be an integer')
            try:
                DownSamplingMethod.from_string(row['down_sampling_method'])
            except ValueError:
                errors.append(f'{label}: down_sampling_method must be one of {[m.name.lower() for m in DownSamplingMethod]}')
            try:
                float(row['gradient_threshold'])
            except ValueError:
                errors.append(f'{label}: gradient_threshold must be a number')
            for col in ('include_in_case', 'exclude_in_case'):
                if any(not v.strip().isdigit() for v in str(row[col]).split(',') if v.strip()):
                    errors.append(f'{label}: {col} must be a comma separated list of case ranks')
            if not any(row[f'{k}_signal_{n}'] for k in ('emt', 'rms') for n in range(1, 4)):
                errors.append(f'{label}: no signals')
        return errors

    def saveAndApply(self) -> None:
        df = self.toDataFrame()
        errors = self.validate(df)
        if errors:
            QtWidgets.QMessageBox.warning(self, 'Figure setup', 'Not saved:\n' + '\n'.join(errors[:20]))
            return
        if not self._backupDone and os.path.isfile(self.path):
            with open(self.path, 'rb') as src, open(self.path + '.bak', 'wb') as dst:
                dst.write(src.read())
            self._backupDone = True
        writeFigureSetupDf(df, self.path)
        self.applied.emit()


#-----------------------------------------------------------------------------#
# Main window
#-----------------------------------------------------------------------------#

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, configPath: str) -> None:
        super().__init__()
        self.setWindowTitle(f'MTBViewer {__version__} (experimental)')
        self.resize(1600, 1000)

        self.config: Optional[ViewerConfig] = None
        self.testcases = Testcases('')
        self.results: Dict[int, List[ResultFile]] = {}
        self.figureDict: Dict[int, List[Figure]] = {-1: []}
        self.cursorList = []
        self.loader = ResultLoader()
        self.executor = ThreadPoolExecutor(max_workers=1)   # A single worker, as the loader cache is not thread safe
        self.bridge = Bridge()
        self.bridge.caseLoaded.connect(self._onCaseLoaded)
        self.requestId = 0
        self.currentRank: Optional[int] = None
        self.caseData: Optional[CaseData] = None
        self.panels: List[PlotPanel] = []
        self.hiddenFigures: set = set()
        self.sourceColors: Dict[str, List[str]] = {}
        self.cursorPos = {'A': 0.0, 'B': 1.0}
        self._syncingCursors = False
        self.metricTimer = QtCore.QTimer(self, singleShot=True, interval=120)
        self.metricTimer.timeout.connect(self.updateCursorTables)

        self._buildUi()
        self.openConfig(configPath)

    # --- UI -----------------------------------------------------------------
    def _buildUi(self) -> None:
        toolbar = self.addToolBar('Navigation')
        toolbar.setMovable(False)
        self.backAction = self._action(toolbar, '\u25C0 Back', self.previousCase, ['PgUp', 'Alt+Left'])
        self.caseCombo = QtWidgets.QComboBox()
        self.caseCombo.setMinimumWidth(420)
        self.caseCombo.setMaxVisibleItems(30)
        self.caseCombo.currentIndexChanged.connect(self._caseComboChanged)
        toolbar.addWidget(self.caseCombo)
        self.nextAction = self._action(toolbar, 'Next \u25B6', self.nextCase, ['PgDown', 'Alt+Right'])
        toolbar.addSeparator()
        toolbar.addWidget(QtWidgets.QLabel(' Columns: '))
        self.columnsSpin = QtWidgets.QSpinBox()
        self.columnsSpin.setRange(1, 4)
        self.columnsSpin.setValue(2)
        self.columnsSpin.valueChanged.connect(self.layoutPanels)
        toolbar.addWidget(self.columnsSpin)
        toolbar.addSeparator()
        self.linkAction = self._action(toolbar, 'Link time axes')
        self.linkAction.setCheckable(True)
        self.linkAction.setChecked(True)
        self.linkAction.toggled.connect(self.linkTimeAxes)
        self.cursorAction = self._action(toolbar, 'Cursors')
        self.cursorAction.setCheckable(True)
        self.cursorAction.setChecked(True)
        self.cursorAction.toggled.connect(self.showCursors)
        self.legendAction = self._action(toolbar, 'Legends')
        self.legendAction.setCheckable(True)
        self.legendAction.setChecked(True)
        self.legendAction.toggled.connect(lambda visible: [p.legend.setVisible(visible) for p in self.panels])
        resetAction = self._action(toolbar, 'Reset zoom', self.resetZoom, ['Ctrl+0'])

        fileMenu = self.menuBar().addMenu('&File')
        self._action(fileMenu, 'Open config.ini...', self.chooseConfig, ['Ctrl+O'])
        self._action(fileMenu, 'Reload results and setup', self.reload, ['F5'])
        fileMenu.addSeparator()
        self._action(fileMenu, 'Export case as PNG...', lambda: self.exportDialog('png'), ['Ctrl+P'])
        self._action(fileMenu, 'Export case as PDF...', lambda: self.exportDialog('pdf'))
        self._action(fileMenu, 'Export cursor tables as CSV...', lambda: self.exportDialog('csv'))
        fileMenu.addSeparator()
        self._action(fileMenu, 'Exit', self.close, ['Ctrl+Q'])
        viewMenu = self.menuBar().addMenu('&View')
        viewMenu.addAction(self.linkAction)
        viewMenu.addAction(self.cursorAction)
        viewMenu.addAction(self.legendAction)
        viewMenu.addAction(resetAction)
        self.figuresMenu = viewMenu.addMenu('Figures')
        helpMenu = self.menuBar().addMenu('&Help')
        self._action(helpMenu, 'Mouse and keyboard', self.showHelp, ['F1'])

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        plotsTab = QtWidgets.QSplitter(Qt.Vertical)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.plotContainer = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.plotContainer)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.scroll.setWidget(self.plotContainer)
        plotsTab.addWidget(self.scroll)
        self.cursorPanel = CursorPanel()
        self.cursorPanel.metricsChanged.connect(self.scheduleCursorUpdate)
        self.cursorPanel.presetSelected.connect(self.setCursors)
        self.cursorPanel.cursorsToView.connect(self.cursorsToView)
        plotsTab.addWidget(self.cursorPanel)
        plotsTab.setStretchFactor(0, 4)
        plotsTab.setStretchFactor(1, 1)
        plotsTab.setSizes([750, 250])
        self.tabs.addTab(plotsTab, 'Plots')

        self.setupEditor = FigureSetupEditor()
        self.setupEditor.applied.connect(self._figureSetupApplied)
        self.tabs.addTab(self.setupEditor, 'Figure setup')

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, 'Messages')

        self.statusLabel = QtWidgets.QLabel()
        self.statusBar().addWidget(self.statusLabel, 1)

    def _action(self, parent, text: str, slot=None, shortcuts: Optional[List[str]] = None) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        if slot is not None:
            action.triggered.connect(lambda checked=False: slot())
        if shortcuts:
            action.setShortcuts([QtGui.QKeySequence(s) for s in shortcuts])
        parent.addAction(action)
        return action

    def message(self, text: str) -> None:
        self.log.appendPlainText(text)
        if text.startswith(('ERROR', 'WARNING')):
            self.tabs.setTabText(2, 'Messages (!)')

    def showHelp(self) -> None:
        QtWidgets.QMessageBox.information(self, 'MTBViewer - mouse and keyboard', (
            'Mouse wheel: zoom x and y\n'
            'Mouse wheel over an axis: zoom only that axis\n'
            'Left drag: pan    Right drag: scale x and y independently\n'
            'Right click: menu with manual x/y ranges, auto range and export\n'
            'Click a legend entry: hide/show that trace\n'
            'Drag the A/B lines: move the cursors (all plots)\n\n'
            'PgUp / Alt+Left: previous case    PgDn / Alt+Right: next case\n'
            'Ctrl+0: reset zoom    F5: reload    Ctrl+P: export PNG'))

    # --- Config and results -------------------------------------------------
    def chooseConfig(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Open config.ini', SCRIPT_DIR, 'Config (*.ini)')
        if path:
            self.openConfig(path)

    def openConfig(self, path: str) -> None:
        try:
            self.config = ViewerConfig(path)
        except Exception as e:
            self.message(f'ERROR: {e}')
            QtWidgets.QMessageBox.critical(self, 'MTBViewer', str(e))
            return
        self.message(f'Config: {self.config.configPath}')
        self.testcases = Testcases(self.config.testcaseSheet)
        if self.testcases.error:
            self.message(f'WARNING: {self.testcases.error}')
        self.reload()

    def reload(self) -> None:
        if self.config is None:
            return
        self.loader.clear()
        self.figureDict, self.cursorList, messages = loadSetups(self.config)
        self.results, discoverMessages = discoverResults(self.config.simDataDirs)
        for m in messages + discoverMessages:
            self.message(m)
        self.setupEditor.load(self.config.figureSetupPath)
        self._assignColors()

        rank = self.currentRank
        self.caseCombo.blockSignals(True)
        self.caseCombo.clear()
        for r in self.results:
            name = self.testcases.caseName(r)
            self.caseCombo.addItem(f'{r}: {name}' if name else str(r), r)
        self.caseCombo.blockSignals(False)
        if not self.results:
            self.statusLabel.setText('No result files found. Check [Simulation data paths] in config.ini.')
            return
        index = self.caseCombo.findData(rank) if rank is not None else -1
        self.caseCombo.setCurrentIndex(max(index, 0))
        self._caseComboChanged(self.caseCombo.currentIndex())

    def _assignColors(self) -> None:
        shorthands = sorted({f.shorthand for files in self.results.values() for f in files})
        self.sourceColors = {s: [PALETTE[(3 * i + k) % len(PALETTE)] for k in range(3)] for i, s in enumerate(shorthands)}

    # --- Navigation ---------------------------------------------------------
    def previousCase(self) -> None:
        if self.caseCombo.currentIndex() > 0:
            self.caseCombo.setCurrentIndex(self.caseCombo.currentIndex() - 1)

    def nextCase(self) -> None:
        if self.caseCombo.currentIndex() < self.caseCombo.count() - 1:
            self.caseCombo.setCurrentIndex(self.caseCombo.currentIndex() + 1)

    def _caseComboChanged(self, index: int) -> None:
        if index < 0:
            return
        self.backAction.setEnabled(index > 0)
        self.nextAction.setEnabled(index < self.caseCombo.count() - 1)
        self.loadCase(self.caseCombo.itemData(index))

    def loadCase(self, rank: int) -> None:
        self.currentRank = rank
        self.requestId += 1
        requestId = self.requestId
        self.statusLabel.setText(f'Loading case {rank}...')
        QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
        future = self.executor.submit(self._loadCaseWorker, rank)

        def done(f, rid=requestId, rank=rank):
            try:
                caseData = f.result()
            except BaseException as e:
                caseData = CaseData(rank, messages=[f'ERROR: Case {rank} could not be loaded: {e!r}'])
            try:
                self.bridge.caseLoaded.emit(rid, caseData)
            except RuntimeError:
                pass    # The window has been closed

        future.add_done_callback(done)

    def _caseSignals(self, rank: int):
        figures = figuresForRank(self.figureDict, rank)
        cursors = cursorsForRank(self.cursorList, self.testcases.caseName(rank))
        return figures, cursors, requestedSignals(figures, cursors)

    def _loadCaseWorker(self, rank: int, prefetch: bool = False) -> CaseData:
        '''
        Runs in the worker thread: load the results of a case and calculate the guide curves
        '''
        caseData = CaseData(rank)
        figures, cursors, (emtNames, rmsNames) = self._caseSignals(rank)
        shown = {s for f in figures for k in (EMT, RMS) for s in figureSignals(f, k)}
        shown |= {s for c in cursors for s in c.emt_signals + c.rms_signals}
        for resultFile in self.results.get(rank, []):
            try:
                loaded = self.loader.load(resultFile, emtNames, rmsNames, self.testcases)
            except Exception as e:
                caseData.messages.append(f'ERROR: Could not load {resultFile.path}: {e}')
                continue
            if prefetch:
                continue
            caseData.loaded.append(loaded)
            missing = [m for m in loaded.missing if m in shown]
            if missing:
                caseData.messages.append(f'WARNING: {resultFile.path} ({loaded.kind}): signals not found: {", ".join(missing)}')
            if loaded.kind == EMT:
                try:
                    caseData.guides[sourceKey(loaded)] = computeGuides(loaded, self.testcases, rank)
                except Exception as e:
                    caseData.messages.append(f'WARNING: Guide curves for {resultFile.path} could not be calculated: {e!r}')
        return caseData

    def _prefetch(self, rank: int) -> None:
        def work():
            try:
                self._loadCaseWorker(rank, prefetch=True)
            except Exception:
                pass
        self.executor.submit(work)

    def _onCaseLoaded(self, requestId: int, caseData: CaseData) -> None:
        if requestId != self.requestId:
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self.caseData = caseData
        for m in caseData.messages:
            self.message(m)
        self.buildPlots()
        kinds = ', '.join(f'{l.file.shorthand} ({l.kind}, {l.file.fmt})' for l in caseData.loaded) or 'no results loaded'
        name = self.testcases.caseName(caseData.rank)
        self.statusLabel.setText(f'Case {caseData.rank}: {name}  |  {kinds}')
        self.setWindowTitle(f'MTBViewer {__version__} (experimental) - case {caseData.rank}: {name}')
        index = self.caseCombo.currentIndex()
        if index < self.caseCombo.count() - 1:
            self._prefetch(self.caseCombo.itemData(index + 1))

    # --- Plots --------------------------------------------------------------
    def buildPlots(self) -> None:
        for panel in self.panels:
            panel.setParent(None)
            panel.deleteLater()
        self.panels = []
        caseData = self.caseData
        if caseData is None:
            return
        figures, cursors, _ = self._caseSignals(caseData.rank)
        self._buildFiguresMenu(figures)

        tMin, tMax = np.inf, -np.inf
        for figure in figures:
            if figure.title in self.hiddenFigures:
                continue
            panel = PlotPanel(figure)
            for loaded in caseData.loaded:
                source = sourceKey(loaded)
                colors = self.sourceColors.get(loaded.file.shorthand, PALETTE[:3])
                t = loaded.time()
                for i, signal in enumerate(figureSignals(figure, loaded.kind)):
                    if loaded.has(signal):
                        panel.addCurve(source, f'{loaded.file.shorthand}:{leaf(signal)}', t, loaded.data[signal].to_numpy(dtype=float), colors[i % 3])
                        tMin, tMax = min(tMin, t[0]), max(tMax, t[-1])
                guidePrefix = 'guide' if len(caseData.guides) <= 1 else f'guide({loaded.file.group})'
                for i, guide in enumerate(g for g in caseData.guides.get(source, []) if g.figureTitle == figure.title):
                    panel.addCurve(GUIDE_SOURCE, f'{guidePrefix}:{guide.name}', guide.time, guide.values, GUIDE_COLORS[i % len(GUIDE_COLORS)], dashed=True)
            panel.finishLegend()
            panel.legend.setVisible(self.legendAction.isChecked())
            for line in panel.cursorLines.values():
                line.sigPositionChanged.connect(self._cursorMoved)
            panel.visibilityChanged.connect(self.scheduleCursorUpdate)
            self.panels.append(panel)

        if not np.isfinite(tMin):
            tMin, tMax = 0.0, 1.0
        presets = cursorPresetIntervals(cursors)
        self.cursorPanel.setPresets(presets, tMax)
        if presets:
            first = presets[0]
            self.setCursors(first[0], first[1] if len(first) == 2 else tMax)
        else:
            self.setCursors(max(tMin, 0.0), tMax)
        self.layoutPanels()
        self.linkTimeAxes(self.linkAction.isChecked())
        self.showCursors(self.cursorAction.isChecked())
        self.resetZoom()
        if not self.panels:
            self.message(f'WARNING: No figures to show for case {caseData.rank}.')
        self._updateAvailableSignals()

    def _buildFiguresMenu(self, figures: List[Figure]) -> None:
        self.figuresMenu.clear()
        self._action(self.figuresMenu, 'Show all', lambda: self._setHiddenFigures(set()))
        self.figuresMenu.addSeparator()
        for figure in figures:
            action = self._action(self.figuresMenu, f'{figure.title} [{figure.units}]')
            action.setCheckable(True)
            action.setChecked(figure.title not in self.hiddenFigures)
            action.toggled.connect(lambda checked, t=figure.title: self._toggleFigure(t, checked))

    def _toggleFigure(self, title: str, visible: bool) -> None:
        hidden = set(self.hiddenFigures)
        hidden.discard(title) if visible else hidden.add(title)
        self._setHiddenFigures(hidden)

    def _setHiddenFigures(self, hidden: set) -> None:
        self.hiddenFigures = hidden
        self.buildPlots()

    def layoutPanels(self) -> None:
        while self.grid.count():
            self.grid.takeAt(0)
        columns = self.columnsSpin.value()
        for i, panel in enumerate(self.panels):
            self.grid.addWidget(panel, i // columns, i % columns)
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def linkTimeAxes(self, linked: bool) -> None:
        for i, panel in enumerate(self.panels):
            panel.plotItem.setXLink(self.panels[0].plotItem if linked and i > 0 else None)

    def resetZoom(self) -> None:
        for panel in self.panels:
            panel.plotItem.enableAutoRange()

    def showCursors(self, visible: bool) -> None:
        for panel in self.panels:
            panel.setCursorsVisible(visible)
        self.cursorPanel.setVisible(visible)
        if visible:
            self.scheduleCursorUpdate()

    # --- Cursors ------------------------------------------------------------
    def setCursors(self, tA: float, tB: float) -> None:
        self.cursorPos = {'A': float(tA), 'B': float(tB)}
        self._syncingCursors = True
        for panel in self.panels:
            for name, line in panel.cursorLines.items():
                line.setValue(self.cursorPos[name])
        self._syncingCursors = False
        self.cursorPanel.setPositions(self.cursorPos['A'], self.cursorPos['B'])
        self.scheduleCursorUpdate()

    def _cursorMoved(self, line: pg.InfiniteLine) -> None:
        if self._syncingCursors:
            return
        self._syncingCursors = True
        self.cursorPos[line.cursorName] = float(line.value())
        for panel in self.panels:
            other = panel.cursorLines[line.cursorName]
            if other is not line:
                other.setValue(self.cursorPos[line.cursorName])
        self._syncingCursors = False
        self.cursorPanel.setPositions(self.cursorPos['A'], self.cursorPos['B'])
        self.scheduleCursorUpdate()

    def cursorsToView(self) -> None:
        if not self.panels:
            return
        x0, x1 = self.panels[0].plotItem.viewRange()[0]
        self.setCursors(x0 + 0.25 * (x1 - x0), x0 + 0.75 * (x1 - x0))

    def scheduleCursorUpdate(self) -> None:
        if self.cursorAction.isChecked():
            self.metricTimer.start()

    def signalMetricsTable(self) -> pd.DataFrame:
        options = self.cursorPanel.selectedMetrics()
        rows = []
        tA, tB = self.cursorPos['A'], self.cursorPos['B']
        for panel in self.panels:
            for item in panel.visibleCurves():
                values = signalMetrics(item.fullT, item.fullY, tA, tB, options)
                rows.append({'Figure': panel.figure.title, 'Trace': item.signalName,
                             **{SIGNAL_METRIC_LABELS[o]: values[o] for o in options}})
        return pd.DataFrame(rows, columns=['Figure', 'Trace'] + [SIGNAL_METRIC_LABELS[o] for o in options])

    def caseMetricsTable(self) -> pd.DataFrame:
        if self.caseData is None:
            return pd.DataFrame()
        cursors = cursorsForRank(self.cursorList, self.testcases.caseName(self.caseData.rank))
        return caseCursorMetrics(cursors, self.caseData.loaded, self.testcases, self.caseData.rank,
                                 self.cursorPos['A'], self.cursorPos['B'])

    def updateCursorTables(self) -> None:
        signalDf = self.signalMetricsTable()
        colors = []
        for panel in self.panels:
            for item in panel.visibleCurves():
                colors.append(item.opts['pen'].color().name())
        CursorPanel.fillTable(self.cursorPanel.signalTable, signalDf, colors)
        caseDf = self.caseMetricsTable()
        if caseDf.empty:
            caseDf = pd.DataFrame({'Info': ['No cursors defined in cursorSetup.csv for this case']})
        CursorPanel.fillTable(self.cursorPanel.caseTable, caseDf)

    # --- Figure setup -------------------------------------------------------
    def _updateAvailableSignals(self) -> None:
        emt, rms = [], []
        for loaded in (self.caseData.loaded if self.caseData else []):
            (emt if loaded.kind == EMT else rms).extend(loaded.available)
        self.setupEditor.setAvailableSignals(emt, rms)

    def _figureSetupApplied(self) -> None:
        self.message(f'Saved {self.config.figureSetupPath}')
        self.figureDict, self.cursorList, messages = loadSetups(self.config)
        for m in messages:
            self.message(m)
        self.loader.clear()
        self.tabs.setCurrentIndex(0)
        if self.currentRank is not None:
            self.loadCase(self.currentRank)

    # --- Export -------------------------------------------------------------
    def _defaultExportName(self, ext: str) -> str:
        name = self.testcases.caseName(self.currentRank) if self.currentRank is not None else ''
        base = f'{self.currentRank}_{name}' if name else f'{self.currentRank}'
        folder = self.config.baseDir if self.config else SCRIPT_DIR
        return os.path.join(folder, f'{base}.{ext}')

    def exportDialog(self, kind: str) -> None:
        filters = {'png': 'PNG image (*.png)', 'pdf': 'PDF (*.pdf)', 'csv': 'CSV (*.csv)'}
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export', self._defaultExportName(kind), filters[kind])
        if not path:
            return
        {'png': self.exportPng, 'pdf': self.exportPdf, 'csv': self.exportCsv}[kind](path)
        self.message(f'Exported {path}')

    def _prepareGrab(self) -> None:
        '''
        Make sure the plot layout is up to date (and not squeezed into the scroll area) before grabbing it
        '''
        QtWidgets.QApplication.processEvents()
        self.grid.activate()
        hint = self.plotContainer.minimumSizeHint()
        if self.plotContainer.height() < hint.height():
            self.plotContainer.resize(self.plotContainer.width(), hint.height())
        QtWidgets.QApplication.processEvents()

    def exportPng(self, path: str) -> None:
        self._prepareGrab()
        self.plotContainer.grab().save(path)

    def exportPdf(self, path: str) -> None:
        self._prepareGrab()
        writer = QtGui.QPdfWriter(path)
        writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.A4))
        writer.setPageOrientation(QtGui.QPageLayout.Landscape)
        writer.setResolution(150)
        painter = QtGui.QPainter(writer)
        page = painter.viewport()
        columns = self.columnsSpin.value()
        rowsPerPage = 2
        title = f'Case {self.currentRank}: {self.testcases.caseName(self.currentRank)}'
        header = 40
        cellW, cellH = page.width() / columns, (page.height() - header) / rowsPerPage
        perPage = columns * rowsPerPage
        for i, panel in enumerate(self.panels):
            if i and i % perPage == 0:
                writer.newPage()
            if i % perPage == 0:
                painter.drawText(QtCore.QRectF(0, 0, page.width(), header), Qt.AlignLeft | Qt.AlignVCenter, title)
            pixmap = panel.grab()
            slot = i % perPage
            target = QtCore.QRectF((slot % columns) * cellW, header + (slot // columns) * cellH, cellW, cellH)
            scaled = pixmap.size().scaled(target.size().toSize(), Qt.KeepAspectRatio)
            painter.drawPixmap(QtCore.QRectF(target.topLeft(), QtCore.QSizeF(scaled)), pixmap, QtCore.QRectF(pixmap.rect()))
        painter.end()

    def exportCsv(self, path: str) -> None:
        base, _ = os.path.splitext(path)
        self.signalMetricsTable().to_csv(f'{base}.csv', sep=';', index=False)
        caseDf = self.caseMetricsTable()
        if not caseDf.empty:
            caseDf.to_csv(f'{base}_case_cursors.csv', sep=';', index=False)

    def closeEvent(self, event) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)


def main() -> None:
    parser = argparse.ArgumentParser(prog='MTBViewer', description='Interactive viewer for MTB EMT and RMS results (experimental)')
    parser.add_argument('-c', '--config', default=os.path.join(SCRIPT_DIR, 'config.ini'), help='the plotter config.ini (default: config.ini next to MTBViewer.py)')
    parser.add_argument('-r', '--rank', type=int, help='the case rank to show first')
    parser.add_argument('--export-png', metavar='FILE', help='export the case given by --rank as PNG and exit')
    parser.add_argument('--export-pdf', metavar='FILE', help='export the case given by --rank as PDF and exit')
    parser.add_argument('-v', '--version', action='version', version=f'%(prog)s {__version__}')
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('MTBViewer')
    window = MainWindow(args.config)
    if args.rank is not None:
        index = window.caseCombo.findData(args.rank)
        if index < 0:
            print(f'Case {args.rank} has no results.')
        else:
            window.caseCombo.setCurrentIndex(index)

    if args.export_png or args.export_pdf:
        window.resize(1800, 1400)
        window.show()

        def exportWhenLoaded(requestId, caseData):
            if requestId != window.requestId:
                return
            QtCore.QTimer.singleShot(300, doExport)

        def doExport():
            window.updateCursorTables()
            if args.export_png:
                window.exportPng(args.export_png)
                print(f'Exported {args.export_png}')
            if args.export_pdf:
                window.exportPdf(args.export_pdf)
                print(f'Exported {args.export_pdf}')
            for line in window.log.toPlainText().splitlines():
                if line.startswith(('ERROR', 'WARNING')):
                    print(line)
            app.quit()

        window.bridge.caseLoaded.connect(exportWhenLoaded)
        sys.exit(app.exec())

    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
