import sys
import numpy as np
import pandas as pd
from scipy.signal import bilinear, lfilter, lfiltic
from Result import ResultType


def genGuideResults(result, resultData, settingsDict, caseDf, pscadInitTime):
    '''
    Generates guide results for different test cases based on PSCAD simulation data and settings.

    Parameters:
        result: Result object containing result type information.
        resultData: pandas.DataFrame containing simulation data.
        settingsDict: dict containing test settings and parameters.
        caseDf: pandas.DataFrame containing case configuration and events.
        pscadInitTime: float, initial time offset from PSCAD simulation.

    Returns:
        dict with keys:
            'figs': list of figure names to plot,
            'signals': list of signal names in the DataFrame,
            'data': pandas.DataFrame with calculated guide results.
    '''
        
    # Use PSCAD result for calculating the guide response
    if result.typ in (ResultType.EMT_INF, ResultType.EMT_PSOUT, ResultType.EMT_CSV, ResultType.EMT_ZIP):
        guideData = resultData.copy()  # Make a copy of the original DataFrame to avoid modifying it directly
        guideData['time'] = guideData.time - pscadInitTime
        
        # Generic LPF settings
        Ts = guideData['time'].iloc[1]-guideData['time'].iloc[0]  # Sampling time
        trise = 0.5                                               # Rise time [s]
        fc = 0.35/trise                                           # Cut-off frequency [Hz]
        
        tThresh = -1                        # Time threshold [s]            
        
        guideFigs = ['']
        guideSignals = ['']
        
        DK = 1 if settingsDict['Area']=='DK1' else 2                             # DK area, either 1 or 2
        DSO = True if settingsDict['Un']<110 else False                          # DSO, either Energinet (TSO))
        if DK == 1 and not DSO:
            vposFrtLimit = 0.85
        elif DK == 2 or DSO:
            vposFrtLimit = 0.9
        else:
            print(f"DK = {DK} is not a valid option!")
            sys.exit(1)

        Pn = settingsDict['Pn']                                                  # Nominal power [MW]         
        P0 = guideData['MTB\\mtb_s_pref_pu'][0]                                  # Initial active power setpoint, P0

        CaseName = caseDf['Case']['Name'].item()                                 # Get the Case Name from the caseDf DataFrame for easier reference
        Qmode = caseDf['Initial Settings']['Qmode'].item()                       # Get the Q control mode from the caseDf DataFrame for easier reference
        
        # Active Power Ramping cases
        if ('P_step' in CaseName or 'PQ/Pn' in CaseName) and not 'Pavail' in CaseName:
            assert caseDf['Event 1']['type'].item() == 'Pref'
            Tstep = caseDf['Event 1']['time'].item()
            Pstep = caseDf['Event 1']['X1'].item()
            assert caseDf['Event 1']['X2'].item() == 0.0
            
            guideData['P_pu_PoC_Ramp'] = pd.Series([guidePramp(Pref=P0, Pn=Pn, Tstep=Tstep, Pstep=Pstep, t=t) for t in guideData.time])
            
            guideFigs.append('Ppoc')
            guideSignals.append('P_pu_PoC_Ramp')
        
        # "Advance" (multi-step) Active Power Ramping cases (with limited Pavailabale cases)
        elif 'Pref-change' in CaseName or 'Pavail_step' in CaseName or 'Pavail_variation' in CaseName:
            guideData['P_pu_PoC_Ramp'] = guideData['MTB\\mtb_s_pref_pu'].clip(upper=guideData['MTB\\mtb_s_pavail_pu']) # Create the active power reference signal clipped to the available power to 'populate' below
            guideData['P_pu_PoC_Ramp'] = guidePramp2(Pref=guideData['P_pu_PoC_Ramp'], Pn=Pn, Pavail=guideData['MTB\\mtb_s_pavail_pu'], Ts=Ts, P=guideData['P_pu_PoC_Ramp'])
            guideFigs.append('Ppoc')
            guideSignals.append('P_pu_PoC_Ramp')                                            

        # LFSM, FSM & RoCoF cases    
        elif 'FSM' in CaseName or 'RoCoF' in CaseName or 'Freq' in CaseName or 'freqStep' in CaseName:
            s_fsm = settingsDict['FSM droop']                                       # FSM droop in [%]
            db = settingsDict['FSM deadband']                                       # FSM deadband in [Hz]
            FSM = caseDf['Initial Settings']['Pmode'].item() == 'LFSM+FSM'          # FSM mode enabled
            Td = 0.2                                                                # Delay time [s]

            guideData['f_hz_Td'] = guideDelay(guideData['MTB\\pll_f_hz'], Td, Ts)   # Delayed the 'pll_f_hz' signal                       
            guideData['f_hz_Td_Lpf'] = guideLPF(guideData['f_hz_Td'], fc, 1/Ts)     # Pass the delayed signal through an LPF

            if 'step' in CaseName and not 'pstep' in CaseName: # Run guideLFSM only for 'step', but not for 'pstep'
                guideData['P_pu_LFSM_FFR'] = guideData['MTB\\mtb_s_pref_pu'].clip(upper=guideData['MTB\\mtb_s_pavail_pu']) # Create the 'dummy' active power reference signal clipped to the available power be to 'overwritten' below
                for i, row in guideData.iterrows():
                    PpuLFSM = guideLFSM(Pref=row['MTB\\mtb_s_pref_pu'], f=row['f_hz_Td_Lpf'], Pavail=row['MTB\\mtb_s_pavail_pu'], DK=DK, FSM=FSM, s_fsm=s_fsm, db=db)
                    guideData.loc[i, 'P_pu_LFSM_FFR'] = PpuLFSM
                                
                guideFigs.append('Ppoc')
                guideSignals.append('P_pu_LFSM_FFR')                                   
            
            guideData['P_pu_LFSM_Ramp'] = guideData['MTB\\mtb_s_pref_pu'].clip(upper=guideData['MTB\\mtb_s_pavail_pu']) # Create the active power reference signal clipped to the available power to 'populate' below
            guideData['P_pu_LFSM_Ramp'] = guideLFSMRamp(Pref=guideData['P_pu_LFSM_Ramp'], Pn=Pn, Pavail=guideData['MTB\\mtb_s_pavail_pu'], Ts=Ts, f=guideData['MTB\\pll_f_hz'], fTdLpf=guideData['f_hz_Td_Lpf'], P=guideData['P_pu_LFSM_Ramp'], DK=DK, FSM=FSM, s_fsm=s_fsm, db=db)
            guideFigs.append('Ppoc')
            guideSignals.append('P_pu_LFSM_Ramp')                                            

            if not 'step' in CaseName or 'pstep' in CaseName: # Run guideLFSM only for 'step', but not for 'pstep'
                Td_2s = 2
                guideData['P_pu_LFSM_Ramp_2s'] = guideDelay(guideData['P_pu_LFSM_Ramp'], Td_2s, Ts)
                guideFigs.append('Ppoc')
                guideSignals.append('P_pu_LFSM_Ramp_2s')       
                                                     
        # SIPS cases
        elif 'SIPS' in CaseName:
            if 'MTB\\mtb_s_sips_g' not in guideData.columns:
                raise KeyError("Missing required signal: 'MTB\\mtb_s_sips_g'")

            # Decode SIPS command -> active power ceiling (pu)
            guideData['P_pu_PoC_SIPS_ref'] = guideSIPS(
                Pref=guideData['MTB\\mtb_s_pref_pu'],
                SIPSg=guideData['MTB\\mtb_s_sips_g']
            )

            # 0 s delay + ~1 Hz response
            fc_sips_fast = 1.0
            guideData['P_pu_PoC'] = guideLPF(guideData['P_pu_PoC_SIPS_ref'], fc_sips_fast, 1 / Ts)
            guideData.loc[guideData['time'] < tThresh, 'P_pu_PoC'] = P0

            # 1 s delay + ~0.1 Hz response (10 s)
            Td_sips = 1.0
            fc_sips_slow = 0.1
            guideData['P_pu_PoC_1s'] = guideLPF(
                guideDelay(guideData['P_pu_PoC_SIPS_ref'], Td_sips, Ts),
                fc_sips_slow,
                1 / Ts
            )
            guideData.loc[guideData['time'] < tThresh, 'P_pu_PoC_1s'] = P0

            guideFigs.extend(['Ppoc', 'Ppoc'])
            guideSignals.extend(['P_pu_PoC', 'P_pu_PoC_1s'])

        # Default case for PoC active power guide signal           
        elif 'SIPS' not in CaseName and 'Fault' not in CaseName and 'LVFRT' not in CaseName:
            guideData['P_pu_PoC'] = guideData['MTB\\mtb_s_pref_pu']
            guideFigs.append('Ppoc')
            guideSignals.append('P_pu_PoC')  
            
        Qdefault = settingsDict['Default Q mode']                
        # Q control cases
        if Qmode == 'Q' or (Qmode == 'Default' and Qdefault == 'Q'):
            Qref0 = caseDf['Initial Settings']['Qref0'].item()                  # Initial reactive power setpoint, when Qmode == 'Q'
            
            guideData['Q_pu_Q_Ctrl'] = guideLPF(guideData['MTB\\mtb_s_qref'], fc, 1/Ts) # Guide response == Qref passed through a LPF      
            guideData.loc[guideData['time'] < tThresh, 'Q_pu_Q_Ctrl'] = Qref0           # Set values for t < tThresh
            guideFigs.append('Qpoc')
            guideSignals.append('Q_pu_Q_Ctrl')  

        # Q(U) control cases
        if Qmode == 'Q(U)' or (Qmode == 'Default' and  Qdefault == 'Q(U)'):
            Qref0 = 0.0                                                         # Note: This is the initial reactive power reference

            # Change LPF setting for Upos
            trise_Upos = 0.025                                                  # Rise time [s]
            fc_Upos = 0.35/trise_Upos                                           # Cut-off frequency [Hz]

            # Implement a LPF on the Upos to slow down the Q(U) response during an "instantaneous" LVFRT event
            guideData['fft_pos_Vmag_pu_lpf'] = guideLPF(guideData['MTB\\fft_pos_Vmag_pu'], fc_Upos, 1/Ts)
            
            guideData['Q_pu_QU_Inst'] = Qref0      # Create new signal to populate
            Qprev = Qref0
            for i, row in guideData.iterrows():
                if row['time'] < tThresh:
                    guideData.loc[i, 'Q_pu_QU_Inst'] = Qref0
                    continue

                if row['fft_pos_Vmag_pu_lpf'] > vposFrtLimit:  # No FRT
                    Qnow = guideQU(
                        Uref=row['MTB\\mtb_s_qref'],
                        Upos=row['fft_pos_Vmag_pu_lpf'],
                        s=row['MTB\\mtb_s_qudroop'],
                        Qref=Qref0
                    )
                    guideData.loc[i, 'Q_pu_QU_Inst'] = Qnow
                    Qprev = Qnow
                else:
                    guideData.loc[i, 'Q_pu_QU_Inst'] = Qprev
                
            # Change LPF setting for Q(U)
            trise_QU = 0.95                                                     # Rise time [s]
            fc_QU = 0.35/trise_QU                                               # Cut-off frequency [Hz]

            guideData['Q_pu_QU_Ctrl'] = guideLPF(guideData['Q_pu_QU_Inst'], fc_QU, 1/Ts)            
            guideFigs.append('Qpoc')
            guideSignals.append('Q_pu_QU_Ctrl')  
            
        #PF control mode
        if Qmode == 'PF' or (Qmode == 'Default' and Qdefault == 'PF'):
            PFref0 = caseDf['Initial Settings']['Qref0'].item()              # Initial PF setpoint, Qref0, when Qmode == 'PF'
            
            if caseDf['Event 1']['type'].item() == 'Pref':   # Pref changes -> slow ramping of Ppoc, thus use Ppoc and not Pref
                Ppoc = guideData['P_pu_PoC_Ramp'] if 'P_pu_PoC_Ramp' in guideData.columns else guideData['MTB\\mtb_s_pref_pu'] # Safety check to ensure that the 'P_pu_PoC_Ramp' column exists in the DataFrame before using it
                guideData['Q_pu_Qpf_Inst'] = guideQpf(Ppoc=Ppoc, PFref=PFref0)
            elif caseDf['Event 1']['type'].item() == 'Qref': # PFref changes & Pref constant
                guideData['Q_pu_Qpf_Inst'] = guideQpf(Ppoc=guideData['MTB\\mtb_s_pref_pu'], PFref=guideData['MTB\\mtb_s_qref']) # Note that 'MTB\mtb_s_qref' = PF if Qmode == 'PF'
            else: # Use Initial settings
                guideData['Q_pu_Qpf_Inst'] = guideQpf(Ppoc=P0, PFref=PFref0)
                
            guideData['Q_pu_Qpf_Ctrl'] = guideLPF(guideData['Q_pu_Qpf_Inst'], fc, 1/Ts)            
            guideData.loc[guideData['time'] < tThresh, 'Q_pu_Qpf_Ctrl'] = P0*np.tan(np.arccos(PFref0))      # Set values for t < tThresh
            guideFigs.append('Qpoc')
            guideSignals.append('Q_pu_Qpf_Ctrl')  
                        
        # Fast Fault Current contribution cases
        if 'FRT' in CaseName or 'Fault' in CaseName or 'support' in CaseName:
            Iq0 = 0
            V_EPS = 1e-6
            guideData['Iq_pu_FFC_Inst'] = 0.0    # Create new signal to populate
            for i, row in guideData.iterrows():
                if row['time'] < tThresh:
                    continue
                
                vpos = row['MTB\\fft_pos_Vmag_pu']
                if not np.isfinite(vpos):
                    guideData.loc[i, 'Iq_pu_FFC_Inst'] = Iq0
                    continue
                
                if vpos >= vposFrtLimit:
                    denom = max(vpos, V_EPS)  # protect against divide-by-zero / bad values

                    # This assumes the guide Iq = Qpoc/Upos
                    if Qmode == 'Q' or (Qmode == 'Default' and Qdefault == 'Q'):            
                        Iq0 =  row['Q_pu_Q_Ctrl']/denom
                    if Qmode == 'Q(U)' or (Qmode == 'Default' and Qdefault == 'Q(U)'):
                        Iq0 =  row['Q_pu_QU_Inst']/denom
                    if Qmode == 'PF' or (Qmode == 'Default' and Qdefault == 'PF'):
                        Iq0 =  row['Q_pu_Qpf_Ctrl']/denom
                        
                IqFFC = guideFFC(Upos=vpos, Iq0 = Iq0, DK=DK, DSO=DSO)
                    
                guideData.loc[i, 'Iq_pu_FFC_Inst'] = IqFFC                                     
            
            # Change LPF setting for Iq
            trise_FFC = 0.025                                                   # Rise time [s]
            fc_FFC = 0.35/trise_FFC                                             # Cut-off frequency [Hz]

            guideData['Iq_pu_FFC'] = guideLPF(guideData['Iq_pu_FFC_Inst'], fc_FFC, 1/Ts)            
            guideFigs.append('Ireactive')
            guideSignals.append('Iq_pu_FFC')  

        returnDict = {'figs': guideFigs, 'signals': guideSignals, 'data': guideData}
            
    else:
        returnDict = {'figs': [''], 'signals': [], 'data': pd.DataFrame()}

    return returnDict


