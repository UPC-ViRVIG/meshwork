# gui/style_manager.py
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject
from config import get_config

class StyleManager(QObject):
    def __init__(self):
        super().__init__()
        self.config = get_config()
        self.current_theme = self.config.get("gui", "theme", "dark")

    def apply_theme(self, app: QApplication):
        """Apply theme to the entire application"""
        if self.current_theme == "dark":
            app.setStyleSheet(self.get_dark_theme())
        else:
            app.setStyleSheet(self.get_light_theme())

    def get_dark_theme(self):
        return """
        QMainWindow {
            background-color: #2a2a2a;
            color: #ffffff;
        }
        QWidget {
            background-color: #2a2a2a;
            color: #ffffff;
        }
        QPushButton {
            background-color: #3a3a3a;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 8px 16px;
            color: #ffffff;
        }
        QPushButton:hover {
            background-color: #4a4a4a;
        }
        QPushButton:pressed {
            background-color: #1a1a1a;
        }
        QPushButton:disabled {
            background-color: #333333;
            color: #888888;
        }
        QMenuBar {
            background-color: #2a2a2a;
            color: #ffffff;
            border-bottom: 1px solid #555555;
        }
        QMenuBar::item {
            background-color: transparent;
            padding: 4px 8px;
        }
        QMenuBar::item:selected {
            background-color: #3a3a3a;
        }
        QMenu {
            background-color: #2a2a2a;
            border: 1px solid #555555;
            color: #ffffff;
        }
        QMenu::item {
            padding: 4px 20px;
        }
        QMenu::item:selected {
            background-color: #3a3a3a;
        }
        QToolBar {
            background-color: #2a2a2a;
            border: 1px solid #555555;
            spacing: 2px;
        }
        QDockWidget {
            background-color: #2a2a2a;
            color: #ffffff;
            titlebar-close-icon: none;
            titlebar-normal-icon: none;
        }
        QDockWidget::title {
            background-color: #3a3a3a;
            padding-left: 5px;
        }
        QTabWidget::pane {
            border: 1px solid #555555;
            background-color: #2a2a2a;
        }
        QTabBar::tab {
            background-color: #3a3a3a;
            color: #ffffff;
            padding: 6px 12px;
            margin: 0 1px;
        }
        QTabBar::tab:selected {
            background-color: #4a4a4a;
        }
        QTabBar::tab:hover {
            background-color: #555555;
        }
        QComboBox {
            background-color: #3a3a3a;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 4px;
            color: #ffffff;
        }
        QComboBox:disabled {
            background-color: #2a2a2a;
            border: 1px solid #333333;
            color: #888888;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox::drop-down:disabled {
            border: none;
        }
        QComboBox::down-arrow {
            width: 12px;
            height: 12px;
        }
        QComboBox::down-arrow:disabled {
            width: 12px;
            height: 12px;
        }
        QCheckBox {
            color: #ffffff;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            background-color: #222222;
            border: 1px solid #aaaaaa;
            border-radius: 3px;
        }
        QCheckBox::indicator:checked {
            background-color: #4a90e2;
            border: 1px solid #aaaaaa;
        }
        QLineEdit, QSpinBox, QDoubleSpinBox {
            background-color: #3a3a3a;
            color: #ffffff;
            border: 1px solid #555555;
            border-radius: 2px;
            padding: 4px;
        }
        QTextEdit, QPlainTextEdit {
            background-color: #1e1e1e;
            color: #ffffff;
            border: 1px solid #555555;
        }
        QScrollBar:vertical {
            background-color: #2a2a2a;
            width: 15px;
            border: none;
        }
        QScrollBar::handle:vertical {
            background-color: #555555;
            min-height: 20px;
            border-radius: 7px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #666666;
        }
        QGroupBox {
            border: 1px solid #555555;
            border-radius: 4px;
            margin-top: 6px;
            color: #ffffff;
            font-weight: bold;
            padding-top: 10px;
        }
        QGroupBox::title {
            color: #ffffff;
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px;
        }
        QStatusBar {
            background-color: #2a2a2a;
            color: #ffffff;
            border-top: 1px solid #555555;
        }
        """

    def get_light_theme(self):
        return """
        QMainWindow {
            background-color: #f0f0f0;
            color: #000000;
        }
        QWidget {
            background-color: #f0f0f0;
            color: #000000;
        }
        QPushButton {
            background-color: #ffffff;
            border: 1px solid #cccccc;
            border-radius: 4px;
            padding: 8px 16px;
            color: #000000;
        }
        QPushButton:hover {
            background-color: #e6e6e6;
        }
        QPushButton:pressed {
            background-color: #d9d9d9;
        }
        QPushButton:disabled {
            background-color: #f0f0f0;
            color: #cccccc;
        }
        QComboBox {
            background-color: #ffffff;
            border: 1px solid #cccccc;
            border-radius: 4px;
            padding: 4px;
            color: #000000;
        }
        QComboBox:disabled {
            background-color: #f0f0f0;
            border: 1px solid #dddddd;
            color: #cccccc;
        }
        """

    def get_console_style(self):
        """Style for console/log displays"""
        if self.current_theme == "dark":
            return """
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 9pt;
            }
            """
        else:
            return """
            QTextEdit {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #cccccc;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 9pt;
            }
            """

    def get_script_editor_style(self):
        """Style for script editor"""
        if self.current_theme == "dark":
            return """
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555555;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
                line-height: 1.2;
            }
            """
        else:
            return """
            QPlainTextEdit {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #cccccc;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
                line-height: 1.2;
            }
            """

_style_manager = None

def get_style_manager():
    global _style_manager
    if _style_manager is None:
        _style_manager = StyleManager()
    return _style_manager