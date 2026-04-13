import os
from sqlalchemy import func
from flask import current_app
from .models import db, Resource, Report

class QuotaExceededError(Exception):
    pass

def get_available_space() -> int:
    """Calculates available space strictly based on DB source of truth."""
    total_limit = current_app.config['STORAGE_LIMIT_BYTES'] # 350 MB

    # Coalesce to 0 if the tables are empty
    res_size = db.session.query(func.sum(Resource.file_size_bytes)).scalar() or 0
    rep_size = db.session.query(func.sum(Report.file_size_bytes)).scalar() or 0

    return total_limit - (res_size + rep_size)

def save_chunked_file(file_stream, destination_path: str) -> int:
    """
    Streams a file to disk in 8KB chunks.
    Immediately aborts, deletes the file, and raises an error if the quota is hit.
    """
    available_space = get_available_space()
    bytes_written = 0
    chunk_size = 8192 # 8KB

    try:
        with open(destination_path, 'wb') as f:
            while True:
                chunk = file_stream.read(chunk_size)
                if not chunk:
                    break # EOF

                bytes_written += len(chunk)

                # The kill-switch
                if bytes_written > available_space:
                    f.close()
                    os.remove(destination_path)
                    raise QuotaExceededError("Storage limit of 350 MB exceeded.")

                f.write(chunk)

        return bytes_written

    except Exception as e:
        # Failsafe cleanup in case of IOError or other interruption
        if os.path.exists(destination_path):
            os.remove(destination_path)
        raise e