def guideLPF(x, fc, fs):
    '''
    Simple first order low pass filter with cut off frequency fc and sampling frequency fs

    Parameters:
        x: input signal 
        fc: cut off frequency in Hz
        fs: sampling frequency in Hz
    
    Returns:
        filtered signal 
    '''
    wc = 2*np.pi*fc
    b, a = bilinear([0, wc], [1, wc], fs)
    zi = lfiltic(b, a, y=x, x=x)    # Calculate flfilter's initial condition
    y, zf = lfilter(b, a, x, zi=zi) # zf holds the final filter delay values and is required with 'zi', but not used

    return y


def guideDelay(x, Td, Ts):
    '''
    Simple signal delay of Td seconds with sampling time Ts

    Parameters:
        x: input signal
        Td: delay time in seconds
        Ts: sampling time in seconds

    Returns:
        delayed signal
    '''
    delay_samples = int(round(Td/Ts))
    if delay_samples <= 0:
        return x  # No delay needed, return original signal

    x_arr = np.asarray(x)
    y = np.empty_like(x_arr)
    
    # Hold initial value before delayed samples become available
    y[:delay_samples] = x_arr[0]
    y[delay_samples:] = x_arr[:-delay_samples]

    if isinstance(x, pd.Series):
        return pd.Series(y, index=x.index)
    return y


