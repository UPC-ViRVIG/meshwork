# gui/main.py
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QSplitter, QStatusBar, QMessageBox)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QKeySequence
import sys
import os
from typing import Optional
from logger import get_logger
from config import get_config
from core.signal_router import SignalRouter
from core.worker_thread import WorkerThread
from gui.style_manager import get_style_manager
from gui.menu import MenuManager
from gui.dock_manager import DockManager
from gui.view import View
from gui.script import ScriptArea
from gui.project_state import ProjectState

import faulthandler
import os

def setup_crash_debugging():
    faulthandler.enable()
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')
    os.environ.setdefault('QT_X11_NO_MITSHM', '1')
setup_crash_debugging()

class MainApplication(QMainWindow):

    def __init__(self):
        super().__init__(parent=None)

        self.logger = get_logger()
        self.config = get_config()
        self.settings = QSettings('meshwork', 'app')

        self.signal_router = None
        self.worker_thread = None
        self.project_state = None

        self.style_manager = get_style_manager()
        self.menu_manager = None
        self.dock_manager = None
        self.view = None
        self.script_area = None

        self.main_splitter = None
        self.viewport_container = None

        self._setup_core_architecture()
        self._setup_ui()
        self._setup_connections()
        self._restore_state()
        self._start_worker_thread()

        self.logger.info("MainApplication initialized successfully")

    def _setup_core_architecture(self):
        self.signal_router = SignalRouter(self)
        self.worker_thread = WorkerThread(self.signal_router, self)
        self.project_state = ProjectState(self.signal_router, self)

    def _setup_ui(self):
        self.setWindowTitle("MeshWork - 3D Mesh Processing & Reconstruction")

        window_config = self.config.get("gui", "window", {})
        self.resize(window_config.get("width", 1280), window_config.get("height", 720))

        if window_config.get("maximized", False):
            self.showMaximized()

        self.menu_manager = MenuManager(self, self.signal_router, self)
        self.menu_manager.setup_menus()

        self._setup_toolbar()

        main_container = QWidget()
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(self.main_splitter)

        self.viewport_container = QMainWindow()
        self.viewport_container.setDockNestingEnabled(True)

        self.view = View(self.signal_router)
        self.viewport_container.setCentralWidget(self.view)

        self.main_splitter.addWidget(self.viewport_container)

        script_config = self.config.get("gui", "script", {})
        self.script_area = ScriptArea(self.signal_router)

        self.main_splitter.addWidget(self.script_area)

        script_height = script_config.get("height", 150)
        viewport_height = 600
        self.main_splitter.setSizes([viewport_height, script_height])

        self.setCentralWidget(main_container)

        self._setup_dock_panels(self.viewport_container)
        self._setup_status_bar()

    def _setup_toolbar(self):
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(True)
        toolbar.setFloatable(False)

        if self.menu_manager:
            recon_action = self.menu_manager.get_action("tools_reconstruction")
            if recon_action:
                toolbar.addAction(recon_action)

    def _setup_dock_panels(self, viewport_container):
        from gui.panel_tools import ToolsPanel
        from gui.panel_scene import ScenePanel
        from gui.panel_material import MaterialPanel
        from gui.panel_render import RenderPanel

        tools_panel = ToolsPanel(self.signal_router)
        scene_panel = ScenePanel(self.signal_router)
        material_panel = MaterialPanel()
        render_panel = RenderPanel()

        self.dock_manager = DockManager(viewport_container)

        self.dock_manager.add_dock("tools", "Tools", tools_panel, Qt.LeftDockWidgetArea)
        self.dock_manager.add_dock("scene", "Scene", scene_panel, Qt.RightDockWidgetArea)
        self.dock_manager.add_dock("material", "Material", material_panel, Qt.RightDockWidgetArea)
        self.dock_manager.add_dock("render", "Render", render_panel, Qt.RightDockWidgetArea)

        self.dock_manager.hide_dock("material")
        self.dock_manager.hide_dock("render")

        viewport_container.setDockOptions(
            QMainWindow.AllowNestedDocks |
            QMainWindow.AllowTabbedDocks
        )

    def _setup_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("MeshWork Ready")

    def _setup_connections(self):
        self.signal_router.subscribe('status.message', self.on_status_message, 'StatusBar')
        self.signal_router.subscribe('view.reset_layout', self.on_reset_layout_signal, 'MainWindow')
        self.signal_router.subscribe('scene.request_sync', self.on_scene_request_sync, 'MainApplication')
        self.project_state.title_changed.connect(self.setWindowTitle)

    def _start_worker_thread(self):
        if self.worker_thread:
            self.worker_thread.start()

    def _restore_state(self):
        if self.settings.contains("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        if self.settings.contains("windowState"):
            self.restoreState(self.settings.value("windowState"))

    def _save_state(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

    def on_scene_request_sync(self, data):
        self.project_state.set_dirty(True)

    def reset_to_default_layout(self):
        self.logger.info("Resetting GUI layout to defaults")

        self._reset_window_geometry()

        if self.dock_manager:
            self.dock_manager.reset_to_config_layout()

        self._reset_splitters()

        if self.view:
            self.view.reset_to_default_view_state()

        if self.script_area:
            self.script_area.reset_to_default(clear_content=False)

        self.logger.info("GUI layout reset completed")

    def _reset_window_geometry(self):
        window_config = self.config.get("gui", "window", {})
        width = window_config.get("width", 1280)
        height = window_config.get("height", 720)
        maximized = window_config.get("maximized", False)

        if maximized:
            self.showMaximized()
        else:
            self.showNormal()
            self.resize(width, height)

    def _reset_splitters(self):
        if self.main_splitter:
            script_config = self.config.get("gui", "script", {})
            script_height = script_config.get("height", 150)
            viewport_height = 600
            self.main_splitter.setSizes([viewport_height, script_height])

    def on_reset_layout_signal(self, data):
        self.reset_to_default_layout()

    def on_status_message(self, data):
        text = data.get('text', '')
        level = data.get('level', 'INFO')
        duration = data.get('duration', 3000)

        self.status_bar.showMessage(text, duration)

    def closeEvent(self, event):
        if self.project_state.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. What would you like to do?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )

            if reply == QMessageBox.Save:
                self.project_state.save_project()

            elif reply == QMessageBox.Cancel:
                event.ignore()
                return
        try:
            self._save_state()
            self.config.save()
            self.project_state.cleanup()
            if self.menu_manager and self.menu_manager.handler:
                self.menu_manager.handler.cleanup_recon_window()
            if self.script_area:
                self.script_area.cleanup()
            if self.view:
                self.view.cleanup()
            if self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.stop_thread()
            self.logger.info("Application closing gracefully")
            event.accept()
        except:
            pass

        os._exit(0)