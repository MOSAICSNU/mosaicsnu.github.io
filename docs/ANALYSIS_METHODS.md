# Analysis methods in v0.2.0

This describes the implementation, not an independent biological validation.

## Timing and fluorescence

ND2 event timestamps are mapped to frame indices. Interior gaps are
interpolated; edge gaps use the median time step per frame between known
frames. Duplicate/reversed timestamps and fewer than two usable timestamps
are rejected. Time is referenced to frame zero. The median positive frame
interval discretizes detection windows.

PyQtGraph ROI masks retain fractional boundary weights. Intensity is the
weighted mean of original pixel values; background is subtracted per frame.
Display contrast does not change measured values.

## Detection and measurements

1. Restrict traces to the analysis range and apply a centered moving average
   of approximately 20 ms, rounded to whole samples.
2. Estimate robust noise from the lower half of the smoothed trace. Candidates
   must exceed max(absolute cutoff, Peak cutoff × noise).
3. Rank local peaks by prominence. Minimum spacing is 90% of the entered
   pacing interval, rounded down to samples. This fixed tolerance permits
   timing variation in paced recordings; frequency is not inferred.
4. Find the recent stable pre-peak baseline. Onset is the first sampled upward
   crossing of 10% of amplitude; onset is not linearly interpolated. Peak and
   maximum rising slope use samples of the smoothed trace. Decay crossings
   are linearly interpolated.
5. Require recovery below 25% of amplitude for 30 ms, a rise shorter than
   recovery, and a full pacing interval after the peak within the analysis
   range. Duplicate suppression ends after the recovery hold, not another
   full pacing interval.

F₀ is the mean pre-onset fluorescence of the aligned, unsmoothed analysis
trace (default 50 ms). Amplitude and maximum slope measured on the smoothed
trace are divided by F₀. F₀ and the local detection baseline are distinct.

Waveforms are aligned from 50 ms before onset to one pacing interval after
onset and normalized as F/F₀. They use the analysis trace before detection
smoothing; at least 80% of the window must be observed. ROI summaries average
per-event measurements, not measurements of the mean waveform. A decay
summary omits non-finite values: its denominator can differ from Tran N.

## Photobleaching and limits

Candidate intervals plus padding are excluded from the fit window. Detection
uses one pacing interval of recording context outside each fit boundary.
Incomplete candidates are masked through their available window; they are not
accepted as kinetic measurements. Bleaching exclusion does not require the
measurement shape gate, so a rejected candidate is not automatically treated
as baseline.
A robust straight line is fitted to the remaining baseline. Positive fits
use ratio correction, otherwise additive correction. Inspect the preview:
missed peaks or artifacts can still contaminate baseline points.

The 20-ms smoothing and baseline/recovery/shape gates affect fast or unusual
signals. Detection changes can alter both event selection and bleaching
correction. High acquisition speed does not eliminate these analysis effects.
Regression tests do not establish method equivalence or biological validity.

Keep the software version with each set of results, and report the settings
actually used.
