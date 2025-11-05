'''
Contains the specific setup for the testbench. Connecting the waveforms to the PSCAD and PowerFactory interfaces.
'''
from __future__ import annotations 
from typing import Union, Tuple, List, Optional
import pandas as pd
import sim_interface as si
from math import isnan, sqrt
from warnings import warn

FAULT_TYPES = { 
    '3p fault' : 7.0,
    '2p-g fault' : 5.0,
    '2p fault' : 3.0,
    '1p fault' : 1.0,
    '3p fault (ohm)' : 8.0,
    '2p-g fault (ohm)' : 6.0,
    '2p fault (ohm)' : 4.0,
    '1p fault (ohm)' : 2.0 
}
    
QMODES = {
    'q': 0,
    'q(u)': 1,
    'pf': 2,
    'qmode3': 3,
    'qmode4': 4,
    'qmode5': 5,
    'qmode6': 6,
}

PMODES = {
    'no p(f)': 0,
    'lfsm': 1,
    'fsm': 2,
    'lfsm+fsm': 3,
    'pmode4': 4,
    'pmode5': 5,
    'pmode6': 6,
    'pmode7': 7
} 

class PlantSettings:
    def __init__(self, path : str) -> None:
        df : pd.DataFrame = pd.read_excel(path, sheet_name='Settings', header=None) # type: ignore

        df.set_index(0, inplace = True) # type: ignore
        inputs : pd.Series[Union[str, float]] = df.iloc[1:, 0] 

        self.Casegroup = str(inputs['Casegroup'])
        self.Run_custom_cases = bool(inputs['Run custom cases'])
        self.Projectname = str(inputs['Projectname']).replace(' ', '_')
        self.Pn = float(inputs['Pn']) 
        self.Uc = float(inputs['Uc'])
        self.Un = float(inputs['Un'])
        self.Area = str(inputs['Area'])
        self.SCR_min = float(inputs['SCR min'])
        self.SCR_tuning = float(inputs['SCR tuning'])
        self.SCR_max = float(inputs['SCR max'])
        self.Default_QUdroop = float(inputs['Default Q(U) droop'])
        self.XR_SCR_min = float(inputs['X/R SCR min'])
        self.XR_SCR_tuning = float(inputs['X/R SCR tuning'])
        self.XR_SCR_max = float(inputs['X/R SCR max'])
        self.R0 = float(inputs['R0'])
        self.X0 = float(inputs['X0'])
        self.Default_Q_mode = str(inputs['Default Q mode'])
        self.PSCAD_Timestep = float(inputs['PSCAD Timestep'])
        self.PSCAD_init_time = float(inputs['PSCAD Initialization time'])
        self.PF_flat_time = float(inputs['PF flat time'])
        self.PF_variable_step = bool(inputs['PF variable step'])
        self.PF_enforced_sync = bool(inputs['PF enforced sync.'])
        self.PF_force_asymmetrical_sim = bool(inputs['PF force asymmetrical sim.'])
        self.PF_enforce_P_limits_in_LDF = bool(inputs['PF enforce P limits in LDF'])
        self.PF_enforce_Q_limits_in_LDF = bool(inputs['PF enforce Q limits in LDF'])

class Case:
    def __init__(self, case: 'pd.Series[Union[str, int, float, bool]]') -> None:
        self.rank: int = int(case['Rank'])
        self.RMS: bool = bool(case['RMS'])
        self.EMT: bool = bool(case['EMT'])
        self.Name: str = str(case['Name'])
        self.U0: float = float(case['U0'])
        self.P0: float = float(case['P0'])
        self.Pmode: str = str(case['Pmode'])
        self.Qmode: str = str(case['Qmode'])
        self.Qref0: float = float(case['Qref0'])
        self.QUdroop0: str = str(case['QUdroop0']) # Use 'str' because 'default' is also a valid value for the droop
        self.SCR0: float = float(case['SCR0'])
        self.XR0: float = float(case['XR0'])
        self.Simulationtime: float = float(case['Simulationtime'])
        self.Events : List[Tuple[str, float, Union[float, str], Union[float, str]]] = []

        index : pd.Index[str] = case.index # type: ignore
        i = 0
        while(True):
            typeLabel = f'type.{i}' if i > 0 else 'type'
            timeLabel = f'time.{i}' if i > 0 else 'time'
            x1Label = f'X1.{i}' if i > 0 else 'X1'
            x2Label = f'X2.{i}' if i > 0 else 'X2'

            if typeLabel in index and timeLabel in index and x1Label in index and x2Label in index:
                try:
                    x1value = float(str(case[x1Label]).replace(' ',''))
                except ValueError:
                    x1value = str(case[x1Label])

                try:
                    x2value = float(str(case[x2Label]).replace(' ',''))
                except ValueError:
                    x2value = str(case[x2Label])

                self.Events.append((str(case[typeLabel]), float(case[timeLabel]), x1value, x2value))
                i += 1
            else:
                break

