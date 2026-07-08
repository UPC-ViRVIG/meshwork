# gui/win_recon.py
import os
import time
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QLabel, QPushButton, QTextEdit, QComboBox, QCheckBox, QWidget,
    QFileDialog, QMessageBox, QGroupBox, QFormLayout, QFrame,
    QScrollArea, QListWidget, QListWidgetItem, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer, QRunnable, QThreadPool, QSettings
from PySide6.QtGui import QFont, QTextCursor, QKeySequence, QPixmap, QKeyEvent
from config import get_config
from logger import get_logger
from gui.image_manager import ImagePreviewPanel
from core.utils import (
    get_system_temp_session_dir,
    ensure_directory_exists,
    check_file_read_permission,
    check_directory_write_permission
)

class ReconConfig:
    def __init__(self):
        self.config = get_config()
        self._load_from_config()

    def _load_from_config(self):
        recon_config = self.config.get("reconstruction", default={})

        self.tool = recon_config.get('default_tool', 'colmap')
        self.quality_level = recon_config.get('default_quality', 'fast')
        self.output_type = recon_config.get('default_output_type', 'point_cloud')

    def get_available_quality_levels(self) -> List[str]:
        recon_config = self.config.get("reconstruction", default={})
        quality_levels = recon_config.get("quality_levels", [])

        if not quality_levels or not isinstance(quality_levels, list):
            return ['Fast']

        return [level.title() for level in quality_levels]

    def get_default_quality_display_name(self) -> str:
        return self.quality_level.title()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'tool': self.tool,
            'quality_level': self.quality_level,
            'output_type': self.output_type
        }

    def from_dict(self, data: Dict[str, Any]):
        self.tool = data.get('tool', 'colmap')
        self.quality_level = data.get('quality_level', 'fast')
        self.output_type = data.get('output_type', 'point_cloud')

    def validate(self) -> Tuple[bool, str]:
        valid_tools = ['colmap', 'alicevision']
        if self.tool not in valid_tools:
            return False, f"Invalid tool: {self.tool}"

        recon_config = self.config.get("reconstruction", default={})
        tool_config = recon_config.get(self.tool, {})
        if not tool_config:
            return False, f"Missing configuration for tool: {self.tool}"

        quality_levels = tool_config.get("quality_levels", {})
        if self.quality_level not in quality_levels:
            return False, f"Invalid quality level: {self.quality_level}"

        return True, ""

    def update_tool(self, tool: str):
        self.tool = tool.lower()

    def update_quality_level(self, quality: str):
        quality_map = {
            'Fast': 'fast',
            'Balanced': 'balanced',
            'Quality': 'quality'
        }
        self.quality_level = quality_map.get(quality, 'balanced')

    def update_output_type(self, output_type: str):
        type_map = {
            'Point Cloud': 'point_cloud',
            'Dense Mesh': 'dense_mesh'
        }
        self.output_type = type_map.get(output_type, 'point_cloud')

class OutputArea(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_lines = 1000
        self.current_lines = 0
        self.color_scheme = {}
        self._setup_ui()
        self._setup_colors()

    def _setup_ui(self):
        self.setReadOnly(True)
        font = QFont("Consolas", 9)
        font.setFamily("monospace")
        self.setFont(font)
        self.setPlaceholderText("Reconstruction output will appear here...")

    def _setup_colors(self):
        self.color_scheme = {
            'local_info': '#ffffff',
            'local_success': '#4ade80',
            'local_warning': '#fbbf24',
            'local_error': '#ef4444',
            'remote_stdout': '#60a5fa',
            'remote_stderr': '#fb7185'
        }

    def append_message(self, text: str, msg_type: str):
        if not text.strip():
            return

        color = self.color_scheme.get(msg_type, '#ffffff')
        formatted_text = self._format_message(text.rstrip(), color)

        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(formatted_text + "<br>")

        self.current_lines += 1
        if self.current_lines > self.max_lines:
            self._trim_buffer()

        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def append_local_info(self, text: str):
        self.append_message(text, 'local_info')

    def append_local_error(self, text: str):
        self.append_message(text, 'local_error')

    def append_local_success(self, text: str):
        self.append_message(text, 'local_success')

    def append_remote_stdout(self, text: str):
        self.append_message(text, 'remote_stdout')

    def append_remote_stderr(self, text: str):
        self.append_message(text, 'remote_stderr')

    def _format_message(self, text: str, color: str) -> str:
        escaped_text = (text.replace('&', '&amp;')
                           .replace('<', '&lt;')
                           .replace('>', '&gt;')
                           .replace('"', '&quot;')
                           .replace("'", '&#x27;'))
        return f'<span style="color: {color};">{escaped_text}</span>'

    def _trim_buffer(self):
        lines_to_remove = int(self.max_lines * 0.2)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.Start)

        for _ in range(lines_to_remove):
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.movePosition(QTextCursor.Down)

        cursor.removeSelectedText()
        self.current_lines -= lines_to_remove

    def clear_output(self):
        self.clear()
        self.current_lines = 0

