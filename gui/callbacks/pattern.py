"""
Pattern Callbacks Module
=========================

Displays domain-based Drain3 templates from the rg+Drain3 pipeline.

When the user selects a domain (e.g. wireless, platform) and clicks Run,
the callback loads the corresponding ``{domain}_rg.parquet`` cache produced
by the background indexer and displays:
    - Summary statistics (total log lines, unique patterns).
    - Template frequency bar chart.
    - Time-series trend chart for a selected pattern.
    - Dynamic parameter values.
    - Matching log lines.
"""

import os
import logging
import pandas as pd
import plotly.express as px
from pathlib import Path
import numpy as np

from dash import ctx, html, dcc, Input, Output, State, callback, dash_table
import dash
import plotly.graph_objects as go

from logai.utils.constants import UPLOAD_DIRECTORY
from logai.pattern import extract_parameters
import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)

# Canonical domain display labels for indexing status
_DOMAIN_LABELS = {
    "wireless": "Wireless",
    "platform": "Platform",
    "core_router": "Core Router",
    "cellular": "Cellular",
    "mesh": "Mesh",
}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _load_domain_parquet(project_dir: Path, domain: str) -> pd.DataFrame:
    """
    Load the parquet cache for a given domain.

    Args:
        project_dir: Project directory.
        domain: Domain name (e.g. "wifi", "platform").

    Returns:
        DataFrame with [timestamp, loglines, template, parameter_list] columns,
        or empty DataFrame if file missing.
    """
    parquet_path = project_dir / f"{domain}_rg.parquet"
    if not parquet_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(parquet_path)


def summary(result_df: pd.DataFrame):
    """Build summary HTML from a result DataFrame."""
    if len(result_df) > 0:
        total_loglines = len(result_df)
        total_log_patterns = result_df["template"].nunique()
        return html.Div([
            html.P(f"Total Number of Loglines: {total_loglines}"),
            html.P(f"Total Number of Log Patterns: {total_log_patterns}"),
        ])
    return html.Div([
        html.P("Total Number of Loglines: 0"),
        html.P("Total Number of Log Patterns: 0"),
    ])


def summary_graph(result_df: pd.DataFrame):
    """Build a bar chart of template frequency (log scale)."""
    count_table = result_df["template"].value_counts()
    scatter_df = pd.DataFrame(count_table)
    scatter_df.columns = ["counts"]
    scatter_df["ratio"] = scatter_df["counts"] / scatter_df["counts"].sum()
    scatter_df["order"] = np.arange(scatter_df.shape[0])

    fig = px.bar(
        scatter_df,
        x="order",
        y="counts",
        labels={"order": "log pattern", "counts": "Occurrence (Log Scale)"},
        hover_name=scatter_df.index.values,
    )
    fig.update_traces(customdata=scatter_df.index.values)
    fig.update_yaxes(type="log")
    fig.update_layout(margin={"l": 40, "b": 40, "t": 10, "r": 0}, hovermode="closest")
    return fig


# ------------------------------------------------------------------
# File-filter population (on domain selection)
# ------------------------------------------------------------------

