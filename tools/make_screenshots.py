"""Drive MOSAIC with the example ND2 and capture tutorial screenshots."""
import json
import shutil
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication

pg.setConfigOptions(imageAxisOrder="row-major")
app = QApplication([])
from mosaic.main import MainWindow  # noqa: E402

EXAMPLE = Path("D:/MOSAIC-example/MOSAIC_example_2Hz.nd2")
OUT = Path("D:/mosaicsnu.github.io/assets/img")
OUT.mkdir(parents=True, exist_ok=True)
ACCENT = QColor("#0F6E66")

w = MainWindow()
w.setAttribute(Qt.WA_DontShowOnScreen, True)
w.resize(1600, 1000)
w.show()


def settle():
    for _ in range(5):
        app.processEvents()


def shot(name):
    settle()
    w.grab().save(str(OUT / name))
    print("saved", name)


def badge(painter, x, y, number):
    r = 12
    painter.setPen(QPen(QColor("#FFFFFF"), 2))
    painter.setBrush(ACCENT)
    painter.drawEllipse(QPoint(int(x), int(y)), r, r)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRect(int(x) - r, int(y) - r, 2 * r, 2 * r), Qt.AlignCenter, str(number))


def annotate(root, items, name, gutter=False, labels=None):
    """Number widgets: a left gutter for single-column panels, boxes otherwise."""
    settle()
    src = root.grab()
    pad = 34 if gutter else 14
    pix = src.__class__(src.width() + pad + (0 if gutter else 14), src.height() + (0 if gutter else 28))
    pix.fill(QColor("#FFFFFF"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    oy = 0 if gutter else 14
    painter.drawPixmap(pad, oy, src)
    for number, (widget, where) in enumerate(items, start=1):
        pos = widget.mapTo(root, QPoint(0, 0))
        rect = QRect(pos.x() + pad, pos.y() + oy, widget.width(), widget.height())
        text = labels[number - 1] if labels else number
        if gutter:
            badge(painter, pad / 2, rect.center().y(), text)
            continue
        painter.setPen(QPen(ACCENT, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4, 4)
        badge(painter, rect.left() - 2, rect.top() - 2, text)
    painter.end()
    pix.save(str(OUT / name))
    print("saved", name, "with", len(items), "badges")


results = {}

# 1. Start screen
shot("01-start.png")

# 2. Open ND2
w.load_nd2(EXAMPLE)
shot("02-open.png")
annotate(
    w,
    [(w.control_dock, ""), (w.image_view, ""), (w.analysis_dock, ""), (w.graph_dock, "")],
    "00-layout.png",
    labels=["A", "B", "C", "D"],
)
# Pacing interval is set first: photobleaching baseline detection uses it too.
w.transient_pacing_interval_spinbox.setValue(450)

# 3. Background ROI on a cell-free area (as if dragged there)
w.set_background_roi(pos=(236.0, 192.0), size=(36, 36))
shot("03-background.png")

# 4. Rectangle ROI over the horizontal cardiomyocyte
w.roi_shape_combo.setCurrentIndex(1)
w.add_signal_roi()
roi = w.rois[-1]
roi.setPos((52.0, 101.0))
roi.setSize((206.0, 28.0))
shot("04-roi.png")

# 5. Calculate traces
w.calculate_traces()
shot("05-calculate.png")

# 6. Analysis range and zoomed detail view
w.set_time_selection_interval(
    w.transient_region, w.transient_start_spinbox, w.transient_end_spinbox, (0.2, 7.8)
)
w.sync_default_photobleaching_fit_window_to_transient()
w.detail_plot.setXRange(1.0, 3.0, padding=0)
shot("06-range.png")

# 7-8. Photobleaching preview and confirmation
w.calculate_photobleaching_preview()
results["photobleaching_status"] = w.info_label.text()
shot("07-photobleaching-preview.png")
w.confirm_photobleaching()
w.detail_plot.setXRange(1.0, 3.0, padding=0)
shot("08-photobleaching-confirmed.png")

# 9. Transient analysis with the documented Pacing interval setting
w.calculate_transient_average()
results["transient_status_450"] = w.info_label.text()
results["events_450"] = len(w.transient_records)
peak = float(w.transient_records[0]["peak_time_s"]) if w.transient_records else 0.0
w.set_frame_index(int(np.argmin(np.abs(w.graph_time_s - peak))))
w.detail_plot.setXRange(1.0, 3.0, padding=0)
shot("09-transients.png")

annotate(
    w.analysis_dock.widget().widget(),
    [
        (w.transient_calculate_button, "left"),
        (w.transient_prominence_noise_spinbox.parentWidget(), "left"),
        (w.transient_pacing_interval_spinbox.parentWidget(), "left"),
        (w.transient_pre_start_spinbox.parentWidget(), "left"),
        (w.transient_decay_percent_spinboxes[0].parentWidget(), "left"),
        (w.transient_decay_percent_spinboxes[1].parentWidget(), "left"),
        (w.transient_decay_percent_spinboxes[2].parentWidget(), "left"),
        (w.transient_average_plot, "corner"),
        (w.transient_table, "corner"),
        (w.saved_roi_table, "corner"),
    ],
    "panel-analysis.png",
)
annotate(
    w.graph_dock.widget(),
    [
        (w.transient_start_spinbox, "left"),
        (w.transient_end_spinbox, "left"),
        (w.overview_plot, "corner"),
        (w.detail_x_start_spinbox, "left"),
        (w.detail_y_start_spinbox, "left"),
        (w.detail_plot, "corner"),
    ],
    "panel-graph.png",
)

control_panel = w.control_dock.widget().widget()
control_panel.resize(control_panel.width(), control_panel.sizeHint().height())
annotate(
    control_panel,
    [
        (w.open_button, "left"),
        (w.close_nd_button, "left"),
        (w.file_label, "left"),
        (w.save_results_button, "left"),
        (w.load_info_button, "left"),
        (w.play_button, "left"),
        (w.frame_label, "left"),
        (w.frame_slider, "left"),
        (w.frame_spinbox, "left"),
        (w.background_button, "left"),
        (w.recommend_background_button, "left"),
        (w.background_radius_spinbox, "left"),
        (w.clear_background_button, "left"),
        (w.roi_shape_combo.parentWidget(), "left"),
        (w.add_roi_button, "left"),
        (w.auto_roi_button, "left"),
        (w.calculate_button, "left"),
        (w.save_roi_button, "left"),
        (w.clear_roi_button, "left"),
        (w.correct_bleaching_button, "left"),
        (w.confirm_bleaching_button, "left"),
        (w.reset_bleaching_button, "left"),
        (w.bleach_pre_padding_spinbox.parentWidget(), "left"),
        (w.bleach_post_padding_spinbox.parentWidget(), "left"),
        (w.bleach_min_baseline_spinbox.parentWidget(), "left"),
        (w.bleach_fit_start_spinbox.parentWidget(), "left"),
        (w.bleach_fit_end_spinbox.parentWidget(), "left"),
        (w.bleach_robustness_spinbox.parentWidget(), "left"),
        (w.info_label, "left"),
    ],
    "panel-controls.png",
    gutter=True,
)

# Record what the default 500 ms setting reports, then restore 450 ms
w.transient_pacing_interval_spinbox.setValue(500)
w.calculate_transient_average()
results["events_500"] = len(w.transient_records)
results["transient_status_500"] = w.info_label.text()
w.detail_plot.setXRange(0.2, 7.8, padding=0)
shot("limit-pacing-500ms.png")
w.transient_pacing_interval_spinbox.setValue(450)
w.calculate_transient_average()
w.detail_plot.setXRange(0.2, 7.8, padding=0)
shot("limit-pacing-450ms.png")
w.transient_pacing_interval_spinbox.setValue(450)
w.calculate_transient_average()

# 10. Save ROI
w.save_current_roi_analysis()
entry = w.saved_roi_entries[-1]
results["saved_summary"] = {k: (None if isinstance(v, float) and not np.isfinite(v) else v)
                            for k, v in entry["summary"].items() if k.startswith("transient")}
results["saved_row"] = w.saved_roi_row_values(entry)
results["saved_headers"] = w.saved_roi_headers_without_use()
shot("10-save-roi.png")

# 11. Export
w.save_analysis_outputs()
results["export_status"] = w.info_label.text()
ana = EXAMPLE.parent / f"{EXAMPLE.stem}_ana"
shutil.copy(ana / "ROI.jpg", OUT / "11-roi-output.jpg")
shot("11-export.png")

# 12. Load Info after closing
w.close_loaded_nd2()
w.load_analysis_info(ana / "analysis_info.json")
results["load_status"] = w.info_label.text()
w.saved_roi_table.setCurrentCell(0, 1)
shot("12-load-info.png")

results["recording"] = {"frames": 4000, "height": 240, "width": 288, "dtype": "uint8",
                        "duration_s": float(w.graph_time_s[-1]) if w.graph_time_s.size else None}
Path("D:/mosaicsnu.github.io/assets/example-results.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)
print(json.dumps(results, indent=2, ensure_ascii=False, default=str))
