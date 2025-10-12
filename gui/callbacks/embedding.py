import os
from pathlib import Path
from dash import ctx, html, Input, Output, State, callback
import dash
from gui.app_instance import dbm
from logai.pattern import Pattern
import time
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.embedding import VectorEmbedding, read_status, update_file_status

@callback(
    Output("embed-templates-table", "data"),
    Input("embed-file-select", "value"),
    State("current-project-store", "data")
)
def update_templates_table(selected_file, project_data):
    if not selected_file or not project_data or not project_data.get("project_id"):
        return []

    try:    
        project_id = project_data["project_id"]
        user_id = project_data.get("user_id")

        filename, file_path, original_name, file_size, _ = dbm.get_project_file_info(project_id, selected_file)
    except Exception as e:
        print(f"Embedding Temporary Error retriving data {e}")
        return []
    
    if not os.path.getsize(file_path):
        return []

    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
    
    # Parse logs and extract patterns
    parser = Pattern(project_dir=project_dir)
    result_df, result_df_path = parser.parse_logs(file_path)
    
    if result_df is None or result_df.empty:
        return []

    # get subset of columns with template and count
    template_counts = result_df['template'].value_counts().reset_index()
    template_counts.columns = ['template', 'count']
    template_counts['log_type'] = ''
    template_counts['meaning'] = ''
    return template_counts.to_dict('records')

def get_pipeline_status(project_dir):
    status = read_status(project_dir)
    queued_files, parsed_files, done_files = [], [], []
    color_map = {"queued": "gray", "processing": "blue", "done": "orange", "indexed": "green", "error": "red"}

    for fname, info in sorted(status.items()):
        state = info.get("state", "queued")
        color = color_map.get(state, "gray")
        badge = html.Div(
            fname,
            style={
                "padding": "4px 6px",
                "margin": "2px 0",
                "background-color": color,
                "color": "white",
                "border-radius": "4px",
            }
        )
        if state == "queued":
            queued_files.append(badge)
        elif state == "parsed":
            parsed_files.append(badge)
        elif state == "indexed":
            done_files.append(badge)

    all_done = all(info.get("state") in ["indexed", "error"] for info in status.values()) if status else False
    print(f"All done: {all_done}")
    return queued_files, parsed_files, done_files, all_done

@callback(
    Output("embed-queued-card", "children", allow_duplicate=True),
    Output("embed-parsed-card", "children", allow_duplicate=True),
    Output("embed-done-card", "children", allow_duplicate=True),
    Input("sync-pipeline-icon", "n_clicks"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def sync_pipeline_status(sync_pipeline_btn, project_data):
    if not project_data or not project_data.get("project_id"):
        return dash.no_update, dash.no_update, dash.no_update

    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')

    if ctx.triggered:
        prop_id = ctx.triggered[0]["prop_id"].split(".")[0]    
        if prop_id == "sync-pipeline-icon":
            queued_files, parsed_files, done_files, _ = get_pipeline_status(project_dir)
            return queued_files, parsed_files, done_files

    return dash.no_update, dash.no_update, dash.no_update

@callback(
    Output("embed-queued-card", "children"),
    Output("embed-parsed-card", "children"),
    Output("embed-done-card", "children"),
    Output("emdedding-status-interval", "disabled"),
    Input("emdedding-status-interval", "n_intervals"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def update_status(_interval, project_data):
    if not project_data or not project_data.get("project_id"):
        return dash.no_update,dash.no_update, dash.no_update, False
        
    #print("Embedding status interval triggered")
    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')

    files = dbm.get_project_files(project_id)
    if not files:
        return dash.no_update,dash.no_update, dash.no_update, False
    
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue

        status = read_status(project_dir).get(original_name, {})
        if status.get("state") == "queued":
                # check if parquet file exists
                parquet_path = project_dir / f"{filename}.parquet"
                if parquet_path.exists():
                    update_file_status(project_dir, original_name, "parsed", {"queued_at": time.time()})

    print("Checked for queued files to parse")
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue

        status = read_status(project_dir).get(original_name, {})
        if status.get("state") == "parsed":
                # check if parquet file exists
                parquet_path = project_dir / f"{filename}.parquet"
                if parquet_path.exists():
                    #faiss_scheduler.enqueue_file(project_dir, parquet_path)
                    embedding  = VectorEmbedding()
                    embedding.add_templates(project_dir, parquet_path, original_name)
                    update_file_status(project_dir, original_name, "indexed", {"queued_at": time.time()})
                    break  # Enqueue one file at a time
    
    print("Checked for parsed files to index")
    queued_files, parsed_files, done_files, all_done = get_pipeline_status(project_dir)
    return queued_files, parsed_files, done_files, all_done