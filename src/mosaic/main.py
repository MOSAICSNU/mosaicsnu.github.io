"""Application entry point and MOSAIC main-window state."""

from __future__ import annotations

import sys
from pathlib import Path

import nd2
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
)
from .constants import (
    GRAPH_FOREGROUND,
    PHOTOBLEACH_DEFAULT_FIT_END_S,
    PHOTOBLEACH_DEFAULT_FIT_START_S,
    PHOTOBLEACH_DEFAULT_ROBUSTNESS_SCALE,
    PHOTOBLEACH_EVENT_POST_PADDING_S,
    PHOTOBLEACH_EVENT_PRE_PADDING_S,
    PHOTOBLEACH_MIN_BASELINE_FRACTION,
    PROJECT_ROOT,
    RECOMMENDED_BACKGROUND_RADIUS,
    SR_CALCIUM_DEFAULT_FIT_END_S,
    SR_CALCIUM_DEFAULT_FIT_START_S,
    SR_CALCIUM_DEFAULT_POST_START_S,
    SR_CALCIUM_DEFAULT_PRE_START_S,
    TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES,
    TRANSIENT_DEFAULT_PACING_INTERVAL_S,
    TRANSIENT_DEFAULT_PRE_START_S,
    TRANSIENT_DEFAULT_PROMINENCE_NOISE,
    TRANSIENT_DEFAULT_SMOOTH_S,
    TRANSIENT_DEFAULT_START_FRACTION,
)
from .movie import MovieRoiMixin
from .persistence import PersistenceMixin
from .photobleaching import PhotobleachingMixin
from .transient import TransientAnalysisMixin
from .ui import InterfaceMixin