def guidePramp(Pref, Pn, Tstep, Pstep, t):
    '''
    This function calculates the guide or maximum rates of change of 
    active power output (Pramp) in both an up and down direction of for 
    a change in the active power reference for power-generating modules
    based on RfG (EU) 2016/631, 15.6 (e) NC 2025 (Version 4)

    Parameters:
        Pref in [pu] -- for Power Park Modules, Pref is Active Power reference *before ramping* 
        Pn in [MW] -- nominal power rating of the Power Park
        Tstep in [s] -- time step for the ramping
        Pstep in [pu] -- the new reference value of the Active Power *after ramping*   
        t in [s] -- time at which the new value of P is calculated

    Returns:
        Pramp in [pu] -- the new value of P after the ramping
    '''
    m = min(0.2, 60/Pn)  # Limit the ramping to the minimum of either 0.2 pu/min or 60 MW/min
    if Pstep > Pref:
        m =  m/60  # convert to pu/s
        Pramp = Pref if t <= Tstep else m*(t-Tstep) + Pref
        Pramp = Pstep if Pramp >= Pstep else Pramp # Ensure Pramp does not exceed the new reference value (Pstep)
    else:
        m = -m/60  # convert to pu/s
        Pramp = Pref if t <= Tstep else m*(t-Tstep) + Pref
        Pramp = Pstep if Pramp <= Pstep else Pramp # Ensure Pramp does not go below the new reference value (Pstep)
        
    return Pramp

