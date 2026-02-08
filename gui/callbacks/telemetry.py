"""
Telemetry Callbacks Module
===========================

Handles all Dash callbacks for the Telemetry 2.0 summarization tab.

On "Run" click:
1. Finds the telemetry2_0.txt file in merged_logs.
2. Parses all cJSON Report entries using the new parser (tid-based or legacy).
3. Extracts summary info (device identity, report stats).
4. Extracts YAML-configured field groups with time-series data.
5. Builds device info card, report summary card, status labels, and Plotly charts.
"""

import os
import glob
import logging
import dash
import pandas as pd
from pathlib import Path
from typing import Optional
from dash import dcc, html, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objs as go

logger = logging.getLogger(__name__)
from gui.file_manager import FileManager
from logai.telemetry_parser import (
    parse_telemetry_file,
    extract_configured_fields,
    load_report_field_config,
)
from logai.utils.constants import MERGED_LOGS_DIR_NAME, UPLOAD_DIRECTORY

# Groups whose fields should appear as status labels instead of tables/charts
_STATUS_LABEL_GROUPS = {"WiFi Radio", "WiFi SSID"}

# Groups whose charts should be excluded (device info is shown as card already)
_SKIP_CHART_GROUPS = {"WiFi Radio", "WiFi SSID", "Device Info"}


def _auto_scale_unit(values: list, unit: str):
    """
    Auto-scale numeric values to a more readable unit.

    Converts large KB values to MB/GB, large B values to KB/MB, and
    large second values to minutes/hours for chart readability.

    Args:
        values: List of numeric values.
        unit: Original unit string (e.g. "KB", "B", "sec").

    Returns:
        Tuple of (scaled_values, new_unit_string).
    """
    if not values or not unit:
        return values, unit

    unit_lower = unit.strip().lower()
    max_val = max(abs(v) for v in values) if values else 0

    if unit_lower == "kb":
        if max_val >= 1_000_000:
            return [round(v / (1024 * 1024), 2) for v in values], "GB"
        elif max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "MB"
    elif unit_lower == "b":
        if max_val >= 1_000_000_000:
            return [round(v / (1024 * 1024 * 1024), 2) for v in values], "GB"
        elif max_val >= 1_000_000:
            return [round(v / (1024 * 1024), 2) for v in values], "MB"
        elif max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "KB"
    elif unit_lower in ("sec", "s"):
        if max_val >= 86400:
            return [round(v / 86400, 2) for v in values], "days"
        elif max_val >= 3600:
            return [round(v / 3600, 2) for v in values], "hours"
        elif max_val >= 120:
            return [round(v / 60, 2) for v in values], "min"
    elif unit_lower == "kbps":
        if max_val >= 1024:
            return [round(v / 1024, 2) for v in values], "Mbps"

    return values, unit


# ---------------------------------------------------------------------------
# Helper: Build device info card content
# ---------------------------------------------------------------------------

def _build_device_info_card(summary: dict) -> html.Div:
    """
    Build the Device Info card body from telemetry summary.

    Includes WAN type, SDK version, and SW upgrade detection.

    Args:
        summary: Output from extract_telemetry_summary().

    Returns:
        Dash HTML Div with device details.
    """
    dev = summary.get("device_info", {})
    items = []
    info_fields = [
        ("Model", "model"),
        ("Manufacturer", "manufacturer"),
        ("MAC Address", "mac"),
        ("Serial Number", "serial"),
        ("Software Version", "version"),
        ("Hardware Version", "hw_version"),
        ("SDK Version", "sdk_version"),
        ("WAN Type", "wan_type"),
    ]
    for label, key in info_fields:
        val = dev.get(key, "")
        if not val:
            continue  # skip empty fields instead of showing N/A
        items.append(
            html.Div([
                html.Strong(f"{label}: ", style={"minWidth": "160px", "display": "inline-block"}),
                html.Span(str(val)),
            ], className="mb-1", style={"fontSize": "0.9rem"})
        )

    # SW Upgrade Detected -- show with colored indicator
    sw_upgrade = dev.get("sw_upgrade", "")
    if sw_upgrade:
        is_upgraded = sw_upgrade.startswith("Yes")
        items.append(
            html.Div([
                html.Strong("SW Upgrade: ", style={"minWidth": "160px", "display": "inline-block"}),
                dbc.Badge(
                    sw_upgrade,
                    color="warning" if is_upgraded else "success",
                    style={"fontSize": "0.82rem", "padding": "4px 10px"},
                ),
            ], className="mb-1 d-flex align-items-center", style={"fontSize": "0.9rem"})
        )

    return html.Div(items)


