# gui/view.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLabel, QPushButton, QApplication
from PySide6.QtCore import Qt, Signal
from typing import Dict, Any, Optional
from logger import get_logger
import pyvista as pv
from pyvistaqt import QtInteractor
from gui.render import SceneRenderer


class ViewState:
    def __init__(self):
        self.current_view = "perspective"
        self.show_grid = True
        self.show_axes = True

    def reset_to_defaults(self):
        self.current_view = "perspective"
        self.show_grid = True
        self.show_axes = True


class PickingHandler:
    def __init__(self, signal_router):
        self._signal_router = signal_router
        self._picking_tolerance = 0.01

    def handle_mesh_picked(self, mesh):
        if not mesh:
            return

        object_name = self._extract_object_name(mesh)
        if not object_name:
            return

        extend = self._get_modifier_keys()

        if self._signal_router:
            self._signal_router.emit('scene.do_select_object', {
                'object_name': object_name,
                'extend': extend
            })

    def _extract_object_name(self, mesh):
        if not hasattr(mesh, 'field_data'):
            return None

        try:
            if 'object_name' not in mesh.field_data:
                return None
            object_name = mesh.field_data['object_name']
        except Exception:
            return None

        if not object_name:
            return None

        if isinstance(object_name, str):
            return object_name
        elif hasattr(object_name, '__iter__') and len(object_name) > 0:
            return str(object_name[0])
        else:
            return str(object_name)

    def _get_modifier_keys(self):
        modifiers = QApplication.keyboardModifiers()
        return bool(modifiers & (Qt.ShiftModifier | Qt.ControlModifier))


class View(QWidget):
    objectSelected = Signal(str, bool)
    viewChanged = Signal(str)

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()

        self.state = ViewState()
        self.plotter = None
        self.renderer = None
        self.picking_handler = None

        self._setup_ui()
        self._setup_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self)
        self.plotter.set_background([0.2, 0.2, 0.2])

        if hasattr(self.plotter, 'auto_update'):
            self.plotter.auto_update = False

        layout.addWidget(self.plotter)

        self.renderer = SceneRenderer(self.plotter)

        self.picking_handler = PickingHandler(self.signal_router)
        try:
            self.plotter.enable_mesh_picking(
                callback=self.picking_handler.handle_mesh_picked,
                show=False,
                show_message=False,
                font_size=0
            )
        except TypeError:
            self.plotter.enable_mesh_picking(
                callback=self.picking_handler.handle_mesh_picked,
                show=False
            )

        controls_layout = QHBoxLayout()

        view_label = QLabel("View:")
        controls_layout.addWidget(view_label)

        self.view_combo = QComboBox()
        self.view_combo.addItems(["Perspective", "Top", "Front", "Side"])
        self.view_combo.currentTextChanged.connect(self.on_view_changed)
        controls_layout.addWidget(self.view_combo)

        controls_layout.addStretch()

        self.grid_checkbox = QCheckBox("Grid")
        self.grid_checkbox.setChecked(True)
        self.grid_checkbox.stateChanged.connect(self.on_grid_toggled)
        controls_layout.addWidget(self.grid_checkbox)

        self.axes_checkbox = QCheckBox("Axes")
        self.axes_checkbox.setChecked(True)
        self.axes_checkbox.stateChanged.connect(self.on_axes_toggled)
        controls_layout.addWidget(self.axes_checkbox)

        self.reset_camera_btn = QPushButton("Reset Camera")
        self.reset_camera_btn.clicked.connect(self.on_reset_camera_clicked)
        controls_layout.addWidget(self.reset_camera_btn)

        layout.addLayout(controls_layout)

    def _setup_signals(self):
        if self.signal_router:
            self.signal_router.subscribe('scene.render_data_updated', self.on_render_data_updated, 'View')
            self.signal_router.subscribe('view.reset_camera', self.on_reset_camera_signal, 'View')
            self.signal_router.subscribe('view.tool_changed', self.on_tool_changed, 'View')
            self.signal_router.subscribe('view.reset_layout', self.on_reset_layout, 'View')

    def reset_to_default_view_state(self):
        self.logger.info("Resetting view to default state")

        self.state.reset_to_defaults()

        self.view_combo.setCurrentText("Perspective")
        self.grid_checkbox.setChecked(True)
        self.axes_checkbox.setChecked(True)

        if self.renderer:
            self.renderer.setup_default_camera()
            self.renderer.toggle_grid(True)
            self.renderer.toggle_axes(True)

        self.logger.info("View state reset completed")

    def on_render_data_updated(self, data):
        render_data = data.get('render_data')
        if render_data and self.renderer:
            objects = render_data.get('objects', [])
            self.renderer.update_scene(objects)

    def on_reset_camera_signal(self, data):
        if self.renderer:
            self.renderer.reset_camera()

    def on_tool_changed(self, data):
        tool_name = data.get('tool_name')
        self.logger.debug(f"Tool changed to: {tool_name}")

    def on_reset_layout(self, data):
        self.reset_to_default_view_state()

    def on_view_changed(self, view_name):
        self.state.current_view = view_name.lower()
        if self.renderer:
            self.renderer.set_view(view_name)
        self.viewChanged.emit(self.state.current_view)

    def on_grid_toggled(self, state):
        self.state.show_grid = (state == Qt.CheckState.Checked.value)
        if self.renderer:
            self.renderer.toggle_grid(self.state.show_grid)

    def on_axes_toggled(self, state):
        self.state.show_axes = (state == Qt.CheckState.Checked.value)
        if self.renderer:
            self.renderer.toggle_axes(self.state.show_axes)

    def on_reset_camera_clicked(self):
        if self.renderer:
            self.renderer.reset_camera()

    def set_view(self, view_type):
        if self.renderer:
            self.renderer.set_view(view_type)
        return True

    def toggle_grid(self, visible):
        self.state.show_grid = visible
        self.grid_checkbox.setChecked(visible)
        if self.renderer:
            self.renderer.toggle_grid(visible)

    def toggle_axes(self, visible):
        self.state.show_axes = visible
        self.axes_checkbox.setChecked(visible)
        if self.renderer:
            self.renderer.toggle_axes(visible)

    def reset_view(self):
        if self.renderer:
            self.renderer.reset_camera()

    def clear_scene(self):
        if self.renderer:
            self.renderer.clear_scene()

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('View')


class ViewManager:
    def __init__(self, view_widget, parent=None):
        self.view_widget = view_widget
        self.logger = get_logger()

    def set_view(self, view_type):
        if hasattr(self.view_widget, 'set_view'):
            return self.view_widget.set_view(view_type)
        return False

    def reset_view(self):
        if hasattr(self.view_widget, 'reset_view'):
            self.view_widget.reset_view()

    def toggle_grid(self, visible):
        if hasattr(self.view_widget, 'toggle_grid'):
            self.view_widget.toggle_grid(visible)

    def toggle_axes(self, visible):
        if hasattr(self.view_widget, 'toggle_axes'):
            self.view_widget.toggle_axes(visible)