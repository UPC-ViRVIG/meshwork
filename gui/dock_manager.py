# gui/dock_manager.py
from PySide6.QtWidgets import QMainWindow, QDockWidget, QWidget
from PySide6.QtCore import Qt
from typing import Dict, Optional
from logger import get_logger
from config import get_config

class DockManager:
    def __init__(self, main_window: QMainWindow):
        self.main_window = main_window
        self.logger = get_logger()
        self.config = get_config()
        self.docks: Dict[str, QDockWidget] = {}

    def add_dock(self, dock_id: str, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        """Add dock widget"""
        if dock_id in self.docks:
            return self.docks[dock_id]

        dock = QDockWidget(title, self.main_window)
        dock.setWidget(widget)
        dock.setObjectName(dock_id)

        self.main_window.addDockWidget(area, dock)
        self.docks[dock_id] = dock

        return dock

    def show_dock(self, dock_id: str) -> bool:
        """Show dock widget"""
        if dock_id in self.docks:
            self.docks[dock_id].show()
            return True
        return False

    def hide_dock(self, dock_id: str) -> bool:
        """Hide dock widget"""
        if dock_id in self.docks:
            self.docks[dock_id].hide()
            return True
        return False

    def is_dock_visible(self, dock_id: str) -> bool:
        """Check if dock is visible"""
        if dock_id in self.docks:
            return self.docks[dock_id].isVisible()
        return False

    def get_dock_names(self) -> list:
        """Get list of dock names"""
        return list(self.docks.keys())

    def reset_to_config_layout(self) -> bool:
        """Reset dock layout based on config"""
        self.logger.info("Resetting dock layout to config defaults")

        panels_config = self.config.get("gui", "panels", {})

        self._apply_dock_visibility(panels_config)

        self._apply_dock_positions(panels_config)

        self.logger.info("Dock layout reset completed")
        return True

    def _apply_dock_visibility(self, panels_config: Dict) -> None:
        """Apply visibility settings from config"""
        for dock_id, dock in self.docks.items():
            panel_config = panels_config.get(dock_id, {})
            visible = panel_config.get("visible", True)

            if visible:
                dock.show()
            else:
                dock.hide()

            self.logger.debug(f"Set {dock_id} visibility: {visible}")

    def _apply_dock_positions(self, panels_config: Dict) -> None:
        """Apply dock positions and sizes from config"""
        if "tools" in self.docks:
            self.main_window.addDockWidget(Qt.LeftDockWidgetArea, self.docks["tools"])

        if "scene" in self.docks:
            self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.docks["scene"])

        if "material" in self.docks:
            self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.docks["material"])
            if "scene" in self.docks:
                self.main_window.tabifyDockWidget(self.docks["scene"], self.docks["material"])

        if "render" in self.docks:
            self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.docks["render"])
            if "material" in self.docks:
                self.main_window.tabifyDockWidget(self.docks["material"], self.docks["render"])
            elif "scene" in self.docks:
                self.main_window.tabifyDockWidget(self.docks["scene"], self.docks["render"])

        if "scene" in self.docks:
            self.docks["scene"].raise_()

        self.logger.debug("Applied dock positions")

    def apply_layout(self, layout_name: str) -> bool:
        """Apply dock layout by name"""
        if layout_name == "default":
            self.show_dock("tools")
            self.show_dock("scene")
            self.hide_dock("material")
            self.hide_dock("render")
            return True
        return False