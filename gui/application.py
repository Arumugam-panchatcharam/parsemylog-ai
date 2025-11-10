import os
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback, ctx, ALL, no_update
from datetime import datetime
import json

from flask import send_file
import mimetypes

from gui.pages import log_viewer as log_viewer_page
from gui.pages import pattern as pattern_page
from gui.pages import telemetry as telemetry_page
from gui.pages import ai_analysis as ai_analysis_page
from gui.pages import embedding as embedding_page
from gui.pages import log_parser_config as log_parser_config_page
from gui.pages import log_parser as rule_pattern_page
from gui.callbacks import pattern, telemetry, utils, ai_analysis, log_viewer, embedding, log_parser_config, log_parser
from gui.file_manager import FileManager
from gui.user_db_mngr import db as dbm
from gui.app_instance import create_app, BASE_DIR

app, flask_server = create_app()

from gui.app_instance import dbm

# Flask download route
@flask_server.route('/download/<project_id>/<filename>')
def download_file(project_id, filename):
    #print("Download request for:", project_id, filename)
    try:
        filename, file_path, original_name, _, _ = dbm.get_project_file_info(project_id, filename)

        if not filename:
            return "File not found", 404

        if not os.path.exists(file_path):
            return "File not found on disk", 404
        
        # update path for static folder
        new_path = os.path.join(BASE_DIR, file_path)

        mime_type, _ = mimetypes.guess_type(original_name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        return send_file(new_path, 
                        as_attachment=True, 
                        download_name=original_name,
                        mimetype=mime_type)

    except Exception as e:
        return f"Download error: {str(e)}", 500


# Enhanced layout with all stores
app.layout = dbc.Container([
    dcc.Location(id="url", refresh=False),
    dcc.Location(id="admin-url", refresh=False),
    dcc.Store(id="session-store", storage_type="session", clear_data=False),
    dcc.Store(id="current-project-store", storage_type="session", clear_data=False), 
    dcc.Store(id="user-data-store", storage_type="session", clear_data=False),
    dcc.Store(id="selected-file-store", storage_type="session", clear_data=False),
    dcc.Store(id="delete-project-store", storage_type="memory"),
    dcc.Store(id="log-viewer-navigation", storage_type="memory"),
    dcc.Store(id="delete-user-store", storage_type="memory"),
    dcc.Store(id="reset-password-store", storage_type="memory"),  # NEW: Password reset

    # for Log Viewer
    dcc.Store(id='current-file-store'),
    dcc.Store(id='current-page-store', data=1),
    dcc.Store(id='pagination-trigger-store'),
    dcc.Store(id="scroll-target", data=None),

    # For Pattern
    dcc.Store(id="pattern-result-store", storage_type="session", clear_data=False),

    # for hiding error for periodic status interval
    html.Div(id="embed-queued-card", style={"display": "none"}),
    html.Div(id="embed-parsed-card", style={"display": "none"}),
    html.Div(id="embed-done-card", style={"display": "none"}),

    html.Div(id="page-content", style={"min-height": "100vh"}),
], fluid=True, className="p-0")


# Layout functions
def create_banner():
    return dbc.Navbar([
        dbc.NavbarBrand([
            html.I(className="fas fa-chart-line me-2"),
            "LogAI"
        ], className="ms-2")
    ], color="primary", dark=True, className="mb-0")


def create_login_layout():
    return html.Div([
        create_banner(),
        dbc.Container([
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H3([
                                html.I(className="fas fa-sign-in-alt me-2"),
                                "Welcome to LogAI"
                            ], className="text-center mb-0")
                        ]),
                        dbc.CardBody([
                            html.Div(id="login-alert"),
                            dbc.Form([
                                dbc.Row([
                                    dbc.Label("Username", html_for="login-username"),
                                    dbc.Input(id="login-username", type="text", placeholder="Enter username")
                                ], className="mb-3"),
                                dbc.Row([
                                    dbc.Label("Password", html_for="login-password"),
                                    dbc.Input(id="login-password", type="password", placeholder="Enter password")
                                ], className="mb-3"),
                                dbc.Row([
                                    dbc.Button([
                                        html.I(className="fas fa-sign-in-alt me-2"), "Login"
                                    ], id="login-btn", color="primary", className="me-2"),
                                    dbc.Button([
                                        html.I(className="fas fa-user-plus me-2"), "Register"
                                    ], id="register-btn", color="secondary", outline=True)
                                ], className="mb-3")
                            ])
                        ])
                    ], style={"max-width": "400px"})
                ], width={"size": 6, "offset": 3})
            ], justify="center", className="mt-5"),

            # Registration Modal
            dbc.Modal([
                dbc.ModalHeader([html.I(className="fas fa-user-plus me-2"), "Register New Account"]),
                dbc.ModalBody([
                    html.Div(id="register-alert"),
                    dbc.Form([
                        dbc.Row([
                            dbc.Label("Username"),
                            dbc.Input(id="reg-username", type="text", placeholder="Choose username")
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Label("Email (optional)"),
                            dbc.Input(id="reg-email", type="email", placeholder="Enter email")
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Label("Password"),
                            dbc.Input(id="reg-password", type="password", placeholder="Choose password")
                        ], className="mb-3"),
                        dbc.Row([
                            dbc.Label("Confirm Password"),
                            dbc.Input(id="reg-password-confirm", type="password", placeholder="Confirm password")
                        ], className="mb-3")
                    ])
                ]),
                dbc.ModalFooter([
                    dbc.Button([html.I(className="fas fa-check me-2"), "Create Account"], 
                              id="create-account-btn", color="primary"),
                    dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                              id="cancel-register-btn", color="secondary", className="ms-2")
                ])
            ], id="register-modal", is_open=False)
        ], fluid=True)
    ])