def setup(casesheetPath : str, pscad : bool, pfEncapsulation : Optional[si.PFinterface]) -> Tuple[PlantSettings, List[si.Channel], List[Case], int, List[Case]]:
    '''
    Sets up the simulation channels and cases from the given casesheet. Returns plant settings, channels, cases, max rank and emtCases.
    '''
    def impedance_uk_pcu(scr : float, xr : float, pn : float, un : float, uc : float) -> Tuple[float, float]:
        scr_ = max(scr, 0.001)
        pcu = (uc*uc)/(un*un)*pn/sqrt(xr*xr + 1)/scr_ if scr >= 0.0 else 0.0
        uk = (uc*uc)/(un*un)/scr_ if scr >= 0.0 else 0.0
        return 100.0 * uk, 1000.0 * pcu

    def signal(name : str, pscad : bool = True, defaultConnection : bool = True, measFile : bool = False) -> si.Signal:
        newSignal = si.Signal(name, pscad, pfEncapsulation)
        
        if defaultConnection:
            newSignal.addPFsub_S(f'{name}.ElmDsl', 's:x')
            newSignal.addPFsub_R(f'{name}.ElmDsl', 'slope')
            newSignal.addPFsub_S0(f'{name}.ElmDsl', 'x0')
            newSignal.addPFsub_T(f'{name}.ElmDsl', 'mode')
        if measFile:
            newSignal.setElmFile(f'{name}_meas.ElmFile')
        
        channels.append(newSignal)
        return newSignal

    def constant(name : str, value : float, pscad : bool = True) -> si.Constant:
        newConstant = si.Constant(name, value, pscad, pfEncapsulation)
        channels.append(newConstant)
        return newConstant

    def pfObjRefer(name : str) -> si.PfObjRefer:
        newPfObjRefer = si.PfObjRefer(name, pfEncapsulation)
        channels.append(newPfObjRefer)
        return newPfObjRefer
    
    def string(name : str) -> si.String:
        newString = si.String(name, pfEncapsulation)
        channels.append(newString)
        return newString
    
    pf = pfEncapsulation is not None

    channels : List[si.Channel] = []
    plantSettings = PlantSettings(casesheetPath)

    si.pf_time_offset = plantSettings.PF_flat_time
    si.pscad_time_offset = plantSettings.PSCAD_init_time

    # Voltage source control
    mtb_t_vmode = signal('mtb_t_vmode', defaultConnection = False) # only to be used in PSCAD
    mtb_s_vref_pu = signal('mtb_s_vref_pu', measFile = True)
    mtb_s_vref_pu.addPFsub_S0('vac.ElmVac', 'usetp', lambda _, x : abs(x))
    mtb_s_vref_pu.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:5', lambda _, x : abs(x))
    mtb_s_vref_pu.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:5', lambda _, x : abs(x))
    mtb_s_vref_pu.addPFsub_T('initializer_script.ComDpl', 'IntExpr:4', lambda _, x : abs(x))
    mtb_s_vref_pu.addPFsub_T('initializer_qdsl.ElmQdsl', 'initVals:4', lambda _, x : abs(x))

    mtb_s_dvref_pu = signal('mtb_s_dvref_pu')
    mtb_s_phref_deg = signal('mtb_s_phref_deg', measFile = True)
    mtb_s_phref_deg.addPFsub_S0('vac.ElmVac', 'phisetp')
    mtb_s_fref_hz = signal('mtb_s_fref_hz', measFile = True)

    mtb_s_varef_pu = signal('mtb_s_varef_pu', defaultConnection = False)
    mtb_s_vbref_pu = signal('mtb_s_vbref_pu', defaultConnection = False)
    mtb_s_vcref_pu = signal('mtb_s_vcref_pu', defaultConnection = False)

    # Grid impedance
    mtb_s_scr = signal('mtb_s_scr')
    mtb_s_scr.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:11')
    mtb_s_scr.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:11')

    mtb_s_xr = signal('mtb_s_xr')
    mtb_s_xr.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:12')
    mtb_s_xr.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:12')

    ldf_t_uk = signal('ldf_t_uk', pscad = False, defaultConnection = False)
    ldf_t_uk.addPFsub_S0('z.ElmSind', 'uk')
    ldf_t_pcu_kw = signal('ldf_t_pcu_kw', pscad = False, defaultConnection = False)
    ldf_t_pcu_kw.addPFsub_S0('z.ElmSind', 'Pcu')

    # Zero sequence impedance
    mtb_t_r0_ohm = signal('mtb_t_r0_ohm', defaultConnection = False)
    mtb_t_r0_ohm.addPFsub_S0('vac.ElmVac', 'R0')
    mtb_t_r0_ohm.addPFsub_S0('fault_ctrl.ElmDsl', 'r0')

    mtb_t_x0_ohm = signal('mtb_t_x0_ohm', defaultConnection = False)
    mtb_t_x0_ohm.addPFsub_S0('vac.ElmVac', 'X0')
    mtb_t_x0_ohm.addPFsub_S0('fault_ctrl.ElmDsl', 'x0')

    # Standard plant references and outputs
    mtb_s_pref_pu = signal('mtb_s_pref_pu', measFile = True)
    mtb_s_pref_pu.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:6')
    mtb_s_pref_pu.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:6')
    mtb_s_pref_pu.addPFsub_S0('powerf_ctrl.ElmSecctrl', 'psetp', lambda _, x : x * plantSettings.Pn)

    mtb_s_qref = signal('mtb_s_qref', measFile = True)
    mtb_s_qref.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:9')
    mtb_s_qref.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:9')
    mtb_s_qref.addPFsub_S0('station_ctrl.ElmStactrl', 'usetp', lambda _, x: 1.0 if x <= 0.0 else x)
    mtb_s_qref.addPFsub_S0('station_ctrl.ElmStactrl', 'qsetp', lambda _, x : -x * plantSettings.Pn)
    mtb_s_qref.addPFsub_S0('station_ctrl.ElmStactrl', 'pfsetp', lambda _, x: min(abs(x), 1.0))
    mtb_s_qref.addPFsub_S0('station_ctrl.ElmStactrl', 'pf_recap', lambda _, x: 0 if x > 0 else 1)

    mtb_s_qref_q_pu = signal('mtb_s_qref_q_pu',  measFile = True)
    mtb_s_qref_qu_pu = signal('mtb_s_qref_qu_pu', measFile = True)
    mtb_s_qref_pf = signal('mtb_s_qref_pf', measFile = True)
    mtb_s_qref_3 = signal('mtb_s_qref_3', measFile = True)
    mtb_s_qref_4 = signal('mtb_s_qref_4', measFile = True)
    mtb_s_qref_5 = signal('mtb_s_qref_5', measFile = True)
    mtb_s_qref_6 = signal('mtb_s_qref_6', measFile = True)

    mtb_t_qmode = signal('mtb_t_qmode')
    mtb_t_qmode.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:8')
    mtb_t_qmode.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:8')

    def stactrl_mode_switch(self : si.Signal, qmode : float):
        if qmode == 1:
            return 0
        elif qmode == 2:
            return 2
        else:
            return 1

    mtb_t_qmode.addPFsub_S0('station_ctrl.ElmStactrl', 'i_ctrl', stactrl_mode_switch)

    mtb_s_qudroop = signal('mtb_s_qudroop')
    mtb_s_qudroop.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:10')
    mtb_s_qudroop.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:10')
    mtb_s_qudroop.addPFsub_S0('station_ctrl.ElmStactrl', 'ddroop')

    mtb_t_pmode = signal('mtb_t_pmode')
    mtb_t_pmode.addPFsub_S0('initializer_script.ComDpl', 'IntExpr:7')
    mtb_t_pmode.addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:7')

    # Constants
    mtb_c_pn = constant('mtb_c_pn', plantSettings.Pn)
    mtb_c_pn.addPFsub('initializer_script.ComDpl', 'IntExpr:0')
    mtb_c_pn.addPFsub('initializer_qdsl.ElmQdsl', 'initVals:0')
    mtb_c_pn.addPFsub('measurements.ElmDsl', 'pn')
    mtb_c_pn.addPFsub('rx_calc.ElmDsl', 'pn')
    mtb_c_pn.addPFsub('z.ElmSind', 'Sn')
    
    mtb_c_qn = constant('mtb_c_qn', 0.33 * plantSettings.Pn, pscad = False)
    mtb_c_qn.addPFsub('station_ctrl.ElmStactrl', 'Srated')

    mtb_c_vbase = constant('mtb_c_vbase', plantSettings.Un)
    mtb_c_vbase.addPFsub('initializer_script.ComDpl', 'IntExpr:1')
    mtb_c_vbase.addPFsub('initializer_qdsl.ElmQdsl', 'initVals:1')
    mtb_c_vbase.addPFsub('measurements.ElmDsl', 'vbase')
    mtb_c_vbase.addPFsub('pcc.ElmTerm', 'uknom')
    mtb_c_vbase.addPFsub('ext.ElmTerm', 'uknom')
    mtb_c_vbase.addPFsub('fault_node.ElmTerm', 'uknom')
    mtb_c_vbase.addPFsub('z.ElmSind', 'ucn')
    mtb_c_vbase.addPFsub('fz.ElmSind', 'ucn')
    mtb_c_vbase.addPFsub('connector.ElmSind', 'ucn')
    mtb_c_vbase.addPFsub('vac.ElmVac', 'Unom')

    mtb_c_vc = constant('mtb_c_vc', plantSettings.Uc)
    mtb_c_vc.addPFsub('initializer_script.ComDpl', 'IntExpr:2')
    mtb_c_vc.addPFsub('initializer_qdsl.ElmQdsl', 'initVals:2')
    mtb_c_vc.addPFsub('rx_calc.ElmDsl', 'vc')

    constant('mtb_c_inittime_s', plantSettings.PSCAD_init_time)

    mtb_c_flattime_s = constant('mtb_c_flattime_s', plantSettings.PF_flat_time, pscad = False)
    mtb_c_flattime_s.addPFsub('initializer_script.ComDpl', 'IntExpr:3')
    mtb_c_flattime_s.addPFsub('initializer_qdsl.ElmQdsl', 'initVals:3')

    # Time and rank control
    mtb_t_simtimePscad_s = signal('mtb_t_simtimePscad_s', defaultConnection = False)
    mtb_t_simtimePf_s = signal('mtb_t_simtimePf_s', defaultConnection = False)
    mtb_t_simtimePf_s.addPFsub_S0('$studycase$\\ComSim', 'tstop')

    # From rank to PSCAD task ID
    mtb_s_task = signal('mtb_s_task', defaultConnection = False)

    # Fault
    flt_s_type = signal('flt_s_type')
    flt_s_rf_ohm = signal('flt_s_rf_ohm')
    flt_s_resxf = signal('flt_s_resxf')

    mtb_s : List[si.Signal] = []
    # Custom signals
    mtb_s.append(signal('mtb_s_1', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:13')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:13')
    mtb_s.append(signal('mtb_s_2', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:14')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:14')
    mtb_s.append(signal('mtb_s_3', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:15')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:15')
    mtb_s.append(signal('mtb_s_4', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:16')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:16')
    mtb_s.append(signal('mtb_s_5', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:17')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:17')
    mtb_s.append(signal('mtb_s_6', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:18')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:18')
    mtb_s.append(signal('mtb_s_7', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:19')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:19')
    mtb_s.append(signal('mtb_s_8', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:20')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:20')
    mtb_s.append(signal('mtb_s_9', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:21')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:21')
    mtb_s.append(signal('mtb_s_10', measFile = True))
    mtb_s[-1].addPFsub_S0('initializer_script.ComDpl', 'IntExpr:22')
    mtb_s[-1].addPFsub_S0('initializer_qdsl.ElmQdsl', 'initVals:22')

    # Powerfactory references
    ldf_r_vcNode = pfObjRefer('mtb_r_vcNode')
    ldf_r_vcNode.addPFsub('vac.ElmVac', 'contbar')

    # Refences outserv time invariants
    ldf_t_refOOS = signal('ldf_t_refOOS', pscad = False, defaultConnection = False)
    ldf_t_refOOS.addPFsub_S0('mtb_s_pref_pu.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_qref_q_pu.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_qref_qu_pu.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_qref_pf.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_t_qmode.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_t_pmode.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_1.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_2.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_3.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_4.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_5.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_6.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_7.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_8.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_9.ElmDsl', 'outserv')
    ldf_t_refOOS.addPFsub_S0('mtb_s_10.ElmDsl', 'outserv')

    # Calculation settings constants and timeVariants
    ldf_c_iopt_lim = constant('ldf_c_iopt_lim', int(plantSettings.PF_enforce_Q_limits_in_LDF), pscad = False)
    ldf_c_iopt_lim.addPFsub('$studycase$\\ComLdf', 'iopt_lim')

    ldf_c_iopt_apdist = constant('ldf_c_iopt_apdist', 1, pscad = False)
    ldf_c_iopt_apdist.addPFsub('$studycase$\\ComLdf', 'iopt_apdist')

    ldf_c_iPST_at = constant('ldf_c_iPST_at', 1, pscad = False)
    ldf_c_iPST_at.addPFsub('$studycase$\\ComLdf', 'iPST_at')

    ldf_c_iopt_at = constant('ldf_c_iopt_at', 1, pscad = False)
    ldf_c_iopt_at.addPFsub('$studycase$\\ComLdf', 'iopt_at')

    ldf_c_iopt_asht = constant('ldf_c_iopt_asht', 1, pscad = False)
    ldf_c_iopt_asht.addPFsub('$studycase$\\ComLdf', 'iopt_asht')

    ldf_c_iopt_plim = constant('ldf_c_iopt_plim', int(plantSettings.PF_enforce_P_limits_in_LDF), pscad = False)
    ldf_c_iopt_plim.addPFsub('$studycase$\\ComLdf', 'iopt_plim')

    ldf_c_iopt_net = signal('ldf_c_iopt_net', pscad = False, defaultConnection = False) # ldf asymmetrical option boolean
    ldf_c_iopt_net.addPFsub_S0('$studycase$\\ComLdf', 'iopt_net')

    inc_c_iopt_net = string('inc_c_iopt_net') # inc asymmetrical option 
    inc_c_iopt_net.addPFsub('$studycase$\\ComInc', 'iopt_net')

    inc_c_iopt_show = constant('inc_c_iopt_show', 1, pscad = False)
    inc_c_iopt_show.addPFsub('$studycase$\\ComInc', 'iopt_show')

    inc_c_dtgrd = constant('inc_c_dtgrd', 0.001, pscad = False)
    inc_c_dtgrd.addPFsub('$studycase$\\ComInc', 'dtgrd')

    inc_c_dtgrd_max = constant('inc_c_dtgrd_max', 0.01, pscad = False)
    inc_c_dtgrd_max.addPFsub('$studycase$\\ComInc', 'dtgrd_max')

    inc_c_tstart = constant('inc_c_tstart', 0, pscad = False)
    inc_c_tstart.addPFsub('$studycase$\\ComInc', 'tstart')

    inc_c_iopt_sync = constant('inc_c_iopt_sync', plantSettings.PF_enforced_sync, pscad = False) # enforced sync. option
    inc_c_iopt_sync.addPFsub('$studycase$\\ComInc', 'iopt_sync')

    inc_c_syncperiod = constant('inc_c_syncperiod', 0.001, pscad = False)
    inc_c_syncperiod.addPFsub('$studycase$\\ComInc', 'syncperiod')

    inc_c_iopt_adapt = constant('inc_c_iopt_adapt', plantSettings.PF_variable_step, pscad = False) # variable step option
    inc_c_iopt_adapt.addPFsub('$studycase$\\ComInc', 'iopt_adapt')

    inc_c_iopt_lt = constant('inc_c_iopt_lt', 0, pscad = False)
    inc_c_iopt_lt.addPFsub('$studycase$\\ComInc', 'iopt_lt')

    inc_c_errseq = constant('inc_c_errseq', 0.01, pscad = False)
    inc_c_errseq.addPFsub('$studycase$\\ComInc', 'errseq')

    inc_c_autocomp = constant('inc_c_autocomp', 0, pscad = False)
    inc_c_autocomp.addPFsub('$studycase$\\ComInc', 'automaticCompilation')

    df = pd.read_excel(casesheetPath, sheet_name=f'{plantSettings.Casegroup} cases', header=1) # type: ignore

    maxRank = 0
    cases : List[Case] = []
    emtCases : List[Case] = []

    for _, case in df.iterrows(): # type: ignore
        cases.append(Case(case)) # type: ignore
        maxRank = max(maxRank, cases[-1].rank)

    if plantSettings.Run_custom_cases and plantSettings.Casegroup != 'Custom':
        dfc = pd.read_excel(casesheetPath, sheet_name='Custom cases', header=1) # type: ignore
        for _, case in dfc.iterrows(): # type: ignore
            cases.append(Case(case)) # type: ignore
            maxRank = max(maxRank, cases[-1].rank)

    for case in cases:
        # Simulation time
        pf_lonRec = pscad_lonRec = 0.0

        # PF: Default symmetrical simulation
        if plantSettings.PF_force_asymmetrical_sim:
            ldf_c_iopt_net[case.rank] = 1
            inc_c_iopt_net[case.rank] = 'rst'
        else:
            ldf_c_iopt_net[case.rank] = 0
            inc_c_iopt_net[case.rank] = 'sym'

        # Voltage source control default setup
        mtb_t_vmode[case.rank] = 0
        mtb_s_vref_pu[case.rank] = -case.U0
        mtb_s_phref_deg[case.rank] = 0.0
        mtb_s_dvref_pu[case.rank] =  0.0
        mtb_s_fref_hz[case.rank] = 50.0

        mtb_s_varef_pu[case.rank] = 0.0
        mtb_s_vbref_pu[case.rank] = 0.0
        mtb_s_vcref_pu[case.rank] = 0.0

        mtb_s_scr[case.rank] = case.SCR0
        mtb_s_xr[case.rank] = case.XR0

        ldf_t_uk[case.rank], ldf_t_pcu_kw[case.rank] = impedance_uk_pcu(case.SCR0, case.XR0, plantSettings.Pn, plantSettings.Un, plantSettings.Uc)

        mtb_t_r0_ohm[case.rank] = plantSettings.R0
        mtb_t_x0_ohm[case.rank] = plantSettings.X0
        
        # Standard plant references and outputs default setup
        mtb_s_pref_pu[case.rank] = case.P0
        
        # Set Qmode
        if case.Qmode.lower() == 'default':
            case.Qmode = plantSettings.Default_Q_mode

        mtb_t_qmode[case.rank] = QMODES[case.Qmode.lower()]

        mtb_s_qref[case.rank] = case.Qref0
        mtb_s_qref_q_pu[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 0 else 0.0
        mtb_s_qref_qu_pu[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 1 else 0.0
        mtb_s_qref_pf[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 2 else 0.0
        mtb_s_qref_3[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 3 else 0.0
        mtb_s_qref_4[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 4 else 0.0
        mtb_s_qref_5[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 5 else 0.0
        mtb_s_qref_6[case.rank] = case.Qref0 if mtb_t_qmode[case.rank].s0 == 6 else 0.0

        if case.QUdroop0.lower() == "default":
            mtb_s_qudroop[case.rank] = plantSettings.Default_QUdroop        
        else:
            mtb_s_qudroop[case.rank] = float(case.QUdroop0)

        mtb_t_pmode[case.rank] = PMODES[case.Pmode.lower()]

        # Fault signals
        flt_s_type[case.rank] = 0.0
        flt_s_rf_ohm[case.rank] = 0.0
        flt_s_resxf[case.rank] = 0.0
        
        # Default custom signal values
        mtb_s[0][case.rank] = 0.0
        mtb_s[1][case.rank] = 0.0
        mtb_s[2][case.rank] = 0.0
        mtb_s[3][case.rank] = 0.0
        mtb_s[4][case.rank] = 0.0
        mtb_s[5][case.rank] = 0.0
        mtb_s[6][case.rank] = 0.0
        mtb_s[7][case.rank] = 0.0
        mtb_s[8][case.rank] = 0.0
        mtb_s[9][case.rank] = 0.0

        # Default OOS references
        ldf_t_refOOS[case.rank] = 0

        # Parse events
        for event in case.Events:
            eventType = event[0]
            eventTime = event[1]
            eventX1 = event[2]
            eventX2 = event[3]

            if eventType == 'Pref':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_pref_pu[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType == 'Qref':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_qref[case.rank].add(eventTime, eventX1, eventX2)

                if mtb_t_qmode[case.rank].s0 == 0:
                    mtb_s_qref_q_pu[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 1:
                    mtb_s_qref_qu_pu[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 2:
                    mtb_s_qref_pf[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 3:
                    mtb_s_qref_3[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 4:
                    mtb_s_qref_4[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 5:
                    mtb_s_qref_5[case.rank].add(eventTime, eventX1, eventX2)
                elif mtb_t_qmode[case.rank].s0 == 6:
                    mtb_s_qref_6[case.rank].add(eventTime, eventX1, eventX2)
                else:
                    raise ValueError('Invalid Q mode')

            elif eventType == 'Voltage':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_vref_pu[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType == 'dVoltage':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_dvref_pu[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType == 'Phase':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_phref_deg[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType == 'Frequency':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_fref_hz[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType == 'SCR':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)
                mtb_s_scr[case.rank].add(eventTime, eventX1, 0.0)
                mtb_s_xr[case.rank].add(eventTime, eventX2, 0.0)

            elif eventType == 'QUdroop':
                assert isinstance(eventX1, float)
                mtb_s_qudroop[case.rank].add(eventTime, eventX1, 0.0)

            elif eventType.count('fault') > 0 and eventType != 'Clear fault':
                assert isinstance(eventX1, float)
                assert isinstance(eventX2, float)

                flt_s_type[case.rank].add(eventTime, FAULT_TYPES[eventType], 0.0)
                flt_s_type[case.rank].add(eventTime + eventX2, 0.0, 0.0)
                flt_s_resxf[case.rank].add(eventTime, eventX1, 0.0)
                if FAULT_TYPES[eventType] < 7:
                    ldf_c_iopt_net[case.rank] = 1
                    inc_c_iopt_net[case.rank] = 'rst'

            elif eventType == 'Clear fault':
                flt_s_type[case.rank].add(eventTime, 0.0, 0.0)

            elif eventType == 'Pref recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                wf = mtb_s_pref_pu[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)
                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                pf_lonRec = max(wf.pfLen, pf_lonRec)

            elif eventType == 'Qref recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                wf = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)

                mtb_s_qref[case.rank] = wf
                mtb_s_qref_q_pu[case.rank] = 0
                mtb_s_qref_qu_pu[case.rank] = 0
                mtb_s_qref_pf[case.rank] = 0
                mtb_s_qref_3[case.rank] = 0
                mtb_s_qref_4[case.rank] = 0
                mtb_s_qref_5[case.rank] = 0
                mtb_s_qref_6[case.rank] = 0

                if mtb_t_qmode[case.rank].s0 == 0:
                    mtb_s_qref_q_pu[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 1:
                    mtb_s_qref_qu_pu[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 2:
                    mtb_s_qref_pf[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 3:
                    mtb_s_qref_3[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 4:
                    mtb_s_qref_4[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 5:
                    mtb_s_qref_5[case.rank] = wf
                elif mtb_t_qmode[case.rank].s0 == 6:
                    mtb_s_qref_6[case.rank] = wf
                else:
                    raise ValueError('Invalid Q mode')

                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                pf_lonRec = max(wf.pfLen, pf_lonRec)

            elif eventType == 'Voltage recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                if mtb_t_vmode[case.rank].s0 != 2:
                    mtb_t_vmode[case.rank] = 1
                wf = mtb_s_vref_pu[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)
                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                pf_lonRec = max(wf.pfLen, pf_lonRec)

            elif eventType == 'Inst. Voltage recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                mtb_t_vmode[case.rank] = 2
                mtb_s_varef_pu[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=False, pscad=pscad)
                mtb_s_vbref_pu[case.rank] = si.Recorded(path=eventX1, column=2, scale=eventX2, pf=False, pscad=pscad)
                wf = mtb_s_vcref_pu[case.rank] = si.Recorded(path=eventX1, column=3, scale=eventX2, pf=False, pscad=pscad)
                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)

            elif eventType == 'Phase recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                wf = mtb_s_phref_deg[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)
                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                pf_lonRec = max(wf.pfLen, pf_lonRec)

            elif eventType == 'Frequency recording':
                assert isinstance(eventX1, str)
                assert isinstance(eventX2, float)
                wf = mtb_s_fref_hz[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)
                pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                pf_lonRec = max(wf.pfLen, pf_lonRec)

            elif eventType.lower().startswith('signal'):
                eventNr = int(eventType.lower().replace('signal','').replace('recording',''))
                customSignal = mtb_s[eventNr - 1] 
                assert isinstance(customSignal, si.Signal)

                if eventType.lower().endswith('recording'):
                    assert isinstance(eventX1, str)
                    assert isinstance(eventX2, float)
                    wf = customSignal[case.rank] = si.Recorded(path=eventX1, column=1, scale=eventX2, pf=pf, pscad=pscad)
                    pscad_lonRec = max(wf.pscadLen, pscad_lonRec)
                    pf_lonRec = max(wf.pfLen, pf_lonRec)
                else:
                    assert isinstance(eventX1, float)
                    assert isinstance(eventX2, float)
                    customSignal[case.rank].add(eventTime, eventX1, eventX2)

            elif eventType  == 'PF disconnect all ref.':
                ldf_t_refOOS[case.rank] = 1

            elif eventType == 'PF force asymmetrical':
                ldf_c_iopt_net[case.rank] = 1
                inc_c_iopt_net[case.rank] = 'rst'

        if isnan(case.Simulationtime) or case.Simulationtime == 0:
            mtb_t_simtimePf_s[case.rank] = pf_lonRec
            mtb_t_simtimePscad_s[case.rank] = pscad_lonRec
            
            if pf_lonRec == 0 and case.RMS:
                warn(f'Rank: {case.rank}. Powerfactory simulationtime set to 0.0s.')
            if pscad_lonRec == 0 and case.EMT:
                warn(f'Rank: {case.rank}. PSCAD simulationtime set to 0.0s.')
        else:
            mtb_t_simtimePscad_s[case.rank] = case.Simulationtime + plantSettings.PSCAD_init_time
            mtb_t_simtimePf_s[case.rank] = case.Simulationtime + plantSettings.PF_flat_time
        
        if not case.EMT:
            mtb_t_simtimePscad_s[case.rank] = -1.0
        else:
            emtCases.append(case)
        
        if isinstance(mtb_s_vref_pu[case.rank], si.Recorded):
            ldf_r_vcNode[case.rank] = ''
        else:
            ldf_r_vcNode[case.rank] = '$nochange$'

    emtCases.sort(key = lambda x: x.Simulationtime)

    taskId = 1
    for emtCase in emtCases:
        mtb_s_task[taskId] = emtCase.rank
        taskId += 1
    mtb_s_task.__pfInterface__ = None
    return plantSettings, channels, cases, maxRank, emtCases