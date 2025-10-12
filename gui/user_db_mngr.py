from typing import Optional, Any, Tuple
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_login import UserMixin
import os
import uuid
import base64
import shutil
from pathlib import Path
from datetime import datetime
from logai.utils.constants import BASE_DIR, UPLOAD_DIRECTORY

db = SQLAlchemy()

class DBManager:
    def __init__(self, upload_root: str = BASE_DIR):
        self.db = db
        self.upload_root = upload_root
        os.makedirs(upload_root, exist_ok=True)

        # ---------------- User Model ----------------
        class User(self.db.Model, UserMixin):
            __tablename__ = "users"

            id = self.db.Column(self.db.Integer, primary_key=True, autoincrement=True)
            username = self.db.Column(self.db.String(80), unique=True, nullable=False)
            password_hash = self.db.Column(self.db.String(128), nullable=False)
            email = self.db.Column(self.db.String(120), unique=False, nullable=True)
            is_admin = self.db.Column(self.db.Boolean, default=False)
            created_at = self.db.Column(self.db.DateTime, default=self.db.func.now())
            last_login = self.db.Column(self.db.DateTime)

            # relationships
            projects = self.db.relationship(
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
        
        self.User = User

        # ---------------- Project Model ----------------
        class Project(self.db.Model):
            __tablename__ = "projects"

            id = self.db.Column(self.db.String(256), primary_key=True)   # matches TEXT PRIMARY KEY
            user_id = self.db.Column(self.db.Integer, self.db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
            name = self.db.Column(self.db.String(120), nullable=False)
            description = self.db.Column(self.db.String(512), nullable=True)
            created_at = self.db.Column(self.db.DateTime, default=self.db.func.now())
            last_accessed = self.db.Column(self.db.DateTime, default=self.db.func.now(), onupdate=self.db.func.now())

            # relationships
            user = self.db.relationship("User", back_populates="projects")
            files = self.db.relationship(
                "ProjectFile",
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

        self.Project = Project

        # ---------------- Project File Model ----------------
        class ProjectFile(self.db.Model):
            __tablename__ = "project_files"

            id = self.db.Column(self.db.Integer, primary_key=True, autoincrement=True)
            project_id = self.db.Column(self.db.String(256), self.db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
            filename = self.db.Column(self.db.String(256), nullable=False)
            original_name = self.db.Column(self.db.String(256), nullable=False)
            file_path = self.db.Column(self.db.String(512), nullable=False)
            file_size = self.db.Column(self.db.Integer, nullable=True)
            uploaded_at = self.db.Column(self.db.DateTime, default=self.db.func.now())

            # relationships
            project = self.db.relationship("Project", back_populates="files")

            def __iter__(self):
                yield self.filename
                yield self.file_path
                yield self.original_name
                yield self.file_size
                yield self.uploaded_at

        self.ProjectFile = ProjectFile

    # ---------------- Initialization ----------------
    def init_app(self, app):
        self.db.init_app(app)
    
    def create_tables(self, app):
        with app.app_context():
            self.db.create_all()
            # create default admin user if not exists
            if not self.db.session.query(self.User).filter_by(username='admin').first():
                self.create_user("admin", "admin123", is_admin=True)

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
        project = self.db.session.query(self.Project).filter_by(id=project_id).first()
        user_id = project.user_id
        #print("user id {} project id {}".format(user_id, project_id))
        try:
            content_type, content_string = file_content.split(',')
            decoded = base64.b64decode(content_string)

            file_extension = Path(filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_extension}"

            project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
            project_dir.mkdir(parents=True, exist_ok=True)
            file_path = project_dir / unique_filename

            with open(file_path, 'wb') as f:
                f.write(decoded)

            uploaded_file = self.ProjectFile(
                                project_id = project_id,
                                filename = unique_filename,
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

    def get_project_files(self, project_id: str):
        #print("Getting files for project:", project_id)
        #print(self.db.session.query(self.ProjectFile).filter_by(project_id=project_id).all())
        files = (
            self.db.session.query(self.ProjectFile)
            .filter_by(project_id=project_id)
            .order_by(func.lower(self.ProjectFile.original_name))
            .all()
            )
        return files
    
    def get_project_file_info(self, project_id:str, filename: str) -> Optional[Any]:
        return self.db.session.query(self.ProjectFile).filter_by(project_id=project_id, filename=filename).first()
    
    def get_project_file_info_by_id(self, project_id:str, file_id) -> Optional[Any]:
        return self.db.session.query(self.ProjectFile).filter_by(project_id=project_id, file_id=file_id).first()

    def get_user_files(self, user_id: int):
        return self.db.session.query(self.ProjectFile).filter_by(user_id=user_id).all()

    # ---------------- Project operations ----------------
    def create_project(self, user_id: int, name: str, description: str) -> Tuple[bool, int, Optional[str]]:
        if not name:
            return False, "Project name required."
        project_id = str(uuid.uuid4())
        project = self.Project(id=project_id,user_id=user_id, name=name, description=description)
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
    
    def delete_project(self, project_id: str, user_id: int) -> Tuple[bool, Optional[str]]:
        project = self.db.session.query(self.Project).filter_by(id=project_id).first()
        if not project:
            return False, "Project not found."
        try:
            self.db.session.delete(project)
            self.db.session.commit()

            project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project_id}')
            if project_dir.exists():
                shutil.rmtree(project_dir)

            return True, "Project deleted successfully"
        except Exception as e:
            self.db.session.rollback()
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

    def delete_user_and_projects(self, user_id: int) -> Tuple[bool, Optional[str]]:
        user = self.db.session.get(self.User, int(user_id))
        if not user:
            return False, "User not found."
        if user.is_admin:
            return False, "Cannot delete admin user."
        try:
            # Delete associated projects and files
            projects = self.db.session.query(self.Project).filter_by(user_id=user_id).all()
            for project in projects:
                project_dir = Path(f'{UPLOAD_DIRECTORY}/{user_id}/{project.id}')
                if project_dir.exists():
                    shutil.rmtree(project_dir)
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