def create_dashboard_layout(username, user_id=None, is_admin=False):
    return html.Div([
        dbc.Row([
            # LEFT SIDEBAR
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        create_banner(),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.H5([
                                html.I(className="fas fa-user me-2"), 
                                f"{username}",
                                html.Span(" 👑", className="text-warning") if is_admin else ""
                            ], className="text-white mb-2"),
                            dbc.ButtonGroup([
                                dbc.Button([html.I(className="fas fa-user-edit me-2"), "Profile"], 
                                         id="profile-btn", color="outline-light", size="sm"),
                                dbc.Button([html.I(className="fas fa-sign-out-alt me-2"), "Logout"], 
                                         id="logout-btn", color="outline-light", size="sm")
                            ], className="w-100")
                        ], className="p-2")
                    ], className="bg-primary text-white"),

                    dbc.CardBody([
                        html.H6([html.I(className="fas fa-compass me-2"), "Navigation"], className="mb-3"),
                        dbc.Nav([
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-tachometer-alt me-2"), "Dashboard"], 
                                                  href="/dashboard", id="nav-dashboard", active=True)),
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-users-cog me-2"), "Admin Panel"], 
                                                  href="/admin", id="nav-admin", active=False)) if is_admin else None,
                        ], vertical=True, pills=True, className="mb-4"),

                        html.Hr(),
                        html.H6([html.I(className="fas fa-info-circle me-2"), "About"], className="mb-3"),
                        html.P("LogAI Complete - Advanced log analysis with enhanced syntax highlighting and admin features.", 
                              className="small text-muted")
                    ], className="h-100")
                ], style={"height": "100vh", "position": "sticky", "top": "0"}, className="border-0 rounded-0")
            ], width=2, className="p-0"),

            # MAIN CONTENT AREA
            dbc.Col([
                dbc.Container([
                    dbc.Row([
                        dbc.Col([
                            dbc.Card([
                                dbc.CardHeader([
                                    dbc.Row([
                                        dbc.Col([
                                            html.H4([html.I(className="fas fa-folder me-2"), "My Projects"], className="mb-0")
                                        ]),
                                        dbc.Col([
                                            dbc.ButtonGroup([
                                                dbc.Button([html.I(className="fas fa-sync-alt")], 
                                                         id="refresh-projects-icon", color="outline-secondary", size="sm", 
                                                         title="Refresh Projects"),
                                                dbc.Button([html.I(className="fas fa-plus me-2"), "New Project"], 
                                                         id="new-project-btn", color="primary", size="sm")
                                            ], className="float-end")
                                        ], width="auto")
                                    ])
                                ]),
                                dbc.CardBody([
                                    html.Div(id="projects-matrix", 
                                            style={
                                                "overflowY": "auto",
                                                "overflowX": "hidden",
                                                "maxHeight": "calc(100vh - 220px)",
                                                "width": "100%",
                                                "whiteSpace": "nowrap",
                                                "padding": "0.5rem"
                                            }
                                        )
                                    ])
                            ])
                        ])
                    ])
                ], fluid=True, className="py-4")
            ], width=10, style={"height": "100vh"}),
        ], className="g-0"),

        # Modals
        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-plus-circle me-2"), "Create New Project"]),
            dbc.ModalBody([
                html.Div(id="new-project-alert"),
                dbc.Form([
                    dbc.Row([
                        dbc.Label("Project Name"),
                        dbc.Input(id="new-project-name", type="text", placeholder="Enter project name")
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Description (optional)"),
                        dbc.Textarea(id="new-project-desc", placeholder="Project description")
                    ], className="mb-3")
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-check me-2"), "Create Project"], 
                          id="create-project-btn", color="primary"),
                dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                          id="cancel-project-btn", color="secondary", className="ms-2")
            ])
        ], id="new-project-modal", is_open=False),

        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-exclamation-triangle me-2 text-danger"), "Delete Project"]),
            dbc.ModalBody([
                html.Div(id="delete-project-alert"),
                html.P("Are you sure you want to delete this project? This action cannot be undone."),
                html.P(html.Strong("All project files and data will be permanently lost."), className="text-danger"),
                html.Div(id="project-to-delete-info")
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-trash me-2"), "Delete Project"], 
                          id="confirm-delete-btn", color="danger"),
                dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                          id="cancel-delete-btn", color="secondary", className="ms-2")
            ])
        ], id="delete-project-modal", is_open=False),

        # Profile Update Modal
        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-user-edit me-2"), "Update Profile"]),
            dbc.ModalBody([
                html.Div(id="profile-alert"),
                dbc.Form([
                    dbc.Row([
                        dbc.Label("Username"),
                        dbc.Input(id="profile-username", type="text", placeholder="New username")
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Email"),
                        dbc.Input(id="profile-email", type="email", placeholder="New email")
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("New Password (leave blank to keep current)"),
                        dbc.Input(id="profile-password", type="password", placeholder="New password")
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Confirm New Password"),
                        dbc.Input(id="profile-password-confirm", type="password", placeholder="Confirm new password")
                    ], className="mb-3")
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-save me-2"), "Update Profile"], 
                          id="update-profile-btn", color="primary"),
                dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                          id="cancel-profile-btn", color="secondary", className="ms-2")
            ])
        ], id="profile-modal", is_open=False)
    ], style={"height": "100vh", "overflow": "hidden"})

