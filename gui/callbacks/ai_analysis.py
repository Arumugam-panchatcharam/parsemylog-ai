"""
AI Analysis Callbacks Module
=============================

Handles semantic search and template analysis using the Qdrant vector store.

Pipeline:
    User query -> BGE embedding -> Qdrant similarity search -> top-k templates
    -> Parameter extraction from domain parquet cache -> Context-window log display.
"""

import logging
import pandas as pd
import dash
from dash import html, ctx, Input, Output, State, callback, dash_table
from pathlib import Path

import gui.app_instance as app_instance
from gui.pages.highlighter import TextHighlighter
from logai.utils.constants import UPLOAD_DIRECTORY, LINES_PER_PAGE, QDRANT_URL

from logai.embedding import quick_search
from logai.pattern import extract_parameters

logger = logging.getLogger(__name__)


@callback(
    Output("ai-embed-search-results", "data"),
    Output("ai_exception_modal", "is_open"),
    Output("ai_exception_modal_content", "children"),
    [
        Input("ai-search-btn", "n_clicks"),
        Input("ai-query-input", "n_submit"),
        Input("ai_exception_modal_close", "n_clicks"),
    ],
    State("ai-query-input", "value"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def update_ai_embed_search_results(n_clicks, n_submit, model_close, query, project_data):
    """
    Run semantic search against the Qdrant vector store.

    Embeds the user query using BGE, queries the per-project Qdrant
    collection, and returns the top-k most similar templates with
    metadata (filename, domain, parquet_path, similarity score).
    """
    if not project_data or not project_data.get("project_id"):
        return dash.no_update, False, ""

    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]

            if prop_id in ("ai-search-btn", "ai-query-input"):
                if not query:
                    return dash.no_update, True, "Please enter a query."

                model = app_instance.EMBEDDING_MODEL
                if model is None:
                    return dash.no_update, True, "Embedding model not loaded yet. Please wait."

                project_id = project_data["project_id"]
                collection_name = f"project_{project_id}"
                logger.info(f"[AI Search] query='{query}', collection='{collection_name}'")

                # Use quick_search with the pre-loaded model (no re-init)
                embedding_results = quick_search(
                    query=query,
                    collection=collection_name,
                    model=model,
                    qdrant_url=QDRANT_URL,
                    top_k=10,
                )

                logger.info(f"[AI Search] Qdrant returned {len(embedding_results)} results")

                if not embedding_results:
                    return dash.no_update, True, "No similar templates found."

                # Include domain and parquet_path for downstream callbacks
                data = []
                for r in embedding_results:
                    data.append({
                        "filename": r.get("filename", "-"),
                        "template": r.get("template", ""),
                        "frequency": r.get("count", r.get("frequency", "-")),
                        "similarity": round(r.get("similarity", 0.0), 4),
                        "domain": r.get("domain", ""),
                        "parquet_path": r.get("parquet_path", ""),
                    })

                return data, False, ""

            elif prop_id == "ai_exception_modal_close":
                return [], False, ""

        return dash.no_update, False, ""

    except Exception as error:
        logger.error(f"[AI Search] Error: {error}")
        return dash.no_update, True, str(error)


def get_param_subset(result_df, log_pattern, parquet_path=None):
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
        project_dir = None
        domain = None
        if parquet_path:
            pq = Path(parquet_path)
            project_dir = str(pq.parent)
            stem = pq.stem  # e.g. "wireless_rg"
            if stem.endswith("_rg"):
                domain = stem[:-3]

        logger.info(
            f"[AI Params] Drain3 extraction for {len(loglines)} lines "
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
            logger.info("[AI Params] No parameter values extracted (0 columns)")
            return para_list

        transposed = params_df.T.values.tolist()
        para_list["values"] = pd.Series(transposed)
        para_list["position"] = [
            "POSITION_{}".format(v) for v in para_list.index.values
        ]
        para_list["value_counts"] = [
            len(list(filter(None, v))) for v in para_list["values"]
        ]
    except Exception as e:
        logger.warning(f"[AI Params] Error building parameter table: {e}")

    return para_list


def get_parameter_list(df, template, parquet_path=None):
    """Build a parameter DataTable for a given template."""
    subset = get_param_subset(df, template, parquet_path=parquet_path)

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


def get_logline_subset(df, log_pattern):
    """Filter DataFrame to rows matching a given template."""
    cols_to_drop = [c for c in ["parameter_list", "template"] if c in df.columns]
    return df[df["template"] == log_pattern].drop(columns=cols_to_drop, errors="ignore")


def get_log_lines(df, template):
    """Extract matching log lines as a list of dicts (includes source_file for context)."""
    df = get_logline_subset(df, template)
    records = []
    for r in df.to_dict("records"):
        entry = {
            "timestamp": str(r.get("timestamp", "-")),
            "loglines": r.get("loglines", ""),
        }
        if "source_file" in r:
            entry["source_file"] = r.get("source_file", "")
        records.append(entry)
    return records


@callback(
    Output("ai-parameter-list", "children"),
    Output("ai-log-template-results", "data"),
    Output('current-file-store', 'data', allow_duplicate=True),
    Output('selected-template-store', 'data'),
    Output('ai-parquet-store', 'data'),
    Input("ai-embed-search-results", "selected_rows"),
    State("ai-embed-search-results", "data"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def load_loglines(selected, rows, project_data):
    """
    Load log lines and parameters for a selected search result.

    Uses the parquet_path from the Qdrant payload to load the correct
    domain-based parquet cache (e.g., wifi_rg.parquet).
    Also stores the resolved parquet path for use by ``load_raw_loglines``.
    """
    no_update = (dash_table.DataTable(), [], dash.no_update, dash.no_update, dash.no_update)
    if not selected or not rows or not project_data or not project_data.get("project_id"):
        return no_update

    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            if prop_id == "ai-embed-search-results":
                row = rows[selected[0]]
                template = row["template"]
                parquet_path = row.get("parquet_path", "")
                domain = row.get("domain", "")
                filename = row.get("filename", "")

                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")
                project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")

                # Resolve parquet: prefer parquet_path from Qdrant, fallback to domain
                pq = Path(parquet_path) if parquet_path else None
                if pq is None or not pq.exists():
                    pq = project_dir / f"{domain}_rg.parquet"
                if not pq.exists():
                    logger.warning(f"[AI Analysis] Parquet not found: {pq}")
                    return no_update

                logger.info(f"[AI Analysis] Loading parquet: {pq}")
                df = pd.read_parquet(pq).reset_index(drop=True)
                logger.info(
                    f"[AI Analysis] Parquet columns: {list(df.columns)}, "
                    f"rows: {len(df)}, template match: "
                    f"{(df['template'] == template).sum() if 'template' in df.columns else 'N/A'}"
                )

                param_list = get_parameter_list(df, template, parquet_path=str(pq))
                log_lines = get_log_lines(df, template)

                return param_list, log_lines, filename, template, str(pq)

    except Exception as e:
        logger.error(f"[AI Analysis] load_loglines error: {e}")

    return no_update


HIGHLIGHT_BACKGROUND_COLOR = "#fff3b0"  # light yellow


def highlight_log_lines(df, template):
    """Highlight matching template lines in yellow, others with syntax highlighting."""
    highlighter = TextHighlighter()
    matches = []
    start = 1
    try:
        for idx, r in df.iterrows():
            is_selected = r['template'] == template
            line_text = f"{r.timestamp} {r.loglines}"
            if is_selected:
                matches.append(
                    html.Div(
                        line_text,
                        style={
                            "backgroundColor": HIGHLIGHT_BACKGROUND_COLOR,
                            "color": "black",
                            "padding": "2px 4px",
                            "fontFamily": "monospace",
                            "whiteSpace": "pre-wrap",
                        },
                    )
                )
                continue

            highlighted_line = highlighter._highlight_single_line(line_text)
            line_num = start + idx
            matches.append(
                html.Div(
                    highlighted_line,
                    **{
                        "data-line": str(line_num),
                        "data-page": str((line_num // LINES_PER_PAGE) + 1),
                        "style": {"cursor": "pointer", "padding": "2px"},
                    },
                )
            )
    except Exception as error:
        logger.error(f"[AI Analysis] highlight error: {error}")
        return []

    return matches


@callback(
    Output("ai-raw-log-view", "children"),
    [
        Input("ai-log-template-results", "selected_rows"),
        Input("ai-timestamp-context-slider", "value"),
        Input("ai-highlight-toggle", "value"),
        Input('selected-template-store', 'data'),
    ],
    [
        State("ai-timestamp-unit-toggle", "value"),
        State("ai-log-template-results", "data"),
        State("current-project-store", "data"),
        State("ai-parquet-store", "data"),
    ],
    prevent_initial_call=True,
)
def load_raw_loglines(selected, time_period, highlight_toggle, template,
                      time_unit, rows, project_data, parquet_store):
    """
    Display raw log lines in a time window around a selected log entry.

    Uses the domain parquet path stored by ``load_loglines`` (via
    ``ai-parquet-store``) and filters by the selected row's ``source_file``
    to show context from the same file only.
    """
    if not template or not selected or not project_data or not project_data.get("project_id"):
        return "No log selected."

    if ctx.triggered_id not in ["ai-log-template-results", "ai-timestamp-context-slider", "ai-highlight-toggle"]:
        return dash.no_update

    try:
        row = rows[selected[0]]

        # ---- Resolve the domain parquet path ----
        parquet_path = None

        # Primary: use the stored parquet path from the search-result selection
        if parquet_store:
            candidate = Path(parquet_store)
            if candidate.exists():
                parquet_path = candidate

        # Fallback: scan project dir for any domain parquet
        if parquet_path is None:
            project_id = project_data["project_id"]
            user_id = project_data.get("user_id")
            project_dir = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
            for pq in project_dir.glob("*_rg.parquet"):
                parquet_path = pq
                break

        if parquet_path is None or not parquet_path.exists():
            return "No parquet data available for this domain."

        logger.info(f"[AI Context] Loading parquet: {parquet_path}")
        df = pd.read_parquet(parquet_path).reset_index(drop=True)

        if "timestamp" not in df.columns:
            return "No timestamp data in parquet."

        # ---- Filter by source_file (back-reference from rg context) ----
        source_file = row.get("source_file", "")
        if source_file and "source_file" in df.columns:
            df = df[df["source_file"] == source_file]
            logger.info(
                f"[AI Context] Filtered to source_file='{source_file}': {len(df)} rows"
            )

        df["timestamp"] = pd.to_datetime(df["timestamp"])
        timestamp = pd.to_datetime(row["timestamp"])

        # Compute time window
        unit = time_unit if time_unit else "minutes"
        if unit == "seconds":
            delta = pd.Timedelta(seconds=time_period)
        else:
            delta = pd.Timedelta(minutes=time_period)

        start_time = timestamp - delta
        end_time = timestamp + delta

        # Filter logs in window
        context_logs = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= end_time)]
        logger.info(
            f"[AI Context] Window [{start_time} .. {end_time}]: {len(context_logs)} lines"
        )

        # Render lines with optional highlighting
        lines = []
        highlight_enabled = True in highlight_toggle
        if highlight_enabled:
            lines = highlight_log_lines(context_logs, template)
        else:
            for _, r in context_logs.iterrows():
                is_selected = r['template'] == template
                line_div = html.Div(
                    f"{r.timestamp} {r.loglines}",
                    style={
                        "backgroundColor": HIGHLIGHT_BACKGROUND_COLOR if is_selected else "transparent",
                        "color": "black" if is_selected else "white",
                        "padding": "2px 4px",
                        "fontFamily": "monospace",
                        "whiteSpace": "pre-wrap",
                    },
                )
                lines.append(line_div)

        return lines if lines else "No log lines found in the selected time window."

    except Exception as e:
        logger.error(f"[AI Analysis] load_raw_loglines error: {e}")
        return f"Error loading log context: {str(e)}"
