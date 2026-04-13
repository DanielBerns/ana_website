import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
    ANA_API_KEY = os.environ.get('ANA_API_KEY', 'dev-ana-key-change-in-prod')

    # Database
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'proxy.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Storage Limits & Paths
    STORAGE_LIMIT_BYTES = 350 * 1024 * 1024  # 350 MB
    RESOURCE_STORAGE_PATH = os.path.join(basedir, 'storage', 'resources')
    REPORT_STORAGE_PATH = os.path.join(basedir, 'storage', 'reports')
