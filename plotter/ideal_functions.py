import sys
import numpy as np
import pandas as pd
from scipy.signal import bilinear, lfilter
from Result import ResultType


def genIdealResults(result, resultData, settingDict, caseDf, pscadInitTime):
    '''
    Generates ideal results for different test cases based on PSCAD simulation data and settings.

    Parameters:
        result: Result object containing result type information.
        resultData: pandas.DataFrame containing simulation data.
        settingDict: dict containing test settings and parameters.
        caseDf: pandas.DataFrame containing case configuration and events.
        pscadInitTime: float, initial time offset from PSCAD simulation.

    Returns:
        dict with keys:
            'figs': list of figure names to plot,
            'signals': list of signal names in the DataFrame,
            'data': pandas.DataFrame with calculated ideal results.
    '''
    
    # Use PSCAD result for calculating the ideal response
    if result.typ in (ResultType.EMT_INF, ResultType.EMT_PSOUT, ResultType.EMT_CSV, ResultType.EMT_ZIP):
        idealData = resultData.rename(columns=dict(zip(resultData.columns, [val.split('\\')[-1] for val in resultData.columns])), inplace=False) # Don't set inplace=True, it will also change the origional DataFrame
        idealData.time = idealData.time - pscadInitTime
        # Active Power Ramping cases
        if 'P_step' in caseDf['Case']['Name'].squeeze():
            P0 = caseDf['Initial Settings']['P0'].squeeze()                     # Initial P0
            assert caseDf['Event 1']['type'].squeeze() == 'Pref'
            Tstep = caseDf['Event 1']['time'].squeeze()
            Pstep = caseDf['Event 1']['X1'].squeeze()
            assert caseDf['Event 1']['X2'].squeeze() == 0.0
            
            idealData.P_pu_PoC = pd.Series([idealPramp(Pref=P0, Tstep=Tstep, Pstep=Pstep, t=t) for t in idealData.time])

            returnDict = {'figs': ['Ppoc'], 'signals': ['P_pu_PoC'], 'data': idealData}

        # LFSM, FSM & RoCoF cases    
        elif  'FSM' in caseDf['Case']['Name'].squeeze() or 'RoCoF' in caseDf['Case']['Name'].squeeze():
            DK = 1 if settingDict['Area']=='DK1' else 2                         # DK area, either 1 or 2
            s_fsm = settingDict['FSM droop']                                    # FSM droop in [%]
            db = settingDict['FSM deadband']                                    # FSM deadband in [Hz]
            P0 = caseDf['Initial Settings']['P0'].squeeze()                     # Initial P0
            FSM = caseDf['Initial Settings']['Pmode'].squeeze() == 'LFSM+FSM'   # FSM mode enabled
            
            # Only apply from t >= 0
            mask = idealData['time'] >= 0            
            newPpocSeries = pd.Series((idealLFSM(Pref=P0, f=f, DK=DK, FSM=FSM, s_fsm=s_fsm, db=db) for f in idealData.loc[mask, 'pll_f_hz']),
                                       index=idealData.loc[mask].index) 
            idealData.loc[mask, 'P_pu_PoC'] = newPpocSeries
            
            # Adding delay and LP filtering 
            #Ts = idealData.time.iloc[1]-idealData.time.iloc[0]
            #Td = 0.5            # delay time [s]
            #trise = 1           # rise time [s]
            #fc = 0.35/trise     # cut off frequency [Hz]
            #idealData.P_pu_PoC_Td = delay(idealData.P_pu_PoC, Td, Ts)
            #idealData.P_pu_PoC_Td_LPF = lpf(idealData.P_pu_PoC, fc, 1/Ts)
            
            #returnDict = {'figs': ['Ppoc', 'Ppoc', 'Ppoc'], 'signals': ['P_pu_PoC', 'P_pu_PoC_Td', 'P_pu_PoC_Td_LPF'], 'data': idealData}
            returnDict = {'figs': ['Ppoc'], 'signals': ['P_pu_PoC'], 'data': idealData}
            
        # Q(U) control cases
        elif 'Ucontrol' in caseDf['Case']['Name'].squeeze():
            U0 = caseDf['Initial Settings']['U0'].squeeze()                     # Initial U0
            s_V_droop = settingDict['V droop']
            Qref0 = 0
            
            # Only apply from t >= 0
            mask = idealData['time'] >= 0            
            newQpocSeries = pd.Series((idealQU(Qref=Qref0, Uref=U0, uag=uag, s=s_V_droop) for uag in idealData.loc[mask,'meas_Vag_pu']),
                                       index=idealData.loc[mask].index)            
            idealData.loc[mask, 'Q_pu_PoC'] = newQpocSeries
            
            returnDict = {'figs': ['Qpoc'], 'signals': ['Q_pu_PoC'], 'data': idealData}
        
        #PF control mode
        elif 'Qpf' in caseDf['Case']['Name'].squeeze():
            P0 = caseDf['Initial Settings']['P0'].squeeze()                     # Initial active power setpoint
            assert caseDf['Initial Settings']['Qmode'].squeeze()  == 'PF'
            Qref0 = caseDf['Initial Settings']['Qref0'].squeeze()               # Initial PF setpoint
            
            if caseDf['Event 1']['type'].squeeze() == 'Pref':   # Pref changes -> slow ramping of Ppoc, thus use Ppoc and not Pref
                idealData.Q_pu_PoC = idealQpf(idealData.P_pu_PoC, Qref0)
            elif caseDf['Event 1']['type'].squeeze() == 'Qref': # PFref changes & Pref constant
                idealData.Q_pu_PoC = idealQpf(idealData.mtb_s_pref_pu, idealData.mtb_s_qref)
                
            returnDict = {'figs': ['Qpoc'], 'signals': ['Q_pu_PoC'], 'data': idealData}
            
            
        # Fast Fault Current contribution cases
        elif 'LVFRT' in caseDf['Case']['Name'].squeeze() or 'Fault' in caseDf['Case']['Name'].squeeze() or 'support' in caseDf['Case']['Name'].squeeze():
            DK = 1 if settingDict['Area']=='DK1' else 2                         # DK area, either 1 or 2
            DSO = True if settingDict['Un']<110 else False                      # DSO, either Energinet (TSO))
    
            # Only apply from t >= 0
            mask = idealData['time'] >= 0            
            newIdIqValues = idealData.loc[mask].apply(lambda t: idealFFC(t.fft_pos_Vmag_pu, t.fft_pos_Id_pu, t.fft_pos_Iq_pu, DK, DSO),
                                                      axis=1,
                                                      result_type='expand')
            idealData.loc[mask, ['fft_pos_Id_pu', 'fft_pos_Iq_pu']] = newIdIqValues.values
            
            returnDict = {'figs': ['Iactive', 'Ireactive'], 'signals': ['fft_pos_Id_pu', 'fft_pos_Iq_pu'], 'data': idealData}

        else:
            returnDict = {'figs': [''], 'signals': [], 'data': pd.DataFrame()}
            
    else:
        returnDict = {'figs': [''], 'signals': [], 'data': pd.DataFrame()}

    return returnDict

