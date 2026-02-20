from typing import Optional, Any, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import UserMixin
import os
import uuid
import base64
import shutil
import logging
from pathlib import Path
from datetime import datetime
from logai.utils.constants import BASE_DIR, UPLOAD_DIRECTORY, QDRANT_URL

logger = logging.getLogger(__name__)

db = SQLAlchemy()

# ---------------- Models defined at module level ----------------

class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    email = db.Column(db.String(120), unique=False, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=db.func.now())
    last_login = db.Column(db.DateTime)

    # relationships
    projects = db.relationship(
        "Project",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    def __iter__(self):
        yield self.username
        yield self.email
        yield self.created_at
        yield self.is_admin

    # utility methods
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

class Natco(db.Model):
    __tablename__ = "natcos"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(16), unique=True, nullable=False)  # e.g. "DE", "PL"
    name = db.Column(db.String(120), nullable=False)              # e.g. "Germany"
    description = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    global_patterns = db.relationship(
        "GlobalPattern", back_populates="natco",
        cascade="all, delete-orphan", passive_deletes=True,
    )

class GlobalPattern(db.Model):
    __tablename__ = "global_patterns"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    natco_id = db.Column(db.Integer, db.ForeignKey("natcos.id", ondelete="CASCADE"), nullable=False)
    domain = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(256), nullable=False)
    regex = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    natco = db.relationship("Natco", back_populates="global_patterns")

class PatternSubmission(db.Model):
    __tablename__ = "pattern_submissions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    natco_id = db.Column(db.Integer, db.ForeignKey("natcos.id", ondelete="CASCADE"), nullable=False)
    domain = db.Column(db.String(120), nullable=False)
    patterns_json = db.Column(db.Text, nullable=False)   # JSON: [{name, regex, enabled}]
    comment = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default="pending") # pending / approved / rejected
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    admin_comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    user = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])
    natco = db.relationship("Natco")

