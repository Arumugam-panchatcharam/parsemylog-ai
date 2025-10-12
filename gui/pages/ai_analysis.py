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
    ),


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
        ),
        style={"marginTop": "10px"}
    )

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
                    html.H5("Tempaltes Relevant to your search"),
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
                    html.H5("AI Summarization of your logs"),
                    dbc.Row([
                        dbc.Col([
                            dbc.Alert(id="ai-status-display", color="info", className="mt-3"),
                            html.Pre(id="ai-search-results", className="mt-3 bg-light p-3 border rounded")
                        ], width=12)
                    ], className="mb-4"),
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