def create_admin_layout(username):
    return html.Div([
        dbc.Row([
            # LEFT SIDEBAR
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        create_banner(),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.H5([html.I(className="fas fa-user-shield me-2"), f"Admin: {username}"], className="text-white mb-2"),
                            dbc.Button([html.I(className="fas fa-arrow-left me-2"), "Dashboard"], 
                                     id="back-to-dashboard-btn", color="outline-light", size="sm", className="w-100")
                        ], className="p-2")
                    ], className="bg-danger text-white"),

                    dbc.CardBody([
                        html.H6([html.I(className="fas fa-cogs me-2"), "Admin Tools"], className="mb-3"),
                        dbc.Nav([
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-users me-2"), "User Management"], 
                                                  href="#users", id="nav-users", active=True)),
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-cog me-2"), "Parser Configuration"], 
                                                  href="#parser-config", id="nav-parser-config", active=False)),
                        ], vertical=True, pills=True, className="mb-4"),

                        html.Hr(),
                        html.H6([html.I(className="fas fa-chart-bar me-2"), "Statistics"], className="mb-3"),
                        html.Div(id="admin-stats")
                    ], className="h-100")
                ], style={"height": "100vh", "position": "sticky", "top": "0"}, className="border-0 rounded-0")
            ], width=3, className="p-0"),

            # MAIN ADMIN CONTENT
            dbc.Col([
                dbc.Container([
                    dbc.Row([
                        dbc.Col([
                            html.Div(id="admin-main-content", className="p-3")
                        ])
                    ])
                ], fluid=True, className="py-4")
            ], width=9, style={"height": "100vh"})
        ], className="g-0"),

        # User Delete Confirmation Modal
        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-exclamation-triangle me-2 text-danger"), "Delete User"]),
            dbc.ModalBody([
                html.Div(id="delete-user-alert"),
                html.P("Are you sure you want to delete this user? This action cannot be undone."),
                html.P(html.Strong("All user projects, files and data will be permanently lost."), className="text-danger"),
                html.Div(id="user-to-delete-info")
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-trash me-2"), "Delete User"], 
                          id="confirm-delete-user-btn", color="danger"),
                dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                          id="cancel-delete-user-btn", color="secondary", className="ms-2")
            ])
        ], id="delete-user-modal", is_open=False),

        # NEW: Password Reset Modal
        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-key me-2"), "Reset User Password"]),
            dbc.ModalBody([
                html.Div(id="reset-password-alert"),
                html.P("Reset password for the selected user. They will need to use the new password to login."),
                html.Div(id="user-to-reset-info", className="mb-3"),
                dbc.Form([
                    dbc.Row([
                        dbc.Label("New Password"),
                        dbc.Input(id="reset-new-password", type="password", placeholder="Enter new password")
                    ], className="mb-3"),
                    dbc.Row([
                        dbc.Label("Confirm New Password"),
                        dbc.Input(id="reset-password-confirm", type="password", placeholder="Confirm new password")
                    ], className="mb-3")
                ])
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-key me-2"), "Reset Password"], 
                          id="confirm-reset-password-btn", color="warning"),
                dbc.Button([html.I(className="fas fa-times me-2"), "Cancel"], 
                          id="cancel-reset-password-btn", color="secondary", className="ms-2")
            ])
        ], id="reset-password-modal", is_open=False),

        # User Projects Modal - FIXED: Removed size parameter from ModalHeader
        dbc.Modal([
            dbc.ModalHeader([html.I(className="fas fa-folder me-2"), "User Projects"]),
            dbc.ModalBody([
                html.Div(id="user-projects-content")
            ]),
            dbc.ModalFooter([
                dbc.Button([html.I(className="fas fa-times me-2"), "Close"], 
                          id="close-user-projects-btn", color="secondary")
            ])
        ], id="user-projects-modal", is_open=False, size="xl")
    ], style={"height": "100vh", "overflow": "hidden"})

def create_workspace_layout(project_name, project_id):
    return html.Div([
        dbc.Row([
            # LEFT SIDEBAR - More compact for maximized log viewer
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        create_banner(),
                        html.Hr(className="my-2"),
                        html.Div([
                            html.H6([html.I(className="fas fa-folder-open me-2"), f"{project_name}"], 
                                   className="text-white mb-2"),
                            dbc.Button([html.I(className="fas fa-arrow-left me-2"), "Dashboard"], 
                                     id="back-dashboard-btn", color="outline-light", size="sm", className="w-100")
                        ], className="p-2")
                    ], className="bg-primary text-white"),

                    dbc.CardBody([
                        # Navigation
                        html.H6([html.I(className="fas fa-compass me-2"), "Tools"], className="mb-2"),
                        dbc.Nav([
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-search me-2"), "Log Viewer"], 
                                                 href="/workspace/viewer", id="nav-viewer", active=True, className="small")),
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-diagram-project me-2"), "Quick Pattern"], 
                                                 href="/workspace/rule_pattern", id="nav-rule_pattern", active=False, className="small")),                                                 
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-diagram-project me-2"), "Pattern"], 
                                                 href="/workspace/pattern", id="nav-pattern", active=False, className="small")),
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-layer-group me-2"), "Embedding"], 
                                                 href="/workspace/embed", id="nav-embed", active=False, className="small")),                                           
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-chart-area me-2"), "Telemetry"], 
                                                  href="/workspace/telemetry", id="nav-telemetry", active=False, className="small")),
                            dbc.NavItem(dbc.NavLink([html.I(className="fas fa-brain me-2"), "AI Analysis"], 
                                                  href="/workspace/ai_analysis", id="nav-ai", active=False, className="small")),
                        ], vertical=True, pills=True, className="mb-3"),

                        html.Hr(),
                        # page specific sidebar content
                        html.Div(id="workspace-sidebar-content"),
                    ], className="h-100", style={"max-height": "calc(100vh - 150px)", "overflow-y": "auto"})
                ], style={"height": "100vh", "position": "sticky", "top": "0"}, className="border-0 rounded-0")
            ], width=2, className="p-0"),

            # MAIN CONTENT AREA - More space for log viewer
            dbc.Col([
                html.Div(id="workspace-content", className="p-3")
            ], width=10)
        ], className="g-0")
    ], style={"height": "100vh", "overflow": "hidden"})

