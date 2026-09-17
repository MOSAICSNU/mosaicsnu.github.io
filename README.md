# MOSAIC

## Multi-ROI Optical System for Analysis of Intracellular Calcium

MOSAIC is a graphical workflow for analyzing cardiomyocyte Ca²⁺ transients from
high-speed Nikon ND2 fluorescence image sequences. It retains the spatial
context of the recording while enabling multiple whole-cell or subcellular
regions of interest (ROIs) to be analyzed from a common field of view.

The software was developed for offline analysis of high-speed sCMOS recordings,
including the 500 frames s⁻¹ (2-ms interval) cardiomyocyte recordings used in
the accompanying manuscript. MOSAIC is not restricted to that acquisition
rate: timing calculations use the timestamps stored in the ND2 file.

## Analytical workflow

1. **ND2 import and temporal calibration** — MOSAIC reads the image sequence
   and acquisition timestamps directly from the ND2 file. Timing is referenced
   to the first frame; the effective sampling interval is derived from the
   median positive timestamp difference.
2. **Multi-ROI fluorescence extraction** — Elliptical, rectangular, or
   activity-refined polygonal ROIs can be placed over individual cells or
   subcellular regions. A cell-free background ROI can be subtracted from each
   signal ROI.
3. **Photobleaching correction** — A robust linear baseline is fitted outside
   detected transient windows. The fit is displayed for review before ratio or
   additive correction is applied.
4. **Transient detection and quantification** — Candidate peaks are evaluated
   against a stable pre-event baseline, recovery, and upstroke-shape criteria.
   Accepted events are aligned to onset, normalized to F/F₀, and averaged.
5. **Review and export** — Individual events may be included or excluded before
   saving an ROI and exporting the selected results.

MOSAIC is intended for cell- and region-scale Ca²⁺-transient analysis, rather
than detection of individual Ca²⁺ sparks.

## Quantified transient parameters

| Parameter | Definition |
| --- | --- |
| Transient number | Number of detected and user-accepted events included in the ROI summary |
| Amplitude | Peak fluorescence minus the pre-event baseline, normalized to F/F₀ |
| Time to peak | Interval from the 10% amplitude onset crossing to peak fluorescence |
| Maximum rising rate | Largest consecutive-sample d(F/F₀)/dt between onset and peak |
| Decay 10%, 50%, 90% | Time from peak to the corresponding amplitude-decay crossing |

### Terminal

Python 3.9 or later is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONPATH="$PWD/src" python -m mosaic.main
```

## Saving and reloading an analysis

After calculating traces, use **Save ROI** to lock each finalized ROI and
retain its selected transient events. Click **Save** to export all checked saved
ROIs to `<movie_name>_ana` beside the source ND2 file.

| File | Contents |
| --- | --- |
| `analysis.xlsx` | Per-ROI summary of accepted transient measurements |
| `rawtrace.xlsx` | Background-corrected ROI intensity traces before optional photobleaching correction |
| `transient.xlsx` | Onset-aligned mean F/F₀ transient traces |
| `ROI.jpg` | First image frame with saved ROI outlines |
| `analysis_info.json` | ROI geometry, traces, and event selections for session reloading |

Use **Load Info** to reopen a saved session. The source ND2 file must still be
available at the path recorded in `analysis_info.json`.
