from dash import Input, Output, callback

from gui.app_instance import dbm

@callback(
    Output("file-select", "options"),
    Output("file-select", "value"),
    [
        Input("refresh-filelist-icon", "n_clicks"),
        Input("current-project-store", "data"),
     ],
)
def update_file_list(n_clicks, project_data):
    if not project_data or not project_data.get("project_id"):
        return [], ""
    
    project_id = project_data["project_id"]
    files = dbm.get_project_files(project_id)

    options = []
    non_text_extensions = ['.xls', '.xlsx', '.tgz', '.zip']
    ignore_filename_list = ['telemetry2']
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue   
        if any(filename.endswith(ext) for ext in non_text_extensions):
            continue
        if any(ign.lower() in original_name.lower() for ign in ignore_filename_list):
            continue

        options.append({
            "label": f"{original_name} ({round(file_size / (1024*1024), 2)} MB)",
            "value": filename
        })

    if len(options) > 0:
        return options, options[0]["label"]
    else:
        return options, ""
    
@callback(
Output("ai-file-select", "options"),
Output("ai-file-select", "value"),
[
    Input("ai-refresh-filelist-icon", "n_clicks"),
    Input("current-project-store", "data"),
    ],
)
def update_ai_analysis_file_list(n_clicks, project_data):
    if not project_data or not project_data.get("project_id"):
        return [], ""
    
    project_id = project_data["project_id"]
    files = dbm.get_project_files(project_id)

    options = []
    non_text_extensions = ['.xls', '.xlsx', '.tgz', '.zip']
    ignore_filename_list = ['telemetry2']
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue   
        if any(filename.endswith(ext) for ext in non_text_extensions):
            continue
        if any(ign.lower() in original_name.lower() for ign in ignore_filename_list):
            continue
        options.append({
            "label": f"{original_name} ({round(file_size / (1024*1024), 2)} MB)",
            "value": filename
        })

    if len(options) > 0:
        return options, options[0]["label"]
    else:
        return options, ""