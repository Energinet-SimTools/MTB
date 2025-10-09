import numpy as np
import pandas as pd
from Result import ResultType
from process_results import getColNames


def getTimeIntervals(time_ranges):
    '''
    Convert the each pair of values in time_ranges into a list of time_interval tuples
    If the the last time value does not form a pair, it is assumed that the last 
    interval is until the end of the simulation
    '''
    time_intervals = []
    for i in range(len(time_ranges)//2):
        time_intervals.append((time_ranges[i*2],time_ranges[i*2+1]))
    if len(time_ranges) % 2 == 1:
        time_intervals.append((time_ranges[-1],))
    return time_intervals
    

def setupCursorDataFrame(ranksCursor):
    '''
    Setup the list of cursor DataFrames
    '''
    dfCursorsList = []
    for cursor in ranksCursor:
        data = []
        for option in cursor.cursor_options:
            for interval in getTimeIntervals(cursor.time_ranges):
                if len(interval)==2:
                    data.append([f'{interval[0]} s : {interval[1]} s'])
                else:
                    data.append([f'{interval[0]} s : ..'])
        dfCursorsList.append(pd.DataFrame(data, columns=['Cursor time intervals']))
        
    return dfCursorsList


def getCursorSignals(rawSigNames, result, resultData, pfFlatTIme, pscadInitTime):
    '''
    Make a DataFrame with all the signals required for the cursor functions
    This DataFrame is created with only a cursor time range column as the first column at first.
    This cursor time range column repeats the time ranges for each cursor function, i.e. if there
    are 5 time ranges, and 3 cursor functions, then the time range column will have 15 rows.
    The cursor metric columns , i.e. min, max, mean, etc. for each signal for the set of cursor
    time ranges will be added, and then appended, once they are calculated

    Parameters
    ----------
    rawSigNames : list
        List of raw signal names to include in the DataFrame.
    result : Result
        The result object containing metadata about the signals.
    resultData : DataFrame
        The DataFrame containing the actual signal data.
    pfFlatTIme : float
        The PowerFactory flat time offset.
    pscadInitTime : float
        The PSCAD initialization time offset.

    Returns
    -------
    DataFrame
        A DataFrame containing the required cursor signals.
    '''
    cursorSignalsDf = pd.DataFrame()
    
    timeColName = 'time' if result.typ in (ResultType.EMT_INF, ResultType.EMT_PSOUT, ResultType.EMT_CSV, ResultType.EMT_ZIP) else resultData.columns[0]
    timeoffset = pfFlatTIme if result.typ == ResultType.RMS else pscadInitTime
    
    if timeColName in resultData.columns:
        t = resultData[timeColName] - timeoffset
        cursorSignalsDf['t'] = t
    else:
        print(f'The time columns {timeColName} was not found in the results DataFrame!')
        
    for rawSigName in rawSigNames:
        sigColName, sigDispName = getColNames(rawSigName,result)
                    
        if sigColName in resultData.columns:
            signal = resultData[sigColName]
            cursorSignalsDf[sigDispName] = signal
        else:
            print(f'Signal columns "{sigColName}" not found in the cursor signal DataFrame!')
    
    return cursorSignalsDf


def addCursorMetrics(ranksCursor, dfCursorsList, result, resultData, settingsDict, caseDf):
    '''
    This is the main function from where all the cursor functions are called 
    and which add the cursor function result to a list of DatafFrames from
    which the cursor tables will be created

    Parameters
    ----------
    ranksCursor : Cursor Object
        for the specifice rank, it contains:
            * a List of .cursor_options or cursor functions to be called
            * a List of .emt_signals & .rms_signal required for the cursor 
              .options (functions) - the output will be based on the first
              signal in the list, with the subsequent signals passed used as
              auxiliary input signals to the cursor function
            * a List of .time_ranges to indicated on which parts of the signals
              the .options (functions) needs to be performed on - the time
              ranges are read in pairs, i.e. start time, and end time of the 
              cursor - if the last time value is a single value, then the end
              time is taken as the end of the signal passed
    dfCursorsList : List of DataFrames
        each DataFrame corrisponds to to a cursor table, with columns:
            * Time ranges
            * Cursor function results for the first .emt_signal for each time
              range (if specified)
            * Cursor function results for the first .rms_signal for each time
              range (if specified)
    result : Result Object
        contains information on the result.typ
    resultData : DataFrame
        contains the result data for all the RMS or EMT signals.
    pfFlatTIme : Float
        PowerFactory flat time
    pscadInitTime : Float
        PSCAD initialisation time
    settingsDict : Dictionary 
        All the 'Settings' from the the testcases.xlsx, 'Setting' sheet, e.g.
        'Area' (DK1 | DK2), 'FSM droop', etc.
    caseDf : DataFrame
        All the 'Case' information from the the testcases.xlsx, e.g. 'RfG case'
        sheet, e.g. 'Initial Settings', 'Event 1'.'type', etc.

    Returns
    -------
    None.

    '''
    pfFlatTIme = settingsDict['PF flat time']
    pscadInitTime = settingsDict['PSCAD Initialization time']
    
    for i, cursor in enumerate(ranksCursor):
        if result.typ == ResultType.RMS:
            rawSigNames = cursor.rms_signals
        elif result.typ in (ResultType.EMT_INF, ResultType.EMT_PSOUT, ResultType.EMT_CSV, ResultType.EMT_ZIP):
            rawSigNames = cursor.emt_signals
        else:
            print(f'File type: {result.typ} unknown')

        cursorSignalsDf = getCursorSignals(rawSigNames, result, resultData, pfFlatTIme, pscadInitTime)
        
        if len(cursorSignalsDf.columns) > 1:
            cursorMetricData = []                
            for option in cursor.cursor_options:
                for time_interval in getTimeIntervals(cursor.time_ranges):
                    if option.name == 'START':
                        cursorMetricData.append(cursorStart(cursorSignalsDf, time_interval))
                    elif option.name == 'END':
                       cursorMetricData.append(cursorEnd(cursorSignalsDf, time_interval))
                    elif option.name == 'DELTA':
                       cursorMetricData.append(cursorDelta(cursorSignalsDf, time_interval))
                    elif option.name == 'MIN':
                        cursorMetricData.append(cursorMin(cursorSignalsDf, time_interval))
                    elif option.name == 'MAX':
                        cursorMetricData.append(cursorMax(cursorSignalsDf, time_interval))
                    elif option.name == 'MEAN':
                        cursorMetricData.append(cursorMean(cursorSignalsDf, time_interval))
                    elif option.name == 'GRAD_MIN':
                        cursorMetricData.append(cursorGradMin(cursorSignalsDf, time_interval))
                    elif option.name == 'GRAD_MAX':
                        cursorMetricData.append(cursorGradMax(cursorSignalsDf, time_interval))
                    elif option.name == 'GRAD_MEAN':
                        cursorMetricData.append(cursorGradMean(cursorSignalsDf, time_interval))
                    elif option.name == 'RESPONSE':
                        cursorMetricData.append(cursorResponseDelay(cursorSignalsDf, time_interval))
                    elif option.name == 'RISE_FALL':
                        cursorMetricData.append(cursorRiseFallTime(cursorSignalsDf, time_interval))
                    elif option.name == 'SETTLING':
                        cursorMetricData.append(cursorSettlingTime(cursorSignalsDf, time_interval))
                    elif option.name == 'OVERSHOOT':
                        cursorMetricData.append(cursorPeakOvershoot(cursorSignalsDf, time_interval))
                    elif option.name == 'FSM_DROOP':
                        cursorMetricData.append(cursorFSMDroop(cursorSignalsDf, time_interval, settingsDict))
                    elif option.name == 'LFSM_DROOP':
                        cursorMetricData.append(cursoLFSMDroop(cursorSignalsDf, time_interval, settingsDict))
                    elif option.name == 'QU_DROOP':
                        cursorMetricData.append(cursorQUDroop(cursorSignalsDf, time_interval, caseDf))
                    else:
                        print(f'Cursor function {option} not defined')
                        
            dfCursorsList[i][cursorSignalsDf.columns[1]] = cursorMetricData # Add column to cursor DataFrame, using the first cursor signal display name


def cursorStart(cursorSignalsDf, time_interval):
    '''
    Determine the closest signal value to the start and end value of the time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
        
        if len(t) > 0:
            t0 = t.iloc[0]      # Cursor start t value
            y0 = y.iloc[0]      # Cursor start y value
    
            cursorMetricText = f"Start: y({t0:.3f}) = {y0:.3f}"
        else:
            cursorMetricText = "Inst: error"
    else:
        cursorMetricText = "Inst: error"
    
    return cursorMetricText
    

def cursorEnd(cursorSignalsDf, time_interval):
    '''
    Determine the closest signal value to the start and end value of the time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
        
        if len(t) > 0:
            t1 = y.iloc[-1]     # Cursor end t value
            y1 = y.iloc[-1]     # Cursor end y value
    
            cursorMetricText = f"End: y({t1:.3f}) = {y1:.3f}"
        else:
            cursorMetricText = "Inst: error"
    else:
        cursorMetricText = "Inst: error"
    
    return cursorMetricText
    

def cursorDelta(cursorSignalsDf, time_interval):
    '''
    Determine the closest signal value to the start and end value of the time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
        
        if len(t) > 0:
            y0 = y.iloc[0]      # Cursor start y value
            y1 = y.iloc[-1]     # Cursor end y value
            dy = y1 - y0        # Difference in y values
    
            cursorMetricText = f"Delta: \u0394y = {dy:.3f}"
        else:
            cursorMetricText = "Inst: error"
    else:
        cursorMetricText = "Inst: error"
    
    return cursorMetricText
    

def cursorMin(cursorSignalsDf, time_interval):
    '''
    Calculate the minimum value of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
        
        if len(t) > 0:
            # Find the min of y
            y_min = y.min()
        
            # Find the corresponding x-values
            t_min = t[y.idxmin()]  # x-value where y is minimum
        
            # Construct the text
            cursorMetricText = f"Min: {y_min:.3f} at t = {t_min:.3f} s"
        else:
            cursorMetricText = "Min: error"
    else:
        cursorMetricText = "Min: error"
    
    return cursorMetricText


def cursorMax(cursorSignalsDf, time_interval):
    '''
    Calculate the maximum value of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
            
        if len(t) > 0:
            # Find the max of y
            y_max = y.max()
        
            # Find the corresponding x-values
            t_max = t[y.idxmax()]  # x-value where y is maximum
        
            # Construct the text
            cursorMetricText = f"Max: {y_max:.3f} at t = {t_max:.3f} s"
        else:
            cursorMetricText = "Max: error"
    else:
        cursorMetricText = "Max: error"
    
    return cursorMetricText


def cursorMean(cursorSignalsDf, time_interval):
    '''
    Calculate the mean value of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
    
        if len(t) > 0:
            # Find the mean of y
            y_mean = y.mean()
        
            # Construct the text
            cursorMetricText = f"Mean: {y_mean:.3f}"
        else:
            cursorMetricText = "Mean: error"
    else:
        cursorMetricText = "Mean: error"

    return cursorMetricText


def cursorGradMin(cursorSignalsDf, time_interval):
    '''
    Calculate the minimum gradient of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
    
        if len(t) > 0:
            # Find the min gradien of y
            y_grad = np.gradient(y,t)
            y_grad_min = y_grad.min()*60
            
            # Construct the text
            cursorMetricText = f"Grad (min): {y_grad_min:.3f} pu/min"
        else:
            cursorMetricText = "Grad (min): error"
    else:
        cursorMetricText = "Grad (min): error"

    return cursorMetricText


def cursorGradMean(cursorSignalsDf, time_interval):
    '''
    Calculate the mean gradient of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
            
        if len(t) > 0:
            # Find the mean gradien of y
            y_grad = np.gradient(y,t)
            y_grad_mean = y_grad.mean()*60
            
            # Construct the text
            cursorMetricText = f"Grad (mean): {y_grad_mean:.3f} pu/min"
        else:
            cursorMetricText = "Grad (mean): error"
    else:
        cursorMetricText = "Grad (mean): error"

    return cursorMetricText


def cursorGradMax(cursorSignalsDf, time_interval):
    '''
    Calculate the maximum gradient of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
    
        if len(t) > 0:
            # Find the min gradien of y
            y_grad = np.gradient(y,t)
            y_grad_max = y_grad.max()*60
            
            # Construct the text
            cursorMetricText = f"Grad (max): {y_grad_max:.3f} pu/min"
        else:
            cursorMetricText = "Grad (max): error"
    else:
        cursorMetricText = "Grad (max): error"

    return cursorMetricText


def cursorResponseDelay(cursorSignalsDf, time_interval):
    '''
    Calculate the signal response delay until it reaches 10% to delta value over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
     
        if len(t) > 0:
            # Find the risetime of y
            y0 = y.iloc[0]      # Cursor start y value
            y1 = y.iloc[-1]     # Cursor end y value
            dy = y1 - y0        # Difference in y values
            
            if dy > 0:          # Response delay time for a rising signal
                mask = (y <= (y0 + 0.1*dy)) # The 10% rise value mask
            else:               # Response delay time for a falling time
                mask = (y >= (y0 + 0.1*dy)) # The 10% fall value mask
            
            t = t[mask]         # Get the rise/fall response delay time range values
            
            t_response = t.max() - t.min()      # Get the rise/fall time      
        
            # Construct the text
            cursorMetricText = f"Response delay: {t_response:.3f} s"
        else:
            cursorMetricText = "Response delay: error"
    else:
        cursorMetricText = "Response delay: error"

    return cursorMetricText


def cursorRiseFallTime(cursorSignalsDf, time_interval):
    '''
    Calculate the 10%-90% rise or fall time of a signal over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
     
        if len(t) > 0:
            # Find the risetime of y
            y0 = y.iloc[0]      # Cursor start y value
            y1 = y.iloc[-1]     # Cursor end y value
            dy = y1 - y0        # Difference in y values
            
            if dy > 0:                                              # Rise time
                mask = (y >= (y0 + 0.1*dy)) & (y <= (y0 + 0.9*dy))  # The 10% to 90% rise value mask
            else:                                                   # Fall time
                mask = (y <= (y0 + 0.1*dy)) & (y >= (y0 + 0.9*dy))  # The 10% to 90% fall value mask
            
            t = t[mask]         # Get the rise/fall time range values
            
            tRiseFall = t.max() - t.min()      # Get the rise/fall time      
        
            # Construct the text
            labelRiseOrFall = 'Rise time' if dy > 0 else 'Fall time'
            cursorMetricText = f"{labelRiseOrFall}: {tRiseFall:.3f} s"
        else:
            cursorMetricText = "Rise/Fall time: error"
    else:
        cursorMetricText = "Rise/Fall time: error"

    return cursorMetricText


def cursorSettlingTime(cursorSignalsDf, time_interval, tol=2):
    '''
    Calculate the settling time of a signal until comes within tol% of the final value over a time interval
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
     
        if len(t) > 0:
            # Find the settling time of y
            t0 = t.iloc[0]          # Time t0
            y0 = y.iloc[0]          # Cursor start y value
            y1 = y.iloc[-1]         # Cursor end y value
            dy = np.abs(y1 - y0)    # Difference in y values
            
            mask = np.abs(y - y1) >= dy*tol/100     # Tollerance setting time mask
                    
            tSettling = t[mask].max() - t0          # Get the settling time      
        
            # Construct the text
            cursorMetricText = f"Settling time: {tSettling:.3f} s"
        else:
            cursorMetricText = "Settling time: error"
    else:
        cursorMetricText = "Settling time: error"

    return cursorMetricText


def cursorPeakOvershoot(cursorSignalsDf, time_interval):
    '''
    Calculate the peak overshoot percentage and damping value of a signal over a time interval
    The overshoot is expressed as a percentage of the final value of the signal.
    '''
    if len(cursorSignalsDf.columns) >=2:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        y = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            y = y[mask]
            
        if len(t) > 0:
            # Find the step size within the time interval
            y0 = y.iloc[0]          # Cursor start y value
            y1 = y.iloc[-1]         # Cursor end y value
            dy = np.abs(y1 - y0)    # Difference in y values
    
            # Find the overshoot ratio of y
            yOSRatio = 0.0                      # Default value if no overshoot
            if y1 > y0:                         # Positve step
                if y.max() > y1:                # Check if there is a positive overshoot
                    yOSRatio = (y.max()-y1)/dy
            else:                               # Negative step
                if y.min() < y1:                # Check if there is a negative overshoot
                    yOSRatio = np.abs(y.min()-y1)/dy
    
            # Find the corresponding second order damping ratio estimate
            if yOSRatio > 0.0:                  # Check if there is an overshoot
                A = np.log(yOSRatio)/np.pi
                zeta = np.sqrt(A**2/(1+A**2))
            else:
                zeta = 1.0                      # Else set zeta to 1.0
            # Construct the text
            cursorMetricText = f"Overshoot: {yOSRatio*100:.2f} % (\u03B6 \u2248 {zeta:.3f})"
        else:
            cursorMetricText = "Overshoot: error"
    else:
        cursorMetricText = "Overshoot: error"
    
    return cursorMetricText


def cursorFSMDroop(cursorSignalsDf, time_interval, settingsDict):
    '''
    Calculate the FSM droop of a signal over a time interval
    The droop is calculated as the change in frequency (f) over the change in power (P)
    The droop is expressed as a percentage of the nominal frequency (fn) and the reference power (Pref)
    The droop is only activated after the FSM deadband is reached, 
    i.e. the FSM deadband is added to the nominal frequency (fn) for positive frequency changes and subtracted for negative frequency changes.

    The droop is calculated as:
        df = fnew - fn + db if df < 0 else fnew - fn - db
        dP/dF = -100 * (df/fn) * (Pref/dP)

    where:
        dP = change in power (P)
        dF = change in frequency (f)
        fn = nominal frequency (f) = 50 Hz
        Pref = reference power (P) = P at the start of the cursor interval
    '''
    if len(cursorSignalsDf.columns) >=3:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        p = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        f = cursorSignalsDf[cursorSignalsDf.columns[2]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            p = p[mask]
            f = f[mask]
        
        if len(t) > 0:
            fn = 50                                 # Nominal frequency [Hz]
            db = float(settingsDict['FSM deadband']) # FSM deadband in [Hz]
                    
            if np.abs(fn-f.iloc[0]) < 0.01:
                fnew = f.iloc[-1]   # Assume new f at the end of the cursor interval
                Pnew = p.iloc[-1]
                Pref = p.iloc[0]
            else:
                fnew = f.iloc[0]
                Pnew = p.iloc[0]
                Pref = p.iloc[-1]
                
            df = fnew - fn
    
            if Pnew == Pref:
                fsmDroop = np.inf
            else:            
                if df < 0:
                    fsmDroop = -100*(fnew-fn+db)/(fn*(Pnew-Pref))
                else:
                    fsmDroop = -100*(fnew-fn-db)/(fn*(Pnew-Pref))
            
            # Construct the text
            cursorMetricText = f"FSM droop: {fsmDroop:.2f}%"
        else:
            cursorMetricText = "FSM droop: error"
    else:
        cursorMetricText = "FSM droop: error"

    return cursorMetricText


def cursoLFSMDroop(cursorSignalsDf, time_interval, settingsDict):
    '''
    Calculate the FSM droop of a signal over a time interval
    The droop is calculated as the change in frequency (f) over the change in power (P)
    The droop is expressed as a percentage of the nominal frequency (fn) and the reference power (Pref)

    The droop is calculated as:
        dP/dF = -100 * (dF/fn) * (Pref/dP)
    where:
        dP = change in power (P)    
        dF = change in frequency (f)
        fn = nominal frequency (f) = 50 Hz
        Pref = reference power (P) = P at the start of the cursor interval
    '''
    if len(cursorSignalsDf.columns) >=3:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        p = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        f = cursorSignalsDf[cursorSignalsDf.columns[2]].copy()
        
        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            p = p[mask]
            f = f[mask]
        
        if len(t) > 0:
            fn = 50                                     # Nominal frequency [Hz]
            DK = 1 if settingsDict['Area']=='DK1' else 2 # DK area, either 1 or 2
                    
            if np.abs(fn-f.iloc[0]) > 0.01:
                fnew = f.iloc[0]
                Pnew = p.iloc[0]
                Pref = p.iloc[-1]
            else:
                fnew = f.iloc[-1]   # new f at the end of the cursor interval
                Pnew = p.iloc[-1]
                Pref = p.iloc[0]
                            
            if DK == 1:
                f1 = 50.2 if fnew > fn else 49.8
            elif DK == 2:
                f1 = 50.5 if fnew > fn else 49.5
            else:
                print('"DK" can either be "1" or "2"!')
                cursorMetricText = "LFSM droop: error"
            
            if Pnew == Pref:
                lfsmDroop = np.inf
            else:
                lfsmDroop = -100*(fnew-f1)/(fn*(Pnew-Pref))
                  
            # Construct the text
            cursorMetricText = f"LFSM droop: {lfsmDroop:.2f}%"
        else:
            cursorMetricText = "LFSM droop: error"
    else:
        cursorMetricText = "LFSM droop: error"

    return cursorMetricText


def cursorQUDroop(cursorSignalsDf, time_interval, caseDf):
    '''
    Calculate the Q(U) droop of a signal over a time interval
    The droop is calculated as the change in reactive power (Q) over the change in voltage (U)
    The droop is expressed as a percentage of the nominal reactive power (Qnom) and the nominal voltage (Uref)

    The droop is calculated as:
        dQ/dU = -100 * (dU/Uref) * (Qnom/dQ)
    
    where:
        dQ = change in reactive power (Q)
        dU = change in voltage (U)
        Uref = nominal voltage (U)
        Qnom = nominal reactive power (Q) = 0.33 pu (as per the standard)
    '''
    if len(cursorSignalsDf.columns) >=3:
        t = cursorSignalsDf[cursorSignalsDf.columns[0]].copy()
        q = cursorSignalsDf[cursorSignalsDf.columns[1]].copy()
        u = cursorSignalsDf[cursorSignalsDf.columns[2]].copy()

        if len(time_interval) > 0:
            mask = (t >= time_interval[0]) & (t <= time_interval[1]) if len(time_interval) == 2 else (t >= time_interval[0])
            t = t[mask]
            q = q[mask]
            u = u[mask]

        if len(t) > 0:
            Uref = caseDf['Initial Settings']['U0'].squeeze() # pu
            Qnom = 0.33 # pu
            
            dq = q.iloc[-1] - q.iloc[0]
            du = u.iloc[-1] - u.iloc[0]
            
            dquDroop = -100*du/Uref*Qnom/dq
            
            # Construct the text
            cursorMetricText = f"Q(U) droop: {dquDroop:.2f}%"
        else:
            cursorMetricText = "Q(U) droop: error"
    else:
        cursorMetricText = "Q(U) droop: error"

    return cursorMetricText
    
