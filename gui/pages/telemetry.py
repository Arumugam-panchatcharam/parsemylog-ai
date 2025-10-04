import dash_bootstrap_components as dbc
from dash import dcc, html

from .utils import (
    create_modal,
    create_run_button,
)


def create_control_card():
    return html.Div(
        id="control-card",
        children=[
            create_run_button("telemetry-btn"),
            create_modal(
                modal_id="telemetry_exception_modal",
                header="An Exception Occurred",
                content="An exception occurred. Please click OK to continue.",
                content_id="telemetry_exception_modal_content",
                button_id="telemetry_exception_modal_close",
            ),
        ],
    )

def create_timeseries_grapy_layout():
    return html.Div(
        children=[
            dcc.Graph(id="telemetry-time-series"),
        ],
        # style={
        #     'display': 'inline-block',
        #     'width': '59%'
        # },
    )


def create_telemetry_layout():
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    [
                        html.H4("Telemetry Summarizaton"),
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Col(
                                    create_control_card(),
                                    width=4,
                                ),
                                dbc.Col(dbc.Card([
                                    dbc.CardHeader("Device Info"),
                                    dbc.CardBody(id="dev-summary-card", children=html.Div("Click 'Run' to load summary."))
                                ]), width=4),
                                dbc.Col(dbc.Card([
                                    dbc.CardHeader("Device Status"),
                                    dbc.CardBody(id="dev-status-card", children=html.Div("Click 'Run' to load summary."))
                                ]), width=4),
                            ],
                        ),
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Card(
                                    dbc.CardBody(
                                        [
                                            dcc.Loading(
                                                id="process-table-load",
                                                children=[
                                                    dbc.Row(
                                                        dbc.Col(html.Div(id="process-table"))
                                                    )
                                                ],
                                                type="default",
                                            )
                                        ]
                                    ),
                                    id="process_table_card",
                                    style={"maxwidth": "900px"},
                                ),
                            ],
                        ),
                    ]
                )
            ),
        ]
    )

def telemetry_page():
    return html.Div(
        style={"height": "100vh", "overflowY": "auto", "padding": "15px"},
        children=[
            create_telemetry_layout(),
        ],
    )

layout = telemetry_page()