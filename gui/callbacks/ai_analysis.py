import pandas as pd
import dash
from dash import html, ctx, Input, Output, State, callback, dash_table
from pathlib import Path

from pyparsing import line
from gui.app_instance import dbm
from gui.pages.highlighter import TextHighlighter
from logai.utils.constants import UPLOAD_DIRECTORY, LINES_PER_PAGE

from logai.embedding import VectorEmbedding

@callback(
    Output("ai-embed-search-results", "data"),
    Output("ai_exception_modal", "is_open"),
    Output("ai_exception_modal_content", "children"),
    [
        Input("ai-search-btn", "n_clicks"),
        Input("ai_exception_modal_close", "n_clicks"),
    ],
    State("ai-query-input", "value"),
    State("current-project-store", "data"),
    prevent_initial_call=True
)
def update_ai_embed_search_results(n_clicks, model_close, query, project_data):
    if not project_data or not project_data.get("project_id"):
        return dash.no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            #print(prop_id)
            if prop_id == "ai-search-btn":
                if not query:
                    return dash.no_update, True, "Please enter a query."
                
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")

                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                embedding  = VectorEmbedding()
                embedding_results = embedding.search(project_dir, query, top_k=10)
                #print("Search results ", embedding_results)

                if not embedding_results:
                    return dash.no_update, True, "No similar templates found."

                data = [
                    {
                        "filename": r.get("filename", "-"),
                        "template": r.get("template", ""),
                        "frequency": r.get("frequency", "-"),
                        "similarity": round(r.get("similarity", 0.0), 4),
                    }
                    for r in embedding_results
                ]
                return data, False, ""
            else:
                return [], False, ""
    except Exception as error:
        return True, str(error)


def get_param_subset(result_df, log_pattern):
    para_list = pd.DataFrame(None, columns=["position", "value_counts", "values"])

    if result_df.empty or not log_pattern:
        return para_list

    parameters = result_df[result_df["template"] == log_pattern]["parameter_list"]

    para_list["values"] = pd.Series(
        pd.DataFrame(parameters.tolist()).T.values.tolist()
    )
    para_list["position"] = [
        "POSITION_{}".format(v) for v in para_list.index.values
    ]
    para_list["value_counts"] = [
        len(list(filter(None, v))) for v in para_list["values"]
    ]

    return para_list

def get_parameter_list(df, template):
    subset = get_param_subset(df, template)

    subset["values"] = subset["values"].apply(lambda x: ", ".join(set(filter(None, x))))
    subset = subset.rename(
        columns={"position": "Position", "value_counts": "Count", "values": "Value"}
    )
    columns = [{"name": c, "id": c} for c in subset.columns]
    return dash_table.DataTable(
        data=subset.to_dict("records"),
        columns=columns,
        style_table={
        "overflowX": "auto",
        "minWidth": "100%",
        },
        style_cell={
            "textAlign": "left",
            "maxWidth": "900px",
            "whiteSpace": "normal",
        },
        editable=False,
        #row_selectable="multi",
        sort_action="native",
        sort_mode="multi",
        column_selectable="single",
    )
def get_logline_subset(df, log_pattern):
    res = df[df["template"] == log_pattern].drop(
        ["parameter_list", "template"], axis=1
    )
    return res

def get_log_lines(df, template):
    df = get_logline_subset(df, template)
    data = [
        {
            "timestamp": r.get("timestamp", "-"),
            "loglines": r.get("loglines", ""),
        }
        for r in df.to_dict("records")
    ]
    return data

@callback(
    Output("ai-parameter-list", "children"),
    Output("ai-log-template-results", "data"),
    Output('current-file-store', 'data', allow_duplicate=True),
    Input("ai-embed-search-results", "selected_rows"),
    State("ai-embed-search-results", "data"),
    State("current-project-store", "data"),
    prevent_initial_call=True
)
def load_loglines(selected, rows, project_data):
    if not selected or not project_data or not project_data.get("project_id"):
        return dash_table.DataTable(), [], dash.no_update
    if ctx.triggered:
        prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
        #print(prop_id)
        if prop_id == "ai-embed-search-results":
            row = rows[selected[0]]
            template = row["template"]
            filename = row["filename"]

            project_id = project_data["project_id"]
            #user_id = project_data.get("user_id")

            #project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
            filename, filepath, original_name, file_size, _ = dbm.get_project_file_info_orig_name(project_id, filename)
            parquet_path = Path(str(filepath) + ".parquet")
            df = pd.read_parquet(parquet_path).reset_index(drop=True)
            
            param_list = get_parameter_list(df, template)
            log_lines = get_log_lines(df, template)

            return param_list, log_lines, original_name

    return dash_table.DataTable(), [], dash.no_update

def highlight_log_lines(df):
    highlighter = TextHighlighter()
    matches = []
    start = 1
    try:
        for idx, r in df.iterrows():
            line_text = f"{r.timestamp} {r.loglines}"
            highlighted_line = highlighter._highlight_single_line(line_text)
            line_num = start + idx
            matches.append(
                html.Div(
                    highlighted_line,
                    **{
                        "data-line": str(line_num),
                        "data-page": str((line_num // LINES_PER_PAGE)+1),
                        "style": {"cursor": "pointer", "padding": "2px"}
                    }
                )
            )
    except Exception as error:
        return []

    return matches

@callback(
    Output("ai-raw-log-view", "children"),
    [
        Input("ai-log-template-results", "selected_rows"),
        Input("ai-timestamp-context-slider", "value"),
        Input("ai-highlight-toggle", "value"),
    ],
    [
        State("ai-timestamp-unit-toggle", "value"),
        State("ai-log-template-results", "data"),
        State("current-project-store", "data"),
        State("current-file-store", "data"),
    ],
    prevent_initial_call=True
)
def load_raw_loglines(selected, time_period, highlight_toggle, time_unit, rows, project_data, filename):
    if not selected or not project_data or not project_data.get("project_id"):
        return "No log selected."

    if ctx.triggered_id not in ["ai-log-template-results", "ai-timestamp-context-slider", "ai-highlight-toggle"]:
        return dash.no_update

    row = rows[selected[0]]
    project_id = project_data["project_id"]

    # Get the file info
    filename, filepath, original_name, file_size, _ = dbm.get_project_file_info_orig_name(project_id, filename)
    parquet_path = Path(str(filepath) + ".parquet")
    df = pd.read_parquet(parquet_path).reset_index(drop=True)

    # Convert timestamp column to datetime
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

    # Render lines with optional highlighting
    lines = []
    highlight_enabled = True in highlight_toggle
    if highlight_enabled:
        lines = highlight_log_lines(context_logs)

    if not highlight_enabled:
        raw_log = []
        for _, r in context_logs.iterrows():
            line_text = f"{r.timestamp} {r.loglines}"
            raw_log.append(line_text)
            lines = "\n".join(raw_log)

    return lines