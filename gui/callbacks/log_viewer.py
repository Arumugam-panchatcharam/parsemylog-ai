import os
import re
import base64
import json
import glob
import shutil
from pathlib import Path
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import ctx, clientside_callback
from dash import html, Input, Output, State, callback
from dash.dependencies import ALL

from gui.file_manager import FileManager
from gui.pages.highlighter import TextHighlighter

from logai.utils.constants import (
    MERGED_LOGS_DIR_NAME,
    LINES_PER_PAGE, UPLOAD_DIRECTORY
)

from gui.app_instance import dbm
from logai.pattern_scheduler import PatternScheduler

CODE_STYLE = {
    'background': '#2d3748',
    'color': '#e2e8f0',
    'padding': '15px',
    'border-radius': '8px',
    'font-family': 'monospace',
    'font-size': '12px',
    'height': '800px',
    'overflow-y': 'auto',
    'white-space': 'pre-wrap'
}

def no_files_uploaded():
    return html.Div([
            html.I(className="fas fa-file fa-2x text-muted mb-2"),
            html.P("No files uploaded yet", className="text-muted")
        ], className="text-center py-3")
    
# FILE UPLOAD
@callback(
    [Output('file-list', 'children'),
     Output('file-stats', 'children'),
     Output('notes-area', 'value'),
     Output("upload-card", "style"),
     ],
    [Input('file-upload', 'contents'),
     Input("current-project-store", "data"),
     Input('refresh-files-icon', 'n_clicks')],
    [State('file-upload', 'filename')],
)
def handle_upload(contents_list, project_data, refresh_clicks, filenames_list):
    if not project_data or not project_data.get("project_id"):
        return html.P([html.I(className="fas fa-info-circle me-2"), "No project selected"], 
                      className="text-muted"), "0 files",dash.no_update, dash.no_update
    
    project_id = project_data["project_id"]
    project_name = project_data["project_name"]
    user_id = project_data.get("user_id")
    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')

    if ctx.triggered_id == 'file-upload':
        if contents_list and filenames_list:
            if not isinstance(contents_list, list):
                contents_list = [contents_list]
                filenames_list = [filenames_list]
            
            results = []
            for content, filename in zip(contents_list, filenames_list):
                content_type, content_string = content.split(',')
                decoded = base64.b64decode(content_string)

                #project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                project_dir.mkdir(parents=True, exist_ok=True)
                file_path = project_dir / filename

                with open(file_path, 'wb') as f:
                    f.write(decoded)
            
            # process the uploadd files
            file_manager = FileManager()
            file_manager.process_uploaded_files(project_dir, project_name)

            for files in os.listdir(project_dir/MERGED_LOGS_DIR_NAME):
                dbm.save_local_file(Path(project_dir/MERGED_LOGS_DIR_NAME/files), project_id)
            
            archive = glob.glob(os.path.join(project_dir, '*.zip'))
            for file in archive:
                print("archive file name", file)
                if os.path.exists(project_dir/file):
                    dbm.save_local_file(Path(project_dir/file), project_id)
            
            # clean up the project directory
            shutil.rmtree(project_dir/MERGED_LOGS_DIR_NAME)

            feedback = dbc.Alert([html.P(r, className="mb-0 small") for r in results], 
                            color="success" if all("✅" in r for r in results) else "warning")
    
    try:
    # remove the uploaded files after processing
        files = dbm.get_project_files(project_id)
    except Exception as e:
        print(f"Viewer Temporary Error retriving data {e}")
        return no_files_uploaded(), "0 files", dash.no_update, dash.no_update
    
    scheduler = PatternScheduler(max_workers=2)
    scheduler.schedule_files(project_dir=project_dir, files=files)

    # Load notes if exist
    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
    notes_file_path = project_dir / "notes.txt"

    # Notes
    if notes_file_path.exists():
        with open(notes_file_path, 'r') as f:
            note_content = f.read()
    else:
        note_content = ""

    if not files:
        return no_files_uploaded(), "0 files", note_content, dash.no_update

    file_items = []
    for filename, _, original_name, file_size, _ in files:
        if file_size == 0:
            continue

        size_mb = round(file_size / (1024 * 1024), 2) if file_size else 0
        download_url = f"/download/{project_id}/{filename}"

        non_text_extensions = ['.xls', '.xlsx', '.tgz', '.zip']
        is_viewable = any(original_name.lower().endswith(ext) for ext in non_text_extensions) == False

        item = dbc.ListGroupItem([
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.I(className="fas fa-file-alt me-2 text-primary" if is_viewable else "fas fa-file me-2 text-secondary"),
                            html.Strong(original_name[:20] + "..." if len(original_name) > 20 else original_name)
                        ], className="mb-1"),
                        html.Small([
                            f"{size_mb} MB"
                        ], className="text-muted")
                    ]),
                    dbc.Col([
                        dbc.ButtonGroup([
                            dbc.Button([html.I(className="fas fa-eye")], 
                                     id={"type": "view-btn", "file_name": filename},
                                     color="outline-info", size="sm", 
                                     title="View") if is_viewable else html.Span(),
                            html.A([html.I(className="fas fa-download")], 
                                  href=download_url, className="btn btn-outline-primary btn-sm", 
                                  title="Download")
                        ], size="sm")
                    ], width="auto")
                ])
            ])
        ], className="border-0")
        file_items.append(item)

    return dbc.ListGroup(file_items, flush=True), f"{len(files)} file(s)", note_content, {"display": "none"}


