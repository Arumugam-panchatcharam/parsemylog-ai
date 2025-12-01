import dash_bootstrap_components as dbc
from dash import dcc, html
from dash.dash_table import DataTable
from .utils import (
    create_modal
)

def create_file_setting_layout():
    return html.Div(
        id="embed-file-setting-layout",
        children=[
            html.H5("Log Files"),
            dcc.Dropdown(id="embed-file-select", 
                         options=[],
                         value=[],
                         #multi=True,
                         placeholder="select a file...",
                        ),
        ],
    )

def create_control_card():
    return html.Div(
        id="embed-control-card",
        children=[
            create_file_setting_layout(),
            #create_run_button("embed-start-indexing-btn"),
            create_modal(
                modal_id="embed_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="embed_exception_modal_content",
                button_id="embed_exception_modal_close",
            ),
        ],
    )

def status_update():
    card_style = {
        "height": "360px",
        "padding": "12px",
        "borderRadius": "10px",
        "overflowY": "auto",
        "boxShadow": "0 2px 8px rgba(0,0,0,0.1)",
        "border": "1px solid #ddd",
        "backgroundColor": "#fff",
    }

    return html.Div(
        style={
            "display": "flex",
            "gap": "20px",
            "justifyContent": "space-between",
            "width": "100%",
        },
        children=[
            html.Div([
                html.H5("Queued Files", style={"fontWeight": "bold", "marginBottom": "5px"}),
                html.Div(id="embed-queued-card", style={
                    **card_style,
                    "backgroundColor": "#f0f0f0"
                })
            ], style={"flex": 1, "display": "flex", "flexDirection": "column"}),

            html.Div([
                html.H5("Parsed Files", style={"fontWeight": "bold", "marginBottom": "5px"}),
                html.Div(id="embed-parsed-card", style={
                    **card_style,
                    "backgroundColor": "#e0f7fa"
                })
            ], style={"flex": 1, "display": "flex", "flexDirection": "column"}),

            html.Div([
                html.H5("Indexed Files", style={"fontWeight": "bold", "marginBottom": "5px"}),
                html.Div(id="embed-done-card", style={
                    **card_style,
                    "backgroundColor": "#e8f5e9"
                })
            ], style={"flex": 1, "display": "flex", "flexDirection": "column"}),
        ]
    )

def templates_table():
    return html.Div([
        DataTable(
            id='embed-templates-table',
            columns=[
                {'id': 'template', 'name': 'Template'},
                {'id': 'count', 'name': 'Count'},
                {'id': 'log_type', 'name': 'Log Type', 'presentation': 'dropdown'},
                {'id': 'meaning', 'name': 'Meaning', 'presentation': 'input'}
            ],
            data=[],
            editable=True,
            dropdown={
                'log_type': {
                    'options': [
                        {'label': 'ERROR', 'value': 'ERROR'},
                        {'label': 'WARN', 'value': 'WARN'},
                        {'label': 'INFO', 'value': 'INFO'},
                        {'label': 'DEBUG', 'value': 'DEBUG'}
                    ]
                }
            },
            css=[{"selector": ".dropdown", "rule": "position: static"}],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'whiteSpace': 'normal',
                'height': 'auto'
            },
            style_cell_conditional=[
            {
                'if': {'column_id': 'template'},
                'width': '60%'
            },
            {
                'if': {'column_id': 'meaning'},
                'width': '30%'
            },
            {
                'if': {'column_id': 'count'},
                'width': '5%'
            },
            {
                'if': {'column_id': 'log_type'},
                'width': '5%'
            }
        ],
            page_size=15
        )
    ])


def create_embedding_layout():
    return dbc.Row([
            dbc.Col(
                html.Div([
                    dbc.Row(
                        [
                            dbc.Col(
                                status_update(),
                                width=12,className="mx-auto mt-4",
                            ),
                        ],
                        ),
                        dbc.Button("Sync Pipeline Status", 
                            id="sync-pipeline", color="primary", size="sm", className="mx-auto m-2"),
                        dbc.Button("Download Templates", 
                            id="embed-download-templates", color="primary", size="sm", className="mx-2 m-2"),
                        dcc.Download(id="embed-download-templates-download"),
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Col(
                                    create_control_card(),
                                    width=4,className="mx-auto mt-0"
                                ),
                            ],
                        ),
                        html.H5("Templates"),
                        html.Hr(),
                        dbc.Row([
                            dbc.Col(
                                dbc.Card(
                                    dbc.CardBody([
                                                templates_table(),
                                            ]),
                                    ), width=12,
                                ),
                        ], className="mb-4"),
                        create_modal(
                        modal_id="embed_dwld_exception_modal",
                        header="An Exception Occurred",
                        content="An exception occurred. Please click OK to continue.",
                        content_id="embed_dwld_exception_modal_content",
                        button_id="embed_dwld_exception_modal_close",
                    ),
                ])
            ),
        ])

def embedding_page():
    return html.Div(
        style={
        "height": "100vh",
        "overflowY": "auto",
        "padding": "15px",
        "fontSize": "12px",
        "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[
            create_embedding_layout(),
            dcc.Interval(id="emdedding-status-interval", interval=5000, n_intervals=0),  # every 5 seconds
        ]
    )
layout = embedding_page()