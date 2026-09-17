# Validation of v0.2.0

Checked on Windows 11 with Python 3.13.2, nd2 0.11.3, NumPy 2.5.3,
SciPy 1.18.1, PySide6 6.11.2, and PyQtGraph 0.14.0.

## Regression tests

`python -m unittest discover -s tests -v` covers:

- Nominal 2-Hz pacing at 2.00-, 2.01-, and 4-ms sampling intervals.
- Small cycle jitter without alternate-beat rejection.
- Flat traces and incomplete recovery; interpolated decay crossings.
- Photobleaching masks excluding interior synthetic event peaks.
- Supported image dimensions, missing/invalid timing, >8-bit display without
  modification of measurement pixels.
- Portable sessions and source identity mismatch; schema validation and
  preservation of an old JSON when a write fails.
- A real Qt window driven by synthetic ND2 arrays: event exclusion, export,
  reload, legacy sessions, original calculation settings after control changes,
  numeric summary output, and detection of changed ROI geometry.

## Example recording

File: `MOSAIC_example_2Hz.nd2`, 4000 frames, 288 × 240, uint8.
Signal rectangle at (52, 101), size (206, 28); background ellipse at
(236, 192), size (36, 36); analysis range 0.2–7.8 s; ratio photobleaching
correction confirmed; Pacing interval 450 ms.

| Quantity | Value |
| --- | ---: |
| Accepted events | 14 |
| Amplitude ΔF/F₀ | 1.474795 |
| Time to peak, ms | 28.571265 |
| Maximum rise, s⁻¹ | 74.365453 |
| Decay 10%, ms | 23.590318 |
| Decay 50%, ms | 61.488679 |
| Decay 90%, ms | 133.516511 |

Three spreadsheets, an ROI image, and a JSON session were generated in a
separate directory, and reloaded summary values were checked.

## Scope

These are software regression tests and one real-recording example, not
validation of all experimental datasets or biological conclusions. CI is
configured for Windows/macOS/Linux with Python 3.10 and 3.13. Missing or
abnormal events, motion artifacts, and operator decisions require review of
the original data.
