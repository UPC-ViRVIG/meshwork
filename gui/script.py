# gui/script.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QPlainTextEdit, QTextEdit, QLabel, QSplitter)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
import time
import ast
from typing import List
from config import get_config
from gui.style_manager import get_style_manager
from logger import get_logger


class ScriptConsole(QWidget):
    """Script console with signal-driven output handling"""

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.style_manager = get_style_manager()
        self.config = get_config()
        self.logger = get_logger()
        self.max_lines = self.config.get("gui", "script", {}).get("max_console_lines", 1000)
        self.current_lines = 0
        self._setup_ui()
        self._setup_signals()

    def _setup_ui(self):
        """Setup console UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header_layout = QHBoxLayout()

        title_label = QLabel("Console")
        title_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear)
        header_layout.addWidget(self.clear_button)

        layout.addLayout(header_layout)

        self.console_text = QTextEdit()
        self.console_text.setReadOnly(True)

        font = QFont("Consolas", 9)
        font.setFamily("monospace")
        self.console_text.setFont(font)

        self.console_text.setStyleSheet(self.style_manager.get_console_style())

        layout.addWidget(self.console_text)

        self.append_output("MeshWork Console Ready", "INFO")

    def _setup_signals(self):
        """Setup signal connections for console output"""
        if self.signal_router:
            self.signal_router.subscribe('executor.incremental_output', self.on_script_output, 'ScriptConsole')

    def on_script_output(self, data):
        """Handle script output signal"""
        stream_type = data.get('stream', 'stdout')
        text = data.get('text', '')

        self.logger.debug(f"Console received output [{stream_type}]: {text.strip()}")

        if stream_type == 'stdout':
            self.append_output(text, "INFO")
        elif stream_type == 'stderr':
            self.append_output(text, "ERROR")

    def append_prompt(self, script_content: str):
        """Append Python prompt with script content"""
        lines = script_content.strip().split('\n')
        if len(lines) == 1:
            self._append_html(f'<span style="color: #4ade80;"><b>&gt;&gt;&gt;</b></span> {self._escape_html(lines[0])}')
        else:
            self._append_html(f'<span style="color: #4ade80;"><b>&gt;&gt;&gt;</b></span> {self._escape_html(lines[0])}')
            for line in lines[1:]:
                self._append_html(f'<span style="color: #4ade80;"><b>...</b></span> {self._escape_html(line)}')

    def append_output(self, message: str, level: str = "INFO"):
        """Append message to console with color coding"""
        if not message.strip():
            return

        color_map = {
            "DEBUG": "#888888",
            "INFO": "#ffffff",
            "SUCCESS": "#4ade80",
            "WARNING": "#fbbf24",
            "ERROR": "#ef4444"
        }

        color = color_map.get(level, "#ffffff")
        escaped_message = self._escape_html(message.rstrip())

        self._append_html(f'<span style="color: {color};">{escaped_message}</span>')

    def _append_html(self, html_content: str):
        """Append HTML content and manage buffer"""
        cursor = self.console_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html_content + "<br>")

        self.current_lines += 1
        if self.current_lines > self.max_lines:
            self._trim_buffer()

        self.console_text.setTextCursor(cursor)
        self.console_text.ensureCursorVisible()

    def _trim_buffer(self):
        """Trim buffer to keep within line limits"""
        lines_to_remove = int(self.max_lines * 0.2)

        cursor = self.console_text.textCursor()
        cursor.movePosition(QTextCursor.Start)

        for _ in range(lines_to_remove):
            cursor.select(QTextCursor.LineUnderCursor)
            cursor.movePosition(QTextCursor.Down)

        cursor.removeSelectedText()

        self.current_lines -= lines_to_remove

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#x27;'))

    def clear(self):
        """Clear console content"""
        self.console_text.clear()
        self.current_lines = 0
        self.append_output("Console cleared", "INFO")

    def reset_content(self):
        """Reset console content for layout reset"""
        self.clear()

    def cleanup(self):
        """Cleanup signal connections"""
        if self.signal_router:
            self.signal_router.unsubscribe_all('ScriptConsole')


class ScriptEditor(QWidget):
    """Script editor with signal-driven execution"""

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.config = get_config()
        self.style_manager = get_style_manager()
        self.logger = get_logger()
        self.console = None
        self.syntax_check_enabled = self.config.get("gui", "script", {}).get("syntax_check_enabled", True)
        self.sample_script = 'print("Hello, World!")'
        self._setup_ui()
        self._setup_signals()

    def _setup_ui(self):
        """Setup script editor UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header_layout = QHBoxLayout()

        title_label = QLabel("Script Editor")
        title_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear)
        header_layout.addWidget(self.clear_button)

        self.execute_button = QPushButton("Execute")
        self.execute_button.clicked.connect(self.execute_script)
        self.execute_button.setDefault(True)
        header_layout.addWidget(self.execute_button)

        layout.addLayout(header_layout)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Enter Python script here...")

        font = QFont("Consolas", self.config.get("gui", "script", {}).get("font_size", 10))
        font.setFamily("monospace")
        self.text_edit.setFont(font)

        self.text_edit.setStyleSheet(self.style_manager.get_script_editor_style())

        if self.syntax_check_enabled:
            self.text_edit.textChanged.connect(self._check_syntax)

        layout.addWidget(self.text_edit)

        self.text_edit.setPlainText(self.sample_script)

    def _setup_signals(self):
        """Setup signal connections for script execution"""
        if self.signal_router:
            self.signal_router.subscribe('executor.done_script_executed', self.on_script_completed, 'ScriptEditor')

    def set_console(self, console: 'ScriptConsole'):
        """Set console reference for output"""
        self.console = console

    def _check_syntax(self):
        """Check Python syntax and update execute button state"""
        if not self.syntax_check_enabled:
            return

        script_text = self.text_edit.toPlainText().strip()

        if not script_text:
            self.execute_button.setEnabled(True)
            return

        ast.parse(script_text)
        self.execute_button.setEnabled(True)

    def execute_script(self):
        """Execute script via signal"""
        script_text = self.text_edit.toPlainText()

        self.logger.info(f"Script editor execute request: length={len(script_text)}")
        self.logger.debug(f"Script content:\n{script_text}")

        if not script_text.strip():
            self.logger.warning("Empty script, cannot execute")
            if self.console:
                self.console.append_output("No script to execute", "WARNING")
            return

        if not self.console:
            self.logger.error("No console available for output")
            return

        if not self.signal_router:
            self.logger.error("No signal router available for script execution")
            if self.console:
                self.console.append_output("Script execution not available - no signal router", "ERROR")
            return

        self.console.append_prompt(script_text)

        self.logger.info("Emitting executor.do_execute_script signal")

        self.signal_router.emit('executor.do_execute_script', {
            'script': script_text,
            'timeout': 30.0
        })

        if self.console:
            self.console.append_output("Script execution started...", "INFO")

    def on_script_completed(self, data):
        """Handle script completion signal"""
        success = data.get('success', False)
        result = data.get('result', {})
        duration = data.get('duration', 0.0)

        self.logger.info(f"Script completion received: success={success}, duration={duration:.3f}s")
        self.logger.debug(f"Full result: {result}")

        if self.console:
            if success:
                self.console.append_output(f"Script completed successfully in {duration:.2f}s", "SUCCESS")

                stderr_content = result.get('stderr', '').strip()

                self.logger.info(f"Final stderr length: {len(stderr_content)}")

                if stderr_content:
                    self.logger.debug(f"Final stderr content: {stderr_content}")
                    self.console.append_output("Errors:", "ERROR")
                    for line in stderr_content.split('\n'):
                        if line.strip():
                            self.console.append_output(line, "ERROR")
            else:
                error_msg = result.get('error', 'Unknown error')
                self.logger.error(f"Script execution failed: {error_msg}")
                self.console.append_output(f"Script failed: {error_msg}", "ERROR")

    def clear(self):
        """Clear editor content"""
        self.text_edit.clear()
        if self.console:
            self.console.append_output("Editor cleared", "INFO")

    def reset_content(self):
        """Reset editor content for layout reset"""
        self.text_edit.setPlainText(self.sample_script)

    def toPlainText(self) -> str:
        """Get editor content"""
        return self.text_edit.toPlainText()

    def setPlainText(self, text: str):
        """Set editor content"""
        self.text_edit.setPlainText(text)

    def appendPlainText(self, text: str):
        """Append text to editor"""
        self.text_edit.appendPlainText(text)

    def cleanup(self):
        """Cleanup signal connections"""
        if self.signal_router:
            self.signal_router.unsubscribe_all('ScriptEditor')


