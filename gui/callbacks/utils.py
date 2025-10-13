from dash import Input, Output, callback

from gui.app_instance import dbm
from logai.utils.constants import NON_TEXT_EXTENSIONS, IGNORE_FILENAME_LIST

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
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue   
        if any(filename.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
            continue
        if any(ign.lower() in original_name.lower() for ign in IGNORE_FILENAME_LIST):
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
    Output("embed-file-select", "options"),
    Output("embed-file-select", "value"),
    [
        Input("current-project-store", "data"),
    ],
)
def update_ai_analysis_file_list(project_data):
    if not project_data or not project_data.get("project_id"):
        return [], ""
    
    project_id = project_data["project_id"]
    files = dbm.get_project_files(project_id)

    options = []
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue   
        if any(filename.endswith(ext) for ext in NON_TEXT_EXTENSIONS):
            continue
        if any(ign.lower() in original_name.lower() for ign in IGNORE_FILENAME_LIST):
            continue
        options.append({
            "label": f"{original_name} ({round(file_size / (1024*1024), 2)} MB)",
            "value": filename
        })

    if len(options) > 0:
        return options, options[0]["label"]
    else:
        return options, ""