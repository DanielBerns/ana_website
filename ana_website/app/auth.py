from functools import wraps
from flask import request, jsonify, current_app
import jwt
from datetime import datetime, timedelta, timezone
from .models import User

def generate_token(user_id: str) -> str:
    """Generates a short-lived HTTP-only JWT for human users."""
    payload = {
        'exp': datetime.now(timezone.utc) + timedelta(hours=2),
        'iat': datetime.now(timezone.utc),
        'sub': user_id
    }
    # PyJWT is required for this: pip install PyJWT
    return jwt.encode(payload, current_app.config['SECRET_KEY'], algorithm='HS256')

def require_human_jwt(f):
    """Decorator to enforce Human RBAC via JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid token'}), 401

        token = auth_header.split(' ')[1]
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.get(data['sub'])
            if not current_user or not current_user.is_active:
                raise ValueError("User inactive or missing")
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401

        # Inject the current_user into the route
        return f(current_user, *args, **kwargs)
    return decorated

def require_ana_system(f):
    """Decorator to enforce Machine RBAC via API Key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing API Key'}), 401

        token = auth_header.split(' ')[1]
        if token != current_app.config['ANA_API_KEY']:
            return jsonify({'error': 'Unauthorized system access'}), 401

        return f(*args, **kwargs)
    return decorated
