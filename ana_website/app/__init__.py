from flask import Flask
from .config import Config
from .models import db
from .cli import admin_cli

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)

    # Register CLI commands
    app.cli.add_command(admin_cli)

    from .routes import api_bp
    app.register_blueprint(api_bp)

    return app
