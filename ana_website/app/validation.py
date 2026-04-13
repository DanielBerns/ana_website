from functools import wraps
from flask import request, jsonify
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import Dict, Any, List, Optional

# --- Pydantic Models from Spec ---

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

# --- Validation Decorator ---

def validate_json(model_class: type[BaseModel]):
    """Intercepts request, validates against Pydantic model, and handles 400s."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400

            try:
                # Validate and instantiate the Pydantic model
                validated_data = model_class(**request.get_json())
            except ValidationError as e:
                # Return standardized 400 response with Pydantic's exact error paths
                return jsonify({"error": "Validation failed", "details": e.errors()}), 400

            # Pass the typed Pydantic object into the route as a keyword argument
            kwargs['payload'] = validated_data
            return f(*args, **kwargs)
        return decorated_function
    return decorator
