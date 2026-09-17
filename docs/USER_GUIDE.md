# MOSAIC user guide (version 0.2.0)

This guide describes every control in the MOSAIC window in the order used during
an analysis. For installation, see the [README](../README.md#installation-and-launch).
Before analyzing your own recordings, read the
[Known limitations](../README.md#limitations) and [analysis methods](ANALYSIS_METHODS.md).

- [1. Window layout](#1-window-layout)
- [2. Open a recording](#2-open-a-recording)
- [3. Playback](#3-playback)
- [4. Background ROI](#4-background-roi)
- [5. Signal ROIs](#5-signal-rois)
- [6. Graph analysis panel](#6-graph-analysis-panel)
- [7. Photobleaching correction](#7-photobleaching-correction)
- [8. Transient analysis](#8-transient-analysis)
- [9. Save ROI and the Saved ROI table](#9-save-roi-and-the-saved-roi-table)
- [10. Export and reload](#10-export-and-reload)
- [11. Parameter reference](#11-parameter-reference)
- [12. Troubleshooting](#12-troubleshooting)

---

## 1. Window layout

| Area | Location | Contents |
| --- | --- | --- |
| **Image** | Center | Current frame, ROIs, background ROI |
| **Controls** | Left | File, Playback, Background, ROI, Photobleaching, Status |
| **Graph analysis** | Bottom | Whole-recording graph (top) and zoomable detail graph (bottom) |
| **Transient analysis** | Right | Detection parameters, average transient, event table, Saved ROI table |

The panels can be moved, resized, or detached. The **Status** box at the bottom
of Controls reports the result of every action; check it after each step.

## 2. Open a recording

| Control | Action |
| --- | --- |
| **Open ND2** | Select a `.nd2` file. The first frame, file path, image size, and data type are shown. |
| **Close ND** | After confirmation, closes the file and clears all ROIs, saved ROIs, and analyses. |
| **Save** | Exports the saved ROIs (see [section 10](#10-export-and-reload)). Enabled after at least one **Save ROI**. |
| **Load Info** | Reopens a previous analysis from `analysis_info.json`. |

Opening a file reads the acquisition timestamps. All graphs use time relative to
the first frame (0 s).

## 3. Playback

| Control | Action |
| --- | --- |
| **Play / Pause** | Plays the movie at its recorded speed. |
| **Frame slider / number box** | Moves to a specific frame. |
| Frame label | Shows `Frame: n / total` and time relative to the first frame. |

A dashed vertical line in both graphs marks the current frame.

## 4. Background ROI

The mean intensity inside the background ROI is subtracted, frame by frame, from
every signal ROI.

| Control | Action |
| --- | --- |
| **Add Background** | Places a blue elliptical ROI (120 × 120 px) at the image center. Drag it to a cell-free area; resize with its handles. |
| **Recommend Background** + **R** | Tests 100 random circles of radius **R** px (default 10) over the first 10 s and places the background on the dimmest one. Check that the chosen area is really cell-free. |
| **Clear Background ROI** | Removes the background ROI. |

Adding, moving by recommendation, or clearing the background removes the
calculated traces; press **Calculate** again.

## 5. Signal ROIs

| Control | Action |
| --- | --- |
| **Shape** | *Ellipse* or *Rectangle* for the next **Add ROI**. Both can be rotated. |
| **Add ROI** | Adds an 80 × 80 px ROI at the image center. Drag to move; use the handles to resize or rotate. Several ROIs can be analyzed together. |
| **(op) Auto ROI** | Optional. Refines the **most recently added** ROI: within it, pixels whose intensity changes most during the first 3 s (top 10%, at least 12 px) are enclosed by a polygon. Press again (**Undo Auto ROI**) to restore the original ROI. |
| **Calculate** | Calculates the mean-intensity trace of each ROI (minus background) and draws it in the graphs. |
| **Save ROI** | Stores the current ROIs with their analyses (see [section 9](#9-save-roi-and-the-saved-roi-table)). |
| **Clear ROIs** | Removes the current (unsaved) ROIs and their analyses. |

Notes:

- The first **Calculate** loads the whole movie into memory; this can take time
  and requires sufficient RAM.
- Moving or reshaping an ROI does not update its trace automatically. Press
  **Calculate** again.

## 6. Graph analysis panel

### Upper graph: whole recording and analysis range

- Shows the complete traces. White traces are uncorrected; yellow traces are
  photobleaching-corrected.
- The **orange band** is the transient analysis range (**Tran.**). Drag the band
  or its edges, or type **Start** and **End**. Choose a period of stable pacing.
- The photobleaching fit window follows this range unless it is changed manually
  (see [section 7](#7-photobleaching-correction)).

### Lower graph: detail view

- Zoom with the mouse wheel and pan by dragging.
- **Detail view X / Y**, **Start** and **End**, set the displayed time and intensity range
  exactly.

## 7. Photobleaching correction

Optional. A robust straight line is fitted to baseline points (outside detected
transients) within the fit window, and the trace is corrected by it.

| Control | Action |
| --- | --- |
| **Cal. Photobleaching** | Calculates a preview. Yellow dashed line: fitted baseline. Red dotted points: baseline samples used for the fit. Traces are not changed yet. |
| **Confirm Photobleaching** | Applies the correction. Traces turn yellow. Any transient analysis is cleared; press **Calculate transients** again. |
| **Reset Photobleaching** | Returns to the uncorrected traces and default parameters. |

Correction method (shown in the Status box):

- **ratio**, used when the fitted line stays positive: corrected = trace ÷ fit × fit value at the window start.
- **subtract**, used otherwise: corrected = trace − fit + fit value at the window start.

While a preview is shown, changing any parameter recalculates it immediately.

| Parameter | Default | Meaning |
| --- | --- | --- |
| **Pre** | 50 ms | Time excluded before each detected transient start |
| **Post** | 200 ms | Time excluded after each detected transient recovery |
| **Base** | 10 % | Minimum fraction of points in the fit window that must remain as baseline; otherwise the ROI is skipped |
| **Fit S / Fit E** | Tran. range | Start and end of the fit window (s from the recording start) |
| **Robust** | 1.0 × | Outlier tolerance. Lower values reduce the influence of outliers more strongly |

## 8. Transient analysis

### Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| **Peak cutoff** | 3 × | A peak must exceed this multiple of the baseline noise. Lower values detect smaller peaks. |
| **Pacing interval** | 450 ms | Default for 2-Hz pacing. For other rates, enter the stimulation interval × 0.9 (1 Hz → 900 ms). Detection allows 10% shorter spacing; this value also sets the recovery-analysis window. |
| **Before start** | 50 ms | Trace kept before each onset. The mean of this period is **F₀** for that event. |
| **Decay 1 / 2 / 3** | 10 / 50 / 90 % | Decay levels reported. Press **Calculate transients** after changing them. |

### Calculate transients

Press **Calculate transients**. For each ROI, within the **Tran.** range, MOSAIC
accepts a peak only if it has

1. a stable baseline before the rise,
2. an amplitude above **Peak cutoff**,
3. a complete return toward baseline within the **Pacing interval**, and
4. a rise that is shorter than its recovery.

Accepted events are aligned at onset and normalized to F/F₀.

- **Average graph**: thin lines are individual events; the thick line is their
  mean. X axis: time from transient start.
- **Status box**: number of events used, e.g. `11/11 selected events`.

If no transient is detected, lower **Peak cutoff**, check the **Tran.** range,
or check the **Pacing interval**.

### Event table

| Column | Meaning |
| --- | --- |
| **Use** | Tick to include the event in the average and summary; untick to exclude it. |
| **Event** | ROI name and event number |
| **Ab_start / Ab_peak** | Absolute time (s) of onset and peak |
| **Peak time ms** | Time to peak: onset (10% amplitude) → peak |
| **Amp dF/F0** | Amplitude normalized to F₀ |
| **Max d(F/F0)/dt** | Maximum rising rate between onset and peak (s⁻¹) |
| **Ab_decay X%** | Absolute time (s) when the trace has decayed by X% |
| **Decay time X% ms** | Time from peak to X% decay |

`NA` means the value could not be measured (for example, the trace did not decay
to that level within the window).

## 9. Save ROI and the Saved ROI table

**Save ROI** stores every current ROI with its trace, detected events, their
**Use** selections, and the summary. The saved ROIs are locked, drawn in white
with their number, and the workspace is cleared for the next cell.

Saved ROI table:

| Column | Meaning |
| --- | --- |
| **Use** | Include this ROI in the export. Unticking also hides it in the image. |
| **ROI** | Saved ROI number |
| **Tran N** | Number of accepted (ticked) events |
| **Tran Amp dF/F0**, **Tran Peak ms**, **Tran Max d(F/F0)/dt**, **Tran Decay X% ms** | Means over the accepted events |

- Click a row to display that ROI's saved analysis. If an unsaved ROI exists,
  MOSAIC asks before clearing it.
- While a saved ROI is displayed, ticking or unticking **Use** in the event table
  updates its summary.

## 10. Export and reload

**Save** writes all saved ROIs whose **Use** is ticked to a folder named
`<movie name>_ana` next to the ND2 file (existing files are overwritten):

| File | Contents |
| --- | --- |
| `analysis.xlsx` | Numeric ROI summaries, without rounding to displayed text; missing values are blank |
| `rawtrace.xlsx` | Time and background-corrected intensity of each ROI, before photobleaching correction |
| `transient.xlsx` | Time and mean F/F₀ transient of each ROI |
| `ROI.jpg` | First frame with saved ROI outlines and numbers |
| `analysis_info.json` | All saved ROIs and selection flags, results, versions, and calculation settings (source ND2 is still required) |

**Load Info** → select `analysis_info.json`. The source is checked at its stored
path and nearby relative paths; if necessary, select the original ND2 again.
New sessions check file size and sampled content to avoid a wrong recording.
Schema-1 results load without invented settings. Results are not recomputed,
and restoring them does not reset every parameter control to that ROI's values.
Inspect `analysis_settings` before reanalysis. JSON retains unchecked ROIs too.

## 11. Parameter reference

| Group | Parameter | Default | Adjustable |
| --- | --- | --- | --- |
| Background | Recommend radius R | 10 px | Yes |
| Transient | Peak cutoff | 3 × noise | Yes |
| Transient | Pacing interval | 450 ms | Yes |
| Transient | Before start (F₀ window) | 50 ms | Yes |
| Transient | Decay levels | 10, 50, 90 % | Yes |
| Photobleaching | Pre / Post padding | 50 / 200 ms | Yes |
| Photobleaching | Minimum baseline | 10 % | Yes |
| Photobleaching | Fit window | Tran. range | Yes |
| Photobleaching | Robustness | 1.0 × | Yes |
| Transient | Smoothing window | 20 ms | No |
| Transient | Onset threshold | 10 % of amplitude | No |
| Transient | Recovery criterion | < 25 % of amplitude for 30 ms | No |
| Auto ROI | Analysis period / pixel fraction | first 3 s / top 10 % | No |

## 12. Troubleshooting

| Symptom | What to check |
| --- | --- |
| `Failed to create .venv` on first launch | Folder is inside Dropbox/OneDrive, or Python is not installed. Move MOSAIC to a local disk, delete `.venv`, and launch again. |
| Program becomes very slow or closes after **Calculate** | Not enough memory for the whole movie. Use a computer with more RAM. |
| Image looks clipped | Contrast for >8-bit recordings is fixed from the first frame; display limits do not change measurements. |
| **Tran N** is lower than the number of beats | Check that the pacing interval matches the stimulation rate (450 ms at 2 Hz), leave a full interval after the last peak, and check baseline/recovery/shape criteria. |
| `No transients detected` | Lower **Peak cutoff**; check the **Tran.** range and background position. |
| **Save** button disabled | Press **Save ROI** at least once. |
| Source recording cannot be located on **Load Info** | Select the original ND2 in the relocation dialog. A different file will fail the new-session identity check. |
