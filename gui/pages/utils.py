import dash_bootstrap_components as dbc
from dash import dcc, html, dash_table

STYLE = {
    "json-output": {
        "overflow-y": "scroll",
        "height": "calc(90% - 25px)",
        "border": "thin lightgrey solid",
    },
    "tab": {"height": "calc(98vh - 80px)"},
    "log-output": {
        "overflow-y": "scroll",
        "height": "calc(90% - 25px)",
        "border": "thin lightgrey solid",
        "white-space": "pre-wrap",
    },
}
TABLE_HEADER_COLOR = "lightskyblue"
TABLE_DATA_COLOR = "rgb(239, 243, 255)"

def create_run_button(button_id):
    return dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                children=[
                                    dbc.Button([html.I(className="fas fa-bar-chart me-2"),"Run"], id=button_id, color="primary", outline=True)
                                ],
                            #children=[html.Button(id=button_id, children="Run", n_clicks=0)],
                            style={"textAlign": "center"},
                            ),
                        ]
                    ),
                ]
            )


def create_modal(modal_id, header, content, content_id, button_id):
    modal = html.Div(
        [
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(header)),
                    dbc.ModalBody(content, id=content_id),
                    dbc.ModalFooter(
                        dbc.Button(
                            "Close", id=button_id, className="ml-auto", n_clicks=0
                        )
                    ),
                ],
                id=modal_id,
                is_open=False,
            ),
        ]
    )
    return modal


def create_upload_file_layout():
    return html.Div(
        id="upload-file-layout",
        children=[
            #html.Br(),
            html.B("Upload Log File"),
            dcc.Upload(
                id="upload-data",
                children=html.Div(["Drag and Drop or Select a File"]),
                style={
                    # "width": "300px",
                    "height": "50px",
                    "lineHeight": "50px",
                    "borderWidth": "1px",
                    "borderStyle": "dashed",
                    "borderRadius": "5px",
                    "textAlign": "center",
                    "margin": "10px",
                },
                multiple=True,
            ),
        ],
    )

