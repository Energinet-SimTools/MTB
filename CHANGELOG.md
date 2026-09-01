# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-09-01

### Added

#### SIPS (System Protection Scheme)
- Dedicated MTB SIPS signal (`mtb_s_sips`) and Integer-to-Binary decoder block in PowerFactory and PSCAD (#302)
- Separate generation and demand SIPS signals: `mtb_SIPS_g` (`out_sips_g`) and `mtb_SIPS_d` (`out_sips_d`), replacing the single `mtb_SIPS` signal (#310)
- `SIPS_future_use` bit for future arming/enable logic, replacing `SIPS_notused` (#311)
- `guideSIPS` function in the plotter for active power ceiling decoding from SIPS binary output (#300, #317)
- Ramping logic for SIPS release and reduction in `guideSIPS` (#325)
- Delayed SIPS ramp-down logic via `guideSIPS2` with configurable delay and linear down-ramp (#328, #329)
- SIPS demand test cases (1043, 1044, 1087, 1088) added to `figureSetup.csv` and `testcases.xlsx` (#317)
- SIPS figures with y-labels and PGB templates for generation and demand in `figureSetup.csv` (#302, #317)

#### New Signals and Parameters
- Q(U) droop signal (`QuDroop`) and `Qudroop0` initial setting for reactive power control (#202)
- Available power signal (`Pavail`) and `Pavail0` initial setting (#202)
- Main Transformer Grounding parameter (`MtrfrGnd`) with `MtrfrGnd0` initialization and output signal (#202)

#### Plotter
- Multiprocessing support in the plotter for significantly faster report generation (#229, #230, #231, #232, #233, #234, #235, #238)
- New cursor metrics for evaluating simulation results (#188, #190, #191, #192, #194, #195, #197, #200)
- Ideal reference waveforms overlaid on figures (#188–#200)
- Multiple columns with legends in HTML reports (#179)
- `psoutPathMTB` configuration option for when the MTB block is not on the PSCAD main canvas (#264)
- Automatic determination of the MTB location in `.psout` files (#270)
- `findPsoutSignalPath` now returns all matching signal paths instead of only the first (#293)
- FRT state handling with voltage hysteresis and updated Iq0 calculation in `genGuideResults`

#### PSCAD
- Support for running PSCAD as an external client with configurable Fortran compiler and workspace settings via `config.ini` (#239)
- `batch_execute_pscad.py` script for batch execution of PSCAD simulations to work around out-of-memory (OOM) issues (#243)
- PSCAD OOM recovery: `recover_psout_files.py` script to rename and recover `.psout` files after a PSCAD crash (#211, #213)
- CSV export of case rank and task ID for OOM recovery tracking (#211, #213)
- MTB can now be placed in a PSCAD subfolder rather than on the main canvas (#203)
- PGB (Probe Group Block) synchronization with `figureSetup.csv` via `pscad_synchronize_pgbs.py`, including automatic disabling of unused signals (#273, #274)
- PSCAD tracing and state animation disabled by default; only in-use channels enabled (#263)

#### PowerFactory
- Option to organise study cases and variations into a dedicated subfolder in PowerFactory (#319)

#### Utility Scripts
- `list_psout_signals.py`: list all signals contained in a `.psout` file (#279)
- `clean_project_definitions.py`: clean up project definitions in a PowerFactory project (#297)
- `convert_psout_to_csv.py` (moved from root and renamed from `psout_to_csv.py`) (#283, #284)

#### Co-location
- Initial framework for co-location case handling in `Case` and `PlantSettings` classes and `testcases.xlsx` (#300)

### Changed

#### Naming and Terminology
- SIPS event types renamed for clarity: `SIPS` → `SIPS Generation` (RfG cases) and `SIPS Demand` (DCC cases) (#310, #317)
- Case names updated from `SystemGuard`/`SystemProtect` to `SIPS` for consistency (#202)
- Q(U) rise/fall time parameter renamed to **Q(U) response time** (#253)
- Unit measurement signal naming simplified: `$Unit$` replaced with `Unit` in PSCAD (#287)
- `psout_to_csv.py` moved to `utility_scripts/` and renamed to `convert_psout_to_csv.py` (#283, #284)
- `psoutRecovery` script renamed to `recover_psout_files.py` for consistency with naming conventions (#272)

#### PowerFactory
- Updated to **PowerFactory 2025 SP4** (`execute_pf.py`) (#244)
- PowerFactory `.pfd` file exported in **2025 format** (#303)

#### PSCAD
- Improved port handling to filter PSCAD connections based on the current user, preventing port conflicts in multi-user environments (#330)
- Optimized XML parsing in `_parseProjectXML` for improved performance and reduced latency when resolving PGB signal paths (#334)
- Enhanced `updateUMs` function for improved performance and flexibility; verbose output disabled by default (#334)
- Updated Fortran compiler version list in `config.ini` for clarity and accuracy (#335)
- Updated PSCAD setup example to reflect recent MTB changes (#337)

#### Requirements
- `requirements.txt` split into separate files for MTB and the plotter (#305, #306)
- Added `mhi.pscad` to requirements (#241)
- Relaxed version constraints for `plotly`, `kaleido`, and `tsdownsample` to allow newer releases

#### Plotter
- Kaleido compatibility updated to support both the older fast version and the newer, slower version (#266, #323, #324)
- Removed deprecated `engine` parameter from `write_image` calls (#331)
- `psoutPathMTB` configuration removed from `read_configs` (now determined automatically) (#270, #271)

#### Configuration
- `config.ini` documentation updated for clarity and accuracy (#336)
- `config.ini` updated with examples for running PSCAD as an external client, configuring Fortran, and default GitHub project settings (#239, #246)

### Fixed

#### PSCAD / psout Processing
- `process_psout.py` fixed to correctly handle multi-dimensional PSCAD signal arrays (#214, #215)
- Fixed crash when `psoutPathMTB` is empty; missing signals in `.psout` are now ignored without exiting (#265)
- Fixed automatic PSCAD certificate acquisition to ensure the volley requirement is met (#240)
- Fixed `execute_pscad.py` to not crash when no Fortran version is specified (#258)
- Fixed `pscad_synchronize_pgbs.py` to execute correctly from the MTB folder (#281)
- Fixed `pscad_synchronize_pgbs.py` failure when the project was not saved before script execution (#288)
- Fixed PGB `mtb_s_pref_pu` that was accidentally disabled (#289)

#### PowerFactory
- Fixed garbage output in MTB `execute.ComPython` (line 218) (#207)
- Fixed Check PowerFactory Model script for state variable derivatives (#208)
- Fixed Main Transformer Grounding (`MtrfrGnd`) condition check in setup function (#262)
- Fixed logic for DCC cases where `Pavail0` and `MtrfrGnd0` are not used in the test case sheet (#236)

#### Plotter / HTML Reports
- Fixed first HTML plot cell being too wide before the browser window is resized (#186)
- Fixed image plots broken by the introduction of multiple-column HTML layout (#185)
- Fixed duplicate signal names in `process_psout.py` (#183)
- Fixed default Unit Measurement EMT signal name (#182)
- Fixed bug with non-legacy naming in `guide_functions` library (#299)
- Fixed `psout_to_csv.py` that was broken after `process_psout.py` was updated (#290)
- Fixed HTML syntax error: missing closing tag on the `mtb.css` stylesheet link (#327)
- Fixed array conversion to use `np.array` for compatibility with pandas 2.0+ (#332)
- Suppressed spurious warnings from `choreographer.utils._tmpfile` logger (#333)

#### Utility Scripts
- Fixed `compare_component_data_with_pscad.py` to ignore geometric models (#189)
- Fixed `get_dsl_checksums.py` minor bug (#180)
- Fixed `sys.exit(1)` call that incorrectly used `os.exit(1)` (#296)

#### General
- Fixed Python 3.7.x compatibility issue caused by `pypdf` (#267)
- Fixed `Pavail0` assignment logic in the setup function (#202)
- Fixed bug in the test case sheet for custom cases (#242)

---

## [1.1.2] - 2025-06-18

_See repository history for earlier release notes._
