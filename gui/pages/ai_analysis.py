import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
from .utils import create_modal

def search_input():
    return  html.Div([
                html.Div([
                    html.I(className="fas fa-search me-2 text-secondary"),
                    dcc.Input(
                        id="ai-query-input",
                        type="text",
                        placeholder="Ask Me about your uploaded logs...",
                        debounce=True,
                        style={
                            "border": "none",
                            "outline": "none",
                            "width": "100%",
                            "background": "transparent",
                            "fontSize": "16px",
                        },
                    ),
                    dbc.Button(
                        html.I(className="fas fa-paper-plane"),
                        id="ai-search-btn",
                        color="primary",
                        size="sm",
                        style={"borderRadius": "50%"},
                    ),
                    create_modal(
                        modal_id="ai_exception_modal",
                        header="An Exception Occurred",
                        content="An exception occurred. Please click OK to continue.",
                        content_id="ai_exception_modal_content",
                        button_id="ai_exception_modal_close",
                    ),
                ],className="ai-input-inner",
            ),
        ],
        className="ai-input-container",
    )


def embedding_results_table():
    """Static table layout — data will be filled dynamically."""
    return html.Div(
        dash_table.DataTable(
            id="ai-embed-search-results",
            columns=[
                {"name": "Filename", "id": "filename"},
                {"name": "Template", "id": "template"},
                {"name": "Frequency", "id": "frequency"},
                {"name": "Similarity", "id": "similarity"},
            ],
            data=[],  # initially empty
            #sort_action="native",
            #filter_action="native",
            editable=False,
            page_size=10,
            style_table={
                "maxHeight": "400px",
                "overflowY": "auto",
                "border": "1px solid #ddd",
                "borderRadius": "8px",
                "backgroundColor": "#fafafa",
            },
            style_cell={
                "textAlign": "left",
                "padding": "6px 8px",
                "fontFamily": "Segoe UI, sans-serif",
                "fontSize": "13px",
                "whiteSpace": "normal",
                "height": "auto",
            },
            style_header={
                "backgroundColor": "#f8f9fa",
                "fontWeight": "600",
                "borderBottom": "1px solid #ccc",
            },
            style_data_conditional=[
                {
                    "if": {"column_id": "similarity"},
                    "textAlign": "center",
                },
                {
                    "if": {"column_id": "frequency"},
                    "textAlign": "center",
                },
                {
                    "if": {
                        "filter_query": "{similarity} >= 0.8",
                        "column_id": "similarity"
                    },
                    "color": "green",
                    "fontWeight": "bold",
                },
                {
                    "if": {
                        "filter_query": "{similarity} < 0.5",
                        "column_id": "similarity"
                    },
                    "color": "grey",
                },
            ],
            row_selectable="single",
        ),
        style={"marginTop": "10px"}
    )

def matching_loglines():
    return html.Div(
        dash_table.DataTable(
            id="ai-log-template-results",
            columns=[
                {"name": "TimeStamp", "id": "timestamp"},
                {"name": "LogLines", "id": "loglines"},
            ],
            data=[],  # initially empty
            #sort_action="native",
            #filter_action="native",
            editable=False,
            page_size=10,
            style_table={
                "maxHeight": "400px",
                "overflowY": "auto",
                "border": "1px solid #ddd",
                "borderRadius": "8px",
                "backgroundColor": "#fafafa",
            },
            style_cell={
                "textAlign": "left",
                "padding": "6px 8px",
                "fontFamily": "Segoe UI, sans-serif",
                "fontSize": "13px",
                "whiteSpace": "normal",
                "height": "auto",
            },
            style_header={
                "backgroundColor": "#f8f9fa",
                "fontWeight": "600",
                "borderBottom": "1px solid #ccc",
            },
            row_selectable="single",
        ),
        style={"marginTop": "10px"}
    )

def template_parameter_list():
    return html.Div(id="ai-parameter-list", style={"overflowX": "auto"})

def log_context_slider(unit="seconds"):
    """Return a slider depending on selected time unit"""
    if unit == "seconds":
        min_val, max_val, step, default = 5, 60, 5, 5
        marks = {i: f"{i}s" for i in range(min_val, max_val + 1, step)}
    else:  # minutes
        min_val, max_val, step, default = 1, 10, 1, 1
        marks = {i: f"{i}min" for i in range(min_val, max_val + 1, step)}

    return dcc.Slider(
        id="ai-timestamp-context-slider",
        min=min_val,
        max=max_val,
        step=step,
        value=default,
        marks=marks,
        tooltip={"placement": "bottom", "always_visible": True},
        updatemode="drag",
    )

def log_context():
    return html.Div([
        # Time unit toggle + Highlight toggle
        dbc.Row([
            dbc.Col([
                html.Label("Time unit:"),
                dcc.RadioItems(
                    id="ai-timestamp-unit-toggle",
                    options=[
                        {"label": "Seconds", "value": "seconds"},
                        {"label": "Minutes", "value": "minutes"},
                    ],
                    value="seconds",
                    inline=True,
                    inputStyle={"margin-left": "15px", "margin-right": "5px"}
                )
            ], width="auto", style={"margin-left": "15px"}),
            dbc.Col([
                html.Label("Highlight log lines:"),
                dcc.Checklist(
                    id="ai-highlight-toggle",
                    options=[{"label": "Enable Highlight", "value": True}],
                    value=[],
                    inline=True,
                    inputStyle={"margin-left": "25px", "margin-right": "5px"}
                )
            ], width="auto"),
        ], className="mb-3", align="center"),

        # Slider container
        html.Div(
            id="ai-timestamp-slider-container",
            children=[log_context_slider("minutes")],
            style={"margin-bottom": "10px"}
        ),
        html.Div(id="ai-raw-log-view",
            className="bg-dark text-light p-2 border rounded",
            style={
                'background': '#2d3748',
                'color': '#e2e8f0',
                'padding': '15px',
                'border-radius': '8px',
                'font-family': 'monospace',
                'font-size': '10px',
                'height': '600px',
                'overflow-y': 'auto',
                'white-space': 'pre-wrap'
            }),
    ])

from dash import Input, Output, callback

@callback(
    Output("ai-timestamp-slider-container", "children"),
    Input("ai-timestamp-unit-toggle", "value")
)
def update_slider(unit):
    return log_context_slider(unit)

def ai_analysis_layout():
    return dbc.Row([
            dbc.Col(
                html.Div([
                    dbc.Row(
                        [
                            dbc.Col(
                                search_input(),
                                width=7,className="mx-auto mt-4",
                            ),
                        ],
                    ),
                    html.Hr(),
                    html.H5("Log Pattern Relevant to your search"),
                    html.Hr(),
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    embedding_results_table(),
                                ]),
                            ), width=12,
                        ),
                    ], className="mb-4"),
                    html.Hr(),
                    html.H5("Parameters list"),
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    template_parameter_list(),
                                ]),
                            ), width=12,
                        ),
                    ], className="mb-4"),
                    html.Hr(),
                    html.H5("Matching loglines"),
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    matching_loglines(),
                                ]),
                            ), width=12,
                        ),
                    ], className="mb-4"),
                    html.Hr(),
                    html.H5("Matching Log Context"),
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    log_context(),
                                ]),
                            ), width=12,
                        ),
                    ], className="mb-4"),
                    html.B(),
                    html.Hr(),
                ])
            ),
        ])

def ai_analysis_page():
    return html.Div(
        style={
        "height": "100vh",
        "overflowY": "auto",
        "padding": "15px",
        "fontSize": "12px",
        "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[
            ai_analysis_layout(),
        ]
    )
layout = ai_analysis_page()
