import dash_bootstrap_components as dbc
from dash import dcc, html
from .utils import (
    create_run_button,
    create_modal
)

def create_file_setting_layout():
    return html.Div(
        id="file-setting-layout",
        children=[
            html.Label("Log File"),
            dbc.Button([html.I(className="fas fa-sync-alt")], 
                                                         id="refresh-filelist-icon", color="outline-secondary", size="sm", 
                                                         title="Log Files"),
            dcc.Dropdown(id="file-select", 
                         options=["No File Selected!"],
                         value=None,
                         style={"width": "100%"}),
            html.Label("Time Interval"),
            dcc.Slider(
                0,
                3,
                step=None,
                marks={0: "1s", 1: "1min", 2: "1h", 3: "1d"},
                value=0,
                id="time-interval",
            ),
        ],
    )

def create_control_card():
    return html.Div(
        id="control-card",
        children=[
            create_file_setting_layout(),
            html.Hr(),
            create_run_button("pattern-btn"),
            create_modal(
                modal_id="pattern_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="pattern_exception_modal_content",
                button_id="pattern_exception_modal_close",
            ),
        ],
    )


def create_summary_graph_layout():
    return html.Div(
        dcc.Graph(id="summary-scatter"),
        # style={'width': '39%', 'display': 'inline-block', 'padding': '0 20'}
    )


def create_timeseries_grapy_layout():
    return html.Div(
        children=[
            dcc.Graph(id="pattern-time-series"),
        ],
        # style={
        #     'display': 'inline-block',
        #     'width': '59%'
        # },
    )


def create_pattern_layout():
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    [
                        dbc.Row(
                            [
                                dbc.Col(
                                    create_control_card(),
                                    width=6,
                                ),
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                html.H4("Summary"),
                                                html.Div(
                                                    id="log-summarization-summary"
                                                ),
                                            ]
                                        )
                                    ),
                                    width=6,
                                ),
                            ],
                        ),
                        html.B("Charts"),
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
                        html.Hr(),
                        dbc.Row([
                                dbc.Col(
                                    dbc.Card(
                                        dbc.CardBody(
                                            [
                                                dcc.Loading(
                                                    [
                                                        create_timeseries_grapy_layout(),
                                                    ]
                                                )
                                            ]
                                        )
                                    ),
                                    width=12,
                                ),
                            ],className="mt-4"
                        ),
                        html.B("Log Patterns"),
                        html.Hr(),
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div(id="log-patterns", style={"overflowX": "auto"}),
                                ],
                            ),
                            id="pattern-log-card",
                        ),
                        html.B("Dynamic Values"),
                        html.Hr(),
                    dbc.Row([
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div(id="log-dynamic-lists", style={"overflowX": "auto"})
                                ],
                            ),
                            id="pattern-dynamic-values",
                        ),
                        width=12,
                        ),
                    ], className="mb-4"),
                        html.B("Log Lines"),
                        html.Hr(),
                        dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody(
                                    [
                                    html.Div(id="select-loglines", style={"overflowX": "auto"})
                                    ]
                                ),
                            ),
                            width=12,
                        ),
                        ], className="mb-4")
                    ]
                )
            ),
        ]
    )

def pattern_page():
    return html.Div(
        style={"height": "100vh", "overflowY": "auto", "padding": "15px"},
        children=[
            create_pattern_layout(),
        ]
    )
layout = pattern_page()