@callback(
    Output("file-filter-select", "options"),
    Output("file-filter-select", "value"),
    Output("file-filter-select", "placeholder"),
    Input("file-select", "value"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def populate_file_filter(domain, project_data):
    """
    Populate the per-file filter dropdown when a domain is selected.

    Reads the ``source_file`` column from the domain parquet to list
    all files that contributed to this domain. If the parquet has no
    ``source_file`` column (older index), the dropdown stays empty.
    """
    if not domain or not project_data or not project_data.get("project_id"):
        return [], None, "All files (select domain first)"

    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

    df = _load_domain_parquet(project_dir, domain)
    if df.empty or "source_file" not in df.columns:
        return [], None, "All files (no file info available)"

    unique_files = sorted(df["source_file"].dropna().unique())

    options = [{"label": name, "value": name} for name in unique_files]

    placeholder = f"{len(options)} file(s) — select to filter"
    return options, None, placeholder


# ------------------------------------------------------------------
# Main Run callback
# ------------------------------------------------------------------

@callback(
    Output("pattern-result-store", "data"),
    Output("pattern-file-filter-store", "data"),
    Output("log-summarization-summary", "children"),
    Output("summary-scatter", "figure"),
    Output("pattern_exception_modal", "is_open"),
    Output("pattern_exception_modal_content", "children"),
    [
        Input("pattern-btn", "n_clicks"),
        Input("pattern_exception_modal_close", "n_clicks"),
    ],
    [
        State("file-select", "value"),
        State("file-filter-select", "value"),
        State("current-project-store", "data"),
    ],
    prevent_initial_call=True,
)
def click_run(ptrn_btn_click, modal_close, domain, file_filter, project_data):
    """
    Load and display domain-based Drain3 patterns.

    Reads the ``{domain}_rg.parquet`` cache from the project directory,
    optionally filters by selected source files, and renders summary,
    bar chart, etc.

    Args:
        ptrn_btn_click: Run button click count.
        modal_close: Exception modal close button click.
        domain: Selected domain name from dropdown.
        file_filter: List of selected filenames to filter, or None for all.
        project_data: Current project store data dict.
    """
    if not project_data or not project_data.get("project_id") or not domain:
        return None, None, dash.no_update, dash.no_update, False, ""

    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]

            if prop_id == "pattern-btn":
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")
                project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

                logger.info(f"[Pattern] Loading domain '{domain}' for project {project_id}")
                result_df = _load_domain_parquet(project_dir, domain)

                if result_df.empty:
                    return (
                        None, None, dash.no_update, dash.no_update, True,
                        f"No patterns found for domain '{domain}'. "
                        "The indexer may still be running -- try refreshing in a moment.",
                    )

                if "template" not in result_df.columns:
                    return (
                        None, None, dash.no_update, dash.no_update, True,
                        "Parquet cache is missing 'template' column.",
                    )

                # Apply per-file filter if specified
                if file_filter and "source_file" in result_df.columns:
                    result_df = result_df[result_df["source_file"].isin(file_filter)]
                    if result_df.empty:
                        return (
                            None, None, dash.no_update, dash.no_update, True,
                            "No patterns found for the selected file(s) in this domain.",
                        )
                    logger.info(
                        f"[Pattern] Filtered to {len(file_filter)} file(s): "
                        f"{len(result_df)} lines remain"
                    )

                parquet_path = str(project_dir / f"{domain}_rg.parquet")
                logger.info(
                    f"[Pattern] Domain '{domain}': {len(result_df)} lines, "
                    f"{result_df['template'].nunique()} unique templates"
                )
                summary_div = summary(result_df)
                fig = summary_graph(result_df)

                # Persist the active file filter for downstream callbacks
                active_filter = file_filter if file_filter else None
                return parquet_path, active_filter, summary_div, fig, False, ""

            elif prop_id == "pattern_exception_modal_close":
                return None, None, dash.no_update, dash.no_update, False, ""
        else:
            return None, None, dash.no_update, dash.no_update, False, ""
    except Exception as error:
        return None, None, dash.no_update, dash.no_update, True, str(error)


# ------------------------------------------------------------------
# Template text display on bar click
# ------------------------------------------------------------------

@callback(Output("log-patterns", "children"), [Input("summary-scatter", "clickData")])
def update_log_pattern(data):
    """Display the selected template text on bar chart click."""
    if data is not None:
        res = data["points"][0]["customdata"]
        return html.Div(
            children=[html.B(res)],
            style={
                "width": "100%",
                "display": "inline-block",
                "alignItems": "left",
                "justifyContent": "left",
            },
        )
    return html.Div()


# ------------------------------------------------------------------
# Dynamic values (parameters)
# ------------------------------------------------------------------

def _get_parameter_list(result_df, log_pattern, parquet_path=None):
    """
    Extract positional parameter values for a given template.

    If the parquet has a ``parameter_list`` column, uses it directly.
    Otherwise, extracts parameters on-demand using Drain3's native
    ``get_parameter_list`` API (handles all masking tokens correctly).

    Args:
        result_df: DataFrame with loglines and templates.
        log_pattern: The selected Drain3 template string.
        parquet_path: Optional path to the domain parquet (used to
            derive project_dir and domain for loading Drain3 state).
    """
    para_list = pd.DataFrame(None, columns=["position", "value_counts", "values"])

    if result_df.empty or not log_pattern:
        return para_list

    matching = result_df[result_df["template"] == log_pattern]
    if matching.empty:
        return para_list

    # Use existing parameter_list if available, otherwise extract lazily
    if "parameter_list" in result_df.columns:
        parameters = matching["parameter_list"]
    else:
        # On-demand extraction using Drain3's native get_parameter_list
        loglines = matching["loglines"].tolist()

        # Derive project_dir and domain from parquet path
        # Pattern: {project_dir}/{domain}_rg.parquet
        project_dir = None
        domain = None
        if parquet_path:
            pq = Path(parquet_path)
            project_dir = str(pq.parent)
            stem = pq.stem  # e.g. "wireless_rg"
            if stem.endswith("_rg"):
                domain = stem[:-3]  # e.g. "wireless"

        logger.info(
            f"[Pattern Params] Drain3 extraction for {len(loglines)} lines "
            f"(domain={domain}, template: {log_pattern[:60]}...)"
        )
        param_values = extract_parameters(
            log_pattern, loglines, project_dir=project_dir, domain=domain
        )
        parameters = pd.Series(param_values)

    if parameters.empty:
        return para_list

    try:
        params_df = pd.DataFrame(parameters.tolist())
        if params_df.empty or params_df.shape[1] == 0:
            # All extractions returned empty lists -- no parameters found
            logger.info("[Pattern Params] No parameter values extracted (0 columns)")
            return para_list

        transposed = params_df.T.values.tolist()
        para_list["values"] = pd.Series(transposed)
        para_list["position"] = [
            f"POSITION_{v}" for v in para_list.index.values
        ]
        para_list["value_counts"] = [
            len(list(filter(None, v))) for v in para_list["values"]
        ]
    except Exception as e:
        logger.warning(f"[Pattern Params] Error building parameter table: {e}")

    return para_list


def _load_filtered_parquet(result_df_path, file_filter):
    """
    Load parquet and apply the active file filter.

    Args:
        result_df_path: Path to the domain parquet.
        file_filter: List of filenames to keep, or None/empty for all.

    Returns:
        Filtered DataFrame.
    """
    df = pd.read_parquet(result_df_path)
    if file_filter and "source_file" in df.columns:
        df = df[df["source_file"].isin(file_filter)]
    return df


@callback(
    Output("log-dynamic-lists", "children"),
    [Input("summary-scatter", "clickData")],
    [
        State("pattern-result-store", "data"),
        State("pattern-file-filter-store", "data"),
    ],
)
def update_dynamic_lists(data, result_df_path, file_filter):
    """Display dynamic parameter values for a selected template."""
    if data is not None and result_df_path is not None:
        df_logs = _load_filtered_parquet(result_df_path, file_filter)
        selected_template = data["points"][0]["customdata"]
        subset = _get_parameter_list(df_logs, selected_template, parquet_path=result_df_path)

        if subset.empty:
            return dash_table.DataTable()

        subset["values"] = subset["values"].apply(
            lambda x: ", ".join(set(filter(None, [str(v) for v in x])))
        )
        subset = subset.rename(
            columns={"position": "Position", "value_counts": "Count", "values": "Value"}
        )
        columns = [{"name": c, "id": c} for c in subset.columns]
        return dash_table.DataTable(
            data=subset.to_dict("records"),
            columns=columns,
            style_table={"overflowX": "auto", "minWidth": "100%"},
            style_cell={"textAlign": "left", "maxWidth": "900px", "whiteSpace": "normal"},
            editable=False,
            sort_action="native",
            sort_mode="multi",
            column_selectable="single",
        )
    return dash_table.DataTable()


# ------------------------------------------------------------------
# Log lines for a selected template
# ------------------------------------------------------------------

@callback(
    Output("select-loglines", "children"),
    [Input("summary-scatter", "clickData")],
    [
        State("pattern-result-store", "data"),
        State("pattern-file-filter-store", "data"),
    ],
)
def update_logline(data, result_df_path, file_filter):
    """Display matching log lines for a selected template."""
    if data is not None and result_df_path is not None:
        df_logs = _load_filtered_parquet(result_df_path, file_filter)
        template = data["points"][0]["customdata"]

        cols_to_drop = [c for c in ["parameter_list", "template", "source_file"]
                        if c in df_logs.columns]
        df = df_logs[df_logs["template"] == template].drop(columns=cols_to_drop, errors="ignore")

        columns = [{"name": c, "id": c} for c in df.columns]
        return dash_table.DataTable(
            data=df.to_dict("records"),
            columns=columns,
            style_table={"overflowX": "auto", "minWidth": "100%"},
            style_cell={"textAlign": "left", "maxWidth": "900px", "whiteSpace": "normal"},
            editable=False,
            sort_action="native",
            sort_mode="multi",
            column_selectable="single",
            page_size=20,
            page_current=0,
        )
    return dash_table.DataTable()


# ------------------------------------------------------------------
# Time-series trend
# ------------------------------------------------------------------

def _create_time_series(dff, axis_type, title):
    """Build a Plotly time-series figure."""
    if dff.empty:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=dff["timestamp"],
            y=dff["count"],
            mode="lines+markers",
            marker=dict(size=4, color="blue"),
            line=dict(width=2),
            hovertemplate="Time: %{x}<br>Count: %{y}<extra></extra>",
        )
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(type="linear" if axis_type == "Linear" else "log")
    fig.update_layout(
        title=title,
        margin={"l": 20, "b": 30, "r": 10, "t": 30},
        hovermode="closest",
    )
    return fig


