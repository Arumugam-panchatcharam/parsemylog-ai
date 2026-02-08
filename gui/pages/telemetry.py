"""
Telemetry Page Layout
======================

Defines the Dash layout for the Telemetry 2.0 summarization tab.

Features:
    - Device Info card (MAC, serial, firmware, model).
    - Report Summary card (report counts, time range, profile stats).
    - Radio/SSID status labels (green/red badges).
    - Time-series Plotly charts for plottable numeric fields.
    - Run button below the summary cards.
"""

import dash_bootstrap_components as dbc
from dash import dcc, html

from .utils import (
    create_modal,
    create_run_button,
)


def create_telemetry_layout():
    """
    Create the main telemetry page layout.

    Layout structure:
        Row 1: Device Info card (6 cols) | Report Summary card (6 cols)
        Row 2: Run button (centered)
        Row 3: Radio/SSID status labels
        Row 4: Time-series charts (dynamically generated per plottable field)
    """
    return dbc.Row([
        dbc.Col(
            html.Div([
                html.H4("Telemetry 2.0 Summarization"),
                html.Hr(),

                # Row 1: Device Info + Report Summary (equal width)
                dbc.Row([
                    dbc.Col(
                        dbc.Card([
                            dbc.CardHeader("Device Info"),
                            dbc.CardBody(
                                id="dev-summary-card",
                                children=html.Div(
                                    "Click 'Run' to load telemetry.",
                                    className="text-muted",
                                ),
                            ),
                        ]),
                        width=6,
                    ),
                    dbc.Col(
                        dbc.Card([
                            dbc.CardHeader("Key Metric Trends"),
                            dbc.CardBody(
                                id="dev-status-card",
                                children=html.Div(
                                    "Click 'Run' to load telemetry.",
                                    className="text-muted",
                                ),
                            ),
                        ]),
                        width=6,
                    ),
                ]),

                # Row 2: Run button (centered) + modal
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            create_run_button("telemetry-btn"),
                        ], className="d-flex justify-content-center"),
                        create_modal(
                            modal_id="telemetry_exception_modal",
                            header="An Exception Occurred",
                            content="An exception occurred. Please click OK to continue.",
                            content_id="telemetry_exception_modal_content",
                            button_id="telemetry_exception_modal_close",
                        ),
                    ]),
                ], className="my-3"),

                # Row 3: Radio / SSID status labels
                dbc.Row([
                    dbc.Col(
                        dcc.Loading(
                            id="status-labels-load",
                            children=[html.Div(id="telemetry-status-labels")],
                            type="default",
                        ),
                    ),
                ]),

                # Row 4: Field tables placeholder (hidden, kept for callback output)
                html.Div(id="telemetry-field-tables", style={"display": "none"}),

                # Row 5: Time-series charts
                html.Hr(),
                dbc.Row([
                    dbc.Col(
                        dcc.Loading(
                            id="telemetry-charts-load",
                            children=[html.Div(id="telemetry-charts")],
                            type="default",
                        ),
                    ),
                ]),
            ])
        ),
    ])


def telemetry_page():
    """Create the full telemetry page with scrolling container."""
    return html.Div(
        style={"height": "100vh", "overflowY": "auto", "padding": "15px"},
        children=[create_telemetry_layout()],
    )


layout = telemetry_page()