def guidePramp2(Pref, Pn, Pavail, Ts, P):
    '''
    This function calculates the guide or maximum rates of change of 
    active power output (Pramp) in both an up and down direction of for 
    a change in the active power reference for power-generating modules
    based on RfG (EU) 2016/631, 15.6 (e) NC 2025 (Version 4)
    
    Parameters:
        Pref in [pu] -- the Active Power reference setpoint allready clipped to Pavail
        Pn in [MW] -- nominal power rating of the Power Park
        Pavail in [pu] -- the limited power available
        Ts in [s] -- sampling time   
        P in [pu] -- the Active Power output to be updated by the function

    Returns:
        P in [pu] -- the new value of P after ensuring the ramping rate is not too high
    '''
    
    PThresh = 0.0001      # Active power threshold
    m = min(0.2, 60/Pn)   # Limit the ramping to the minimum of either 0.2 pu/min or 60 MW/min
    m = m/60              # Convert pu/min to pu/s
       
    # Convert Pandas Series to Numpy Array for added speed in doing difference equations below
    Pref_array = np.asarray(Pref)
    Pavail_array = np.asarray(Pavail)
    P_array = np.asarray(P)
    
    for k in range(1, len(P)):
        if np.abs(Pref_array[k] - P_array[k-1]) > PThresh:
            if Pref_array[k] - P_array[k-1] > 0:  # If P needs to increasing
                P_array[k] = m*Ts + P_array[k-1]
                if P_array[k] > Pref_array[k]:  # Ensure P does not exceed Pref / Pavail
                    P_array[k] = Pref_array[k]
            else: # If P needs to decreasing
                P_array[k] = -m*Ts + P_array[k-1]
                if P_array[k] < Pref_array[k]:  # Ensure P does not go below Pref
                    P_array[k] = Pref_array[k]
                if P_array[k] > Pavail_array[k]:  # Ensure P is clamped to Pavail if Pavail goes down suddenly
                    P_array[k] = Pavail_array[k]
        else: # Maintain current value of P
            P_array[k] = P_array[k-1]            
        
    if isinstance(P, pd.Series):
        return pd.Series(P_array, index=P.index)
    else:
        return P_array

