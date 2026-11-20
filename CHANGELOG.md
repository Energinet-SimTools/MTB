# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - Unreleased

### Added

#### PSCAD

- `PSCAD version` setting in `config.ini` to select the PSCAD version launched when running as an external client ([#322](https://github.com/Energinet-SimTools/MTB/pull/322))

#### Plotter

- `sharedXaxis` option in the plotter `config.ini` to link x-axis zoom, pan and reset across all plots within each HTML page ([#348](https://github.com/Energinet-SimTools/MTB/pull/348), [#364](https://github.com/Energinet-SimTools/MTB/pull/364))
- Guide curves for RMS (PowerFactory) results: if a case has no EMT result, the guide curves are calculated from the RMS result. The MTB reference signals in the PowerFactory result (e.g. `mtb_s_pref_pu.ElmDsl` `s:yo`) are mapped to the guide signals, the PF flat time is removed and the result is resampled to a fixed time step with sample-and-hold, so event steps are kept as steps. RMS cases without the MTB reference signals (e.g. with the event `PF disconnect all ref.`) get no guide curves

### Changed

#### Configuration

- `config.ini` now states that only PSCAD 5.0.2 is currently supported, with 5.1.0 being experimental; the default `PSCAD version` is 5.0.2 ([#363](https://github.com/Energinet-SimTools/MTB/pull/363))

#### Plotter

- Maximum number of HTML columns increased to 4 ([#354](https://github.com/Energinet-SimTools/MTB/pull/354))
- `PdfWriter` is now only imported when PDF generation is needed ([#354](https://github.com/Energinet-SimTools/MTB/pull/354))
- Guide curves are drawn once per case: from the first EMT result, or from the first RMS result if there is no EMT result (previously for every EMT result)
- A guide curve whose input signals are missing in the result is skipped with a warning, e.g. `Warning: Guide 'SIPS' skipped - missing signal(s): MTB\mtb_s_sips_g`, instead of stopping the plotter; the other guide curves of the case are still drawn
- The P step and PF control guide curves find the `Pref`/`Qref` events by event type in any `Event N` column, instead of assuming `Event 1`
- `genGuideResults()` no longer has the `pscadInitTime` parameter; the PSCAD initialisation time and PF flat time are taken from the testcase settings
- The cursor metric formatting is moved to `formatCursorMetric()` in `cursor_functions.py`, so it can be reused for other cursor intervals and front ends
- The generic `.psout` functions `getPsoutSignalRecords()`, `listPsoutSignals()` and `getAllPsoutSignals()` are moved from `convert_psout_to_csv.py` to `process_psout.py`. They use the real signal paths in the `.psout` file; the MTB naming (`MTB\<signal>`, also when the MTB is not placed on the main canvas) is applied separately with `findMtbPath()`, `toMtbSignalName()` and `fromMtbSignalName()` in `process_results.py`, which also has `getAllMtbSignals()` and `getFigureSetupSignals()` to read all signals or the figureSetup signals of a `.psout` file with MTB naming
- The plotter is about 16 times faster, with identical results:
  - The row-by-row loops for the LFSM, Q(U) and FFC guide curves in `guide_functions.py` now use NumPy arrays
  - `getPsoutSignals()` in `process_psout.py` opens the `.psout` file once instead of once per signal (also used by `convert_psout_to_csv.py`)

  Plotter time per case (`.psout` results, HTML with guide curves and cursors, `processes = 1`, no images):

  | Case | Type | 2.0.0 [s] | 2.0.1 [s] | Speed-up |
  | ---- | ---- | --------: | --------: | -------: |
  | 1 | Flat run | 2.4 | 1.4 | 1.7x |
  | 11 | P step, Q(U) control | 32.6 | 1.2 | 28x |
  | 17 | FSM step, Q(U) control | 29.1 | 0.9 | 34x |
  | 41 | FRT, Q(U) control | 22.7 | 0.9 | 25x |
  | 57 | SIPS | 1.2 | 0.9 | 1.3x |
  | 104 | Q(U) droop | 11.7 | 0.9 | 13x |
  | **Total** | | **99.6** | **6.2** | **16x** |

  Cases with Q(U) control, LFSM/FSM or FRT guide curves benefit most. With `processes` > 1 the cases run in parallel, so the total run time is reduced correspondingly

#### Utility Scripts

- `plotter/psout_to_csv.py` moved to `utility_scripts/` and renamed to `convert_psout_to_csv.py`. The script now locates `process_psout.py` in the `plotter` folder automatically, and the default `--figureSetupPath` is `..\plotter\figureSetup.csv` ([#369](https://github.com/Energinet-SimTools/MTB/pull/369))
- `convert_psout_to_csv.py`: `--psoutFolder` is now required and the script exits with an error if the folder is missing or contains no `.psout` files. If `--figureSetupPath` is omitted, all PGB output channel signals are extracted. The default `--outputRootFolder` is now the parent folder of `--psoutFolder`, the output folder is printed on completion, and a new `--decimal` option selects `,` (with `;` column separator, default) or `.` (with `,` column separator). A new `--list` option lists all PGB output channel signals in the first `.psout` file. MTB signals are always written (and listed) as `MTB\<signal>`, also when the MTB is not placed on the main canvas

### Removed

#### Utility Scripts

- `list_psout_signals.py` removed; use `convert_psout_to_csv.py --list` instead

### Fixed

#### PSCAD

- Fixed recorded waveform files (`recordings_scaled\*.out`) not being found by EMTDC when the `.pswx` and `.pscx` files are in different folders; file paths are now resolved relative to the project build folder ([#367](https://github.com/Energinet-SimTools/MTB/pull/367))
- Fixed MTB PGBs being disabled by the PGB synchronization when the MTB is not on the main canvas ([#360](https://github.com/Energinet-SimTools/MTB/pull/360))
- Fixed `FFT_TRACKING` output when the frequency input is 0 at the first time step. This occurs when the frequency signal is transmitted via a radio link (transmitter and receiver(s)) from the canvas where the MTB is located to the canvas where the measurement units are located ([#359](https://github.com/Energinet-SimTools/MTB/pull/359))

#### Plotter / HTML Reports

- Fixed plotter when the MTB is located on a canvas named e.g. `MTB_1`, `MTB_2` ([#362](https://github.com/Energinet-SimTools/MTB/pull/362))
- Fixed plotter for DSO cases where `mtb_s_pavail_pu` is not present; `mtb_s_pref_pu` is used instead ([#355](https://github.com/Energinet-SimTools/MTB/pull/355))
- Fixed layout when the configured number of HTML columns exceeds the maximum allowed ([#354](https://github.com/Energinet-SimTools/MTB/pull/354))
- Blank rows in the figure and cursor setup files (e.g. from Excel) are now skipped ([#358](https://github.com/Energinet-SimTools/MTB/pull/358))
- Improved error message when the MTB path is not found in a `.psout` file; the plotter now exits with code 1 ([#356](https://github.com/Energinet-SimTools/MTB/pull/356))
- Clarified comments in `getUniqueEmtSignals` ([#357](https://github.com/Energinet-SimTools/MTB/pull/357))
- The Q(U) t1 cursor metric now shows "metric error" instead of the text of the previous metric when it cannot be calculated
- EMT `.csv`/`.zip` results (e.g. from `convert_psout_to_csv.py`) are now matched on the full signal path, e.g. `MTB\P_pu_PoC`, as for `.psout` files; previously only the last part of the name was used, so their signals were not found. Matching on the signal name only is kept for legacy (MTB 1.0) `.inf` results
- `genGuide` is set to `False` (with a warning) when legacy `.inf` results are found, as guide curves are not supported for them; the plotter previously stopped with a `KeyError`
- Fixed wrong column names in `getPsoutSignals()` when a signal array (a signal with several traces) is not the first signal; the array names were inserted at the start, shifting the names of the other signals

#### General

- `execute_pscad.py` and `execute_pf.py` now check that the casesheet file exists and print a clear error if it does not ([#366](https://github.com/Energinet-SimTools/MTB/pull/366))
- The plotter now checks that each folder in `[Simulation data paths]` exists and prints an error for every missing folder ([#365](https://github.com/Energinet-SimTools/MTB/pull/365))

---

## [2.0.0] - 2026-09-17

### Added

#### New Signals and Parameters

- Q(U) droop signal (`QuDroop`) and `Qudroop0` initial setting for reactive power control ([#202](https://github.com/Energinet-SimTools/MTB/pull/202))
- Available power signal (`Pavail`) and `Pavail0` initial setting ([#202](https://github.com/Energinet-SimTools/MTB/pull/202))
- Main Transformer Grounding parameter (`MtrfrGnd`) with `MtrfrGnd0` initialization and output signal ([#202](https://github.com/Energinet-SimTools/MTB/pull/202))

#### SIPS (System Protection Scheme)

- Dedicated MTB SIPS signal (`mtb_s_sips`) and Integer-to-Binary decoder block in PowerFactory and PSCAD ([#302](https://github.com/Energinet-SimTools/MTB/pull/302))
- `SIPS_future_use` bit for future arming/enable logic, replacing `SIPS_notused` ([#311](https://github.com/Energinet-SimTools/MTB/pull/311))
- Separate generation and demand SIPS signals: `mtb_SIPS_g` (`out_sips_g`) and `mtb_SIPS_d` (`out_sips_d`), replacing the single `mtb_SIPS` signal ([#310](https://github.com/Energinet-SimTools/MTB/pull/310))
- SIPS demand test cases (1043, 1044, 1087, 1088) added to `figureSetup.csv` and `testcases.xlsx` ([#317](https://github.com/Energinet-SimTools/MTB/pull/317))
- `guideSIPS` function in the plotter for active power ceiling decoding from SIPS binary output ([#300](https://github.com/Energinet-SimTools/MTB/pull/300), [#317](https://github.com/Energinet-SimTools/MTB/pull/317))
- Ramping logic for SIPS release and reduction in `guideSIPS` ([#325](https://github.com/Energinet-SimTools/MTB/pull/325))
- Delayed SIPS ramp-down logic via `guideSIPS2` with configurable delay and linear down-ramp ([#328](https://github.com/Energinet-SimTools/MTB/pull/328), [#329](https://github.com/Energinet-SimTools/MTB/pull/329))
- SIPS figures with y-labels and PGB templates for generation and demand in `figureSetup.csv` ([#302](https://github.com/Energinet-SimTools/MTB/pull/302), [#317](https://github.com/Energinet-SimTools/MTB/pull/317))

#### Plotter

- Anlytical guide curves overlaid on figures ([#188](https://github.com/Energinet-SimTools/MTB/pull/188)–[#200](https://github.com/Energinet-SimTools/MTB/pull/200))
- Multiprocessing support in the plotter for significantly faster calculation of the analytical guide curves ([#229](https://github.com/Energinet-SimTools/MTB/pull/229), [#230](https://github.com/Energinet-SimTools/MTB/pull/230), [#231](https://github.com/Energinet-SimTools/MTB/pull/231), [#232](https://github.com/Energinet-SimTools/MTB/pull/232), [#233](https://github.com/Energinet-SimTools/MTB/pull/233), [#234](https://github.com/Energinet-SimTools/MTB/pull/234), [#235](https://github.com/Energinet-SimTools/MTB/pull/235), [#238](https://github.com/Energinet-SimTools/MTB/pull/238))
- New cursor metrics for evaluating simulation results ([#188](https://github.com/Energinet-SimTools/MTB/pull/188), [#190](https://github.com/Energinet-SimTools/MTB/pull/190), [#191](https://github.com/Energinet-SimTools/MTB/pull/191), [#192](https://github.com/Energinet-SimTools/MTB/pull/192), [#194](https://github.com/Energinet-SimTools/MTB/pull/194), [#195](https://github.com/Energinet-SimTools/MTB/pull/195), [#197](https://github.com/Energinet-SimTools/MTB/pull/197), [#200](https://github.com/Energinet-SimTools/MTB/pull/200))
- Multiple columns with legends in HTML reports ([#179](https://github.com/Energinet-SimTools/MTB/pull/179))
- Automatic determination of the MTB location in `.psout` files ([#270](https://github.com/Energinet-SimTools/MTB/pull/270))
- `findPsoutSignalPath` now returns all matching signal paths instead of only the first ([#293](https://github.com/Energinet-SimTools/MTB/pull/293))
- FRT state handling with voltage hysteresis and updated Iq0 calculation in `genGuideResults`

#### PSCAD

- Support for running PSCAD as an external client with configurable Fortran compiler and workspace settings via `config.ini` ([#239](https://github.com/Energinet-SimTools/MTB/pull/239))
- `batch_execute_pscad.py` script for batch execution of PSCAD simulations to work around out-of-memory (OOM) issues ([#243](https://github.com/Energinet-SimTools/MTB/pull/243))
- PSCAD OOM recovery: `recover_psout_files.py` script to rename and recover `.psout` files after a PSCAD crash ([#211](https://github.com/Energinet-SimTools/MTB/pull/211), [#213](https://github.com/Energinet-SimTools/MTB/pull/213))
- CSV export of case rank and task ID for OOM recovery tracking ([#211](https://github.com/Energinet-SimTools/MTB/pull/211), [#213](https://github.com/Energinet-SimTools/MTB/pull/213))
- MTB can now be placed in a PSCAD subfolder rather than on the main canvas ([#203](https://github.com/Energinet-SimTools/MTB/pull/203))
- PGB (Plotter Group Block) synchronization with `figureSetup.csv` via `pscad_synchronize_pgbs.py`, including automatic disabling of unused signals ([#273](https://github.com/Energinet-SimTools/MTB/pull/273), [#274](https://github.com/Energinet-SimTools/MTB/pull/274))
- PSCAD tracing and state animation disabled by default; only in-use channels enabled ([#263](https://github.com/Energinet-SimTools/MTB/pull/263))

#### PowerFactory

- Option to organise study cases and variations into a dedicated subfolder in PowerFactory ([#319](https://github.com/Energinet-SimTools/MTB/pull/319))

#### Utility Scripts

- `list_psout_signals.py`: list all signals contained in a `.psout` file ([#279](https://github.com/Energinet-SimTools/MTB/pull/279))
- `clean_project_definitions.py`: clean up project definitions in a PowerFactory project ([#297](https://github.com/Energinet-SimTools/MTB/pull/297))

#### Co-location

- Initial framework for co-location case handling in `Case` and `PlantSettings` classes and `testcases.xlsx` ([#300](https://github.com/Energinet-SimTools/MTB/pull/300))

### Changed

#### Naming and Terminology

- SIPS event types renamed for clarity: `SIPS` → `SIPS Generation` (RfG cases) and `SIPS Demand` (DCC cases) ([#310](https://github.com/Energinet-SimTools/MTB/pull/310), [#317](https://github.com/Energinet-SimTools/MTB/pull/317))
- Case names updated from `SystemGuard`/`SystemProtect` to `SIPS` for consistency ([#202](https://github.com/Energinet-SimTools/MTB/pull/202))
- Q(U) rise/fall time parameter renamed to **Q(U) response time** ([#253](https://github.com/Energinet-SimTools/MTB/pull/253))
- Unit measurement signal naming simplified: `$Unit$` replaced with `Unit` in PSCAD ([#287](https://github.com/Energinet-SimTools/MTB/pull/287))
- `psoutRecovery` script renamed to `recover_psout_files.py` for consistency with naming conventions ([#272](https://github.com/Energinet-SimTools/MTB/pull/272))

#### PowerFactory

- Updated to **PowerFactory 2025 SP4** (`execute_pf.py`) ([#244](https://github.com/Energinet-SimTools/MTB/pull/244))
- PowerFactory `.pfd` file exported in **2025 format** ([#303](https://github.com/Energinet-SimTools/MTB/pull/303))

#### PSCAD

- Improved port handling to filter PSCAD connections based on the current user, preventing port conflicts in multi-user environments ([#330](https://github.com/Energinet-SimTools/MTB/pull/330))
- Optimized XML parsing in `_parseProjectXML` for improved performance and reduced latency when resolving PGB signal paths ([#334](https://github.com/Energinet-SimTools/MTB/pull/334))
- Enhanced `updateUMs` function for improved performance and flexibility; verbose output disabled by default ([#334](https://github.com/Energinet-SimTools/MTB/pull/334))
- Updated Fortran compiler version list in `config.ini` for clarity and accuracy ([#335](https://github.com/Energinet-SimTools/MTB/pull/335))
- Updated PSCAD setup example to reflect recent MTB changes ([#337](https://github.com/Energinet-SimTools/MTB/pull/337))

#### Requirements

- `requirements.txt` split into separate files for MTB and the plotter ([#305](https://github.com/Energinet-SimTools/MTB/pull/305), [#306](https://github.com/Energinet-SimTools/MTB/pull/306))
- Added `mhi.pscad` to requirements ([#241](https://github.com/Energinet-SimTools/MTB/pull/241))
- Relaxed version constraints for `plotly`, `kaleido`, and `tsdownsample` to allow newer releases

#### Plotter

- Kaleido compatibility updated to support both the older fast version and the newer, slower version ([#266](https://github.com/Energinet-SimTools/MTB/pull/266), [#323](https://github.com/Energinet-SimTools/MTB/pull/323), [#324](https://github.com/Energinet-SimTools/MTB/pull/324))
- Removed deprecated `engine` parameter from `write_image` calls ([#331](https://github.com/Energinet-SimTools/MTB/pull/331))
- `psoutPathMTB` configuration removed from `read_configs` (now determined automatically) ([#270](https://github.com/Energinet-SimTools/MTB/pull/270), [#271](https://github.com/Energinet-SimTools/MTB/pull/271))

#### Configuration

- `config.ini` documentation updated for clarity and accuracy ([#336](https://github.com/Energinet-SimTools/MTB/pull/336))
- `config.ini` updated with examples for running PSCAD as an external client, configuring Fortran, and default GitHub project settings ([#239](https://github.com/Energinet-SimTools/MTB/pull/239), [#246](https://github.com/Energinet-SimTools/MTB/pull/246))

#### Documentation

- Reworked the README to provide a clearer MTB overview, workflow, documentation links, requirements, release notes, contribution guidance, and contact details ([#339](https://github.com/Energinet-SimTools/MTB/pull/339), [#340](https://github.com/Energinet-SimTools/MTB/pull/340), [#341](https://github.com/Energinet-SimTools/MTB/pull/341))
- Added a workflow illustration and an annotated HTML report example to the README ([#339](https://github.com/Energinet-SimTools/MTB/pull/339), [#340](https://github.com/Energinet-SimTools/MTB/pull/340), [#341](https://github.com/Energinet-SimTools/MTB/pull/341))
- Corrected the `.bz2` compression extension in the `psout_to_csv.py` help text ([#338](https://github.com/Energinet-SimTools/MTB/pull/338))
- Clarified the README disclaimer to state that passing MTB test cases does not by itself constitute approval, and that a model will not be approved unless there is full confidence that the connected plant will not cause grid instability or reduce grid security

### Fixed

#### PSCAD / psout Processing

- `process_psout.py` fixed to correctly handle multi-dimensional PSCAD signal arrays ([#214](https://github.com/Energinet-SimTools/MTB/pull/214), [#215](https://github.com/Energinet-SimTools/MTB/pull/215))
- Fixed crash when `psoutPathMTB` is empty; missing signals in `.psout` are now ignored without exiting ([#265](https://github.com/Energinet-SimTools/MTB/pull/265))
- Fixed automatic PSCAD certificate acquisition to ensure the volley requirement is met ([#240](https://github.com/Energinet-SimTools/MTB/pull/240))
- Fixed `execute_pscad.py` to not crash when no Fortran version is specified ([#258](https://github.com/Energinet-SimTools/MTB/pull/258))
- Fixed `pscad_synchronize_pgbs.py` to execute correctly from the MTB folder ([#281](https://github.com/Energinet-SimTools/MTB/pull/281))
- Fixed `pscad_synchronize_pgbs.py` failure when the project was not saved before script execution ([#288](https://github.com/Energinet-SimTools/MTB/pull/288))
- Fixed PGB `mtb_s_pref_pu` that was accidentally disabled ([#289](https://github.com/Energinet-SimTools/MTB/pull/289))
- Improved `batch_execute_pscad.py` to fail softly on first error, allowing graceful error handling ([#346](https://github.com/Energinet-SimTools/MTB/pull/346))
- Fixed `execute_pscad.py` to handle a missing or invalid PSCAD workspace file gracefully instead of crashing ([#346](https://github.com/Energinet-SimTools/MTB/pull/346))
- Enhanced print feedback messages in `execute_pscad.py` and `batch_execute_pscad.py` for improved user communication ([#346](https://github.com/Energinet-SimTools/MTB/pull/346))

#### PowerFactory

- Fixed garbage output in MTB `execute.ComPython` (line 218) ([#207](https://github.com/Energinet-SimTools/MTB/pull/207))
- Fixed Check PowerFactory Model script for state variable derivatives ([#208](https://github.com/Energinet-SimTools/MTB/pull/208))
- Fixed Main Transformer Grounding (`MtrfrGnd`) condition check in setup function ([#262](https://github.com/Energinet-SimTools/MTB/pull/262))
- Fixed logic for DCC cases where `Pavail0` and `MtrfrGnd0` are not used in the test case sheet ([#236](https://github.com/Energinet-SimTools/MTB/pull/236))

#### Plotter / HTML Reports

- Fixed first HTML plot cell being too wide before the browser window is resized ([#186](https://github.com/Energinet-SimTools/MTB/pull/186))
- Fixed image plots broken by the introduction of multiple-column HTML layout ([#185](https://github.com/Energinet-SimTools/MTB/pull/185))
- Fixed duplicate signal names in `process_psout.py` ([#183](https://github.com/Energinet-SimTools/MTB/pull/183))
- Fixed default Unit Measurement EMT signal name ([#182](https://github.com/Energinet-SimTools/MTB/pull/182))
- Fixed bug with non-legacy naming in `guide_functions` library ([#299](https://github.com/Energinet-SimTools/MTB/pull/299))
- Fixed `psout_to_csv.py` that was broken after `process_psout.py` was updated ([#290](https://github.com/Energinet-SimTools/MTB/pull/290))
- Fixed HTML syntax error: missing closing tag on the `mtb.css` stylesheet link ([#324](https://github.com/Energinet-SimTools/MTB/pull/324))
- Fixed array conversion to use `np.array` for compatibility with pandas 2.0+ ([#332](https://github.com/Energinet-SimTools/MTB/pull/332))
- Suppressed spurious warnings from `choreographer.utils._tmpfile` logger ([#333](https://github.com/Energinet-SimTools/MTB/pull/333))

#### Utility Scripts

- Fixed `compare_component_data_with_pscad.py` to ignore geometric models ([#189](https://github.com/Energinet-SimTools/MTB/pull/189))
- Fixed `get_dsl_checksums.py` minor bug ([#180](https://github.com/Energinet-SimTools/MTB/pull/180))
- Fixed `sys.exit(1)` call that incorrectly used `os.exit(1)` ([#296](https://github.com/Energinet-SimTools/MTB/pull/296))

#### General

- Fixed Python 3.7.x compatibility issue caused by `pypdf` ([#267](https://github.com/Energinet-SimTools/MTB/pull/267))
- Fixed `Pavail0` assignment logic in the setup function ([#202](https://github.com/Energinet-SimTools/MTB/pull/202))
- Fixed bug in the test case sheet for custom cases ([#242](https://github.com/Energinet-SimTools/MTB/pull/242))

---

## [1.1.2] - 2025-06-18

_See repository history for earlier release notes._
