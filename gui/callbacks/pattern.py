import os
import pandas as pd
import plotly.express as px
from pathlib import Path
import numpy as np

from dash import ctx, html, Input, Output, State, callback, dash_table
import dash
from gui.app_instance import dbm
from logai.pattern import Pattern

from logai.utils.constants import (
    UPLOAD_DIRECTORY
)

def save_result_df(result_df, project_dir, filename="result_df.parquet"):
    file_path = os.path.join(project_dir, filename)
    result_df.to_parquet(file_path, index=False)
    return file_path

def load_result_df(file_path):
    if not os.path.exists(file_path):
        return pd.DataFrame()
    return pd.read_parquet(file_path)

def summary(result_df):
    if len(result_df) > 0:
        total_loglines = len(result_df["loglines"])
        total_log_patterns = len(result_df["template"].unique())

        return html.Div(
            [
                html.P("Total Number of Loglines: {}".format(total_loglines)),
                html.P("Total Number of Log Patterns: {}".format(total_log_patterns)),
            ]
        )
    else:
        return html.Div(
            [
                html.P("Total Number of Loglines: "),
                html.P("Total Number of Log Patterns: "),
            ]
        )

def summary_graph(result_df):
    count_table = result_df["template"].value_counts()
    scatter_df = pd.DataFrame(count_table)
    scatter_df.columns = ["counts"]
    scatter_df["ratio"] = scatter_df["counts"] * 1.0 / sum(scatter_df["counts"])
    scatter_df["order"] = np.array(range(scatter_df.shape[0]))

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

@callback(
    Output("pattern-result-store", "data"),
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
        State("current-project-store", "data"),
    ],
    prevent_initial_call=True,
)
def click_run(
    ptrn_btn_click, modal_close, filename, project_data
):
    if not project_data or not project_data.get("project_id") or not filename:
        return None,dash.no_update,dash.no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            
            if prop_id == "pattern-btn":
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")
                filename, file_path, original_name, file_size, _ = dbm.get_project_file_info(project_id, filename)
                
                if not os.path.getsize(file_path):
                    return None,dash.no_update,dash.no_update, True, "File Length is Zero!"

                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                
                # Parse logs and extract patterns
                parser = Pattern(project_dir=project_dir)
                result_df = parser.parse_logs(file_path)

                if result_df is None or result_df.empty:
                    return None,dash.no_update,dash.no_update, True, "No patterns were extracted from the log file."

                if "timestamp" not in result_df.columns or "loglines" not in result_df.columns:
                    return None,dash.no_update,dash.no_update, True, "The log file must contain 'timestamp' and 'logline' columns."
                
                summary_div = summary(result_df)
                fig = summary_graph(result_df)
                result_df_path = save_result_df(result_df, project_dir)
                return result_df_path, summary_div, fig, False, ""
            
            elif prop_id == "pattern_exception_modal_close":
                return None,dash.no_update,dash.no_update, False, ""
        else:
            return None,dash.no_update,dash.no_update, False, ""
    except Exception as error:
        return None,dash.no_update,dash.no_update, True, str(error)


@callback(Output("log-patterns", "children"), [Input("summary-scatter", "clickData")])
def update_log_pattern(data):
    if data is not None:
        res = data["points"][0]["customdata"]

        return html.Div(
            children=[html.B(res)],
            style={
                "width": "100 %",
                "display": "in-block",
                "align-items": "left",
                "justify-content": "left",
            },
        )
    else:
        return html.Div()

def get_parameter_list(result_df, log_pattern):
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


@callback(
    Output("log-dynamic-lists", "children"), 
    [Input("summary-scatter", "clickData")],
    [State("pattern-result-store", "data")]
)
def update_dynamic_lists(data, result_df_path):
    if data is not None and result_df_path is not None:
        df_logs = load_result_df(result_df_path)
        selected_template = data['points'][0]['customdata']
        
        subset = get_parameter_list(df_logs, selected_template)

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
    else:
        return dash_table.DataTable()

def get_log_lines(result_df, log_pattern):
        df = result_df
        res = df[df["template"] == log_pattern].drop(
            ["parameter_list", "template"], axis=1
        )

        return res

@callback(
    Output("select-loglines", "children"), 
    [Input("summary-scatter", "clickData")],
    [State("pattern-result-store", "data")],
)
def update_logline(data, result_df_path):
    if data is not None and result_df_path is not None:
        df_logs = load_result_df(result_df_path)
        df = get_log_lines(df_logs, data["points"][0]["customdata"])
        columns = [{"name": c, "id": c} for c in df.columns]
        return dash_table.DataTable(
            data=df.to_dict("records"),
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
            #page_action="native",
            page_size=20,
            page_current=0,
        )
    else:
        return dash_table.DataTable()

def create_time_series(dff, axis_type, title):
    fig = px.scatter(
        dff,
        x="timestamp",
        y="count",
        labels={"count": "Occurrence", "timstamp": "Time"},
        title=title,
    )

    fig.update_traces(mode="lines+markers")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(type="linear" if axis_type == "Linear" else "log")
    fig.update_layout(margin={"l": 20, "b": 30, "r": 10, "t": 30})
    return fig

@callback(
    Output("pattern-time-series", "figure"),
    [Input("summary-scatter", "clickData"), 
     Input("time-interval", "value")],
    [State("pattern-result-store", "data")],
    prevent_initial_call=True,
)

def update_y_timeseries(data, interval, result_df_path):
    if data is not None and result_df_path is not None:
        df_logs = load_result_df(result_df_path)

        interval_map = {0: "1s", 1: "1min", 2: "1h", 3: "1d"}
        pattern = data["points"][0]["customdata"]
        freq = interval_map[interval]
        dff = df_logs[df_logs["template"] == pattern][
            ["timestamp", "template"]
        ]
        df_clean = dff.dropna(subset=["timestamp"])
        #print(dff)
        ts_df = (
            df_clean[["timestamp", "template"]]
            .groupby(pd.Grouper(key="timestamp", freq=freq, offset=0, label="right"))
            .size()
            .reset_index(name="count")
        )

        title = "Trend of Occurrence at Freq({})".format(freq)
        return create_time_series(ts_df, "Linear", title)
    else:
        return px.scatter()