# ALL CALLBACKS - Complete implementation
@callback(
    Output("admin-main-content", "children"),
    Input("admin-url", "hash")
)
def render_admin_section(hash_value):
    if hash_value == "#parser-config":
        return log_parser_config_page.layout
    else:
        return dbc.Col([
            dbc.Row([
                dbc.Col([
                    html.H4([html.I(className="fas fa-users me-2"), "User Management"], className="mb-0")
                ]),
                dbc.Col([
                    dbc.Button([html.I(className="fas fa-sync-alt me-2"), "Refresh"], 
                                id="refresh-users-btn", color="outline-secondary", size="sm", className="float-end")
                            ], width="auto")
                ]),
                html.Hr(),
                html.Br(),
                dbc.Card([
                    dbc.CardBody([
                        html.Div(id="users-list", 
                            style={
                                "overflowY": "auto",
                                "overflowX": "hidden",
                                "maxHeight": "calc(100vh - 220px)",
                                "width": "100%",
                                "whiteSpace": "nowrap",
                                "padding": "0.5rem"
                            }
                        )
                    ])
                ])
        ], width=12, style={"height": "100vh", "overflowY": "auto"})

@callback(
    Output("nav-users", "active"),
    Output("nav-parser-config", "active"),
    Input("admin-url", "hash")
)
def toggle_nav_active(hash_val):
    if hash_val == "#parser-config":
        return False, True
    return True, False

# Main routing callback
@callback(
    Output("page-content", "children"),
    [Input("url", "pathname")],
    [State("session-store", "data"),
     State("current-project-store", "data")]
)
def display_page(pathname, session_data, project_data):
    if pathname != "/" and (not session_data or not session_data.get("logged_in")):
        return create_login_layout()

    if pathname == "/" or pathname is None:
        return create_login_layout()

    elif pathname == "/dashboard":
        if session_data and session_data.get("logged_in"):
            return create_dashboard_layout(session_data["username"], 
                                         session_data.get("user_id"), 
                                         session_data.get("is_admin", False))
        else:
            return create_login_layout()

    elif pathname == "/admin":
        if session_data and session_data.get("logged_in") and session_data.get("is_admin"):
            return create_admin_layout(session_data["username"])
        else:
            return create_dashboard_layout(session_data["username"], 
                                         session_data.get("user_id"), 
                                         session_data.get("is_admin", False))

    elif pathname.startswith("/workspace/"):
        if not project_data or not project_data.get("project_name"):
            if session_data and session_data.get("logged_in"):
                return create_dashboard_layout(session_data["username"], 
                                             session_data.get("user_id"), 
                                             session_data.get("is_admin", False))
            else:
                return create_login_layout()

        return create_workspace_layout(project_data["project_name"], project_data.get("project_id"))

    else:
        if session_data and session_data.get("logged_in"):
            return create_dashboard_layout(session_data["username"], 
                                         session_data.get("user_id"), 
                                         session_data.get("is_admin", False))
        else:
            return create_login_layout()

# Workspace content routing with default Log Viewer selection
@callback(
    Output("workspace-content", "children"),
    Input("url", "pathname"),
    State("current-project-store", "data"),
)
def update_workspace_content(pathname, project_data):
    if not pathname.startswith("/workspace/"):
        return no_update

    page = pathname.split("/workspace/")[-1]
    if page == "viewer":
        return log_viewer_page.layout
    elif page == "rule_pattern":
        return rule_pattern_page.layout
    elif page == "pattern":
        return pattern_page.layout
    elif page == "embed":
        return embedding_page.layout
    elif page == "telemetry":
        return telemetry_page.layout
    elif page == "ai_analysis":
        return ai_analysis_page.layout
    else:
        return log_viewer_page.layout  # Default to logviewer page

# Login callback - Enhanced with admin flag
@callback(
    [Output("session-store", "data"),
     Output("user-data-store", "data"),
     Output("login-alert", "children"),
     Output("url", "pathname")],
    [Input("login-btn", "n_clicks")],
    [State("login-username", "value"),
     State("login-password", "value")],
    prevent_initial_call=True
)
def handle_login(n_clicks, username, password):
    if not username or not password:
        return {}, {}, dbc.Alert("Please enter username and password", color="danger"), no_update

    success, user_id, is_admin = dbm.authenticate_user(username, password)

    if success:
        session_data = {
            "user_id": user_id, 
            "username": username, 
            "logged_in": True,
            "is_admin": is_admin,
            "timestamp": str(datetime.now())
        }
        return session_data, session_data, "", "/dashboard"
    else:
        return {}, {}, dbc.Alert("Invalid username or password", color="danger"), no_update