def guideLFSMRamp(Pref, Pn, Pavail, Ts, f, fTdLpf, P, DK, FSM, s_fsm, db):
    '''
    This function ensures that the active power output (P) does not
    change too fast when the frequency (f) is close to the nominal frequency (fn)
    based on RfG (EU) 2016/631, 13.2 (e) NC 2025 (Version 4)
    
    Parameters:
        Pref in [pu] -- the Active Power reference setpoint 
        Pn in [MW] -- nominal power rating of the Power Park
        Pavail in [pu] -- the limited power available
        Ts in [s] -- sampling time   
        f in [Hz] -- the actual frequency
        fTdLpf in [Hz] -- the delayed and low-pass filtered frequency
        P in [pu] -- the Active Power output to be updated by the function
        DK [1,2] -- the Danish area, either 1 or 2
        FSM  [True, False] -- if True, the function will use the FSM droop and deadband
        s_fsm in [%] -- the FSM droop in [%]
        db in [Hz] -- the FSM deadband in [Hz]
        
    Returns:
        P in [pu] -- the new value of P after ensuring the ramping rate is not too high
    '''
    
    fLower = 0.020        # Lower hysteresis frequency threshold
    fUpper = 0.040        # Upper hysteresis frequency threshold
    PThresh = 0.0001      # Active power threshold
    m = min(0.2, 60/Pn)   # Limit the ramping to the minimum of either 0.2 pu/min or 60 MW/min
    m = m/60              # Convert pu/min to pu/s
    fn = 50.0             # Nominal frequency in Hz
    
    # Hysteresis band LOWER and UPPER band switches assuming we start at fn
    LOWER = True        
    UPPER = False
    
    # Convert Pandas Series to Numpy Array for added speed in doing difference equations below
    Pref_array = np.asarray(Pref)
    Pavail_array = np.asarray(Pavail)
    P_array = np.asarray(P)
    f_array = np.asarray(f)
    fTdLpf_array = np.asarray(fTdLpf)
    
    Pref=Pref_array[0]
    for k in range(1, len(P)):
        # Activate active power ramping if the frequency is close to the nominal frequency
        if np.abs(f_array[k] - fn) > fUpper:
            UPPER = True
            LOWER = False
        elif np.abs(f_array[k] - fn) < fLower:
            LOWER = True
            UPPER = False
        if LOWER:    # Ramping active
            if np.abs(Pref_array[k] - P_array[k-1]) > PThresh:
                if Pref_array[k] - P_array[k-1] > 0:  # If P needs to increasing
                    P_array[k] = m*Ts + P_array[k-1]
                    if P_array[k] > Pref_array[k]:  # Ensure P does not exceed Pref
                        P_array[k] = Pref_array[k]
                else: # If P needs to decreasing
                    P_array[k] = -m*Ts + P_array[k-1]
                    if P_array[k] < Pref_array[k]:  # Ensure P does not go below Pref
                        P_array[k] = Pref_array[k]
            else:   # Maintain current value of P
                P_array[k] = P_array[k-1]
            Pref = P_array[k] # The new reference is the current P value
        elif UPPER:   # LFSM active
            P_array[k] = guideLFSM(Pref=Pref, f=fTdLpf_array[k-1], Pavail=Pavail_array[k], DK=DK, FSM=FSM, s_fsm=s_fsm, db=db)
        else: # Trapped inbetween hystersis band
            print('How the hell did we end up trapped in the hysteresis loop!!')
            sys.exit(1)
    
    if isinstance(P, pd.Series):
        return pd.Series(P_array, index=P.index)
    else:
        return P_array


