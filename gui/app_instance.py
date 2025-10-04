from dash import Dash
import dash_bootstrap_components as dbc
from flask import Flask
import secrets
import os
from gui.db_manager import DBManager
dbm = DBManager()

from logai.utils.constants import BASE_DIR, UPLOAD_DIRECTORY

def create_app():
    # Initialize Flask server and Dash app
    flask_server = Flask(__name__, static_folder=UPLOAD_DIRECTORY)
    flask_server.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'logai_users.db')}"
    flask_server.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    SECRET_KEY = secrets.token_hex(16)
    flask_server.secret_key = SECRET_KEY

    # Database setup
    dbm.init_app(flask_server)
    dbm.create_tables(flask_server)

    app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        external_stylesheets=[
            dbc.themes.BOOTSTRAP, 
            "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css"
        ],
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
        title="LogAI",
        server=flask_server
    )

    return app, flask_server


