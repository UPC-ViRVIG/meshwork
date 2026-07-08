# gui/panel_render.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal
from logger import get_logger


class RenderPanel(QWidget):
    """Render panel - placeholder implementation."""

    renderStarted = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self._setup_ui()

    def _setup_ui(self):
        """Setup render panel UI."""
        layout = QVBoxLayout(self)

        title = QLabel("Render Settings")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        # Placeholder content
        placeholder = QLabel("Render settings not yet implemented")
        placeholder.setStyleSheet("color: #888888; font-style: italic;")
        layout.addWidget(placeholder)

        layout.addStretch()

        self.logger.info("Render panel initialized (placeholder)")