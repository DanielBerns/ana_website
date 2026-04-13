from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Boolean
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

def generate_uuid():
    return str(uuid.uuid4())

class User(db.Model):
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tasks = db.relationship("Task", back_populates="submitter")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Task(db.Model):
    __tablename__ = 'tasks'
    id = Column(String, primary_key=True, default=generate_uuid)
    submitter_id = Column(String, ForeignKey('users.id'), nullable=False)
    command_type = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="PENDING", index=True)
    internal_correlation_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    submitter = db.relationship("User", back_populates="tasks")
    report = db.relationship("Report", back_populates="task", uselist=False)

class Resource(db.Model):
    __tablename__ = 'resources'
    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    storage_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Report(db.Model):
    __tablename__ = 'reports'
    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey('tasks.id'), nullable=True)
    title = Column(String, nullable=False)
    deductions = Column(JSON, nullable=False)
    file_size_bytes = Column(Integer, default=0)
    storage_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    task = db.relationship("Task", back_populates="report")