def get_page_content(file_data, page_number):
    if not file_data:
        return None, "File not found"

    lines = file_data['lines']
    
    start_idx = (page_number - 1) * LINES_PER_PAGE
    end_idx = min(start_idx + LINES_PER_PAGE, len(lines))
    
    page_lines = lines[start_idx:end_idx]
    
    return {
        'lines': page_lines,
        'start_line': start_idx + 1,
        'end_line': end_idx,
        'total_lines': len(lines),
        'page_number': page_number,
        'total_pages': file_data['total_pages']
    }, None

def reset_page_data():
    return {'page': 1, 'timestamp': datetime.now().isoformat()}

# FILE VIEW
@callback(
    [Output('file-content', 'children'),
     Output('pagination-controls', 'children'),
     Output('current-file-store', 'data'),
     Output('current-page-store', 'data'),
     Output('pagination-trigger-store', 'data', allow_duplicate=True),
     ]
     ,
    [Input({'type': 'view-btn', 'file_name': ALL}, 'n_clicks'),
     State("current-project-store", "data"),
     ],
    prevent_initial_call=True
)
def view_file(n_clicks_list, project_data):
    select_file = dbc.Alert("Select A File to View", color="warning")
    if not any(n_clicks_list):
        return select_file, "", None, 1, dash.no_update
    
    if not project_data or not project_data.get("project_id"):
        return select_file, "", None, 1, dash.no_update
    
    project_id = project_data["project_id"]
    user_id = project_data.get("user_id")
    triggered = ctx.triggered[0]
    if triggered["value"]:
        file_name = json.loads(triggered["prop_id"].split(".n_clicks")[0])["file_name"]
        filename, filepath, original_name, file_size, _ = dbm.get_project_file_info(project_id, file_name)
        if not filename or not filepath or not os.path.exists(filepath):
            return dbc.Alert("File not found", color="danger"), "", None, 1, dash.no_update
        
        # Load file content
        with open(filepath, 'r', errors='ignore') as f:
            lines = [line.rstrip("\r\n") for line in f]
        
        total_lines = len(lines)
        total_pages = (total_lines // LINES_PER_PAGE) + (1 if total_lines % LINES_PER_PAGE > 0 else 0)
        
        file_data = {
            'filename': original_name,
            'file_size_mb': round(file_size / (1024 * 1024), 2) if file_size else 0,
            'lines': lines,
            'total_lines': total_lines,
            'total_pages': total_pages
        }
        
        if file_data:
            # Content (Page 1)
            page_content, _ = get_page_content(file_data, 1)
            if page_content:
                highlighted_content = highlight_components(
                    page_content['lines'],
                    page_number=1,
                    start_line=page_content['start_line']
                    )
            # Pagination
            if file_data['total_pages'] > 1:
                pagination = html.Div([
                    html.P(f"Page 1 of {file_data['total_pages']}", 
                          className="text-center small", id="page-info"),
                    dbc.Pagination(
                        max_value=file_data['total_pages'],
                        active_page=1,
                        size="sm",
                        id="file-paginator",
                        fully_expanded=False,
                        previous_next=True,
                        first_last=True,
                        className="d-flex justify-content-center mt-2"
                    )
                ], className="text-center")
            else:
                pagination = html.Div([
                    html.P("Single page file", className="text-center small text-muted", id="page-info")
                ])
            
            return highlighted_content, pagination, file_name, 1, reset_page_data()
    
    return select_file, "", None, 1, dash.no_update

# PAGINATION CALLBACK - Now works with suppress_callback_exceptions=True
@callback(
    Output('pagination-trigger-store', 'data'),
    Output("scroll-target", "data"),
    [Input('file-paginator', 'active_page', allow_optional=True),
     Input("results-listener", "event", allow_optional=True)
     ],
    prevent_initial_call=True
)
def handle_pagination_click(active_page, dbl):
    trigger = ctx.triggered_id

    if trigger == "file-paginator" and active_page:
        return {'page': active_page, 'timestamp': datetime.now().isoformat()}, None

    elif trigger == "results-listener" and dbl:
        #print("Double click event:", dbl)
        # Grab dataset info from double-clicked search result
        val = dbl.get("target.dataset.line") or dbl.get("target.parentElement.dataset.line")
        page = dbl.get("target.dataset.page") or dbl.get("target.parentElement.dataset.page")
        #print("val, page", val, page)
        if val and page:
            line_index = int(val)
            page = int(page)
            return {"page": page, "timestamp": datetime.now().isoformat()}, {"line": line_index, "page": page}

    return dash.no_update, dash.no_update


# CONTENT UPDATE CALLBACK
@callback(
    [Output('file-content', 'children', allow_duplicate=True),
     Output('current-page-store', 'data', allow_duplicate=True),
     Output('page-info', 'children'),
     Output('pagination-controls', 'children', allow_duplicate=True)
     ],
    [Input('pagination-trigger-store', 'data')],
    [State('current-file-store', 'data'),
     State("current-project-store", "data"),
     ],
    prevent_initial_call=True,
)
def update_file_content(pagination_data, file_name, project_data):
    if not pagination_data or not project_data or not file_name:
        return dash.no_update, dash.no_update, dash.no_update
    
    page = pagination_data.get('page', 1)
    #print("page", page)
    #print("file id",file_name)
    project_id = project_data["project_id"]
    try:
        filename, filepath, original_name, file_size, _ = dbm.get_project_file_info(project_id, file_name)
    except Exception as e:
        print(f"Viewer file content Temporary Error retriving data {e}")
        return dash.no_update, dash.no_update, dash.no_update
    
    if not filename or not filepath or not os.path.exists(filepath):
        return dbc.Alert("File not found", color="danger"), dash.no_update, dash.no_update
    
    # Load file content
    with open(filepath, 'r', errors='ignore') as f:
        lines = f.readlines()
    
    total_lines = len(lines)
    total_pages = (total_lines // LINES_PER_PAGE) + (1 if total_lines % LINES_PER_PAGE > 0 else 0)
    
    file_data = {
        'filename': original_name,
        'file_size_mb': round(file_size / (1024 * 1024), 2) if file_size else 0,
        'lines': lines,
        'total_lines': total_lines,
        'total_pages': total_pages
    }
    page_content, _ = get_page_content(file_data, page)
    if page_content:
        highlighted_content = highlight_components(
            page_content['lines'],
            page_number=page,
            start_line=page_content['start_line']
            )
        page_info = f"Page {page} of {file_data['total_pages']}" if file_data else f"Page {page}"

        # Recreate paginator DOM here so it always reflects the active page
        if file_data['total_pages'] > 1:
            paginator = html.Div([
                html.P(page_info, className="text-center small", id="page-info"),
                dbc.Pagination(
                    max_value=file_data['total_pages'],
                    active_page=page,
                    size="sm",
                    id="file-paginator",
                    fully_expanded=False,
                    previous_next=True,
                    first_last=True,
                    className="d-flex justify-content-center mt-2"
                )
            ], className="text-center")
        else:
            paginator = html.Div([
                html.P("Single page file", className="text-center small text-muted", id="page-info")
            ])

        if total_pages > 1:
            return highlighted_content, page, page_info, paginator
        else:
            return highlighted_content, page, "Single page file", dash.no_update
    
    return dash.no_update, dash.no_update, dash.no_update

def search_file(filepath, pattern):
    highlighter = TextHighlighter()
    matches = []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        with open(filepath, 'r', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                if regex.search(line):
                    highlighted_line = highlighter._highlight_single_line(line)

                    matches.append(
                        html.Div(
                            highlighted_line,
                            **{
                                "data-line": str(line_num),
                                "data-page": str((line_num // LINES_PER_PAGE)+1),
                                "style": {"cursor": "pointer", "padding": "2px"}
                            }
                        )
                    )
    except re.error:
        return []

    return matches


# SEARCH
@callback(
    [Output('search-results', 'children'),
     Output('search-input', 'value')],
    [Input('search-btn', 'n_clicks'),
     Input('btn-error', 'n_clicks'),
     Input('btn-warn', 'n_clicks'), 
     Input('btn-ip', 'n_clicks'),
     Input('btn-time', 'n_clicks')],
    [
     State('search-input', 'value'),
     State('current-file-store', 'data'),
     State("current-project-store", "data"),
     ],
    prevent_initial_call=True
)
def handle_search(search_clicks, error_clicks, warn_clicks, ip_clicks, time_clicks, 
                 search_pattern, file_name, project_data):
    
    project_id = project_data["project_id"]
    
    try:
        filename, filepath, original_name, file_size, _ = dbm.get_project_file_info(project_id, file_name)
    except Exception as e:
        print(f"Viewer search Temporary Error retriving data {e}")
        return dash.no_update, dash.no_update
    if not filename or not filepath or not os.path.exists(filepath):
        return dbc.Alert("File not found", color="danger"), dash.no_update
        
    triggered = ctx.triggered_id
    
    # Quick patterns
    patterns = {
        'btn-error': r'\b(ERROR|FATAL|CRITICAL|FAIL)\b',
        'btn-warn': r'\b(WARNING|WARN|ALERT)\b',
        'btn-ip': r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        'btn-time': r'\b\d{2}:\d{2}:\d{2}\b'
    }
    
    if triggered in patterns:
        search_pattern = patterns[triggered]
    
    if not search_pattern:
        return "", dash.no_update
    
    matches = search_file(filepath, search_pattern)
    if not matches:
        return dbc.Alert("No matches found", color="warning"), search_pattern

    return html.Div([
        html.H6(f"Found {len(matches)} matches"),
        html.Div(matches, style={'max-height': '400px', 'overflow-y': 'auto'})
    ]), search_pattern

# SAVE NOTES
@callback(
    Output("save-status", "children"),
    Input("save-notes-btn", "n_clicks"),
    State("notes-area", "value"),
    State("current-project-store", "data"),
    prevent_initial_call=True
)
def save_notes(n_clicks, note_content, project_data):
    if not n_clicks:   # nothing saved yet
        raise dash.exceptions.PreventUpdate

    if project_data and note_content is not None:
        project_id = project_data.get("project_id")
        user_id = project_data.get("user_id")
        project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
        notes_file_path = project_dir / "notes.txt"

        with open(notes_file_path, 'w') as f:
            f.write(note_content)

    # ✅ Status message
    timestamp = datetime.now().strftime("%H:%M:%S")
    status = f"Saved at {timestamp}"

    return status

# -------------------------
# Client-side scroll into view
# -------------------------
clientside_callback(
    dash.ClientsideFunction(
        namespace="clientside",
        function_name="scrollToLine"
    ),
    Output("scroll-target", "data", allow_duplicate=True),
    Input("scroll-target", "data"),
    prevent_initial_call=True
)

# HIGHLIGHTER
def highlight_components(lines, page_number=1, start_line=1):
    highlighter = TextHighlighter()
    result_components = []

    for idx, line in enumerate(lines):
        # compute global line number
        line_number = start_line + idx

        highlighted_line = highlighter.highlight_chunk([line])

        line_div = html.Div(
            highlighted_line,
            style={"whiteSpace": "pre-wrap"},
            **{
                "data-line": str(line_number),
                "data-page": str(page_number)
            }
        )
        result_components.append(line_div)

    return result_components