def idealQpf(Ppoc, PFref): # Note that PF = Qref0 if Qmode == 'PF'
    theta = np.arccos(PFref)
    Qpoc = Ppoc/np.tan(theta)
    
    return Qpoc
    

# Simple first ordedr Low Pass Filter
def lpf(x, fc, fs):
    wc = 2*np.pi*fc
    b, a = bilinear([0, wc], [1, wc], fs)
    return lfilter(b, a, x)

# Simple signal delay
def delay(x, Td, Ts):
    delay_samples = int(round(Td/Ts))
    b = np.zeros(delay_samples + 1)
    b[delay_samples] = 1    # For a pure delay of N samples, b = [0, 0, ..., 0, 1] (where 1 is at index N)
    a = np.array([1.0])     # For an FIR filter (pure delay), a = [1]
    return lfilter(b, a, x)

# Ideal Active Power Ramping function
def idealPramp(Pref, Tstep, Pstep, t):
    '''
    With Pref in pu, the function calculates the maximum limits on rates of 
    change of active power output (ramping limits) in both an up and down 
    direction of change of active power output for a power-generating module
    based on RfG (EU) 2016/631, 15.6 (e) NC 2025 (Version 4)
    '''
    if Pstep > Pref:
        m =  0.0033   # pu/s - equivalent to 0.2 pu/min
        Pramp = Pref if t <= Tstep else m*t + Pref
        Pramp = Pstep if Pramp >= Pstep else Pramp
    else:
        m = -0.0033
        Pramp = Pref if t <= Tstep else m*t + Pref
        Pramp = Pstep if Pramp <= Pstep else Pramp
        
    return Pramp