def _build_key_metrics(configured_fields: dict, summary: dict) -> html.Div:
    """
    Build the Key Metric Trends card from extracted telemetry fields.

    Computes first->last trends, averages, peaks, min-max ranges, and
    reboot/reset detection for the most important system health metrics.

    Args:
        configured_fields: Output from extract_configured_fields().
        summary: Output from extract_telemetry_summary().

    Returns:
        Dash HTML Div with key metric trend lines.
    """
    # ---- helpers ----
    def _numerics(field_list, label_prefix):
        """Find a field by label prefix and return its numeric values list."""
        for fd in field_list:
            if fd["label"].startswith(label_prefix):
                nums = [v["numeric"] for v in fd["values"] if v["numeric"] is not None]
                return nums, fd.get("unit", "")
        return [], ""

    def _text_values(field_list, label_prefix):
        """Find a field by label prefix and return raw text values."""
        for fd in field_list:
            if fd["label"].startswith(label_prefix):
                return [v["raw"] for v in fd["values"]]
        return []

    def _fmt(val, unit=""):
        """Format a value with its unit."""
        if isinstance(val, float):
            val = int(val) if val == int(val) else round(val, 1)
        return f"{val} {unit}".strip() if unit else str(val)

    def _make_row(icon_cls, label, value_text, color="inherit"):
        """Create a single metric row with icon."""
        return html.Div([
            html.I(className=f"{icon_cls} me-2", style={"width": "18px", "color": "#6c757d"}),
            html.Strong(f"{label}: ", style={"minWidth": "130px", "display": "inline-block"}),
            html.Span(value_text, style={"color": color}),
        ], className="mb-2", style={"fontSize": "0.9rem"})

    rows = []

    # -- Report overview (compact single line) --
    total = summary.get("total", 0)
    parsed = summary.get("parsed", 0)
    tr = summary.get("overall_time_range", {})
    time_range = ""
    if tr.get("first") and tr.get("last"):
        time_range = f"  ({tr['first'][:16]} → {tr['last'][:16]})"
    rows.append(_make_row(
        "fas fa-chart-bar", "Reports",
        f"{parsed}/{total} parsed{time_range}",
    ))

    # -- System Resources --
    sys_fields = configured_fields.get("System Resources", [])
    if sys_fields:
        # Memory Free: first -> last (total: X)
        mem_vals, mem_unit = _numerics(sys_fields, "Memory Free")
        mem_total_vals, _ = _numerics(sys_fields, "Memory Total")
        if mem_vals:
            trend_text = f"{_fmt(mem_vals[0], mem_unit)} → {_fmt(mem_vals[-1], mem_unit)}"
            if mem_total_vals:
                trend_text += f" (total: {_fmt(mem_total_vals[0], mem_unit)})"
            # Detect trend direction
            if len(mem_vals) >= 2 and mem_vals[-1] < mem_vals[0] * 0.85:
                trend_text += "  ↓ decreasing"
                color = "#dc3545"  # red
            elif len(mem_vals) >= 2 and mem_vals[-1] > mem_vals[0] * 1.15:
                trend_text += "  ↑ increasing"
                color = "#28a745"  # green
            else:
                color = "inherit"
            rows.append(_make_row("fas fa-memory", "Memory Free", trend_text, color))

        # CPU Usage: avg, peak
        cpu_vals, cpu_unit = _numerics(sys_fields, "CPU Usage")
        if cpu_vals:
            avg_cpu = round(sum(cpu_vals) / len(cpu_vals), 1)
            peak_cpu = round(max(cpu_vals), 1)
            rows.append(_make_row(
                "fas fa-microchip", "CPU Usage",
                f"avg={avg_cpu}{cpu_unit}, peak={peak_cpu}{cpu_unit}",
            ))

        # Uptime: first -> last (resets detected)
        up_vals, up_unit = _numerics(sys_fields, "Uptime")
        if up_vals:
            resets = sum(1 for i in range(1, len(up_vals)) if up_vals[i] < up_vals[i - 1])
            uptime_text = f"{_fmt(up_vals[0], up_unit)} → {_fmt(up_vals[-1], up_unit)}"
            if resets:
                uptime_text += f" (resets detected: {resets})"
            rows.append(_make_row("fas fa-clock", "Uptime", uptime_text))

    # -- DSL / WAN --
    dsl_fields = configured_fields.get("DSL / WAN", [])
    if dsl_fields:
        ds_vals, ds_unit = _numerics(dsl_fields, "DSL Downstream")
        if ds_vals:
            rows.append(_make_row(
                "fas fa-arrow-down", "DSL Downstream",
                f"{_fmt(min(ds_vals))} - {_fmt(max(ds_vals))} {ds_unit}",
            ))
        us_vals, us_unit = _numerics(dsl_fields, "DSL Upstream")
        if us_vals:
            rows.append(_make_row(
                "fas fa-arrow-up", "DSL Upstream",
                f"{_fmt(min(us_vals))} - {_fmt(max(us_vals))} {us_unit}",
            ))

    # -- Device Info (reboot reasons) --
    dev_fields = configured_fields.get("Device Info", [])
    if dev_fields:
        reasons = _text_values(dev_fields, "Reboot Reason")
        if reasons:
            from collections import Counter
            reason_counts = dict(Counter(reasons))
            rows.append(_make_row(
                "fas fa-redo", "Reboot Reasons",
                ", ".join(f"{k}: {v}" for k, v in reason_counts.items()),
            ))

        conn_vals, _ = _numerics(dev_fields, "Connected Devices")
        if conn_vals:
            rows.append(_make_row(
                "fas fa-laptop", "Connected Devices",
                f"avg={round(sum(conn_vals)/len(conn_vals), 1)}, "
                f"peak={int(max(conn_vals))}",
            ))

    if not rows:
        return html.Div("No metric data available.", className="text-muted")

    return html.Div(rows)


