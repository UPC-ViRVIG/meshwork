# gui/panel_scene.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QLabel, QListWidgetItem, QHBoxLayout, QPushButton, QApplication
from PySide6.QtCore import Signal, QObject, Qt
from PySide6.QtGui import QKeyEvent
from logger import get_logger


class SceneController(QObject):

    objectSelected = Signal(str)

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self._setup_done_handlers()

    def _setup_done_handlers(self):
        pass

    def _select_object(self, object_name: str, extend: bool = False):
        if self.signal_router:
            self.signal_router.emit('scene.do_select_object', {
                'object_name': object_name,
                'extend': extend
            })

    def _delete_selected_objects(self):
        if self.signal_router:
            self.signal_router.emit('scene.do_remove_object', {})

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('SceneController')


class ScenePanel(QWidget):

    objectSelected = Signal(str)
    selectionChanged = Signal(list)

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.controller = SceneController(signal_router, self)
        self.controller.objectSelected.connect(self.objectSelected)

        self.logger = get_logger()
        self.selected_object_names = set()

        self._setup_ui()
        self._setup_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()

        title = QLabel("Scene Objects")
        title.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title)

        header_layout.addStretch()

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self.on_delete_selected)
        self.delete_btn.setEnabled(False)
        header_layout.addWidget(self.delete_btn)

        layout.addLayout(header_layout)

        self.object_list = QListWidget()
        self.object_list.setSelectionMode(QListWidget.NoSelection)
        self.object_list.itemClicked.connect(self.on_item_clicked)
        layout.addWidget(self.object_list)

    def _setup_signals(self):
        if self.signal_router:
            self.signal_router.subscribe('scene.done_selection_changed', self.done_selection_changed, 'ScenePanel')

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Delete:
            self.on_delete_selected()
        else:
            super().keyPressEvent(event)

    def _get_modifier_keys(self) -> bool:
        modifiers = QApplication.keyboardModifiers()
        return bool(modifiers & (Qt.ShiftModifier | Qt.ControlModifier))

    def _refresh_object_list(self, all_objects: list):
        self.object_list.clear()

        for obj_data in all_objects:
            if obj_data.get('type') in ['CAMERA', 'LIGHT']:
                continue

            item = QListWidgetItem()

            name = obj_data.get('name', 'unnamed')
            obj_type = obj_data.get('type', 'UNKNOWN')
            display_text = f"{name} [{obj_type}]"

            item.setText(display_text)
            item.setData(Qt.UserRole, name)

            self.object_list.addItem(item)

    def _update_item_styles(self):
        """Update visual styles for all items based on selection state"""
        for i in range(self.object_list.count()):
            item = self.object_list.item(i)
            object_name = item.data(Qt.UserRole)

            if object_name in self.selected_object_names:
                # Selected style - blue background
                item.setBackground(Qt.blue)
                item.setForeground(Qt.white)
            else:
                # Unselected style - default
                item.setBackground(Qt.transparent)
                item.setForeground(Qt.white)

    def _update_list_selection(self, all_objects: list):
        # Sync local selection state with backend state
        backend_selected = set(obj.get('name', '') for obj in all_objects if obj.get('selected', False))

        # Update local state to match backend
        self.selected_object_names = backend_selected

        # Update visual appearance
        self._update_item_styles()

        # Update delete button
        self.delete_btn.setEnabled(len(self.selected_object_names) > 0)

    def done_selection_changed(self, data):
        all_objects = data.get('all_objects', [])
        self._refresh_object_list(all_objects)
        self._update_list_selection(all_objects)

    def on_item_clicked(self, item: QListWidgetItem):
        object_name = item.data(Qt.UserRole)
        if object_name:
            extend = self._get_modifier_keys()

            # Update selection state immediately for instant visual feedback
            if extend:
                # Toggle selection
                if object_name in self.selected_object_names:
                    self.selected_object_names.remove(object_name)
                else:
                    self.selected_object_names.add(object_name)
            else:
                # Replace selection
                self.selected_object_names.clear()
                self.selected_object_names.add(object_name)

            # Update visual appearance immediately
            self._update_item_styles()

            # Update delete button state
            self.delete_btn.setEnabled(len(self.selected_object_names) > 0)

            # Emit selection changed signal
            self.selectionChanged.emit(list(self.selected_object_names))

            # Send signal to backend (async, no waiting)
            self.controller._select_object(object_name, extend)

    def on_delete_selected(self):
        self.controller._delete_selected_objects()

    def cleanup(self):
        if self.controller:
            self.controller.cleanup()
        if self.signal_router:
            self.signal_router.unsubscribe_all('ScenePanel')