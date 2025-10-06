import dash_bootstrap_components as dbc
from dash import dcc, html
from .utils import (
    create_run_button,
    create_modal
)

def create_file_setting_layout():
    return html.Div(
        id="ai-file-setting-layout",
        children=[
            html.Label("Log Files"),
            dbc.Button([html.I(className="fas fa-sync-alt")], 
                        id="ai-refresh-filelist-icon", 
                        color="primary", 
                        size="sm", 
                        title="Log Files"
                        ),
            dcc.Dropdown(id="ai-file-select", 
                         options=[],
                         value=[],
                         #multi=True,
                        placeholder="Choose one or more files...",
                        )
        ],
    )

def create_control_card():
    return html.Div(
        id="ai-control-card",
        children=[
            create_file_setting_layout(),
            #create_run_button("ai-analysis-btn"),
            create_modal(
                modal_id="ai_analysis_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="ai_analysis_exception_modal_content",
                button_id="ai_analysis_exception_modal_close",
            ),
        ],
    )

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
                        id="ai-submit-btn",
                        color="primary",
                        size="sm",
                        style={"borderRadius": "50%"},
                    ),
                ],
                className="ai-input-inner",
            ),
        ],
        className="ai-input-container",
    ),


def create_pattern_layout():
    return dbc.Row([
            dbc.Col(
                html.Div([
                        dbc.Row(
                            [
                                dbc.Col(
                                    search_input(),
                                    width=6,className="mx-auto mt-2",
                                ),
                                dbc.Col(
                                    create_control_card(),
                                    width=6,className="mx-auto mt-0"
                                ),
                            ],
                        ),
                        html.Hr(),
                        html.B("Logs Relevant to your search"),
                        html.Hr(),
                        dbc.Row([
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody([
                                        html.Div(id="ai-search-results", style={"overflowX": "auto"})
                                    ]),
                                ), width=12,
                            ),
                        ], className="mb-4"),
                        html.B("Help Me understand from the uploaded logs"),
                        html.Hr(),
                        dbc.Row([
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            html.Div(id="ai-log-patterns", style={"overflowX": "auto"}),
                                        ],
                                    ),
                                    id="ai-pattern-log-card",
                                ), width=12,
                            ),
                        ], className="mb-4"),
                        dbc.Button("Sync to global DB",
                        id="ai-save-to-db-btn", 
                        color="primary", 
                        size="xl", 
                        ),
                    ])
            ),
        ])

def pattern_page():
    return html.Div(
        style={
        "height": "100vh",
        "overflowY": "auto",
        "padding": "15px",
        "fontSize": "14px",
        "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[
            create_pattern_layout(),
        ]
    )
layout = pattern_page()