class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.String(256), primary_key=True)   # matches TEXT PRIMARY KEY
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    natco_id = db.Column(db.Integer, db.ForeignKey("natcos.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(512), nullable=True)
    project_type = db.Column(db.String(20), default="normal")  # "normal" or "batch"
    created_at = db.Column(db.DateTime, default=db.func.now())
    last_accessed = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    # relationships
    user = db.relationship("User", back_populates="projects")
    natco = db.relationship("Natco")
    files = db.relationship(
        "ProjectFile",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
    cpes = db.relationship(
        "ProjectCPE",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    def __iter__(self):
        yield self.id
        yield self.name
        yield self.description
        yield self.created_at
        yield self.last_accessed

class ProjectCPE(db.Model):
    __tablename__ = "project_cpes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(256), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    serial = db.Column(db.String(256), nullable=False)
    mac = db.Column(db.String(64), nullable=True)
    date_from = db.Column(db.String(32), nullable=True)
    date_to = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())

    project = db.relationship("Project", back_populates="cpes")

class ProjectFile(db.Model):
    __tablename__ = "project_files"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(256), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    cpe_id = db.Column(db.String(256), nullable=True)  # serial of CPE, or None for legacy
    filename = db.Column(db.String(256), nullable=False)
    original_name = db.Column(db.String(256), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=db.func.now())

    # relationships
    project = db.relationship("Project", back_populates="files")

    def __iter__(self):
        yield self.filename
        yield self.file_path
        yield self.original_name
        yield self.file_size
        yield self.uploaded_at

class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(120), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

class ChatConversation(db.Model):
    __tablename__ = "chat_conversations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(256), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cpe_id = db.Column(db.String(256), nullable=True)
    title = db.Column(db.String(256), nullable=False, default="New conversation")
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    messages = db.relationship(
        "ChatMessage", back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # system, user, assistant
    content = db.Column(db.Text, nullable=False)
    context_used = db.Column(db.Text, nullable=True)  # JSON metadata
    created_at = db.Column(db.DateTime, default=db.func.now())

    conversation = db.relationship("ChatConversation", back_populates="messages")

class BatchJob(db.Model):
    __tablename__ = "batch_jobs"

    id = db.Column(db.String(64), primary_key=True)  # UUID
    project_id = db.Column(db.String(256), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_type = db.Column(db.String(32), default="cpe_processing")  # cpe_processing, pattern_indexing
    total_cpes = db.Column(db.Integer, default=0)
    processed_cpes = db.Column(db.Integer, default=0)
    failed_cpes = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="queued")  # queued, processing, completed, failed, cancelled
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # relationships
    cpe_records = db.relationship(
        "CPEProcessRecord",
        back_populates="batch_job",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

class CPEProcessRecord(db.Model):
    __tablename__ = "cpe_process_records"

    id = db.Column(db.String(64), primary_key=True)  # UUID
    job_id = db.Column(db.String(64), db.ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False)
    serial = db.Column(db.String(256), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, processing, completed, failed, skipped
    celery_task_id = db.Column(db.String(64), nullable=True)  # Celery task UUID
    error_message = db.Column(db.Text, nullable=True)
    processing_time_sec = db.Column(db.Float, nullable=True)
    logs_extracted = db.Column(db.Integer, default=0)
    patterns_indexed = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=db.func.now())
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # relationships
    batch_job = db.relationship("BatchJob", back_populates="cpe_records")


class DBManager:
    def __init__(self, upload_root: str = BASE_DIR):
        self.db = db
        self.upload_root = upload_root
        os.makedirs(upload_root, exist_ok=True)

        # Expose models as instance attributes for backward compatibility
        self.User = User
        self.Natco = Natco
        self.GlobalPattern = GlobalPattern
        self.PatternSubmission = PatternSubmission
        self.Project = Project
        self.ProjectCPE = ProjectCPE
        self.ProjectFile = ProjectFile
        self.SystemSetting = SystemSetting
        self.ChatConversation = ChatConversation
        self.ChatMessage = ChatMessage
        self.BatchJob = BatchJob
        self.CPEProcessRecord = CPEProcessRecord

    # ---------------- Initialization ----------------
    def init_app(self, app):
        self.db.init_app(app)

        # Enable SQLite foreign key enforcement (required for argument ON DELETE CASCADE)
        from sqlalchemy import event as sa_event
        with app.app_context():
            @sa_event.listens_for(self.db.engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    
    def create_tables(self, app):
        with app.app_context():
            self.db.create_all()
            # Migrate existing tables: add cpe_id column if missing
            self._migrate_add_cpe_columns(app)
            # create default admin user if not exists
            if not self.db.session.query(self.User).filter_by(username='admin').first():
                self.create_user("admin", "admin123", is_admin=True)
            # Seed default system settings
            if not self.db.session.query(self.SystemSetting).filter_by(key="llm_enabled").first():
                self.db.session.add(self.SystemSetting(key="llm_enabled", value="true"))
                self.db.session.commit()

            # Clean up orphaned chat messages (from past deletes without FK enforcement)
            orphaned = (
                self.db.session.query(self.ChatMessage)
                .filter(
                    ~self.ChatMessage.conversation_id.in_(
                        self.db.session.query(self.ChatConversation.id)
                    )
                )
                .all()
            )
            if orphaned:
                for msg in orphaned:
                    self.db.session.delete(msg)
                self.db.session.commit()
                logger.info(f"Cleaned up {len(orphaned)} orphaned chat messages")

    def _migrate_add_cpe_columns(self, app):
        """Add cpe_id column to project_files and natco_id to projects if missing."""
        try:
            with app.app_context():
                from sqlalchemy import text, inspect as sa_inspect
                inspector = sa_inspect(self.db.engine)
                # project_files: cpe_id
                cols = [c["name"] for c in inspector.get_columns("project_files")]
                if "cpe_id" not in cols:
                    self.db.session.execute(text("ALTER TABLE project_files ADD COLUMN cpe_id VARCHAR(256)"))
                    self.db.session.commit()
                    logger.info("[Migration] Added cpe_id column to project_files")
                # projects: natco_id
                proj_cols = [c["name"] for c in inspector.get_columns("projects")]
                if "natco_id" not in proj_cols:
                    self.db.session.execute(text("ALTER TABLE projects ADD COLUMN natco_id INTEGER REFERENCES natcos(id)"))
                    self.db.session.commit()
                    logger.info("[Migration] Added natco_id column to projects")
        except Exception as e:
            logger.warning(f"[Migration] Could not add columns (may already exist): {e}")

    # ---------------- User operations ----------------
    def create_user(self, username: str, password: str, email: Optional[str] = None, is_admin: bool = False) -> Tuple[bool, Optional[str]]:
        if not username or not password:
            return False, "Username and password are required."
        if self.db.session.query(self.User).filter_by(username=username).first():
            return False, "Username already exists."
        u = self.User(username=username, email=email, is_admin=is_admin)
        u.set_password(password)
        self.db.session.add(u)
        try:
            self.db.session.commit()
            return True, None
        except Exception as e:
            self.db.session.rollback()
            return False, str(e)

    def authenticate_user(self, username_or_email: str, password: str) -> Optional[Any]:
        """Authenticate and return user or None.
        Accepts either username or email in the first parameter.
        """
        if not username_or_email or not password:
            return None
        # Try by username first
        u = self.db.session.query(self.User).filter_by(username=username_or_email).first()
        if u and u.check_password(password):
            u.last_login = datetime.now()
            self.db.session.commit()
            return True, u.id, u.is_admin
        # Then try by email
        if "@" in (username_or_email or ""):
            u = self.db.session.query(self.User).filter_by(email=username_or_email).first()
            if u and u.check_password(password):
                u.last_login = datetime.now()
                self.db.session.commit()
                return True, u.id, u.is_admin
        return False, None, None

    def get_user_by_id(self, user_id: int) -> Optional[Any]:
        return self.db.session.get(self.User, int(user_id))

    def get_user_by_username(self, username: str) -> Optional[Any]:
        return self.db.session.query(self.User).filter_by(username=username).first()

    def update_user(self, user_id: int, username: Optional[str] = None, password: Optional[str] = None,
                    email: Optional[str] = None, is_admin: Optional[bool] = None) -> Tuple[bool, Optional[str]]:
        """
        Update user fields. Only non-None parameters will be updated.
        Returns (True, None) on success, or (False, error_message).
        """
        user = self.db.session.get(self.User, int(user_id))
        if not user:
            return False, "User not found."

        # If username is changing, ensure it's not taken by another user
        if username is not None:
            username = username.strip()
            if not username:
                return False, "Username cannot be empty."
            existing = self.db.session.query(self.User).filter(self.User.username == username, self.User.id != user.id).first()
            if existing:
                return False, "Username already taken."
            user.username = username

        if password is not None:
            if password == "":
                return False, "Password cannot be empty."
            user.set_password(password)

        if email is not None:
            user.email = email

        if is_admin is not None:
            try:
                user.is_admin = bool(is_admin)
            except Exception:
                user.is_admin = is_admin

        try:
            self.db.session.commit()
            return True, None
        except Exception as e:
            self.db.session.rollback()
            return False, str(e)

    def save_local_file(self, local_file_path, project_id):
        with open(local_file_path, "rb") as f:
            data = f.read()

        # Encode like dcc.Upload provides
        encoded = base64.b64encode(data).decode("utf-8")
        mime_type = "application/octet-stream"  # or detect via mimetypes
        contents = f"data:{mime_type};base64,{encoded}"

        # Get filename
        filename = os.path.basename(local_file_path)
        return self.save_uploaded_file(project_id, contents, filename)
        
    # ---------------- File operations ----------------
    def save_uploaded_file(self, project_id: str, file_content, filename):
        """
        Save an uploaded file to disk using its original filename.

        Files are stored as-is (no UUID renaming) inside the project
        directory ``UPLOAD_DIRECTORY/{user_id}/{project_id}/{filename}``.
        The ``filename`` and ``original_name`` DB columns both hold the
        original name for backward-compatibility.
        """
        project = self.db.session.query(self.Project).filter_by(id=project_id).first()
        user_id = project.user_id
        try:
            content_type, content_string = file_content.split(',')
            decoded = base64.b64decode(content_string)

            project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
            project_dir.mkdir(parents=True, exist_ok=True)
            file_path = project_dir / filename

            with open(file_path, 'wb') as f:
                f.write(decoded)

            uploaded_file = self.ProjectFile(
                                project_id = project_id,
                                filename = filename,
                                original_name = filename,
                                file_path = str(file_path),
                                file_size = len(decoded)
                                )
            
            self.db.session.add(uploaded_file)
            self.db.session.commit()
            return True, "File uploaded successfully"
        except Exception as e:
            self.db.session.rollback()
            return False, None,str(e)

    def get_project_files(self, project_id: str, cpe_id: str = None):
        q = self.db.session.query(self.ProjectFile).filter_by(project_id=project_id)
        if cpe_id is not None:
            q = q.filter_by(cpe_id=cpe_id)
        return q.order_by(func.lower(self.ProjectFile.original_name)).all()

    # ---------------- CPE operations ----------------
    def list_project_cpes(self, project_id: str):
        return (
            self.db.session.query(self.ProjectCPE)
            .filter_by(project_id=project_id)
            .order_by(self.ProjectCPE.serial)
            .all()
        )

    def save_cpe(self, project_id: str, serial: str, mac: str = None,
                 date_from: str = None, date_to: str = None):
        existing = (
            self.db.session.query(self.ProjectCPE)
            .filter_by(project_id=project_id, serial=serial)
            .first()
        )
        if existing:
            if mac:
                existing.mac = mac
            if date_from:
                existing.date_from = date_from
            if date_to:
                existing.date_to = date_to
        else:
            cpe = self.ProjectCPE(
                project_id=project_id, serial=serial,
                mac=mac, date_from=date_from, date_to=date_to,
            )
            self.db.session.add(cpe)
        try:
            self.db.session.commit()
            return True
        except Exception as e:
            self.db.session.rollback()
            logger.error(f"Failed to save CPE {serial}: {e}")
            return False

    def save_cpe_file(self, project_id: str, cpe_id: str, file_path: Path, filename: str):
        """Save a file record for a specific CPE."""
        size = file_path.stat().st_size if file_path.exists() else 0
        pf = self.ProjectFile(
            project_id=project_id,
            cpe_id=cpe_id,
            filename=filename,
            original_name=filename,
            file_path=str(file_path),
            file_size=size,
        )
        self.db.session.add(pf)
        try:
            self.db.session.commit()
            return True
        except Exception as e:
            self.db.session.rollback()
            logger.error(f"Failed to save CPE file {filename}: {e}")
            return False
    
    def get_project_file_info(self, project_id:str, filename: str, cpe_id: str = None) -> Optional[Any]:
        q = self.db.session.query(self.ProjectFile).filter_by(project_id=project_id, filename=filename)
        if cpe_id is not None:
            q = q.filter_by(cpe_id=cpe_id)
        return q.first()
    
    def get_project_file_info_orig_name(self, project_id:str, original_name: str) -> Optional[Any]:
        return self.db.session.query(self.ProjectFile).filter_by(project_id=project_id, original_name=original_name).first()
    
    def get_project_file_info_by_id(self, project_id:str, file_id) -> Optional[Any]:
        return self.db.session.query(self.ProjectFile).filter_by(project_id=project_id, file_id=file_id).first()

    def get_user_files(self, user_id: int):
        return self.db.session.query(self.ProjectFile).filter_by(user_id=user_id).all()

    # ---------------- Project operations ----------------
    def create_project(self, user_id: int, name: str, description: str, project_type: str = "normal") -> Tuple[bool, int, Optional[str]]:
        if not name:
            return False, "Project name required."
        if project_type not in ["normal", "batch"]:
            project_type = "normal"
        project_id = str(uuid.uuid4())
        project = self.Project(id=project_id, user_id=user_id, name=name, description=description, project_type=project_type)
        self.db.session.add(project)
        try:
            self.db.session.commit()
            project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
            project_dir.mkdir(parents=True, exist_ok=True)

            return True, project_id, "Project created successfully"
        except Exception as e:
            self.db.session.rollback()
            return False, None,str(e)

    def get_user_projects(self, user_id: int):
        return self.db.session.query(self.Project).filter_by(user_id=user_id).all()
    
    def get_project_by_id(self, project_id: str) -> Optional[Any]:
        #print(self.db.session.query(self.Project).filter_by(project_id=project_id).first())
        return self.db.session.query(self.Project).filter_by(id=project_id).first()
    
    def _delete_qdrant_collections(self, project_id: str) -> None:
        """
        Delete all Qdrant vector collections for a project.

        Handles both legacy ``project_{project_id}`` and per-CPE
        ``project_{project_id}_cpe_{serial}`` collection names.
        Failures are logged but never propagated.
        """
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=QDRANT_URL, timeout=10)

            # Delete main legacy collection
            try:
                client.delete_collection(f"project_{project_id}")
                logger.info(f"Deleted Qdrant collection 'project_{project_id}'")
            except Exception:
                pass

            # Delete per-CPE collections
            cpes = self.list_project_cpes(project_id)
            for cpe in cpes:
                name = f"project_{project_id}_cpe_{cpe.serial}"
                try:
                    client.delete_collection(name)
                    logger.info(f"Deleted Qdrant collection '{name}'")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to delete Qdrant collections for project {project_id}: {e}")

    def delete_project(self, project_id: str, user_id: int) -> Tuple[bool, Optional[str]]:
        """
        Delete a project and all associated resources.

        Multi-user safe: waits for any active indexer thread to finish
        before removing files, preventing write-after-delete races.
        """
        project = self.db.session.query(self.Project).filter_by(id=project_id).first()
        if not project:
            return False, "Project not found."
        try:
            # Wait for any active indexer to finish before deleting files
            # to prevent write-after-delete races.
            try:
                from api.indexer import _get_project_lock
                lock = _get_project_lock(project_id)
                logger.info(f"[DeleteProject] Acquiring indexer lock for {project_id}...")
                lock.acquire()  # Blocking: wait until indexer finishes
                try:
                    self.db.session.delete(project)
                    self.db.session.commit()

                    # Remove entire project directory (includes drain3_*.json,
                    # all *_rg.parquet caches, status.json, uploaded files, archives)
                    project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                    if project_dir.exists():
                        logger.info(f"Removing project directory: {project_dir}")
                        shutil.rmtree(project_dir, ignore_errors=True)

                    # Clean up Qdrant vector collection for this project
                    self._delete_qdrant_collections(project_id)
                finally:
                    lock.release()
            except ImportError:
                # Fallback if callbacks not loaded yet (e.g. during tests)
                self.db.session.delete(project)
                self.db.session.commit()
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
                if project_dir.exists():
                    shutil.rmtree(project_dir, ignore_errors=True)
                self._delete_qdrant_collections(project_id)

            logger.info(f"Project {project_id} deleted successfully")
            return True, "Project deleted successfully"
        except Exception as e:
            self.db.session.rollback()
            logger.error(f"Failed to delete project {project_id}: {e}")
            return False, str(e)

    # ---------------- Admin operations ----------------
    def get_user_projects_admin(self, user_id: int):
        Project = self.Project
        ProjectFile = self.ProjectFile
        
        # Subquery: count files per project
        file_count = (
            self.db.session.query(func.count(ProjectFile.id))
            .filter(ProjectFile.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )

        # Subquery: sum of file sizes (default to 0 if NULL)
        total_size = (
        self.db.session.query(func.coalesce(func.sum(ProjectFile.file_size), 0))
            .filter(ProjectFile.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )

        query = (
        self.db.session.query(
            Project.id,
            Project.name,
            Project.description,
            Project.created_at,
            Project.last_accessed,
            file_count.label("file_count"),
            total_size.label("total_size"),
        )
            .filter(Project.user_id == user_id)
            .order_by(Project.last_accessed.desc())
        )

        return query.all()
    
    def admin_reset_user_password(self, user_id: int, new_password: str) -> Tuple[bool, Optional[str]]:
        user = self.db.session.get(self.User, int(user_id))
        if not user:
            return False, "User not found."
        if not new_password:
            return False, "New password cannot be empty."
        user.set_password(new_password)
        try:
            self.db.session.commit()
            return True, None
        except Exception as e:
            self.db.session.rollback()
            return False, str(e)
        
    def get_all_user(self):
        Project = self.Project
        ProjectFile = self.ProjectFile
        User = self.User

        # Count projects per user
        project_count = (
            self.db.session.query(func.count(Project.id))
            .filter(Project.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )

        # Count files per user (via join)
        file_count = (
            self.db.session.query(func.count(ProjectFile.id))
            .join(Project, Project.id == ProjectFile.project_id)
            .filter(Project.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )

        query = (
            self.db.session.query(
                User.id,
                User.username,
                User.email,
                User.is_admin,
                User.created_at,
                User.last_login,
                project_count.label("project_count"),
                file_count.label("file_count"),
            )
            .order_by(User.created_at.desc())
        )
        #print(query.all())
        return query.all()

    # ---------------- System Settings ----------------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.db.session.query(self.SystemSetting).filter_by(key=key).first()
        return row.value if row else default

    def set_setting(self, key: str, value: str) -> None:
        row = self.db.session.query(self.SystemSetting).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = self.SystemSetting(key=key, value=value)
            self.db.session.add(row)
        self.db.session.commit()

    # ---------------- Chat Conversations ----------------
    def create_conversation(self, project_id: str, user_id: int,
                            cpe_id: str = None, title: str = "New conversation"):
        conv = self.ChatConversation(
            project_id=project_id, user_id=user_id,
            cpe_id=cpe_id, title=title,
        )
        self.db.session.add(conv)
        self.db.session.commit()
        return conv

    def get_conversations(self, project_id: str, user_id: int, cpe_id: str = None):
        q = (
            self.db.session.query(self.ChatConversation)
            .filter_by(project_id=project_id, user_id=user_id)
        )
        if cpe_id is not None:
            q = q.filter_by(cpe_id=cpe_id)
        return q.order_by(self.ChatConversation.updated_at.desc()).all()

    def get_conversation_by_id(self, conv_id: int):
        return self.db.session.get(self.ChatConversation, int(conv_id))

    def delete_conversation(self, conv_id: int) -> bool:
        conv = self.db.session.get(self.ChatConversation, int(conv_id))
        if not conv:
            return False
        self.db.session.delete(conv)
        self.db.session.commit()
        return True

    # ---------------- Chat Messages ----------------
    def save_message(self, conversation_id: int, role: str, content: str,
                     context_used: str = None):
        msg = self.ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            context_used=context_used,
        )
        self.db.session.add(msg)
        # Touch the conversation's updated_at
        conv = self.db.session.get(self.ChatConversation, int(conversation_id))
        if conv:
            conv.updated_at = datetime.now()
        self.db.session.commit()
        return msg

    def get_messages(self, conversation_id: int, limit: int = 50):
        return (
            self.db.session.query(self.ChatMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(self.ChatMessage.created_at.asc())
            .limit(limit)
            .all()
        )

    def delete_user_and_projects(self, user_id: int) -> Tuple[bool, Optional[str]]:
        user = self.db.session.get(self.User, int(user_id))
        if not user:
            return False, "User not found."
        if user.is_admin:
            return False, "Cannot delete admin user."
        try:
            # Delete associated projects, files, and Qdrant collections
            projects = self.db.session.query(self.Project).filter_by(user_id=user_id).all()
            for project in projects:
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project.id}')
                if project_dir.exists():
                    shutil.rmtree(project_dir)
                # Clean up Qdrant vector collection for each project
                self._delete_qdrant_collections(project.id)
                self.db.session.delete(project)

            # Finally delete the user
            self.db.session.delete(user)
            self.db.session.commit()
            user_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}')
            if user_dir.exists():
                shutil.rmtree(user_dir)

            return True, "User and associated projects deleted successfully"
        except Exception as e:
            self.db.session.rollback()
            return False, str(e)

    # ---------------- Batch Job operations ----------------
    def create_batch_job(self, project_id: str, user_id: int, total_cpes: int, 
                        job_type: str = "cpe_processing") -> str:
        """Create a new batch processing job and return its ID."""
        job_id = str(uuid.uuid4())
        job = self.BatchJob(
            id=job_id,
            project_id=project_id,
            user_id=user_id,
            total_cpes=total_cpes,
            job_type=job_type,
            status="queued",
        )
        self.db.session.add(job)
        self.db.session.commit()
        logger.info(f"Created batch job {job_id} for project {project_id} with {total_cpes} CPEs")
        return job_id

    def get_batch_job(self, job_id: str) -> Optional[Any]:
        """Get batch job by ID."""
        return self.db.session.get(self.BatchJob, job_id)

    def get_project_batch_jobs(self, project_id: str, limit: int = 50):
        """Get all batch jobs for a project, ordered by most recent first."""
        return (
            self.db.session.query(self.BatchJob)
            .filter_by(project_id=project_id)
            .order_by(self.BatchJob.created_at.desc())
            .limit(limit)
            .all()
        )

    def create_cpe_record(self, job_id: str, serial: str, celery_task_id: str = None) -> str:
        """Create a CPE processing record and return its ID."""
        record_id = str(uuid.uuid4())
        record = self.CPEProcessRecord(
            id=record_id,
            job_id=job_id,
            serial=serial,
            status="pending",
            celery_task_id=celery_task_id,
        )
        self.db.session.add(record)
        self.db.session.commit()
        return record_id

    def update_batch_job_status(self, job_id: str, status: str, error_message: str = None):
        """Update batch job status."""
        job = self.db.session.get(self.BatchJob, job_id)
        if not job:
            return False
        job.status = status
        if error_message:
            job.error_message = error_message
        if status == "processing" and not job.started_at:
            job.started_at = datetime.now()
        if status in ("completed", "failed", "cancelled"):
            job.completed_at = datetime.now()
        self.db.session.commit()
        return True

    def increment_batch_job_progress(self, job_id: str, success: bool = True):
        """Increment processed or failed CPE count."""
        job = self.db.session.get(self.BatchJob, job_id)
        if not job:
            return False
        if success:
            job.processed_cpes += 1
        else:
            job.failed_cpes += 1
        self.db.session.commit()
        return True

    def get_cpe_record(self, record_id: str) -> Optional[Any]:
        """Get CPE process record by ID."""
        return self.db.session.get(self.CPEProcessRecord, record_id)

    def get_job_cpe_records(self, job_id: str, status: str = None):
        """Get all CPE records for a job, optionally filtered by status."""
        q = self.db.session.query(self.CPEProcessRecord).filter_by(job_id=job_id)
        if status:
            q = q.filter_by(status=status)
        return q.order_by(self.CPEProcessRecord.created_at.asc()).all()

    def update_cpe_record_status(self, record_id: str, status: str, 
                                 error_message: str = None, 
                                 logs_extracted: int = None,
                                 patterns_indexed: int = None):
        """Update CPE processing record status and metrics."""
        record = self.db.session.get(self.CPEProcessRecord, record_id)
        if not record:
            return False
        record.status = status
        if error_message:
            record.error_message = error_message
        if logs_extracted is not None:
            record.logs_extracted = logs_extracted
        if patterns_indexed is not None:
            record.patterns_indexed = patterns_indexed
        if status == "processing" and not record.started_at:
            record.started_at = datetime.now()
        if status in ("completed", "failed", "skipped"):
            record.completed_at = datetime.now()
            if record.started_at:
                delta = (record.completed_at - record.started_at).total_seconds()
                record.processing_time_sec = delta
        self.db.session.commit()
        return True

    def delete_batch_job(self, job_id: str) -> Tuple[bool, Optional[str]]:
        """Delete a batch job and all its CPE records."""
        job = self.db.session.get(self.BatchJob, job_id)
        if not job:
            return False, "Job not found"
        try:
            self.db.session.delete(job)
            self.db.session.commit()
            return True, "Job deleted successfully"
        except Exception as e:
            self.db.session.rollback()
            return False, str(e)