@callback(
    Output("pattern-time-series", "figure"),
    [Input("summary-scatter", "clickData"), Input("time-interval", "value")],
    [
        State("pattern-result-store", "data"),
        State("pattern-file-filter-store", "data"),
    ],
    prevent_initial_call=True,
)
def update_y_timeseries(data, interval, result_df_path, file_filter):
    """Update time-series chart for the selected template and interval."""
    if data is None or result_df_path is None:
        return go.Figure()

    df_logs = _load_filtered_parquet(result_df_path, file_filter)
    if df_logs.empty or "timestamp" not in df_logs.columns:
        return go.Figure()

    interval_map = {0: "1s", 1: "1min", 2: "1h", 3: "1d"}
    freq = interval_map.get(interval, "1min")
    pattern = data["points"][0]["customdata"]

    df_pattern = df_logs.loc[df_logs["template"] == pattern, ["timestamp"]].dropna()
    if df_pattern.empty:
        return go.Figure()

    df_pattern["timestamp"] = pd.to_datetime(df_pattern["timestamp"])

    ts_df = (
        df_pattern.groupby(pd.Grouper(key="timestamp", freq=freq))
        .size()
        .reset_index(name="count")
    )

    # Downsample if too many points
    max_points = 5000
    if len(ts_df) > max_points:
        ts_df = ts_df.iloc[:: len(ts_df) // max_points + 1]

    title = f"Trend of Occurrence at Freq({freq})"
    return _create_time_series(ts_df, "Linear", title)


# ------------------------------------------------------------------
# Domain indexing status + auto-resume for missing domains
# ------------------------------------------------------------------

# Thread-safe tracking of resume-indexing launches.
# Keys are cleared when indexing completes so failed domains can be retried.
import threading as _threading
_resume_launched: set = set()
_resume_guard = _threading.Lock()

# All expected domains (must match 'domain:' key inside configs/rg_patterns/*.yaml)
_ALL_DOMAINS = ["wireless", "platform", "core_router", "cellular", "mesh"]


def _get_indexed_domains(project_dir: Path) -> set:
    """
    Fast check: which domains have finished indexing.

    Simply checks for ``{domain}_rg.parquet`` file existence -- no stat()
    or size computation, just pure file-presence check.

    Args:
        project_dir: Project directory to scan.

    Returns:
        Set of domain names that have a parquet cache.
    """
    indexed = set()
    for domain in _ALL_DOMAINS:
        if (project_dir / f"{domain}_rg.parquet").exists():
            indexed.add(domain)
    return indexed


def _has_text_files(project_dir: Path) -> bool:
    """Quick check if the project directory has any uploadedtext files."""
    if not project_dir.exists():
        return False
    for f in project_dir.iterdir():
        if f.is_file() and f.suffix not in (".json", ".parquet", ".tmp"):
            return True
    return False


def _launch_resume_indexer(project_dir: Path, project_id: str, missing_domains: list):
    """
    Launch background indexer for missing domains only.

    Multi-user safe:
    - Respects the per-project lock (won't launch if indexing is active).
    - Uses a thread-safe set to prevent duplicate launches.
    - Clears the tracking key after indexing completes so failed domains
      can be retried on the next check.
    """
    import threading
    from gui.callbacks.log_viewer import _run_indexer_async, is_indexing

    key = f"{project_id}:{','.join(sorted(missing_domains))}"

    with _resume_guard:
        if key in _resume_launched:
            return  # Already launched for these domains
        _resume_launched.add(key)

    # Don't launch if another indexer thread is already running
    if is_indexing(project_id):
        logger.info(
            f"[ResumeIndexer] Skipping -- indexer already running for project {project_id}"
        )
        return

    def _run_and_clear():
        """Wrapper that clears the tracking key after completion."""
        try:
            _run_indexer_async(project_dir, project_id, missing_domains)
        finally:
            with _resume_guard:
                _resume_launched.discard(key)

    logger.info(
        f"[ResumeIndexer] Launching background indexer for project {project_id}, "
        f"missing domains: {missing_domains}"
    )
    t = threading.Thread(target=_run_and_clear, daemon=True)
    t.start()


@callback(
    Output("indexing-status-container", "children"),
    Output("indexing-status-interval", "disabled"),
    Input("indexing-status-interval", "n_intervals"),
    Input("current-project-store", "data"),
    prevent_initial_call=True,
)
def update_indexing_status(_n, project_data):
    """
    Poll domain indexing status and render badges per domain.

    Uses fast file-presence checks (no stat calls) on first pass.
    If any domains are missing AND the project has text files, auto-
    launches background indexing for the missing domains only.

    The interval disables itself once all expected domains are indexed.
    """
    if not project_data or not project_data.get("project_id"):
        return "", True

    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

    if not project_dir.exists():
        return "", True

    # Fast file-presence check for indexed domains
    indexed_domains = _get_indexed_domains(project_dir)
    missing_domains = [d for d in _ALL_DOMAINS if d not in indexed_domains]

    if not indexed_domains:
        # No parquets at all yet
        if not _has_text_files(project_dir):
            return "", True

        # Auto-resume: launch indexer for all domains
        _launch_resume_indexer(project_dir, project_id, _ALL_DOMAINS)

        return dbc.Alert(
            [html.I(className="fas fa-spinner fa-spin me-2"),
             "Indexing in progress..."],
            color="info", className="mb-0 py-2 small",
        ), False

    # Build badge list for indexed domains
    badges = []
    for domain in _ALL_DOMAINS:
        label = _DOMAIN_LABELS.get(domain, domain)
        if domain in indexed_domains:
            badges.append(
                dbc.Badge(
                    [html.I(className="fas fa-check-circle me-1"), label],
                    color="success", className="me-2 mb-1",
                )
            )

    all_done = len(missing_domains) == 0

    # Check if an indexer is already running for this project
    from gui.callbacks.log_viewer import is_indexing
    currently_indexing = is_indexing(project_id)

    # Auto-resume: if some domains are missing AND no indexer is running
    if missing_domains and _has_text_files(project_dir) and not currently_indexing:
        _launch_resume_indexer(project_dir, project_id, missing_domains)

    # Show pending/in-progress badges for missing domains
    if missing_domains:
        for domain in missing_domains:
            label = _DOMAIN_LABELS.get(domain, domain)
            if currently_indexing:
                badges.append(
                    dbc.Badge(
                        [html.I(className="fas fa-spinner fa-spin me-1"), label],
                        color="info", className="me-2 mb-1",
                    )
                )
            else:
                badges.append(
                    dbc.Badge(
                        [html.I(className="fas fa-spinner fa-spin me-1"), label],
                        color="warning", className="me-2 mb-1",
                    )
                )

    status_content = html.Div(badges, className="d-flex flex-wrap")
    return status_content, all_done