# Ideal LFSM function
def idealLFSM(Pref, f, DK=1, FSM=False, s_fsm=10, db=0):
    '''
    With Pref in pu, the function calculates the new value of P given the
    frequency f, according to RfG (EU) 2016/631, 13.2 (a-d) and NC 2025
    (Version 4)for either DK1 or DK2
    * Pref in [pu] -- for Power Park Modules, Pref is the actual Active Power 
      output and not the nominal power
    * LFSM droop, s in [%]
    
    If f > fn (50Hz),
        the output will be the LFSM-O value
    else if f < fn (50Hz),
        it will be the LFSM-U value
    If FSM is True,
        the FSM droop, "s_fsm" has to be specified 
        as well as the deadband, "db" if any
    '''
    Pn = 1.0 #pu
    fn = 50  #Hz
    if DK == 1:
        f1 = 50.2 if f > fn else 49.8
        s = 5
    elif DK == 2:
        f1 = 50.5 if f > fn else 49.5
        s = 4
    else:
        print('"DK" can either be "1" or "2"!')
        return 0
    
    if FSM:
        Pref = idealFSM(Pref, f, DK, s_fsm, db)
        
    if f > fn and f > f1 or f < fn and f < f1:
        Pnew = Pref-100/s*(f-f1)/fn*Pn
    else:
        Pnew = Pref
        
    if Pnew > 1.0:
        Pnew = 1.0
        
    return Pnew

# Ideal FSM function
def idealFSM(Pref, f, DK=1, s=10, db=0):
    '''
    With Pref in pu, the function calculates the new value of P given the
    frequency f, for the FSM droop, s, according to RfG (EU) 2016/631, 15.2 (d)
    and NC 2025 (Version 4)
    * Pref in [pu] -- for Power Park Modules, Pref is the actual Active Power
      output and not the nominal power
    * FSM droop, s in [%]
    * FSM deadband, db in [Hz]
    '''
    Pn = 1.0 #pu
    fn = 50  #Hz
    if DK == 1:
        fRU = 49.8
        fRO = 50.2
    elif DK == 2:
        fRU = 49.5
        fRO = 50.5
    else:
        print('"DK" can either be "1" or "2"!')
        return 0

    f = fRU if f < fRU else f
    f = fRO if f > fRO else f
    
    if f<fn:
        Pnew = Pref-100/s*(f-fn+db)/fn*Pn if f<fn-db else Pref
    else:
        Pnew = Pref-100/s*(f-fn-db)/fn*Pn if f>fn+db else Pref        
    
    return Pnew

# Ideal Q(U) control function
def idealQU(Qref, Uref, uag, s):
    '''
    This function calculates the reactive power required for voltage control
    mode based on RfG (EU) 2016/631, 21.3 (d) NC 2025 (Version 4)
    '''
    Qnom = 0.33
    du = Uref-uag
    dq = 100*du/Uref*Qnom/s
    Qnew = Qref + dq if Qref + dq <= Qnom else Qnom
        
    return Qnew

# Ideal Fast Fault Current contribution function
def idealFFC(vpos_val, id_val, iq_val, DK=1 , DSO=False):
    '''
    This function calculates the fast fault currunt (FFC) contribution,
    id_ffc and iq_ffc, based on the positive sequence voltage magnitude,
    based on RfG (EU) 2016/631, 20.2 (b) NC 2025 (Version 4) for DK1 and DK2
    '''
    if DK == 1:
        vposFrtLimit = 0.85
    elif DK == 2 or DSO:
        vposFrtLimit = 0.9
    else:
        print(f"DK = {DK} is not a valid option!")
        sys.exit(1)
    
    Imax = 1/vposFrtLimit # Could actually be higher
    
    if vpos_val >= vposFrtLimit: # No FRT
        iq_ffc = iq_val
        id_ffc = id_val
    elif vpos_val < vposFrtLimit and vpos_val > 0.5:
        if DK==2 or DSO:
            iq_ffc = -1/0.4*vpos_val+2.25     
        else: # DK==1
            iq_ffc = -1/0.35*vpos_val+2.42857 
            
        id_ffc = np.sqrt(Imax**2-iq_ffc**2)
    else: # vpos_val <= 0.5
        iq_ffc = 1.0
        id_ffc = np.sqrt(Imax**2-iq_ffc**2)
        
    return (id_ffc, iq_ffc) 


