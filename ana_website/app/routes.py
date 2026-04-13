import os
import json
import jwt
from flask import Blueprint, request, jsonify, current_app, send_file
from werkzeug.utils import secure_filename
from pydantic import ValidationError

from .models import db, User, Task, Resource, Report
from .auth import generate_token, require_human_jwt, require_ana_system
from .validation import validate_json, TaskCreateRequest, TaskStatusUpdateRequest, ReportMetadataSchema
from .storage import save_chunked_file, QuotaExceededError

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

# ==========================================
# 1. Auth Endpoints
# ==========================================

@api_bp.route('/auth/login', methods=['POST'])
def login():
    """Exchanges human credentials for a short-lived JWT."""
    data = request.get_json()
    if not data or not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Missing credentials'}), 400

    user = User.query.filter_by(username=data['username'], is_active=True).first()
    if user and user.check_password(data['password']):
        token = generate_token(user.id)
        return jsonify({'token': token}), 200

    return jsonify({'error': 'Invalid credentials'}), 401

# ==========================================
# 2. Task Endpoints (The Mailbox)
# ==========================================

@api_bp.route('/tasks', methods=['POST'])
@require_human_jwt
@validate_json(TaskCreateRequest)
def create_task(current_user, payload: TaskCreateRequest):
    """Humans enqueue commands for Ana."""
    new_task = Task(
        submitter_id=current_user.id,
        command_type=payload.command_type,
        parameters=payload.parameters
    )
    db.session.add(new_task)
    db.session.commit()
    return jsonify({'task_id': new_task.id, 'status': new_task.status}), 201

@api_bp.route('/tasks/<task_id>', methods=['GET'])
@require_human_jwt
def get_task(current_user, task_id):
    """Humans poll for task status."""
    task = Task.query.filter_by(id=task_id, submitter_id=current_user.id).first_or_404()
    report_uri = f"/api/v1/reports/{task.report.id}" if task.report else None

    return jsonify({
        'id': task.id,
        'status': task.status,
        'command_type': task.command_type,
        'internal_correlation_id': task.internal_correlation_id,
        'result_report_uri': report_uri,
        'created_at': task.created_at.isoformat(),
        'updated_at': task.updated_at.isoformat()
    }), 200

@api_bp.route('/tasks/pending', methods=['GET'])
@require_ana_system
def get_pending_tasks():
    """Ana pulls pending commands."""
    tasks = Task.query.filter_by(status="PENDING").all()
    return jsonify([{
        'id': t.id,
        'command_type': t.command_type,
        'parameters': t.parameters
    } for t in tasks]), 200

@api_bp.route('/tasks/<task_id>/status', methods=['PATCH'])
@require_ana_system
@validate_json(TaskStatusUpdateRequest)
def update_task_status(task_id, payload: TaskStatusUpdateRequest):
    """Ana updates the status of a task."""
    task = Task.query.get_or_404(task_id)
    task.status = payload.status
    if payload.internal_correlation_id:
        task.internal_correlation_id = payload.internal_correlation_id

    db.session.commit()
    return jsonify({'message': 'Status updated successfully'}), 200

# ==========================================
# 3. Resource Endpoints
# ==========================================

