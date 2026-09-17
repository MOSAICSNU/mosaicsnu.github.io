"""Transient and SR-calcium event detection, measurements, and rendering."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QTableWidgetItem,
)
from scipy.optimize import least_squares
from .constants import (
    GRAPH_FOREGROUND,
    SR_CALCIUM_DETECTION_SMOOTH_S,
    TRANSIENT_RECOVERY_FRACTION,
    TRANSIENT_RECOVERY_HOLD_S,
    TRANSIENT_SECONDARY_LOOKAHEAD_S,
    TRANSIENT_SECONDARY_RISE_FRACTION,
    TRANSIENT_TAIL_TURN_FRACTION,
)


class TransientAnalysisMixin:
    """Detects, measures, and renders calcium transient events."""

    def clear_transient_plot_items(self) -> None:
        for curve in self.transient_event_curves:
            self.transient_average_plot.removeItem(curve)
        self.transient_event_curves = []

        if self.transient_average_curve is not None:
            self.transient_average_plot.removeItem(self.transient_average_curve)

        self.transient_average_curve = None

    def clear_sr_calcium_analysis(self) -> None:
        for item in self.sr_calcium_curves:
            self.sr_calcium_event_plot.removeItem(item)
        self.sr_calcium_curves = []

        for item in self.sr_calcium_fit_curves:
            self.sr_calcium_event_plot.removeItem(item)
        self.sr_calcium_fit_curves = []

        for marker in self.sr_calcium_markers:
            self.sr_calcium_event_plot.removeItem(marker)
        self.sr_calcium_markers = []

        self.sr_calcium_records = []
        self.sr_calcium_trace_segments = []
        self.sr_calcium_fit_segments = []
        self.sr_calcium_table.setRowCount(0)
        self.sr_calcium_fit_reference_peak_s = None
        self.sr_calcium_fit_region_updating = True
        self.sr_calcium_fit_region.hide()
        self.sr_calcium_fit_region_updating = False

    def clear_all_analysis(self) -> None:
        self.clear_transient_analysis()
        self.clear_sr_calcium_analysis()

    def clear_transient_analysis(self) -> None:
        self.clear_transient_plot_items()
        self.transient_common_time = np.array([], dtype=float)
        self.transient_snippets = np.empty((0, 0), dtype=float)
        self.transient_records = []
        self.transient_status_suffix = ""
        self.transient_table_updating = True
        self.transient_table.setRowCount(0)
        self.transient_table_updating = False

    def calculate_transient_average(self) -> None:
        if not self.rois:
            self.info_label.setText("Add at least one ROI before transient analysis.")
            return

        if not self.roi_traces:
            self.calculate_traces()
        if not self.roi_traces:
            self.info_label.setText("No ROI traces available for transient analysis.")
            return

        self.transient_table_decay_percents = self.transient_decay_percent_values()
        self.set_transient_table_headers(self.transient_table_decay_percents)
        self.transient_interval_note = (
            "Pacing interval = "
            f"{self.transient_pacing_interval_spinbox.value():.0f} ms."
        )

        self.clear_transient_analysis()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            result = self.build_transient_average()
        finally:
            QApplication.restoreOverrideCursor()

        if result is None:
            self.info_label.setText(
                "No transients detected. Try lowering Peak cutoff."
            )
            return

        common_time, snippets, records = result
        self.transient_common_time = common_time
        self.transient_snippets = snippets
        self.transient_records = records

        suffix_parts = []
        if self.transient_window_note:
            suffix_parts.append(self.transient_window_note)
        if self.transient_interval_note:
            suffix_parts.append(self.transient_interval_note)
        self.transient_status_suffix = " ".join(suffix_parts)
        self.populate_transient_table(records)
        self.render_selected_transients()

    def calculate_sr_calcium_events(self) -> None:
        if not self.rois:
            self.info_label.setText("Add at least one ROI before Caff. analysis.")
            return

        if not self.roi_traces:
            self.calculate_traces()
        if not self.roi_traces or self.graph_time_s.size < 3:
            self.info_label.setText("No ROI traces available for Caff. analysis.")
            return

        self.clear_sr_calcium_analysis()
        self.set_sr_calcium_table_headers(self.transient_table_decay_percents)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            records, trace_segments, fit_segments = self.build_sr_calcium_events()
        finally:
            QApplication.restoreOverrideCursor()

        self.sr_calcium_records = records
        self.sr_calcium_trace_segments = trace_segments
        self.sr_calcium_fit_segments = fit_segments
        self.populate_sr_calcium_table(records)
        self.render_sr_calcium_events(records, trace_segments, fit_segments)
        if records:
            self.info_label.setText(
                f"Caff. analysis calculated for {len(records)} ROI trace(s)."
            )
        else:
            self.info_label.setText("No Caff. event detected in the blue range.")

    def build_sr_calcium_events(
        self,
    ) -> tuple[
        list[dict[str, object]],
        list[tuple[np.ndarray, np.ndarray]],
        list[tuple[np.ndarray, np.ndarray]],
    ]:
        interval_start, interval_end = sorted(
            float(value) for value in self.sr_calcium_region.getRegion()
        )
        records: list[dict[str, object]] = []
        trace_segments: list[tuple[np.ndarray, np.ndarray]] = []
        fit_segments: list[tuple[np.ndarray, np.ndarray]] = []

        for roi, trace in self.roi_traces.items():
            event = self.detect_sr_calcium_event(
                self.graph_time_s,
                trace,
                interval_start,
                interval_end,
            )
            if event is None:
                continue

            start_time_s = float(event["start_time_s"])
            peak_time_s = float(event["peak_time_s"])
            window_start = max(
                float(self.graph_time_s[0]),
                start_time_s - self.sr_calcium_pre_start_s(),
            )
            window_end = min(
                float(self.graph_time_s[-1]),
                start_time_s + self.sr_calcium_post_start_s(),
            )
            mask = (self.graph_time_s >= window_start) & (self.graph_time_s <= window_end)
            if int(mask.sum()) < 3:
                continue

            segment_time = self.graph_time_s[mask]
            segment_trace = trace[mask]
            f0 = self.event_f0_from_pre_start(
                segment_time,
                segment_trace,
                start_time_s,
                event.get("baseline", float("nan")),
            )
            normalized_segment_trace = self.normalize_trace_to_f_over_f0(
                segment_trace,
                f0,
            )
            if normalized_segment_trace is None:
                continue
            normalized_amplitude = float(event["amplitude"]) / f0
            normalized_max_rise_rate = float(event["max_rise_rate"]) / f0
            (
                tau_s,
                fit_time,
                fit_trace,
                fit_offset,
                fit_r2,
                fit_rmse,
            ) = self.fit_exponential_decay_from_peak(
                segment_time,
                normalized_segment_trace,
                peak_time_s,
                self.sr_calcium_fit_start_s(),
                self.sr_calcium_fit_end_s(),
            )
            roi_name = self.roi_names.get(roi, "ROI")
            trace_segments.append((segment_time, normalized_segment_trace))
            if fit_time.size and fit_trace.size:
                fit_segments.append((fit_time, fit_trace))
            records.append(
                {
                    "roi": roi_name,
                    "event": 1,
                    "start_time_s": start_time_s,
                    "peak_time_s": peak_time_s,
                    "amplitude": normalized_amplitude,
                    "amp_ratio": self.amp_ratio_for_roi(roi_name, normalized_amplitude),
                    "prominence": float(event["prominence"]) / f0,
                    "max_rise_rate": normalized_max_rise_rate,
                    "f0": f0,
                    "baseline_raw": float(event["baseline"]),
                    "amplitude_raw": float(event["amplitude"]),
                    "max_rise_rate_raw": float(event["max_rise_rate"]),
                    "tau_s": tau_s,
                    "fit_offset": fit_offset,
                    "fit_r2": fit_r2,
                    "fit_rmse": fit_rmse,
                    "trace_time_s": segment_time.copy(),
                    "trace": normalized_segment_trace.copy(),
                    "fit_time_s": fit_time.copy(),
                    "fit_trace": fit_trace.copy(),
                }
            )

        return records, trace_segments, fit_segments

    def detect_sr_calcium_event(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        interval_start: float,
        interval_end: float,
    ) -> dict[str, object] | None:
        mask = (time_s >= interval_start) & (time_s <= interval_end)
        if int(mask.sum()) < 3:
            return None

        segment_time = time_s[mask]
        segment_trace = trace[mask]
        dt = self.estimate_sample_interval(segment_time)
        smooth_trace = self.smooth_trace(
            segment_trace,
            max(self.transient_smooth_s(), SR_CALCIUM_DETECTION_SMOOTH_S),
            dt,
        )
        if smooth_trace.size < 3 or not np.any(np.isfinite(smooth_trace)):
            return None

        peak_index = int(np.nanargmax(smooth_trace))
        if peak_index <= 0:
            return None

        pre_peak_trace = smooth_trace[: peak_index + 1]
        baseline_index = int(np.nanargmin(pre_peak_trace))
        baseline = float(smooth_trace[baseline_index])
        peak_value = float(smooth_trace[peak_index])
        amplitude = peak_value - baseline
        if not np.isfinite(amplitude) or amplitude <= 0:
            return None

        threshold = baseline + self.transient_start_fraction_spinbox.value() * amplitude
        start_index = baseline_index
        for index in range(peak_index, baseline_index - 1, -1):
            if smooth_trace[index] <= threshold:
                start_index = index
                break

        max_rise_rate = self.max_increasing_speed(
            segment_time,
            smooth_trace,
            start_index,
            peak_index,
        )
        return {
            "start_time_s": float(segment_time[start_index]),
            "peak_time_s": float(segment_time[peak_index]),
            "recovery_time_s": float(segment_time[-1]),
            "amplitude": float(amplitude),
            "prominence": float(amplitude),
            "baseline": float(baseline),
            "max_rise_rate": float(max_rise_rate),
        }

    def render_sr_calcium_events(
        self,
        records: list[dict[str, object]],
        trace_segments: list[tuple[np.ndarray, np.ndarray]],
        fit_segments: list[tuple[np.ndarray, np.ndarray]],
    ) -> None:
        for item in self.sr_calcium_curves:
            self.sr_calcium_event_plot.removeItem(item)
        self.sr_calcium_curves = []

        for item in self.sr_calcium_fit_curves:
            self.sr_calcium_event_plot.removeItem(item)
        self.sr_calcium_fit_curves = []

        for marker in self.sr_calcium_markers:
            self.sr_calcium_event_plot.removeItem(marker)
        self.sr_calcium_markers = []

        segment_values: list[np.ndarray] = []
        for segment_time, segment_trace in trace_segments:
            curve = self.sr_calcium_event_plot.plot(
                segment_time,
                segment_trace,
                pen=pg.mkPen("#FFFFFFCC", width=1),
            )
            curve.setZValue(10)
            self.sr_calcium_curves.append(curve)
            segment_values.append(segment_trace)

        for fit_time, fit_trace in fit_segments:
            curve = self.sr_calcium_event_plot.plot(
                fit_time,
                fit_trace,
                pen=pg.mkPen("#FFD23F", width=4),
            )
            curve.setZValue(20)
            self.sr_calcium_fit_curves.append(curve)

        for record in records:
            start_marker = pg.InfiniteLine(
                pos=float(record["start_time_s"]),
                angle=90,
                movable=False,
                pen=pg.mkPen("#FFFFFF80", width=1, style=Qt.DashLine),
            )
            peak_marker = pg.InfiniteLine(
                pos=float(record["peak_time_s"]),
                angle=90,
                movable=False,
                pen=pg.mkPen(GRAPH_FOREGROUND, width=1, style=Qt.DashLine),
            )
            self.sr_calcium_event_plot.addItem(start_marker)
            self.sr_calcium_event_plot.addItem(peak_marker)
            self.sr_calcium_markers.extend([start_marker, peak_marker])

        if trace_segments:
            x_min = min(float(segment_time[0]) for segment_time, _ in trace_segments)
            x_max = max(float(segment_time[-1]) for segment_time, _ in trace_segments)
            if x_max > x_min:
                self.sr_calcium_event_plot.setXRange(x_min, x_max, padding=0)
        if segment_values:
            self.set_plot_y_range(
                self.sr_calcium_event_plot,
                segment_values,
            )
        self.update_sr_fit_region_from_records(records)

    def update_sr_fit_region_from_records(self, records: list[dict[str, object]]) -> None:
        if not records:
            self.sr_calcium_fit_reference_peak_s = None
            self.sr_calcium_fit_region_updating = True
            self.sr_calcium_fit_region.hide()
            self.sr_calcium_fit_region_updating = False
            return

        peak_time_s = float(records[0]["peak_time_s"])
        self.sr_calcium_fit_reference_peak_s = peak_time_s
        fit_start_s = self.sr_calcium_fit_start_s()
        fit_end_s = self.sr_calcium_fit_end_s()
        start_s = peak_time_s + fit_start_s
        end_s = peak_time_s + fit_end_s
        if end_s <= start_s:
            dt = self.estimate_sample_interval(self.graph_time_s)
            end_s = start_s + max(dt, 0.001)

        if self.graph_time_s.size:
            self.sr_calcium_fit_region.setBounds(
                (float(self.graph_time_s[0]), float(self.graph_time_s[-1]))
            )

        self.sr_calcium_fit_region_updating = True
        self.sr_calcium_fit_region.setRegion((start_s, end_s))
        self.sr_calcium_fit_region.show()
        self.sr_calcium_fit_region_updating = False

    def sync_sr_fit_region_to_parameters(self, *_args: object) -> None:
        if self.sr_calcium_fit_region_updating:
            return
        if self.sr_calcium_fit_reference_peak_s is None:
            return

        start_s, end_s = sorted(
            float(value) for value in self.sr_calcium_fit_region.getRegion()
        )
        fit_start_s = max(0.0, start_s - self.sr_calcium_fit_reference_peak_s)
        fit_end_s = max(
            fit_start_s + 0.001,
            end_s - self.sr_calcium_fit_reference_peak_s,
        )

        self.sr_calcium_fit_region_updating = True
        self.sr_calcium_fit_start_spinbox.setValue(self.seconds_to_ms(fit_start_s))
        self.sr_calcium_fit_end_spinbox.setValue(self.seconds_to_ms(fit_end_s))
        self.sr_calcium_fit_region_updating = False
        self.calculate_sr_calcium_events()

    def update_transient_selection_from_table(self, item: QTableWidgetItem) -> None:
        if self.transient_table_updating or item.column() != 0:
            return
        self.render_selected_transients()
        if self.current_saved_roi_row is not None and not self.rois:
            self.update_current_saved_roi_from_transient_selection()
        else:
            self.refresh_sr_calcium_amp_ratios()

    def selected_transient_rows(self) -> list[int]:
        selected_rows = []
        for row in range(self.transient_table.rowCount()):
            item = self.transient_table.item(row, 0)
            if item is not None and item.checkState() == Qt.Checked:
                selected_rows.append(row)
        return selected_rows

    def transient_amp_reference_for_roi(self, roi_name: str) -> float:
        amplitudes = []
        for row in self.selected_transient_rows():
            if row >= len(self.transient_records):
                continue
            record = self.transient_records[row]
            if str(record.get("roi", "")) != roi_name:
                continue
            try:
                amplitude = float(record["amplitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(amplitude) and amplitude > 0:
                amplitudes.append(amplitude)

        if not amplitudes:
            return float("nan")
        return float(np.mean(amplitudes))

    def amp_ratio_for_roi(self, roi_name: str, amplitude: float) -> float:
        transient_amp = self.transient_amp_reference_for_roi(roi_name)
        if not np.isfinite(transient_amp) or transient_amp <= 0:
            return float("nan")
        return float(amplitude / transient_amp)

    def refresh_sr_calcium_amp_ratios(self) -> None:
        if not self.sr_calcium_records:
            return

        for record in self.sr_calcium_records:
            try:
                amplitude = float(record["amplitude"])
            except (KeyError, TypeError, ValueError):
                record["amp_ratio"] = float("nan")
                continue
            record["amp_ratio"] = self.amp_ratio_for_roi(
                str(record.get("roi", "")),
                amplitude,
            )

        self.populate_sr_calcium_table(self.sr_calcium_records)

    def render_selected_transients(self) -> None:
        self.clear_transient_plot_items()
        if self.transient_common_time.size == 0 or self.transient_snippets.size == 0:
            return

        selected_rows = self.selected_transient_rows()
        total_events = int(self.transient_snippets.shape[0])
        if not selected_rows:
            self.info_label.setText(
                f"No transients selected for average. 0/{total_events} events selected."
            )
            return

        selected_snippets = self.transient_snippets[selected_rows, :]
        counts = np.sum(np.isfinite(selected_snippets), axis=0)
        mean_trace = np.full(self.transient_common_time.shape, np.nan, dtype=float)
        valid_mean = counts > 0
        mean_trace[valid_mean] = np.nansum(selected_snippets, axis=0)[
            valid_mean
        ] / counts[valid_mean]

        event_pen = pg.mkPen("#FFFFFF30", width=1)
        for snippet in selected_snippets:
            curve = self.transient_average_plot.plot(
                self.transient_common_time,
                snippet,
                pen=event_pen,
            )
            curve.setZValue(5)
            self.transient_event_curves.append(curve)

        self.transient_average_curve = self.transient_average_plot.plot(
            self.transient_common_time,
            mean_trace,
            pen=pg.mkPen(GRAPH_FOREGROUND, width=3),
        )
        self.transient_average_curve.setZValue(10)

        self.transient_average_plot.setXRange(
            float(self.transient_common_time[0]),
            float(self.transient_common_time[-1]),
            padding=0,
        )
        self.set_plot_y_range(
            self.transient_average_plot,
            [mean_trace, *list(selected_snippets)],
        )

        status = (
            f"One average transient calculated from {len(selected_rows)}/"
            f"{total_events} selected events across {len(self.roi_traces)} ROI trace(s)."
        )
        if self.transient_status_suffix:
            status = f"{status} {self.transient_status_suffix}"
        self.info_label.setText(status)

    def build_transient_average(
        self,
    ) -> tuple[np.ndarray, np.ndarray, list[dict[str, object]]] | None:
        time_s = self.graph_time_s
        if time_s.size < 3:
            return None

        dt = self.estimate_sample_interval(time_s)
        pre_start_s = self.transient_pre_start_s()
        post_start_s = self.transient_pacing_interval_s()
        self.transient_window_note = None
        common_time = np.arange(-pre_start_s, post_start_s + dt * 0.5, dt)
        if common_time.size < 3:
            return None

        interval_start, interval_end = sorted(
            float(value) for value in self.transient_region.getRegion()
        )
        snippets: list[np.ndarray] = []
        records: list[dict[str, object]] = []

        for roi, trace in self.roi_traces.items():
            roi_name = self.roi_names.get(roi, "ROI")
            events = self.detect_transient_events(
                time_s,
                trace,
                interval_start,
                interval_end,
            )
            for event_number, event in enumerate(events, start=1):
                snippet = self.extract_transient_snippet(
                    time_s,
                    trace,
                    float(event["start_time_s"]),
                    common_time,
                )
                used = bool(np.isfinite(snippet).sum() >= max(3, int(common_time.size * 0.8)))
                if used:
                    f0 = self.transient_f0_from_snippet(
                        common_time,
                        snippet,
                        event.get("baseline", float("nan")),
                    )
                    normalized_snippet = self.normalize_trace_to_f_over_f0(snippet, f0)
                    if normalized_snippet is None:
                        continue

                    amplitude = float(event["amplitude"]) / f0
                    prominence = float(event["prominence"]) / f0
                    max_rise_rate = float(event["max_rise_rate"]) / f0
                    snippets.append(normalized_snippet)
                    records.append(
                        {
                            "roi": roi_name,
                            "event": event_number,
                            "start_time_s": float(event["start_time_s"]),
                            "peak_time_s": float(event["peak_time_s"]),
                            "amplitude": amplitude,
                            "prominence": prominence,
                            "max_rise_rate": max_rise_rate,
                            "f0": f0,
                            "baseline_raw": float(event["baseline"]),
                            "amplitude_raw": float(event["amplitude"]),
                            "max_rise_rate_raw": float(event["max_rise_rate"]),
                            "decay_absolute_times_s": event["decay_absolute_times_s"],
                            "decay_durations_s": event["decay_durations_s"],
                        }
                    )

        if not snippets:
            self.populate_transient_table(records)
            return None

        return common_time, np.vstack(snippets), records

    def detect_transient_events(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        interval_start: float,
        interval_end: float,
    ) -> list[dict[str, object]]:
        """Measure peaks that pass stable-baseline, recovery, and shape gates."""
        mask = (time_s >= interval_start) & (time_s <= interval_end)
        if int(mask.sum()) < 3:
            return []

        segment_time = time_s[mask]
        segment_trace = trace[mask]
        dt = self.estimate_sample_interval(segment_time)
        smooth_trace = self.smooth_trace(
            segment_trace,
            self.transient_smooth_s(),
            dt,
        )
        noise = self.baseline_noise(smooth_trace)
        min_prominence = max(
            self.transient_min_prominence_spinbox.value(),
            self.transient_prominence_noise_spinbox.value() * noise,
        )
        pacing_interval_points = max(
            1,
            int(round(max(self.transient_pacing_interval_s(), dt) / dt)),
        )
        peak_indices = self.find_prominent_peaks(
            smooth_trace,
            min_prominence,
            pacing_interval_points,
        )
        peak_indices = self.apply_recovery_gate(
            smooth_trace,
            peak_indices,
            pacing_interval_points,
            dt,
            noise,
        )

        events: list[dict[str, object]] = []
        for peak_index, _peak_prominence in peak_indices:
            start_index, baseline, amplitude = self.find_transient_start_index(
                smooth_trace,
                peak_index,
                pacing_interval_points,
                dt,
                noise,
            )
            # Re-evaluate prominence against the median of a stable baseline
            # interval before the rise, rather than the lowest single point
            # anywhere in the pacing window.
            if amplitude < min_prominence:
                continue
            peak_time_s = float(segment_time[peak_index])
            window_end_time_s = peak_time_s + self.transient_pacing_interval_s()
            if window_end_time_s > float(segment_time[-1]):
                continue
            window_end_index = int(
                np.searchsorted(segment_time, window_end_time_s, side="right") - 1
            )
            if window_end_index <= peak_index:
                continue
            max_rise_rate = self.max_increasing_speed(
                segment_time,
                smooth_trace,
                start_index,
                peak_index,
            )
            decay_absolute_times_s = [
                self.decay_crossing_time_s(
                    segment_time,
                    smooth_trace,
                    peak_index,
                    baseline,
                    amplitude,
                    percent,
                    window_end_index,
                )
                for percent in self.transient_table_decay_percents
            ]
            decay_durations_s = [
                absolute_time - peak_time_s
                if np.isfinite(float(absolute_time))
                else float("nan")
                for absolute_time in decay_absolute_times_s
            ]
            recovery_index = self.find_transient_recovery_index(
                smooth_trace,
                peak_index,
                baseline,
                amplitude,
                dt,
                window_end_index,
            )
            if not self.is_complete_transient_recovery(
                smooth_trace,
                recovery_index,
                baseline,
                amplitude,
                dt,
                window_end_index,
            ):
                continue
            if not self.has_transient_upstroke_shape(
                segment_time,
                start_index,
                peak_index,
                recovery_index,
            ):
                continue
            events.append(
                {
                    "start_time_s": float(segment_time[start_index]),
                    "peak_time_s": peak_time_s,
                    "recovery_time_s": float(segment_time[recovery_index]),
                    "amplitude": float(amplitude),
                    "prominence": float(amplitude),
                    "baseline": float(baseline),
                    "max_rise_rate": float(max_rise_rate),
                    "decay_absolute_times_s": decay_absolute_times_s,
                    "decay_durations_s": decay_durations_s,
                }
            )

        return events

    def smooth_trace(self, trace: np.ndarray, window_s: float, dt: float) -> np.ndarray:
        if window_s <= 0 or dt <= 0:
            return trace.astype(float, copy=True)

        window_points = max(1, int(round(window_s / dt)))
        if window_points <= 1:
            return trace.astype(float, copy=True)

        kernel = np.ones(window_points, dtype=float) / window_points
        left_pad = window_points // 2
        right_pad = window_points - 1 - left_pad
        padded_trace = np.pad(
            trace.astype(float, copy=False),
            (left_pad, right_pad),
            mode="edge",
        )
        return np.convolve(padded_trace, kernel, mode="valid")

    def robust_noise(self, trace: np.ndarray) -> float:
        finite = trace[np.isfinite(trace)]
        if finite.size == 0:
            return 0.0
        median = float(np.median(finite))
        mad = float(np.median(np.abs(finite - median)))
        if mad == 0:
            return float(np.std(finite))
        return mad / 0.6745

    def baseline_noise(self, trace: np.ndarray) -> float:
        finite = trace[np.isfinite(trace)]
        if finite.size == 0:
            return 0.0

        lower_half = finite[finite <= np.median(finite)]
        return self.robust_noise(lower_half if lower_half.size else finite)

    def find_prominent_peaks(
        self,
        trace: np.ndarray,
        min_prominence: float,
        min_distance_points: int,
    ) -> list[tuple[int, float]]:
        if trace.size < 3:
            return []

        candidate_indices = np.flatnonzero(
            (trace[1:-1] > trace[:-2]) & (trace[1:-1] >= trace[2:])
        ) + 1
        if candidate_indices.size == 0:
            return []

        window = max(min_distance_points, 1)
        candidates: list[tuple[int, float]] = []
        for index in candidate_indices:
            left = max(0, int(index) - window)
            right = min(trace.size, int(index) + window + 1)
            left_min = float(np.min(trace[left : int(index) + 1]))
            right_min = float(np.min(trace[int(index) : right]))
            prominence = float(trace[index] - max(left_min, right_min))
            if prominence >= min_prominence:
                candidates.append((int(index), prominence))

        candidates.sort(key=lambda item: item[1], reverse=True)
        selected: list[tuple[int, float]] = []
        for index, prominence in candidates:
            if all(abs(index - selected_index) >= min_distance_points for selected_index, _ in selected):
                selected.append((index, prominence))

        return sorted(selected, key=lambda item: item[0])

    def apply_recovery_gate(
        self,
        trace: np.ndarray,
        peak_indices: list[tuple[int, float]],
        min_distance_points: int,
        dt: float,
        baseline_noise: float,
    ) -> list[tuple[int, float]]:
        """Keep one candidate for each pacing/recovery window."""
        selected: list[tuple[int, float]] = []
        ignore_until_index = -1

        for peak_index, prominence in peak_indices:
            if peak_index <= ignore_until_index:
                continue

            _start_index, baseline, amplitude = self.find_transient_start_index(
                trace,
                peak_index,
                min_distance_points,
                dt,
                baseline_noise,
            )
            if amplitude <= 0:
                continue

            window_end_index = min(
                trace.size - 1,
                peak_index + self.transient_event_window_points(dt),
            )
            recovery_index = self.find_transient_recovery_index(
                trace,
                peak_index,
                baseline,
                amplitude,
                dt,
                window_end_index,
            )
            event_window_index = peak_index + self.transient_event_window_points(dt)
            event_block_index = min(
                recovery_index,
                peak_index + min_distance_points,
            )
            ignore_until_index = max(event_block_index, event_window_index)
            selected.append((peak_index, prominence))

        return selected

    def transient_event_window_points(self, dt: float) -> int:
        if dt <= 0:
            return 1
        return max(1, int(round(self.transient_pacing_interval_s() / dt)))

    def find_transient_start_index(
        self,
        trace: np.ndarray,
        peak_index: int,
        search_points: int,
        dt: float,
        baseline_noise: float,
    ) -> tuple[int, float, float]:
        left = max(0, peak_index - max(search_points, 1))
        baseline_region = self.stable_baseline_before_peak(
            trace,
            left,
            peak_index,
            dt,
            baseline_noise,
        )
        if baseline_region is None:
            # A peak at the beginning of the selected range, or one that rose
            # continuously from an earlier event, has no stable observed
            # baseline.  It cannot be measured as an independent transient.
            peak_value = float(trace[peak_index])
            return peak_index, peak_value, 0.0

        _baseline_start, baseline_end, baseline = baseline_region
        amplitude = float(trace[peak_index] - baseline)
        if amplitude <= 0:
            return baseline_end, baseline, amplitude

        threshold = baseline + self.transient_start_fraction_spinbox.value() * amplitude
        start_index = baseline_end
        for index in range(baseline_end + 1, peak_index + 1):
            if trace[index] >= threshold:
                start_index = index
                break

        return start_index, baseline, amplitude

    def stable_baseline_before_peak(
        self,
        trace: np.ndarray,
        left: int,
        peak_index: int,
        dt: float,
        baseline_noise: float,
    ) -> tuple[int, int, float] | None:
        """Find the most recent stable baseline interval before a peak.

        Baseline is a short, low-variation interval and its median is used as
        the reference level.  This avoids defining an event from one noisy
        trough sample, while keeping onset tied to the first 10% crossing of
        the event's own amplitude.
        """
        if dt <= 0:
            return None

        stable_points = max(3, int(round(self.transient_smooth_s() / dt)) + 1)
        first_end = max(int(left) + stable_points - 1, stable_points - 1)
        last_end = min(int(peak_index) - 1, trace.size - 1)
        if first_end > last_end:
            return None

        values = trace.astype(float, copy=False)
        scale = max(
            float(baseline_noise),
            np.finfo(float).eps * max(1.0, float(np.nanmax(np.abs(values)))),
        )
        for end_index in range(last_end, first_end - 1, -1):
            start_index = end_index - stable_points + 1
            baseline_values = values[start_index : end_index + 1]
            if not np.all(np.isfinite(baseline_values)):
                continue
            if self.robust_noise(baseline_values) > scale:
                continue
            baseline = float(np.median(baseline_values))
            local_amplitude = float(values[peak_index] - baseline)
            if local_amplitude <= 0:
                continue
            if np.ptp(baseline_values) > (
                self.transient_start_fraction_spinbox.value() * local_amplitude
            ):
                continue
            return (
                start_index,
                end_index,
                baseline,
            )

        return None

    def max_increasing_speed(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        start_index: int,
        peak_index: int,
    ) -> float:
        if peak_index <= start_index:
            return float("nan")

        rise_time = time_s[start_index : peak_index + 1]
        rise_trace = trace[start_index : peak_index + 1]
        dt = np.diff(rise_time)
        dy = np.diff(rise_trace)
        valid = np.isfinite(dt) & np.isfinite(dy) & (dt > 0)
        if not np.any(valid):
            return float("nan")
        return float(np.max(dy[valid] / dt[valid]))

    def fit_exponential_decay_from_peak(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        peak_time_s: float,
        fit_start_s: float,
        fit_end_s: float,
    ) -> tuple[float, np.ndarray, np.ndarray, float, float, float]:
        """Robustly fit A * exp(-t/tau) + C to an event tail."""
        empty = np.array([], dtype=float)
        failed = (float("nan"), empty, empty, float("nan"), float("nan"), float("nan"))
        if time_s.size < 4 or trace.size != time_s.size:
            return failed

        peak_index = int(np.argmin(np.abs(time_s - peak_time_s)))
        if peak_index >= time_s.size - 2:
            return failed

        dt = self.estimate_sample_interval(time_s)
        smooth_trace = self.smooth_trace(trace, self.transient_smooth_s(), dt)
        peak_value = float(max(smooth_trace[peak_index], trace[peak_index]))
        if not np.isfinite(peak_value) or peak_value <= 0:
            return failed

        tail_time = time_s[peak_index:]
        tail_trace = smooth_trace[peak_index:]
        relative_time = tail_time - float(time_s[peak_index])
        fit_start_s = max(0.0, float(fit_start_s))
        fit_end_s = max(fit_start_s + max(dt, 1e-12), float(fit_end_s))
        valid = (
            np.isfinite(relative_time)
            & np.isfinite(tail_trace)
            & (relative_time >= fit_start_s)
            & (relative_time <= fit_end_s)
            & (tail_trace <= peak_value * 1.2)
        )
        if int(valid.sum()) < 4:
            return failed

        fit_x = relative_time[valid]
        fit_y = tail_trace[valid]
        data_min = float(np.min(fit_y))
        data_max = float(np.max(fit_y))
        data_span = max(data_max - data_min, abs(peak_value), 1e-6)
        tail_count = max(3, int(round(fit_y.size * 0.25)))
        offset_guess = float(np.median(fit_y[-tail_count:]))
        amplitude_guess = max(peak_value - offset_guess, data_span * 0.5, 1e-6)
        fit_duration = max(float(fit_x[-1] - fit_x[0]), dt)
        tau_guess = max(fit_duration / 3.0, dt)
        noise_scale = self.robust_noise_scale(fit_y)

        def model(params: np.ndarray, x_values: np.ndarray) -> np.ndarray:
            amplitude, tau, offset = params
            return amplitude * np.exp(-x_values / tau) + offset

        def residuals(params: np.ndarray) -> np.ndarray:
            return model(params, fit_x) - fit_y

        lower_bounds = np.array(
            [
                0.0,
                max(dt * 0.25, 1e-6),
                data_min - data_span * 3.0,
            ],
            dtype=float,
        )
        upper_bounds = np.array(
            [
                max(amplitude_guess * 10.0, data_span * 10.0),
                max(fit_duration * 20.0, dt * 10.0, 1.0),
                data_max + data_span * 3.0,
            ],
            dtype=float,
        )
        initial = np.array([amplitude_guess, tau_guess, offset_guess], dtype=float)
        initial = np.minimum(np.maximum(initial, lower_bounds), upper_bounds)

        try:
            result = least_squares(
                residuals,
                initial,
                bounds=(lower_bounds, upper_bounds),
                loss="soft_l1",
                f_scale=max(noise_scale, data_span * 0.03, 1e-6),
                max_nfev=2000,
            )
        except ValueError:
            return failed

        amplitude, tau_s, offset = (float(value) for value in result.x)
        if (
            not result.success
            or not np.isfinite(amplitude)
            or not np.isfinite(tau_s)
            or not np.isfinite(offset)
            or amplitude <= 0
            or tau_s <= 0
        ):
            return failed

        fitted_y = model(result.x, fit_x)
        residual_y = fit_y - fitted_y
        fit_rmse = float(np.sqrt(np.mean(residual_y * residual_y)))
        ss_res = float(np.sum(residual_y * residual_y))
        ss_tot = float(np.sum((fit_y - float(np.mean(fit_y))) ** 2))
        fit_r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan")

        plot_mask = (relative_time >= fit_start_s) & (relative_time <= fit_end_s)
        fit_time = tail_time[plot_mask]
        fit_trace = model(result.x, relative_time[plot_mask])
        return float(tau_s), fit_time, fit_trace, offset, fit_r2, fit_rmse

    def robust_noise_scale(self, values: np.ndarray) -> float:
        if values.size < 3:
            return 1.0

        diffs = np.diff(values)
        median = float(np.median(diffs))
        mad = float(np.median(np.abs(diffs - median)))
        if mad > 0 and np.isfinite(mad):
            return mad * 1.4826

        std = float(np.std(values))
        if std > 0 and np.isfinite(std):
            return std
        return 1.0

    def decay_crossing_time_s(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        peak_index: int,
        baseline: float,
        amplitude: float,
        percent: int,
        window_end_index: int | None = None,
    ) -> float:
        """Return the linearly interpolated time of a decay-level crossing."""
        if amplitude <= 0 or peak_index >= trace.size - 1:
            return float("nan")

        target = baseline + (1.0 - percent / 100.0) * amplitude
        end_index = min(
            trace.size - 1,
            trace.size - 1 if window_end_index is None else window_end_index,
        )
        for index in range(peak_index + 1, end_index + 1):
            if trace[index] > target:
                continue

            previous_index = index - 1
            previous_value = float(trace[previous_index])
            current_value = float(trace[index])
            previous_time = float(time_s[previous_index])
            current_time = float(time_s[index])
            if current_value == previous_value:
                return current_time

            fraction = (target - previous_value) / (current_value - previous_value)
            fraction = min(max(fraction, 0.0), 1.0)
            crossing_time = previous_time + fraction * (current_time - previous_time)
            return float(crossing_time)

        return float("nan")

    def find_transient_recovery_index(
        self,
        trace: np.ndarray,
        peak_index: int,
        baseline: float,
        amplitude: float,
        dt: float,
        window_end_index: int | None = None,
    ) -> int:
        if amplitude <= 0 or peak_index >= trace.size - 1:
            return peak_index

        threshold = baseline + TRANSIENT_RECOVERY_FRACTION * amplitude
        end_index = min(
            trace.size - 1,
            trace.size - 1 if window_end_index is None else window_end_index,
        )
        recovery_index = end_index
        hold_points = max(1, int(round(TRANSIENT_RECOVERY_HOLD_S / max(dt, 1e-12))))
        for index in range(peak_index + 1, end_index + 1):
            right = min(end_index + 1, index + hold_points)
            if np.all(trace[index:right] <= threshold):
                recovery_index = index
                break

        tail_turn_index = self.find_secondary_rise_start_index(
            trace,
            peak_index,
            baseline,
            amplitude,
            dt,
            end_index,
        )
        if tail_turn_index is not None:
            recovery_index = min(recovery_index, tail_turn_index)

        return recovery_index

    def is_complete_transient_recovery(
        self,
        trace: np.ndarray,
        recovery_index: int,
        baseline: float,
        amplitude: float,
        dt: float,
        window_end_index: int,
    ) -> bool:
        """Require an observed, sustained return toward the local baseline.

        Merely having enough samples left in the pacing window is not a
        complete transient.  In particular, a slow ramp may end at a local
        maximum and previously passed the window check despite never
        recovering.  Use the existing recovery definition and hold duration;
        no additional user-facing time cutoff is introduced.
        """
        if amplitude <= 0 or recovery_index <= 0:
            return False

        hold_points = max(1, int(round(TRANSIENT_RECOVERY_HOLD_S / max(dt, 1e-12))))
        end_index = min(trace.size - 1, int(window_end_index))
        if recovery_index + hold_points > end_index + 1:
            return False

        threshold = baseline + TRANSIENT_RECOVERY_FRACTION * amplitude
        return bool(
            np.all(trace[recovery_index : recovery_index + hold_points] <= threshold)
        )

    def has_transient_upstroke_shape(
        self,
        time_s: np.ndarray,
        start_index: int,
        peak_index: int,
        recovery_index: int,
    ) -> bool:
        """Accept the fast-rise, slower-recovery shape of a Ca transient.

        This is intentionally a comparison within the same candidate rather
        than an absolute time-to-peak cutoff.  A gradual drift followed by a
        small peak can have enough amplitude and even return to baseline, but
        its rise lasts longer than its recovery.  It is not an independent
        calcium transient.  Genuine transients retain the characteristic
        rapid upstroke followed by a slower decay regardless of frame rate.
        """
        if not (0 <= start_index < peak_index < recovery_index < time_s.size):
            return False

        rise_duration_s = float(time_s[peak_index] - time_s[start_index])
        recovery_duration_s = float(time_s[recovery_index] - time_s[peak_index])
        return bool(
            np.isfinite(rise_duration_s)
            and np.isfinite(recovery_duration_s)
            and rise_duration_s > 0
            and recovery_duration_s > rise_duration_s
        )

    def find_secondary_rise_start_index(
        self,
        trace: np.ndarray,
        peak_index: int,
        baseline: float,
        amplitude: float,
        dt: float,
        window_end_index: int | None = None,
    ) -> int | None:
        if amplitude <= 0 or dt <= 0 or peak_index >= trace.size - 2:
            return None

        end_index = min(
            trace.size - 1,
            trace.size - 1 if window_end_index is None else window_end_index,
        )
        decay_level = baseline + TRANSIENT_TAIL_TURN_FRACTION * amplitude
        min_rise = TRANSIENT_SECONDARY_RISE_FRACTION * amplitude
        lookahead_points = max(
            2,
            int(round(TRANSIENT_SECONDARY_LOOKAHEAD_S / dt)),
        )

        for index in range(peak_index + 1, end_index):
            if trace[index] > decay_level:
                continue
            if trace[index] > trace[index - 1] or trace[index] > trace[index + 1]:
                continue

            right = min(end_index + 1, index + lookahead_points + 1)
            if right <= index + 1:
                continue
            if float(np.max(trace[index + 1 : right]) - trace[index]) >= min_rise:
                return index

        return None

    def extract_transient_snippet(
        self,
        time_s: np.ndarray,
        trace: np.ndarray,
        start_time_s: float,
        common_time: np.ndarray,
    ) -> np.ndarray:
        """Align a trace to onset and leave unobserved samples as NaN."""
        target_time = start_time_s + common_time
        snippet = np.full(common_time.shape, np.nan, dtype=float)
        valid = (target_time >= time_s[0]) & (target_time <= time_s[-1])
        if np.any(valid):
            snippet[valid] = np.interp(target_time[valid], time_s, trace)
        return snippet

    def estimate_sample_interval(self, time_s: np.ndarray) -> float:
        if time_s.size < 2:
            return 1.0
        diffs = np.diff(time_s)
        diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
        if diffs.size == 0:
            return 1.0
        return float(np.median(diffs))

    def populate_transient_table(
        self,
        records: list[dict[str, object]],
        used_rows: list[bool] | None = None,
    ) -> None:
        self.transient_table_updating = True
        self.set_transient_table_headers(self.transient_table_decay_percents)
        self.transient_table.setRowCount(len(records))
        for row, record in enumerate(records):
            use_item = QTableWidgetItem()
            use_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            checked = True if used_rows is None or row >= len(used_rows) else bool(used_rows[row])
            use_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.transient_table.setItem(row, 0, use_item)

            for column, value in enumerate(self.event_record_values(record)):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.transient_table.setItem(row, column + 1, item)
        self.transient_table.resizeColumnsToContents()
        self.transient_table_updating = False

    def populate_sr_calcium_table(self, records: list[dict[str, object]]) -> None:
        self.set_sr_calcium_table_headers(self.transient_table_decay_percents)
        self.sr_calcium_table.setRowCount(len(records))
        for row, record in enumerate(records):
            for column, value in enumerate(self.sr_calcium_record_values(record)):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.sr_calcium_table.setItem(row, column, item)
        self.sr_calcium_table.resizeColumnsToContents()

    def sr_calcium_record_values(self, record: dict[str, object]) -> list[str]:
        start_time_s = float(record["start_time_s"])
        peak_time_s = float(record["peak_time_s"])
        return [
            f"{record['roi']} #{record['event']}",
            f"{start_time_s:.6f}",
            f"{peak_time_s:.6f}",
            self.format_optional_float(
                self.seconds_to_ms(peak_time_s - start_time_s),
                ".3f",
            ),
            f"{float(record['amplitude']):.6g}",
            self.format_optional_float(
                record.get("amp_ratio", float("nan")),
                ".6g",
            ),
            self.format_optional_float(record["max_rise_rate"], ".6g"),
            self.format_optional_float(
                self.seconds_to_ms(float(record.get("tau_s", float("nan")))),
                ".3f",
            ),
            self.format_optional_float(record.get("fit_offset", float("nan")), ".6g"),
            self.format_optional_float(record.get("fit_r2", float("nan")), ".4f"),
            self.format_optional_float(record.get("fit_rmse", float("nan")), ".6g"),
        ]

    def event_record_values(self, record: dict[str, object]) -> list[str]:
        start_time_s = float(record["start_time_s"])
        peak_time_s = float(record["peak_time_s"])
        decay_absolute_times_s = record.get("decay_absolute_times_s", [])
        decay_durations_s = record.get("decay_durations_s", [])
        values = [
            f"{record['roi']} #{record['event']}",
            f"{start_time_s:.6f}",
            f"{peak_time_s:.6f}",
            self.format_optional_float(
                self.seconds_to_ms(peak_time_s - start_time_s),
                ".3f",
            ),
            f"{float(record['amplitude']):.6g}",
            self.format_optional_float(record["max_rise_rate"], ".6g"),
        ]
        for absolute_time in decay_absolute_times_s:
            values.append(self.format_optional_float(absolute_time, ".6f"))
        for duration in decay_durations_s:
            values.append(
                self.format_optional_float(self.seconds_to_ms(float(duration)), ".3f")
            )
        return values

    def format_optional_float(self, value: object, format_spec: str) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "NA"
        if not np.isfinite(number):
            return "NA"
        return format(number, format_spec)
