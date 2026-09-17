"""Photobleaching fitting and correction for calculated ROI traces."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from scipy.optimize import least_squares
from .constants import (
    PHOTOBLEACH_MIN_BASELINE_POINTS,
    SIGNAL_TRACE_CORRECTED_COLOR,
    SIGNAL_TRACE_RAW_COLOR,
)


class PhotobleachingMixin:
    """Previews and applies photobleaching correction."""

    def calculate_photobleaching_preview(self) -> None:
        if not self.roi_raw_traces:
            self.info_label.setText(
                "Calculate ROI traces before photobleaching correction."
            )
            return
        if self.graph_time_s.size < 3:
            self.info_label.setText("Time axis is too short for photobleaching correction.")
            return

        preview_traces: dict[pg.ROI, np.ndarray] = {}
        fit_lines: dict[pg.ROI, np.ndarray] = {}
        baseline_masks: dict[pg.ROI, np.ndarray] = {}
        modes: dict[pg.ROI, str] = {}
        skipped = 0
        ratio_count = 0
        subtract_count = 0

        for roi, trace in self.roi_raw_traces.items():
            result = self.photobleaching_corrected_trace(self.graph_time_s, trace)
            if result is None:
                skipped += 1
                continue

            corrected_trace, fit_line, baseline_mask, mode = result
            preview_traces[roi] = corrected_trace
            fit_lines[roi] = fit_line
            baseline_masks[roi] = baseline_mask
            modes[roi] = mode
            if mode == "ratio":
                ratio_count += 1
            else:
                subtract_count += 1

        if not fit_lines:
            self.clear_photobleaching_preview()
            self.info_label.setText(
                "Not enough baseline points for photobleaching correction."
            )
            return

        self.photobleaching_preview_traces = preview_traces
        self.photobleaching_preview_fit_lines = fit_lines
        self.photobleaching_preview_baseline_masks = baseline_masks
        self.photobleaching_preview_modes = modes
        self.draw_bleaching_preview_curves(fit_lines, baseline_masks)
        self.update_photobleaching_controls_enabled()

        mode_parts = []
        if ratio_count:
            mode_parts.append(f"ratio={ratio_count}")
        if subtract_count:
            mode_parts.append(f"subtract={subtract_count}")
        if skipped:
            mode_parts.append(f"skipped={skipped}")
        self.info_label.setText(
            "Photobleaching preview calculated ("
            + ", ".join(mode_parts)
            + "). Press Confirm Photobleaching to apply."
        )

    def confirm_photobleaching(self) -> None:
        if not self.photobleaching_preview_traces:
            self.info_label.setText(
                "Cal. Photobleaching before confirming correction."
            )
            return

        self.roi_traces = {
            roi: trace.copy()
            for roi, trace in self.roi_raw_traces.items()
        }
        for roi, corrected_trace in self.photobleaching_preview_traces.items():
            self.roi_traces[roi] = corrected_trace.copy()

        self.photobleaching_corrected = True
        self.clear_all_analysis()
        self.refresh_trace_curves()
        traces = list(self.roi_traces.values())
        self.apply_overview_plot_range(traces)
        self.apply_detail_plot_range(
            traces,
            preserve_range=False,
            view_range=self.detail_plot.viewRange(),
        )
        self.update_photobleaching_controls_enabled()
        self.info_label.setText("Photobleaching correction confirmed and applied.")

    def reset_photobleaching(self) -> None:
        if not self.roi_raw_traces:
            self.info_label.setText("No calculated traces to reset.")
            return

        self.roi_traces = {
            roi: trace.copy()
            for roi, trace in self.roi_raw_traces.items()
        }
        self.photobleaching_corrected = False
        self.clear_photobleaching_preview()
        self.reset_photobleaching_parameters()
        self.clear_all_analysis()
        self.refresh_trace_curves()
        traces = list(self.roi_traces.values())
        self.apply_overview_plot_range(traces)
        self.apply_detail_plot_range(
            traces,
            preserve_range=False,
            view_range=self.detail_plot.viewRange(),
        )
        self.update_photobleaching_controls_enabled()
        self.info_label.setText("Photobleaching correction reset.")

    def photobleaching_corrected_trace(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, str] | None:
        """Fit a baseline, using ratio correction when its values stay positive."""
        baseline_mask = self.photobleaching_baseline_mask(time_s, trace)
        baseline_points = int(np.sum(baseline_mask))
        fit_window_mask = self.photobleaching_fit_window_mask(time_s)
        fit_window_points = int(np.sum(fit_window_mask))
        min_points = max(
            PHOTOBLEACH_MIN_BASELINE_POINTS,
            int(round(fit_window_points * self.bleach_min_baseline_fraction())),
        )
        if baseline_points < min_points:
            return None

        fit_line = self.fit_photobleaching_line(time_s, trace, baseline_mask)
        if fit_line is None or not np.all(np.isfinite(fit_line)):
            return None

        reference_values = fit_line[fit_window_mask]
        reference_values = reference_values[np.isfinite(reference_values)]
        reference = (
            float(reference_values[0])
            if reference_values.size
            else float(fit_line[0])
        )
        if not np.isfinite(reference):
            return None

        if float(np.min(fit_line)) > 1e-6:
            corrected = trace / fit_line * reference
            mode = "ratio"
        else:
            corrected = trace - fit_line + reference
            mode = "subtract"

        return corrected, fit_line, baseline_mask, mode

    def photobleaching_baseline_mask(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
    ) -> np.ndarray:
        """Keep fit-window points outside transient events and their padding."""
        mask = (
            np.isfinite(time_s)
            & np.isfinite(trace)
            & self.photobleaching_fit_window_mask(time_s)
        )
        if time_s.size < 3 or not np.any(mask):
            return mask

        interval_start, interval_end = self.bleach_fit_window_s()
        interval_start = max(float(time_s[0]), interval_start)
        interval_end = min(float(time_s[-1]), interval_end)
        if interval_end <= interval_start:
            return np.zeros_like(mask, dtype=bool)

        events = self.detect_transient_events(
            time_s,
            trace,
            interval_start,
            interval_end,
        )
        for event in events:
            start = float(event["start_time_s"]) - self.bleach_pre_padding_s()
            end = float(event["recovery_time_s"]) + self.bleach_post_padding_s()
            mask &= ~((time_s >= start) & (time_s <= end))

        return mask

    def photobleaching_fit_window_mask(self, time_s: np.ndarray) -> np.ndarray:
        if time_s.size == 0:
            return np.array([], dtype=bool)

        start_s, end_s = self.bleach_fit_window_s()
        return (time_s >= start_s) & (time_s <= end_s)

    def fit_photobleaching_line(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        baseline_mask: np.ndarray,
    ) -> np.ndarray | None:
        """Fit a robust linear baseline after centering time for numerical stability."""
        fit_time = time_s[baseline_mask]
        fit_trace = trace[baseline_mask]
        if fit_time.size < 2:
            return None

        center_time = float(np.mean(fit_time))
        centered_fit_time = fit_time - center_time
        centered_time = time_s - center_time
        try:
            slope, intercept = np.polyfit(centered_fit_time, fit_trace, deg=1)
        except (TypeError, ValueError, np.linalg.LinAlgError):
            return None

        initial = np.array([float(slope), float(intercept)], dtype=float)
        noise_scale = self.robust_noise_scale(fit_trace)

        def residuals(params: np.ndarray) -> np.ndarray:
            slope_param, intercept_param = params
            return slope_param * centered_fit_time + intercept_param - fit_trace

        try:
            result = least_squares(
                residuals,
                initial,
                loss="soft_l1",
                f_scale=max(noise_scale * self.bleach_robustness_scale(), 1e-6),
                max_nfev=1000,
            )
        except ValueError:
            return None

        if not result.success or not np.all(np.isfinite(result.x)):
            return None

        slope, intercept = (float(value) for value in result.x)
        return slope * centered_time + intercept

    def refresh_trace_curves(self) -> None:
        pen = self.signal_trace_pen()
        for roi, trace in self.roi_traces.items():
            curves = self.trace_curves.get(roi)
            if curves is None:
                self.create_signal_trace_curves(roi, trace)
                continue

            overview_curve, detail_curve = curves
            overview_curve.setPen(pen)
            detail_curve.setPen(pen)
            overview_curve.setData(self.graph_time_s, trace)
            detail_curve.setData(self.graph_time_s, trace)

    def signal_trace_pen(self):
        color = (
            SIGNAL_TRACE_CORRECTED_COLOR
            if self.photobleaching_corrected
            else SIGNAL_TRACE_RAW_COLOR
        )
        return pg.mkPen(color, width=2)

    def create_signal_trace_curves(
        self,
        roi: pg.ROI,
        trace: np.ndarray,
    ) -> tuple[pg.PlotDataItem, pg.PlotDataItem]:
        pen = self.signal_trace_pen()
        overview_curve = self.overview_plot.plot(
            self.graph_time_s,
            trace,
            pen=pen,
        )
        detail_curve = self.detail_plot.plot(
            self.graph_time_s,
            trace,
            pen=pen,
        )
        overview_curve.setZValue(10)
        detail_curve.setZValue(10)
        self.trace_curves[roi] = (overview_curve, detail_curve)
        return overview_curve, detail_curve

    def draw_bleaching_preview_curves(
        self,
        fit_lines: dict[pg.ROI, np.ndarray],
        baseline_masks: dict[pg.ROI, np.ndarray],
    ) -> None:
        self.clear_bleaching_fit_curves()
        fit_pen = pg.mkPen("#FFE082CC", width=3, style=Qt.DashLine)
        baseline_pen = pg.mkPen("#FF3B30", width=3, style=Qt.DotLine)
        for roi, fit_line in fit_lines.items():
            overview_curve = self.overview_plot.plot(
                self.graph_time_s,
                fit_line,
                pen=fit_pen,
            )
            detail_curve = self.detail_plot.plot(
                self.graph_time_s,
                fit_line,
                pen=fit_pen,
            )
            overview_curve.setZValue(12)
            detail_curve.setZValue(12)
            self.bleaching_fit_curves[roi] = (overview_curve, detail_curve)

            mask = baseline_masks.get(roi)
            trace = self.roi_raw_traces.get(roi)
            if mask is None or trace is None or mask.size != trace.size:
                continue

            baseline_trace = np.where(mask, trace, np.nan)
            overview_baseline_curve = self.overview_plot.plot(
                self.graph_time_s,
                baseline_trace,
                pen=baseline_pen,
                connect="finite",
            )
            detail_baseline_curve = self.detail_plot.plot(
                self.graph_time_s,
                baseline_trace,
                pen=baseline_pen,
                connect="finite",
            )
            overview_baseline_curve.setZValue(14)
            detail_baseline_curve.setZValue(14)
            self.bleaching_baseline_curves[roi] = (
                overview_baseline_curve,
                detail_baseline_curve,
            )
