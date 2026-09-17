"""ND2 loading, playback, ROI tools, and intensity-trace extraction."""

from __future__ import annotations

from bisect import bisect_left
import time
from pathlib import Path

import nd2
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QMessageBox,
)
from .constants import (
    AUTO_ROI_CHANGE_PERCENTILE,
    AUTO_ROI_DURATION_S,
    AUTO_ROI_MAX_FRAMES,
    AUTO_ROI_MIN_PIXELS,
    BACKGROUND_RECOMMEND_CANDIDATES,
    BACKGROUND_RECOMMEND_DURATION_S,
    BACKGROUND_ROI_SIZE,
    DISPLAY_LEVELS,
    PROJECT_ROOT,
    ROI_COLORS,
    ROI_SIZE,
)


class MovieRoiMixin:
    """Handles ND2 movies, playback, image ROIs, and trace extraction."""

    def open_file_dialog(self) -> None:
        initial_directory = (
            self.last_open_directory
            if self.last_open_directory.is_dir()
            else PROJECT_ROOT
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open ND2 file",
            str(initial_directory),
            "ND2 files (*.nd2);;All files (*)",
        )
        if path:
            self.load_nd2(Path(path))

    def close_nd2_with_confirmation(self) -> None:
        if self.reader is None and self.current_path is None:
            return

        response = QMessageBox.question(
            self,
            "Close current ND2 file?",
            "Close the current ND2 file and clear all ROI analysis from the workspace?",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if response != QMessageBox.StandardButton.Ok:
            return

        self.close_loaded_nd2()

    def close_loaded_nd2(self) -> None:
        self.clear_rois()
        self.clear_background_roi()
        self.clear_saved_roi_entries()
        self.clear_trace_curves()
        self.clear_all_analysis()
        self.close_reader()

        self.current_path = None
        self.roi_raw_traces = {}
        self.roi_traces = {}
        self.roi_names = {}
        self.roi_pens = {}
        self.auto_roi_originals = {}
        self.roi_counter = 0
        self.current_saved_roi_row = None
        self.photobleaching_corrected = False
        self.detail_plot_has_data = False
        self.file_label.setText("No file loaded")
        self.frame_label.setText("Frame: -")
        self.info_label.setText("No ND2 file loaded.")
        self.overview_time_line.setPos(0)
        self.detail_time_line.setPos(0)
        self.image_view.clear()
        self.hide_histogram_panel()
        self.update_auto_roi_button_text()
        self.update_photobleaching_controls_enabled()
        self.update_saved_roi_controls_enabled()

    def load_nd2(self, path: Path) -> None:
        path = path.expanduser()
        if path.parent.is_dir():
            self.last_open_directory = path.parent
        self.close_reader()
        self.clear_rois()
        self.clear_background_roi()
        self.clear_saved_roi_entries()
        self.current_path = path

        try:
            self.reader = nd2.ND2File(path)
            sizes = dict(self.reader.sizes)
            self.frame_count = int(sizes.get("T", 1))
            self.frame_times_s = self.read_frame_times()
            self.build_time_index()
            self.build_graph_time_axis()
            self.configure_time_selection_controls()
            self.configure_detail_range_controls()
            self.current_frame_index = -1

            self.frame_slider.blockSignals(True)
            self.frame_spinbox.blockSignals(True)
            self.frame_slider.setMinimum(0)
            self.frame_slider.setMaximum(max(self.frame_count - 1, 0))
            self.frame_slider.setValue(0)
            self.frame_spinbox.setMinimum(0)
            self.frame_spinbox.setMaximum(max(self.frame_count - 1, 0))
            self.frame_spinbox.setValue(0)
            self.frame_slider.blockSignals(False)
            self.frame_spinbox.blockSignals(False)
            self.set_frame_controls_enabled(True)

            dtype = self.reader.dtype

            self.file_label.setText(f"Loaded: {path}")
            self.info_label.setText(
                f"Loaded ND2 | dtype={dtype} | sizes={sizes} | "
                "slider preview enabled | playback uses recorded timestamps"
            )
            self.update_trace_x_range()
            self.display_frame(0)
        except Exception as exc:
            self.close_reader()
            self.file_label.setText(f"Failed to load: {path}")
            self.info_label.setText(f"Error: {exc}")

    def read_frame_times(self) -> list[float | None]:
        if self.reader is None:
            return []

        times: list[float | None] = [None] * self.frame_count
        try:
            events = self.reader.events()
        except Exception:
            return times

        for event in events:
            try:
                frame_index = int(event["T Index"])
                times[frame_index] = float(event["Time [s]"])
            except (KeyError, TypeError, ValueError):
                continue

        return times

    def build_time_index(self) -> None:
        self.valid_time_values_s = []
        self.valid_time_frame_indices = []

        for frame_index, time_s in enumerate(self.frame_times_s):
            if time_s is None:
                continue
            self.valid_time_values_s.append(time_s)
            self.valid_time_frame_indices.append(frame_index)

    def build_graph_time_axis(self) -> None:
        if self.frame_count <= 0:
            self.graph_time_s = np.array([], dtype=float)
            return

        start_time = self.time_for_frame(0)
        self.graph_time_s = np.array(
            [self.time_for_frame(i) - start_time for i in range(self.frame_count)],
            dtype=float,
        )

    def configure_time_selection_controls(self) -> None:
        if self.graph_time_s.size == 0:
            self.reset_time_selection_controls()
            return

        time_min = float(self.graph_time_s[0])
        time_max = float(self.graph_time_s[-1])
        duration = max(time_max - time_min, 0.0)
        step = max(duration / 1000.0, 0.001)

        for spinbox in self.time_selection_spinboxes():
            spinbox.blockSignals(True)
            spinbox.setRange(time_min, time_max)
            spinbox.setSingleStep(step)
            spinbox.blockSignals(False)

        for region in (self.transient_region, self.sr_calcium_region):
            region.setBounds((time_min, time_max))

        if duration <= 0:
            transient_interval = (time_min, time_max)
            sr_calcium_interval = (time_min, time_max)
        else:
            transient_interval = (time_min, time_min + duration * 0.25)
            sr_calcium_interval = (
                time_min + duration * 0.5,
                time_min + duration * 0.75,
            )

        self.set_time_selection_interval(
            self.transient_region,
            self.transient_start_spinbox,
            self.transient_end_spinbox,
            transient_interval,
        )
        self.set_time_selection_interval(
            self.sr_calcium_region,
            self.sr_calcium_start_spinbox,
            self.sr_calcium_end_spinbox,
            sr_calcium_interval,
        )
        self.photobleaching_fit_window_custom = False
        self.configure_photobleaching_fit_window_range(time_min, time_max, step)
        self.set_photobleaching_fit_window_to_transient_region()

    def reset_time_selection_controls(self) -> None:
        for spinbox in self.time_selection_spinboxes():
            spinbox.blockSignals(True)
            spinbox.setRange(0.0, 0.0)
            spinbox.setValue(0.0)
            spinbox.blockSignals(False)

        for region in (self.transient_region, self.sr_calcium_region):
            region.setBounds((0.0, 0.0))
            region.setRegion((0.0, 0.0))
        self.photobleaching_fit_window_custom = False

    def configure_detail_range_controls(self) -> None:
        if self.graph_time_s.size == 0:
            self.reset_detail_range_controls()
            return

        time_min = float(self.graph_time_s[0])
        time_max = float(self.graph_time_s[-1])
        duration = max(time_max - time_min, 0.0)
        step = max(duration / 1000.0, 0.001)
        for spinbox in (self.detail_x_start_spinbox, self.detail_x_end_spinbox):
            spinbox.blockSignals(True)
            spinbox.setRange(time_min, time_max)
            spinbox.setSingleStep(step)
            spinbox.blockSignals(False)

        self.update_detail_range_spinboxes()

    def reset_detail_range_controls(self) -> None:
        for spinbox in self.detail_range_spinboxes():
            spinbox.blockSignals(True)
            spinbox.setValue(0.0)
            spinbox.blockSignals(False)

    def sync_detail_plot_to_range_spinboxes(self) -> None:
        if self.detail_range_syncing:
            return
        self.update_detail_range_spinboxes()

    def update_detail_range_spinboxes(self) -> None:
        x_range, y_range = self.detail_plot.viewRange()
        self.detail_range_syncing = True
        try:
            self.detail_x_start_spinbox.setValue(float(x_range[0]))
            self.detail_x_end_spinbox.setValue(float(x_range[1]))
            self.detail_y_start_spinbox.setValue(float(y_range[0]))
            self.detail_y_end_spinbox.setValue(float(y_range[1]))
        finally:
            self.detail_range_syncing = False

    def sync_range_spinboxes_to_detail_plot(self) -> None:
        if self.detail_range_syncing:
            return

        x_start, x_end = sorted(
            (self.detail_x_start_spinbox.value(), self.detail_x_end_spinbox.value())
        )
        y_start, y_end = sorted(
            (self.detail_y_start_spinbox.value(), self.detail_y_end_spinbox.value())
        )
        if x_start == x_end or y_start == y_end:
            return

        self.detail_range_syncing = True
        try:
            self.detail_x_start_spinbox.setValue(x_start)
            self.detail_x_end_spinbox.setValue(x_end)
            self.detail_y_start_spinbox.setValue(y_start)
            self.detail_y_end_spinbox.setValue(y_end)
            self.detail_plot.setRange(
                xRange=(x_start, x_end),
                yRange=(y_start, y_end),
                padding=0,
            )
        finally:
            self.detail_range_syncing = False

    def time_selection_spinboxes(self) -> tuple[QDoubleSpinBox, ...]:
        return (
            self.transient_start_spinbox,
            self.transient_end_spinbox,
        )

    def set_time_selection_interval(
        self,
        region: pg.LinearRegionItem,
        start_spinbox: QDoubleSpinBox,
        end_spinbox: QDoubleSpinBox,
        interval: tuple[float, float],
    ) -> None:
        start, end = sorted(interval)
        self.selection_syncing = True
        try:
            start_spinbox.setValue(start)
            end_spinbox.setValue(end)
            region.setRegion((start, end))
        finally:
            self.selection_syncing = False

    def configure_photobleaching_fit_window_range(
        self,
        time_min: float,
        time_max: float,
        step: float,
    ) -> None:
        self.photobleaching_parameter_updating = True
        try:
            for spinbox in (
                self.bleach_fit_start_spinbox,
                self.bleach_fit_end_spinbox,
            ):
                spinbox.blockSignals(True)
                spinbox.setRange(time_min, time_max)
                spinbox.setSingleStep(step)
                spinbox.blockSignals(False)
        finally:
            self.photobleaching_parameter_updating = False

    def set_photobleaching_fit_window_to_transient_region(self) -> None:
        start, end = sorted(float(value) for value in self.transient_region.getRegion())
        self.photobleaching_parameter_updating = True
        try:
            self.bleach_fit_start_spinbox.setValue(start)
            self.bleach_fit_end_spinbox.setValue(end)
        finally:
            self.photobleaching_parameter_updating = False

    def sync_default_photobleaching_fit_window_to_transient(self) -> None:
        if self.photobleaching_fit_window_custom:
            return

        self.set_photobleaching_fit_window_to_transient_region()
        if self.photobleaching_preview_traces:
            self.calculate_photobleaching_preview()

    def sync_region_to_time_spinboxes(
        self,
        region: pg.LinearRegionItem,
        start_spinbox: QDoubleSpinBox,
        end_spinbox: QDoubleSpinBox,
    ) -> None:
        if self.selection_syncing:
            return

        start, end = sorted(float(value) for value in region.getRegion())
        self.selection_syncing = True
        try:
            start_spinbox.setValue(start)
            end_spinbox.setValue(end)
        finally:
            self.selection_syncing = False
        if region is self.transient_region:
            self.sync_default_photobleaching_fit_window_to_transient()

    def sync_time_spinboxes_to_region(
        self,
        region: pg.LinearRegionItem,
        start_spinbox: QDoubleSpinBox,
        end_spinbox: QDoubleSpinBox,
    ) -> None:
        if self.selection_syncing:
            return

        start, end = sorted((start_spinbox.value(), end_spinbox.value()))
        self.selection_syncing = True
        try:
            start_spinbox.setValue(start)
            end_spinbox.setValue(end)
            region.setRegion((start, end))
        finally:
            self.selection_syncing = False
        if region is self.transient_region:
            self.sync_default_photobleaching_fit_window_to_transient()

    def update_trace_x_range(self) -> None:
        if self.graph_time_s.size == 0:
            return

        self.overview_plot.setXRange(
            float(self.graph_time_s[0]),
            float(self.graph_time_s[-1]),
            padding=0,
        )
        if not self.detail_plot_has_data:
            self.detail_plot.setXRange(
                float(self.graph_time_s[0]),
                float(self.graph_time_s[-1]),
                padding=0,
            )

    def apply_overview_plot_range(self, traces: list[np.ndarray]) -> None:
        self.update_trace_x_range()
        self.set_plot_y_range(self.overview_plot, traces)

    def apply_detail_plot_range(
        self,
        traces: list[np.ndarray],
        preserve_range: bool,
        view_range: list[list[float]],
    ) -> None:
        if preserve_range:
            self.detail_plot.setRange(
                xRange=tuple(view_range[0]),
                yRange=tuple(view_range[1]),
                padding=0,
            )
            self.update_detail_range_spinboxes()
            return

        self.update_trace_x_range()
        self.set_plot_y_range(self.detail_plot, traces)
        self.update_detail_range_spinboxes()

    def set_plot_y_range(self, plot: pg.PlotWidget, traces: list[np.ndarray]) -> None:
        values = [
            trace[np.isfinite(trace)]
            for trace in traces
            if trace is not None and np.isfinite(trace).any()
        ]
        if not values:
            return

        all_values = np.concatenate(values)
        y_min = float(np.min(all_values))
        y_max = float(np.max(all_values))
        if y_min == y_max:
            padding = max(abs(y_min) * 0.05, 1.0)
            y_min -= padding
            y_max += padding

        plot.setYRange(y_min, y_max, padding=0)

    def set_frame_controls_enabled(self, enabled: bool) -> None:
        self.frame_slider.setEnabled(enabled)
        self.frame_spinbox.setEnabled(enabled)
        self.play_button.setEnabled(enabled and self.frame_count > 1)
        self.close_nd_button.setEnabled(enabled and self.reader is not None)
        self.add_roi_button.setEnabled(enabled)
        self.roi_shape_combo.setEnabled(enabled)
        self.auto_roi_button.setEnabled(enabled)
        self.calculate_button.setEnabled(enabled)
        self.background_button.setEnabled(enabled)
        self.recommend_background_button.setEnabled(enabled)
        self.background_radius_spinbox.setEnabled(enabled)
        self.clear_background_button.setEnabled(enabled)
        self.clear_roi_button.setEnabled(enabled)
        self.load_info_button.setEnabled(True)
        self.update_photobleaching_controls_enabled()
        self.update_saved_roi_controls_enabled()
        for spinbox in self.time_selection_spinboxes():
            spinbox.setEnabled(enabled)
        for spinbox in self.detail_range_spinboxes():
            spinbox.setEnabled(enabled)
        self.transient_calculate_button.setEnabled(enabled)
        for widget in self.transient_parameter_widgets():
            widget.setEnabled(enabled)
        for widget in self.sr_calcium_parameter_widgets():
            widget.setEnabled(enabled)
        for widget in self.photobleaching_parameter_widgets():
            widget.setEnabled(enabled)

    def update_photobleaching_controls_enabled(self) -> None:
        has_traces = self.reader is not None and bool(self.roi_raw_traces)
        self.correct_bleaching_button.setEnabled(has_traces)
        self.confirm_bleaching_button.setEnabled(
            has_traces and bool(self.photobleaching_preview_traces)
        )
        self.reset_bleaching_button.setEnabled(
            has_traces
            and (self.photobleaching_corrected or bool(self.photobleaching_preview_traces))
        )

    def update_saved_roi_controls_enabled(self) -> None:
        self.save_roi_button.setEnabled(self.reader is not None and bool(self.rois))
        self.save_results_button.setEnabled(
            self.current_path is not None and bool(self.saved_roi_entries)
        )

    def set_frame_index(self, frame_index: int) -> None:
        self.display_frame(frame_index)
        if self.is_playing:
            self.reset_playback_clock(self.current_frame_index)

    def display_frame(self, frame_index: int) -> None:
        if self.reader is None:
            return

        frame_index = max(0, min(frame_index, self.frame_count - 1))
        if frame_index == self.current_frame_index:
            return

        self.frame_slider.blockSignals(True)
        self.frame_spinbox.blockSignals(True)
        self.frame_slider.setValue(frame_index)
        self.frame_spinbox.setValue(frame_index)
        self.frame_slider.blockSignals(False)
        self.frame_spinbox.blockSignals(False)

        frame = self.get_frame(frame_index)
        self.image_shape = frame.shape[:2]
        self.image_view.setImage(
            frame,
            autoRange=False,
            autoLevels=False,
            levels=DISPLAY_LEVELS,
            autoHistogramRange=False,
        )
        self.fit_image_to_view()
        self.apply_fixed_display_levels()
        self.current_frame_index = frame_index
        self.update_frame_label(frame_index)

    def get_frame(self, frame_index: int) -> np.ndarray:
        if self.movie_stack is not None:
            return self.movie_stack[frame_index]
        if self.reader is None:
            raise RuntimeError("No ND2 reader is open.")
        return self.reader.read_frame(frame_index)

    def ensure_movie_loaded(self) -> np.ndarray:
        if self.movie_stack is not None:
            return self.movie_stack
        if self.reader is None:
            raise RuntimeError("No ND2 reader is open.")

        self.info_label.setText("Loading full movie into memory for ROI trace...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            self.movie_stack = self.reader.asarray()
        finally:
            QApplication.restoreOverrideCursor()

        self.info_label.setText(
            f"Movie loaded in memory | shape={self.movie_stack.shape} | "
            f"dtype={self.movie_stack.dtype}"
        )
        QApplication.processEvents()
        return self.movie_stack

    def fit_image_to_view(self) -> None:
        if self.image_shape is None:
            return

        height, width = self.image_shape
        self.image_view.view.setAspectLocked(True)
        self.image_view.view.disableAutoRange()
        self.image_view.view.setRange(
            xRange=(0, width),
            yRange=(0, height),
            padding=0,
        )

    def hide_histogram_panel(self) -> None:
        self.image_view.ui.histogram.hide()
        self.image_view.getHistogramWidget().hide()

    def apply_fixed_display_levels(self) -> None:
        histogram = self.image_view.getHistogramWidget()
        histogram.setLevels(*DISPLAY_LEVELS)
        self.hide_histogram_panel()

    def add_signal_roi(self) -> None:
        if self.image_shape is None:
            return

        self.roi_counter += 1
        roi_name = f"ROI {self.roi_counter}"
        roi_color = ROI_COLORS[(self.roi_counter - 1) % len(ROI_COLORS)]
        roi_pen = pg.mkPen(roi_color, width=2)
        roi = self.create_signal_roi(
            size=ROI_SIZE,
            pen=roi_pen,
            hover_pen=pg.mkPen("#FFF4A3", width=3),
        )
        roi.setToolTip(roi_name)
        self.image_view.view.addItem(roi)
        self.rois.append(roi)
        self.roi_names[roi] = roi_name
        self.roi_pens[roi] = roi_pen
        self.update_auto_roi_button_text()
        self.update_saved_roi_controls_enabled()
        self.update_roi_status()

    def selected_roi_shape(self) -> str:
        shape = self.roi_shape_combo.currentData()
        return str(shape) if shape in {"ellipse", "rectangle"} else "ellipse"

    def create_signal_roi(
        self,
        size: tuple[int, int],
        pen,
        hover_pen,
        pos: tuple[float, float] | None = None,
    ) -> pg.ROI:
        if self.selected_roi_shape() == "rectangle":
            return self.create_rectangle_roi(size, pen, hover_pen, pos)
        return self.create_ellipse_roi(size, pen, hover_pen, pos)

    def toggle_auto_roi(self) -> None:
        if self.rois and self.rois[-1] in self.auto_roi_originals:
            self.undo_auto_roi()
            return

        self.auto_latest_roi()

    def update_auto_roi_button_text(self) -> None:
        if self.rois and self.rois[-1] in self.auto_roi_originals:
            self.auto_roi_button.setText("(op) Undo Auto ROI")
            return

        self.auto_roi_button.setText("(op) Auto ROI")

    def auto_latest_roi(self) -> None:
        if not self.rois:
            self.info_label.setText("Add an ROI before using Auto ROI.")
            self.update_auto_roi_button_text()
            return

        target_roi = self.rois[-1]
        roi_name = self.roi_names.get(target_roi, "ROI")
        if target_roi in self.auto_roi_originals:
            self.info_label.setText(
                f"{roi_name} is already an Auto ROI. Press the same button to undo it."
            )
            self.update_auto_roi_button_text()
            return

        self.info_label.setText(
            f"Auto ROI for {roi_name}: detecting changing pixels inside the current ROI over 0-3 s..."
        )
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        try:
            result = self.build_auto_roi_polygon(target_roi)
        finally:
            QApplication.restoreOverrideCursor()

        if result is None:
            self.info_label.setText(
                f"{roi_name}: not enough changing pixels found for Auto ROI."
            )
            return

        polygon_points, active_pixels, frame_count = result
        new_roi = pg.PolyLineROI(
            polygon_points,
            closed=True,
            pen=self.roi_pens.get(target_roi, pg.mkPen("#FFD23F", width=2)),
            movable=True,
            removable=False,
        )
        new_roi.setToolTip(f"{roi_name} auto ROI")
        self.replace_signal_roi(target_roi, new_roi)
        self.auto_roi_originals[new_roi] = target_roi
        self.update_auto_roi_button_text()
        self.info_label.setText(
            f"{roi_name} Auto ROI made from the current ROI position using {active_pixels} active pixels "
            f"from {frame_count} frames. Press Calculate to update graph."
        )

    def undo_auto_roi(self) -> None:
        if not self.rois or self.rois[-1] not in self.auto_roi_originals:
            self.info_label.setText("No Auto ROI to undo.")
            self.update_auto_roi_button_text()
            return

        auto_roi = self.rois[-1]
        original_roi = self.auto_roi_originals.pop(auto_roi)
        roi_name = self.roi_names.get(auto_roi, "ROI")
        original_roi.setToolTip(roi_name)
        self.replace_signal_roi(auto_roi, original_roi)
        self.update_auto_roi_button_text()
        self.info_label.setText(
            f"{roi_name}: Auto ROI undone. The previous ellipse ROI is restored."
        )

    def build_auto_roi_polygon(
        self,
        roi: pg.ROI,
    ) -> tuple[list[tuple[float, float]], int, int] | None:
        """Enclose high-changing pixels in the current ROI with a convex hull."""
        if self.image_shape is None:
            return None

        frame_indices = self.auto_roi_frame_indices()
        if frame_indices.size == 0:
            return None

        ones = np.ones(self.image_shape, dtype=np.float32)
        mask = roi.getArrayRegion(ones, self.image_view.imageItem, axes=(0, 1))
        if mask is None or float(mask.sum()) <= 0:
            return None

        regions = []
        coords = None
        for frame_counter, frame_index in enumerate(frame_indices, start=1):
            frame = self.get_frame(int(frame_index))
            if coords is None:
                region, coords = roi.getArrayRegion(
                    frame,
                    self.image_view.imageItem,
                    axes=(0, 1),
                    returnMappedCoords=True,
                )
            else:
                region = roi.getArrayRegion(
                    frame,
                    self.image_view.imageItem,
                    axes=(0, 1),
                )

            if region is None:
                return None
            regions.append(region.astype(np.float32, copy=False))

            if frame_counter % 100 == 0:
                self.info_label.setText(
                    "Auto ROI: "
                    f"{frame_counter}/{len(frame_indices)} frames checked..."
                )
                QApplication.processEvents()

        if coords is None:
            return None

        stack = np.stack(regions, axis=0)
        change = stack.max(axis=0) - stack.min(axis=0)
        inside = mask > 0
        values = change[inside]
        if values.size == 0:
            return None

        threshold = float(np.percentile(values, AUTO_ROI_CHANGE_PERCENTILE))
        active = inside & (change >= threshold)
        if int(active.sum()) < AUTO_ROI_MIN_PIXELS:
            flat_inside = np.flatnonzero(inside.ravel())
            if flat_inside.size < AUTO_ROI_MIN_PIXELS:
                return None
            ranked = flat_inside[np.argsort(change.ravel()[flat_inside])]
            chosen = ranked[-AUTO_ROI_MIN_PIXELS:]
            active = np.zeros_like(inside, dtype=bool)
            active.ravel()[chosen] = True

        # getArrayRegion returns image-array coordinates as row, column.
        # PolyLineROI expects view coordinates as x, y.
        points = np.column_stack((coords[1][active], coords[0][active]))
        hull = self.convex_hull(points)
        if len(hull) < 3:
            return None

        return hull, int(active.sum()), int(len(frame_indices))

    def auto_roi_frame_indices(self) -> np.ndarray:
        if self.graph_time_s.size:
            frame_indices = np.flatnonzero(self.graph_time_s <= AUTO_ROI_DURATION_S)
        else:
            frame_indices = np.arange(min(self.frame_count, 1), dtype=int)

        if frame_indices.size > AUTO_ROI_MAX_FRAMES:
            sample_positions = np.linspace(
                0,
                frame_indices.size - 1,
                AUTO_ROI_MAX_FRAMES,
                dtype=int,
            )
            frame_indices = frame_indices[sample_positions]

        return frame_indices.astype(int)

    def convex_hull(self, points: np.ndarray) -> list[tuple[float, float]]:
        unique_points = sorted({(float(x), float(y)) for x, y in points})
        if len(unique_points) <= 1:
            return unique_points

        def cross(
            origin: tuple[float, float],
            a: tuple[float, float],
            b: tuple[float, float],
        ) -> float:
            return (
                (a[0] - origin[0]) * (b[1] - origin[1])
                - (a[1] - origin[1]) * (b[0] - origin[0])
            )

        lower: list[tuple[float, float]] = []
        for point in unique_points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                lower.pop()
            lower.append(point)

        upper: list[tuple[float, float]] = []
        for point in reversed(unique_points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                upper.pop()
            upper.append(point)

        return lower[:-1] + upper[:-1]

    def replace_signal_roi(self, old_roi: pg.ROI, new_roi: pg.ROI) -> None:
        if old_roi not in self.rois:
            return

        index = self.rois.index(old_roi)
        self.image_view.view.removeItem(old_roi)
        self.image_view.view.addItem(new_roi)
        self.rois[index] = new_roi

        self.roi_names[new_roi] = self.roi_names.pop(old_roi, f"ROI {index + 1}")
        self.roi_pens[new_roi] = self.roi_pens.pop(
            old_roi,
            pg.mkPen("#FFD23F", width=2),
        )

        curves = self.trace_curves.pop(old_roi, None)
        if curves is not None:
            self.overview_plot.removeItem(curves[0])
            self.detail_plot.removeItem(curves[1])
        self.roi_traces.pop(old_roi, None)
        self.roi_raw_traces.pop(old_roi, None)
        bleaching_curves = self.bleaching_fit_curves.pop(old_roi, None)
        if bleaching_curves is not None:
            self.overview_plot.removeItem(bleaching_curves[0])
            self.detail_plot.removeItem(bleaching_curves[1])
        self.photobleaching_corrected = False
        self.update_photobleaching_controls_enabled()
        self.clear_all_analysis()

    def set_background_roi(
        self,
        pos: tuple[float, float] | None = None,
        size: tuple[int, int] = BACKGROUND_ROI_SIZE,
        tooltip: str = "Background ROI",
    ) -> None:
        if self.image_shape is None:
            return

        if self.background_roi is not None:
            self.image_view.view.removeItem(self.background_roi)

        roi = self.create_ellipse_roi(
            size=size,
            pen=pg.mkPen("#4DB6FF", width=2),
            hover_pen=pg.mkPen("#A6DDFF", width=3),
            pos=pos,
        )
        roi.setToolTip(tooltip)
        self.image_view.view.addItem(roi)
        self.background_roi = roi
        self.background_trace = None
        self.clear_trace_curves()
        self.roi_raw_traces = {}
        self.roi_traces = {}
        self.photobleaching_corrected = False
        self.clear_all_analysis()
        self.update_photobleaching_controls_enabled()
        self.update_roi_status()

    def clear_background_roi(self) -> None:
        had_background = (
            self.background_roi is not None or self.background_trace is not None
        )

        if self.background_roi is not None:
            self.image_view.view.removeItem(self.background_roi)
            self.background_roi = None

        self.background_trace = None
        if had_background:
            self.clear_trace_curves()
            self.roi_raw_traces = {}
            self.roi_traces = {}
            self.photobleaching_corrected = False
            self.clear_all_analysis()
            self.update_photobleaching_controls_enabled()
        self.update_roi_status()

    def recommend_background_roi(self) -> None:
        if self.image_shape is None or self.reader is None:
            return

        radius = self.background_radius_spinbox.value()
        self.info_label.setText(
            "Finding recommended background: "
            f"100 random radius {radius} px circles over ~10 s..."
        )
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

        try:
            recommendation = self.find_recommended_background()
        finally:
            QApplication.restoreOverrideCursor()

        if recommendation is None:
            self.info_label.setText("Could not find a recommended background area.")
            return

        x, y, score, n_frames, radius = recommendation
        diameter = radius * 2
        self.set_background_roi(
            pos=(float(x), float(y)),
            size=(diameter, diameter),
            tooltip=(
                f"Recommended Background ROI | radius={radius}px | mean={score:.3f} | "
                f"frames tested={n_frames}"
            ),
        )
        self.info_label.setText(
            f"Recommended background set at x={x}, y={y} | "
            f"radius={radius} px mean={score:.3f} over {n_frames} frames."
        )

    def find_recommended_background(self) -> tuple[int, int, float, int, int] | None:
        """Choose the dimmest circular region sampled from the early movie."""
        if self.image_shape is None:
            return None

        height, width = self.image_shape
        radius = self.background_radius_spinbox.value()
        diameter = radius * 2
        if width < diameter or height < diameter:
            return None

        frame_indices = self.background_recommend_frame_indices()
        if frame_indices.size == 0:
            return None

        yy, xx = np.ogrid[:diameter, :diameter]
        center = radius - 0.5
        circle_mask = (xx - center) ** 2 + (yy - center) ** 2 <= radius**2

        rng = np.random.default_rng()
        xs = rng.integers(0, width - diameter + 1, size=BACKGROUND_RECOMMEND_CANDIDATES)
        ys = rng.integers(0, height - diameter + 1, size=BACKGROUND_RECOMMEND_CANDIDATES)
        scores = np.zeros(BACKGROUND_RECOMMEND_CANDIDATES, dtype=np.float64)

        if self.movie_stack is not None:
            for candidate_index, (x, y) in enumerate(zip(xs, ys)):
                patch = self.movie_stack[
                    frame_indices,
                    y : y + diameter,
                    x : x + diameter,
                ]
                scores[candidate_index] = float(patch[:, circle_mask].mean())
        else:
            for frame_counter, frame_index in enumerate(frame_indices, start=1):
                frame = self.get_frame(int(frame_index))
                for candidate_index, (x, y) in enumerate(zip(xs, ys)):
                    patch = frame[y : y + diameter, x : x + diameter]
                    scores[candidate_index] += float(
                        patch[circle_mask].mean()
                    )
                if frame_counter % 250 == 0:
                    self.info_label.setText(
                        "Finding recommended background: "
                        f"{frame_counter}/{len(frame_indices)} frames checked..."
                    )
                    QApplication.processEvents()
            scores /= len(frame_indices)

        best_index = int(np.argmin(scores))
        return (
            int(xs[best_index]),
            int(ys[best_index]),
            float(scores[best_index]),
            int(len(frame_indices)),
            int(radius),
        )

    def background_recommend_frame_indices(self) -> np.ndarray:
        if self.graph_time_s.size:
            frame_indices = np.flatnonzero(
                self.graph_time_s <= BACKGROUND_RECOMMEND_DURATION_S
            )
            if frame_indices.size:
                return frame_indices.astype(int)

        return np.arange(
            min(self.frame_count, max(1, int(BACKGROUND_RECOMMEND_DURATION_S))),
            dtype=int,
        )

    def create_ellipse_roi(
        self,
        size: tuple[int, int],
        pen,
        hover_pen,
        pos: tuple[float, float] | None = None,
    ) -> pg.EllipseROI:
        if self.image_shape is None:
            raise RuntimeError("Image shape is not available.")

        if pos is None:
            pos = self.default_roi_position(size)

        return pg.EllipseROI(
            pos,
            size,
            pen=pen,
            hoverPen=hover_pen,
            movable=True,
            rotatable=True,
            resizable=True,
            removable=False,
        )

    def create_rectangle_roi(
        self,
        size: tuple[int, int],
        pen,
        hover_pen,
        pos: tuple[float, float] | None = None,
    ) -> pg.RectROI:
        if self.image_shape is None:
            raise RuntimeError("Image shape is not available.")

        if pos is None:
            pos = self.default_roi_position(size)

        roi = pg.RectROI(
            pos,
            size,
            pen=pen,
            hoverPen=hover_pen,
            movable=True,
            rotatable=True,
            resizable=True,
            removable=False,
        )
        # RectROI adds a scale handle only, unlike EllipseROI.  Add the same
        # center-based rotation handle so rectangle ROIs can be rotated by
        # dragging the handle on their right edge.
        roi.addRotateHandle([1.0, 0.5], [0.5, 0.5])
        return roi

    def default_roi_position(self, size: tuple[int, int]) -> tuple[float, float]:
        if self.image_shape is None:
            raise RuntimeError("Image shape is not available.")

        height, width = self.image_shape
        roi_width, roi_height = size
        return (
            max((width - roi_width) / 2, 0),
            max((height - roi_height) / 2, 0),
        )

    def clear_rois(self) -> None:
        for roi in self.rois:
            self.image_view.view.removeItem(roi)
        self.rois = []

        self.clear_trace_curves()
        self.clear_all_analysis()
        self.roi_raw_traces = {}
        self.roi_traces = {}
        self.photobleaching_corrected = False
        self.detail_plot_has_data = False
        self.roi_names = {}
        self.roi_pens = {}
        self.auto_roi_originals = {}
        self.roi_counter = 0
        self.update_photobleaching_controls_enabled()
        self.update_auto_roi_button_text()
        self.update_saved_roi_controls_enabled()
        self.update_roi_status()

    def clear_trace_curves(self) -> None:
        for overview_curve, detail_curve in self.trace_curves.values():
            self.overview_plot.removeItem(overview_curve)
            self.detail_plot.removeItem(detail_curve)
        self.trace_curves = {}
        self.clear_photobleaching_preview()

    def clear_bleaching_fit_curves(self) -> None:
        for overview_curve, detail_curve in self.bleaching_fit_curves.values():
            self.overview_plot.removeItem(overview_curve)
            self.detail_plot.removeItem(detail_curve)
        self.bleaching_fit_curves = {}

        for overview_curve, detail_curve in self.bleaching_baseline_curves.values():
            self.overview_plot.removeItem(overview_curve)
            self.detail_plot.removeItem(detail_curve)
        self.bleaching_baseline_curves = {}

    def clear_photobleaching_preview(self) -> None:
        self.clear_bleaching_fit_curves()
        self.photobleaching_preview_traces = {}
        self.photobleaching_preview_fit_lines = {}
        self.photobleaching_preview_baseline_masks = {}
        self.photobleaching_preview_modes = {}
        self.update_photobleaching_controls_enabled()

    def calculate_traces(self) -> None:
        if not self.rois:
            self.info_label.setText("Add at least one ROI before calculating.")
            return

        preserve_detail_range = self.detail_plot_has_data
        detail_view_range = self.detail_plot.viewRange()
        self.clear_trace_curves()
        self.clear_all_analysis()
        self.roi_raw_traces = {}
        self.roi_traces = {}
        self.photobleaching_corrected = False
        self.background_trace = None
        traces = self.update_all_signal_roi_traces()
        self.apply_overview_plot_range(traces)
        self.apply_detail_plot_range(
            traces,
            preserve_range=preserve_detail_range,
            view_range=detail_view_range,
        )
        self.detail_plot_has_data = bool(traces)
        self.update_photobleaching_controls_enabled()
        self.update_roi_status()

    def update_signal_roi_trace(self, roi: pg.ROI) -> np.ndarray | None:
        if roi not in self.rois or self.graph_time_s.size == 0:
            return None

        roi_name = self.roi_names.get(roi, "ROI")
        self.info_label.setText(f"Calculating intensity trace for {roi_name}...")
        QApplication.processEvents()

        raw_trace = self.calculate_roi_trace(roi)
        if raw_trace is None:
            self.info_label.setText(f"{roi_name}: ROI is outside the image.")
            return None

        background_trace = self.get_background_trace()
        trace = raw_trace - background_trace if background_trace is not None else raw_trace
        self.roi_raw_traces[roi] = trace.copy()
        self.roi_traces[roi] = trace.copy()

        curves = self.trace_curves.get(roi)
        if curves is None:
            self.create_signal_trace_curves(roi, trace)
        else:
            overview_curve, detail_curve = curves
            overview_curve.setData(self.graph_time_s, trace)
            detail_curve.setData(self.graph_time_s, trace)

        return trace

    def update_all_signal_roi_traces(self) -> list[np.ndarray]:
        traces: list[np.ndarray] = []
        for roi in list(self.rois):
            trace = self.update_signal_roi_trace(roi)
            if trace is not None:
                traces.append(trace)
        return traces

    def get_background_trace(self) -> np.ndarray | None:
        if self.background_roi is None:
            return None
        if self.background_trace is None:
            self.background_trace = self.calculate_roi_trace(self.background_roi)
        return self.background_trace

    def calculate_roi_trace(self, roi: pg.ROI) -> np.ndarray | None:
        """Calculate one mean-intensity value per frame inside an ROI mask."""
        if self.image_shape is None:
            return None

        stack = self.ensure_movie_loaded()
        mask = roi.getArrayRegion(
            np.ones(self.image_shape, dtype=np.float32),
            self.image_view.imageItem,
            axes=(0, 1),
        )
        if mask is None:
            return None

        mask_sum = float(mask.sum())
        if mask_sum <= 0:
            return None

        region = roi.getArrayRegion(stack, self.image_view.imageItem, axes=(1, 2))
        if region is None:
            return None

        return region.sum(axis=(1, 2), dtype=np.float64) / mask_sum

    def update_roi_status(self) -> None:
        background_text = "set" if self.background_roi is not None else "not set"
        trace_text = "background-corrected" if self.background_roi is not None else "raw"
        if self.photobleaching_corrected:
            trace_text += " + photobleaching-corrected"
        self.info_label.setText(
            f"Current ROIs: {len(self.rois)} | Saved ROIs: {len(self.saved_roi_entries)} | "
            f"Background: {background_text} | "
            f"Graph: {trace_text} intensity | "
            "Drag ellipses, then press Calculate."
        )

    def update_frame_label(self, frame_index: int) -> None:
        time_text = "time unavailable"
        if 0 <= frame_index < len(self.frame_times_s):
            time_s = self.frame_times_s[frame_index]
            if time_s is not None:
                time_text = f"{time_s:.6f} s"

        self.frame_label.setText(
            f"Frame: {frame_index + 1} / {self.frame_count} | Time: {time_text}"
        )
        if self.graph_time_s.size and 0 <= frame_index < len(self.graph_time_s):
            time_position = float(self.graph_time_s[frame_index])
            self.overview_time_line.setPos(time_position)
            self.detail_time_line.setPos(time_position)

    def toggle_playback(self) -> None:
        if self.is_playing:
            self.pause_playback()
        else:
            self.start_playback()

    def start_playback(self) -> None:
        if self.reader is None or self.frame_count <= 1:
            return

        if self.current_frame_index >= self.frame_count - 1:
            self.display_frame(0)

        self.is_playing = True
        self.play_button.setText("Pause")
        self.reset_playback_clock(self.current_frame_index)
        self.play_timer.start()

    def pause_playback(self) -> None:
        self.is_playing = False
        self.play_timer.stop()
        self.play_button.setText("Play")

    def reset_playback_clock(self, frame_index: int) -> None:
        self.playback_start_wall_s = time.perf_counter()
        self.playback_start_movie_s = self.time_for_frame(frame_index)

    def time_for_frame(self, frame_index: int) -> float:
        """Use recorded time first, then an interpolated or index-based fallback."""
        if 0 <= frame_index < len(self.frame_times_s):
            time_s = self.frame_times_s[frame_index]
            if time_s is not None:
                return time_s

        if self.valid_time_values_s:
            first_time = self.valid_time_values_s[0]
            last_time = self.valid_time_values_s[-1]
            if self.frame_count > 1:
                fraction = frame_index / (self.frame_count - 1)
                return first_time + fraction * (last_time - first_time)

        return float(frame_index)

    def find_frame_for_time(self, target_time_s: float) -> int:
        if not self.valid_time_values_s:
            return max(0, min(round(target_time_s), self.frame_count - 1))

        position = bisect_left(self.valid_time_values_s, target_time_s)
        if position <= 0:
            return self.valid_time_frame_indices[0]
        if position >= len(self.valid_time_values_s):
            return self.valid_time_frame_indices[-1]

        previous_time = self.valid_time_values_s[position - 1]
        next_time = self.valid_time_values_s[position]
        if abs(target_time_s - previous_time) <= abs(next_time - target_time_s):
            return self.valid_time_frame_indices[position - 1]
        return self.valid_time_frame_indices[position]

    def advance_playback(self) -> None:
        if not self.is_playing:
            return

        elapsed_wall_s = time.perf_counter() - self.playback_start_wall_s
        target_movie_time_s = self.playback_start_movie_s + elapsed_wall_s

        if self.valid_time_values_s and target_movie_time_s >= self.valid_time_values_s[-1]:
            self.display_frame(self.valid_time_frame_indices[-1])
            self.pause_playback()
            return

        self.display_frame(self.find_frame_for_time(target_movie_time_s))

    def close_reader(self) -> None:
        self.pause_playback()
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.movie_stack = None
        self.frame_count = 0
        self.image_shape = None
        self.frame_times_s = []
        self.graph_time_s = np.array([], dtype=float)
        self.valid_time_values_s = []
        self.valid_time_frame_indices = []
        self.current_frame_index = -1
        self.reset_time_selection_controls()
        self.reset_detail_range_controls()
        self.set_frame_controls_enabled(False)