# Registration callback
@callback(
    [Output("register-modal", "is_open"),
     Output("register-alert", "children")],
    [Input("register-btn", "n_clicks"),
     Input("create-account-btn", "n_clicks"),
     Input("cancel-register-btn", "n_clicks")],
    [State("reg-username", "value"),
     State("reg-password", "value"),
     State("reg-password-confirm", "value"),
     State("reg-email", "value"),
     State("register-modal", "is_open")],
    prevent_initial_call=True
)
def handle_registration(register_click, create_click, cancel_click, 
                       username, password, confirm_password, email, is_open):

    if ctx.triggered_id == "register-btn":
        return True, ""
    elif ctx.triggered_id == "create-account-btn":
        if not username or not password:
            return True, dbc.Alert("Username and password are required", color="danger")
        if password != confirm_password:
            return True, dbc.Alert("Passwords do not match", color="danger")

        success, message = dbm.create_user(username, password, email or "")
        if success:
            return False, ""
        else:
            return True, dbc.Alert(message, color="danger")
    elif ctx.triggered_id == "cancel-register-btn":
        return False, ""

    return is_open, ""

# Projects matrix callback
@callback(
    Output("projects-matrix", "children"),
    [Input("session-store", "data"),
     Input("user-data-store", "data"),
     Input("new-project-modal", "is_open"),
     Input("refresh-projects-icon", "n_clicks"),
     Input("delete-project-modal", "is_open")],
    #prevent_initial_call=True
)
def load_user_projects_matrix(session_data, user_data_backup, modal_open, refresh_clicks, delete_modal):
    active_session = session_data if session_data and session_data.get("logged_in") else user_data_backup

    if not active_session or not active_session.get("logged_in"):
        return dbc.Alert("Session expired. Please refresh the page and login again.", color="warning")

    user_id = active_session.get("user_id")
    if not user_id:
        return dbc.Alert("User ID not found in session data.", color="danger")

    projects = dbm.get_user_projects(user_id)

    if not projects:
        return dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className="fas fa-folder-open fa-3x text-muted mb-3"),
                    html.H5("No projects yet", className="text-muted"),
                    html.P("Create your first project to get started with LogAI analysis!", 
                          className="text-muted")
                ], className="text-center py-4")
            ])
        ])

    # Create matrix layout
    project_cards = []
    for i in range(0, len(projects), 3):
        row_projects = projects[i:i+3]

        row_cards = []
        for project in row_projects:
            project_id, name, description, created_at, last_accessed = project

            card = dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        dbc.Row([
                            dbc.Col([
                                html.H6([html.I(className="fas fa-folder me-2"), name], 
                                       className="mb-0 text-primary")
                            ]),
                            dbc.Col([
                                dbc.Button([html.I(className="fas fa-trash")], 
                                         id={"type": "delete-project", "index": project_id},
                                         color="outline-danger", size="sm", 
                                         title="Delete Project", className="float-end")
                            ], width="auto")
                        ])
                    ], className="pb-2"),
                    dbc.CardBody([
                        html.P(description or "No description", 
                              className="card-text text-muted mb-3 card-scroll", 
                              style={
                                    "maxHeight": "100px",
                                    "overflowY": "auto",
                                    "fontSize": "0.85rem",
                                    "whiteSpace": "pre-wrap",    # preserve newlines and wrap lines
                                    "wordBreak": "break-word",   # break long words
                                    "overflowWrap": "break-word" # prevent overflow from long tokens
                                }
                              ),
                        html.Small([
                            html.I(className="fas fa-calendar me-1"),
                            f"Created: {created_at}"
                        ], className="text-muted d-block mb-2"),
                        dbc.Button([html.I(className="fas fa-external-link-alt me-2"), "Open Project"], 
                                 color="primary", size="sm",
                                 id={"type": "open-project", "index": project_id},
                                 className="w-100")
                    ])
                ], className="h-100 shadow-sm")
            ], width=4, className="mb-4")

            row_cards.append(card)

        while len(row_cards) < 3:
            row_cards.append(dbc.Col(width=4))

        project_cards.append(dbc.Row(row_cards))

    return html.Div(project_cards)


# Project deletion callbacks
@callback(
    [Output("delete-project-modal", "is_open"),
     Output("delete-project-store", "data"),
     Output("project-to-delete-info", "children"),
     Output("delete-project-alert", "children")],
    [Input({"type": "delete-project", "index": ALL}, "n_clicks"),
     Input("confirm-delete-btn", "n_clicks"),
     Input("cancel-delete-btn", "n_clicks")],
    [State("session-store", "data"),
     State("user-data-store", "data"),
     State("delete-project-store", "data")],
    prevent_initial_call=True
)
def handle_project_deletion(delete_clicks, confirm_click, cancel_click, session_data, user_data_backup, delete_store):
    triggered_id = ctx.triggered_id

    if isinstance(triggered_id, dict) and triggered_id.get("type") == "delete-project":
        if any(delete_clicks):
            project_id = triggered_id["index"]
            project = dbm.get_project_by_id(project_id=project_id)

            project_name, project_desc = project.name, project.description if project else (None, None)
            project_info = html.Div([
                    html.P([html.Strong("Project: "), project_name]),
                    html.P([html.Strong("Description: "), project_desc or "No description"])
                ])
            return True, {"project_id": project_id}, project_info, ""

        return False, {}, "", ""

    elif triggered_id == "confirm-delete-btn" and delete_store:
        active_session = session_data if session_data and session_data.get("logged_in") else user_data_backup

        if not active_session or not active_session.get("logged_in"):
            return True, delete_store, no_update, dbc.Alert("Session expired", color="danger")

        project_id = delete_store.get("project_id")
        user_id = active_session.get("user_id")

        if project_id and user_id:
            success, message = dbm.delete_project(project_id, user_id)
            if success:
                return False, {}, "", ""
            else:
                return True, delete_store, no_update, dbc.Alert(message, color="danger")

    elif triggered_id == "cancel-delete-btn":
        return False, {}, "", ""

    return no_update, no_update, no_update, no_update

