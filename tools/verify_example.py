"""Read a real example without changing its existing analysis directory.

Run: python tools/verify_example.py recording.nd2 --output validation/example.json
The output directory contains the newly generated test exports only.
"""

import argparse
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase
from mosaic.main import MainWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('recording', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pg.setConfigOptions(imageAxisOrder='row-major')
    app = QApplication([])
    # Qt's Windows offscreen plugin may not discover installed fonts.
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'segoeui.ttf'
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 9))
    window = MainWindow()
    report = {'software': window.software_environment(), 'conditions': {}}
    try:
        for pacing in (450, 500):
            window.load_nd2(args.recording)
            if window.reader is None:
                raise RuntimeError(window.info_label.text())
            window.transient_pacing_interval_spinbox.setValue(pacing)
            window.set_background_roi(pos=(236., 192.), size=(36, 36))
            window.roi_shape_combo.setCurrentIndex(1)
            window.add_signal_roi()
            window.rois[-1].setPos((52., 101.))
            window.rois[-1].setSize((206., 28.))
            window.calculate_traces()
            window.set_time_selection_interval(window.transient_region,
                window.transient_start_spinbox, window.transient_end_spinbox, (.2, 7.8))
            window.sync_default_photobleaching_fit_window_to_transient()
            window.calculate_photobleaching_preview()
            preview_status = window.info_label.text()
            window.confirm_photobleaching()
            window.calculate_transient_average()
            folder = args.output.parent / f'exports-{pacing}ms'
            folder.mkdir(exist_ok=True)
            window.resize(1600, 1000)
            window.show()
            app.processEvents()
            window.grab().save(str(folder / 'window.png'))
            count = len(window.transient_records)
            peaks = [r['peak_time_s'] for r in window.transient_records]
            window.save_current_roi_analysis()
            if len(window.saved_roi_entries) != 1:
                raise AssertionError('Expected one saved ROI')
            entry = window.saved_roi_entries[0]
            report['conditions'][str(pacing)] = {
                'events': count, 'peak_times_s': peaks,
                'photobleaching_status': preview_status, 'summary': entry['summary'],
            }
            window.write_xlsx(folder / 'analysis.xlsx', window.analysis_xlsx_rows([entry]), 'analysis')
            window.write_xlsx(folder / 'rawtrace.xlsx', window.raw_trace_xlsx_rows([entry]), 'rawtrace')
            window.write_xlsx(folder / 'transient.xlsx', window.paired_trace_xlsx_rows(
                [entry], 'transient_time_s', 'transient_mean_trace', 'transient'), 'transient')
            window.save_roi_overlay_image(folder / 'ROI.jpg', [entry])
            window.save_session_info(folder / 'analysis_info.json')
            summary_before = entry['summary'].copy()
            window.load_analysis_info(folder / 'analysis_info.json')
            assert window.saved_roi_entries[0]['summary'] == window.json_safe_value(summary_before)
        assert report['conditions']['500']['events'] >= 14, report
        report = window.json_safe_value(report)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        window.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
