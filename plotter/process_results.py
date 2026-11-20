from Result import ResultType


def getColNames(rawSigName, result):
    '''
    Translate the signal names used in figureSetup.csv and cursorSetup.csv into the actual signal names used in the various result type files
    '''
    
    if result.typ == ResultType.RMS:
        while rawSigName.startswith('#'):
            rawSigName = rawSigName[1:]
        splitSigName = rawSigName.split('\\')

        if len(splitSigName) == 2:
            sigColName = ('##' + splitSigName[0], splitSigName[1])
        elif len(splitSigName) > 2:
            sigColName = ('\\'.join(splitSigName[:-1]), splitSigName[-1])
        else:
            sigColName = rawSigName
    elif result.typ == ResultType.EMT_INF:
        # Legacy (MTB 1.0) .inf/.csv results have no signal path, i.e. only the unique signal name is used
        rawSigName = rawSigName.split('\\')[-1]
        sigColName = rawSigName
    elif result.typ in (ResultType.EMT_PSOUT, ResultType.EMT_CSV, ResultType.EMT_ZIP):
        # uses the full hierarchical signal name, e.g. 'MTB\\P_pu_PoC' (also for .csv files from convert_psout_to_csv.py)
        sigColName = rawSigName
    else:
        print(f'File type: {result.typ} unknown')
    
    sigDispName = f'{result.shorthand}:{rawSigName.split(" ")[0]}'.replace('$','')

    return sigColName, sigDispName


def getUniqueEmtSignals(figureList):
    '''
    Get a unique list of emt_signals from the figureList, i.e. with no duplicate emt_signals
    used to extract signal from the .psout files and generate a DataFrame with unique columns names
    Python's "set()" could also be used, but then the order of the signals in the DataFrame would change
    '''
    
    # Use 'mtb_s_pref_pu' as the first signal as this signal/PGB will never manually be disabled and is later used to find the MTB path
    # The other signals are required to generate Guide Waveforms
    emt_signals = ['MTB\\mtb_s_pref_pu',
                   'MTB\\mtb_s_pavail_pu',
                   'MTB\\mtb_s_qudroop',
                   'MTB\\mtb_s_sips_g',
                   'MTB\\mtb_s_sips_d']
    
    for fig in figureList:
        if fig.emt_signal_1 != '': emt_signals.append(fig.emt_signal_1)
        if fig.emt_signal_2 != '': emt_signals.append(fig.emt_signal_2)
        if fig.emt_signal_3 != '': emt_signals.append(fig.emt_signal_3)
    
    unique_emt_signals = []

    for emt_signal in emt_signals:
        if emt_signal not in unique_emt_signals: unique_emt_signals.append(emt_signal)
    
    return unique_emt_signals


def findMtbPath(signalPaths):
    '''
    Find the path of the MTB module relative to Root\\Main, e.g. 'MTB' or 'Grid\\MTB_2', from the location of the
    'mtb_s_pref_pu' signal in the signal paths, e.g. the keys of getPsoutSignalRecords() or the columns of
    getAllPsoutSignals(). Returns None if it is not found.
    '''
    for path in signalPaths:
        if path.endswith('\\mtb_s_pref_pu'):
            return path[:-len('\\mtb_s_pref_pu')]
    return None


def toMtbSignalName(signalPath, mtbPath):
    '''
    Map an actual .psout signal path to the figureSetup.csv name, i.e. MTB signals are always named 'MTB\\<signal>'
    even if the MTB is not placed on the main canvas, e.g. 'Grid\\MTB_2\\P_pu_PoC' -> 'MTB\\P_pu_PoC'
    '''
    if mtbPath and mtbPath != 'MTB' and signalPath.startswith(mtbPath + '\\'):
        return 'MTB\\' + signalPath[len(mtbPath) + 1:]
    return signalPath


def fromMtbSignalName(signalName, mtbPath):
    '''
    The inverse of toMtbSignalName(), e.g. 'MTB\\P_pu_PoC' -> 'Grid\\MTB_2\\P_pu_PoC'
    '''
    if mtbPath and mtbPath != 'MTB' and signalName.startswith('MTB\\'):
        return mtbPath + '\\' + signalName[4:]
    return signalName


def getAllMtbSignals(psoutFilePath):
    '''
    Get all PGB output channel signals in the .psout file, with the MTB signals always named 'MTB\\<signal>'
    '''
    from process_psout import getAllPsoutSignals

    dfSignals = getAllPsoutSignals(psoutFilePath)
    mtbPath = findMtbPath(dfSignals.columns)
    dfSignals.columns = [toMtbSignalName(c, mtbPath) for c in dfSignals.columns]
    return dfSignals


def getFigureSetupSignals(psoutFilePath, signalnames):
    '''
    Get the figureSetup.csv signals from the .psout file. The 'MTB\\' signals are found also if the MTB is not
    placed on the main canvas, and are always named 'MTB\\<signal>' in the returned DataFrame.
    '''
    import mhi.psout
    from process_psout import getPsoutSignalRecords, getPsoutSignals

    with mhi.psout.File(psoutFilePath) as psoutFile:
        mtbPath = findMtbPath(getPsoutSignalRecords(psoutFile))
    dfSignals = getPsoutSignals(psoutFilePath, [fromMtbSignalName(s, mtbPath) for s in signalnames])
    dfSignals.columns = [toMtbSignalName(c, mtbPath) for c in dfSignals.columns]
    return dfSignals
