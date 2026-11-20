# -*- coding: utf-8 -*-
'''
A set of functions to process Manitoba Hydro International (MHI) PSOUT files.
This library provides functions to read and process PSOUT files.
Signal paths are relative to Root\\Main and use '\\' as separator, e.g. 'Module\\SubModule\\signal_name', to be
consistent with MHI's Enerplot (and PowerFactory). The paths are converted to the '/' separator used by mhi.psout.
It is designed to be used in conjunction with the Manitoba Hydro International (MHI) PSOUT File Reader Library.
'''

from __future__ import annotations
import sys
import numpy as np
import pandas as pd
from typing import List

try:
    import mhi.psout
except ImportError:
    print("Could not import mhi.psout. Make sure Manitoba Hydro International (MHI) PSOUT File Reader Library is installed and available in your Python environment.")
    sys.exit(1)


def findPsoutSignalPath(psoutFilePath: str, signalPathName: str, sourceType: str = 'Module') -> List[str] | None:
    """
    Recursively find the path(s) relative to Root/Main/ of a signal in a .psout file.
    Returns None if the signal could not be found, otherwise a list of paths where the signal was found.
    Note: Multiple paths may be returned if the signal exists in multiple modules.

    Parameters:
        psoutFilePath: The path to the .psout file
        signalPathName: Can be in the format 'Module\\signal_name' or just 'signal_name' 
                        as the leading path will be stripped to get just the signal name.
        sourceType: Should be a valid source type, e.g. 'Module', 'Graphic', 'PGB', etc.
    """
    # Strip any leading path prefix (e.g. 'Module\\' or 'Module\\SubModule\\') to get just the signal name
    signalName = signalPathName.split('\\')[-1]

    def search_node(node, current_path='', depth=0):
        if depth > 10:
            return None
        result_list = []
        try:
            for call in node.calls():
                call_str = str(call)
                name = call_str.split("Name='")[1].split("'")[0]
                source = call_str.split("Source='")[1].split("'")[0]
                new_path = current_path + '\\' + name if current_path else name

                if source == sourceType:
                    try:
                        child_path = 'Root/Main/' + new_path.replace('\\', '/')
                        child_node = psout_file.call(child_path)
                        for child_call in child_node.calls():
                            child_str = str(child_call)
                            child_name = child_str.split("Name='")[1].split("'")[0]
                            if child_name == signalName:
                                result_list.append(new_path)
                        # Recurse deeper
                        result_list.extend(search_node(child_node, new_path, depth + 1))
                    except Exception:
                        pass
        except Exception:
            pass
        return result_list

    with mhi.psout.File(psoutFilePath) as psout_file:
        root = psout_file.call('Root/Main')
        results = search_node(root)
        return results if results else None
       
def getPsoutSignalRecords(psoutFile):
    '''
    Find all PGB output channel signals in an opened .psout file (mhi.psout.File).
    Returns a dict of {signal path: data record call}, where the signal path is relative to Root\\Main
    using '\\' as separator (as in Enerplot) and the record's calls are the trace(s) of the signal.
    '''
    records = dict()

    def traverse(node, currentPath=''):
        for call in node.calls():
            name = call.variables().get('Name', '')
            source = call.variables().get('Source', '')
            path = f'{currentPath}\\{name}' if currentPath else name
            if source == 'PGB':
                if path in records:
                    print(f"Warning: Duplicate signal path '{path}'. Skipping...")
                    continue
                try:
                    records[path] = psoutFile.call('Root/Main/' + path.replace('\\', '/') + '/0')
                except Exception:
                    print(f"Warning: Signal '{path}' could not be read. Skipping...")
            elif source == 'Module':
                traverse(call, path)

    traverse(psoutFile.call('Root/Main'))
    return records


def listPsoutSignals(psoutFilePath):
    '''
    List all PGB output channel signals in the .psout file.
    Returns a list of (signal path, number of traces) sorted by signal path, where the signal path is relative to
    Root\\Main and the number of traces is > 1 for signal arrays.
    '''
    with mhi.psout.File(psoutFilePath) as psoutFile:
        records = getPsoutSignalRecords(psoutFile)
        return sorted(((path, record.num_calls) for path, record in records.items()), key=lambda item: item[0].lower())


