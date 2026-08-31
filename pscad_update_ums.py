'''
Update unit measurement pgb names
'''
from __future__ import annotations
import os
import sys
import xml.etree.ElementTree as ET
from typing import List, Tuple

if __name__ == '__main__':
    print(sys.version)
    #Ensure right working directory
    executePath = os.path.abspath(__file__)
    executeFolder = os.path.dirname(executePath)
    os.chdir(executeFolder)
    sys.path.append(executeFolder)
    print(executeFolder)

if __name__ == '__main__':
    from execute_pscad import connectPSCAD
    from configparser import ConfigParser

import mhi.pscad


def _findUnitMeasPgbUpdates(proj, legacy: bool) -> List[Tuple[int, str, str]]:
    """
    Parse the project XML to find every 'unit_meas'-family instance and its pgbs, instead of
    walking canvas.components()/comp.canvas() via automation. That automation-based traversal
    is unreliable when PSCAD runs on a remote server reached via mhi.pscad.connect(port=...),
    even though it works fine when running inside PSCAD's own embedded Python console.

    Returns:
        [(pgb_id, current_name, new_name), ...]
    """
    tree = ET.parse(proj.filename)
    root = tree.getroot()

    # Map each unit_meas-family definition name -> its instance 'alias' parameter value
    instance_alias = {}
    for elem in root.iter('User'):
        defn_attr = elem.get('defn', '')
        if ':' not in defn_attr:
            continue
        proj_name, child_defn = defn_attr.split(':', 1)
        if proj_name != proj.name or 'unit_meas' not in child_defn:
            continue
        for param in elem.iter('param'):
            if param.get('name') == 'alias':
                instance_alias[child_defn] = param.get('value', '')
                break

    updates: List[Tuple[int, str, str]] = []
    for defn_elem in root.iter('Definition'):
        if defn_elem.get('classid') != 'UserCmpDefn':
            continue
        defn_name = defn_elem.get('name', '')
        if 'unit_meas' not in defn_name:
            continue
        alias = instance_alias.get(defn_name)
        if alias is None:
            continue  # No placed instance found for this definition

        for pgb_elem in defn_elem.iter('User'):
            if pgb_elem.get('defn') != 'master:pgb':
                continue
            pgb_id = int(pgb_elem.get('id'))
            group = ''
            current_name = ''
            for param in pgb_elem.iter('param'):
                if param.get('name') == 'Group':
                    group = param.get('value', '')
                elif param.get('name') == 'Name':
                    current_name = param.get('value', '')
            new_name = f'{alias}_{group}' if legacy else group
            updates.append((pgb_id, current_name, new_name))

    return updates


def updateUMs(pscad : mhi.pscad.PSCAD, legacy : bool = True, verbose : bool = False) -> None:
    """
    Update all unit measurements' instances signal names
    
    Parameters:
        pscad: PSCAD instance
        legacy: If True, each pgb gets an explicit "<alias>_<Group>" name (unique across units,
                required for the old flat .out format). If False, the pgb's name is reset to its
                bare 'Group' (the name of the signal it is connected to, with no alias prefix).
        verbose: If True, print the signal names being updated
    """
    projectLst = pscad.projects()
    for prjDic in projectLst:
        if prjDic['type'].lower() == 'case':
            project = pscad.project(prjDic['name'])
            project.save()  # Ensure XML is up to date before parsing
            updates = _findUnitMeasPgbUpdates(project, legacy)
            print(f'Updating unit measurements in project: {project} ({len(updates)} pgb(s) found)')

            # Single remote call, just to get component handles for setting parameters
            pgb_components = {comp.iid: comp for comp in project.find_all('master:pgb')}

            changed_count = 0
            for pgb_id, current_name, new_name in updates:
                pgb = pgb_components.get(pgb_id)
                if pgb is None:
                    continue  # Guard against XML/runtime state mismatch
                if current_name != new_name:
                    if verbose:
                        print(f'\t{pgb}: Name={current_name!r} -> Name={new_name!r} UseSignalName=0')
                    pgb.parameters(Name = new_name, UseSignalName = 0)
                    changed_count += 1

            # Persist to disk; without this, the automation-only change may not be reflected in the
            # project's saved .pscx/.pslx file (e.g. when read back for signal validation, or reopened).
            project.save()
            print(f'\t{changed_count} pgb name(s) updated. Saved!')
    print()
    
def main():
    config = ConfigParser()
    config.read('config.ini')
    legacy = config.getboolean('PSCAD', 'Use legacy Unit measurement signal naming', fallback=True)
    print(f'Use legacy Unit measurement signal naming = {legacy}')

    pscad = connectPSCAD()
    updateUMs(pscad, legacy=legacy, verbose=True)
    print()

if __name__ == '__main__':
    main()






