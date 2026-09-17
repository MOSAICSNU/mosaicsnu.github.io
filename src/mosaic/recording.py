"""Validation and display calibration that never modify measured pixels."""

import numpy as np


def validate_dimensions(sizes):
    if any(int(sizes.get(axis, 0)) < 1 for axis in ("T", "Y", "X")):
        raise ValueError("A time-lapse ND2 with T, Y and X dimensions is required.")
    extra = {key: value for key, value in sizes.items() if key not in ("T", "Y", "X") and int(value) > 1}
    if extra:
        raise ValueError(f"Only single-channel T x Y x X ND2 recordings are supported; found {extra}.")


def calibrated_times(values):
    """Interpolate at actual frame indices; extrapolate edges using median dt."""
    times = np.asarray([np.nan if value is None else value for value in values], dtype=float)
    indices = np.flatnonzero(np.isfinite(times))
    if indices.size < 2:
        raise ValueError("At least two valid ND2 timestamps are required for kinetic measurements.")
    recorded = times[indices]
    if np.any(np.diff(recorded) <= 0):
        raise ValueError("ND2 timestamps must increase strictly; duplicate or reversed times were found.")
    dt = float(np.median(np.diff(recorded) / np.diff(indices)))
    frames = np.arange(times.size)
    result = np.interp(frames, indices, recorded)
    before, after = frames < indices[0], frames > indices[-1]
    result[before] = recorded[0] + (frames[before] - indices[0]) * dt
    result[after] = recorded[-1] + (frames[after] - indices[-1]) * dt
    return result


def display_levels(frame):
    """Keep the 8-bit presentation; use first-frame contrast for other types."""
    if frame.dtype == np.uint8:
        return (0.0, 255.0)
    finite = frame[np.isfinite(frame)]
    if not finite.size:
        return (0.0, 1.0)
    low, high = np.percentile(finite, [0.5, 99.5])
    if high <= low:
        low, high = float(np.min(finite)), float(np.max(finite))
    return (float(low), float(max(high, low + 1)))
