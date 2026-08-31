"""
pscad_synchronize_pgbs.py

Library for synchronizing PGB (Output Channel) components in PSCAD projects with a list of signals specified in a figureSetup.csv file.

Usage as library:
    from pscad_synchronize_pgbs import getSignalsFromFigureSetup, validateFigureSetupAgainstWorkspace, synchronizePGBsInProject
    
    pscad = mhi.pscad.application()
    
    keep_signals = getSignalsFromFigureSetup(figureSetup)
    missing_total = validateFigureSetupAgainstWorkspace(pscad, keep_signals)
        
    if not missing_total:
        case_names = [p['name'] for p in pscad.projects() if p['type'] == 'Case']
        
        for case_name in case_names:
            proj = pscad.project(case_name)
            synchronizePGBsInProject(proj, keep_signals, sync=False, verbose=True) # Do a dry run first to review changes before actually applying them with sync=True

========================================================================================================================
Can also be run as a script from within the PSCAD Python console to list the status of all PGBs across all Case projects
========================================================================================================================

"""

from __future__ import annotations
import os
import sys
import csv
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional

# ============================================================
# SIGNAL PATH UTILITIES
# ============================================================

def _parseProjectXML(proj) -> Tuple[Dict[str, str], Dict[str, str], List[Tuple[int, str, str, bool]]]:
    """
    Parses the project XML file once to extract everything needed to resolve PGB signal
    paths, instead of walking the canvas/component hierarchy via PSCAD automation calls
    (proj.canvas(), canvas.components(), pgb.parent, pgb.parameters()). Each automation
    call is a remote round-trip, which becomes very slow (minutes instead of seconds)
    when connected to PSCAD over an external automation link rather than running inside
    PSCAD's embedded Python console.

    Returns:
        parent_map: {child_defn -> parent_defn} (canvas hierarchy, by definition name)
        instance_map: {defn_name -> instance_name} for components with a custom 'Name' param
        pgb_records: [(id, signal_name, parent_defn_name, is_disabled), ...] for all master:pgb components
    """
    parent_map: Dict[str, str] = {}
    instance_map: Dict[str, str] = {}
    pgb_records: List[Tuple[int, str, str, bool]] = []

    try:
        tree = ET.parse(proj.filename)
        root = tree.getroot()

        # Definition elements live under a <definitions> wrapper (not direct children of <project>),
        # so use iter() to find them regardless of nesting depth. Skip StationDefn (e.g. 'DS'),
        # which wraps Main for multiple-run purposes and is not part of the real canvas hierarchy.
        for defn_elem in root.iter('Definition'):
            if defn_elem.get('classid') != 'UserCmpDefn':
                continue
            parent_name = defn_elem.get('name', '')

            for user_elem in defn_elem.iter('User'):
                defn_attr = user_elem.get('defn', '')

                if defn_attr == 'master:pgb':
                    comp_id = int(user_elem.get('id'))
                    is_disabled = user_elem.get('disable', 'false').lower() == 'true'
                    signal_name = ''
                    for param in user_elem.iter('param'):
                        if param.get('name') == 'Name':
                            signal_name = param.get('value', '')
                            break
                    pgb_records.append((comp_id, signal_name, parent_name, is_disabled))
                    continue

                if ':' not in defn_attr:
                    continue

                child_project, child_defn = defn_attr.split(':', 1)
                if child_project != proj.name:
                    continue

                if child_defn not in parent_map:
                    parent_map[child_defn] = parent_name

                # Look for a 'Name' parameter identifying a custom instance name
                for param in user_elem.iter('param'):
                    if param.get('name') == 'Name':
                        instance_name = param.get('value', '')
                        if instance_name and instance_name != child_defn:
                            instance_map.setdefault(child_defn, instance_name)
                        break
    except Exception as e:
        print('Warning: Could not parse project XML: ' + str(e))

    return parent_map, instance_map, pgb_records


def _getCanvasPath(canvas_name: str, parent_map: Dict[str, str]) -> str:
    """Build full canvas path e.g. Main\\BePPC\\Pcontrol_30"""
    path = [canvas_name]
    current = canvas_name
    while current in parent_map:
        current = parent_map[current]
        path.append(current)
    path.reverse()
    return '\\'.join(path)


def _getSignalPath(canvas_name: str, signal_name: str, parent_map: Dict[str, str], 
                   instance_map: Dict[str, str] = None) -> str:
    """
    Build full psout signal path excluding Main.
    Uses instance names (e.g. '$Unit$') instead of definition names (e.g. 'unit_meas')
    where applicable.
    """
    canvas_path = _getCanvasPath(canvas_name, parent_map)
    parts = canvas_path.split('\\')
    if parts[0] == 'Main':
        parts = parts[1:]
    if not parts:
        return signal_name
    
    # Replace definition names with instance names where available
    if instance_map:
        parts = [instance_map.get(p, p) for p in parts]
    
    return '\\'.join(parts) + '\\' + signal_name


