# gui/project_state.py
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import QObject, Signal
from typing import Optional, Dict, Any
import os
from pathlib import Path
from logger import get_logger
from core.utils import (
    check_file_read_permission,
    check_file_write_permission,
    check_directory_write_permission
)


class ProjectState(QObject):
    title_changed = Signal(str)

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()

        self.project_path: Optional[str] = None
        self.tmp_project_path: Optional[str] = None
        self.dirty: bool = False
        self.lock: bool = False

        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('project.done_new', self.done_new_project, 'ProjectState')
            self.signal_router.subscribe('project.done_open', self.done_open_project, 'ProjectState')
            self.signal_router.subscribe('project.done_save', self.done_save_project, 'ProjectState')
            self.signal_router.subscribe('project.done_import', self.done_import_file, 'ProjectState')
            self.signal_router.subscribe('project.done_export', self.done_export_file, 'ProjectState')

    def try_lock(self) -> bool:
        if self.lock:
            return False
        self.lock = True
        return True

    def unlock(self):
        self.lock = False

    def has_unsaved_changes(self) -> bool:
        return self.dirty

    def get_current_project_name(self) -> str:
        if not self.project_path:
            return "Untitled"
        return self._extract_project_name_from_path(self.project_path)

    def set_dirty(self, dirty: bool):
        self.dirty = dirty
        self._update_window_title()

    def new_project(self):
        if not self.try_lock():
            return

        self.tmp_project_path = None
        if self.signal_router:
            self.signal_router.emit('project.do_new', {})

    def open_project(self):
        if not self.try_lock():
            return

        file_path = self._show_permission_error_and_retry("open")
        if not file_path:
            self.unlock()
            return

        self.tmp_project_path = file_path
        if self.signal_router:
            self.signal_router.emit('project.do_open', {'file_path': file_path})

    def save_project(self):
        if not self.try_lock():
            return

        if not self.project_path:
            file_path = self._show_permission_error_and_retry("save_as")
            if not file_path:
                self.unlock()
                return
            self.tmp_project_path = file_path
        else:
            if not check_file_write_permission(self.project_path):
                self.logger.error(f"No write permission for {self.project_path}")
                self.unlock()
                return
            self.tmp_project_path = self.project_path

        if self.signal_router:
            self.signal_router.emit('project.do_save', {'file_path': self.tmp_project_path})

    def save_project_as(self):
        if not self.try_lock():
            return

        file_path = self._show_permission_error_and_retry("save_as")
        if not file_path:
            self.unlock()
            return

        self.tmp_project_path = file_path
        if self.signal_router:
            self.signal_router.emit('project.do_save', {'file_path': file_path})

    def import_file(self):
        if not self.try_lock():
            return

        file_path = self._show_permission_error_and_retry("import")
        if not file_path:
            self.unlock()
            return

        if self.signal_router:
            self.signal_router.emit('project.do_import', {'file_path': file_path})

    def export_file(self):
        if not self.try_lock():
            return

        file_path = self._show_permission_error_and_retry("export")
        if not file_path:
            self.unlock()
            return

        if self.signal_router:
            self.signal_router.emit('project.do_export', {'file_path': file_path})

    def _show_permission_error_and_retry(self, operation_type: str, initial_path: str = None) -> Optional[str]:
        while True:
            file_path = self._show_file_dialog(operation_type, initial_path=initial_path)
            if not file_path:
                return None

            if operation_type == "open":
                if check_file_read_permission(file_path):
                    return file_path
            elif operation_type in ["save_as"]:
                if check_file_write_permission(file_path):
                    return file_path
            elif operation_type == "import":
                if check_file_read_permission(file_path):
                    return file_path
            elif operation_type == "export":
                if check_file_write_permission(file_path):
                    return file_path
            else:
                return file_path

    def _ensure_file_extension(self, file_path: str, default_ext: str) -> str:
        path_obj = Path(file_path)
        if not path_obj.suffix:
            return str(path_obj.with_suffix(default_ext))
        return file_path

    def _extract_project_name_from_path(self, file_path: str) -> str:
        if not file_path:
            return "Untitled"
        return Path(file_path).stem

    def _show_file_dialog(self, operation_type: str, **kwargs) -> Optional[str]:
        initial_path = kwargs.get("initial_path", "")

        if operation_type == "open":
            file_path, _ = QFileDialog.getOpenFileName(
                None, "Open Project", initial_path,
                "Blender Files (*.blend);;All Files (*)"
            )
            return file_path if file_path else None
        elif operation_type == "save_as":
            file_path, _ = QFileDialog.getSaveFileName(
                None, "Save Project As", initial_path,
                "Blender Files (*.blend);;All Files (*)"
            )
            if file_path:
                return self._ensure_file_extension(file_path, ".blend")
            return None
        elif operation_type == "import":
            file_path, _ = QFileDialog.getOpenFileName(
                None, "Import File", initial_path,
                "Mesh Files (*.obj *.ply *.stl);;OBJ Files (*.obj);;PLY Files (*.ply);;STL Files (*.stl);;All Files (*)"
            )
            return file_path if file_path else None
        elif operation_type == "export":
            file_path, selected_filter = QFileDialog.getSaveFileName(
                None, "Export Selected Objects", initial_path,
                "OBJ Files (*.obj);;PLY Files (*.ply);;STL Files (*.stl)"
            )
            if not file_path:
                return None

            file_ext = ".obj"
            if "*.obj)" in selected_filter:
                file_ext = ".obj"
            elif "*.ply)" in selected_filter:
                file_ext = ".ply"
            elif "*.stl)" in selected_filter:
                file_ext = ".stl"

            return self._ensure_file_extension(file_path, file_ext)

        return None

    def done_new_project(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.project_path = None
            self.dirty = True
            self.logger.info("New project created successfully")
        else:
            self.logger.error(f"Failed to create new project: {error}")

        self.tmp_project_path = None
        self.unlock()
        self._update_window_title()

    def done_open_project(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.project_path = self.tmp_project_path
            self.dirty = False
            self.logger.info(f"Project opened: {self.get_current_project_name()}")
        else:
            self.logger.error(f"Failed to open project: {error}")

        self.tmp_project_path = None
        self.unlock()
        self._update_window_title()

    def done_save_project(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.project_path = self.tmp_project_path
            self.dirty = False
            self.logger.info(f"Project saved: {self.get_current_project_name()}")
        else:
            self.logger.error(f"Failed to save project: {error}")

        self.tmp_project_path = None
        self.unlock()
        self._update_window_title()

    def done_import_file(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.logger.info("File imported successfully")
        else:
            self.logger.error(f"Failed to import file: {error}")

        self.unlock()

    def done_export_file(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.logger.info("File exported successfully")
        else:
            self.logger.error(f"Failed to export file: {error}")

        self.unlock()

    def _update_window_title(self):
        project_name = self.get_current_project_name()
        title = self._format_window_title(project_name, self.dirty)
        self.title_changed.emit(title)

    def _format_window_title(self, project_name: str, is_dirty: bool) -> str:
        if is_dirty:
            return f"{project_name}* - MeshWork"
        else:
            return f"{project_name} - MeshWork"

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ProjectState')