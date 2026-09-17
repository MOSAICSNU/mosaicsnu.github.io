"""Qt widget construction and synchronization helpers for MOSAIC."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from .constants import (
    GRAPH_BACKGROUND,
    GRAPH_FOREGROUND,
    GRAPH_GRID_ALPHA,
    MS_PER_SECOND,
    PHOTOBLEACH_DEFAULT_ROBUSTNESS_SCALE,
    PHOTOBLEACH_EVENT_POST_PADDING_S,
    PHOTOBLEACH_EVENT_PRE_PADDING_S,
    PHOTOBLEACH_MIN_BASELINE_FRACTION,
)


class InterfaceMixin:
    """Builds and synchronizes the MOSAIC Qt interface."""

    def build_control_dock(self) -> None:
        control_panel = QWidget()
        control_layout = QVBoxLayout()
        control_layout.setSpacing(12)
        control_layout.setContentsMargins(10, 10, 10, 10)

        file_group = QGroupBox("File")
        file_layout = QVBoxLayout()
        file_layout.addWidget(self.open_button)
        file_layout.addWidget(self.close_nd_button)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.save_results_button)
        file_layout.addWidget(self.load_info_button)
        file_group.setLayout(file_layout)

        playback_group = QGroupBox("Playback")
        playback_layout = QVBoxLayout()
        playback_layout.addWidget(self.play_button)
        playback_layout.addWidget(self.frame_label)
        playback_layout.addWidget(self.frame_slider)
        playback_layout.addWidget(self.frame_spinbox)
        playback_group.setLayout(playback_layout)

        background_group = QGroupBox("Background")
        background_layout = QVBoxLayout()
        recommend_background_row = QHBoxLayout()
        recommend_background_row.setSpacing(4)
        recommend_background_row.addWidget(self.recommend_background_button, 1)
        radius_label = QLabel("R")
        radius_label.setFixedWidth(12)
        recommend_background_row.addWidget(radius_label)
        recommend_background_row.addWidget(self.background_radius_spinbox, 0)
        background_layout.addWidget(self.background_button)
        background_layout.addLayout(recommend_background_row)
        background_layout.addWidget(self.clear_background_button)
        background_group.setLayout(background_layout)

        roi_group = QGroupBox("ROI")
        roi_layout = QVBoxLayout()
        roi_layout.addWidget(self.build_parameter_pair("Shape", self.roi_shape_combo))
        roi_layout.addWidget(self.add_roi_button)
        roi_layout.addWidget(self.auto_roi_button)
        roi_layout.addWidget(self.calculate_button)
        roi_layout.addWidget(self.save_roi_button)
        roi_layout.addWidget(self.clear_roi_button)
        roi_group.setLayout(roi_layout)

        photobleaching_group = QGroupBox("Photobleaching")
        photobleaching_group.setLayout(self.build_photobleaching_layout())

        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        self.info_label.setWordWrap(True)
        status_layout.addWidget(self.info_label)
        status_group.setLayout(status_layout)

        control_layout.addWidget(file_group)
        control_layout.addWidget(playback_group)
        control_layout.addWidget(background_group)
        control_layout.addWidget(roi_group)
        control_layout.addWidget(photobleaching_group)
        control_layout.addWidget(status_group)
        control_layout.addStretch(1)
        control_panel.setLayout(control_layout)
        self.allow_panel_to_shrink(control_panel)
        # The generic compact-panel policy intentionally lets most widgets
        # shrink.  Keep the ROI shape selector wide enough to show both its
        # text and arrow instead of clipping it at a narrow dock width.
        self.roi_shape_combo.setMinimumWidth(118)
        self.roi_shape_combo.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed,
        )

        self.control_dock = QDockWidget("Controls", self)
        self.control_dock.setMinimumWidth(220)
        self.control_dock.setWidget(
            self.create_scroll_area(control_panel, horizontal_scroll=False)
        )
        self.control_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.control_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.control_dock)

    def build_photobleaching_layout(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.addWidget(self.correct_bleaching_button)
        layout.addWidget(self.confirm_bleaching_button)
        layout.addWidget(self.reset_bleaching_button)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(
            self.build_parameter_pair("Pre", self.bleach_pre_padding_spinbox),
            1,
        )
        row.addWidget(
            self.build_parameter_pair("Post", self.bleach_post_padding_spinbox),
            1,
        )
        layout.addLayout(row)

        layout.addWidget(
            self.build_parameter_pair("Base", self.bleach_min_baseline_spinbox)
        )

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(
            self.build_parameter_pair("Fit S", self.bleach_fit_start_spinbox),
            1,
        )
        row.addWidget(
            self.build_parameter_pair("Fit E", self.bleach_fit_end_spinbox),
            1,
        )
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(
            self.build_parameter_pair("Robust", self.bleach_robustness_spinbox),
            1,
        )
        layout.addLayout(row)
        return layout

    def create_scroll_area(
        self,
        widget: QWidget,
        horizontal_scroll: bool = True,
    ) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setWidget(widget)
        scroll_area.setWidgetResizable(True)
        horizontal_policy = Qt.ScrollBarAsNeeded if horizontal_scroll else Qt.ScrollBarAlwaysOff
        scroll_area.setHorizontalScrollBarPolicy(horizontal_policy)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setMinimumWidth(0)
        return scroll_area

    def allow_panel_to_shrink(self, panel: QWidget) -> None:
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for widget in panel.findChildren(QWidget):
            if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                continue
            widget.setMinimumWidth(0)
            current_policy = widget.sizePolicy()
            widget.setSizePolicy(QSizePolicy.Ignored, current_policy.verticalPolicy())

    def create_trace_plot(self) -> pg.PlotWidget:
        plot = pg.PlotWidget(background=GRAPH_BACKGROUND)
        plot.showGrid(x=True, y=True, alpha=GRAPH_GRID_ALPHA)
        plot.setLabel("bottom", "Time", units="s", color=GRAPH_FOREGROUND)
        plot.setLabel("left", "Intensity", color=GRAPH_FOREGROUND)
        axis_pen = pg.mkPen(GRAPH_FOREGROUND, width=1)
        for axis_name in ("bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(axis_pen)
            axis.setTextPen(axis_pen)
        return plot

    def create_time_spinbox(self) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setEnabled(False)
        spinbox.setDecimals(6)
        spinbox.setRange(0.0, 0.0)
        spinbox.setSingleStep(0.001)
        spinbox.setSuffix(" s")
        spinbox.setKeyboardTracking(False)
        spinbox.setFixedWidth(96)
        return spinbox

    def create_detail_range_spinbox(self, suffix: str) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setEnabled(False)
        spinbox.setDecimals(6)
        spinbox.setRange(-1_000_000_000.0, 1_000_000_000.0)
        spinbox.setSingleStep(0.001)
        spinbox.setSuffix(suffix)
        spinbox.setKeyboardTracking(False)
        spinbox.setFixedWidth(96)
        return spinbox

    def create_analysis_spinbox(
        self,
        value: float,
        minimum: float,
        maximum: float,
        step: float,
        suffix: str,
        decimals: int = 4,
    ) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setEnabled(False)
        spinbox.setDecimals(decimals)
        spinbox.setRange(minimum, maximum)
        spinbox.setSingleStep(step)
        spinbox.setValue(value)
        spinbox.setSuffix(suffix)
        spinbox.setKeyboardTracking(False)
        spinbox.setFixedWidth(96)
        return spinbox

    def create_decay_percent_spinbox(self, value: int) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setEnabled(False)
        spinbox.setRange(1, 99)
        spinbox.setSingleStep(1)
        spinbox.setValue(value)
        spinbox.setSuffix(" %")
        spinbox.setKeyboardTracking(False)
        spinbox.setFixedWidth(76)
        return spinbox

    def seconds_to_ms(self, value_s: float) -> float:
        return value_s * MS_PER_SECOND

    def ms_to_seconds(self, value_ms: float) -> float:
        return value_ms / MS_PER_SECOND

    def transient_smooth_s(self) -> float:
        return self.ms_to_seconds(self.transient_smooth_spinbox.value())

    def transient_pacing_interval_s(self) -> float:
        return self.ms_to_seconds(self.transient_pacing_interval_spinbox.value())

    def transient_pre_start_s(self) -> float:
        return self.ms_to_seconds(self.transient_pre_start_spinbox.value())

    def sr_calcium_pre_start_s(self) -> float:
        return self.ms_to_seconds(self.sr_calcium_pre_start_spinbox.value())

    def sr_calcium_post_start_s(self) -> float:
        return self.ms_to_seconds(self.sr_calcium_post_start_spinbox.value())

    def sr_calcium_fit_start_s(self) -> float:
        return self.ms_to_seconds(self.sr_calcium_fit_start_spinbox.value())

    def sr_calcium_fit_end_s(self) -> float:
        return self.ms_to_seconds(self.sr_calcium_fit_end_spinbox.value())

    def bleach_pre_padding_s(self) -> float:
        return self.ms_to_seconds(self.bleach_pre_padding_spinbox.value())

    def bleach_post_padding_s(self) -> float:
        return self.ms_to_seconds(self.bleach_post_padding_spinbox.value())

    def bleach_min_baseline_fraction(self) -> float:
        return self.bleach_min_baseline_spinbox.value() / 100.0

    def bleach_robustness_scale(self) -> float:
        return self.bleach_robustness_spinbox.value()

    def bleach_fit_window_s(self) -> tuple[float, float]:
        start_s = float(self.bleach_fit_start_spinbox.value())
        end_s = float(self.bleach_fit_end_spinbox.value())
        return tuple(sorted((start_s, end_s)))

    def valid_f0(self, value: object) -> float:
        try:
            f0 = float(value)
        except (TypeError, ValueError):
            return float("nan")
        if not np.isfinite(f0) or f0 <= 0:
            return float("nan")
        return f0

    def normalize_trace_to_f_over_f0(
        self,
        trace: np.ndarray,
        f0: object,
    ) -> np.ndarray | None:
        f0_value = self.valid_f0(f0)
        if not np.isfinite(f0_value):
            return None
        return trace.astype(float, copy=True) / f0_value

    def transient_f0_from_snippet(
        self,
        common_time: np.ndarray,
        snippet: np.ndarray,
        fallback_f0: object,
    ) -> float:
        baseline_values = snippet[(common_time < 0) & np.isfinite(snippet)]
        if baseline_values.size:
            f0 = float(np.mean(baseline_values))
        else:
            f0 = self.valid_f0(fallback_f0)
        return self.valid_f0(f0)

    def event_f0_from_pre_start(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        start_time_s: float,
        fallback_f0: object,
    ) -> float:
        baseline_values = trace[(time_s < start_time_s) & np.isfinite(trace)]
        if baseline_values.size:
            f0 = float(np.mean(baseline_values))
        else:
            f0 = self.valid_f0(fallback_f0)
        return self.valid_f0(f0)

    def transient_decay_percent_values(self) -> list[int]:
        return [spinbox.value() for spinbox in self.transient_decay_percent_spinboxes]

    def set_transient_table_headers(self, decay_percents: list[int]) -> None:
        self.transient_table.setColumnCount(1 + len(self.event_metric_headers(decay_percents)))
        self.transient_table.setHorizontalHeaderLabels(
            ["Use", *self.event_metric_headers(decay_percents)]
        )

    def set_sr_calcium_table_headers(self, decay_percents: list[int]) -> None:
        headers = [
            "Event",
            "Ab_start",
            "Ab_peak",
            "Peak time ms",
            "Amp dF/F0",
            "Amp ratio",
            "Max d(F/F0)/dt",
            "Tau ms",
            "Offset C",
            "Fit R2",
            "Fit RMSE",
        ]
        self.sr_calcium_table.setColumnCount(len(headers))
        self.sr_calcium_table.setHorizontalHeaderLabels(
            headers
        )

    def set_saved_roi_table_headers(self) -> None:
        headers = [
            "Use",
            "ROI",
            "Tran N",
            "Tran Amp dF/F0",
            "Tran Peak ms",
            "Tran Max d(F/F0)/dt",
        ]
        headers.extend(
            f"Tran Decay {percent}% ms" for percent in self.saved_decay_percents
        )
        self.saved_roi_table.setColumnCount(len(headers))
        self.saved_roi_table.setHorizontalHeaderLabels(headers)

    def saved_roi_headers_without_use(self) -> list[str]:
        return [
            self.saved_roi_table.horizontalHeaderItem(column).text()
            for column in range(1, self.saved_roi_table.columnCount())
        ]

    def event_metric_headers(self, decay_percents: list[int]) -> list[str]:
        headers = [
            "Event",
            "Ab_start",
            "Ab_peak",
            "Peak time ms",
            "Amp dF/F0",
            "Max d(F/F0)/dt",
        ]
        headers.extend([f"Ab_decay {percent}%" for percent in decay_percents])
        headers.extend([f"Decay time {percent}% ms" for percent in decay_percents])
        return headers

    def create_time_selection_region(self, color: str) -> pg.LinearRegionItem:
        region = pg.LinearRegionItem(
            values=(0.0, 0.0),
            orientation="vertical",
            brush=pg.mkBrush(color + "44"),
            movable=True,
        )
        region.setZValue(10)
        region.setBounds((0.0, 0.0))
        return region

    def build_graph_dock(self) -> None:
        graph_panel = QWidget()
        graph_layout = QVBoxLayout()
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(4)
        graph_splitter = QSplitter(Qt.Vertical)
        graph_splitter.setChildrenCollapsible(False)
        graph_splitter.addWidget(
            self.build_graph_row(self.build_time_selection_panel(), self.overview_plot)
        )
        graph_splitter.addWidget(
            self.build_graph_row(self.build_detail_range_panel(), self.detail_plot)
        )
        graph_splitter.setSizes([220, 220])
        graph_layout.addWidget(graph_splitter, 1)
        graph_panel.setLayout(graph_layout)

        self.graph_dock = QDockWidget("Graph analysis", self)
        self.graph_dock.setWidget(graph_panel)
        self.graph_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.graph_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self.graph_dock)

    def build_analysis_dock(self) -> None:
        analysis_panel = self.build_transient_analysis_panel()

        self.analysis_dock = QDockWidget("Transient analysis", self)
        self.analysis_dock.setWidget(self.create_scroll_area(analysis_panel))
        self.analysis_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.analysis_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.analysis_dock)

    def build_saved_roi_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel("Saved ROI")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(self.saved_roi_table, 1)
        panel.setLayout(layout)
        panel.setMinimumWidth(260)
        self.configure_event_table(self.saved_roi_table, minimum_height=320)
        self.saved_roi_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.saved_roi_table.setSelectionMode(QAbstractItemView.SingleSelection)
        return panel

    def build_transient_analysis_panel(self) -> QWidget:
        analysis_panel = QWidget()
        analysis_layout = QVBoxLayout()
        analysis_layout.setContentsMargins(0, 0, 0, 0)
        analysis_layout.setSpacing(6)
        analysis_splitter = QSplitter(Qt.Vertical)
        analysis_splitter.setChildrenCollapsible(False)
        analysis_splitter.addWidget(self.build_transient_parameter_panel())
        analysis_splitter.addWidget(self.transient_average_plot)
        analysis_splitter.addWidget(self.transient_table)
        analysis_splitter.addWidget(self.build_saved_roi_panel())
        analysis_splitter.setStretchFactor(0, 0)
        analysis_splitter.setStretchFactor(1, 1)
        analysis_splitter.setStretchFactor(2, 0)
        analysis_splitter.setStretchFactor(3, 1)
        analysis_splitter.setSizes([78, 220, 200, 320])
        analysis_layout.addWidget(analysis_splitter, 1)
        analysis_panel.setLayout(analysis_layout)

        self.transient_average_plot.setMinimumHeight(140)
        self.configure_event_table(self.transient_table, minimum_height=82)
        return analysis_panel

    def configure_event_table(self, table: QTableWidget, minimum_height: int) -> None:
        table.setMinimumHeight(minimum_height)
        table.setWordWrap(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)

    def build_parameter_pair(self, label: str, widget: QWidget) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label_widget = QLabel(label)
        label_widget.setMinimumWidth(0)
        label_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(label_widget, 1)
        layout.addWidget(widget, 0)
        panel.setLayout(layout)
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return panel

    def build_transient_parameter_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        calculate_row = QHBoxLayout()
        calculate_row.setContentsMargins(0, 0, 0, 0)
        calculate_row.setSpacing(6)
        self.transient_calculate_button.setSizePolicy(
            QSizePolicy.Expanding,
            self.transient_calculate_button.sizePolicy().verticalPolicy(),
        )
        calculate_row.addWidget(self.transient_calculate_button, 1)
        layout.addLayout(calculate_row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(
            self.build_parameter_pair("Peak cutoff", self.transient_prominence_noise_spinbox),
            1,
        )
        row.addWidget(
            self.build_parameter_pair(
                "Pacing interval", self.transient_pacing_interval_spinbox
            ),
            1,
        )
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(
            self.build_parameter_pair("Before start", self.transient_pre_start_spinbox),
            1,
        )
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.build_parameter_pair("Decay 1", self.transient_decay_percent_spinboxes[0]), 1)
        row.addWidget(self.build_parameter_pair("Decay 2", self.transient_decay_percent_spinboxes[1]), 1)
        row.addWidget(self.build_parameter_pair("Decay 3", self.transient_decay_percent_spinboxes[2]), 1)
        layout.addLayout(row)
        panel.setLayout(layout)
        return panel

    def configure_transient_parameter_help(self) -> None:
        self.transient_smooth_spinbox.setToolTip(
            "Smooth the trace over this time window before finding peaks."
        )
        self.transient_prominence_noise_spinbox.setToolTip(
            "A peak must be this many times larger than baseline noise. "
            "Lower values detect smaller peaks."
        )
        self.transient_min_prominence_spinbox.setToolTip(
            "Optional absolute peak cutoff. Leave at 0 for noise-based detection."
        )
        self.transient_pacing_interval_spinbox.setToolTip(
            "Fixed recovery-analysis window after each detected transient peak. "
            "Only complete transients within this pacing interval are used."
        )
        self.transient_pre_start_spinbox.setToolTip(
            "How much trace to show before the detected transient start."
        )
        self.transient_start_fraction_spinbox.setToolTip(
            "The start is where the rise reaches this fraction of peak amplitude."
        )
        self.transient_baseline_checkbox.setToolTip(
            "Event traces are displayed as F/F0 using each pre-start baseline."
        )
        for spinbox in self.transient_decay_percent_spinboxes:
            spinbox.setToolTip(
                "Report the time after peak until the trace has fallen by this "
                "percent of the peak amplitude. Press Calculate after changing it."
            )
        self.sr_calcium_pre_start_spinbox.setToolTip(
            "How much Caff. trace to show before the detected event start."
        )
        self.sr_calcium_post_start_spinbox.setToolTip(
            "How much Caff. trace to show after the detected event start."
        )
        self.sr_calcium_fit_start_spinbox.setToolTip(
            "Start of the Caff. exponential fitting window, measured after peak."
        )
        self.sr_calcium_fit_end_spinbox.setToolTip(
            "End of the Caff. exponential fitting window, measured after peak."
        )
        self.bleach_pre_padding_spinbox.setToolTip(
            "Exclude this much time before each detected transient start."
        )
        self.bleach_post_padding_spinbox.setToolTip(
            "Exclude this much time after each detected transient recovery."
        )
        self.bleach_min_baseline_spinbox.setToolTip(
            "Minimum percent of time points that must remain for baseline fitting."
        )
        self.bleach_robustness_spinbox.setToolTip(
            "Lower values reduce outlier influence more strongly; higher values follow points more closely."
        )
        self.bleach_fit_start_spinbox.setToolTip(
            "Start time, from the movie start, used for photobleaching baseline fitting."
        )
        self.bleach_fit_end_spinbox.setToolTip(
            "End time, from the movie start, used for photobleaching baseline fitting."
        )

    def connect_photobleaching_parameter_controls(self) -> None:
        for widget in (
            self.bleach_pre_padding_spinbox,
            self.bleach_post_padding_spinbox,
            self.bleach_min_baseline_spinbox,
            self.bleach_robustness_spinbox,
        ):
            widget.valueChanged.connect(self.handle_photobleaching_parameter_change)
        for widget in (
            self.bleach_fit_start_spinbox,
            self.bleach_fit_end_spinbox,
        ):
            widget.valueChanged.connect(self.handle_photobleaching_fit_window_change)

    def handle_photobleaching_parameter_change(self, *_args: object) -> None:
        if self.photobleaching_parameter_updating:
            return
        if self.photobleaching_preview_traces:
            self.calculate_photobleaching_preview()

    def handle_photobleaching_fit_window_change(self, *_args: object) -> None:
        if not self.photobleaching_parameter_updating:
            self.photobleaching_fit_window_custom = True
        self.handle_photobleaching_parameter_change()

    def reset_photobleaching_parameters(self) -> None:
        self.photobleaching_parameter_updating = True
        try:
            self.bleach_pre_padding_spinbox.setValue(
                self.seconds_to_ms(PHOTOBLEACH_EVENT_PRE_PADDING_S)
            )
            self.bleach_post_padding_spinbox.setValue(
                self.seconds_to_ms(PHOTOBLEACH_EVENT_POST_PADDING_S)
            )
            self.bleach_min_baseline_spinbox.setValue(
                PHOTOBLEACH_MIN_BASELINE_FRACTION * 100.0
            )
            self.bleach_robustness_spinbox.setValue(
                PHOTOBLEACH_DEFAULT_ROBUSTNESS_SCALE
            )
            self.photobleaching_fit_window_custom = False
            self.set_photobleaching_fit_window_to_transient_region()
        finally:
            self.photobleaching_parameter_updating = False

    def build_graph_row(self, control_panel: QWidget, plot: pg.PlotWidget) -> QWidget:
        row = QSplitter(Qt.Horizontal)
        row.setChildrenCollapsible(False)
        row.addWidget(control_panel)
        row.addWidget(plot)
        row.setStretchFactor(0, 0)
        row.setStretchFactor(1, 1)
        row.setSizes([270, 900])
        return row

    def build_time_selection_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(230)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QGridLayout()
        layout.setContentsMargins(14, 10, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        layout.addWidget(QLabel("Ranges"), 0, 0, 1, 3)
        layout.addWidget(QLabel("Start"), 1, 1)
        layout.addWidget(QLabel("End"), 1, 2)
        layout.addWidget(QLabel("Tran."), 2, 0)
        layout.addWidget(self.transient_start_spinbox, 2, 1)
        layout.addWidget(self.transient_end_spinbox, 2, 2)
        panel.setLayout(layout)
        return panel

    def build_detail_range_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(230)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        layout = QGridLayout()
        layout.setContentsMargins(14, 10, 8, 8)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)
        layout.addWidget(QLabel("Detail view"), 0, 0, 1, 3)
        layout.addWidget(QLabel("Start"), 1, 1)
        layout.addWidget(QLabel("End"), 1, 2)
        layout.addWidget(QLabel("X"), 2, 0)
        layout.addWidget(self.detail_x_start_spinbox, 2, 1)
        layout.addWidget(self.detail_x_end_spinbox, 2, 2)
        layout.addWidget(QLabel("Y"), 3, 0)
        layout.addWidget(self.detail_y_start_spinbox, 3, 1)
        layout.addWidget(self.detail_y_end_spinbox, 3, 2)
        panel.setLayout(layout)
        return panel

    def connect_time_selection_controls(self) -> None:
        self.connect_time_selection(
            self.transient_region,
            self.transient_start_spinbox,
            self.transient_end_spinbox,
        )

    def connect_time_selection(
        self,
        region: pg.LinearRegionItem,
        start_spinbox: QDoubleSpinBox,
        end_spinbox: QDoubleSpinBox,
    ) -> None:
        region.sigRegionChangeFinished.connect(
            lambda *_args: self.sync_region_to_time_spinboxes(
                region,
                start_spinbox,
                end_spinbox,
            )
        )
        start_spinbox.valueChanged.connect(
            lambda _value: self.sync_time_spinboxes_to_region(
                region,
                start_spinbox,
                end_spinbox,
            )
        )
        end_spinbox.valueChanged.connect(
            lambda _value: self.sync_time_spinboxes_to_region(
                region,
                start_spinbox,
                end_spinbox,
            )
        )

    def connect_detail_range_controls(self) -> None:
        self.detail_plot.getViewBox().sigRangeChanged.connect(
            lambda *_args: self.sync_detail_plot_to_range_spinboxes()
        )
        for spinbox in self.detail_range_spinboxes():
            spinbox.valueChanged.connect(
                lambda _value: self.sync_range_spinboxes_to_detail_plot()
            )

    def detail_range_spinboxes(self) -> tuple[QDoubleSpinBox, ...]:
        return (
            self.detail_x_start_spinbox,
            self.detail_x_end_spinbox,
            self.detail_y_start_spinbox,
            self.detail_y_end_spinbox,
        )

    def transient_parameter_widgets(self) -> tuple[QDoubleSpinBox | QCheckBox, ...]:
        return (
            self.transient_smooth_spinbox,
            self.transient_prominence_noise_spinbox,
            self.transient_min_prominence_spinbox,
            self.transient_pacing_interval_spinbox,
            self.transient_pre_start_spinbox,
            self.transient_start_fraction_spinbox,
            *self.transient_decay_percent_spinboxes,
        )

    def sr_calcium_parameter_widgets(self) -> tuple[QDoubleSpinBox, ...]:
        return (
            self.sr_calcium_pre_start_spinbox,
            self.sr_calcium_post_start_spinbox,
            self.sr_calcium_fit_start_spinbox,
            self.sr_calcium_fit_end_spinbox,
        )

    def photobleaching_parameter_widgets(
        self,
    ) -> tuple[QDoubleSpinBox, ...]:
        return (
            self.bleach_pre_padding_spinbox,
            self.bleach_post_padding_spinbox,
            self.bleach_min_baseline_spinbox,
            self.bleach_robustness_spinbox,
            self.bleach_fit_start_spinbox,
            self.bleach_fit_end_spinbox,
        )