def _getDisabledIds(proj) -> set:
    """Get set of component IDs that are disabled in the project XML."""
    disabled_ids = set()
    try:
        tree = ET.parse(proj.filename)
        root = tree.getroot()
        for elem in root.iter('User'):
            if elem.get('defn') == 'master:pgb':
                if elem.get('disable', 'false').lower() == 'true':
                    disabled_ids.add(int(elem.get('id')))
    except Exception as e:
        print('Warning: Could not parse project XML: ' + str(e))
    return disabled_ids


# ============================================================
# FIGURE SETUP CSV READER AND SIGNAL VALIDATION
# ============================================================

def getSignalsFromFigureSetup(figureSetupPath: str) -> List[str]:

    emt_signals = []

    try:
        with open(figureSetupPath, newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                for key in ['emt_signal_1', 'emt_signal_2', 'emt_signal_3']:
                    signal = row.get(key) or ''  # Handle None explicitly
                    signal = signal.strip()
                    if signal and signal not in emt_signals:
                        emt_signals.append(signal)
    except Exception as e:
        print('Warning: Could not read figureSetup.csv: ' + str(e))
    
    emt_signals = [s for s in emt_signals if not s.startswith('MTB\\') ]
    
    return emt_signals


def validateFigureSetupAgainstWorkspace(pscad, keep_signals: List[str]) -> List[str]:
    """
    Checks if the signals requested in the CSV exist anywhere in the workspace.
    """
    case_names = [p['name'] for p in pscad.projects() if p['type'] == 'Case']
    all_existing_paths = set()

    # Collect every single PGB path available in the workspace
    for name in case_names:
        proj = pscad.project(name)
        proj.save() # Ensure XML is up to date before parsing
        print("Checking project: " + name + " for signals from figureSetup.csv...")
        status_map = getPGBStatus(proj)
        for signals in status_map.values():
            for _, signal_path, _, _ in signals:
                all_existing_paths.add(signal_path)

    # Find signals in CSV that don't exist in ANY project
    missing_globally = [s for s in keep_signals if s not in all_existing_paths]

    if missing_globally:
        print("\nERROR: These signals from figureSetup.csv are missing from the ENTIRE workspace:")
        for missing in missing_globally:
            print(f"  - {missing}")
    else:
        print("\nSuccess: All signals in figureSetup.csv were located in the workspace.")

    return missing_globally


# ============================================================
# PGB INSPECTION
# ============================================================

def getPGBStatus(proj) -> Dict[str, List[Tuple[str, str, bool, object]]]:
    """
    Get all PGB components in a project grouped by canvas path.
    As .psout signal paths are built using instance names, the canvas names are replaced with 
    instance names where applicable (e.g. 'unit_meas' -> '$Unit$').
    
    Returns:
        Dict of {canvas_path: [(signal_name, signal_path, is_disabled, pgb_component), ...]}
    """
    parent_map, instance_map, pgb_records = _parseProjectXML(proj)

    # Single remote call, just to get component handles for later enable()/disable() calls
    pgb_components = {comp.iid: comp for comp in proj.find_all('master:pgb')}

    canvas_path_dict = {}
    for comp_id, signal_name, canvas_name, is_disabled in pgb_records:
        pgb = pgb_components.get(comp_id)
        if pgb is None:
            continue  # Guard against XML/runtime state mismatch

        # Build canvas path using definition names (for hierarchy traversal)
        canvas_path_defn = _getCanvasPath(canvas_name, parent_map)

        # Build display canvas path using instance names
        parts = canvas_path_defn.split('\\')
        display_parts = [instance_map.get(p, p) for p in parts]
        canvas_path_display = '\\'.join(display_parts)

        # Build signal path using instance names (for psout matching)
        signal_path = _getSignalPath(canvas_name, signal_name, parent_map, instance_map)

        if canvas_path_display not in canvas_path_dict:
            canvas_path_dict[canvas_path_display] = []
        canvas_path_dict[canvas_path_display].append((signal_name, signal_path, is_disabled, pgb))

    return canvas_path_dict


def printPGBStatus(proj, keep_signals: Optional[List[str]] = None) -> None:
    """
    Print all PGB components in a project grouped by canvas path.

    Parameters:
        proj: PSCAD project object
        keep_signals: Optional list of signal paths to mark as KEEP
    """
    canvas_path_dict = getPGBStatus(proj)
    total_enabled = 0
    total_disabled = 0
    will_keep = 0
    will_disable = 0

    print('\n' + '=' * 60)
    print('Project: ' + proj.name)
    print('=' * 60)

    for canvas_path in sorted(canvas_path_dict.keys()):
        signals = canvas_path_dict[canvas_path]
        n_enabled = sum(1 for _, _, d, _ in signals if not d)
        n_disabled = sum(1 for _, _, d, _ in signals if d)
        total_enabled += n_enabled
        total_disabled += n_disabled

        print('\n' + canvas_path)
        print('=' * len(canvas_path))

        for signal_name, signal_path, is_disabled, pgb in sorted(signals, key=lambda x: x[0]):
            if keep_signals:
                if signal_path in keep_signals:
                    action = 'KEEP'
                    will_keep += 1
                elif not is_disabled:
                    action = 'WILL DISABLE'
                    will_disable += 1
                else:
                    action = 'already disabled'
            else:
                action = 'disabled' if is_disabled else 'enabled'

            print('  ' + signal_name + ' [' + action + ']')

        print('\n  --------------')
        print('  Enabled : ' + str(n_enabled))
        print('  Disabled: ' + str(n_disabled))

    print('\n' + '=' * 60)
    print('Total enabled : ' + str(total_enabled))
    print('Total disabled: ' + str(total_disabled))
    if keep_signals:
        print('Will keep     : ' + str(will_keep))
        print('Will disable  : ' + str(will_disable))


# ============================================================
# PGB DISABLE/ENABLE
# ============================================================

def synchronizePGBsInProject(proj, keep_signals: List[str], 
                             sync: bool = False, 
                             verbose: bool = True) -> None:
    """
    Synchronizes PGB states with the keep_signals list.
    Enables PGBs found in the list, disables those that are not.
    """
    canvas_path_dict = getPGBStatus(proj)

    if verbose:
        printPGBStatus(proj, keep_signals)

    disabled_count = 0
    enabled_count = 0
    kept_count = 0

    for canvas_path, signals in canvas_path_dict.items():
        for signal_name, signal_path, is_disabled, pgb in signals:
            in_keep_list = signal_path in keep_signals
            
            # Case 1: Signal should be Disabled but is currently Enabled
            if not in_keep_list and not is_disabled:
                if sync:
                    pgb.disable()
                disabled_count += 1
            
            # Case 2: Signal should be Enabled but is currently Disabled
            elif in_keep_list and is_disabled:
                if sync:
                    pgb.enable()
                enabled_count += 1
            
            # Case 3: Signal is in the list and already Enabled, or not in the list and already Disabled
            elif in_keep_list:
                kept_count += 1

    if sync:
        proj.save()
        print(f'\nProject {proj.name}: Disabled {disabled_count}, Enabled {enabled_count}, Kept {kept_count}. Saved!')
    else:
        print(f'\nProject {proj.name} DRY RUN: Would disable {disabled_count}, and enable {enabled_count}.')

    print('=' * 60)
    print()


def enableAllPGBs(pscad, verbose: bool = True) -> None:
    """
    Re-enable all PGB components across all Case projects.

    Parameters:
        pscad: PSCAD application object
        verbose: If True, print status.
    """
    case_names = [p['name'] for p in pscad.projects() if p['type'] == 'Case']

    for case_name in case_names:
        proj = pscad.project(case_name)
        pgb_components = proj.find_all('master:pgb')
        disabled_ids = _getDisabledIds(proj)

        enabled_count = 0
        for pgb in pgb_components:
            if pgb.iid in disabled_ids:
                pgb.enable()
                enabled_count += 1

        proj.save()
        if verbose:
            print('Project ' + case_name + ': re-enabled ' + str(enabled_count) + ' pgbs. Saved!')


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    import mhi.pscad
    
    pscad = mhi.pscad.application()

    # --------------------------------------------------------
    print(sys.version)
    print()
    # --------------------------------------------------------
    #Ensure right working directory
    # --------------------------------------------------------
    executePath = os.path.abspath(__file__)
    executeFolder = os.path.dirname(executePath)
    os.chdir(executeFolder)
    sys.path.append(executeFolder)
    print(executeFolder)
    print()
    # --------------------------------------------------------
    
    figureSetup = r'.\plotter\figureSetup.csv' # Or set to None to just print status of all PGBs without modifying anything
    SYNC = False   # Do a dry run first to review changes before actually applying them with SYNC=True
    VERBOSE = True # Print detailed status of each PGB and summary counts at the end of each project
    
    if figureSetup:
        # 1. Load the "Keep" list from CSV
        keep_signals = getSignalsFromFigureSetup(figureSetup)
        
        # 2. Validate the list against the whole Workspace
        # This catches signal typos regardless of which project they are in.
        missing_total = validateFigureSetupAgainstWorkspace(pscad, keep_signals)
        
        if not missing_total:
            # 3. Only if the CSV is 100% correct, proceed to modify projects
            case_names = [p['name'] for p in pscad.projects() if p['type'] == 'Case']
            
            for case_name in case_names:
                proj = pscad.project(case_name)
                # This function (from previous step) now handles one project at a time
                synchronizePGBsInProject(proj, keep_signals, sync=SYNC, verbose=VERBOSE) 
        else:
            print("\nAborting: Please fix the signal names in figureSetup.csv before proceeding.")

    else:
        # Just print status of all PGBs
        print('No figureSetup.csv file provided. Printing PGB status for all Case projects...')
        case_names = [p['name'] for p in pscad.projects() if p['type'] == 'Case']
        for case_name in case_names:
            proj = pscad.project(case_name)
            printPGBStatus(proj)








