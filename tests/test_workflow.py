"""Exercise the real Qt window with a deterministic in-memory ND2 reader."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from mosaic.main import MainWindow
from test_transients import paced_trace


class Reader:
    def __init__(self, path):
        self.time, trace, _ = paced_trace()
        self.sizes = {'T': self.time.size, 'Y': 16, 'X': 16}
        self.dtype = np.dtype('uint16')
        self.stack = np.broadcast_to(trace[:, None, None], (trace.size, 16, 16)).astype('uint16').copy()

    def events(self):
        return [{'T Index': i, 'Time [s]': t + 1000} for i, t in enumerate(self.time)]

    def read_frame(self, i):
        return self.stack[i]

    def asarray(self):
        return self.stack.copy()

    def close(self):
        pass


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg.setConfigOptions(imageAxisOrder='row-major')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'recording.nd2'
        self.path.write_bytes(b'fake ND2 for integration tests')
        self.reader_patch = patch('mosaic.movie.nd2.ND2File', Reader)
        self.reader_patch.start()
        self.window = MainWindow()
        self.window.load_nd2(self.path)

    def tearDown(self):
        self.window.close()
        self.reader_patch.stop()
        self.temp.cleanup()

    def analyze(self):
        w = self.window
        w.add_signal_roi()
        w.rois[-1].setPos((2, 2))
        w.rois[-1].setSize((10, 10))
        w.calculate_traces()
        w.set_time_selection_interval(w.transient_region, w.transient_start_spinbox,
                                      w.transient_end_spinbox, (0, 7.99))
        w.calculate_transient_average()
        self.assertEqual(len(w.transient_records), 15)

    def test_export_reload_and_calculation_time_metadata(self):
        self.analyze()
        w = self.window
        # Changing an input after calculation must not rewrite its provenance.
        w.transient_pacing_interval_spinbox.setValue(900)
        w.save_current_roi_analysis()
        entry = w.saved_roi_entries[0]
        self.assertEqual(entry['analysis_settings']['pacing_interval_s'], .45)
        w.save_analysis_outputs()
        folder = self.path.parent / 'recording_ana'
        self.assertEqual({p.name for p in folder.iterdir()},
                         {'analysis.xlsx', 'rawtrace.xlsx', 'transient.xlsx', 'ROI.jpg', 'analysis_info.json'})
        data = json.loads((folder / 'analysis_info.json').read_text())
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['software']['mosaic_version'], '0.2.0')
        self.assertEqual(data['entries'][0]['summary']['transient_n'], 15)
        w.load_analysis_info(folder / 'analysis_info.json')
        self.assertEqual(len(w.saved_roi_entries), 1)
        self.assertEqual(w.saved_roi_entries[0]['analysis_settings']['pacing_interval_s'], .45)
        self.assertIn('Time: 0.000000 s', w.frame_label.text())

    def test_legacy_session_does_not_gain_invented_settings(self):
        self.analyze()
        self.window.save_current_roi_analysis()
        path = self.path.parent / 'legacy.json'
        self.window.save_session_info(path)
        data = json.loads(path.read_text())
        data['version'] = 1
        for entry in data['entries']:
            for key in ('software', 'analysis_settings', 'photobleaching_settings', 'background_roi'):
                entry.pop(key, None)
        path.write_text(json.dumps(data))
        self.window.load_analysis_info(path)
        self.assertIsNone(self.window.saved_roi_entries[0]['analysis_settings'])
        self.assertIn('Legacy session', self.window.info_label.text())

    def test_event_exclusion_updates_saved_summary(self):
        self.analyze()
        w = self.window
        w.transient_table.item(0, 0).setCheckState(Qt.Unchecked)
        w.save_current_roi_analysis()
        self.assertEqual(w.saved_roi_entries[0]['summary']['transient_n'], 14)

    def test_changed_roi_cannot_be_saved_with_stale_trace(self):
        self.analyze()
        w = self.window
        w.rois[0].setPos((3, 3))
        w.save_current_roi_analysis()
        self.assertEqual(w.saved_roi_entries, [])
        self.assertIn('ROI geometry changed', w.info_label.text())

    def test_summary_exports_numeric_values(self):
        self.analyze()
        w = self.window
        w.save_current_roi_analysis()
        row = w.analysis_xlsx_rows(w.saved_roi_entries)[1]
        self.assertIsInstance(row[1], int)
        self.assertIsInstance(row[2], float)
        xml = w.xlsx_sheet_xml([row])
        self.assertIn('<c r="B1"><v>15</v></c>', xml)
