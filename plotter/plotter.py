'''
Minimal script to plot simulation results from PSCAD and PowerFactory.
'''
from __future__ import annotations
from os import listdir, makedirs
from os.path import join, split, exists
import re
import pandas as pd
from plotly.subplots import make_subplots  # type: ignore
import plotly.graph_objects as go  # type: ignore
from typing import List, Dict, Union, Tuple, Set
import sampling_functions
from down_sampling_method import DownSamplingMethod
from threading import Thread, Lock
import time
import sys
from math import ceil
from collections import defaultdict
from cursor_image_logic import addCursors, setupPlotLayoutCursors
from read_configs import ReadConfig, readFigureSetup, readCursorSetup
from Figure import Figure
from Result import ResultType, Result
from Case import Case
from Cursor import Cursor
from read_and_write_functions import loadEMT
from process_psout import getAllSignalnames, getCaseSignalnames, getSignals

try:
    LOG_FILE = open('plotter.log', 'w')
except:
    print('Failed to open log file. Logging to file disabled.')
    LOG_FILE = None  # type: ignore

gLock = Lock()


def print(*args):  # type: ignore
    '''
    Overwrites the print function to also write to a log file.
    '''
    gLock.acquire()
    outputString = ''.join(map(str, args)) + '\n'  # type: ignore
    sys.stdout.write(outputString)
    if LOG_FILE:
        try:
            LOG_FILE.write(outputString)
            LOG_FILE.flush()
        except:
            pass
    gLock.release()


def idFile(filePath: str) -> Tuple[
    Union[ResultType, None], Union[int, None], Union[str, None], Union[str, None], Union[str, None]]:
    '''
    Identifies the type (EMT or RMS), root and case id of a given file. If the file is not recognized, a none tuple is returned.
    '''
    path, fileName = split(filePath)
    match = re.match(r'^(\w+?)_([0-9]+).(inf|csv|psout|zip|gz|bz2|xz)$', fileName.lower())
    if match:
        rank = int(match.group(2))
        projectName = match.group(1)
        bulkName = join(path, match.group(1))
        fullpath = filePath
        if match.group(3) == 'psout':
            fileType = ResultType.EMT_PSOUT
            return (fileType, rank, projectName, bulkName, fullpath)
        elif match.group(3) == 'zip' or match.group(3) == 'gz' or match.group(3) == 'bz2' or match.group(3) == 'xz':
            fileType = ResultType.EMT_ZIP
            return (fileType, rank, projectName, bulkName, fullpath)
        else:
            with open(filePath, 'r') as file:
                firstLine = file.readline()
                if match.group(3) == 'inf' and firstLine.startswith('PGB(1)'):
                    fileType = ResultType.EMT_INF
                    return (fileType, rank, projectName, bulkName, fullpath)
                elif match.group(3) == 'csv' and firstLine.startswith('time;'):
                    fileType = ResultType.EMT_CSV
                    return (fileType, rank, projectName, bulkName, fullpath)
                elif match.group(3) == 'csv':
                    secondLine = file.readline()
                    if secondLine.startswith(r'"b:tnow in s"'):
                        fileType = ResultType.RMS
                        return (fileType, rank, projectName, bulkName, fullpath)
                
    return (None, None, None, None, None)


def mapResultFiles(config: ReadConfig) -> Dict[int, List[Result]]:
    '''
    Goes through all files in the given directories and maps them to a dictionary of cases.
    '''
    files: List[Tuple[str, str]] = list()
    for dir_ in config.simDataDirs:
        for file_ in listdir(dir_[1]):
            files.append((dir_[0], join(dir_[1], file_)))
    
    results: Dict[int, List[Result]] = dict()

    for file in files:
        group = file[0]
        fullpath = file[1]
        typ, rank, projectName, bulkName, fullpath = idFile(fullpath)

        if typ is None:
            continue
        assert rank is not None
        assert projectName is not None
        assert bulkName is not None
        assert fullpath is not None

        newResult = Result(typ, rank, projectName, bulkName, fullpath, group)

        if rank in results.keys():
            results[rank].append(newResult)
        else:
            results[rank] = [newResult]

    return results

