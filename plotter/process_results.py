from Result import ResultType


def getColNames(rawSigName,resultType):
    '''
    Translate the signal names used in figureSetup.csv and cursorSetup.csv into the actual signal names used in the various result type files
    '''
    
    if resultType == ResultType.RMS:
        while rawSigName.startswith('#'):
            rawSigName = rawSigName[1:]
        splitSigName = rawSigName.split('\\')

        if len(splitSigName) == 2:
            sigColName = ('##' + splitSigName[0], splitSigName[1])
        else:
            sigColName = rawSigName
    elif resultType in (ResultType.EMT_INF, ResultType.EMT_CSV, ResultType.EMT_ZIP):
        # uses only the signal name - last part of the hierarchical signal name
        rawSigName = rawSigName.split('\\')[-1]
        sigColName = rawSigName
    elif resultType == ResultType.EMT_PSOUT:
        # uses the full hierarchical signal name
        sigColName = rawSigName
    else:
        print(f'File type: {resultType} unknown')
        
    return sigColName


def getUniqueEmtSignals(figureList):
    '''
    Get a unique list of emt_signals from the figureList, i.e. with no duplicate emt_signals
    used to extract signal from the .psout files and generate a DataFrame with unique columns names
    Python's "set()" could also be used, but then the order of the signals in the DataFrame would change
    '''
    emt_signals = []
    
    for fig in figureList:
        if fig.emt_signal_1 != '': emt_signals.append(fig.emt_signal_1)
        if fig.emt_signal_2 != '': emt_signals.append(fig.emt_signal_2)
        if fig.emt_signal_3 != '': emt_signals.append(fig.emt_signal_3)
    
    unique_emt_signals = []

    for emt_signal in emt_signals:
        if emt_signal not in unique_emt_signals: unique_emt_signals.append(emt_signal)
    
    return unique_emt_signals

