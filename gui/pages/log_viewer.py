import dash_bootstrap_components as dbc
from dash import dcc, html

from dash_extensions import EventListener

CODE_STYLE = {
    'background': '#2d3748',
    'color': '#e2e8f0',
    'padding': '15px',
    'border-radius': '8px',
    'font-family': 'monospace',
    'font-size': '10px',
    'height': '800px',
    'overflow-y': 'auto',
    'white-space': 'pre-wrap'
}

SEARCH_STYLE = {
    'background': '#2d3748',
    'color': '#e2e8f0',
    'padding': '15px',
    'border-radius': '8px',
    'font-family': 'monospace',
    'font-size': '9px',
    'height': '400px',
    'overflow-y': 'auto',
    'white-space': 'pre-wrap'
}

UPLOAD_STYLE = {
    'border': '2px dashed #dee2e6',
    'border-radius': '8px',
    'padding': '20px',
    'text-align': 'center',
    'background': '#f8f9fa',
    'min-height': '100px'
}

def create_log_viewer_layout():
    return html.Div(
        style={"height": "100vh", "overflowY": "auto", "padding": "15px"},
        children=[
            # 1. Upload Section
            dbc.Card([
                dbc.CardBody([
                    dcc.Upload(
                        id='file-upload',
                        children=html.Div([
                            html.H5("Drag & Drop Files Here", className="mb-1"),
                            html.P("or click to browse", className="text-muted small mb-0"),
                        ], style=UPLOAD_STYLE),
                        multiple=True
                    ),
                    html.Div(id="upload-feedback", className="mt-2 small text-success")
                ])
            ], id="upload-card", className="mb-3 shadow-sm"),

            # 2. Main Controls Section
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        # File Explorer Column
                        dbc.Col([
                            html.H6([
                                html.I(className="fas fa-folder-tree me-2 text-info"),
                                "File Explorer"
                            ]),
                            dbc.Row([
                                dbc.Col(html.Small(id="file-stats", className="text-muted")),
                                dbc.Col(
                                    dbc.Button(html.I(className="fas fa-sync-alt"),
                                               id="refresh-files-icon",
                                               size="sm",
                                               color="secondary",
                                               outline=True),
                                    width="auto"
                                )
                            ], className="mb-2 justify-content-between"),
                            html.Div(id="file-list",
                                     className="border rounded bg-white p-2",
                                     style={"maxHeight": "220px", "overflowY": "auto"})
                        ], width=4),

                        # Search Column
                        dbc.Col([
                            html.H6([
                                html.I(className="fas fa-search me-2 text-primary"),
                                "Search"
                            ]),
                            dbc.InputGroup([
                                dbc.Input(id="search-input", placeholder="Search pattern", size="sm"),
                                dbc.Button("Go", id="search-btn", size="sm", color="primary")
                            ], className="mb-3"),
                            html.Div("Quick Patterns:", className="small text-muted mb-2"),
                            dbc.ButtonGroup([
                                dbc.Button("ERROR", id="btn-error", size="sm", color="danger", outline=True),
                                dbc.Button("WARN", id="btn-warn", size="sm", color="warning", outline=True)
                            ], className="w-100 mb-2"),
                            dbc.ButtonGroup([
                                dbc.Button("IP", id="btn-ip", size="sm", color="info", outline=True),
                                dbc.Button("Time", id="btn-time", size="sm", color="secondary", outline=True)
                            ], className="w-100")
                        ], width=4),

                        # Notes Column
                        dbc.Col([
                            html.H6([
                                html.I(className="fas fa-sticky-note me-2 text-warning"),
                                "Notes"
                            ]),
                            dbc.Textarea(
                                id="notes-area",
                                placeholder="Write analysis notes here...",
                                style={"height": "220px", "fontSize": "12px"},
                                className="form-control"
                            ),
                            html.Div([
                                dbc.Button("Save Notes", id="save-notes-btn", color="primary", size="sm", className="me-2"),
                                html.Small(id="save-status", className="text-success me-2"),
                            ], className="mt-2 justify-content-between")
                        ], width=4)
                    ])
                ])
            ], className="mb-3 shadow-sm"),

            # 3. Log Viewer
            dbc.Card([
                dbc.CardBody([
                    html.Div(id="file-header", className="mb-2 fw-bold"),
                    html.Div(id="file-content",
                             className="bg-dark text-light p-2 border rounded",
                             style=CODE_STYLE),
                    html.Div(id="pagination-controls", className="mt-2 text-center")
                ])
            ], className="mb-3 shadow-sm"),

            # 4. Search Results Viewer
            dbc.Card([
                dbc.CardBody([
                    EventListener(
                        id="results-listener",
                        events=[{"event": "dblclick",
                                     "props": [
                                    "target.dataset.line",
                                    "target.dataset.page",
                                    "target.parentElement.dataset.line",
                                    "target.parentElement.dataset.page"
                                    ]
                                }],
                        children=html.Div(id="search-results",
                                          className="bg-dark text-light p-2 border rounded",
                                          style=SEARCH_STYLE)
                    )
                ])
            ], className="mb-3 shadow-sm"),
        ]
    )


layout = create_log_viewer_layout()