def colorMap(results: Dict[int, List[Result]]) -> Dict[str, List[str]]:
    '''
    Select colors for the given projects. Return a dictionary with the project name as key and a list of colors as value.
    '''
    colors = ['#e6194B', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
              '#fabed4', '#469990', '#dcbeff', '#9A6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1',
              '#000075', '#a9a9a9', '#000000']

    projects: Set[str] = set()

    for rank in results.keys():
        for result in results[rank]:
            projects.add(result.shorthand)

    cMap: Dict[str, List[str]] = dict()

    if len(list(projects)) > 2:
        i = 0
        for p in list(projects):
            cMap[p] = [colors[i % len(colors)]] * 3
            i += 1
        return cMap
    else:
        i = 0
        for p in list(projects):
            cMap[p] = colors[i:i + 3]
            i += 3
    return cMap


def addResults(plots: List[go.Figure],
               typ: ResultType,
               data: pd.DataFrame,
               figures: List[Figure],
               resultName: str,
               file: str,  # Only for error messages
               colors: Dict[str, List[str]],
               nColumns: int,
               pfFlatTIme: float,
               pscadInitTime: float) -> None:
    '''
    Add result to plot.
    '''

    assert nColumns > 0

    if nColumns > 3: # Max figure columns
        plotlyFigure = plots[0]
    else:
        assert len(plots) == len(figures)

    rowPos = 1
    colPos = 1
    fi = -1
    for figure in figures:
        fi += 1

        if nColumns in (1,2,3):
            plotlyFigure = plots[fi]
        else:
            rowPos = (fi // nColumns) + 1
            colPos = (fi % nColumns) + 1

        downsampling_method = figure.down_sampling_method
        traces = 0
        for sig in range(1, 4):
            signalKey = typ.name.lower().split('_')[0]
            rawSigName: str = getattr(figure, f'{signalKey}_signal_{sig}')

            if typ == ResultType.RMS:
                while rawSigName.startswith('#'):
                    rawSigName = rawSigName[1:]
                splitSigName = rawSigName.split('\\')

                if len(splitSigName) == 2:
                    sigColumn = ('##' + splitSigName[0], splitSigName[1])
                else:
                    sigColumn = rawSigName
            elif typ == ResultType.EMT_INF or typ == ResultType.EMT_CSV or typ == ResultType.EMT_ZIP:
                # uses only the signal name - last part of the hierarchical signal name
                rawSigName = rawSigName.split('\\')[-1]
                sigColumn = rawSigName
            elif typ == ResultType.EMT_PSOUT:
                # uses the full hierarchical signal name
                sigColumn = rawSigName
            else:
                print(f'File type: {typ} unknown')
                

            displayName = f'{resultName}:{rawSigName.split(" ")[0]}'

            timeColName = 'time' if typ == ResultType.EMT_INF or typ == ResultType.EMT_PSOUT or typ == ResultType.EMT_CSV  or typ == ResultType.EMT_ZIP else data.columns[0]
            timeoffset = pfFlatTIme if typ == ResultType.RMS else pscadInitTime

            if sigColumn in data.columns:
                x_value = data[timeColName] - timeoffset  # type: ignore
                y_value = data[sigColumn]  # type: ignore
                if downsampling_method == DownSamplingMethod.GRADIENT:
                    x_value, y_value = sampling_functions.downsample_based_on_gradient(x_value, y_value,
                                                                                       figure.gradient_threshold)  # type: ignore
                elif downsampling_method == DownSamplingMethod.AMOUNT:
                    x_value, y_value = sampling_functions.down_sample(x_value, y_value)  # type: ignore

                add_scatterplot_for_result(colPos, colors, displayName, nColumns, plotlyFigure, resultName, rowPos,
                                           traces, x_value, y_value)

                # plot_cursor_functions.add_annotations(x_value, y_value, plotlyFigure)
                traces += 1
            elif sigColumn != '':
                print(f'Signal "{rawSigName}" not recognized in resultfile: {file}')
                add_scatterplot_for_result(colPos, colors, f'{displayName} (Unknown)', nColumns, plotlyFigure, resultName, rowPos,
                                           traces, None, None)
                traces += 1

        update_y_and_x_axis(colPos, figure, nColumns, plotlyFigure, rowPos)


def update_y_and_x_axis(colPos, figure, nColumns, plotlyFigure, rowPos):
    if nColumns in (1,2,3):
        yaxisTitle = f'[{figure.units}]'
    else:
        yaxisTitle = f'{figure.title}[{figure.units}]'
    if nColumns in (1,2,3):
        plotlyFigure.update_xaxes(  # type: ignore
            title_text='Time[s]'
        )
        plotlyFigure.update_yaxes(  # type: ignore
            title_text=yaxisTitle
        )
    else:
        plotlyFigure.update_xaxes(  # type: ignore
            title_text='Time[s]',
            row=rowPos, col=colPos
        )
        plotlyFigure.update_yaxes(  # type: ignore
            title_text=yaxisTitle,
            row=rowPos, col=colPos
        )


def add_scatterplot_for_result(colPos, colors, displayName, nColumns, plotlyFigure, resultName, rowPos, traces, x_value,
                               y_value):
    if nColumns in (1,2,3):
        plotlyFigure.add_trace(  # type: ignore
            go.Scatter(
                x=x_value,
                y=y_value,
                #line_color=colors[resultName][traces],
                name=displayName,
                legendgroup=displayName,
                showlegend=True
            )
        )
    else:
        plotlyFigure.add_trace(  # type: ignore
            go.Scatter(
                x=x_value,
                y=y_value,
                line_color=colors[resultName][traces],
                name=displayName,
                legendgroup=resultName,
                showlegend=True
            ),
            row=rowPos, col=colPos
        )


def drawPlot(rank: int,
             resultDict: Dict[int, List[Result]],
             figureDict: Dict[int, List[Figure]],
             caseDict: Dict[int, str],
             colorMap: Dict[str, List[str]],
             cursorDict: List[Cursor],
             config: ReadConfig,
             emtRankSignalnamesList: List):
    '''
    Draws plots for html and static image export.    
    '''

    print(f'Drawing plot for rank {rank}.')

    resultList = resultDict.get(rank, [])
    rankList = list(resultDict.keys())
    rankList.sort()
    figureList = figureDict[rank]
    ranksCursor = [i for i in cursorDict if i.id == rank]

    if resultList == [] or figureList == []:
        return

    figurePath = join(config.resultsDir, str(rank))

    htmlPlots: List[go.Figure] = list()
    imagePlots: List[go.Figure] = list()
    htmlPlotsCursors: List[go.Figure] = list()
    imagePlotsCursors: List[go.Figure] = list()

    columnNr = setupPlotLayout(caseDict, config, figureList, htmlPlots, imagePlots, rank)
    if len(ranksCursor) > 0:
        setupPlotLayoutCursors(config, ranksCursor, htmlPlotsCursors, imagePlotsCursors)
    for result in resultList:
        print(result.typ)
        if result.typ == ResultType.RMS:
            resultData: pd.DataFrame = pd.read_csv(result.fullpath, sep=';', decimal=',', header=[0, 1])  # type: ignore
        elif result.typ == ResultType.EMT_INF:
            resultData: pd.DataFrame = loadEMT(result.fullpath)
        elif result.typ == ResultType.EMT_PSOUT:
            resultData: pd.DataFrame = getSignals(result.fullpath, emtRankSignalnamesList)
        elif result.typ == ResultType.EMT_CSV or result.typ == ResultType.EMT_ZIP:
            resultData: pd.DataFrame = pd.read_csv(result.fullpath, sep=';', decimal=',')  # type: ignore
        else:
            continue
        if config.genHTML:
            addResults(htmlPlots, result.typ, resultData, figureList, result.shorthand, result.fullpath, colorMap,
                       config.htmlColumns, config.pfFlatTIme, config.pscadInitTime)
        if config.genImage:
            addResults(imagePlots, result.typ, resultData, figureList, result.shorthand, result.fullpath, colorMap,
                       config.imageColumns, config.pfFlatTIme, config.pscadInitTime)

    if config.genHTML:
        addCursors(htmlPlotsCursors, resultList, cursorDict, config.pfFlatTIme, config.pscadInitTime,
                   rank, config.htmlCursorColumns, emtRankSignalnamesList)
        create_html(htmlPlots, htmlPlotsCursors, figurePath, caseDict[rank] if caseDict is not None else "", rank, config, rankList)
        print(f'Exported plot for rank {rank} to {figurePath}.html')

    if config.genImage:
        # Cursor plots are not currently supported for image export and commented out
        # addCursors(imagePlotsCursors, resultList, cursorDict, config.pfFlatTIme, config.pscadInitTime,
        #           rank, config.imageCursorColumns)
        create_image_plots(columnNr, config, figureList, figurePath, imagePlots)
        # create_cursor_plots(config.htmlCursorColumns, config, figurePath, imagePlotsCursors, ranksCursor)
        print(f'Exported plot for rank {rank} to {figurePath}.{config.imageFormat}')

    print(f'Plot for rank {rank} done.')


def create_image_plots(columnNr, config, figureList, figurePath, imagePlots):
    if columnNr in (1,2,3):
        # Combine all figures into a single plot, same as for nColumns > 1 but no grid needed
        combined_plot = make_subplots(rows=len(imagePlots), cols=1,
                                      subplot_titles=[fig.layout.title.text for fig in imagePlots])

        for i, plot in enumerate(imagePlots):
            for trace in plot['data']:  # Add each trace to the combined plot
                combined_plot.add_trace(trace, row=i + 1, col=1)

            # Copy over the x and y axis titles from the original plot
            combined_plot.update_xaxes(title_text=plot.layout.xaxis.title.text, row=i + 1, col=1)
            combined_plot.update_yaxes(title_text=plot.layout.yaxis.title.text, row=i + 1, col=1)

        # Explicitly set the width and height in the layout
        combined_plot.update_layout(
            height=500 * len(imagePlots),  # Height adjusted based on number of plots
            width=2000,  # Set the desired width here, adjust as needed
            showlegend=True,
        )

        # Save the combined plot as a single image
        combined_plot.write_image(f'{figurePath}.{config.imageFormat}', height=500 * len(imagePlots), width=2000)

    else:
        # Combine all figures into a grid when nColumns > 1
        imagePlots[0].update_layout(
            height=500 * ceil(len(figureList) / columnNr),
            width=500 * config.imageColumns,  # Adjust width based on column number
            showlegend=True,
        )
        imagePlots[0].write_image(f'{figurePath}.{config.imageFormat}', height=500 * ceil(len(figureList) / columnNr),
                                  width=500 * config.imageColumns)  # type: ignore


def create_cursor_plots(columnNr, config, figurePath, imagePlotsCursors, ranksCursor):
    # Handle the cursor plots (which are tables)
    if len(ranksCursor) > 0:
        cursor_path = figurePath + "_cursor"
        if columnNr in (1,2,3):
            # Create a combined plot for tables using the 'table' spec type
            combined_cursor_plot = make_subplots(rows=len(imagePlotsCursors), cols=1,
                                                 specs=[[{"type": "table"}]] * len(imagePlotsCursors),
                                                 # 'table' type for each subplot
                                                 subplot_titles=[fig.layout.title.text for fig in imagePlotsCursors])
            for i, cursor_plot in enumerate(imagePlotsCursors):
                for trace in cursor_plot['data']:  # Add each trace (table) to the combined cursor plot
                    combined_cursor_plot.add_trace(trace, row=i + 1, col=1)

            # Explicitly set width and height in the layout for table plots
            combined_cursor_plot.update_layout(
                height=500 * len(imagePlotsCursors),
                width=600,  # Set the desired width for tables
                showlegend=False,
            )

            # Save the combined table plot as a single image
            combined_cursor_plot.write_image(f'{cursor_path}.{config.imageFormat}', height=500 * len(imagePlotsCursors),
                                             width=600)
        else:
            imagePlotsCursors[0].update_layout(
                height=500 * ceil(len(ranksCursor) / columnNr),
                width=500 * config.imageColumns,  # Adjust width for multiple columns
                showlegend=False,
            )
            imagePlotsCursors[0].write_image(f'{cursor_path}.{config.imageFormat}',
                                             height=500 * ceil(len(ranksCursor) / columnNr),
                                             width=500 * config.imageColumns)


def setupPlotLayout(caseDict, config, figureList, htmlPlots, imagePlots, rank):
    lst: List[Tuple[int, List[go.Figure]]] = []
    if config.genHTML:
        lst.append((config.htmlColumns, htmlPlots))
    if config.genImage:
        lst.append((config.imageColumns, imagePlots))

    for columnNr, plotList in lst:
        if columnNr in (1,2,3):
            for fig in figureList:
                # Create a direct Figure instead of subplots when there's only 1 column
                plotList.append(go.Figure())  # Normal figure, no subplots
                plotList[-1].update_layout(
                    title=fig.title,  # Add the figure title directly
                    height=500,  # Set height for the plot
                    legend=dict(
                        orientation="h",
                        yanchor="top",
                        y=1.22,
                        xanchor="left",
                        x=0.12,
                    )
                )
        elif columnNr > 1:
            plotList.append(make_subplots(rows=ceil(len(figureList) / columnNr), cols=columnNr))
            plotList[-1].update_layout(height=500 * ceil(len(figureList) / columnNr))  # type: ignore
            if plotList == imagePlots and caseDict is not None:
                plotList[-1].update_layout(title_text=caseDict[rank])  # type: ignore
    return columnNr


def create_css(resultsDir):

    css_path = join(resultsDir, "mtb.css")
    
    css_content = r'''body {
  font-family: Arial, Helvetica, sans-serif;
}
		
.navbar {
  overflow: hidden;
  background-color: #028B76;
  font-family: Arial, Helvetica, sans-serif;
}

.navbar {
  overflow: hidden;
  background-color: #028B76;
  font-family: Arial, Helvetica, sans-serif;
}

.navbar a {
  float: left;
  font-size: 16px;
  color: white;
  text-align: center;
  padding: 14px 16px;
  text-decoration: none;
}

.dropdown {
  float: left;
  overflow: hidden;
}

.dropdown .dropbtn {
  font-size: 16px;  
  border: none;
  outline: none;
  color: white;
  padding: 14px 16px;
  background-color: inherit;
  font-family: inherit;
  margin: 0;
}

.navbar a:hover, .dropdown:hover .dropbtn {
  background-color: #ddd;
  color: black;
}

.dropdown-content {
  display: none;
  position: absolute;
  background-color: #f9f9f9;
  min-width: 160px;
  box-shadow: 0px 8px 16px 0px rgba(0,0,0,0.2);
  z-index: 1;
}

.dropdown-content a {
  float: none;
  color: black;
  padding: 12px 16px;
  text-decoration: none;
  display: block;
  text-align: left;
}

.dropdown-content a:hover {
  background-color: #ddd;
}

.dropdown:hover .dropdown-content {
  display: block;'''
    
    with open(f'{css_path}', 'w') as file:
        file.write(css_content)        
        
        
def create_html(plots: List[go.Figure], cursor_plots: List[go.Figure], path: str, title: str, rank: int,
                config: ReadConfig, rankList) -> None:
                
    source_list = '<div style="text-align: left; margin-top: 1px;">'
    source_list += '<h4>Source data:</h4>'
    for group in config.simDataDirs:
        source_list += f'<p>{group[0]} = {group[1]}</p>'

    source_list += '</div>'

    html_content = create_html_plots(config.htmlColumns, plots, title, rank)
    html_content_cursors = create_html_plots(config.htmlCursorColumns, cursor_plots, "Relevant signal metrics", rank) if len(
        cursor_plots) > 0 else ""
    
    # Create Dropdown Content for the Navbar
    idx = 0
    dropdown_content = ''
    while idx < len(rankList):
        dropdown_content += f'<a href="{rankList[idx]}.html">Rank {rankList[idx]}</a>\n'
        idx += 5
    
    # Determine the Previous and Next Rank html page for the Navbar
    idx = rankList.index(rank)
    rankPrev = rankList[idx-1]
    rankNext = rankList[idx+1 if idx+1 < len(rankList) else 0]
    
    full_html_content = f'''<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
	<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
    <link rel="stylesheet" href="mtb.css"
  </head>
  <body>
	<div class="navbar">
	  <a href="{rankPrev}.html" > &laquo; Previous Rank</a>
	  <a href="{rankNext}.html" > Next Rank &raquo;</a>
	  <div class="dropdown">
		<button class="dropbtn">More Ranks
		  <i class="fa fa-caret-down"></i>
		</button>
		<div class="dropdown-content">
          {dropdown_content}
		</div>
	  </div> 
	</div>
    <script>
        function showHelp() {{
        alert("Use Alt+PageUp to go to the previous rank\\nAnd Alt+PageDown to go to the next rank");
        }}
        document
            .addEventListener("keydown",
                function (event) {{
                    if (event.altKey && event.key === "PageUp") {{
                        event.preventDefault();
                        window.location.href = "{rankPrev}.html";
                    }} else if (event.altKey && event.key === "PageDown") {{
                        event.preventDefault();
                        window.location.href = "{rankNext}.html";
                    }} else if (event.altKey && event.key === "h") {{
                        event.preventDefault();
                        showHelp();
                    }}
                }});
    </script>
    <script>
    MathJax = {{
      tex: {{
              inlineMath: [['$', '$'], ['\\(', '\\)']]
      }}
    }};
    </script>
    <script id="MathJax-script" async
      src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js">
    </script>
    {html_content}
    {html_content_cursors}
    {source_list}
    <p><center><a href="https://github.com/Energinet-AIG/MTB" target="_blank">Generated with Energinets Model Testbench</a></center></p>
  </body>
</html>'''

    with open(f'{path}.html', 'w') as file:
        file.write(full_html_content)


def create_html_plots(columns, plots, title, rank):
    if columns in (1,2,3):
        figur_links = '<div style="text-align: left; margin-top: 1px;">'
        figur_links += '<h4>Figures:</h4>'
        for p in plots:
            plot_title: str = p['layout']['title']['text']  # type: ignore
            figur_links += f'<a href="#{plot_title}">{plot_title}</a>&emsp;'

        figur_links += '</div>'
    else:
        figur_links = ''
    html_content = f'<h1>Rank {rank}: {title}</h1>'
    html_content += figur_links
    html_content += '<table style="width:100%">'
    for i, p in enumerate(plots):
        plot_title: str = p['layout']['title']['text']  # type: ignore

        if ((i+1) % columns) == 1:
            html_content += '<tr>'
        html_content += f'<td><div id="{plot_title}">' + p.to_html(full_html=False,
                                                               include_plotlyjs='cdn',
                                                               include_mathjax='cdn',
                                                               default_width='100%') + '</div></td>'  # type: ignore
        if ((i+1) % columns) == 0:
            html_content += '</tr>'

    html_content += '</table>'
    return html_content


def readCasesheet(casesheetPath: str) -> Dict[int, str]:
    '''
    Reads optional casesheets and provides dict mapping rank to case title.
    '''
    if not casesheetPath:
        return None
    try:
        pd.read_excel(casesheetPath, sheet_name='RfG cases', header=1)  # type: ignore
    except FileNotFoundError:
        print(f'Casesheet not found at {casesheetPath}.')
        return dict()

    cases: List[Case] = list()
    for sheet in ['RfG', 'DCC', 'Unit', 'Custom']:
        dfc = pd.read_excel(casesheetPath, sheet_name=f'{sheet} cases', header=1)  # type: ignore
        for _, case in dfc.iterrows():  # type: ignore
            cases.append(Case(case))  # type: ignore

    caseDict: Dict[int, str] = defaultdict(lambda: 'Unknown case')
    for case in cases:
        caseDict[case.rank] = case.Name
    return caseDict


def main() -> None:
    config = ReadConfig()

    print('Starting plotter main thread')

    # Output config
    print('Configuration:')
    for setting in config.__dict__:
        print(f'\t{setting}: {config.__dict__[setting]}')

    print()

    resultDict = mapResultFiles(config)
    figureDict = readFigureSetup('figureSetup.csv')
    cursorDict = readCursorSetup('cursorSetup.csv')
    caseDict = readCasesheet(config.optionalCasesheet)
    emtAllSignalnamesDF = getAllSignalnames('figureSetup.csv')    # Required to process .psout files
    colorSchemeMap = colorMap(resultDict)
    
    if not exists(config.resultsDir):
        makedirs(config.resultsDir)

    create_css(config.resultsDir)

    threads: List[Thread] = list()

    for rank in resultDict.keys():
        emtRankSignalnamesList = getCaseSignalnames(emtAllSignalnamesDF, rank) # Required to process .psout files
        if config.threads > 1:
            threads.append(Thread(target=drawPlot,
                                  args=(rank, resultDict, figureDict, caseDict, colorSchemeMap, cursorDict, config, emtRankSignalnamesList)))
        else:
            drawPlot(rank, resultDict, figureDict, caseDict, colorSchemeMap, cursorDict, config, emtRankSignalnamesList)

    NoT = len(threads)
    if NoT > 0:
        sched = threads.copy()
        inProg: List[Thread] = []

        while len(sched) > 0:
            for t in inProg:
                if not t.is_alive():
                    print(f'Thread {t.native_id} finished')
                    inProg.remove(t)

            while len(inProg) < config.threads and len(sched) > 0:
                nextThread = sched.pop()
                nextThread.start()
                print(f'Started thread {nextThread.native_id}')
                inProg.append(nextThread)

            time.sleep(0.5)

    print('Finished plotter main thread')


if __name__ == "__main__":
    main()

if LOG_FILE:
    LOG_FILE.close()
