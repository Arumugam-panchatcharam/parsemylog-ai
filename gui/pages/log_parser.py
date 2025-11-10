import dash_bootstrap_components as dbc
from dash import dcc, html
from .utils import (
    create_modal,
)

def create_control_card():
    return html.Div(
        id="control-card",
        children=[
            dbc.Row([
                dbc.Col(
                    dbc.Button([html.I(className="fas fa-bar-chart me-2"),"Run Quick Analysis"], 
                               id="parser-run-btn", 
                               color="primary", outline=True,
                               className="mt-2", n_clicks=0),
                    width=6
                ),
                dbc.Col([
                    dbc.Button(
                        "Download Report",
                        id="parser-generate-report-btn",
                        color="primary",
                        className="mt-2",
                        outline=True,
                        n_clicks=0
                    ),
                    dcc.Download(id="parser-download-report")
                ], width=6
                ),
            ]),
            create_modal(
                modal_id="parser_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="parser_exception_modal_content",
                button_id="parser_exception_modal_close",
            ),
            create_modal(
                modal_id="parser_dwld_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="parser_dwld_exception_modal_content",
                button_id="parser_dwld_exception_modal_close",
            ),
        ],
    )

def create_summary_graph_layout():
    return html.Div(
        dcc.Graph(
        id="parser-summary-graph",
        style={
            "height": "45vh", 
            "width": "100%", 
            "margin": "0", 
            "padding": "0"},
        config={
            #"responsive": True,
            "displayModeBar": True, 
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]
            },
        ),
        style={
            "width": "100%",
            #"border": "1px solid #e0e0e0",
            #"borderRadius": "8px",
            #"boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
            "padding": "5px",
            "backgroundColor": "#fff",
            "overflow": "hidden",
        },
        className="graph-container"
    )


def create_log_parser_layout():
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    [
                        dbc.Row([
                                dbc.Col([create_control_card(),], width=4),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H5("Summary"),
                                                html.Div(
                                                    id="parser-summary"
                                                ),
                                            ]
                                        )
                                    ),width=8,
                                ),
                            ],
                        ),
                        html.Br(),
                        html.H5("Results Chart"),
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                dcc.Loading(
                                                    [
                                                        create_summary_graph_layout(),
                                                    ]
                                                )
                                            ]
                                        )
                                    ),
                                    width=12,
                                ),
                            ]),
                        html.Br(),
                        html.H5("Results"),
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Col(
                                    html.Div(id="parser-results", style={"overflowX": "auto"}),
                                    width=12,
                                ),
                            ]
                        )
                    ]
                )
            ),
        ]
    )

def log_parser_page():
    return html.Div(
        style={
        "height": "100vh",
        "overflowY": "auto",
        "padding": "15px",
        "fontSize": "12px",
        "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[
            create_log_parser_layout(),
        ]
    )

layout = log_parser_page()
