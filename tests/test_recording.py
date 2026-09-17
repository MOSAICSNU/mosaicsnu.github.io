import unittest
import numpy as np
from mosaic.recording import calibrated_times, display_levels, validate_dimensions


class RecordingTests(unittest.TestCase):
    def test_internal_and_edge_timestamp_gaps(self):
        np.testing.assert_allclose(
            calibrated_times([None, 10.002, None, 10.006, None]),
            [10, 10.002, 10.004, 10.006, 10.008],
        )

    def test_invalid_timing_is_not_assumed_to_be_one_fps(self):
        for values in ([None, None], [1, None], [1, 1], [2, 1], [np.nan, np.inf]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                calibrated_times(values)

    def test_dimensions(self):
        validate_dimensions({'T': 10, 'Y': 20, 'X': 30, 'C': 1})
        for sizes in ({'Y': 20, 'X': 30}, {'T': 10, 'Y': 20, 'X': 30, 'C': 2}):
            with self.assertRaises(ValueError):
                validate_dimensions(sizes)

    def test_display_preserves_original_pixels(self):
        frame = np.arange(10000, dtype=np.uint16).reshape(100, 100)
        before = frame.copy()
        low, high = display_levels(frame)
        self.assertGreater(high, 255)
        self.assertLess(low, high)
        np.testing.assert_array_equal(frame, before)
        self.assertEqual(display_levels(np.zeros((2, 2), dtype=np.uint8)), (0, 255))