def getAllPsoutSignals(psoutFilePath):
    '''
    Get all PGB output channel signals in the .psout file as a DataFrame with a 'time' column.
    Column names are the signal paths relative to Root\\Main, with an '_<n>' suffix for each element of signal arrays.
    '''
    columns = dict()
    time = None

    with mhi.psout.File(psoutFilePath) as psoutFile:
        run = psoutFile.run(0)
        for path, record in getPsoutSignalRecords(psoutFile).items():
            traces = [run.trace(traceCall) for traceCall in record.calls()]
            if not traces:
                continue
            if time is None:
                time = np.array(traces[0].domain.data)
            for i, trace in enumerate(traces):
                data = np.array(trace.data)
                if data.shape != time.shape:
                    print(f"Warning: Signal '{path}' has a different length than the time vector. Skipping...")
                    break
                columns[path if len(traces) == 1 else f'{path}_{i+1}'] = data

    if time is None:
        return pd.DataFrame()
    return pd.DataFrame({'time': time, **columns})


def getPsoutSignal(psoutFilePath, signalPathName):
    '''
    Get time and trace/signal from the opened psout file
    '''
    data_path = 'Root\\Main\\'+ signalPathName +'\\0'       # Signal paths use '\\' to be consistent with MHI's Enerplot (and PowerFactory)
    data_path = data_path.replace('\\', '/')                # But mhi.psout wants '/'
    
    with mhi.psout.File(psoutFilePath) as psoutFile:
        try:
            data = psoutFile.call(data_path)
        except:
            print(f'The signal data path, {data_path} could not be found in {psoutFilePath}!')
            return None, None
            
        run = psoutFile.run(0)
        signal = list()
        for call in data.calls():
            trace = run.trace(call)
            time = trace.domain.data
            signal.append(trace.data)

    return time, signal


def getPsoutSignals(psoutFilePath, signalPathNames):
    '''
    Get all signals from the .psout file whose names appear in the signalPathNames list
    Exit if the first signal (time refrence) is missing.
    Missing signals are ignored.
    The .psout file is opened only once, as opening it for every signal is slow.
    '''    
    
    if not signalPathNames:                                             # Return an empy DataFrame is the signalPathNames list is empy.
        return pd.DataFrame()

    columnNames = ['time']                                              # Column names to be used for the returned DataFrame
    psoutSignals = []                                                   # Rows of the returned DataFrame, the time first

    with mhi.psout.File(psoutFilePath) as psoutFile:
        run = psoutFile.run(0)
        for n, signalPathName in enumerate(signalPathNames):
            data_path = 'Root\\Main\\'+ signalPathName +'\\0'           # Signal paths use '\\' to be consistent with MHI's Enerplot (and PowerFactory)
            data_path = data_path.replace('\\', '/')                    # But mhi.psout wants '/'
            try:
                data = psoutFile.call(data_path)
            except:
                print(f'The signal data path, {data_path} could not be found in {psoutFilePath}!')
                if n == 0:
                    print(f"CRITICAL: Primary signal '{signalPathName}' (Time) not found. Cannot proceed.")
                    sys.exit(1)
                print(f"Warning: Signal '{signalPathName}' not found. Skipping...")
                continue

            traces = [run.trace(call) for call in data.calls()]
            if n == 0:
                psoutSignals.append(np.array(traces[-1].domain.data))   # Use the time of the first signal as the time column

            # A signal array gets a set of signal names, one for each signal in the array
            if len(traces) > 1:
                columnNames.extend(f'{signalPathName}_{i+1}' for i in range(len(traces)))
            else:
                columnNames.append(signalPathName)
            psoutSignals.extend(np.array(trace.data) for trace in traces)

    return pd.DataFrame(np.transpose(np.array(psoutSignals)), columns=columnNames)