def guideLFSM(Pref, f, Pavail=1.0, DK=1, FSM=False, s_fsm=10, db=0):
    '''
    This function calculates the new value of P given the
    frequency f, according to RfG (EU) 2016/631, 13.2 (a-d) and NC 2025
    (Version 4) for either DK1 or DK2

    Parameters:
        Pref in [pu] -- for Power Park Modules, Pref is the actual Active Power output     
        f in [Hz] -- the actual frequency at the point of connection
        Pavail in [pu] -- the limited power available
        DK in [1,2] -- the Danish area, either 1 or 2
        FSM in [True, False] -- if True, the function will use the FSM droop and deadband
        s_fsm in [%] -- the FSM droop in [%]
        db in [Hz] -- the FSM deadband in [Hz]

        If f > fn (50Hz),
            the output will be the LFSM-O value
        else if f < fn (50Hz),
            it will be the LFSM-U value
        If FSM is True,
            the FSM droop, "s_fsm" has to be specified 
            as well as the deadband, "db" if any

    Returns:
        Pnew in [pu] -- the new value of P after the frequency change
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
        Pref = guideFSM(Pref, f, DK, s_fsm, db)
        
    if f > fn and f > f1 or f < fn and f < f1:
        Pnew = Pref-100/s*(f-f1)/fn*Pn
    else:
        Pnew = Pref
        
    if Pnew >= Pavail:
        Pnew = Pavail  # Limit Active Power to Pavail
    elif Pnew <= 0.0:
        Pnew = 0.0  # Limit Active Power to 0.0 pu

    return Pnew


def guideFSM(Pref, f, DK=1, s=10, db=0):
    '''
    With Pref in pu, the function calculates the new value of P given the
    frequency f, for the FSM droop, s, according to RfG (EU) 2016/631, 15.2 (d)
    and NC 2025 (Version 4)

    Parameters:
        Pref in [pu] -- for Power Park Modules, Pref is the actual Active Power output and not the nominal power
        f in [Hz] -- the actual frequency at the point of connection
        DK in [1,2] -- the Danish area, either 1 or 2
        s in [%] -- the FSM droop in [%]
        db in [Hz] -- the FSM deadband in [Hz]

    Returns:
        Pnew in [pu] -- the new value of P after the frequency change 
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
    
    # Clamp Pnew to to be not exceed Pref by +/- 10%
    if Pnew > Pref+0.1*Pn: Pnew = Pref+0.1*Pn
    if Pnew < Pref-0.1*Pn: Pnew = Pref-0.1*Pn
    
    return Pnew


