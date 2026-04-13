This is a crucial addition. Since we explicitly removed public registration to secure the system, a local CLI is the *only* way to bootstrap the environment and provision those trusted human users. Using Flask's built-in CLI framework (`click`) is perfect for this.

Here is the final, fully consolidated Public Proxy API Specification, now including **Section 7: Administrative CLI Tools**. You can copy this entire block for your new chat!

***

# Public Proxy API Specification: Ana System

## 1. Architectural Overview & Constraints
This system acts as a public-facing, asynchronous "Mailbox" or "State Proxy" between human users and the internal "Ana" event-driven system. 
* **Core Pattern:** Strict polling. No WebSockets or Webhooks are permitted. Ana pushes results and pulls pending commands; humans enqueue commands and poll for results.
* **Tech Stack:** Python, Flask, SQLite (with JSON1 extension) via SQLAlchemy, Pydantic for validation.
* **Storage Limit:** The server has a strict **350 MB** hard limit for the local filesystem. This must be programmatically enforced before files are fully written to disk.

## 2. Security & Identity Management
Strict Role-Based Access Control (RBAC) separates human users from the machine system. There are no public registration endpoints.

* **Human Users (Web Frontend):**
  * Accounts are manually provisioned by the administrator via local CLI tools.
  * Credentials are exchanged strictly out-of-band.
  * Humans authenticate via `POST /api/v1/auth/login` to receive a short-lived, HTTP-only JWT.
  * Protected by a `@require_human_jwt` decorator.
* **Ana System (Machine-to-Machine):**
  * Authenticates using a high-entropy API Key stored in Flask's environment variables (not in the DB).
  * Injected via the `Authorization: Bearer <API_KEY>` header.
  * Protected by a `@require_ana_system` decorator.

## 3. Database Schema (SQLAlchemy)
The database acts as the source of truth for both state and storage consumption.

```python
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    tasks = relationship("Task", back_populates="submitter")

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(String, primary_key=True, default=generate_uuid)
    submitter_id = Column(String, ForeignKey('users.id'), nullable=False)
    command_type = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="PENDING", index=True) # PENDING, IN_PROGRESS, COMPLETED, FAILED
    internal_correlation_id = Column(String, nullable=True) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    submitter = relationship("User", back_populates="tasks")
    report = relationship("Report", back_populates="task", uselist=False)

class Resource(Base):
    __tablename__ = 'resources'
    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False) # Used for storage quota
    storage_path = Column(String, nullable=False) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Report(Base):
    __tablename__ = 'reports'
    id = Column(String, primary_key=True, default=generate_uuid)
    task_id = Column(String, ForeignKey('tasks.id'), nullable=True)
    title = Column(String, nullable=False)
    deductions = Column(JSON, nullable=False) 
    file_size_bytes = Column(Integer, default=0)
    storage_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    task = relationship("Task", back_populates="report")
```

## 4. Input Validation (Pydantic)
All incoming JSON payloads must be validated using a `@validate_json(Model)` decorator that intercepts the request and returns a `400 Bad Request` upon failure.

```python
from pydantic import BaseModel, Field, field_validator
from typing import Dict, Any, List, Optional

class TaskCreateRequest(BaseModel):
    command_type: str = Field(..., min_length=1, max_length=100)
    parameters: Dict[str, Any] = Field(default_factory=dict)

class TaskStatusUpdateRequest(BaseModel):
    status: str = Field(...)
    internal_correlation_id: Optional[str] = Field(None)
    result_report_uri: Optional[str] = Field(None)

    @field_validator('status')
    @classmethod
    def status_must_be_valid(cls, v):
        allowed_statuses = ['IN_PROGRESS', 'COMPLETED', 'FAILED']
        if v not in allowed_statuses:
            raise ValueError(f'Status must be one of {allowed_statuses}')
        return v

class TupleModel(BaseModel):
    subject: str = Field(..., min_length=1)
    predicate: str = Field(..., min_length=1)
    object_: str = Field(..., min_length=1)

class ReportMetadataSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    triggering_task_id: Optional[str] = None
    deductions: List[TupleModel] = Field(default_factory=list)
```

## 5. Storage Quota Enforcement Logic
To strictly enforce the 350 MB limit, file uploads must utilize a chunked streaming function.

1.  **Calculate Space:** `available_space = 367_000_000 - (SUM(Resource.file_size_bytes) + SUM(Report.file_size_bytes))`
2.  **Stream Intercept:** Read the `flask_request.files` stream in 8KB chunks.
3.  **Enforce:** If `bytes_written > available_space`, immediately close the file, delete it from the OS, and return HTTP `413 Payload Too Large`.

## 6. API Route Definitions

**Auth Endpoints**
* `POST /api/v1/auth/login`: Human login to receive JWT.

**Task Endpoints (The Mailbox)**
* `POST /api/v1/tasks` (Human Only): Enqueue a command. Validates against `TaskCreateRequest`. Returns `201 Created` with `task_id`.
* `GET /api/v1/tasks/<task_id>` (Human Only): Poll for task status and report URI.
* `GET /api/v1/tasks/pending` (Ana Only): Returns list of tasks where status is "PENDING".
* `PATCH /api/v1/tasks/<task_id>/status` (Ana Only): Update task status. Validates against `TaskStatusUpdateRequest`.

**Resource Endpoints**
* `POST /api/v1/resources` (Ana Only): Upload raw data. Must enforce the 350 MB chunked upload limit. Returns `201 Created` and public URI.
* `GET /api/v1/resources/<resource_id>` (Human & Ana): Download raw data file.
* `DELETE /api/v1/resources/<resource_id>` (Human Only): Delete file from OS and DB to free storage.

**Report Endpoints**
* `POST /api/v1/reports` (Ana Only): Upload deductions and an optional file. Uses `multipart/form-data`. Manually parses the `metadata` form field against `ReportMetadataSchema` and enforces the 350 MB chunked upload limit for the file.
* `GET /api/v1/reports/<report_id>` (Human Only): Download the generated intelligence.

## 7. Administrative CLI Tools
To securely bootstrap the proxy server and provision users out-of-band, the application will expose local command-line tools using Flask's built-in `click` integration.

* **`flask admin init-db`**
  * **Purpose:** Creates the SQLite database file and generates all tables defined in the SQLAlchemy models. Also ensures the necessary local storage directories (e.g., `storage/resources`, `storage/reports`) exist.
* **`flask admin provision-user`**
  * **Purpose:** Creates a new trusted human user.
  * **Behavior:** Prompts securely for a username and a password. Hashes the password using a robust algorithm (e.g., `werkzeug.security.generate_password_hash` or `bcrypt`) before saving the `User` record to the database.

