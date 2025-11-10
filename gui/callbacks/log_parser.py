from pathlib import Path
from dash import dcc, ctx, Input, Output, State, callback, dash_table, html
import plotly.express as px
from gui.app_instance import dbm
from logai.log_parser_config import LogParserConfig
from dash import no_update

from logai.utils.constants import (
    UPLOAD_DIRECTORY
)

def summary(result_df):
    if len(result_df) > 0:
        total_issues = len(result_df)
        categories = result_df["Category"].unique()

        return html.Div(
            [
                html.P("Total Number of Issues: {}".format(total_issues)),
                html.P("Categories: {}".format(categories)),
            ]
        )
    else:
        return html.Div(
            [
                html.P("Total Number of Issues: "),
                html.P("Categories: "),
            ]
        )

def summary_graph(result_df):
    fig = px.bar(result_df, x="Title", y="Frequency", color="Category",
    title="Frequency (capped at MAX_MATCHES(100))",
    text="Frequency")
    fig.update_traces(textposition="outside")
    fig.update_layout(uniformtext_minsize=8, uniformtext_mode="hide")
    return fig

def create_results_table(result_df):
    if "SampleLogs" in result_df.columns:
        result_df["SampleLogs"] = result_df["SampleLogs"].apply(
            lambda x: "\n".join(x) if isinstance(x, list) else str(x)
        )
    # Define preferred column order
    preferred_order = [
        "Category", "Title", "Description", "SampleLogs", "Frequency"
    ]
    columns_order = [c for c in preferred_order if c in result_df.columns]

    # Build column definitions
    columns = []
    for col in columns_order:
        columns.append({"name": col, "id": col})

    # Style config
    table = dash_table.DataTable(
        data=result_df.to_dict("records"),
        columns=columns,
        page_size=10,
        #filter_action="native",
        #sort_action="native",
        style_table={
            "overflowX": "auto",
            "borderRadius": "10px",
            "padding": "5px",
            "border": "1px solid #e0e0e0",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.1)"
        },
        style_header={
            "backgroundColor": "#f7f7f7",
            "fontWeight": "bold",
            "textAlign": "center",
            "borderBottom": "2px solid #ccc"
        },
        style_cell={
            "textAlign": "left",
            "whiteSpace": "pre-line",   # ✅ allow multiline logs
            "height": "auto",
            "fontFamily": "monospace",
            "fontSize": "13px",
            "padding": "6px",
        },
        style_data_conditional=[
            {
                "if": {"column_id": "Frequency"},
                "fontWeight": "bold",
                "color": "#1565c0"
            },
            {
                "if": {"column_id": "SampleLogs"},
                "whiteSpace": "pre-line",
                "maxWidth": "600px",
                "overflow": "hidden",
                "textOverflow": "ellipsis",
            }
        ],
        style_cell_conditional=[
            {
                'if': {'column_id': 'SampleLogs'},
                'width': '63%'
            },
            {
                'if': {'column_id': 'Category'},
                'width': '10%'
            },
            {
                'if': {'column_id': 'Title'},
                'width': '10%'
            },
            {
                'if': {'column_id': 'Description'},
                'width': '15%'
            },
            {
                'if': {'column_id': 'Frequency'},
                'width': '2%'
            },

        ],
        style_data={"borderBottom": "1px solid #e0e0e0"},
        #export_format="csv",   # ✅ allow user export
        export_headers="display"
    )
    return table

@callback(
    Output("parser-summary", "children"),
    Output("parser-summary-graph", "figure"),
    Output("parser-results", "children"),
    Output("parser_exception_modal", "is_open"),
    Output("parser_exception_modal_content", "children"),
    [
        Input("parser-run-btn", "n_clicks"),
        Input("parser_exception_modal_close", "n_clicks"),
    ],
    [
        State("current-project-store", "data"),
    ],
    prevent_initial_call=True,
)
def click_run( n_click, modal_close, project_data ):
    if not project_data or not project_data.get("project_id"):
        return  no_update, no_update, no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            
            if prop_id == "parser-run-btn":
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")
                try:
                    files = dbm.get_project_files(project_id)
                except Exception as e:
                    print(f"Parser Temporary Error retrieving data {e}")
                    return no_update, no_update, no_update, False, ""

                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                lpc = LogParserConfig()
                result_df = lpc.analyse_logs(project_dir, files)
                if result_df.empty:
                    return no_update, no_update, no_update, False, ""

                summary_div = summary(result_df)
                fig = summary_graph(result_df)
                table = create_results_table(result_df)

                return summary_div, fig, table, False, ""

            elif prop_id == "parser_exception_modal_close":
                return no_update, no_update, no_update, False, ""
        else:
            return no_update, no_update, no_update, False, ""
    except Exception as error:
        return no_update, no_update, no_update, True, str(error)
    

@callback(
    Output("parser-download-report", "data"),
    Output("parser_dwld_exception_modal", "is_open"),
    Output("parser_dwld_exception_modal_content", "children"),
    Input("parser-generate-report-btn", "n_clicks"),
    Input("parser_dwld_exception_modal_close", "n_clicks"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def generate_report(n_clicks, modal_close, project_data):
    if not project_data or not project_data.get("project_id"):
        return  no_update, False, ""

    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            
            if prop_id == "parser-generate-report-btn":
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                lpc = LogParserConfig()
                pdf_path, pdf_name = lpc.generate_pdf(project_dir)
                if not pdf_path:
                    return no_update, False, ""
                
                return dcc.send_file(pdf_path), False, ""

            elif prop_id == "parser_dwld_exception_modal_close":
                return no_update, False, ""
        else:
            return no_update, False, ""
    except Exception as error:
        return no_update, True, str(error)