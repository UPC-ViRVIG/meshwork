# gui/panel_scene.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QListWidget, QLabel,
                                QListWidgetItem, QHBoxLayout, QPushButton,
                                QApplication, QToolButton, QSizePolicy)
from PySide6.QtCore import Signal, QObject, Qt, QSize
from PySide6.QtGui import QKeyEvent
import qtawesome as qta
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

    def _toggle_visibility(self, object_name: str):
        if self.signal_router:
            self.signal_router.emit('scene.do_toggle_visibility', {
                'object_name': object_name
            })

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('SceneController')


class SceneItemWidget(QWidget):

    visibilityToggled = Signal(str)

    def __init__(self, object_name: str, display_text: str, visible: bool, parent=None):
        super().__init__(parent)
        self.object_name = object_name
        self._visible = visible
        self.logger = get_logger()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        self.name_label = QLabel(display_text)
        self.name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)

        self.vis_btn = QToolButton()
        self.vis_btn.setAutoRaise(True)
        self.vis_btn.setFixedSize(QSize(20, 20))
        self.vis_btn.setIconSize(QSize(14, 14))
        self.vis_btn.clicked.connect(self._on_vis_clicked)
        layout.addWidget(self.vis_btn)

        self._update_icon()

    def _update_icon(self):
        if self._visible:
            icon = qta.icon('fa5.eye', color='#cccccc')
        else:
            icon = qta.icon('fa5.eye-slash', color='#666666')
        self.vis_btn.setIcon(icon)

    def set_visible_state(self, visible: bool):
        self._visible = visible
        self._update_icon()

    def set_selected(self, selected: bool):
        if selected:
            self.name_label.setStyleSheet("color: white; background: transparent;")
            self.setStyleSheet("background-color: #2255aa;")
        else:
            if self._visible:
                self.name_label.setStyleSheet("color: white; background: transparent;")
            else:
                self.name_label.setStyleSheet("color: #666666; background: transparent;")
            self.setStyleSheet("background-color: transparent;")

    def _on_vis_clicked(self):
        self.visibilityToggled.emit(self.object_name)


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

            name = obj_data.get('name', 'unnamed')
            obj_type = obj_data.get('type', 'UNKNOWN')
            visible = obj_data.get('visible', True)
            display_text = f"{name} [{obj_type}]"

            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setSizeHint(QSize(0, 28))

            item_widget = SceneItemWidget(name, display_text, visible)
            item_widget.visibilityToggled.connect(self._on_visibility_toggled)

            self.object_list.addItem(item)
            self.object_list.setItemWidget(item, item_widget)

            retrieved = self.object_list.itemWidget(item)


    def _update_item_styles(self):
        for i in range(self.object_list.count()):
            item = self.object_list.item(i)
            object_name = item.data(Qt.UserRole)
            widget = self.object_list.itemWidget(item)
            if widget:
                selected = object_name in self.selected_object_names
                widget.set_selected(selected)

    def _update_list_selection(self, all_objects: list):
        backend_selected = set(obj.get('name', '') for obj in all_objects if obj.get('selected', False))
        self.selected_object_names = backend_selected
        self._update_item_styles()
        self.delete_btn.setEnabled(len(self.selected_object_names) > 0)

    def done_selection_changed(self, data):
        all_objects = data.get('all_objects', [])
        self._refresh_object_list(all_objects)
        self._update_list_selection(all_objects)
        for i in range(self.object_list.count()):
            item = self.object_list.item(i)
            w = self.object_list.itemWidget(item)

    def on_item_clicked(self, item: QListWidgetItem):
        object_name = item.data(Qt.UserRole)
        if object_name:
            extend = self._get_modifier_keys()

            if extend:
                if object_name in self.selected_object_names:
                    self.selected_object_names.remove(object_name)
                else:
                    self.selected_object_names.add(object_name)
            else:
                self.selected_object_names.clear()
                self.selected_object_names.add(object_name)

            self._update_item_styles()
            self.delete_btn.setEnabled(len(self.selected_object_names) > 0)
            self.selectionChanged.emit(list(self.selected_object_names))
            self.controller._select_object(object_name, extend)

    def _on_visibility_toggled(self, object_name: str):
        self.controller._toggle_visibility(object_name)

    def on_delete_selected(self):
        self.controller._delete_selected_objects()

    def cleanup(self):
        if self.controller:
            self.controller.cleanup()
        if self.signal_router:
            self.signal_router.unsubscribe_all('ScenePanel')