class ReconWindow(QDialog):
    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.config = get_config()
        self.logger = get_logger()
        self.settings = QSettings('meshwork', 'recon_window')
        self.recon_config = ReconConfig()

        self.DEFAULT_MAIN_SPLITTER_SIZES = [300, 700]
        self.DEFAULT_VERTICAL_SPLITTER_SIZES = [600, 150]

        self.is_running = False
        self.project_dir = ""
        self.result_dir_name = ""
        self.input_folder = ""

        self._setup_ui()
        self._setup_connections()
        self._setup_signals()
        self._restore_state()

    def _setup_ui(self):
        self.setWindowTitle("3D Reconstruction")
        self.setModal(False)
        self.setWindowFlags(Qt.Window)

        window_config = self.config.get("gui", "window", {})
        default_width = window_config.get("width", 1280)
        default_height = window_config.get("height", 720)
        self.resize(default_width, default_height)

        if window_config.get("maximized", False):
            self.showMaximized()

        layout = QVBoxLayout(self)

        main_splitter = QSplitter(Qt.Horizontal)

        config_widget = self._create_config_widget()
        main_splitter.addWidget(config_widget)

        self.preview_panel = ImagePreviewPanel(self.signal_router)
        main_splitter.addWidget(self.preview_panel)

        main_splitter.setSizes(self.DEFAULT_MAIN_SPLITTER_SIZES)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        self.main_splitter = main_splitter

        vertical_splitter = QSplitter(Qt.Vertical)
        vertical_splitter.addWidget(main_splitter)

        self.output_area = OutputArea()
        self.output_area.setMinimumHeight(100)
        self.output_area.setMaximumHeight(1000)
        vertical_splitter.addWidget(self.output_area)

        vertical_splitter.setSizes(self.DEFAULT_VERTICAL_SPLITTER_SIZES)
        vertical_splitter.setCollapsible(0, False)
        vertical_splitter.setCollapsible(1, False)
        self.vertical_splitter = vertical_splitter

        layout.addWidget(vertical_splitter)

        button_layout = self._create_button_layout()
        layout.addLayout(button_layout)

    def _create_config_widget(self) -> QWidget:
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)

        title = QLabel("Configuration")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(title)

        input_group = QGroupBox("Input")
        input_layout = QVBoxLayout(input_group)

        folder_label = QLabel("Image Folder:")
        input_layout.addWidget(folder_label)

        folder_btn_layout = QHBoxLayout()
        self.folder_display = QLabel("No folder selected")
        self.folder_display.setStyleSheet("padding: 4px; border: 1px solid #555; background-color: #333;")
        folder_btn_layout.addWidget(self.folder_display)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._select_image_folder)
        folder_btn_layout.addWidget(browse_btn)

        input_layout.addLayout(folder_btn_layout)
        layout.addWidget(input_group)

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        output_label = QLabel("Output Folder:")
        output_layout.addWidget(output_label)

        output_btn_layout = QHBoxLayout()
        self.output_display = QLabel("No folder selected")
        self.output_display.setStyleSheet("padding: 4px; border: 1px solid #555; background-color: #333;")
        output_btn_layout.addWidget(self.output_display)

        output_browse_btn = QPushButton("Browse...")
        output_browse_btn.setFixedWidth(90)
        output_browse_btn.clicked.connect(self._select_output_folder)
        output_btn_layout.addWidget(output_browse_btn)

        output_layout.addLayout(output_btn_layout)
        layout.addWidget(output_group)

        tool_group = QGroupBox("Settings")
        tool_layout = QVBoxLayout(tool_group)

        tool_selection_layout = QHBoxLayout()
        tool_label = QLabel("Tool:")
        tool_selection_layout.addWidget(tool_label)

        self.tool_combo = QComboBox()
        self.tool_combo.addItems(["COLMAP", "AliceVision"])
        tool_mapping = {"colmap": "COLMAP", "alicevision": "AliceVision"}
        default_tool_display = tool_mapping.get(self.recon_config.tool, "COLMAP")
        self.tool_combo.setCurrentText(default_tool_display)
        self.tool_combo.currentTextChanged.connect(self._on_config_changed)
        tool_selection_layout.addWidget(self.tool_combo)

        tool_layout.addLayout(tool_selection_layout)

        quality_layout = QHBoxLayout()
        quality_label = QLabel("Quality:")
        quality_layout.addWidget(quality_label)

        self.quality_combo = QComboBox()
        available_qualities = self.recon_config.get_available_quality_levels()
        self.quality_combo.addItems(available_qualities)
        default_quality = self.recon_config.get_default_quality_display_name()
        if default_quality in available_qualities:
            self.quality_combo.setCurrentText(default_quality)
        self.quality_combo.currentTextChanged.connect(self._on_config_changed)
        quality_layout.addWidget(self.quality_combo)

        tool_layout.addLayout(quality_layout)

        output_type_layout = QHBoxLayout()
        output_type_label = QLabel("Output:")
        output_type_layout.addWidget(output_type_label)

        self.output_type_combo = QComboBox()
        self.output_type_combo.addItems(["Point Cloud", "Dense Mesh"])
        self.output_type_combo.setCurrentText("Point Cloud")
        self.output_type_combo.currentTextChanged.connect(self._on_config_changed)
        output_type_layout.addWidget(self.output_type_combo)

        tool_layout.addLayout(output_type_layout)

        layout.addWidget(tool_group)
        layout.addStretch()

        return config_widget

    def _create_button_layout(self) -> QHBoxLayout:
        button_layout = QHBoxLayout()

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start_reconstruction)
        self.start_btn.setEnabled(False)
        button_layout.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel_reconstruction)
        self.cancel_btn.setEnabled(False)
        button_layout.addWidget(self.cancel_btn)

        self.import_btn = QPushButton("Import")
        self.import_btn.clicked.connect(self._import_results)
        self.import_btn.setEnabled(False)
        button_layout.addWidget(self.import_btn)

        self.delete_cache_btn = QPushButton("Delete Cache")
        self.delete_cache_btn.clicked.connect(self._delete_cache)
        self.delete_cache_btn.setEnabled(False)
        button_layout.addWidget(self.delete_cache_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset_reconstruction)
        self.reset_btn.setEnabled(False)
        button_layout.addWidget(self.reset_btn)

        button_layout.addStretch()

        clear_output_btn = QPushButton("Clear Output")
        clear_output_btn.clicked.connect(self.output_area.clear_output)
        button_layout.addWidget(clear_output_btn)

        return button_layout

    def _setup_connections(self):
        pass

    def _setup_signals(self):
        if self.signal_router:
            self.signal_router.subscribe('recon.progress', self._on_recon_progress, 'ReconWindow')
            self.signal_router.subscribe('recon.completed', self._on_recon_completed, 'ReconWindow')
            self.signal_router.subscribe('recon.image_all_converted', self._on_phase_completed, 'ReconWindow')
            self.signal_router.subscribe('recon.selection_changed', self._on_selection_changed, 'ReconWindow')
            self.signal_router.subscribe('recon.import_ready', self._on_import_ready, 'ReconWindow')
            self.signal_router.subscribe('view.reset_layout', self.on_reset_layout_signal, 'ReconWindow')

    def _restore_state(self):
        if self.settings.contains("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))

        if self.settings.contains("mainSplitterSizes"):
            sizes = self.settings.value("mainSplitterSizes")
            if sizes:
                self.main_splitter.setSizes([int(s) for s in sizes])

        if self.settings.contains("verticalSplitterSizes"):
            sizes = self.settings.value("verticalSplitterSizes")
            if sizes:
                self.vertical_splitter.setSizes([int(s) for s in sizes])

    def _save_state(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("mainSplitterSizes", self.main_splitter.sizes())
        self.settings.setValue("verticalSplitterSizes", self.vertical_splitter.sizes())

    def reset_to_default_layout(self):
        self.logger.info("Resetting ReconWindow layout to defaults")

        if self.isVisible():
            window_config = self.config.get("gui", "window", {})
            default_width = window_config.get("width", 1280)
            default_height = window_config.get("height", 720)
            default_maximized = window_config.get("maximized", False)

            if default_maximized:
                self.showMaximized()
            else:
                self.showNormal()
                self.resize(default_width, default_height)

        self.main_splitter.setSizes(self.DEFAULT_MAIN_SPLITTER_SIZES)
        self.vertical_splitter.setSizes(self.DEFAULT_VERTICAL_SPLITTER_SIZES)

        self.logger.info("ReconWindow layout reset completed")

    def on_reset_layout_signal(self, data):
        self.reset_to_default_layout()

    def _on_config_changed(self):
        tool_mapping = {"COLMAP": "colmap", "AliceVision": "alicevision"}
        selected_tool = self.tool_combo.currentText()
        if selected_tool in tool_mapping:
            self.recon_config.update_tool(tool_mapping[selected_tool])

        self.recon_config.update_quality_level(self.quality_combo.currentText())
        self.recon_config.update_output_type(self.output_type_combo.currentText())
        self._update_button_states()

    def _select_image_folder(self):
        folder = self._show_permission_error_and_retry("image_folder")
        if not folder:
            return

        self.input_folder = folder
        self.folder_display.setText(os.path.basename(folder))

        if self.signal_router:
            self.signal_router.emit('recon.folder_changed', {
                'folder_type': 'input',
                'path': folder
            })

        self.output_area.append_local_info(f"Selected image folder: {folder}")
        self._update_button_states()

    def _select_output_folder(self):
        folder = self._show_permission_error_and_retry("output_folder")
        if not folder:
            return

        self.project_dir = folder
        self.output_display.setText(os.path.basename(folder))

        if self.signal_router:
            self.signal_router.emit('recon.folder_changed', {
                'folder_type': 'output',
                'path': folder
            })

        self.output_area.append_local_info(f"Selected output folder: {folder}")
        self._update_button_states()

    def _show_permission_error_and_retry(self, operation_type: str) -> Optional[str]:
        while True:
            if operation_type == "image_folder":
                folder = QFileDialog.getExistingDirectory(self, "Select Images Folder")
                if not folder:
                    return None
                if os.access(folder, os.R_OK):
                    return folder
            elif operation_type == "output_folder":
                folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
                if not folder:
                    return None
                if check_directory_write_permission(folder):
                    return folder

            QMessageBox.warning(self, "Permission Error",
                               f"Insufficient permissions for selected folder. Please choose another folder.")

    def _on_recon_progress(self, data: Dict[str, Any]):
        stream_type = data.get('stream_type', 'stdout')
        message = data.get('message', '')

        if stream_type == 'stdout':
            self.output_area.append_remote_stdout(message)
        elif stream_type == 'stderr':
            self.output_area.append_remote_stderr(message)

    def _on_phase_completed(self, data: Dict[str, Any]):
        phase = data.get('phase', '')
        success_count = data.get('success_count', 0)
        total_count = data.get('total_count', 0)

        if phase == 'thumbnail':
            self.output_area.append_local_success(f"Thumbnail generation completed: {success_count}/{total_count}")
        elif phase == 'converted':
            self.output_area.append_local_success(f"Image conversion completed: {success_count}/{total_count}")

        self._update_button_states()

    def _on_selection_changed(self, data: Dict[str, Any]):
        self._update_button_states()

    def _on_import_ready(self, data: Dict[str, Any]):
        self.result_dir_name = data.get('result_dir_name', '')
        available_files = data.get('available_files', {})

        self.import_btn.setEnabled(True)
        self.output_area.append_local_success("Results ready for import")

        file_count = len(available_files)
        if file_count > 0:
            self.output_area.append_local_info(f"Found {file_count} result files")

    def _update_button_states(self):
        output_folder_selected = bool(self.project_dir)
        self.delete_cache_btn.setEnabled(not self.is_running and output_folder_selected)
        self.tool_combo.setEnabled(not self.is_running)
        self.reset_btn.setEnabled(not self.is_running and output_folder_selected)

        if self.is_running:
            self.start_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            return

        folders_selected = bool(self.project_dir) and self.folder_display.text() != "No folder selected"
        has_selection = len(self.preview_panel.get_selected_images()) > 0
        images_ready = (self.preview_panel.thumbnail_completed and
                       self.preview_panel.converted_completed)

        can_start = folders_selected and has_selection and images_ready
        self.start_btn.setEnabled(can_start)
        self.cancel_btn.setEnabled(False)

    def _start_reconstruction(self):
        if not self.project_dir:
            self.show_error_message("Please select output folder")
            return

        selected_images = self.preview_panel.get_selected_images()
        if not selected_images:
            self.show_error_message("Please select at least one image")
            return

        selected_basenames = [os.path.splitext(os.path.basename(img))[0] for img in selected_images]

        self.output_area.clear_output()
        self.output_area.append_local_info(f"Starting reconstruction with {len(selected_images)} images")
        self.output_area.append_local_info(f"Selected files: {', '.join(selected_basenames[:5])}")
        if len(selected_basenames) > 5:
            self.output_area.append_local_info(f"... and {len(selected_basenames) - 5} more")

        if self.signal_router:
            self.signal_router.emit('recon.start', {
                'tool': self.recon_config.tool,
                'project_dir': self.project_dir,
                'selected_images': selected_basenames,
                'config': self.recon_config.to_dict()
            })

        self.is_running = True
        self.import_btn.setEnabled(False)
        self._update_button_states()

        self.output_area.append_local_info(f"Reconstruction started with {self.recon_config.tool}")

    def _cancel_reconstruction(self):
        if self.signal_router:
            self.signal_router.emit('recon.cancel', {})

        self.is_running = False
        self._update_button_states()

        self.output_area.append_local_info("Reconstruction cancelled")

    def _delete_cache(self):
        if self.signal_router:
            self.signal_router.emit('recon.delete_cache', {
                'project_dir': self.project_dir
            })

        self.output_area.append_local_info("Delete cache requested")

    def _reset_reconstruction(self):
        if self.signal_router:
            self.signal_router.emit('recon.reset', {})

        self.output_area.append_local_info("Reconstruction reset")
        self._update_button_states()

    def _on_recon_completed(self, data: Dict[str, Any]):
        success = data.get('success', False)
        error_message = data.get('error_message', '')
        tool = data.get('tool', '')
        duration = data.get('duration', 0.0)

        self.is_running = False

        if success:
            self.output_area.append_local_success(f"Reconstruction completed successfully in {duration:.1f}s")
        else:
            self.output_area.append_local_error(f"Reconstruction failed: {error_message}")

        self._update_button_states()

    def _get_target_import_file(self) -> Optional[str]:
        if not self.result_dir_name or not self.project_dir:
            return None

        result_path = os.path.join(self.project_dir, self.result_dir_name, "result")

        if self.recon_config.output_type == 'dense_mesh':
            mesh_files = ['mesh.obj', 'mesh.ply', 'scene_mesh.ply', 'textured_mesh.obj']
            for filename in mesh_files:
                file_path = os.path.join(result_path, filename)
                if os.path.exists(file_path):
                    return file_path

        point_cloud_files = ['dense_points.ply', 'points.ply', 'sparse_points.ply']
        for filename in point_cloud_files:
            file_path = os.path.join(result_path, filename)
            if os.path.exists(file_path):
                return file_path

        return None

    def _import_results(self):
        target_file = self._get_target_import_file()

        if not target_file:
            self.show_error_message("No suitable result files found for import")
            return

        if self.signal_router:
            self.signal_router.emit('project.do_import', {
                'file_path': target_file
            })

        file_name = os.path.basename(target_file)
        self.output_area.append_local_info(f"Importing {file_name}")

    def show_error_message(self, message: str):
        self.output_area.append_local_error(message)

    def show_success_message(self, message: str):
        self.output_area.append_local_success(message)

    def real_close(self):
        self._save_state()

        if self.preview_panel:
            self.preview_panel.cleanup()

        if self.signal_router:
            self.signal_router.unsubscribe_all('ReconWindow')

    def closeEvent(self, event):
        if self.is_running:
            self._cancel_reconstruction()

        self._save_state()
        self.hide()
        event.ignore()