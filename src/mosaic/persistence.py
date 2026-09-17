"""Session persistence and spreadsheet/image export for MOSAIC."""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QTableWidgetItem,
)
from .constants import (
    BACKGROUND_ROI_SIZE,
    DISPLAY_LEVELS,
    GRAPH_FOREGROUND,
    PROJECT_ROOT,
    ROI_SIZE,
    TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES,
)


class PersistenceMixin:
    """Saves and restores ROI analysis sessions and export files."""

    def save_current_roi_analysis(self) -> None:
        if not self.rois:
            self.info_label.setText("Add an ROI before Save ROI.")
            return

        if not self.roi_traces:
            self.calculate_traces()
        if not self.roi_traces:
            self.info_label.setText("Calculate ROI traces before Save ROI.")
            return

        saved_now: list[dict[str, object]] = []
        for roi in list(self.rois):
            if roi not in self.roi_traces:
                continue

            self.saved_roi_counter += 1
            entry = self.build_saved_roi_entry(roi, self.saved_roi_counter)
            self.lock_saved_roi_entry(entry)
            saved_now.append(entry)

        if not saved_now:
            self.info_label.setText("No calculated ROI trace was available to save.")
            return

        self.saved_roi_entries.extend(saved_now)
        self.update_saved_decay_percents(saved_now)
        self.populate_saved_roi_table()
        self.clear_active_roi_workspace_after_save()
        self.info_label.setText(
            f"Saved {len(saved_now)} ROI(s). Add a new ROI for the next cell."
        )

    def build_saved_roi_entry(self, roi: pg.ROI, saved_id: int) -> dict[str, object]:
        roi_name = self.roi_names.get(roi, f"ROI {saved_id}")
        transient_summary, transient_time, transient_trace = (
            self.current_transient_average_for_roi(roi_name)
        )
        transient_records, transient_event_traces, transient_event_used = (
            self.current_transient_events_for_roi(roi_name)
        )
        caff_summary, caff_time, caff_trace, caff_fit_time, caff_fit_trace = (
            self.current_caff_result_for_roi(roi_name)
        )
        summary = {
            **transient_summary,
            **caff_summary,
        }
        saved_name = f"ROI {saved_id}"
        return {
            "id": saved_id,
            "name": saved_name,
            "source_name": roi_name,
            "enabled": True,
            "roi": roi,
            "roi_info": self.serialize_roi(roi),
            "label_item": None,
            "summary": summary,
            "raw_trace": self.roi_raw_traces.get(roi, np.array([], dtype=float)).copy(),
            "analysis_trace": self.roi_traces.get(roi, np.array([], dtype=float)).copy(),
            "photobleaching_corrected": self.photobleaching_corrected,
            "transient_time_s": transient_time,
            "transient_mean_trace": transient_trace,
            "transient_event_time_s": self.transient_common_time.copy()
            if transient_event_traces.size
            else np.array([], dtype=float),
            "transient_event_traces": transient_event_traces,
            "transient_event_records": transient_records,
            "transient_event_used": transient_event_used,
            "caff_trace_time_s": caff_time,
            "caff_trace": caff_trace,
            "caff_fit_time_s": caff_fit_time,
            "caff_fit_trace": caff_fit_trace,
        }

    def current_transient_average_for_roi(
        self,
        roi_name: str,
    ) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
        selected_records: list[dict[str, object]] = []
        selected_snippets: list[np.ndarray] = []
        for row in self.selected_transient_rows():
            if row >= len(self.transient_records):
                continue
            record = self.transient_records[row]
            if str(record.get("roi", "")) != roi_name:
                continue
            selected_records.append(record)
            if row < self.transient_snippets.shape[0]:
                selected_snippets.append(self.transient_snippets[row].copy())

        return self.summarize_transient_records(
            selected_records,
            selected_snippets,
            self.transient_common_time,
            list(self.transient_table_decay_percents),
        )

    def summarize_transient_records(
        self,
        selected_records: list[dict[str, object]],
        selected_snippets: list[np.ndarray],
        common_time: np.ndarray,
        decay_percents: list[int],
    ) -> tuple[dict[str, object], np.ndarray, np.ndarray]:
        if selected_snippets:
            stack = np.vstack(selected_snippets)
            counts = np.sum(np.isfinite(stack), axis=0)
            mean_trace = np.full(common_time.shape, np.nan, dtype=float)
            valid = counts > 0
            mean_trace[valid] = np.nansum(stack, axis=0)[valid] / counts[valid]
            output_time = common_time.copy()
        else:
            mean_trace = np.array([], dtype=float)
            output_time = np.array([], dtype=float)

        summary: dict[str, object] = {
            "transient_n": len(selected_records),
            "transient_amp": self.mean_record_value(selected_records, "amplitude"),
            "transient_peak_time_ms": self.mean_relative_time_ms(selected_records),
            "transient_max_dydt": self.mean_record_value(selected_records, "max_rise_rate"),
        }
        for index, percent in enumerate(decay_percents):
            values = []
            for record in selected_records:
                durations = record.get("decay_durations_s", [])
                if index >= len(durations):
                    continue
                try:
                    value = float(durations[index])
                except (TypeError, ValueError):
                    continue
                if np.isfinite(value):
                    values.append(self.seconds_to_ms(value))
            summary[f"transient_decay_{percent}_ms"] = (
                float(np.mean(values)) if values else float("nan")
            )

        return summary, output_time, mean_trace

    def current_transient_events_for_roi(
        self,
        roi_name: str,
    ) -> tuple[list[dict[str, object]], np.ndarray, list[bool]]:
        selected_rows = set(self.selected_transient_rows())
        records: list[dict[str, object]] = []
        snippets: list[np.ndarray] = []
        used_rows: list[bool] = []
        for row, record in enumerate(self.transient_records):
            if str(record.get("roi", "")) != roi_name:
                continue
            if row >= self.transient_snippets.shape[0]:
                continue
            records.append(dict(record))
            snippets.append(self.transient_snippets[row].copy())
            used_rows.append(row in selected_rows)

        if snippets:
            return records, np.vstack(snippets), used_rows
        return records, np.empty((0, 0), dtype=float), used_rows

    def current_caff_result_for_roi(
        self,
        roi_name: str,
    ) -> tuple[dict[str, object], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        record = next(
            (
                candidate
                for candidate in self.sr_calcium_records
                if str(candidate.get("roi", "")) == roi_name
            ),
            None,
        )
        if record is None:
            return (
                {
                    "caff_start_s": float("nan"),
                    "caff_peak_s": float("nan"),
                    "caff_amp": float("nan"),
                    "caff_amp_ratio": float("nan"),
                    "caff_peak_time_ms": float("nan"),
                    "caff_max_dydt": float("nan"),
                    "caff_tau_ms": float("nan"),
                    "caff_offset_c": float("nan"),
                    "caff_fit_r2": float("nan"),
                    "caff_fit_rmse": float("nan"),
                },
                np.array([], dtype=float),
                np.array([], dtype=float),
                np.array([], dtype=float),
                np.array([], dtype=float),
            )

        start_time_s = float(record["start_time_s"])
        peak_time_s = float(record["peak_time_s"])
        summary = {
            "caff_start_s": start_time_s,
            "caff_peak_s": peak_time_s,
            "caff_amp": float(record.get("amplitude", float("nan"))),
            "caff_amp_ratio": float(record.get("amp_ratio", float("nan"))),
            "caff_peak_time_ms": self.seconds_to_ms(peak_time_s - start_time_s),
            "caff_max_dydt": float(record.get("max_rise_rate", float("nan"))),
            "caff_tau_ms": self.seconds_to_ms(float(record.get("tau_s", float("nan")))),
            "caff_offset_c": float(record.get("fit_offset", float("nan"))),
            "caff_fit_r2": float(record.get("fit_r2", float("nan"))),
            "caff_fit_rmse": float(record.get("fit_rmse", float("nan"))),
        }
        return (
            summary,
            self.array_from_record(record, "trace_time_s"),
            self.array_from_record(record, "trace"),
            self.array_from_record(record, "fit_time_s"),
            self.array_from_record(record, "fit_trace"),
        )

    def array_from_record(self, record: dict[str, object], key: str) -> np.ndarray:
        value = record.get(key, np.array([], dtype=float))
        if isinstance(value, np.ndarray):
            return value.astype(float, copy=True)
        try:
            return np.array(value, dtype=float)
        except (TypeError, ValueError):
            return np.array([], dtype=float)

    def mean_record_value(
        self,
        records: list[dict[str, object]],
        key: str,
    ) -> float:
        values = []
        for record in records:
            try:
                value = float(record[key])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(value):
                values.append(value)
        return float(np.mean(values)) if values else float("nan")

    def mean_relative_time_ms(self, records: list[dict[str, object]]) -> float:
        values = []
        for record in records:
            try:
                start_time_s = float(record["start_time_s"])
                peak_time_s = float(record["peak_time_s"])
            except (KeyError, TypeError, ValueError):
                continue
            value = self.seconds_to_ms(peak_time_s - start_time_s)
            if np.isfinite(value):
                values.append(value)
        return float(np.mean(values)) if values else float("nan")

    def update_saved_decay_percents(self, entries: list[dict[str, object]]) -> None:
        changed = False
        for entry in entries:
            summary = entry.get("summary", {})
            if not isinstance(summary, dict):
                continue
            for key in summary:
                if not key.startswith("transient_decay_") or not key.endswith("_ms"):
                    continue
                try:
                    percent = int(key.removeprefix("transient_decay_").removesuffix("_ms"))
                except ValueError:
                    continue
                if percent not in self.saved_decay_percents:
                    self.saved_decay_percents.append(percent)
                    changed = True
        if changed:
            self.saved_decay_percents.sort()
            self.set_saved_roi_table_headers()

    def populate_saved_roi_table(self) -> None:
        self.saved_roi_table_updating = True
        self.set_saved_roi_table_headers()
        self.saved_roi_table.setRowCount(len(self.saved_roi_entries))
        for row, entry in enumerate(self.saved_roi_entries):
            use_item = QTableWidgetItem()
            use_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            use_item.setCheckState(
                Qt.Checked if bool(entry.get("enabled", True)) else Qt.Unchecked
            )
            self.saved_roi_table.setItem(row, 0, use_item)

            for column, value in enumerate(self.saved_roi_row_values(entry), start=1):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.saved_roi_table.setItem(row, column, item)
        self.saved_roi_table.resizeColumnsToContents()
        self.saved_roi_table_updating = False
        self.update_saved_roi_controls_enabled()

    def saved_roi_row_values(self, entry: dict[str, object]) -> list[str]:
        summary = entry.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        values = [
            str(entry.get("name", "")),
            str(summary.get("transient_n", 0)),
            self.format_optional_float(summary.get("transient_amp"), ".6g"),
            self.format_optional_float(summary.get("transient_peak_time_ms"), ".3f"),
            self.format_optional_float(summary.get("transient_max_dydt"), ".6g"),
        ]
        for percent in self.saved_decay_percents:
            values.append(
                self.format_optional_float(
                    summary.get(f"transient_decay_{percent}_ms"),
                    ".3f",
                )
            )
        return values

    def update_saved_roi_visibility_from_table(self, item: QTableWidgetItem) -> None:
        if self.saved_roi_table_updating or item.column() != 0:
            return
        row = item.row()
        if row >= len(self.saved_roi_entries):
            return

        enabled = item.checkState() == Qt.Checked
        entry = self.saved_roi_entries[row]
        entry["enabled"] = enabled
        self.set_saved_roi_visible(entry, enabled)

    def handle_saved_roi_row_selected(
        self,
        current_row: int,
        current_column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        if self.saved_roi_table_updating or self.saved_roi_selection_updating:
            return
        if current_row < 0 or current_row >= len(self.saved_roi_entries):
            return

        if self.rois:
            response = QMessageBox.question(
                self,
                "Clear current ROI?",
                "A current editable ROI is present.\n"
                "Clear it and show the selected saved ROI analysis?",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if response != QMessageBox.StandardButton.Ok:
                self.restore_saved_roi_table_selection(previous_row, previous_column)
                return
            self.clear_rois()

        self.current_saved_roi_row = current_row
        self.show_saved_roi_entry(self.saved_roi_entries[current_row])

    def restore_saved_roi_table_selection(self, row: int, column: int) -> None:
        self.saved_roi_selection_updating = True
        try:
            if 0 <= row < self.saved_roi_table.rowCount():
                self.saved_roi_table.setCurrentCell(row, max(column, 0))
                self.saved_roi_table.selectRow(row)
            else:
                self.saved_roi_table.clearSelection()
                self.saved_roi_table.setCurrentCell(-1, -1)
        finally:
            self.saved_roi_selection_updating = False

    def show_saved_roi_entry(self, entry: dict[str, object]) -> None:
        self.clear_all_analysis()
        self.render_saved_transient_entry(entry)
        self.info_label.setText(
            f"Showing saved {entry.get('name', 'ROI')} analysis."
        )

    def render_saved_transient_entry(self, entry: dict[str, object]) -> None:
        self.transient_table_decay_percents = list(self.saved_decay_percents)
        records = self.saved_transient_event_records(entry)
        traces = self.entry_matrix(entry, "transient_event_traces")
        time_values = self.entry_array(entry, "transient_event_time_s")
        if time_values.size == 0:
            time_values = self.entry_array(entry, "transient_time_s")

        event_count = min(len(records), traces.shape[0] if traces.ndim == 2 else 0)
        if event_count > 0 and time_values.size > 0:
            point_count = min(time_values.size, traces.shape[1])
            if point_count > 0:
                time_values = time_values[:point_count]
                traces = traces[:event_count, :point_count]
                records = records[:event_count]
                used_rows = self.saved_transient_event_used(entry, event_count)
                self.transient_common_time = time_values.copy()
                self.transient_snippets = traces.copy()
                self.transient_records = records
                self.populate_transient_table(records, used_rows)
                self.render_selected_transients()
                return

        self.render_saved_transient_average_only(entry)

    def render_saved_transient_average_only(self, entry: dict[str, object]) -> None:
        self.transient_table_updating = True
        self.set_transient_table_headers(self.transient_table_decay_percents)
        self.transient_table.setRowCount(1)

        use_item = QTableWidgetItem()
        use_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        use_item.setCheckState(Qt.Checked)
        self.transient_table.setItem(0, 0, use_item)
        for column, value in enumerate(self.saved_transient_row_values(entry), start=1):
            item = QTableWidgetItem(value)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.transient_table.setItem(0, column, item)
        self.transient_table.resizeColumnsToContents()
        self.transient_table_updating = False

        time_values = self.entry_array(entry, "transient_time_s")
        trace_values = self.entry_array(entry, "transient_mean_trace")
        if time_values.size == 0 or trace_values.size == 0:
            return

        count = min(time_values.size, trace_values.size)
        time_values = time_values[:count]
        trace_values = trace_values[:count]
        finite = np.isfinite(time_values) & np.isfinite(trace_values)
        if not np.any(finite):
            return

        self.transient_common_time = time_values.copy()
        self.transient_snippets = trace_values.reshape(1, -1)
        self.transient_records = []
        self.transient_average_curve = self.transient_average_plot.plot(
            time_values,
            trace_values,
            pen=pg.mkPen(GRAPH_FOREGROUND, width=3),
        )
        self.transient_average_curve.setZValue(10)

        finite_time = time_values[finite]
        if finite_time[-1] > finite_time[0]:
            self.transient_average_plot.setXRange(
                float(finite_time[0]),
                float(finite_time[-1]),
                padding=0,
            )
        self.set_plot_y_range(self.transient_average_plot, [trace_values])

    def saved_transient_event_records(self, entry: dict[str, object]) -> list[dict[str, object]]:
        records = entry.get("transient_event_records", [])
        if not isinstance(records, list):
            return []
        return [dict(record) for record in records if isinstance(record, dict)]

    def saved_transient_event_used(
        self,
        entry: dict[str, object],
        event_count: int,
    ) -> list[bool]:
        used_rows = entry.get("transient_event_used", [])
        if not isinstance(used_rows, list):
            return [True] * event_count
        return [
            bool(used_rows[index]) if index < len(used_rows) else True
            for index in range(event_count)
        ]

    def update_current_saved_roi_from_transient_selection(self) -> None:
        row = self.current_saved_roi_row
        if row is None or row < 0 or row >= len(self.saved_roi_entries):
            return

        entry = self.saved_roi_entries[row]
        selected_rows = set(self.selected_transient_rows())
        used_rows = [
            index in selected_rows
            for index in range(len(self.transient_records))
        ]
        selected_row_list = sorted(selected_rows)
        selected_records = [
            self.transient_records[index]
            for index in selected_row_list
            if index < len(self.transient_records)
        ]
        selected_snippets = [
            self.transient_snippets[index].copy()
            for index in selected_row_list
            if index < self.transient_snippets.shape[0]
        ]
        summary, common_time, mean_trace = self.summarize_transient_records(
            selected_records,
            selected_snippets,
            self.transient_common_time,
            list(self.transient_table_decay_percents),
        )

        saved_summary = self.saved_entry_summary(entry)
        saved_summary.update(summary)
        entry["summary"] = saved_summary
        entry["transient_time_s"] = common_time
        entry["transient_mean_trace"] = mean_trace
        entry["transient_event_time_s"] = self.transient_common_time.copy()
        entry["transient_event_traces"] = self.transient_snippets.copy()
        entry["transient_event_records"] = [
            dict(record) for record in self.transient_records
        ]
        entry["transient_event_used"] = used_rows
        self.refresh_saved_roi_table_row(row)

    def update_saved_caff_amp_ratio(self, entry: dict[str, object]) -> None:
        summary = self.saved_entry_summary(entry)
        caff_amp = self.optional_float(summary.get("caff_amp"))
        transient_amp = self.optional_float(summary.get("transient_amp"))
        summary["caff_amp_ratio"] = (
            caff_amp / transient_amp
            if np.isfinite(caff_amp) and np.isfinite(transient_amp) and transient_amp > 0
            else float("nan")
        )
        entry["summary"] = summary

    def refresh_saved_roi_table_row(self, row: int) -> None:
        if row < 0 or row >= len(self.saved_roi_entries):
            return
        self.saved_roi_table_updating = True
        try:
            for column, value in enumerate(
                self.saved_roi_row_values(self.saved_roi_entries[row]),
                start=1,
            ):
                item = self.saved_roi_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.saved_roi_table.setItem(row, column, item)
                item.setText(value)
            self.saved_roi_table.resizeColumnsToContents()
        finally:
            self.saved_roi_table_updating = False

    def saved_transient_row_values(self, entry: dict[str, object]) -> list[str]:
        summary = self.saved_entry_summary(entry)
        values = [
            f"{entry.get('name', 'ROI')} avg",
            "NA",
            "NA",
            self.format_optional_float(summary.get("transient_peak_time_ms"), ".3f"),
            self.format_optional_float(summary.get("transient_amp"), ".6g"),
            self.format_optional_float(summary.get("transient_max_dydt"), ".6g"),
        ]
        values.extend("NA" for _percent in self.saved_decay_percents)
        values.extend(
            self.format_optional_float(
                summary.get(f"transient_decay_{percent}_ms"),
                ".3f",
            )
            for percent in self.saved_decay_percents
        )
        return values

    def render_saved_sr_calcium_entry(self, entry: dict[str, object]) -> None:
        self.populate_saved_sr_calcium_table(entry)

        caff_time = self.entry_array(entry, "caff_trace_time_s")
        caff_trace = self.entry_array(entry, "caff_trace")
        segment_values: list[np.ndarray] = []
        if caff_time.size and caff_trace.size:
            count = min(caff_time.size, caff_trace.size)
            caff_time = caff_time[:count]
            caff_trace = caff_trace[:count]
            finite = np.isfinite(caff_time) & np.isfinite(caff_trace)
            if np.any(finite):
                curve = self.sr_calcium_event_plot.plot(
                    caff_time,
                    caff_trace,
                    pen=pg.mkPen("#FFFFFFCC", width=1),
                )
                curve.setZValue(10)
                self.sr_calcium_curves.append(curve)
                segment_values.append(caff_trace)
                finite_time = caff_time[finite]
                if finite_time[-1] > finite_time[0]:
                    self.sr_calcium_event_plot.setXRange(
                        float(finite_time[0]),
                        float(finite_time[-1]),
                        padding=0,
                    )

        fit_time = self.entry_array(entry, "caff_fit_time_s")
        fit_trace = self.entry_array(entry, "caff_fit_trace")
        if fit_time.size and fit_trace.size:
            count = min(fit_time.size, fit_trace.size)
            fit_time = fit_time[:count]
            fit_trace = fit_trace[:count]
            if np.any(np.isfinite(fit_time) & np.isfinite(fit_trace)):
                fit_curve = self.sr_calcium_event_plot.plot(
                    fit_time,
                    fit_trace,
                    pen=pg.mkPen("#FFD23F", width=4),
                )
                fit_curve.setZValue(20)
                self.sr_calcium_fit_curves.append(fit_curve)
                segment_values.append(fit_trace)

        summary = self.saved_entry_summary(entry)
        for key, pen in (
            ("caff_start_s", pg.mkPen("#FFFFFF80", width=1, style=Qt.DashLine)),
            ("caff_peak_s", pg.mkPen(GRAPH_FOREGROUND, width=1, style=Qt.DashLine)),
        ):
            value = self.optional_float(summary.get(key))
            if not np.isfinite(value):
                continue
            marker = pg.InfiniteLine(
                pos=value,
                angle=90,
                movable=False,
                pen=pen,
            )
            self.sr_calcium_event_plot.addItem(marker)
            self.sr_calcium_markers.append(marker)

        if segment_values:
            self.set_plot_y_range(self.sr_calcium_event_plot, segment_values)

    def populate_saved_sr_calcium_table(self, entry: dict[str, object]) -> None:
        self.set_sr_calcium_table_headers(self.transient_table_decay_percents)
        self.sr_calcium_table.setRowCount(1)
        for column, value in enumerate(self.saved_sr_calcium_row_values(entry)):
            item = self.sr_calcium_table.item(0, column)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.sr_calcium_table.setItem(0, column, item)
            item.setText(value)
        self.sr_calcium_table.resizeColumnsToContents()

    def saved_sr_calcium_row_values(self, entry: dict[str, object]) -> list[str]:
        summary = self.saved_entry_summary(entry)
        return [
            f"{entry.get('name', 'ROI')} #1",
            self.format_optional_float(summary.get("caff_start_s"), ".6f"),
            self.format_optional_float(summary.get("caff_peak_s"), ".6f"),
            self.format_optional_float(summary.get("caff_peak_time_ms"), ".3f"),
            self.format_optional_float(summary.get("caff_amp"), ".6g"),
            self.format_optional_float(summary.get("caff_amp_ratio"), ".6g"),
            self.format_optional_float(summary.get("caff_max_dydt"), ".6g"),
            self.format_optional_float(summary.get("caff_tau_ms"), ".3f"),
            self.format_optional_float(summary.get("caff_offset_c"), ".6g"),
            self.format_optional_float(summary.get("caff_fit_r2"), ".4f"),
            self.format_optional_float(summary.get("caff_fit_rmse"), ".6g"),
        ]

    def saved_entry_summary(self, entry: dict[str, object]) -> dict[str, object]:
        summary = entry.get("summary", {})
        return summary if isinstance(summary, dict) else {}

    def optional_float(self, value: object) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return float("nan")
        return number if np.isfinite(number) else float("nan")

    def set_saved_roi_visible(self, entry: dict[str, object], visible: bool) -> None:
        roi = entry.get("roi")
        if roi is not None and hasattr(roi, "setVisible"):
            roi.setVisible(visible)
        label_item = entry.get("label_item")
        if label_item is not None and hasattr(label_item, "setVisible"):
            label_item.setVisible(visible)

    def lock_saved_roi_entry(self, entry: dict[str, object]) -> None:
        roi = entry.get("roi")
        if roi is None:
            return

        self.lock_roi_item(roi)
        roi.setToolTip(str(entry.get("name", "Saved ROI")))
        label_item = self.create_saved_roi_label(entry)
        entry["label_item"] = label_item
        self.set_saved_roi_visible(entry, bool(entry.get("enabled", True)))

    def lock_roi_item(self, roi: pg.ROI) -> None:
        pen = pg.mkPen("#FFFFFF", width=2)
        roi.setPen(pen)
        if hasattr(roi, "setHoverPen"):
            roi.setHoverPen(pen)
        roi.setAcceptedMouseButtons(Qt.NoButton)
        if hasattr(roi, "translatable"):
            roi.translatable = False
        if hasattr(roi, "resizable"):
            roi.resizable = False
        if hasattr(roi, "rotatable"):
            roi.rotatable = False
        for handle in getattr(roi, "handles", []):
            item = handle.get("item")
            if item is not None:
                item.hide()

    def create_saved_roi_label(self, entry: dict[str, object]) -> pg.TextItem:
        center_x, center_y = self.roi_state_center(entry.get("roi_info", {}))
        label_item = pg.TextItem(
            text=str(entry.get("id", "")),
            color="#FFFFFF",
            anchor=(0.5, 0.5),
        )
        label_item.setFont(QFont("Arial", 14, QFont.Bold))
        label_item.setPos(center_x, center_y)
        label_item.setZValue(40)
        self.image_view.view.addItem(label_item)
        return label_item

    def clear_active_roi_workspace_after_save(self) -> None:
        self.rois = []
        self.roi_names = {}
        self.roi_pens = {}
        self.auto_roi_originals = {}
        self.clear_trace_curves()
        self.clear_all_analysis()
        self.roi_raw_traces = {}
        self.roi_traces = {}
        self.photobleaching_corrected = False
        self.detail_plot_has_data = False
        self.update_auto_roi_button_text()
        self.update_photobleaching_controls_enabled()
        self.update_saved_roi_controls_enabled()
        self.update_roi_status()

    def clear_saved_roi_entries(self) -> None:
        for entry in self.saved_roi_entries:
            roi = entry.get("roi")
            if roi is not None:
                try:
                    self.image_view.view.removeItem(roi)
                except ValueError:
                    pass
            label_item = entry.get("label_item")
            if label_item is not None:
                try:
                    self.image_view.view.removeItem(label_item)
                except ValueError:
                    pass
        self.saved_roi_entries = []
        self.saved_roi_counter = 0
        self.current_saved_roi_row = None
        self.saved_decay_percents = list(TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES)
        self.set_saved_roi_table_headers()
        self.saved_roi_table.setRowCount(0)
        self.update_saved_roi_controls_enabled()

    def serialize_roi(self, roi: pg.ROI | None) -> dict[str, object] | None:
        if roi is None:
            return None
        if isinstance(roi, pg.PolyLineROI):
            roi_type = "polygon"
        elif isinstance(roi, pg.RectROI):
            roi_type = "rectangle"
        else:
            roi_type = "ellipse"
        return {
            "type": roi_type,
            "state": self.json_safe_value(roi.saveState()),
        }

    def create_roi_from_info(self, roi_info: dict[str, object]) -> pg.ROI | None:
        """Restore ROI geometry; saved polygon points are local to saved position."""
        if self.image_shape is None:
            return None

        state = roi_info.get("state", {})
        if not isinstance(state, dict):
            return None

        roi_type = roi_info.get("type", "ellipse")
        pen = pg.mkPen("#FFFFFF", width=2)
        if roi_type == "polygon":
            points = [
                (float(point[0]), float(point[1]))
                for point in state.get("points", [])
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]
            if len(points) < 3:
                return None
            roi = pg.PolyLineROI(
                points,
                closed=bool(state.get("closed", True)),
                pen=pen,
                movable=False,
                removable=False,
            )
            pos = state.get("pos", (0.0, 0.0))
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                roi.setPos(float(pos[0]), float(pos[1]))
            return roi

        pos = state.get("pos", (0.0, 0.0))
        size = state.get("size", ROI_SIZE)
        if not (
            isinstance(pos, (list, tuple))
            and len(pos) >= 2
            and isinstance(size, (list, tuple))
            and len(size) >= 2
        ):
            return None

        roi_class = pg.RectROI if roi_type == "rectangle" else pg.EllipseROI
        roi = roi_class(
            (float(pos[0]), float(pos[1])),
            (float(size[0]), float(size[1])),
            pen=pen,
            hoverPen=pen,
            movable=False,
            rotatable=False,
            resizable=False,
            removable=False,
        )
        try:
            roi.setAngle(float(state.get("angle", 0.0)))
        except (TypeError, ValueError):
            pass
        return roi

    def roi_state_center(self, roi_info: object) -> tuple[float, float]:
        if not isinstance(roi_info, dict):
            return 0.0, 0.0
        state = roi_info.get("state", {})
        if not isinstance(state, dict):
            return 0.0, 0.0

        if roi_info.get("type") == "polygon":
            try:
                points = np.array(state.get("points", []), dtype=float)
            except (TypeError, ValueError):
                points = np.empty((0, 2), dtype=float)
            if points.ndim == 2 and points.shape[0] > 0 and points.shape[1] >= 2:
                try:
                    pos = np.array(state.get("pos", [0.0, 0.0]), dtype=float)
                except (TypeError, ValueError):
                    pos = np.array([0.0, 0.0], dtype=float)
                if pos.size >= 2:
                    points[:, 0] += pos[0]
                    points[:, 1] += pos[1]
                return float(np.mean(points[:, 0])), float(np.mean(points[:, 1]))

        pos = state.get("pos", (0.0, 0.0))
        size = state.get("size", (0.0, 0.0))
        if (
            isinstance(pos, (list, tuple))
            and len(pos) >= 2
            and isinstance(size, (list, tuple))
            and len(size) >= 2
        ):
            return (
                float(pos[0]) + float(size[0]) / 2.0,
                float(pos[1]) + float(size[1]) / 2.0,
            )
        return 0.0, 0.0

    def json_safe_value(self, value: object) -> object:
        """Convert NumPy values to JSON-safe data, mapping NaN and infinity to null."""
        if isinstance(value, np.ndarray):
            return [self.json_safe_value(item) for item in value.tolist()]
        if isinstance(value, np.generic):
            return self.json_safe_value(value.item())
        if isinstance(value, dict):
            return {str(key): self.json_safe_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.json_safe_value(item) for item in value]
        if isinstance(value, float):
            return value if np.isfinite(value) else None
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)

    def json_array(self, array: object) -> list[float | None]:
        if not isinstance(array, np.ndarray):
            try:
                array = np.array(array, dtype=float)
            except (TypeError, ValueError):
                return []
        return [
            float(value) if np.isfinite(float(value)) else None
            for value in np.ravel(array)
        ]

    def json_matrix(self, array: object) -> list[list[float | None]]:
        if not isinstance(array, np.ndarray):
            try:
                array = np.array(array, dtype=float)
            except (TypeError, ValueError):
                return []
        array = np.asarray(array, dtype=float)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2:
            return []
        return [
            [
                float(value) if np.isfinite(float(value)) else None
                for value in row
            ]
            for row in array
        ]

    def array_from_json(self, values: object) -> np.ndarray:
        if not isinstance(values, list):
            return np.array([], dtype=float)
        parsed = [
            float(value) if value is not None else np.nan
            for value in values
        ]
        return np.array(parsed, dtype=float)

    def matrix_from_json(self, values: object) -> np.ndarray:
        if not isinstance(values, list):
            return np.empty((0, 0), dtype=float)
        rows: list[list[float]] = []
        for row in values:
            if not isinstance(row, list):
                continue
            parsed_row = [
                float(value) if value is not None else np.nan
                for value in row
            ]
            rows.append(parsed_row)
        if not rows:
            return np.empty((0, 0), dtype=float)

        width = max(len(row) for row in rows)
        matrix = np.full((len(rows), width), np.nan, dtype=float)
        for row_index, row in enumerate(rows):
            matrix[row_index, : len(row)] = row
        return matrix

    def record_list_from_json(self, values: object) -> list[dict[str, object]]:
        if not isinstance(values, list):
            return []
        return [dict(item) for item in values if isinstance(item, dict)]

    def bool_list_from_json(self, values: object) -> list[bool]:
        if not isinstance(values, list):
            return []
        return [bool(value) for value in values]

    def checked_saved_roi_entries(self) -> list[dict[str, object]]:
        return [
            entry
            for entry in self.saved_roi_entries
            if bool(entry.get("enabled", True))
        ]

    def save_analysis_outputs(self) -> None:
        if self.current_path is None:
            self.info_label.setText("Open an ND2 file before Save.")
            return
        if not self.saved_roi_entries:
            self.info_label.setText("Save at least one ROI before exporting.")
            return

        output_dir = self.current_path.parent / f"{self.current_path.stem}_ana"
        output_dir.mkdir(parents=True, exist_ok=True)
        checked_entries = self.checked_saved_roi_entries()

        self.write_xlsx(
            output_dir / "analysis.xlsx",
            self.analysis_xlsx_rows(checked_entries),
            "analysis",
        )
        self.write_xlsx(
            output_dir / "rawtrace.xlsx",
            self.raw_trace_xlsx_rows(checked_entries),
            "rawtrace",
        )
        self.write_xlsx(
            output_dir / "transient.xlsx",
            self.paired_trace_xlsx_rows(
                checked_entries,
                "transient_time_s",
                "transient_mean_trace",
                "transient",
            ),
            "transient",
        )
        self.save_roi_overlay_image(output_dir / "ROI.jpg", checked_entries)
        self.save_session_info(output_dir / "analysis_info.json")
        self.info_label.setText(
            f"Saved {len(checked_entries)} checked ROI(s) to {output_dir}."
        )

    def analysis_xlsx_rows(self, entries: list[dict[str, object]]) -> list[list[object]]:
        headers = self.saved_roi_headers_without_use()
        return [headers, *[self.saved_roi_row_values(entry) for entry in entries]]

    def raw_trace_xlsx_rows(self, entries: list[dict[str, object]]) -> list[list[object]]:
        headers = ["Time s", *[str(entry.get("name", "")) for entry in entries]]
        traces = [self.entry_array(entry, "raw_trace") for entry in entries]
        max_len = max(
            [self.graph_time_s.size, *[trace.size for trace in traces]],
            default=0,
        )
        rows: list[list[object]] = [headers]
        for index in range(max_len):
            row: list[object] = [
                float(self.graph_time_s[index])
                if index < self.graph_time_s.size
                else None
            ]
            for trace in traces:
                row.append(float(trace[index]) if index < trace.size else None)
            rows.append(row)
        return rows

    def paired_trace_xlsx_rows(
        self,
        entries: list[dict[str, object]],
        time_key: str,
        trace_key: str,
        label: str,
    ) -> list[list[object]]:
        series = []
        headers: list[object] = []
        for entry in entries:
            time_values = self.entry_array(entry, time_key)
            trace_values = self.entry_array(entry, trace_key)
            if time_values.size == 0 or trace_values.size == 0:
                continue
            name = str(entry.get("name", "ROI"))
            headers.extend([f"{name} {label} time s", f"{name} {label} F/F0"])
            series.append((time_values, trace_values))

        max_len = max(
            [max(time_values.size, trace_values.size) for time_values, trace_values in series],
            default=0,
        )
        rows: list[list[object]] = [headers]
        for index in range(max_len):
            row: list[object] = []
            for time_values, trace_values in series:
                row.append(float(time_values[index]) if index < time_values.size else None)
                row.append(float(trace_values[index]) if index < trace_values.size else None)
            rows.append(row)
        return rows

    def caff_trace_xlsx_rows(self, entries: list[dict[str, object]]) -> list[list[object]]:
        series = []
        headers: list[object] = []
        for entry in entries:
            caff_time = self.entry_array(entry, "caff_trace_time_s")
            caff_trace = self.entry_array(entry, "caff_trace")
            fit_time = self.entry_array(entry, "caff_fit_time_s")
            fit_trace = self.entry_array(entry, "caff_fit_trace")
            if caff_time.size == 0 or caff_trace.size == 0:
                continue
            name = str(entry.get("name", "ROI"))
            headers.extend(
                [
                    f"{name} Caff time s",
                    f"{name} Caff F/F0",
                    f"{name} fit time s",
                    f"{name} fit F/F0",
                ]
            )
            series.append((caff_time, caff_trace, fit_time, fit_trace))

        max_len = max(
            [
                max(
                    caff_time.size,
                    caff_trace.size,
                    fit_time.size,
                    fit_trace.size,
                )
                for caff_time, caff_trace, fit_time, fit_trace in series
            ],
            default=0,
        )
        rows: list[list[object]] = [headers]
        for index in range(max_len):
            row: list[object] = []
            for caff_time, caff_trace, fit_time, fit_trace in series:
                row.extend(
                    [
                        float(caff_time[index]) if index < caff_time.size else None,
                        float(caff_trace[index]) if index < caff_trace.size else None,
                        float(fit_time[index]) if index < fit_time.size else None,
                        float(fit_trace[index]) if index < fit_trace.size else None,
                    ]
                )
            rows.append(row)
        return rows

    def entry_array(self, entry: dict[str, object], key: str) -> np.ndarray:
        value = entry.get(key, np.array([], dtype=float))
        if isinstance(value, np.ndarray):
            return value.astype(float, copy=False)
        try:
            return np.array(value, dtype=float)
        except (TypeError, ValueError):
            return np.array([], dtype=float)

    def entry_matrix(self, entry: dict[str, object], key: str) -> np.ndarray:
        value = entry.get(key, np.empty((0, 0), dtype=float))
        if isinstance(value, np.ndarray):
            matrix = value.astype(float, copy=False)
        else:
            try:
                matrix = np.array(value, dtype=float)
            except (TypeError, ValueError):
                return np.empty((0, 0), dtype=float)
        if matrix.ndim == 1 and matrix.size:
            return matrix.reshape(1, -1)
        if matrix.ndim != 2:
            return np.empty((0, 0), dtype=float)
        return matrix

    def write_xlsx(
        self,
        path: Path,
        rows: list[list[object]],
        sheet_name: str,
    ) -> None:
        """Write a minimal single-sheet XLSX package without an Excel dependency."""
        sheet_xml = self.xlsx_sheet_xml(rows)
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
            '</workbook>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
            workbook.writestr("[Content_Types].xml", content_types)
            workbook.writestr("_rels/.rels", root_rels)
            workbook.writestr("xl/workbook.xml", workbook_xml)
            workbook.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)

    def xlsx_sheet_xml(self, rows: list[list[object]]) -> str:
        row_xml_parts = []
        for row_index, row_values in enumerate(rows, start=1):
            cell_parts = []
            for column_index, value in enumerate(row_values, start=1):
                cell_xml = self.xlsx_cell_xml(row_index, column_index, value)
                if cell_xml:
                    cell_parts.append(cell_xml)
            row_xml_parts.append(f'<row r="{row_index}">{"".join(cell_parts)}</row>')
        sheet_data = "".join(row_xml_parts)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{sheet_data}</sheetData>"
            "</worksheet>"
        )

    def xlsx_cell_xml(
        self,
        row_index: int,
        column_index: int,
        value: object,
    ) -> str:
        if value is None:
            return ""
        cell_ref = f"{self.xlsx_column_name(column_index)}{row_index}"
        if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
            number = float(value)
            if not np.isfinite(number):
                return ""
            return f'<c r="{cell_ref}"><v>{number:.12g}</v></c>'
        text = escape(str(value))
        return f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    def xlsx_column_name(self, column_index: int) -> str:
        name = ""
        while column_index > 0:
            column_index, remainder = divmod(column_index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def save_roi_overlay_image(
        self,
        path: Path,
        entries: list[dict[str, object]],
    ) -> None:
        if self.reader is None:
            return

        frame = self.get_frame(0)
        if frame.ndim > 2:
            frame = frame[..., 0]
        low, high = DISPLAY_LEVELS
        scaled = np.clip(
            (frame.astype(float) - low) / max(high - low, 1) * 255.0,
            0,
            255,
        )
        image_data = np.ascontiguousarray(scaled.astype(np.uint8))
        height, width = image_data.shape
        image = QImage(
            image_data.data,
            width,
            height,
            width,
            QImage.Format_Grayscale8,
        ).copy().convertToFormat(QImage.Format_RGB888)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setFont(QFont("Arial", 18, QFont.Bold))
        for entry in entries:
            self.draw_saved_roi_on_painter(painter, entry)
        painter.end()
        image.save(str(path), "JPG", 95)

    def draw_saved_roi_on_painter(
        self,
        painter: QPainter,
        entry: dict[str, object],
    ) -> None:
        roi_info = entry.get("roi_info", {})
        if not isinstance(roi_info, dict):
            return
        state = roi_info.get("state", {})
        if not isinstance(state, dict):
            return

        if roi_info.get("type") == "polygon":
            points = []
            pos = state.get("pos", [0.0, 0.0])
            pos_x = float(pos[0]) if isinstance(pos, list) and len(pos) >= 2 else 0.0
            pos_y = float(pos[1]) if isinstance(pos, list) and len(pos) >= 2 else 0.0
            for point in state.get("points", []):
                if isinstance(point, list) and len(point) >= 2:
                    points.append(
                        QPointF(float(point[0]) + pos_x, float(point[1]) + pos_y)
                    )
            if points:
                painter.drawPolygon(QPolygonF(points))
            center_x, center_y = self.roi_state_center(roi_info)
        else:
            pos = state.get("pos", [0.0, 0.0])
            size = state.get("size", [0.0, 0.0])
            if not (
                isinstance(pos, list)
                and len(pos) >= 2
                and isinstance(size, list)
                and len(size) >= 2
            ):
                return
            x, y = float(pos[0]), float(pos[1])
            width, height = float(size[0]), float(size[1])
            center_x, center_y = x + width / 2.0, y + height / 2.0
            painter.save()
            painter.translate(center_x, center_y)
            painter.rotate(float(state.get("angle", 0.0) or 0.0))
            shape_rect = QRectF(-width / 2.0, -height / 2.0, width, height)
            if roi_info.get("type") == "rectangle":
                painter.drawRect(shape_rect)
            else:
                painter.drawEllipse(shape_rect)
            painter.restore()

        painter.drawText(
            QPointF(center_x + 4.0, center_y - 4.0),
            str(entry.get("id", "")),
        )

    def save_session_info(self, path: Path) -> None:
        data = {
            "version": 1,
            "movie_path": str(self.current_path) if self.current_path is not None else "",
            "saved_decay_percents": self.saved_decay_percents,
            "background_roi": self.serialize_roi(self.background_roi),
            "saved_roi_counter": self.saved_roi_counter,
            "entries": [
                self.serialized_saved_entry(entry)
                for entry in self.saved_roi_entries
            ],
        }
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def serialized_saved_entry(self, entry: dict[str, object]) -> dict[str, object]:
        """Preserve the analysis_info JSON schema for backward-compatible loading."""
        return {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "source_name": entry.get("source_name"),
            "enabled": bool(entry.get("enabled", True)),
            "roi_info": entry.get("roi_info"),
            "summary": self.json_safe_value(entry.get("summary", {})),
            "raw_trace": self.json_array(entry.get("raw_trace")),
            "analysis_trace": self.json_array(entry.get("analysis_trace")),
            "photobleaching_corrected": bool(entry.get("photobleaching_corrected", False)),
            "transient_time_s": self.json_array(entry.get("transient_time_s")),
            "transient_mean_trace": self.json_array(entry.get("transient_mean_trace")),
            "transient_event_time_s": self.json_array(entry.get("transient_event_time_s")),
            "transient_event_traces": self.json_matrix(entry.get("transient_event_traces")),
            "transient_event_records": self.json_safe_value(
                entry.get("transient_event_records", [])
            ),
            "transient_event_used": self.json_safe_value(
                entry.get("transient_event_used", [])
            ),
            "caff_trace_time_s": self.json_array(entry.get("caff_trace_time_s")),
            "caff_trace": self.json_array(entry.get("caff_trace")),
            "caff_fit_time_s": self.json_array(entry.get("caff_fit_time_s")),
            "caff_fit_trace": self.json_array(entry.get("caff_fit_trace")),
        }

    def load_analysis_info_dialog(self) -> None:
        initial_directory = (
            self.last_open_directory
            if self.last_open_directory.is_dir()
            else PROJECT_ROOT
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load analysis info",
            str(initial_directory),
            "Analysis info (*.json);;All files (*)",
        )
        if path:
            self.load_analysis_info(Path(path))

    def load_analysis_info(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.info_label.setText(f"Could not load info file: {exc}")
            return

        movie_path = Path(str(data.get("movie_path", "")))
        if not movie_path.exists():
            self.info_label.setText(f"Movie file not found: {movie_path}")
            return

        self.load_nd2(movie_path)
        self.restore_background_roi_from_info(data.get("background_roi"))
        self.saved_decay_percents = [
            int(value)
            for value in data.get("saved_decay_percents", TRANSIENT_DEFAULT_DECAY_PERCENT_VALUES)
        ]
        self.saved_roi_counter = int(data.get("saved_roi_counter", 0) or 0)

        restored_entries: list[dict[str, object]] = []
        for entry_data in data.get("entries", []):
            if not isinstance(entry_data, dict):
                continue
            roi_info = entry_data.get("roi_info")
            if not isinstance(roi_info, dict):
                continue
            roi = self.create_roi_from_info(roi_info)
            if roi is None:
                continue
            self.image_view.view.addItem(roi)
            entry = {
                "id": int(entry_data.get("id", len(restored_entries) + 1) or 0),
                "name": str(entry_data.get("name", f"ROI {len(restored_entries) + 1}")),
                "source_name": str(entry_data.get("source_name", "")),
                "enabled": bool(entry_data.get("enabled", True)),
                "roi": roi,
                "roi_info": roi_info,
                "label_item": None,
                "summary": entry_data.get("summary", {}),
                "raw_trace": self.array_from_json(entry_data.get("raw_trace")),
                "analysis_trace": self.array_from_json(entry_data.get("analysis_trace")),
                "photobleaching_corrected": bool(entry_data.get("photobleaching_corrected", False)),
                "transient_time_s": self.array_from_json(entry_data.get("transient_time_s")),
                "transient_mean_trace": self.array_from_json(entry_data.get("transient_mean_trace")),
                "transient_event_time_s": self.array_from_json(
                    entry_data.get("transient_event_time_s")
                ),
                "transient_event_traces": self.matrix_from_json(
                    entry_data.get("transient_event_traces")
                ),
                "transient_event_records": self.record_list_from_json(
                    entry_data.get("transient_event_records")
                ),
                "transient_event_used": self.bool_list_from_json(
                    entry_data.get("transient_event_used")
                ),
                "caff_trace_time_s": self.array_from_json(entry_data.get("caff_trace_time_s")),
                "caff_trace": self.array_from_json(entry_data.get("caff_trace")),
                "caff_fit_time_s": self.array_from_json(entry_data.get("caff_fit_time_s")),
                "caff_fit_trace": self.array_from_json(entry_data.get("caff_fit_trace")),
            }
            self.lock_saved_roi_entry(entry)
            restored_entries.append(entry)

        self.saved_roi_entries = restored_entries
        if restored_entries:
            self.saved_roi_counter = max(
                self.saved_roi_counter,
                max(int(entry.get("id", 0) or 0) for entry in restored_entries),
            )
        self.populate_saved_roi_table()
        self.clear_active_roi_workspace_after_save()
        self.info_label.setText(
            f"Loaded {len(restored_entries)} saved ROI(s) from {path.name}."
        )

    def restore_background_roi_from_info(self, roi_info: object) -> None:
        if not isinstance(roi_info, dict) or self.image_shape is None:
            return
        state = roi_info.get("state", {})
        if not isinstance(state, dict):
            return
        pos = state.get("pos", (0.0, 0.0))
        size = state.get("size", BACKGROUND_ROI_SIZE)
        if not (
            isinstance(pos, (list, tuple))
            and len(pos) >= 2
            and isinstance(size, (list, tuple))
            and len(size) >= 2
        ):
            return
        if self.background_roi is not None:
            self.image_view.view.removeItem(self.background_roi)
        roi = pg.EllipseROI(
            (float(pos[0]), float(pos[1])),
            (float(size[0]), float(size[1])),
            pen=pg.mkPen("#4DB6FF", width=2),
            hoverPen=pg.mkPen("#A6DDFF", width=3),
            movable=True,
            rotatable=True,
            resizable=True,
            removable=False,
        )
        try:
            roi.setAngle(float(state.get("angle", 0.0)))
        except (TypeError, ValueError):
            pass
        roi.setToolTip("Background ROI")
        self.image_view.view.addItem(roi)
        self.background_roi = roi
        self.background_trace = None