# New project callback
@callback(
    [Output("new-project-modal", "is_open"),
     Output("new-project-alert", "children"),
     Output("new-project-name", "value"),
     Output("new-project-desc", "value")],
    [Input("new-project-btn", "n_clicks"),
     Input("create-project-btn", "n_clicks"),
     Input("cancel-project-btn", "n_clicks")],
    [State("new-project-name", "value"),
     State("new-project-desc", "value"),
     State("session-store", "data"),
     State("user-data-store", "data"),
     State("new-project-modal", "is_open")],
    prevent_initial_call=True
)
def handle_new_project(new_click, create_click, cancel_click, 
                      project_name, description, session_data, user_data_backup, is_open):

    if ctx.triggered_id == "new-project-btn":
        return True, "", "", ""
    elif ctx.triggered_id == "create-project-btn":
        if not project_name:
            return True, dbc.Alert("Project name is required", color="danger"), project_name, description

        active_session = session_data if session_data and session_data.get("logged_in") else user_data_backup

        if not active_session or not active_session.get("logged_in"):
            return True, dbc.Alert("Session expired. Please login again.", color="danger"), project_name, description

        user_id = active_session.get("user_id")
        success, project_id, message = dbm.create_project(user_id, project_name, description or "")

        if success:
            return False, "", "", ""
        else:
            return True, dbc.Alert(message, color="danger"), project_name, description
    elif ctx.triggered_id == "cancel-project-btn":
        return False, "", "", ""

    return is_open, "", project_name, description

# Open project callback
@callback(
    [Output("current-project-store", "data"),
     Output("url", "pathname", allow_duplicate=True)],
    Input({"type": "open-project", "index": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def open_project(n_clicks_list):
    if not any(n_clicks_list):
        return no_update, no_update

    triggered = ctx.triggered[0]
    if triggered["value"]:
        project_id = json.loads(triggered["prop_id"].split(".")[0])["index"]
        
        project = dbm.get_project_by_id(project_id=project_id)
        project_name, user_id = project.name, project.user_id if project else (None, None)
        # TODO: Update TimeStamp

        project_data = {"project_id": project_id, "project_name": project_name, "user_id": user_id}
        return project_data, "/workspace/viewer"

    return no_update, no_update

# Profile management callbacks
@callback(
    [Output("profile-modal", "is_open"),
     Output("profile-alert", "children"),
     Output("profile-username", "value"),
     Output("profile-email", "value"),
     Output("profile-password", "value"),
     Output("profile-password-confirm", "value")],
    [Input("profile-btn", "n_clicks"),
     Input("update-profile-btn", "n_clicks"),
     Input("cancel-profile-btn", "n_clicks")],
    [State("profile-username", "value"),
     State("profile-email", "value"),
     State("profile-password", "value"),
     State("profile-password-confirm", "value"),
     State("session-store", "data"),
     State("profile-modal", "is_open")],
    prevent_initial_call=True
)
def handle_profile_update(profile_click, update_click, cancel_click,
                         new_username, new_email, new_password, confirm_password,
                         session_data, is_open):

    if ctx.triggered_id == "profile-btn":
        # Pre-fill current user info
        if session_data and session_data.get("logged_in"):
            user_info = dbm.get_user_by_id(session_data["user_id"])
            if user_info:
                username, email, created_at, _ = user_info
                return True, "", username, email or "", "", ""
        return True, "", "", "", "", ""

    elif ctx.triggered_id == "update-profile-btn":
        if not session_data or not session_data.get("logged_in"):
            return True, dbc.Alert("Session expired. Please login again.", color="danger"), new_username, new_email, "", ""

        # Validation
        if new_password and new_password != confirm_password:
            return True, dbc.Alert("Passwords do not match", color="danger"), new_username, new_email, "", ""

        # Update profile
        user_id = session_data["user_id"]
        success, message = dbm.update_user(
            user_id, 
            new_username if new_username else None,
            new_password if new_password else None,
            new_email if new_email is not None else None
        )

        if success:
            # Update session if username changed
            if new_username:
                session_data["username"] = new_username
            return False, "", "", "", "", ""
        else:
            return True, dbc.Alert(message, color="danger"), new_username, new_email, "", ""

    elif ctx.triggered_id == "cancel-profile-btn":
        return False, "", "", "", "", ""

    return is_open, "", new_username, new_email, new_password, confirm_password

# Admin callbacks - User list with password reset
@callback(
    [Output("users-list", "children"),
     Output("admin-stats", "children")],
    [Input("session-store", "data"),
     Input("refresh-users-btn", "n_clicks"),
     Input("delete-user-modal", "is_open"),
     Input("reset-password-modal", "is_open")],
    prevent_initial_call=True
)
def load_admin_users_list(session_data, refresh_clicks, delete_modal, reset_modal):
    if not session_data or not session_data.get("is_admin"):
        return dbc.Alert("Access denied. Admin privileges required.", color="danger"), ""

    users = dbm.get_all_user()

    # Stats
    total_users = len(users)
    total_projects = sum(user[6] for user in users)  # project_count
    total_files = sum(user[7] for user in users)     # file_count
    admin_count = sum(1 for user in users if user[3])  # is_admin

    stats = dbc.Card([
        dbc.CardBody([
            html.H6("📊 System Stats", className="mb-2"),
            html.P([html.Strong(f"{total_users}"), " Users"], className="mb-1 small"),
            html.P([html.Strong(f"{admin_count}"), " Admins"], className="mb-1 small"),
            html.P([html.Strong(f"{total_projects}"), " Projects"], className="mb-1 small"),
            html.P([html.Strong(f"{total_files}"), " Files"], className="mb-0 small")
        ])
    ], color="light")

    # Users table with enhanced admin controls
    user_rows = []
    for user in users:
        user_id, username, email, is_admin, created_at, last_login, project_count, file_count = user

        row = dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.H6([
                            html.I(className="fas fa-user me-2"),
                            username,
                            html.Span(" 👑", className="text-warning") if is_admin else ""
                        ], className="mb-1"),
                        html.P([
                            html.Small([email or "No email", " • Created: ", created_at]),
                        ], className="text-muted mb-2"),
                        html.P([
                            html.I(className="fas fa-folder me-1"),
                            f"{project_count} projects • ",
                            html.I(className="fas fa-file me-1"),
                            f"{file_count} files"
                        ], className="small mb-0")
                    ], width=7),
                    dbc.Col([
                        dbc.ButtonGroup([
                            dbc.Button([html.I(className="fas fa-folder")], 
                                     id={"type": "view-user-projects", "index": user_id},
                                     color="outline-info", size="sm", 
                                     title="View Projects"),
                            dbc.Button([html.I(className="fas fa-key")], 
                                     id={"type": "reset-user-password", "index": user_id},
                                     color="outline-warning", size="sm", 
                                     title="Reset Password"),  # NEW: Password reset button
                            dbc.Button([html.I(className="fas fa-trash")], 
                                     id={"type": "delete-user", "index": user_id},
                                     color="outline-danger", size="sm", 
                                     title="Delete User",
                                     disabled=is_admin)  # Can't delete admin
                        ], size="sm", className="float-end")
                    ], width=5)
                ])
            ])
        ], className="mb-2")
        user_rows.append(row)

    return html.Div(user_rows), stats

