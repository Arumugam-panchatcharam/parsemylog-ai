import dash_bootstrap_components as dbc
from dash import ctx, Input, Output, State, callback
import dash

from logai.log_parser_config import LogParserConfig

@callback(
    Output("parser-config-category-select", "options"),
    Output("parser-config-table", "data"),
    Input("parser-config-category-select", "id")
)
def initialize(_):
    lpc = LogParserConfig()
    config = lpc.load_config()
    categories = [{"label": k, "value": k} for k in config.keys()]
    table_data = []
    for cat, issues in config.items():
        for issue in issues:
            for cpe in issue.get("CPELogs", []):
                table_data.append({
                    "Category": cat,
                    "Title": issue["Title"],
                    "FileName": cpe["FileName"],
                    "PatternCount": len(cpe.get("Regex", []))
                })
    return categories, table_data


# --- Category Modal ---
@callback(
    Output("parser-config-add-category-modal", "is_open"),
    [Input("parser-config-add-category-btn", "n_clicks"), 
     Input("parser-config-confirm-add-category", "n_clicks"), 
     Input("parser-config-cancel-add-category", "n_clicks")],
    [State("parser-config-add-category-modal", "is_open")],
    prevent_initial_call=True
)
def toggle_category_modal(add, confirm, cancel, is_open):
    trigger = ctx.triggered_id
    if trigger == "parser-config-add-category-btn":
        return True
    elif trigger in ["parser-config-confirm-add-category", "parser-config-cancel-add-category"]:
        return False
    return is_open


@callback(
    Output("parser-config-category-select", "options", allow_duplicate=True),
    Input("parser-config-confirm-add-category", "n_clicks"),
    State("parser-config-new-category-name", "value"),
    prevent_initial_call="initial_duplicate"
)
def add_category(_, new_name):
    if not new_name:
        return dash.no_update
    lpc = LogParserConfig()
    config = lpc.load_config()
    if new_name in config:
        return dash.no_update
    config[new_name] = []
    lpc.save_config(config)
    return [{"label": k, "value": k} for k in config.keys()]


# --- Issue Modal ---
@callback(
    Output("parser-config-add-issue-modal", "is_open"),
    [Input("parser-config-add-issue-btn", "n_clicks"), 
     Input("parser-config-confirm-add-issue", "n_clicks"), 
     Input("parser-config-cancel-add-issue", "n_clicks")],
    [State("parser-config-add-issue-modal", "is_open")],
    prevent_initial_call=True
)
def toggle_issue_modal(add, confirm, cancel, is_open):
    trigger = ctx.triggered_id
    if trigger == "parser-config-add-issue-btn":
        return True
    elif trigger in ["parser-config-confirm-add-issue", "parser-config-cancel-add-issue"]:
        return False
    return is_open


# --- Confirm Add Issue ---
@callback(
    Output("parser-config-issue-select", "options", allow_duplicate=True),
    Input("parser-config-confirm-add-issue", "n_clicks"),
    State("parser-config-new-issue-title", "value"),
    State("parser-config-new-issue-file", "value"),
    State("parser-config-new-issue-cause", "value"),
    State("parser-config-category-select", "value"),
    prevent_initial_call="initial_duplicate"
)
def add_issue(_, title, file_name, cause, category):
    if not category:
        return dash.no_update
    if not title or not file_name:
        return dash.no_update

    lpc = LogParserConfig()
    config = lpc.load_config()
    if category not in config:
        config[category] = []

    config[category].append({
        "Title": title,
        "Cause": cause or "",
        "CPELogs": [{"FileName": file_name, "Regex": []}]
    })
    lpc.save_config(config)
    issue_opts = [{"label": i["Title"], "value": i["Title"]} for i in config[category]]
    return issue_opts


# --- Update Issue Dropdown ---
@callback(
    Output("parser-config-issue-select", "options"),
    Input("parser-config-category-select", "value")
)
def update_issue_dropdown(category):
    lpc = LogParserConfig()
    config = lpc.load_config()
    if not category or category not in config:
        return []
    return [{"label": issue["Title"], "value": issue["Title"]} for issue in config[category]]


