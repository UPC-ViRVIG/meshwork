# core/utils.py
import os
import tempfile
import shutil
import time
from typing import Any, Dict, Optional, Tuple, List
from pathlib import Path

def format_bytes(byte_count: int) -> str:
    """Format byte count in human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if byte_count < 1024:
            return f"{byte_count:.1f}{unit}"
        byte_count /= 1024
    return f"{byte_count:.1f}TB"

def format_duration(seconds: float) -> str:
    """Format duration in human readable format."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.1f}s"

def validate_file_path(file_path: str) -> bool:
    """Validate file path."""
    try:
        path = Path(file_path)
        return path.exists()
    except:
        return False

def check_file_read_permission(file_path: str) -> bool:
    """Check if file has read permission."""
    if not os.path.exists(file_path):
        return False
    return os.access(file_path, os.R_OK)

def check_file_write_permission(file_path: str) -> bool:
    """Check if file has write permission."""
    if os.path.exists(file_path):
        return os.access(file_path, os.W_OK)
    else:
        parent_dir = Path(file_path).parent
        return parent_dir.exists() and os.access(parent_dir, os.W_OK)

def check_directory_write_permission(dir_path: str) -> bool:
    """Check if directory has write permission."""
    return os.path.exists(dir_path) and os.access(dir_path, os.W_OK)

def get_system_temp_session_dir(session_id: str = None) -> str:
    """Get system temporary directory for session."""
    if session_id is None:
        session_id = f"{int(time.time())}"

    temp_base = tempfile.gettempdir()
    session_dir = os.path.join(temp_base, f"meshwork_session_{session_id}")
    return session_dir

def ensure_directory_exists(dir_path: str) -> bool:
    """Ensure directory exists, create if necessary."""
    try:
        os.makedirs(dir_path, exist_ok=True)
        return True
    except OSError:
        return False
