# MTB (Model Test Bench)

**MTB** (**M**odel **T**est **B**ench) automates grid compliance simulation studies in both [DIgSILENT PowerFactory](https://www.digsilent.de/en/powerfactory.html) and [PSCAD](https://www.pscad.com/), with external plotting and comparison of RMS and EMT results.

MTB is intended to help facility owners and model providers evaluate simulation model behaviour in the context of Danish grid-code requirements and Energinet simulation model requirements. It includes predefined case sets for RfG, DCC, unit testing, co-located generation/demand cases, and custom user-defined studies.

## MTB Workflow

1. Configure the testcase workbook to test various requirements in e.g. EU 2016/631 with specific relevance to the Danish NC RfG
2. Set up the MTB in PowerFactory and execute the selected simulation cases
3. Set up the MTB in PSCAD and execute the selected simulation cases
4. Plot and compare RMS and EMT results making use of among other things, analytically calculated guide curves, cursor metrics, and visual inspection

> [!IMPORTANT]
> Using MTB in Danish grid connection processes is entirely voluntary, though recommended. The predefined test cases are designed to catch non-compliant behaviour in broad terms; they are not an exhaustive or fixed list. Existing cases can be edited, and new cases added, whenever relevant to properly assess compliance for a specific plant. Using MTB, including its predefined case sets, is not a guarantee of model compliance. The plant owner remains responsible for ensuring that models comply with the requirements applicable at any time, regardless of which test cases were run.
>
> Regardless of which test cases are run or passed, the connected plant must under no circumstances cause grid instability or reduce the security of the grid. Passing the predefined (or any) MTB test cases does not by itself constitute approval. A model will not be approved unless there is full confidence, established through whatever additional analysis and testing is necessary, that this requirement is met.

<p align="center">
	<!-- <img src="https://github.com/user-attachments/assets/2264d07d-e99f-46ab-bbb1-4dceddcc614b" width="800" height="210" alt="MTB workflow from testcase workbook to simulation and plotting"> -->
	<img width="1000" alt="image" src="https://github.com/user-attachments/assets/2bb9ffc7-150d-482e-b54d-af127151b8b5" />
</p>

## Python/Plotly Output Example

The MTB plotter generates interactive, self-contained HTML reports built with Plotly, letting users pan, zoom, and toggle signals directly in the browser without any additional software. One HTML output file is generated per testcase (or Rank), with multiple plots covering line voltages, line currents, active and reactive current components, active power, reactive power, frequency, and more.

<p align="left">
	<img width="1000" alt="Zoomed view of MTB HTML plot output features" src="https://github.com/user-attachments/assets/522c623e-e778-41ec-a800-d4f807ae7a46" />
</p>

The generated HTML reports include:

1. **Previous Rank** - navigates to the previous rank in the study, with wraparound.
2. **Next Rank** - navigates to the next rank in the study, with wraparound.
3. **More Ranks** - drop-down list for faster navigation between ranks.
4. **Rank Number and Title** - shows the rank number and case title from `testcases.xlsx`.
5. **Subsection Hyperlinks** - links to Figures, Cursors, and Source Data.
6. **Figures subsection** - contains the result plot figures.
7. **Plot Figure Hyperlinks** - links to each plot figure on the page.
8. **Plot Figure Title** - taken from `figureSetup.csv`.
9. **Plot Figure Units** - taken from `figureSetup.csv`.
10. **Plot Figure Legend** - lists the plotted signals. Click a legend item to hide or show the corresponding trace.
11. **Plotly Buttons** - standard Plotly controls for downloading, zooming, panning, autoscaling, and resetting axes.

## MTB Quickstart Wiki Guides

| Section | Page                                                                                                                        | Purpose                                                                                         |
| ------- | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1       | [Quickstart Testcases Workbook Guide](https://github.com/Energinet-SimTools/MTB/wiki/1.-Quickstart-Testcases-Workbook-Guide) | Configure`testcases.xlsx`, case sheets, settings, and event types.                            |
| 2       | [Quickstart PowerFactory Guide](https://github.com/Energinet-SimTools/MTB/wiki/2.-Quickstart-PowerFactory-Guide)             | Set up and execute MTB cases in PowerFactory.                                                   |
| 3       | [Quickstart PSCAD Guide](https://github.com/Energinet-SimTools/MTB/wiki/3.-Quickstart-PSCAD-Guide)                           | Set up and execute MTB cases in PSCAD.                                                          |
| 4       | [Quickstart Plotter Guide](https://github.com/Energinet-SimTools/MTB/wiki/4.-Quickstart-Plotter-Guide)                       | Configure and run the MTB plotter.                                                              |
| 5       | [Quickstart Guide Curve Generation](https://github.com/Energinet-SimTools/MTB/wiki/5.-Quickstart-Guide-Curve-Generation)     | Understand analytical guide curves generated by the plotter.                                    |
| 6       | [Quickstart Cursor Metrics](https://github.com/Energinet-SimTools/MTB/wiki/6.-Quickstart-Cursor-Metrics)                     | Configure and interpret cursor metric tables.                                                   |
| 7       | [Quickstart Python Utility Scripts](https://github.com/Energinet-SimTools/MTB/wiki/7.-Quickstart-Python-Utility-Scripts)     | Use helper scripts for model checks, data extraction,`.psout` inspection, and recovery.       |
| A       | [Working with .psout files](https://github.com/Energinet-SimTools/MTB/wiki/A.-Working-with-.psout-files)                     | Use PSCAD`.psout` files with MHI tools, MTB helper functions, and conversion/listing scripts. |

The above Quickstart Wiki can also be downloaded as a single PDF file: [MTB 2.0 Quickstart Guide](<https://raw.githubusercontent.com/wiki/Energinet-SimTools/MTB/MTB%202.0%20Quickstart%20Guide.pdf>)

Example PowerFactory and PSCAD setups are available in [setup_examples](setup_examples). These examples demonstrate the MTB setup workflow only; they are not representative of compliant plant models.

## Requirements

Install the main MTB dependencies from the repository root:

```bash
python -m pip install -r requirements.txt
```

The plotter has a separate dependency file:

```bash
cd plotter
python -m pip install -r requirements.txt
```

### Tested Environments

- **PowerFactory**: PowerFactory 2025 SP4 with Python >= 3.11.
- **PSCAD**: PSCAD 5.0.2.0 with embedded Python 3.7.2 or Python 3.13 as an external client. Compatibility is only guaranteed with Intel Fortran compilers.

## Releases

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Contributing

Please use the [Issues tab](https://github.com/Energinet-SimTools/MTB/issues) to report bugs, request features, or suggest improvements.

## Contact

For inquiries, please contact the Energinet simulation model team: [simuleringsmodeller@energinet.dk](mailto:simuleringsmodeller@energinet.dk)