def guideQU(Uref, Upos, s, Qref=0.0):
    '''
    This function calculates the value of the reactive power required, Qpoc_QU, 
    for voltage control mode based on RfG (EU) 2016/631, 21.3 (d) NC 2025
    (Version 4)

    Parameters:
        Uref in [pu] -- the voltage reference at the point of connection
        Upos in [pu] -- the magnitude of the positive sequence voltage at the 
                        point of connection
                        TODO: Legacy suppor for Terminal (LV/MV ?)
        s in [%]     -- the voltage droop of the Q(U) control   
        Qref in [pu] -- the Reactive Power reference/offset (which by default is zero)

    Returns:
        Qpoc_QU in [pu] -- the new value of Q at the point of connection
    '''
    Qnom = 0.33     # TODO: Qnom should be the actual Qnom of the plant
    
    dU = Uref-Upos
    dQ = 100*dU/Uref*Qnom/s      
    if Qref + dQ > Qnom:
        Qpoc_QU = Qnom
    elif Qref + dQ < -Qnom:
       Qpoc_QU = -Qnom 
    else:
        Qpoc_QU = Qref + dQ
        
    return Qpoc_QU


def guideQpf(Ppoc, PFref): 
    '''
    This function calculates the guide reactive power output (Qpoc) based on the active power output (Ppoc)
    and the power factor reference (PFref) according to RfG (EU) 2016/631, 21.3 (d) NC 2025 (Version 4)

    Parameters:
        Ppoc in [pu] -- the actual Active Power output at the point of connection
        PFref in [pu] -- the power factor reference

    Returns:
        Qpoc in [pu] -- the new value of Q at the point of connection
    '''
    Qnom = 0.33     # TODO: Qnom should be the actual Qnom of the plant

    theta = np.arccos(PFref)
    Qpoc = np.clip(Ppoc*np.tan(theta), -Qnom, Qnom)  # Ensure Qpoc is within [-0.33, 0.33] range
                    
    return Qpoc
    