# ---------------------------------------------------------------------------
# Helper: Build Radio / SSID status labels
# ---------------------------------------------------------------------------

def _build_status_labels(configured_fields: dict) -> html.Div:
    """
    Build modern status cards for Radio/SSID fields.

    Each Radio/SSID instance is displayed as a compact card with an
    icon, status indicator dot, and key properties (band, bandwidth,
    SSID name) shown as muted metadata underneath.

    Args:
        configured_fields: Output from extract_configured_fields().

    Returns:
        Dash HTML Div with modern status cards.
    """
    if not configured_fields:
        return html.Div()

    # ---- Color & icon helpers ----
    def _status_color(val: str):
        v = val.strip().lower()
        if v in ("up", "true", "enabled", "1"):
            return "#28a745", "#d4edda"  # green dot, light green bg
        elif v in ("down", "false", "disabled", "0", "error"):
            return "#dc3545", "#f8d7da"  # red dot, light red bg
        return "#6c757d", "#e9ecef"      # grey

    # ---- Collect per-instance data ----
    # Group fields by instance number (Radio 1, Radio 2, SSID 1, etc.)
    import re as _re

    cards = []

    for group_label, field_list in configured_fields.items():
        if group_label not in _STATUS_LABEL_GROUPS:
            continue

        # Identify instances by extracting the number from label
        instances: dict = {}  # instance_id -> {status, enable, meta: {label: val}}
        for fd in field_list:
            label = fd["label"]
            ftype = fd.get("type", "")
            latest = str(fd.get("latest", "N/A"))

            # Extract instance number (e.g. "Radio 1 Status" -> "1")
            m = _re.search(r"(\d+)", label)
            inst_id = m.group(1) if m else "0"

            if inst_id not in instances:
                instances[inst_id] = {"status": None, "enable": None, "meta": {}}

            if ftype == "status":
                instances[inst_id]["status"] = latest
            elif ftype == "bool":
                instances[inst_id]["enable"] = latest
            else:
                # Additional metadata (band, BW, SSID name, etc.)
                # Strip the instance prefix from label for compact display
                short = _re.sub(r"(Radio|SSID)\s*\d+\s*", "", label).strip()
                if short:
                    instances[inst_id]["meta"][short] = latest

        # Build a card per instance
        is_radio = "Radio" in group_label
        icon_cls = "fas fa-broadcast-tower" if is_radio else "fas fa-wifi"
        type_label = "Radio" if is_radio else "SSID"

        for inst_id in sorted(instances.keys(), key=lambda x: int(x) if x.isdigit() else x):
            data = instances[inst_id]
            status_val = data["status"] or data["enable"] or "N/A"
            dot_color, bg_color = _status_color(status_val)

            # Status dot + instance title
            header = html.Div([
                html.Span(
                    "",
                    style={
                        "width": "10px", "height": "10px",
                        "borderRadius": "50%", "backgroundColor": dot_color,
                        "display": "inline-block", "marginRight": "8px",
                        "boxShadow": f"0 0 6px {dot_color}",
                    },
                ),
                html.I(className=f"{icon_cls} me-2", style={"color": "#495057"}),
                html.Span(
                    f"{type_label} {inst_id}",
                    style={"fontWeight": "600", "fontSize": "0.95rem"},
                ),
                html.Span(
                    f"  {status_val.capitalize()}",
                    style={"marginLeft": "auto", "fontWeight": "500",
                           "color": dot_color, "fontSize": "0.85rem"},
                ),
            ], className="d-flex align-items-center")

            # Metadata chips
            meta_chips = []
            for k, v in data["meta"].items():
                meta_chips.append(
                    html.Span(
                        f"{k}: {v}",
                        style={
                            "fontSize": "0.78rem", "color": "#6c757d",
                            "backgroundColor": "#f1f3f5", "borderRadius": "4px",
                            "padding": "2px 8px", "marginRight": "6px",
                            "marginTop": "4px", "display": "inline-block",
                        },
                    )
                )

            card_content = [header]
            if meta_chips:
                card_content.append(html.Div(meta_chips, className="mt-1"))

            cards.append(
                html.Div(
                    card_content,
                    style={
                        "backgroundColor": bg_color,
                        "border": f"1px solid {dot_color}22",
                        "borderRadius": "10px",
                        "padding": "12px 16px",
                        "minWidth": "220px",
                        "flex": "1 1 260px",
                        "maxWidth": "350px",
                    },
                    className="me-3 mb-3 shadow-sm",
                )
            )

    if not cards:
        return html.Div()

    return html.Div(
        cards,
        className="d-flex flex-wrap",
        style={"gap": "12px"},
    )


