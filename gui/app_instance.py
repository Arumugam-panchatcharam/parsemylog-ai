from dash import Dash
import dash_bootstrap_components as dbc
from flask import Flask
import secrets
import os
from pathlib import Path
from gui.user_db_mngr import DBManager
from sentence_transformers import SentenceTransformer
dbm = DBManager()

from logai.utils.constants import (
    BASE_DIR, 
    UPLOAD_DIRECTORY,
    SENTENCE_TRANSFORMER_MODE_NAME,
)

EMBEDDING_MODEL=None

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

    # check and download sentence transformer
    model_path=os.path.join(BASE_DIR, SENTENCE_TRANSFORMER_MODE_NAME)
    if not os.path.exists(model_path):
        model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        model.save(model_path)
    global EMBEDDING_MODEL
    EMBEDDING_MODEL=SentenceTransformer(model_path)
    print(f"Loaded SentenceTransformer model from {model_path}")


    app = Dash(
        __name__,
        use_pages=True,
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