@api_bp.route('/resources', methods=['POST'])
@require_ana_system
def upload_resource():
    """Ana uploads raw data files (strictly enforces 350MB limit)."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    filename = secure_filename(file.filename)

    new_resource = Resource(
        filename=filename,
        mime_type=file.mimetype,
        file_size_bytes=0,
        storage_path=""
    )
    db.session.add(new_resource)
    db.session.flush() # Get ID to construct path

    storage_path = os.path.join(current_app.config['RESOURCE_STORAGE_PATH'], f"{new_resource.id}_{filename}")
    new_resource.storage_path = storage_path

    try:
        # Stream intercept - this triggers the 413 if the quota is exceeded
        bytes_written = save_chunked_file(file.stream, storage_path)
        new_resource.file_size_bytes = bytes_written
        db.session.commit()
        return jsonify({'resource_id': new_resource.id, 'uri': f'/api/v1/resources/{new_resource.id}'}), 201
    except QuotaExceededError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 413

@api_bp.route('/resources/<resource_id>', methods=['GET'])
def download_resource(resource_id):
    """Both Human and Ana can download resources (Custom Auth Logic)."""
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401

    token = auth_header.split(' ')[1]
    is_authorized = (token == current_app.config.get('ANA_API_KEY'))

    if not is_authorized:
        try: # Check if it's a valid human JWT
            jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        return jsonify({'error': 'Unauthorized access'}), 401

    resource = Resource.query.get_or_404(resource_id)
    return send_file(resource.storage_path, mimetype=resource.mime_type, as_attachment=True, download_name=resource.filename)

@api_bp.route('/resources/<resource_id>', methods=['DELETE'])
@require_human_jwt
def delete_resource(current_user, resource_id):
    """Humans delete resources to free up filesystem quota."""
    resource = Resource.query.get_or_404(resource_id)
    if os.path.exists(resource.storage_path):
        os.remove(resource.storage_path)
    db.session.delete(resource)
    db.session.commit()
    return '', 204

# ==========================================
# 4. Report Endpoints
# ==========================================

@api_bp.route('/reports', methods=['POST'])
@require_ana_system
def upload_report():
    """Ana uploads intelligence deductions (multipart/form-data)."""
    metadata_str = request.form.get('metadata')
    if not metadata_str:
        return jsonify({'error': 'Missing metadata form field'}), 400

    try: # Manual Pydantic validation for the form field
        metadata_dict = json.loads(metadata_str)
        metadata = ReportMetadataSchema(**metadata_dict)
    except (json.JSONDecodeError, ValidationError) as e:
        return jsonify({'error': 'Invalid metadata', 'details': str(e)}), 400

    new_report = Report(
        task_id=metadata.triggering_task_id,
        title=metadata.title,
        deductions=[d.model_dump() for d in metadata.deductions],
        file_size_bytes=0
    )
    db.session.add(new_report)
    db.session.flush()

    # Process optional file attachment
    if 'file' in request.files and request.files['file'].filename != '':
        file = request.files['file']
        filename = secure_filename(file.filename)
        storage_path = os.path.join(current_app.config['REPORT_STORAGE_PATH'], f"{new_report.id}_{filename}")
        new_report.storage_path = storage_path

        try:
            bytes_written = save_chunked_file(file.stream, storage_path)
            new_report.file_size_bytes = bytes_written
        except QuotaExceededError as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 413

    db.session.commit()
    return jsonify({'report_id': new_report.id}), 201

@api_bp.route('/reports/<report_id>', methods=['GET'])
@require_human_jwt
def get_report(current_user, report_id):
    """Humans retrieve intelligence JSON and optionally download the attached file."""
    report = Report.query.get_or_404(report_id)

    # Simple tenant isolation: Ensure the report belongs to a task submitted by the user
    if report.task_id:
        task = Task.query.get(report.task_id)
        if task and task.submitter_id != current_user.id:
            return jsonify({'error': 'Unauthorized to view this report'}), 403

    # If the user wants the raw file instead of the JSON metadata
    if request.args.get('download_file') == 'true':
        if not report.storage_path or not os.path.exists(report.storage_path):
             return jsonify({'error': 'No file attached to this report'}), 404
        return send_file(report.storage_path, as_attachment=True)

    # Otherwise, return the JSON deductions
    response_data = {
        'id': report.id,
        'title': report.title,
        'deductions': report.deductions,
        'has_attached_file': bool(report.storage_path),
        'file_download_uri': f"/api/v1/reports/{report.id}?download_file=true" if report.storage_path else None
    }
    return jsonify(response_data), 200