# ---------------------------------------------------------------------------
# Helper: Build time-series charts (excluding status/device-info groups)
# ---------------------------------------------------------------------------

def _build_charts(configured_fields: dict) -> html.Div:
    """
    Build Plotly time-series charts for plottable numeric fields.

    Excludes groups in _SKIP_CHART_GROUPS (Radio/SSID status and Device Info
    are shown elsewhere).

    Args:
        configured_fields: Output from extract_configured_fields().

    Returns:
        Dash HTML Div with chart cards.
    """
    if not configured_fields:
        return html.Div()

    chart_cards = []

    for group_label, field_list in configured_fields.items():
        # Skip groups whose data is displayed elsewhere
        if group_label in _SKIP_CHART_GROUPS:
            continue

        # Collect plottable numeric fields
        plottable = [fd for fd in field_list if fd.get("plot") and len(fd["values"]) >= 2]

        if not plottable:
            continue

        traces = []
        for fd in plottable:
            times = [v["time"] for v in fd["values"] if v["numeric"] is not None]
            values = [v["numeric"] for v in fd["values"] if v["numeric"] is not None]

            if len(times) < 2:
                continue

            # Auto-scale units for readability (KB→MB, B→KB, sec→hours, etc.)
            raw_unit = fd.get("unit", "")
            scaled_values, display_unit = _auto_scale_unit(values, raw_unit)
            unit_str = f" ({display_unit})" if display_unit else ""

            traces.append(
                go.Scatter(
                    x=times,
                    y=scaled_values,
                    name=f"{fd['label']}{unit_str}",
                    mode="lines+markers",
                    marker=dict(size=3),
                )
            )

        if not traces:
            continue

        figure = go.Figure(
            data=traces,
            layout=go.Layout(
                title=dict(
                    text=group_label,
                    y=0.98,
                    x=0.5,
                    xanchor="center",
                    yanchor="top",
                ),
                xaxis_title="Time",
                yaxis_title="Value",
                hovermode="x unified",
                height=380,
                margin=dict(l=50, r=20, t=70, b=40),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.05,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                ),
            ),
        )

        chart_cards.append(
            dbc.Card(
                dbc.CardBody(dcc.Graph(figure=figure)),
                className="mb-3 shadow-sm",
            )
        )

    if not chart_cards:
        return html.Div("No plottable data available.", className="text-muted")

    return html.Div(chart_cards)