def guideFFC(Upos, Iq0, DK, DSO):
    '''
    This function calculates the fast fault current (FFC) contribution, Iq, based on the positive sequence voltage, Upos
    based on RfG (EU) 2016/631, 20.2 (b) NC 2025 (Version 4) for DK1 and DK2
    
    Parameters:    
        Upos in [pu] -- the positive sequence voltage magnitude at the point of connection
        DK in [1,2] -- the Danish area, either 1 or 2
        Iq0 in [pu] -- the Iq value just before FRT is entered 
        DSO in [True, False] -- if True, the function will use the DSO voltage limit of 0.9 pu, otherwise it will use the TSO voltage limit of 0.85 pu for DK1
    Returns:
        IqFFC in [pu] -- the required positive sequence, quadrature current at the point of connection

    '''
    if DK == 2 or DSO:
        vposFrtLimit = 0.9  # NC 2025 (Version 4) for DK2 or for DSO cases
        m = 1/0.4
        c = 2.25
    else: # DK1
        vposFrtLimit = 0.85 # NC 2025 (Version 4) for DK1
        m = 1/0.35
        c = 2.42857
       
    if Upos >= vposFrtLimit: # No FRT
        IqFFC = Iq0     # Iq is unchanged
    else:
        if Upos < vposFrtLimit and Upos > 0.5:
            IqFFC = -m*Upos + c + Iq0
        else: # Upos <= 0.5
            IqFFC = 1.0 + Iq0
        
    return IqFFC


def guideSIPS(Pref, SIPSg, step_setpoints=None):
    '''
    Decode MTB SIPS bitfield and return commanded active power ceiling.

    Bit 0: reserved
    Bit 1..N: SIPS steps
    Default Energinet steps:
      1 -> 0.70 pu
      2 -> 0.50 pu
      3 -> 0.40 pu
      4 -> 0.25 pu
      5 -> 0.00 pu

    If multiple steps are active, the lowest reduction is used
    (i.e., highest remaining power setpoint among active bits).
    '''
    if step_setpoints is None:
        step_setpoints = {1: 0.70, 2: 0.50, 3: 0.40, 4: 0.25, 5: 0.00}

    pref = np.asarray(Pref, dtype=float)
    g = np.asarray(SIPSg)
    g = np.nan_to_num(g, nan=0.0)
    g = np.rint(g).astype(np.int64)

    best_setpoint = np.zeros_like(pref, dtype=float)
    any_active = np.zeros_like(pref, dtype=bool)

    for bit, setpoint in step_setpoints.items():
        active = ((g >> bit) & 1) == 1
        best_setpoint = np.where(active, np.maximum(best_setpoint, setpoint), best_setpoint)
        any_active = np.logical_or(any_active, active)

    limit = np.where(any_active, best_setpoint, 1.0)
    sips_pref = np.minimum(pref, limit)

    if isinstance(Pref, pd.Series):
        return pd.Series(sips_pref, index=Pref.index)
    return sips_pref