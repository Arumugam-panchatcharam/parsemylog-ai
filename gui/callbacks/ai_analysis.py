import dash
from dash import ctx, html, Input, Output, State, callback
from pathlib import Path
from logai.utils.constants import UPLOAD_DIRECTORY

from logai.embedding import VectorEmbedding

@callback(
    Output("ai-embed-search-results", "data"),
    Output("ai-search-results", "children"),
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
        return dash.no_update, dash.no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            if prop_id == "ai-search-btn":
                if not query:
                    return dash.no_update, dash.no_update, True, "Please enter a query."
                
                project_id = project_data["project_id"]
                user_id = project_data.get("user_id")

                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                embedding  = VectorEmbedding()
                embedding_results = embedding.search(project_dir, query, top_k=10)
                #print("Search results ", embedding_results)

                if not embedding_results:
                    return dash.no_update, dash.no_update, True, "No similar templates found."

                data = [
                    {
                        "filename": r.get("filename", "-"),
                        "template": r.get("template", ""),
                        "frequency": r.get("frequency", "-"),
                        "similarity": round(r.get("similarity", 0.0), 4),
                    }
                    for r in embedding_results
                ]
                #print("Data ", data)
                return data, "", False, ""
            else:
                return [], "", False, ""
    except Exception as error:
        return True, str(error)


'''
@callback(
    Output("task-id", "children"),
    Input("ai-search-btn", "n_clicks"),
    State("ai-query-input", "value"),
    prevent_initial_call=True
)
def start_search(n_clicks, query):
    if not query:
        return "Please enter a query."
    task = search_templates_task.delay(query, top_k=10)
    return f"Task submitted. ID = {task.id}"


@callback(
    Output("ai-search-results", "children"),
    Input("check-btn", "n_clicks"),
    State("task-id", "children"),
    State("current-project-store", "data"),
    prevent_initial_call=True
)
def check_status(n_clicks, task_id_text):
    if not task_id_text or "ID =" not in task_id_text:
        return "No task ID found."

    task_id = task_id_text.split("ID =")[1].strip()
    result = AsyncResult(task_id, app=celery)

    if not result.ready():
        return "Task still running..."
    if result.failed():
        return "Task failed."

    results = result.get()
    children = []
    for r in results:
        provenance = [f"[{p['project']}] {p['user']} ({p['file']})" for p in r["provenance"]]
        children.append(html.Div([
            html.H4(r["template"]),
            html.P(f"Type: {r['log_type']} | Meaning: {r['meaning']} | Distance: {r['distance']:.4f}"),
            html.Ul([html.Li(p) for p in provenance])
        ], style={"margin": "10px", "padding": "10px", "border": "1px solid #ddd"}))
    return children


def similarity_to_color(similarity: float) -> str:
    """
    Convert cosine similarity (0–1) to a badge color.
    High similarity -> green, medium -> yellow, low -> grey.
    """
    if similarity >= 0.9:
        return "success"   # bright green
    elif similarity >= 0.75:
        return "warning"   # yellow
    elif similarity >= 0.6:
        return "secondary" # light grey
    else:
        return "dark"      # dark grey


# -------------------------
# CALLBACK: Search Handler
# -------------------------
@app.callback(
    Output("results", "children"),
    Input("search-btn", "n_clicks"),
    State("query", "value"),
    prevent_initial_call=True
)
def search_logs(n_clicks, query):
    if not query:
        return dbc.Alert("Please enter a query.", color="warning")

    # Encode query
    qemb = model.encode([query], normalize_embeddings=True).astype('float32')
    D, I = index.search(qemb, 10)

    results = []
    for dist, idx in zip(D[0], I[0]):
        if idx < len(metadata):
            m = metadata[int(idx)].copy()
            m["similarity"] = float(dist)
            results.append(m)

    # Sort by similarity descending
    results = sorted(results, key=lambda x: x["similarity"], reverse=True)

    cards = []
    for r in results:
        color = similarity_to_color(r["similarity"])
        badge = dbc.Badge(f"{r['similarity']:.3f}", color=color, className="ms-2", pill=True)

        # Slightly fade low-similarity cards
        opacity = 1.0 if r["similarity"] >= 0.75 else 0.6
        bg_color = "#222" if r["similarity"] >= 0.75 else "#333"

        cards.append(
            dbc.Card([
                dbc.CardBody([
                    html.H5([
                        f"{r['file']}",
                        html.Span(" – Similarity: ", style={"fontSize": "0.9em"}),
                        badge
                    ], className="card-title text-light"),
                    html.P(
                        r["text"],
                        className="card-text text-light",
                        style={"opacity": opacity, "fontSize": "0.95em"}
                    ),
                ])
            ], className="mb-3 rounded-3 border-0 shadow-sm", style={"backgroundColor": bg_color})
        )

    if not cards:
        return dbc.Alert("No similar logs found.", color="info")

    return cards
'''