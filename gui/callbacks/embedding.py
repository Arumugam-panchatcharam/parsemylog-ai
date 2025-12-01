import os
import re
import pandas as pd
from pathlib import Path
from dash import dcc, ctx, html, Input, Output, State, callback, no_update
import dash
from gui.app_instance import dbm
from logai.pattern import Pattern
import time
from logai.utils.constants import UPLOAD_DIRECTORY
from logai.utils.constants import NON_TEXT_EXTENSIONS, IGNORE_FILENAME_LIST
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
    Input("sync-pipeline", "n_clicks"),
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
        if prop_id == "sync-pipeline":
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

def export_df_to_csv(files):
    df_list = []
    
    for filename, file_path, original_name, _, _ in files:
        if not os.path.exists(file_path) or not os.path.getsize(file_path):
            continue
        if any(filename.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
            continue
        if any(ign.lower() in original_name.lower() for ign in IGNORE_FILENAME_LIST):
            continue

        parquet_path = Path(file_path + ".parquet")
        if not parquet_path.exists():
            continue

        df = pd.read_parquet(parquet_path)

        # Drop unwanted columns
        df = df.drop(columns=["timestamp", "loglines", "parameter_list"], errors="ignore")
        df['template'] = df['template'].astype(str)
        
        ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
        df['template'] = df['template'].apply(lambda x: ANSI_RE.sub('', x))

        # Remove any remaining non-printable ASCII chars
        df['template'] = df['template'].apply(lambda x: re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', x))
        
        result_df = df['template'].value_counts().reset_index()
        result_df.columns = ['template', 'count']

        result_df["filename"] = original_name

        # Reorder columns
        result_df = result_df[["filename", "count", "template"]]

        df_list.append(result_df)

    if not df_list:
        return None

    # Merge all files
    combined_df = pd.concat(df_list, ignore_index=True)

    return combined_df

@callback(
    Output("embed-download-templates-download", "data"),
    Output("embed_dwld_exception_modal", "is_open"),
    Output("embed_dwld_exception_modal_content", "children"),
    Input("embed-download-templates", "n_clicks"),
    State("current-project-store", "data"),
    prevent_initial_call=True,
)
def download_templates(n_clicks,  project_data):
    if not project_data or not project_data.get("project_id"):
        return  no_update, False, ""
    
    try:
        if ctx.triggered:
            prop_id = ctx.triggered[0]["prop_id"].split(".")[0]
            
            if prop_id == "embed-download-templates":
                project_id = project_data["project_id"]
                project_name = project_data["project_name"]
                user_id = project_data.get("user_id")
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                try:
                    files = dbm.get_project_files(project_id)
                except Exception as e:
                    return no_update, True, f"Embedding Temporary Error retrieving data: {str(e)}"

                df = export_df_to_csv(files)
                if df is None or df.empty:
                    return no_update, True, "No templates available for download."
                    
                excel_name = f"Unique-Patterns-{project_name}.xlsx"
                excel_path = project_dir / excel_name
                #print(f"Exporting templates to {excel_path}")
                df.to_excel(excel_path, index=False)
                return dcc.send_file(excel_path), False, ""

            elif prop_id == "embed_dwld_exception_modal_close":
                return no_update, False, ""
        else:
            return no_update, False, ""
    except Exception as error:
        return no_update, True, str(error)