# NEW: Admin password reset callback
@callback(
    [Output("reset-password-modal", "is_open"),
     Output("reset-password-store", "data"),
     Output("user-to-reset-info", "children"),
     Output("reset-password-alert", "children"),
     Output("reset-new-password", "value"),
     Output("reset-password-confirm", "value")],
    [Input({"type": "reset-user-password", "index": ALL}, "n_clicks"),
     Input("confirm-reset-password-btn", "n_clicks"),
     Input("cancel-reset-password-btn", "n_clicks")],
    [State("reset-new-password", "value"),
     State("reset-password-confirm", "value"),
     State("session-store", "data"),
     State("reset-password-store", "data")],
    prevent_initial_call=True
)
def handle_admin_password_reset(reset_clicks, confirm_click, cancel_click,
                               new_password, confirm_password, session_data, reset_store):
    triggered_id = ctx.triggered_id

    if isinstance(triggered_id, dict) and triggered_id.get("type") == "reset-user-password":
        if any(reset_clicks) and session_data and session_data.get("is_admin"):
            user_id = triggered_id["index"]

            # Get user info
            user = dbm.get_user_by_id(user_id)  # Ensure user exists
            if not user:
                return False, {}, "", dbc.Alert("User not found", color="danger"), "", ""

            username, email, _, _ = user
            user_info = html.Div([
                html.P([html.Strong("User: "), username]),
                html.P([html.Strong("Email: "), email or "No email"])
            ])
            return True, {"user_id": user_id}, user_info, "", "", ""

        return False, {}, "", "", "", ""

    elif triggered_id == "confirm-reset-password-btn" and reset_store:
        if not session_data or not session_data.get("is_admin"):
            return True, reset_store, no_update, dbc.Alert("Access denied", color="danger"), "", ""

        if not new_password:
            return True, reset_store, no_update, dbc.Alert("Password is required", color="danger"), "", ""

        if new_password != confirm_password:
            return True, reset_store, no_update, dbc.Alert("Passwords do not match", color="danger"), "", ""

        user_id = reset_store.get("user_id")
        if user_id:
            success, message = dbm.admin_reset_user_password(user_id, new_password)
            if success:
                return False, {}, "", "", "", ""
            else:
                return True, reset_store, no_update, dbc.Alert(message, color="danger"), "", ""

    elif triggered_id == "cancel-reset-password-btn":
        return False, {}, "", "", "", ""

    return no_update, no_update, no_update, no_update, no_update, no_update

