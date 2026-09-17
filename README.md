# MOSAIC

Multi-ROI Optical System for Analysis of Intracellular Calcium

**Version 0.2.0** — desktop analysis of cardiomyocyte Ca²⁺ transients from
single-channel Nikon ND2 time-lapse recordings.

MOSAIC retains images and ROI geometry alongside fluorescence traces, accepted
events, and kinetic measurements. Multiple whole-cell or subcellular ROIs can
be analyzed in one field of view using a PySide6 interface.

## Version notes

Version 0.2.0 changes peak selection and can change the accepted events,
photobleaching baseline, and derived summaries compared with v0.1.0. Report
the software version and settings used for each analysis.
See [CHANGELOG](CHANGELOG.md) and [analysis methods](docs/ANALYSIS_METHODS.md).

**Pacing interval defaults to 450 ms** for 2-Hz pacing. For other rates, enter
the stimulation interval × 0.9 (1 Hz → 900 ms). Small timing variation is allowed independently of the decay-analysis window.
This is a paced-transient detector, not a general classifier of all abnormal
or spontaneous Ca²⁺ events.

## Installation and launch

Use Python **3.10 or later** in a local, writable folder. Intended desktop
platforms are Windows and macOS. Dependencies are defined in `pyproject.toml`;
first launch needs internet access.

1. Download [MOSAIC-0.2.0.zip](https://mosaicsnu.github.io/downloads/MOSAIC-0.2.0.zip)
   and extract it to a local folder.
2. Windows: install Python with “Add python.exe to PATH”, then double-click
   `run_app.bat`.
3. macOS: double-click `run_app.command`. If necessary, use a terminal in the
   extracted folder: `chmod +x run_app.command`, then `./run_app.command`.

The launcher creates an isolated `.venv` and installs the application.
Avoid cloud-synchronized program folders during installation.

For terminal installation:

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
python -m mosaic.main
```

An installed environment also provides the `mosaic` command.

## Quick start

1. **Open ND2** and inspect the image and relative frame time.
2. **Add Background** in a cell-free region.
3. **Add ROI**, position it over a cell, and click **Calculate**.
4. Set the orange **Tran.** range to stable pacing. Leave one pacing interval
   after the last peak to be analyzed.
5. Check the **Pacing interval** (default 450 ms for 2 Hz).
6. If needed, **Cal. Photobleaching**, inspect the baseline points, then
   **Confirm Photobleaching**.
7. **Calculate transients**, review **Use** checkboxes, and **Save ROI**.
8. Repeat for other cells, then **Save** to export.

Use the [v0.2.0 control reference](docs/USER_GUIDE.md) or
[한국어 빠른 안내](docs/USER_GUIDE_KO.md). Illustrated guides are at
<https://mosaicsnu.github.io>.

ND2 recordings, including `MOSAIC_example_2Hz.nd2` used in the guides, are not
stored in this repository. They are available upon request through
[GitHub Issues](https://github.com/MOSAICSNU/mosaicsnu.github.io/issues) or from the
corresponding author.

## Measurements and export

| Measurement | Definition |
| --- | --- |
| Tran N | Number of detected and user-included events |
| Amplitude | Baseline-to-peak amplitude divided by pre-onset F₀ |
| Time to peak | Detected 10% onset to peak |
| Maximum rising rate | Largest consecutive-sample d(F/F₀)/dt during the rise, s⁻¹ |
| Decay 10/50/90% | Interpolated time from peak to the specified amplitude loss |

The detector measures a 20-ms smoothed trace. Aligned waveform exports use
the analysis trace before this detection smoothing.
See [ANALYSIS_METHODS.md](docs/ANALYSIS_METHODS.md).

**Save** exports to `<recording>_ana` beside the ND2 file:

| File | Contents |
| --- | --- |
| `analysis.xlsx` | Numeric ROI summaries; missing values are blank |
| `rawtrace.xlsx` | Background-subtracted traces before photobleaching correction |
| `transient.xlsx` | Onset-aligned mean F/F₀ curves |
| `ROI.jpg` | ROI overlay on the first frame |
| `analysis_info.json` | All saved ROIs, inclusion flags, traces, events, and provenance |

Spreadsheet/image exports include checked ROIs. JSON preserves **all** saved
ROIs with their inclusion flags. Saving again overwrites existing exports.
Use separate copies of input files to retain independent analyses.

New sessions record program/dependency versions, calculation-time settings
per ROI, applied bleaching settings, and background geometry. **Load Info**
accepts old schema-1 sessions without inventing their missing settings. It
locates a moved source beside the results or asks for its location. New
sessions use the file size and first/last MiB hash to check the selected source;
this is not a full-file integrity hash. Saved results are restored without
recomputing them. Restoring results does not set every control to the saved
ROI's settings: inspect its `analysis_settings` before reanalysis.

## Limitations

- Only single-channel `T × Y × X` time-lapse ND2 is supported. Other varying
  dimensions are rejected.
- At least two valid increasing timestamps are required. Missing timestamps
  are interpolated by frame index; edge gaps are extrapolated. Unusable timing
  is rejected instead of assigning an arbitrary frame rate.
- The entire movie loads into RAM. Allow the uncompressed pixel-array size
  plus space for computation. Loading, background recommendation, and Auto ROI
  can freeze the window temporarily.
- ROIs do not track contraction. Manual choices can affect results;
  inter-operator reproducibility has not been established.
  After moving a signal or background ROI, recalculate traces before analysis
  or saving; v0.2.0 blocks stale geometry/trace combinations.
- Detection requires a stable baseline, recovery below 25% of amplitude for
  30 ms, and a rise shorter than recovery. Slow/abnormal events may be rejected.
  Compare accepted events with the original trace.
- Display uses 0–255 for 8-bit data and first-frame contrast limits for higher
  bit depths. Display limits never alter measurement intensities.
- Caffeine/SR-related code is present but has no exposed v0.2.0 user workflow.

## Validation and contributions

```sh
python -m unittest discover -s tests -v
```

Tests cover nominal/jittered pacing, photobleaching peak exclusion, timing,
session portability, and a Qt save/reload workflow with synthetic images.
[VALIDATION.md](docs/VALIDATION.md) records checks and their limits.
The real-example check is optional and does not download research data:

```sh
python tools/verify_example.py /path/to/MOSAIC_example_2Hz.nd2 --output validation/example.json
```

This writes verification exports below `validation/`, leaving existing
analysis outputs beside the original recording untouched.
See [CONTRIBUTING.md](CONTRIBUTING.md).

## Citation and license

Citation details will be added upon publication. When reporting use, identify
the software version and settings.

License: to be announced. Research data may have different terms.
