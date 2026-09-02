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
        self.show_bounds = False

    def reset_to_defaults(self) -> None:
        self.current_view = "perspective"
        self.show_grid = True
        self.show_axes = True
        self.show_bounds = False


class PickingHandler:
    def __init__(self, signal_router):
        self._signal_router = signal_router
        self._picking_tolerance = 0.01
        self._logger = get_logger()

    def handle_mesh_picked(self, *args) -> None:
        self._logger.info(
            f"handle_mesh_picked called: n_args={len(args)}, "
            f"arg_types={[type(a).__name__ for a in args]}"
        )

        mesh = args[0] if args else None

        if mesh is None:
            self._logger.warning("handle_mesh_picked: args[0] is None (picker found nothing)")
            return

        self._logger.info(
            f"handle_mesh_picked: mesh type={type(mesh).__name__}, "
            f"has_field_data={hasattr(mesh, 'field_data')}"
        )

        if hasattr(mesh, 'field_data') and mesh.field_data is not None:
            try:
                fd_keys = list(mesh.field_data.keys()) if hasattr(mesh.field_data, 'keys') else []
                self._logger.info(f"handle_mesh_picked: field_data keys={fd_keys}")
                for k in fd_keys:
                    val = mesh.field_data[k]
                    self._logger.info(
                        f"  field_data[{k!r}] = {val!r} (type={type(val).__name__})"
                    )
            except Exception as e:
                self._logger.warning(f"handle_mesh_picked: error reading field_data: {e}")
        else:
            self._logger.warning(
                f"handle_mesh_picked: no field_data on picked object "
                f"(type={type(mesh).__name__})"
            )

        if not mesh:
            return

        object_name = self._extract_object_name(mesh)
        self._logger.info(f"handle_mesh_picked: extracted object_name={object_name!r}")

        if not object_name:
            return

        extend = self._get_modifier_keys()

        if self._signal_router:
            self._signal_router.emit('scene.do_select_object', {
                'object_name': object_name,
                'extend': extend
            })

    def _extract_object_name(self, mesh) -> Optional[str]:
        if not hasattr(mesh, 'field_data') or mesh.field_data is None:
            return None

        try:
            wrapped = pv.wrap(mesh)
            raw = wrapped.field_data.get('object_name')
            if raw is None:
                return None

            if isinstance(raw, str):
                return raw
            elif isinstance(raw, (list, tuple)) and len(raw) > 0:
                return str(raw[0])
            elif hasattr(raw, '__len__') and len(raw) > 0:
                val = raw[0]
                if isinstance(val, bytes):
                    return val.decode('utf-8')
                if hasattr(val, 'item'):
                    return str(val.item())
                return str(val)
            else:
                return str(raw)
        except Exception as e:
            self._logger.warning(f"_extract_object_name pv.wrap path failed ({e}), trying VTK direct")

        try:
            fd = mesh.GetFieldData() if hasattr(mesh, 'GetFieldData') else None
            if fd is None:
                return None
            arr = fd.GetAbstractArray('object_name')
            if arr is None:
                return None
            if hasattr(arr, 'GetValue'):
                val = arr.GetValue(0)
                return str(val) if val else None
            return None
        except Exception as e:
            self._logger.warning(f"_extract_object_name VTK direct path failed: {e}")
            return None

    def _get_modifier_keys(self) -> bool:
        modifiers = QApplication.keyboardModifiers()
        return bool(modifiers & (Qt.ShiftModifier | Qt.ControlModifier))

    def handle_actor_picked(self, *args) -> None:
        self._logger.info(
            f"handle_actor_picked called: n_args={len(args)}, "
            f"arg_types={[type(a).__name__ for a in args]}"
        )
        actor = args[0] if args else None
        if actor is None:
            self._logger.warning("handle_actor_picked: actor is None")
            return

        self._logger.info(
            f"handle_actor_picked: actor type={type(actor).__name__}"
        )

        name_from_vtk = None
        try:
            if hasattr(actor, 'GetObjectName'):
                name_from_vtk = actor.GetObjectName()
                self._logger.info(f"handle_actor_picked: GetObjectName()={name_from_vtk!r}")
        except Exception as e:
            self._logger.warning(f"handle_actor_picked: GetObjectName failed: {e}")

        mapper_dataset = None
        try:
            if hasattr(actor, 'GetMapper') and actor.GetMapper():
                mapper = actor.GetMapper()
                if hasattr(mapper, 'GetInputDataObject'):
                    mapper_dataset = mapper.GetInputDataObject(0, 0)
                    self._logger.info(
                        f"handle_actor_picked: mapper dataset type="
                        f"{type(mapper_dataset).__name__ if mapper_dataset else None}"
                    )
        except Exception as e:
            self._logger.warning(f"handle_actor_picked: mapper inspection failed: {e}")

        self._logger.info(
            f"handle_actor_picked summary: "
            f"vtk_name={name_from_vtk!r}, "
            f"has_mapper_data={mapper_dataset is not None}"
        )


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
        self._setup_picking()

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
            self.signal_router.subscribe('view.toggle_bounds', self.on_toggle_bounds_signal, 'View')

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
            self.renderer.toggle_bounds(False)

        self.logger.info("View state reset completed")

    def _setup_picking(self):
        try:
            pv_version = tuple(int(x) for x in pv.__version__.split('.')[:2])
            self.logger.info(f"PyVista version: {pv.__version__} (parsed: {pv_version})")
        except Exception:
            pv_version = (0, 0)
            self.logger.warning(f"Could not parse PyVista version: {pv.__version__}")

        self.logger.info(
            f"Plotter type: {type(self.plotter).__name__}, "
            f"has enable_mesh_picking={hasattr(self.plotter, 'enable_mesh_picking')}, "
            f"has enable_actor_picking={hasattr(self.plotter, 'enable_actor_picking')}"
        )

        self._pv_version = pv_version
        self._reregister_picking()

    def _reregister_picking(self):
        if not self.plotter or not self.picking_handler:
            return

        pv_version = getattr(self, '_pv_version', (0, 0))

        try:
            if hasattr(self.plotter, 'disable_picking'):
                self.plotter.disable_picking()
            elif hasattr(self.plotter, 'picking') and hasattr(self.plotter.picking, 'disable_picking'):
                self.plotter.picking.disable_picking()
        except Exception as e:
            self.logger.debug(f"disable_picking skipped: {e}")

        mesh_picking_ok = False

        try:
            if pv_version >= (0, 44):
                self.plotter.enable_mesh_picking(
                    callback=self.picking_handler.handle_mesh_picked,
                    show=False,
                    show_message=False,
                    left_clicking=True,
                )
            else:
                self.plotter.enable_mesh_picking(
                    callback=self.picking_handler.handle_mesh_picked,
                    show=False,
                    show_message=False,
                    font_size=0,
                )
            mesh_picking_ok = True
            self.logger.debug("Picking re-registered (mesh picking)")
        except TypeError as e:
            self.logger.warning(f"enable_mesh_picking re-register failed ({e}), trying minimal")
            try:
                self.plotter.enable_mesh_picking(
                    callback=self.picking_handler.handle_mesh_picked,
                    left_clicking=True,
                )
                mesh_picking_ok = True
                self.logger.debug("Picking re-registered (minimal fallback)")
            except Exception as e2:
                self.logger.error(f"enable_mesh_picking re-register failed completely: {e2}")

        if not mesh_picking_ok and hasattr(self.plotter, 'enable_actor_picking'):
            try:
                self.plotter.enable_actor_picking(
                    callback=self.picking_handler.handle_actor_picked,
                    show=False,
                    show_message=False,
                )
                self.logger.debug("Picking re-registered (actor picking fallback)")
            except Exception as e3:
                self.logger.error(f"enable_actor_picking re-register also failed: {e3}")

    def on_render_data_updated(self, data: Dict[str, Any]):
        render_data = data.get('render_data')
        if render_data and self.renderer:
            objects = render_data.get('objects', [])
            for obj in objects:
                name = obj.get('name', '?')
                has_verts = 'vertices' in obj and obj['vertices'] is not None
                n_verts = len(obj['vertices']) if has_verts else 0
                dirty = obj.get('dirty_state', 'unknown')
            self.renderer.update_scene(objects)
            self._reregister_picking()

    def on_reset_camera_signal(self, data: Dict[str, Any]):
        if self.renderer:
            self.renderer.reset_camera()

    def on_tool_changed(self, data: Dict[str, Any]):
        tool_name = data.get('tool_name')
        self.logger.debug(f"Tool changed to: {tool_name}")

    def on_reset_layout(self, data: Dict[str, Any]):
        self.reset_to_default_view_state()

    def on_toggle_bounds_signal(self, data: Dict[str, Any]):
        visible = bool(data.get('visible', False))
        self.state.show_bounds = visible
        if self.renderer:
            self.renderer.toggle_bounds(visible)

    def on_view_changed(self, view_name: str):
        self.state.current_view = view_name.lower()
        if self.renderer:
            self.renderer.set_view(view_name)
        self.viewChanged.emit(self.state.current_view)

    def on_grid_toggled(self, state: int):
        self.state.show_grid = (state == Qt.CheckState.Checked.value)
        if self.renderer:
            self.renderer.toggle_grid(self.state.show_grid)

    def on_axes_toggled(self, state: int):
        self.state.show_axes = (state == Qt.CheckState.Checked.value)
        if self.renderer:
            self.renderer.toggle_axes(self.state.show_axes)

    def on_reset_camera_clicked(self):
        if self.renderer:
            self.renderer.reset_camera()

    def set_view(self, view_type: str):
        if self.renderer:
            self.renderer.set_view(view_type)
        return True

    def toggle_grid(self, visible: bool):
        self.state.show_grid = visible
        self.grid_checkbox.setChecked(visible)
        if self.renderer:
            self.renderer.toggle_grid(visible)

    def toggle_axes(self, visible: bool):
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

    def set_view(self, view_type: str):
        if hasattr(self.view_widget, 'set_view'):
            return self.view_widget.set_view(view_type)
        return False

    def reset_view(self):
        if hasattr(self.view_widget, 'reset_view'):
            self.view_widget.reset_view()

    def toggle_grid(self, visible: bool):
        if hasattr(self.view_widget, 'toggle_grid'):
            self.view_widget.toggle_grid(visible)

    def toggle_axes(self, visible: bool):
        if hasattr(self.view_widget, 'toggle_axes'):
            self.view_widget.toggle_axes(visible)