class MainWindow(
    InterfaceMixin,
    MovieRoiMixin,
    PhotobleachingMixin,
    TransientAnalysisMixin,
    PersistenceMixin,
    QMainWindow,
):
    """Owns the shared Qt state while feature modules provide behavior."""

    def __init__(self) -> None:
        super().__init__()

        # Shared state is kept here so the feature mixins operate on one UI.
        # Movie timing, active ROI workspaces, analysis views, and saved ROI
        # snapshots are grouped below in the order they are initialized.
        self.reader: nd2.ND2File | None = None
        self.current_path: Path | None = None
        self.last_open_directory = PROJECT_ROOT
        self.movie_stack: np.ndarray | None = None
        self.frame_count = 0
        self.image_shape: tuple[int, int] | None = None
        self.frame_times_s: list[float | None] = []
        self.graph_time_s = np.array([], dtype=float)
        self.valid_time_values_s: list[float] = []
        self.valid_time_frame_indices: list[int] = []
        self.transient_interval_note: str | None = None
        self.transient_window_note: str | None = None
        self.current_frame_index = -1
        self.is_playing = False
        self.playback_start_wall_s = 0.0
        self.playback_start_movie_s = 0.0
        self.rois: list[pg.ROI] = []
        self.background_roi: pg.EllipseROI | None = None
        self.background_trace: np.ndarray | None = None
        self.trace_curves: dict[pg.ROI, tuple[pg.PlotDataItem, pg.PlotDataItem]] = {}
        self.roi_raw_traces: dict[pg.ROI, np.ndarray] = {}
        self.roi_traces: dict[pg.ROI, np.ndarray] = {}
        self.bleaching_fit_curves: dict[
            pg.ROI,
            tuple[pg.PlotDataItem, pg.PlotDataItem],
        ] = {}
        self.bleaching_baseline_curves: dict[
            pg.ROI,
            tuple[pg.PlotDataItem, pg.PlotDataItem],
        ] = {}
        self.photobleaching_preview_traces: dict[pg.ROI, np.ndarray] = {}
        self.photobleaching_preview_fit_lines: dict[pg.ROI, np.ndarray] = {}
        self.photobleaching_preview_baseline_masks: dict[pg.ROI, np.ndarray] = {}
        self.photobleaching_preview_modes: dict[pg.ROI, str] = {}
        self.photobleaching_parameter_updating = False
        self.photobleaching_fit_window_custom = False
        self.photobleaching_corrected = False
        self.detail_plot_has_data = False
        self.transient_average_curve: pg.PlotDataItem | None = None
        self.transient_event_curves: list[pg.PlotDataItem] = []
        self.transient_common_time = np.array([], dtype=float)
        self.transient_snippets = np.empty((0, 0), dtype=float)
        self.transient_records: list[dict[str, object]] = []
        self.transient_table_decay_percents = list(TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES)
        self.transient_status_suffix = ""
        self.transient_table_updating = False
        self.sr_calcium_curves: list[pg.PlotDataItem] = []
        self.sr_calcium_fit_curves: list[pg.PlotDataItem] = []
        self.sr_calcium_markers: list[pg.InfiniteLine] = []
        self.sr_calcium_records: list[dict[str, object]] = []
        self.sr_calcium_trace_segments: list[tuple[np.ndarray, np.ndarray]] = []
        self.sr_calcium_fit_segments: list[tuple[np.ndarray, np.ndarray]] = []
        self.sr_calcium_fit_reference_peak_s: float | None = None
        self.sr_calcium_fit_region_updating = False
        self.roi_names: dict[pg.ROI, str] = {}
        self.roi_pens: dict[pg.ROI, pg.Qt.QtGui.QPen] = {}
        self.auto_roi_originals: dict[pg.ROI, pg.ROI] = {}
        self.saved_roi_entries: list[dict[str, object]] = []
        self.saved_roi_table_updating = False
        self.saved_roi_selection_updating = False
        self.current_saved_roi_row: int | None = None
        self.saved_roi_counter = 0
        self.saved_decay_percents = list(TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES)
        self.roi_counter = 0
        self.selection_syncing = False
        self.detail_range_syncing = False

        # Create controls before building the docks that place them.
        self.setWindowTitle("MOSAIC")
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.AnimatedDocks
        )
        self.resize(1800, 1000)

        self.open_button = QPushButton("Open ND2")
        self.open_button.clicked.connect(self.open_file_dialog)

        self.close_nd_button = QPushButton("Close ND")
        self.close_nd_button.setEnabled(False)
        self.close_nd_button.clicked.connect(self.close_nd2_with_confirmation)

        self.file_label = QLineEdit("No file loaded")
        self.file_label.setReadOnly(True)
        self.file_label.setFrame(False)
        self.file_label.setMinimumWidth(0)
        self.file_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.info_label = QLabel("Open an ND2 file to display the first frame.")
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setMinimumWidth(0)
        self.info_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.frame_label = QLabel("Frame: -")
        self.frame_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.frame_label.setWordWrap(True)
        self.frame_label.setMinimumWidth(0)
        self.frame_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.play_button = QPushButton("Play")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_playback)

        self.add_roi_button = QPushButton("Add ROI")
        self.add_roi_button.setEnabled(False)
        self.add_roi_button.clicked.connect(self.add_signal_roi)

        self.roi_shape_combo = QComboBox()
        self.roi_shape_combo.addItem("Ellipse", "ellipse")
        self.roi_shape_combo.addItem("Rectangle", "rectangle")
        self.roi_shape_combo.setEnabled(False)
        self.roi_shape_combo.setMinimumContentsLength(len("Rectangle") + 2)
        self.roi_shape_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.roi_shape_combo.setToolTip(
            "Choose the shape used by Add ROI. Both shapes can be rotated."
        )

        self.auto_roi_button = QPushButton("(op) Auto ROI")
        self.auto_roi_button.setEnabled(False)
        self.auto_roi_button.clicked.connect(self.toggle_auto_roi)

        self.calculate_button = QPushButton("Calculate")
        self.calculate_button.setEnabled(False)
        self.calculate_button.clicked.connect(self.calculate_traces)

        self.save_roi_button = QPushButton("Save ROI")
        self.save_roi_button.setEnabled(False)
        self.save_roi_button.clicked.connect(self.save_current_roi_analysis)

        self.save_results_button = QPushButton("Save")
        self.save_results_button.setEnabled(False)
        self.save_results_button.clicked.connect(self.save_analysis_outputs)

        self.load_info_button = QPushButton("Load Info")
        self.load_info_button.clicked.connect(self.load_analysis_info_dialog)

        self.correct_bleaching_button = QPushButton("Cal. Photobleaching")
        self.correct_bleaching_button.setEnabled(False)
        self.correct_bleaching_button.clicked.connect(self.calculate_photobleaching_preview)

        self.confirm_bleaching_button = QPushButton("Confirm Photobleaching")
        self.confirm_bleaching_button.setEnabled(False)
        self.confirm_bleaching_button.clicked.connect(self.confirm_photobleaching)

        self.reset_bleaching_button = QPushButton("Reset Photobleaching")
        self.reset_bleaching_button.setEnabled(False)
        self.reset_bleaching_button.clicked.connect(self.reset_photobleaching)

        self.background_button = QPushButton("Add Background")
        self.background_button.setEnabled(False)
        self.background_button.clicked.connect(lambda: self.set_background_roi())

        self.recommend_background_button = QPushButton("Recommend Background")
        self.recommend_background_button.setEnabled(False)
        self.recommend_background_button.clicked.connect(self.recommend_background_roi)

        self.background_radius_spinbox = QSpinBox()
        self.background_radius_spinbox.setEnabled(False)
        self.background_radius_spinbox.setMinimum(1)
        self.background_radius_spinbox.setMaximum(500)
        self.background_radius_spinbox.setValue(RECOMMENDED_BACKGROUND_RADIUS)
        self.background_radius_spinbox.setSuffix(" px")
        self.background_radius_spinbox.setFixedWidth(54)
        self.background_radius_spinbox.setSizePolicy(
            QSizePolicy.Fixed,
            QSizePolicy.Fixed,
        )

        self.clear_background_button = QPushButton("Clear Background ROI")
        self.clear_background_button.setEnabled(False)
        self.clear_background_button.clicked.connect(self.clear_background_roi)

        self.clear_roi_button = QPushButton("Clear ROIs")
        self.clear_roi_button.setEnabled(False)
        self.clear_roi_button.clicked.connect(self.clear_rois)

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(16)
        self.play_timer.timeout.connect(self.advance_playback)

        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.setTracking(True)
        self.frame_slider.valueChanged.connect(self.set_frame_index)

        self.frame_spinbox = QSpinBox()
        self.frame_spinbox.setEnabled(False)
        self.frame_spinbox.setMinimum(0)
        self.frame_spinbox.valueChanged.connect(self.set_frame_index)

        self.image_view = pg.ImageView()
        self.image_view.ui.roiBtn.hide()
        self.image_view.ui.menuBtn.hide()
        self.hide_histogram_panel()

        self.overview_plot = self.create_trace_plot()
        self.overview_plot.setMinimumHeight(180)
        self.overview_plot.setMouseEnabled(x=False, y=False)
        self.overview_plot.getViewBox().disableAutoRange()

        self.detail_plot = self.create_trace_plot()
        self.detail_plot.setMinimumHeight(180)
        self.trace_plot = self.detail_plot

        self.transient_start_spinbox = self.create_time_spinbox()
        self.transient_end_spinbox = self.create_time_spinbox()
        self.sr_calcium_start_spinbox = self.create_time_spinbox()
        self.sr_calcium_end_spinbox = self.create_time_spinbox()
        self.detail_x_start_spinbox = self.create_detail_range_spinbox(" s")
        self.detail_x_end_spinbox = self.create_detail_range_spinbox(" s")
        self.detail_y_start_spinbox = self.create_detail_range_spinbox("")
        self.detail_y_end_spinbox = self.create_detail_range_spinbox("")
        self.transient_region = self.create_time_selection_region("#FF9F43")
        self.sr_calcium_region = self.create_time_selection_region("#4DB6FF")

        self.transient_calculate_button = QPushButton("Calculate transients")
        self.transient_calculate_button.setEnabled(False)
        self.transient_calculate_button.clicked.connect(self.calculate_transient_average)
        self.transient_smooth_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(TRANSIENT_DEFAULT_SMOOTH_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(2.0),
            step=10.0,
            suffix=" ms",
            decimals=0,
        )
        self.transient_prominence_noise_spinbox = self.create_analysis_spinbox(
            value=TRANSIENT_DEFAULT_PROMINENCE_NOISE,
            minimum=0.0,
            maximum=50.0,
            step=1.0,
            suffix=" x",
            decimals=0,
        )
        self.transient_min_prominence_spinbox = self.create_analysis_spinbox(
            value=0.0,
            minimum=0.0,
            maximum=1_000_000_000.0,
            step=1.0,
            suffix="",
            decimals=0,
        )
        self.transient_pacing_interval_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(TRANSIENT_DEFAULT_PACING_INTERVAL_S),
            minimum=self.seconds_to_ms(0.01),
            maximum=self.seconds_to_ms(60.0),
            step=50.0,
            suffix=" ms",
            decimals=0,
        )
        self.transient_pre_start_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(TRANSIENT_DEFAULT_PRE_START_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(10.0),
            step=10.0,
            suffix=" ms",
            decimals=0,
        )
        self.transient_start_fraction_spinbox = self.create_analysis_spinbox(
            value=TRANSIENT_DEFAULT_START_FRACTION,
            minimum=0.0,
            maximum=0.9,
            step=0.05,
            suffix="",
        )
        self.transient_decay_percent_spinboxes = tuple(
            self.create_decay_percent_spinbox(value)
            for value in TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES
        )
        self.sr_calcium_pre_start_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(SR_CALCIUM_DEFAULT_PRE_START_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(10.0),
            step=50.0,
            suffix=" ms",
            decimals=0,
        )
        self.sr_calcium_post_start_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(SR_CALCIUM_DEFAULT_POST_START_S),
            minimum=self.seconds_to_ms(0.01),
            maximum=self.seconds_to_ms(60.0),
            step=500.0,
            suffix=" ms",
            decimals=0,
        )
        self.sr_calcium_fit_start_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(SR_CALCIUM_DEFAULT_FIT_START_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(60.0),
            step=100.0,
            suffix=" ms",
            decimals=0,
        )
        self.sr_calcium_fit_end_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(SR_CALCIUM_DEFAULT_FIT_END_S),
            minimum=self.seconds_to_ms(0.01),
            maximum=self.seconds_to_ms(60.0),
            step=500.0,
            suffix=" ms",
            decimals=0,
        )
        self.bleach_pre_padding_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(PHOTOBLEACH_EVENT_PRE_PADDING_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(10.0),
            step=10.0,
            suffix=" ms",
            decimals=0,
        )
        self.bleach_post_padding_spinbox = self.create_analysis_spinbox(
            value=self.seconds_to_ms(PHOTOBLEACH_EVENT_POST_PADDING_S),
            minimum=0.0,
            maximum=self.seconds_to_ms(10.0),
            step=10.0,
            suffix=" ms",
            decimals=0,
        )
        self.bleach_min_baseline_spinbox = self.create_analysis_spinbox(
            value=PHOTOBLEACH_MIN_BASELINE_FRACTION * 100.0,
            minimum=1.0,
            maximum=100.0,
            step=1.0,
            suffix=" %",
            decimals=0,
        )
        self.bleach_robustness_spinbox = self.create_analysis_spinbox(
            value=PHOTOBLEACH_DEFAULT_ROBUSTNESS_SCALE,
            minimum=0.1,
            maximum=10.0,
            step=0.1,
            suffix=" x",
            decimals=1,
        )
        self.bleach_fit_start_spinbox = self.create_analysis_spinbox(
            value=PHOTOBLEACH_DEFAULT_FIT_START_S,
            minimum=0.0,
            maximum=600.0,
            step=0.001,
            suffix=" s",
            decimals=6,
        )
        self.bleach_fit_end_spinbox = self.create_analysis_spinbox(
            value=PHOTOBLEACH_DEFAULT_FIT_END_S,
            minimum=0.1,
            maximum=600.0,
            step=0.001,
            suffix=" s",
            decimals=6,
        )
        self.transient_baseline_checkbox = QCheckBox("F/F0")
        self.transient_baseline_checkbox.setChecked(True)
        self.transient_baseline_checkbox.setEnabled(False)
        self.configure_transient_parameter_help()
        self.connect_photobleaching_parameter_controls()

        self.transient_average_plot = self.create_trace_plot()
        self.transient_average_plot.setLabel(
            "bottom",
            "Time from transient start",
            units="s",
            color=GRAPH_FOREGROUND,
        )
        self.transient_average_plot.setLabel("left", "F/F0", color=GRAPH_FOREGROUND)
        self.transient_average_start_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(GRAPH_FOREGROUND, width=1, style=Qt.DashLine),
        )
        self.transient_average_start_line.setZValue(20)
        self.transient_average_plot.addItem(self.transient_average_start_line)
        self.transient_table = QTableWidget(0, 0)
        self.set_transient_table_headers(self.transient_table_decay_percents)
        self.transient_table.itemChanged.connect(self.update_transient_selection_from_table)
        self.saved_roi_table = QTableWidget(0, 0)
        self.set_saved_roi_table_headers()
        self.saved_roi_table.itemChanged.connect(self.update_saved_roi_visibility_from_table)
        self.saved_roi_table.currentCellChanged.connect(self.handle_saved_roi_row_selected)
        self.sr_calcium_event_plot = self.create_trace_plot()
        self.sr_calcium_event_plot.setLabel(
            "bottom",
            "Time",
            units="s",
            color=GRAPH_FOREGROUND,
        )
        self.sr_calcium_event_plot.setLabel("left", "F/F0", color=GRAPH_FOREGROUND)
        self.sr_calcium_fit_region = pg.LinearRegionItem(
            values=(0.0, 0.0),
            orientation="vertical",
            brush=pg.mkBrush("#FFD23F12"),
            movable=True,
        )
        self.sr_calcium_fit_region.setZValue(1)
        self.sr_calcium_fit_region.hide()
        self.sr_calcium_fit_region.sigRegionChangeFinished.connect(
            self.sync_sr_fit_region_to_parameters
        )
        self.sr_calcium_event_plot.addItem(self.sr_calcium_fit_region)
        self.sr_calcium_table = QTableWidget(0, 0)
        self.set_sr_calcium_table_headers(self.transient_table_decay_percents)

        self.overview_time_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(GRAPH_FOREGROUND, width=1, style=Qt.DashLine),
        )
        self.detail_time_line = pg.InfiniteLine(
            pos=0,
            angle=90,
            movable=False,
            pen=pg.mkPen(GRAPH_FOREGROUND, width=1, style=Qt.DashLine),
        )
        self.overview_time_line.setZValue(20)
        self.detail_time_line.setZValue(20)
        self.overview_plot.addItem(self.transient_region)
        self.overview_plot.addItem(self.overview_time_line)
        self.detail_plot.addItem(self.detail_time_line)
        self.current_time_line = self.overview_time_line
        self.connect_time_selection_controls()
        self.connect_detail_range_controls()

        self.setCentralWidget(self.image_view)
        self.build_control_dock()
        self.build_graph_dock()
        self.build_analysis_dock()
        self.resizeDocks([self.control_dock], [285], Qt.Horizontal)
        self.resizeDocks([self.graph_dock], [205], Qt.Vertical)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.close_reader()
        super().closeEvent(event)


def main() -> int:
    pg.setConfigOptions(imageAxisOrder="row-major")

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