# --- Load Issue Data ---
@callback(
    Output("parser-config-cause-input", "value"),
    Output("parser-config-file-name", "value"),
    Output("parser-config-regex-table", "data"),
    Input("parser-config-issue-select", "value"),
    State("parser-config-category-select", "value")
)
def load_issue(issue_title, category):
    lpc = LogParserConfig()
    config = lpc.load_config()
    if not category or not issue_title or category not in config:
        return "", "", []
    for issue in config[category]:
        if issue["Title"] == issue_title:
            return issue["Cause"], issue["CPELogs"][0]["FileName"], issue["CPELogs"][0]["Regex"]
    return "", "", []


# --- Add Pattern Row ---
@callback(
    Output("parser-config-regex-table", "data", allow_duplicate=True),
    Input("parser-config-add-pattern-btn", "n_clicks"),
    State("parser-config-regex-table", "data"),
    prevent_initial_call="initial_duplicate"
)
def add_pattern(_, data):
    data = data or []
    data.append({"type": "STD", "pattern": "", "description": ""})
    return data


# --- Save Config ---
@callback(
    Input("parser-config-save-btn", "n_clicks"),
    State("parser-config-category-select", "value"),
    State("parser-config-issue-select", "value"),
    State("parser-config-cause-input", "value"),
    State("parser-config-file-name", "value"),
    State("parser-config-regex-table", "data"),
    prevent_initial_call=True
)
def save_issue(_, category, title, cause, file_name, regex_data):
    if not category or not title or not file_name:
        print("⚠️ Please fill all fields.")

    lpc = LogParserConfig()
    config = lpc.load_config()
    if category not in config:
        config[category] = []
    
    existing_index = next(
        (i for i, issue in enumerate(config[category]) if issue.get("Title") == title),
        None
    )
    new_issue = {
        "Title": title,
        "Cause": cause,
        "CPELogs": [
            {
                "FileName": file_name,
                "Regex": regex_data
            }
        ]
    }
    if existing_index is not None:
        config[category][existing_index] = new_issue
    else:
        config[category].append(new_issue)
    lpc.save_config(config)
    print(f"✅ Added new issue '{title}'.")


@callback(
    Output("parser-config-delete-modal", "is_open"),
    Output("parser-config-delete-confirm-text", "children"),
    Input("parser-config-del-issue-btn", "n_clicks"),
    Input("parser-config-del-category-btn", "n_clicks"),
    Input("parser-config-cancel-delete", "n_clicks"),
    State("parser-config-category-select", "value"),
    State("parser-config-issue-select", "value"),
    prevent_initial_call=True
)
def open_delete_modal(del_issue, del_cat, cancel, category, issue):
    ctx = dash.callback_context
    if not ctx.triggered:
        return False, dash.no_update

    trigger = ctx.triggered[0]["prop_id"].split(".")[0]

    if trigger == "parser-config-del-issue-btn":
        if not issue or not category:
            return False, "Please select an issue to delete."
        return True, f"Are you sure you want to delete issue '{issue}' from '{category}'?"
    elif trigger == "parser-config-del-category-btn":
        if not category:
            return False, "Please select a category to delete."
        return True, f"Are you sure you want to delete the entire category '{category}' (all issues will be lost)?"
    else:
        return False, dash.no_update

    return False, dash.no_update

@callback(
    Output("parser-config-delete-modal", "is_open", allow_duplicate=True),
    Output("parser-config-category-select", "options", allow_duplicate=True),
    Output("parser-config-issue-select", "options", allow_duplicate=True),
    Input("parser-config-confirm-delete", "n_clicks"),
    State("parser-config-category-select", "value"),
    State("parser-config-issue-select", "value"),
    State("parser-config-delete-confirm-text", "children"),
    prevent_initial_call=True
)
def confirm_delete(n_clicks, category, issue, confirm_text):
    if not n_clicks:
        return False, dash.no_update, dash.no_update
    
    lpc = LogParserConfig()
    #lpc.load_config()
    delete_category = "entire category" in confirm_text.lower()
    success, msg = lpc.delete_config_entry(category, issue, delete_category)
    config = lpc.load_config()
    categories = [{"label": k, "value": k} for k in config.keys()]
    if delete_category:
        return False, categories, []
    else:
        issue_opts = [{"label": i["Title"], "value": i["Title"]} for i in config.get(category, [])]
        return False, categories, issue_opts