class ScriptArea(QWidget):
    """Combined script area with editor and console"""

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.editor = None
        self.console = None

        self.default_splitter_sizes: List[int] = [700, 300]

        self._setup_ui()

    def _setup_ui(self):
        """Setup script area UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(self.splitter)

        self.editor = ScriptEditor(self.signal_router)
        self.splitter.addWidget(self.editor)

        self.console = ScriptConsole(self.signal_router)
        self.splitter.addWidget(self.console)

        self.editor.set_console(self.console)

        self.splitter.setSizes(self.default_splitter_sizes)

    def reset_to_default(self, clear_content: bool = False):
        """Reset script area to default state"""
        logger = get_logger()
        logger.info("Resetting script area to defaults")

        self._reset_splitter_proportions()

        if clear_content:
            if self.editor:
                self.editor.reset_content()
            if self.console:
                self.console.reset_content()

        logger.info("Script area reset completed")

    def _reset_splitter_proportions(self):
        """Reset splitter to default proportions"""
        if hasattr(self, 'splitter'):
            self.splitter.setSizes(self.default_splitter_sizes)

    def get_script_content(self) -> str:
        """Get current script content"""
        if self.editor:
            return self.editor.toPlainText()
        return ""

    def set_script_content(self, content: str):
        """Set script content"""
        if self.editor:
            self.editor.setPlainText(content)

    def clear_console(self):
        """Clear console output"""
        if self.console:
            self.console.clear()

    def clear_editor(self):
        """Clear editor content"""
        if self.editor:
            self.editor.clear()

    def execute_script(self):
        """Execute current script"""
        if self.editor:
            self.editor.execute_script()

    def cleanup(self):
        """Cleanup signal connections for both components"""
        if self.editor:
            self.editor.cleanup()
        if self.console:
            self.console.cleanup()