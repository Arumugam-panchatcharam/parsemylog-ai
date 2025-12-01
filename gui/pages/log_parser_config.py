import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table
from .utils import (
    create_modal
)

def left_card():
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("Category", className="fw-bold text-secondary"),
                    dcc.Dropdown(id="parser-config-category-select", placeholder="Select Category"),
                ], width=12),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-plus me-1"), "Add Category"],
                    id="parser-config-add-category-btn", color="info", size="sm"),
                ], width=5),
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-trash me-1"), "Delete Category"],
                        id="parser-config-del-category-btn", outline=True, color="danger", size="sm",
                    ),
                ], width=6),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Label("Issue Title", className="fw-bold text-secondary"),
                    dcc.Dropdown(id="parser-config-issue-select", placeholder="Select or Add New Issue"),
                ], width=12),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-plus me-1"), "Add Issue"],
                               id="parser-config-add-issue-btn", color="secondary", size="sm"),
                ], width=4),
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-trash me-1"), "Delete Issue"],
                        id="parser-config-del-issue-btn", outline=True, color="danger", size="sm"),
                ], width=8)
            ], className="mb-2"),
    ])
    ],className="border-0 shadow-0 bg-transparent")

def right_card():
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                    html.Label("File Name", className="fw-bold text-secondary"),
                    dbc.Input(id="parser-config-file-name", placeholder="File Name without extension"),
                ], width=4),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Label("Cause / Description", className="fw-bold text-secondary"),
                    dbc.Textarea(id="parser-config-cause-input", placeholder="Enter Root Cause/Issue Description", 
                                 style={"width": "100%", "height": "100px"})
                ], width=8)
            ], className="mb-2"),
        ])
    ],className="border-0 shadow-0 bg-transparent")

def create_log_parser_config_layout():
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([
                   left_card(),
                ], width=4),
                dbc.Col([
                   right_card(),
                ], width=8),
            ], className="mb-2"),

            # --- Regex Pattern Table ---
            html.H4("🔍 Regex Patterns"),
            dash_table.DataTable(
                id="parser-config-regex-table",
                columns=[
                    {"name": "Type", "id": "type", "presentation": "dropdown"},
                    {"name": "Pattern", "id": "pattern"},
                    {"name": "Description", "id": "description"}
                ],
                dropdown={
                    "type": {"options": [{"label": "STD", "value": "STD"}, {"label": "CTR", "value": "CTR"}]}
                },
                editable=True,
                row_deletable=True,
                style_table={"overflowX": "auto"},
                style_cell={"textAlign": "left", "padding": "5px"},
                #style_header={"backgroundColor": "#f1f3f6", "fontWeight": "bold"}
            ),

            # Buttons for pattern editing
            dbc.Row([
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-plus me-1"), "Add Pattern"],
                               id="parser-config-add-pattern-btn", color="secondary", size="sm", className="mt-2 me-2"),
                ])
            ], className="mb-2 mt-2"),
            dbc.Row([
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-save me-1"), "Save Config"],
                               id="parser-config-save-btn", color="success", size="sm", className="mt-2 me-2"),

                ], width="auto", class_name="mx-auto"),
            ], className="mb-3 mt-2"),
            dbc.Row([
                dbc.Col([
                    dcc.Upload(
                        id="parser-config-load-json",
                        children=dbc.Button(
                            [html.I(className="fas fa-upload me-1"), "Load Config JSON"],
                            color="primary", size="sm", className="mt-2 me-2"
                        ),
                        multiple=False,
                        style={"display": "inline-block"}
                    ),
                ], width="2"),
                dbc.Col([
                    dbc.Button(
                        [html.I(className="fas fa-download me-1"), "Export Config JSON"],
                        id="parser-config-export-json", color="secondary", size="sm",className="mt-2 me-2"
                    ),
                    dcc.Download(id="parser-config-download-json"),
                ], width="2"),
            ], className="mb-3"),
            html.Hr(),
            html.H4("📘 Current Configuration"),
            dash_table.DataTable(
                id='parser-config-table',
                columns=[
                    {"name": "Category", "id": "Category"},
                    {"name": "Title", "id": "Title"},
                    {"name": "FileName", "id": "FileName"},
                    {"name": "Pattern Count", "id": "PatternCount"},
                ],
                data=[],
                editable=True,
                dropdown={
                    'log_type': {
                        'options': [
                            {'label': 'STD', 'value': 'STD'},
                            {'label': 'CTR', 'value': 'CTR'},
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
                page_size=15
            ),
        ]),
        # --- ADD CATEGORY MODAL ---
        dbc.Modal([
            dbc.ModalHeader("Add New Category"),
            dbc.ModalBody([
                dbc.Label("Enter new category name:"),
                dbc.Input(id="parser-config-new-category-name", placeholder="e.g., WLAN_Issues"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Add", id="parser-config-confirm-add-category", color="success", className="me-2"),
                dbc.Button("Cancel", id="parser-config-cancel-add-category", color="secondary")
            ])
        ], id="parser-config-add-category-modal", is_open=False),

        # --- ADD ISSUE MODAL ---
        dbc.Modal([
            dbc.ModalHeader("Add New Issue"),
            dbc.ModalBody([
                dbc.Label("Issue Title:"),
                dbc.Input(id="parser-config-new-issue-title", placeholder="Enter new issue title", className="mb-3"),
                dbc.Label("File Name:"),
                dbc.Input(id="parser-config-new-issue-file", placeholder="wifi_vendor_driver", className="mb-3"),
                dbc.Label("Cause / Description:"),
                dbc.Textarea(id="parser-config-new-issue-cause", placeholder="Enter cause", style={"height": "80px"}, className="mb-3"),
            ]),
            dbc.ModalFooter([
                dbc.Button("Add", id="parser-config-confirm-add-issue", color="success", className="me-2"),
                dbc.Button("Cancel", id="parser-config-cancel-add-issue", color="secondary")
            ])
        ], id="parser-config-add-issue-modal", is_open=False),
        # --- confirm DELETE MODAL ---
        dbc.Modal([
            dbc.ModalHeader("Confirm Delete"),
            dbc.ModalBody(id="parser-config-delete-confirm-text"),
            dbc.ModalFooter([
                dbc.Button("Yes, Delete", id="parser-config-confirm-delete", color="danger"),
                dbc.Button("Cancel", id="parser-config-cancel-delete", color="secondary", className="ms-2")
            ])
        ], id="parser-config-delete-modal", is_open=False),
        create_modal(
        modal_id="parser_config_dwld_exception_modal",
        header="Alert",
        content="An exception occurred. Please click OK to continue.",
        content_id="parser_config_dwld_exception_modal_content",
        button_id="parser_config_dwld_exception_modal_close",
    ),
    ],)

def log_parser_config_page():
    return html.Div(
        style={
        "height": "100vh",
        "overflowY": "auto",
        "padding": "15px",
        "fontSize": "12px",
        "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[
            create_log_parser_config_layout(),
        ]
    )

layout = log_parser_config_page()
