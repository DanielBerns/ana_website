from pathlib import Path
import click
from flask.cli import AppGroup
from .models import db, User

admin_cli = AppGroup('admin')

@admin_cli.command('init-db')
def init_db():
    """Creates the SQLite database and storage directories."""
    from flask import current_app

    # Create storage directories
    resource_storage_path = Path(current_app.config['RESOURCE_STORAGE_PATH'])
    resource_storage_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    report_storage_path = Path(current_app.config['REPORT_STORAGE_PATH'])
    report_storage_path.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Create database tables
    db.create_all()
    click.echo('Database initialized and storage directories created successfully.')

@admin_cli.command('provision-user')
@click.option('--username', prompt='Username', help='The username for the new human proxy user.')
@click.password_option(prompt='Password', confirmation_prompt=True, help='The password for the user.')
def provision_user(username, password):
    """Provisions a new trusted human user out-of-band."""
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        click.echo(f"Error: User '{username}' already exists.", err=True)
        return

    user = User(username=username)
    user.set_password(password)

    db.session.add(user)
    db.session.commit()
    click.echo(f"Success: User '{username}' provisioned securely.")