# ---------------------------------------------------------------------------
# Main callback
# ---------------------------------------------------------------------------

@callback(
    Output("dev-summary-card", "children"),
    Output("dev-status-card", "children"),
    Output("telemetry-status-labels", "children"),
    Output("telemetry-field-tables", "children"),
    Output("telemetry-charts", "children"),
    Output("telemetry_exception_modal", "is_open"),
    Output("telemetry_exception_modal_content", "children"),
    [
        Input("telemetry-btn", "n_clicks"),
        Input("telemetry_exception_modal_close", "n_clicks"),
    ],
    State("current-project-store", "data"),
)
def click_run(btn_click, modal_close, project_data):
    """
    Main telemetry callback: parse reports and populate all UI components.

    Triggered by the "Run" button or modal close. Finds telemetry2_0.txt
    in the project's upload directory, parses it, and builds:
    - Device Info card
    - Report Summary card
    - Radio/SSID status labels
    - Time-series charts for plottable fields

    Args:
        btn_click: Number of Run button clicks.
        modal_close: Number of modal close clicks.
        project_data: Current project store data (project_id, user_id).

    Returns:
        Tuple of (summary_card, status_card, status_labels, field_tables,
                  charts, modal_is_open, modal_content).
    """
    empty = html.Div()
    ctx = dash.callback_context

    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]

            if prop_id == "telemetry-btn" and project_data:
                project_id = project_data.get("project_id")
                user_id = project_data.get("user_id")
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')

                logger.info(f"[Telemetry] Searching for telemetry file in project {project_id}")

                # Find telemetry file by original name via DB lookup
                telemetry_file = _find_telemetry_file(project_dir, project_id)
                if telemetry_file is None:
                    logger.warning(f"[Telemetry] No telemetry2_0 file found for project {project_id}")
                    return empty, empty, empty, empty, empty, True, "No telemetry2_0 file found."

                # Parse the telemetry file
                logger.info(f"[Telemetry] Parsing {telemetry_file}")
                reports, merged, summary = parse_telemetry_file(telemetry_file)
                logger.info(f"[Telemetry] Parsed {summary.get('parsed', 0)}/{summary.get('total', 0)} reports")

                if not reports or summary.get("parsed", 0) == 0:
                    return empty, empty, empty, empty, empty, True, "No parseable telemetry reports found."

                # Extract YAML-configured fields
                field_config = load_report_field_config()
                configured_fields = extract_configured_fields(reports, field_config)

                # Enrich device_info with version.txt data (SDK version, SW upgrade)
                from logai.info_extractor import find_and_parse_version_txt
                version_info = find_and_parse_version_txt(project_dir)
                if version_info:
                    dev = summary.setdefault("device_info", {})
                    if version_info.get("sdk_version"):
                        dev["sdk_version"] = version_info["sdk_version"]
                    if version_info.get("sw_upgrade_detected"):
                        dev["sw_upgrade"] = f"Yes ({version_info['sw_upgrade_detail']})"
                    else:
                        dev["sw_upgrade"] = "No"

                # Build UI components
                summary_card = _build_device_info_card(summary)
                status_card = _build_key_metrics(configured_fields, summary)
                status_labels = _build_status_labels(configured_fields)
                charts = _build_charts(configured_fields)

                return summary_card, status_card, status_labels, empty, charts, False, ""

            elif prop_id == "telemetry_exception_modal_close":
                return empty, empty, empty, empty, empty, False, ""

        return empty, empty, empty, empty, empty, False, ""

    except Exception as error:
        logger.exception(f"[Telemetry] Callback error: {error}")
        return empty, empty, empty, empty, empty, True, str(error)


def _find_telemetry_file(project_dir: Path, project_id: str) -> Optional[Path]:
    """
    Find the telemetry2_0 file in the project directory.

    Files are now stored with their original names, so a direct
    filename match in the project directory is sufficient.

    Args:
        project_dir: Project directory to search.
        project_id: Project ID (unused, kept for API compat).

    Returns:
        Path to telemetry file, or None if not found.
    """
    if project_dir.exists():
        for f in project_dir.iterdir():
            if f.is_file() and f.name.lower().startswith("telemetry2_0"):
                logger.info(f"[Telemetry] Found telemetry file: {f}")
                return f

    return None
