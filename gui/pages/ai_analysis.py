import dash_bootstrap_components as dbc
from dash import html

 
def create_ai_analysis_layout():
    return dbc.Row(
        [
            dbc.Col(
                html.Div(
                    [
                    dbc.Row([
                        dbc.Col([
                              dbc.Button("Run AI Analysis", id="run-ai-script-btn", color="primary"),
                              html.Pre(id="ai-script-output", className="mt-3", style={
                              "whiteSpace": "pre-wrap",
                              "maxHeight": "500px",
                              "overflowY": "auto"
                                })
                            ], width=8)
                        ], justify="center")
                ])
            ),
        ])
layout = create_ai_analysis_layout()
