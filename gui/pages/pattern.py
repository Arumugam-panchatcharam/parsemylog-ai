"""
Pattern Page Layout
====================

Displays domain-based Drain3 templates extracted by the rg+Drain3 pipeline.

Instead of selecting individual files, the user selects a domain
(wireless, platform, core_router, cellular, mesh) and the page shows
all templates from the rg pre-filtered + Drain3-parsed parquet cache.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html
from .utils import (
    create_run_button,
    create_modal,
)


def create_indexing_status():
    """Create the domain indexing status section with auto-refresh."""
    return html.Div([
        html.Div(id="indexing-status-container", className="mt-2"),
        dcc.Interval(id="indexing-status-interval", interval=5000, n_intervals=0),
    ])


def create_domain_selector():
    """Create domain selection dropdown with file filter and refresh button."""
    return html.Div(
        id="file-setting-layout",
        children=[
            html.Label("Domain"),
            dbc.Button(
                [html.I(className="fas fa-sync-alt")],
                id="refresh-filelist-icon",
                color="outline-secondary",
                size="sm",
                title="Refresh Domains",
                className="ms-2 mb-1",
            ),
            dcc.Dropdown(
                id="file-select",
                options=[],
                value=None,
                placeholder="Select a domain...",
                style={"width": "100%"},
            ),
            # File filter within the selected domain
            html.Label("Filter by File", className="mt-2"),
            dcc.Dropdown(
                id="file-filter-select",
                options=[],
                value=None,
                placeholder="All files (select domain first)",
                style={"width": "100%"},
                multi=True,
            ),
            html.Label("Time Interval", className="mt-2"),
            dcc.Slider(
                0, 3,
                step=None,
                marks={0: "1s", 1: "1min", 2: "1h", 3: "1d"},
                value=0,
                id="time-interval",
            ),
        ],
    )


def create_control_card():
    """Create the control card with domain selector and run button."""
    return html.Div(
        id="control-card",
        children=[
            create_domain_selector(),
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
    """Create the bar chart for template frequency distribution."""
    return html.Div(
        dcc.Graph(
            id="summary-scatter",
            style={"height": "45vh", "width": "100%", "margin": "0", "padding": "0"},
            config={
                "displayModeBar": True,
                "displaylogo": False,
                "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
            },
        ),
        style={
            "width": "100%",
            "padding": "5px",
            "backgroundColor": "#fff",
            "overflow": "hidden",
        },
        className="graph-container",
    )


def create_timeseries_graph_layout():
    """Create the time-series trend chart for a selected template."""
    return html.Div(
        dcc.Graph(
            id="pattern-time-series",
            style={"height": "45vh", "width": "100%", "margin": "0", "padding": "0"},
            config={
                "displayModeBar": True,
                "displaylogo": False,
                "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
            },
        ),
        style={
            "width": "100%",
            "padding": "5px",
            "backgroundColor": "#fff",
            "overflow": "hidden",
        },
        className="graph-container",
    )


def create_pattern_layout():
    """
    Create the main pattern analysis layout.

    Layout:
        Row 1: Domain selector + Run button | Summary card
        Row 2: Template frequency bar chart
        Row 3: Time-series trend chart
        Row 4: Selected template text
        Row 5: Dynamic values (parameters)
        Row 6: Matching log lines
    """
    return dbc.Row([
        # Hidden store to persist the active file filter for downstream callbacks
        dcc.Store(id="pattern-file-filter-store", data=None),
        dbc.Col(
            html.Div([
                dbc.Row([
                    dbc.Col(create_control_card(), width=6),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody([
                                html.H4("Summary"),
                                html.Div(id="log-summarization-summary"),
                                html.Hr(),
                                html.H6("Indexed Domains"),
                                create_indexing_status(),
                            ])
                        ),
                        width=6,
                    ),
                ]),
                html.B("Charts"),
                html.Hr(),
                dbc.Row([
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            dcc.Loading([create_summary_graph_layout()]),
                        ])),
                        width=12,
                    ),
                ]),
                html.Hr(),
                dbc.Row([
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            dcc.Loading([create_timeseries_graph_layout()]),
                        ])),
                        width=12,
                    ),
                ], className="mt-4"),
                html.B("Log Patterns"),
                html.Hr(),
                dbc.Card(
                    dbc.CardBody([
                        html.Div(id="log-patterns", style={"overflowX": "auto"}),
                    ]),
                    id="pattern-log-card",
                ),
                html.B("Dynamic Values"),
                html.Hr(),
                dbc.Row([
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            html.Div(id="log-dynamic-lists", style={"overflowX": "auto"}),
                        ])),
                        width=12,
                    ),
                ], className="mb-4"),
                html.B("Log Lines"),
                html.Hr(),
                dbc.Row([
                    dbc.Col(
                        dbc.Card(dbc.CardBody([
                            html.Div(id="select-loglines", style={"overflowX": "auto"}),
                        ])),
                        width=12,
                    ),
                ], className="mb-4"),
            ])
        ),
    ])


def pattern_page():
    """Create the full pattern page with scrolling container."""
    return html.Div(
        style={
            "height": "100vh",
            "overflowY": "auto",
            "padding": "15px",
            "fontSize": "12px",
            "fontFamily": "consolas, Arial, sans-serif",
        },
        children=[create_pattern_layout()],
    )


layout = pattern_page()
