import dash
from dash import ctx, Input, Output, State, callback
from pathlib import Path
from logai.utils.constants import UPLOAD_DIRECTORY

from logai.embedding import VectorEmbedding

@callback(
    Output("ai-embed-search-results", "data"),
    Output("ai_exception_modal", "is_open"),
    Output("ai_exception_modal_content", "children"),
    [
        Input("ai-search-btn", "n_clicks"),
        Input("ai_exception_modal_close", "n_clicks"),
    ],
    State("ai-query-input", "value"),
    State("current-project-store", "data"),
    prevent_initial_call=True
)
def update_ai_embed_search_results(n_clicks, model_close, query, project_data):
    if not project_data or not project_data.get("project_id"):
        return dash.no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            print(prop_id)
            if prop_id == "ai-search-btn":
                if not query:
                    return dash.no_update, True, "Please enter a query."
                
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")

                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                embedding  = VectorEmbedding()
                embedding_results = embedding.search(project_dir, query, top_k=10)
                #print("Search results ", embedding_results)

                if not embedding_results:
                    return dash.no_update, True, "No similar templates found."

                data = [
                    {
                        "filename": r.get("filename", "-"),
                        "template": r.get("template", ""),
                        "frequency": r.get("frequency", "-"),
                        "similarity": round(r.get("similarity", 0.0), 4),
                    }
                    for r in embedding_results
                ]
                return data, False, ""
            else:
                return [], False, ""
    except Exception as error:
        return True, str(error)

