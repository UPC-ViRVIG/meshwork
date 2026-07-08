# gui/panel_material.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from logger import get_logger


class MaterialPanel(QWidget):
    """Material panel - placeholder implementation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()
        self._setup_ui()

    def _setup_ui(self):
        """Setup material panel UI."""
        layout = QVBoxLayout(self)

        title = QLabel("Material Properties")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        # Placeholder content
        placeholder = QLabel("Material editing not yet implemented")
        placeholder.setStyleSheet("color: #888888; font-style: italic;")
        layout.addWidget(placeholder)

        layout.addStretch()

        self.logger.info("Material panel initialized (placeholder)")