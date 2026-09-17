# Changelog

## 0.2.0 — 2026-09-16

### Analysis changes

- Fix alternate-beat rejection at nominal pacing. Minimum peak spacing allows
  10% timing variation; duplicate suppression ends after sustained recovery.
  The full pacing interval still bounds decay measurements.
- Default Pacing interval is 450 ms for 2-Hz pacing.
- The same change affects photobleaching exclusion. Reanalysis may change
  event counts and summary measurements.
- Exclude candidate transients at bleaching-fit boundaries using adjacent
  recording context. Incomplete candidates are masked, not accepted as kinetic
  measurements. This can change bleaching-corrected amplitudes even when event
  counts are unchanged.
- Interpolate missing timestamps at actual frame indices, extrapolate edge
  gaps, reject insufficient/non-increasing timestamps, and remove the implicit
  one-second-per-frame fallback from loaded recordings.

### Reproducibility and usability

- JSON schema 2 records calculation settings per ROI, software/dependency
  versions, applied bleaching settings, and background geometry.
- Read schema 1 without inventing metadata. Locate moved ND2 files with sampled
  identity checks for new sessions. Replace JSON atomically after writing.
- Export numeric summary cells instead of rounded display strings.
- Calibrate >8-bit display from the first frame, including ROI images, without
  altering measurements. Show relative playback time.
- Reject unsupported varying ND2 dimensions explicitly.
- Prevent saving/processing stale traces after signal or background ROI geometry changes.
- Python >=3.10, one dependency list, console entry point, launcher checks,
  regression tests, CI configuration, and versioned documentation.

### Remaining limitations

Synchronous full-movie RAM loading, fixed ROIs, 20-ms smoothing and existing
baseline/recovery/shape gates remain. This release does not add motion
correction, multichannel analysis, or new biological validation.

## 0.1.0

Initial version.
