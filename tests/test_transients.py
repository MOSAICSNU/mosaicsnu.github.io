"""Regression cases for timing, event counting, and photobleaching masks."""

import unittest

import numpy as np

from mosaic.transient import TransientAnalysisMixin
from mosaic.photobleaching import PhotobleachingMixin


class Value:
    def __init__(self, value):
        self.number = value

    def value(self):
        return self.number


class Analyzer(TransientAnalysisMixin, PhotobleachingMixin):
    def __init__(self, pacing=0.5):
        self.pacing = pacing
        self.transient_min_prominence_spinbox = Value(0)
        self.transient_prominence_noise_spinbox = Value(3)
        self.transient_start_fraction_spinbox = Value(0.1)
        self.transient_table_decay_percents = [10, 50, 90]

    def transient_pacing_interval_s(self):
        return self.pacing

    def transient_smooth_s(self):
        return 0.02

    def bleach_fit_window_s(self):
        return (0, 8)

    def bleach_pre_padding_s(self):
        return 0.05

    def bleach_post_padding_s(self):
        return 0.10


def paced_trace(dt=0.002, jitter=0.0):
    time = np.arange(0, 8, dt)
    starts = np.arange(0.4, 7.5, 0.5)
    starts += jitter * np.sin(np.arange(starts.size))
    trace = np.full(time.shape, 100.0)
    for onset in starts:
        x = time - onset
        rise = (x >= 0) & (x < 0.02)
        decay = (x >= 0.02) & (x < 0.32)
        trace[rise] += 100 * x[rise] / 0.02
        trace[decay] += 100 * np.exp(-(x[decay] - 0.02) / 0.06)
    return time, trace, starts


class TransientTests(unittest.TestCase):
    def test_nominal_pacing_does_not_drop_alternate_beats(self):
        # 0.45 s is the default; 0.5 s is the nominal 2-Hz interval.
        for pacing in (0.45, 0.5):
            for dt in (0.002, 0.00201, 0.004):
                with self.subTest(pacing=pacing, dt=dt):
                    time, trace, starts = paced_trace(dt)
                    events = Analyzer(pacing).detect_transient_events(time, trace, 0, 8)
                    # Only peaks with a full analysis window count as measurements.
                    expected = sum(onset + 0.03 + pacing < time[-1] for onset in starts)
                    self.assertEqual(len(events), expected)

    def test_small_pacing_jitter_keeps_recovered_beats(self):
        time, trace, starts = paced_trace(jitter=0.012)
        events = Analyzer().detect_transient_events(time, trace, 0, 8)
        expected = sum(onset + 0.03 + 0.5 < time[-1] for onset in starts)
        self.assertEqual(len(events), expected)

    def test_flat_trace_has_no_events(self):
        time = np.arange(0, 4, 0.002)
        self.assertEqual(Analyzer().detect_transient_events(time, np.ones(time.size), 0, 4), [])

    def test_incomplete_recovery_is_rejected(self):
        time = np.arange(0, 2, 0.002)
        trace = np.where(time < 0.4, 100.0, 200.0)
        self.assertEqual(Analyzer().detect_transient_events(time, trace, 0, 2), [])

    def test_decay_crossing_is_interpolated(self):
        result = Analyzer().decay_crossing_time_s(
            np.array([0., 1., 2.]), np.array([2., 1.5, 1.]), 0, 1, 1, 25
        )
        self.assertAlmostEqual(result, 0.5)

    def test_photobleaching_excludes_all_interior_peaks(self):
        time, trace, starts = paced_trace()
        mask = Analyzer().photobleaching_baseline_mask(time, trace)
        for onset in starts[:-1]:
            self.assertFalse(mask[np.argmin(np.abs(time - onset - 0.02))])

    def test_photobleaching_excludes_peak_near_fit_boundary(self):
        time, trace, starts = paced_trace()
        analyzer = Analyzer()
        analyzer.bleach_fit_window_s = lambda: (0.2, 7.6)
        mask = analyzer.photobleaching_baseline_mask(time, trace)
        for onset in starts:
            self.assertFalse(mask[np.argmin(np.abs(time - onset - .02))])

    def test_incomplete_peak_is_masked_but_not_measured(self):
        time, trace, _ = paced_trace()
        selected = time <= 7.5
        time, trace = time[selected], trace[selected]
        analyzer = Analyzer()
        events = analyzer.detect_transient_events(time, trace, 0, 7.5)
        self.assertTrue(all(event['peak_time_s'] < 7.4 for event in events))
        mask = analyzer.photobleaching_baseline_mask(time, trace)
        self.assertFalse(mask[np.argmin(np.abs(time - 7.42))])


if __name__ == '__main__':
    unittest.main()