# Admin user deletion callback
@callback(
    [Output("delete-user-modal", "is_open"),
     Output("delete-user-store", "data"),
     Output("user-to-delete-info", "children"),
     Output("delete-user-alert", "children")],
    [Input({"type": "delete-user", "index": ALL}, "n_clicks"),
     Input("confirm-delete-user-btn", "n_clicks"),
     Input("cancel-delete-user-btn", "n_clicks")],
    [State("session-store", "data"),
     State("delete-user-store", "data")],
    prevent_initial_call=True
)
def handle_admin_user_deletion(delete_clicks, confirm_click, cancel_click, session_data, delete_store):
    triggered_id = ctx.triggered_id

    if isinstance(triggered_id, dict) and triggered_id.get("type") == "delete-user":
        if any(delete_clicks) and session_data and session_data.get("is_admin"):
            user_id = triggered_id["index"]

            # Get user info
            user = dbm.get_user_by_id(user_id)  # Ensure user exists
            if not user:
                return False, {}, "", dbc.Alert("User not found", color="danger")

            username, email, _, is_admin = user
            if is_admin:
                return False, {}, "", dbc.Alert("Cannot delete admin user", color="danger")

            user_info = html.Div([
                html.P([html.Strong("User: "), username]),
                html.P([html.Strong("Email: "), email or "No email"])
            ])
            return True, {"user_id": user_id}, user_info, ""

        return False, {}, "", ""

    elif triggered_id == "confirm-delete-user-btn" and delete_store:
        if not session_data or not session_data.get("is_admin"):
            return True, delete_store, no_update, dbc.Alert("Access denied", color="danger")

        user_id = delete_store.get("user_id")
        if user_id:
            success, message = dbm.delete_user_and_projects(user_id)
            if success:
                return False, {}, "", ""
            else:
                return True, delete_store, no_update, dbc.Alert(message, color="danger")

    elif triggered_id == "cancel-delete-user-btn":
        return False, {}, "", ""

    return no_update, no_update, no_update, no_update

# Admin user projects viewer
@callback(
    [Output("user-projects-modal", "is_open"),
     Output("user-projects-content", "children")],
    [Input({"type": "view-user-projects", "index": ALL}, "n_clicks"),
     Input("close-user-projects-btn", "n_clicks")],
    [State("session-store", "data")],
    prevent_initial_call=True
)
def handle_view_user_projects(view_clicks, close_click, session_data):
    if ctx.triggered_id == "close-user-projects-btn":
        return False, ""

    if any(view_clicks) and session_data and session_data.get("is_admin"):
        triggered = ctx.triggered[0]
        if "view-user-projects" in triggered["prop_id"]:
            user_id = json.loads(triggered["prop_id"].split(".")[0])["index"]

            # Get user info and projects
            user = dbm.get_user_by_id(user_id)  # Ensure user exists
            if not user:
                return False, dbc.Alert("User not found", color="danger")
            
            username, _, _, _ = user
            projects = dbm.get_user_projects_admin(user_id)

            content = []
            content.append(html.H5([html.I(className="fas fa-user me-2"), f"{username}'s Projects"]))

            if not projects:
                content.append(dbc.Alert("No projects found for this user.", color="info"))
            else:
                for project in projects:
                    proj_id, name, description, created_at, last_accessed, file_count, total_size = project
                    size_mb = round(total_size / (1024 * 1024), 2) if total_size else 0

                    card = dbc.Card([
                        dbc.CardBody([
                            html.H6([html.I(className="fas fa-folder me-2"), name]),
                            html.P(description or "No description", className="text-muted"),
                            html.Small([
                                f"Files: {file_count} • Size: {size_mb} MB • ",
                                f"Created: {created_at} • Last accessed: {last_accessed}"
                            ], className="text-muted")
                        ])
                    ], className="mb-2")
                    content.append(card)

            return True, html.Div(content)

    return False, ""

# Navigation callbacks
@callback(
    Output("url", "pathname", allow_duplicate=True),
    Input("back-dashboard-btn", "n_clicks"),
    prevent_initial_call=True
)
def back_to_dashboard(n_clicks):
    if n_clicks:
        return "/dashboard"
    return no_update

@callback(
    Output("url", "pathname", allow_duplicate=True),
    Input("back-to-dashboard-btn", "n_clicks"),
    prevent_initial_call=True
)
def admin_back_to_dashboard(n_clicks):
    if n_clicks:
        return "/dashboard"
    return no_update

@callback(
    [Output("session-store", "data", allow_duplicate=True),
     Output("user-data-store", "data", allow_duplicate=True),
     Output("url", "pathname", allow_duplicate=True)],
    Input("logout-btn", "n_clicks"),
    prevent_initial_call=True
)
def logout(n_clicks):
    if n_clicks:
        return {}, {}, "/"
    return no_update, no_update, no_update

# Navigation active state callback
@callback(
    [Output("nav-viewer", "active"),
     Output("nav-pattern", "active"),
     Output("nav-rule_pattern", "active"),
     Output("nav-embed", "active"),
     Output("nav-telemetry", "active"),
     Output("nav-ai", "active")],
    Input("url", "pathname"),
)
def update_nav_active(pathname):
    if not pathname or not pathname.startswith("/workspace/"):
        return no_update, no_update, no_update, no_update, no_update, no_update

    page = pathname.split("/workspace/")[-1]
    return (
        page == "viewer" or page == "",  # Default to log viewer
        page == "pattern",
        page == "rule_pattern",
        page == "embed",
        page == "telemetry",
        page == "ai_analysis"
    )

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
