# gui/panel_tools.py
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QGroupBox,
                               QDoubleSpinBox, QLabel, QHBoxLayout, QCheckBox, QSpinBox, QFrame)
from PySide6.QtCore import Signal, QObject, Qt
from logger import get_logger
from scipy.spatial.transform import Rotation
import numpy as np

class ToolsController(QObject):

    toolSelected = Signal(str)

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.current_tool = None
        self.selected_objects = []
        self.logger = get_logger()
        self._setup_done_handlers()

    def _setup_done_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('mesh.done_operation', self.done_mesh_operation, 'ToolsController')
            self.signal_router.subscribe('transform.tool_ready', self.done_tool_ready, 'ToolsController')
            self.signal_router.subscribe('scene.done_selection_changed', self.done_selection_changed, 'ToolsController')
            self.signal_router.subscribe('scene.done_baking', self.done_baking, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_analyze_plane', self.done_pointcloud_operation, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_remove_plane', self.done_pointcloud_operation, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_remove_plane_preview', self.done_remove_plane_preview, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_align_clouds', self.done_pointcloud_operation, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_merge_clouds', self.done_pointcloud_operation, 'ToolsController')
            self.signal_router.subscribe('pointcloud.done_generate_mesh', self.done_pointcloud_operation, 'ToolsController')

    def set_active_tool(self, tool_name: str, selected_objects: list = None):
        valid_tools = ["move", "rotate", "quat_rotate", "scale"]
        if tool_name not in valid_tools:
            self.logger.warning(f"Invalid tool: {tool_name}")
            return False

        if selected_objects is None:
            selected_objects = []

        self.current_tool = tool_name
        self.selected_objects = selected_objects
        self.toolSelected.emit(tool_name)
        self.logger.info(f"Active tool: {tool_name}")

        if self.signal_router:
            self.signal_router.emit('transform.tool_activated', {
                'tool_type': tool_name,
                'selected_objects': selected_objects
            })

        return True

    def get_active_tool(self) -> str:
        return self.current_tool

    def preview_move(self, position: list):
        if self.signal_router and self.current_tool == "move":
            self.signal_router.emit('transform.preview_move', {
                'object_names': self.selected_objects,
                'position': position
            })

    def preview_rotate(self, rotation: list):
        if self.signal_router and self.current_tool in ["rotate", "quat_rotate"]:
            self.signal_router.emit('transform.preview_rotate', {
                'object_names': self.selected_objects,
                'rotation': rotation
            })

    def preview_scale(self, scale: list, uniform: bool = False):
        if self.signal_router and self.current_tool == "scale":
            self.signal_router.emit('transform.preview_scale', {
                'object_names': self.selected_objects,
                'scale': scale,
                'uniform': uniform
            })

    def apply_changes(self):
        if self.signal_router and self.current_tool:
            self.signal_router.emit('transform.apply_changes', {
                'object_names': self.selected_objects
            })
        self.current_tool = None

    def cancel_changes(self):
        if self.signal_router and self.current_tool:
            self.signal_router.emit('transform.cancel_changes', {
                'object_names': self.selected_objects
            })
        self.current_tool = None

    def subdivide_mesh(self, object_id: str = 'selected', levels: int = 1):
        if self.signal_router:
            self.signal_router.emit('mesh.do_subdivide', {
                'object_id': object_id,
                'levels': levels
            })

    def simplify_mesh(self, object_id: str = 'selected', ratio: float = 0.5):
        if self.signal_router:
            self.signal_router.emit('mesh.do_simplify', {
                'object_id': object_id,
                'ratio': ratio
            })

    def repair_mesh(self, object_id: str = 'selected'):
        if self.signal_router:
            self.signal_router.emit('mesh.do_repair', {
                'object_id': object_id
            })

    def done_mesh_operation(self, data):
        operation_type = data.get('operation_type', '')
        object_id = data.get('object_id', '')
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.logger.info(f"Mesh {operation_type} completed for {object_id}")
        else:
            self.logger.error(f"Mesh {operation_type} failed for {object_id}: {error}")

    def done_tool_ready(self, data):
        tool_type = data.get('tool_type', '')
        current_values = data.get('current_values', {})

        if tool_type == self.current_tool:
            parent_widget = self.parent()
            if hasattr(parent_widget, 'update_tool_values'):
                parent_widget.update_tool_values(tool_type, current_values)

    def done_selection_changed(self, data):
        all_objects = data.get('all_objects', [])
        selected_names = [obj.get('name') for obj in all_objects if obj.get('selected', False)]

        if self.current_tool:
            self.logger.info(f"Selection changed while {self.current_tool} tool active - canceling tool")
            self._cancel_tool_due_to_selection_change()

        self.selected_objects = selected_names

        parent_widget = self.parent()
        if hasattr(parent_widget, 'update_selection'):
            parent_widget.update_selection(selected_names)

    def done_baking(self, data):
        parent_widget = self.parent()
        if hasattr(parent_widget, 'on_done_baking'):
            parent_widget.on_done_baking(data)

    def done_pointcloud_operation(self, data):
        success = data.get('success', False)
        error = data.get('error', '')

        if success:
            self.logger.info("Point cloud operation completed")
        else:
            self.logger.error(f"Point cloud operation failed: {error}")

        parent_widget = self.parent()
        if hasattr(parent_widget, '_clear_pointcloud_tool_state'):
            parent_widget._clear_pointcloud_tool_state()

    def done_remove_plane_preview(self, data):
        recommended_margin = data.get('recommended_margin', 0.05)

        parent_widget = self.parent()
        if hasattr(parent_widget, 'pc_margin_input'):
            parent_widget.pc_margin_input.setValue(recommended_margin)

    def _cancel_tool_due_to_selection_change(self):
        if self.signal_router and self.current_tool:
            if self.current_tool in ['move', 'rotate', 'scale']:
                self.signal_router.emit('transform.cancel_changes', {
                    'object_names': self.selected_objects
                })

        self.current_tool = None

        parent_widget = self.parent()
        if hasattr(parent_widget, '_clear_tool_selection'):
            parent_widget._clear_tool_selection()
        if hasattr(parent_widget, '_clear_baking_tool_state'):
            parent_widget._clear_baking_tool_state()
        if hasattr(parent_widget, '_clear_pointcloud_tool_state'):
            parent_widget._clear_pointcloud_tool_state()

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ToolsController')


class ToolsPanel(QWidget):
    """Tools panel"""

    toolSelected = Signal(str)

    def __init__(self, signal_router=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.controller = ToolsController(signal_router, self)
        self.controller.toolSelected.connect(self.toolSelected)

        self.logger = get_logger()
        self.selected_objects = []
        self.current_tool = None
        self.quat_base_rotation = None

        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        transform_group = QGroupBox("Transform")
        transform_layout = QVBoxLayout(transform_group)

        self.move_btn = QPushButton("Move")
        self.move_btn.setCheckable(True)
        self.move_btn.clicked.connect(lambda: self.on_tool_selected("move"))
        transform_layout.addWidget(self.move_btn)

        self.move_controls = QWidget()
        move_layout = QVBoxLayout(self.move_controls)
        move_layout.setContentsMargins(20, 5, 5, 5)

        move_layout.addWidget(QLabel("Position:"))

        pos_layout = QHBoxLayout()

        pos_layout.addWidget(QLabel("X:"))
        self.move_x = QDoubleSpinBox()
        self.move_x.setRange(-1000.0, 1000.0)
        self.move_x.setDecimals(2)
        self.move_x.setSingleStep(0.1)
        pos_layout.addWidget(self.move_x)

        pos_layout.addWidget(QLabel("Y:"))
        self.move_y = QDoubleSpinBox()
        self.move_y.setRange(-1000.0, 1000.0)
        self.move_y.setDecimals(2)
        self.move_y.setSingleStep(0.1)
        pos_layout.addWidget(self.move_y)

        pos_layout.addWidget(QLabel("Z:"))
        self.move_z = QDoubleSpinBox()
        self.move_z.setRange(-1000.0, 1000.0)
        self.move_z.setDecimals(2)
        self.move_z.setSingleStep(0.1)
        pos_layout.addWidget(self.move_z)

        move_layout.addLayout(pos_layout)

        move_buttons = QHBoxLayout()
        move_buttons.addStretch()

        self.move_apply_btn = QPushButton("Apply")
        self.move_apply_btn.clicked.connect(self.on_apply_changes)
        move_buttons.addWidget(self.move_apply_btn)

        self.move_cancel_btn = QPushButton("Cancel")
        self.move_cancel_btn.clicked.connect(self.on_cancel_changes)
        move_buttons.addWidget(self.move_cancel_btn)

        move_layout.addLayout(move_buttons)
        self.move_controls.setVisible(False)
        transform_layout.addWidget(self.move_controls)

        self.rotate_btn = QPushButton("Rotate")
        self.rotate_btn.setCheckable(True)
        self.rotate_btn.clicked.connect(lambda: self.on_tool_selected("rotate"))
        transform_layout.addWidget(self.rotate_btn)

        self.rotate_controls = QWidget()
        rotate_layout = QVBoxLayout(self.rotate_controls)
        rotate_layout.setContentsMargins(20, 5, 5, 5)

        rotate_layout.addWidget(QLabel("Rotation (degrees):"))

        rot_layout = QHBoxLayout()

        rot_layout.addWidget(QLabel("X:"))
        self.rotate_x = QDoubleSpinBox()
        self.rotate_x.setRange(-360.0, 360.0)
        self.rotate_x.setDecimals(2)
        self.rotate_x.setSingleStep(1.0)
        rot_layout.addWidget(self.rotate_x)

        rot_layout.addWidget(QLabel("Y:"))
        self.rotate_y = QDoubleSpinBox()
        self.rotate_y.setRange(-360.0, 360.0)
        self.rotate_y.setDecimals(2)
        self.rotate_y.setSingleStep(1.0)
        rot_layout.addWidget(self.rotate_y)

        rot_layout.addWidget(QLabel("Z:"))
        self.rotate_z = QDoubleSpinBox()
        self.rotate_z.setRange(-360.0, 360.0)
        self.rotate_z.setDecimals(2)
        self.rotate_z.setSingleStep(1.0)
        rot_layout.addWidget(self.rotate_z)

        rotate_layout.addLayout(rot_layout)

        rotate_buttons = QHBoxLayout()
        rotate_buttons.addStretch()

        self.rotate_apply_btn = QPushButton("Apply")
        self.rotate_apply_btn.clicked.connect(self.on_apply_changes)
        rotate_buttons.addWidget(self.rotate_apply_btn)

        self.rotate_cancel_btn = QPushButton("Cancel")
        self.rotate_cancel_btn.clicked.connect(self.on_cancel_changes)
        rotate_buttons.addWidget(self.rotate_cancel_btn)

        rotate_layout.addLayout(rotate_buttons)
        self.rotate_controls.setVisible(False)
        transform_layout.addWidget(self.rotate_controls)

        self.quat_rotate_btn = QPushButton("Quat Rotate")
        self.quat_rotate_btn.setCheckable(True)
        self.quat_rotate_btn.clicked.connect(lambda: self.on_tool_selected("quat_rotate"))
        transform_layout.addWidget(self.quat_rotate_btn)

        self.quat_rotate_controls = QWidget()
        quat_rotate_layout = QVBoxLayout(self.quat_rotate_controls)
        quat_rotate_layout.setContentsMargins(20, 5, 5, 5)

        quat_rotate_layout.addWidget(QLabel("Rotation (Axis-Angle):"))

        quat_angle_layout = QHBoxLayout()
        quat_angle_layout.addWidget(QLabel("Angle:"))
        self.quat_angle = QDoubleSpinBox()
        self.quat_angle.setRange(-180.0, 180.0)
        self.quat_angle.setDecimals(2)
        self.quat_angle.setSingleStep(1.0)
        self.quat_angle.setValue(0.0)
        quat_angle_layout.addWidget(self.quat_angle)
        quat_rotate_layout.addLayout(quat_angle_layout)

        quat_axis_layout = QHBoxLayout()
        quat_axis_layout.addWidget(QLabel("Axis X:"))
        self.quat_axis_x = QDoubleSpinBox()
        self.quat_axis_x.setRange(-1000.0, 1000.0)
        self.quat_axis_x.setDecimals(4)
        self.quat_axis_x.setSingleStep(0.1)
        self.quat_axis_x.setValue(1.0)
        quat_axis_layout.addWidget(self.quat_axis_x)

        quat_axis_layout.addWidget(QLabel("Y:"))
        self.quat_axis_y = QDoubleSpinBox()
        self.quat_axis_y.setRange(-1000.0, 1000.0)
        self.quat_axis_y.setDecimals(4)
        self.quat_axis_y.setSingleStep(0.1)
        self.quat_axis_y.setValue(0.0)
        quat_axis_layout.addWidget(self.quat_axis_y)

        quat_axis_layout.addWidget(QLabel("Z:"))
        self.quat_axis_z = QDoubleSpinBox()
        self.quat_axis_z.setRange(-1000.0, 1000.0)
        self.quat_axis_z.setDecimals(4)
        self.quat_axis_z.setSingleStep(0.1)
        self.quat_axis_z.setValue(0.0)
        quat_axis_layout.addWidget(self.quat_axis_z)

        quat_rotate_layout.addLayout(quat_axis_layout)

        quat_rotate_buttons = QHBoxLayout()
        quat_rotate_buttons.addStretch()

        self.quat_rotate_apply_btn = QPushButton("Apply")
        self.quat_rotate_apply_btn.clicked.connect(self.on_apply_changes)
        quat_rotate_buttons.addWidget(self.quat_rotate_apply_btn)

        self.quat_rotate_cancel_btn = QPushButton("Cancel")
        self.quat_rotate_cancel_btn.clicked.connect(self.on_cancel_changes)
        quat_rotate_buttons.addWidget(self.quat_rotate_cancel_btn)

        quat_rotate_layout.addLayout(quat_rotate_buttons)
        self.quat_rotate_controls.setVisible(False)
        transform_layout.addWidget(self.quat_rotate_controls)

        self.scale_btn = QPushButton("Scale")
        self.scale_btn.setCheckable(True)
        self.scale_btn.clicked.connect(lambda: self.on_tool_selected("scale"))
        transform_layout.addWidget(self.scale_btn)

        self.scale_controls = QWidget()
        scale_layout = QVBoxLayout(self.scale_controls)
        scale_layout.setContentsMargins(20, 5, 5, 5)

        scale_layout.addWidget(QLabel("Scale:"))

        self.uniform_scale = QCheckBox("Uniform Scale")
        self.uniform_scale.stateChanged.connect(self.on_uniform_scale_changed)
        scale_layout.addWidget(self.uniform_scale)

        scale_xyz_layout = QHBoxLayout()

        scale_xyz_layout.addWidget(QLabel("X:"))
        self.scale_x = QDoubleSpinBox()
        self.scale_x.setRange(0.001, 100.0)
        self.scale_x.setDecimals(3)
        self.scale_x.setSingleStep(0.1)
        self.scale_x.setValue(1.0)
        scale_xyz_layout.addWidget(self.scale_x)

        scale_xyz_layout.addWidget(QLabel("Y:"))
        self.scale_y = QDoubleSpinBox()
        self.scale_y.setRange(0.001, 100.0)
        self.scale_y.setDecimals(3)
        self.scale_y.setSingleStep(0.1)
        self.scale_y.setValue(1.0)
        scale_xyz_layout.addWidget(self.scale_y)

        scale_xyz_layout.addWidget(QLabel("Z:"))
        self.scale_z = QDoubleSpinBox()
        self.scale_z.setRange(0.001, 100.0)
        self.scale_z.setDecimals(3)
        self.scale_z.setSingleStep(0.1)
        self.scale_z.setValue(1.0)
        scale_xyz_layout.addWidget(self.scale_z)

        scale_layout.addLayout(scale_xyz_layout)

        scale_buttons = QHBoxLayout()
        scale_buttons.addStretch()

        self.scale_apply_btn = QPushButton("Apply")
        self.scale_apply_btn.clicked.connect(self.on_apply_changes)
        scale_buttons.addWidget(self.scale_apply_btn)

        self.scale_cancel_btn = QPushButton("Cancel")
        self.scale_cancel_btn.clicked.connect(self.on_cancel_changes)
        scale_buttons.addWidget(self.scale_cancel_btn)

        scale_layout.addLayout(scale_buttons)
        self.scale_controls.setVisible(False)
        transform_layout.addWidget(self.scale_controls)

        layout.addWidget(transform_group)

        mesh_group = QGroupBox("Mesh Operations")
        mesh_layout = QVBoxLayout(mesh_group)

        subdivide_btn = QPushButton("Subdivide")
        subdivide_btn.clicked.connect(self.on_subdivide_mesh)
        mesh_layout.addWidget(subdivide_btn)

        simplify_btn = QPushButton("Simplify")
        simplify_btn.clicked.connect(self.on_simplify_mesh)
        mesh_layout.addWidget(simplify_btn)

        repair_btn = QPushButton("Repair")
        repair_btn.clicked.connect(self.on_repair_mesh)
        mesh_layout.addWidget(repair_btn)

        layout.addWidget(mesh_group)

        self.materials_group = QGroupBox("Materials")
        materials_layout = QVBoxLayout(self.materials_group)

        self.bake_color_btn = QPushButton("Bake Color")
        self.bake_color_btn.setCheckable(True)
        self.bake_color_btn.clicked.connect(self._on_bake_color_clicked)
        self.bake_color_btn.setEnabled(False)
        materials_layout.addWidget(self.bake_color_btn)

        self.baking_controls = QWidget()
        baking_layout = QVBoxLayout(self.baking_controls)
        baking_layout.setContentsMargins(20, 5, 5, 5)

        self.no_color_checkbox = QCheckBox("No color")
        baking_layout.addWidget(self.no_color_checkbox)

        baking_buttons = QHBoxLayout()
        baking_buttons.addStretch()

        self.baking_apply_btn = QPushButton("Apply")
        baking_buttons.addWidget(self.baking_apply_btn)

        self.baking_cancel_btn = QPushButton("Cancel")
        baking_buttons.addWidget(self.baking_cancel_btn)

        baking_layout.addLayout(baking_buttons)
        self.baking_controls.setVisible(False)
        materials_layout.addWidget(self.baking_controls)

        layout.addWidget(self.materials_group)

        pointcloud_group = QGroupBox("Point Cloud")
        pointcloud_layout = QVBoxLayout(pointcloud_group)

        self.pc_analyze_btn = QPushButton("Analyze Plane")
        self.pc_analyze_btn.setCheckable(True)
        self.pc_analyze_btn.clicked.connect(lambda: self._on_pointcloud_tool_clicked("pc_analyze"))
        self.pc_analyze_btn.setEnabled(False)
        pointcloud_layout.addWidget(self.pc_analyze_btn)

        self.pc_analyze_controls = QWidget()
        pc_analyze_layout = QVBoxLayout(self.pc_analyze_controls)
        pc_analyze_layout.setContentsMargins(20, 5, 5, 5)
        pc_analyze_layout.addWidget(QLabel("Analyze plane and align gravity direction"))
        pc_analyze_buttons = QHBoxLayout()
        pc_analyze_buttons.addStretch()
        self.pc_analyze_apply_btn = QPushButton("Apply")
        self.pc_analyze_apply_btn.clicked.connect(self._on_pointcloud_apply)
        pc_analyze_buttons.addWidget(self.pc_analyze_apply_btn)
        self.pc_analyze_cancel_btn = QPushButton("Cancel")
        self.pc_analyze_cancel_btn.clicked.connect(self._on_pointcloud_cancel)
        pc_analyze_buttons.addWidget(self.pc_analyze_cancel_btn)
        pc_analyze_layout.addLayout(pc_analyze_buttons)
        self.pc_analyze_controls.setVisible(False)
        pointcloud_layout.addWidget(self.pc_analyze_controls)

        self.pc_remove_btn = QPushButton("Remove Plane")
        self.pc_remove_btn.setCheckable(True)
        self.pc_remove_btn.clicked.connect(lambda: self._on_pointcloud_tool_clicked("pc_remove"))
        self.pc_remove_btn.setEnabled(False)
        pointcloud_layout.addWidget(self.pc_remove_btn)

        self.pc_remove_controls = QWidget()
        pc_remove_layout = QVBoxLayout(self.pc_remove_controls)
        pc_remove_layout.setContentsMargins(20, 5, 5, 5)
        pc_remove_layout.addWidget(QLabel("Margin:"))
        self.pc_margin_input = QDoubleSpinBox()
        self.pc_margin_input.setRange(0.01, 1.0)
        self.pc_margin_input.setSingleStep(0.01)
        self.pc_margin_input.setValue(0.05)
        self.pc_margin_input.setDecimals(3)
        pc_remove_layout.addWidget(self.pc_margin_input)
        pc_remove_layout.addWidget(QLabel("Method:"))
        self.pc_method_dbscan = QCheckBox("DBSCAN")
        self.pc_method_statistical = QCheckBox("Statistical")
        self.pc_method_dbscan.setChecked(True)
        self.pc_method_dbscan.toggled.connect(
            lambda checked: self.pc_method_statistical.setChecked(not checked) if checked else None
        )
        self.pc_method_statistical.toggled.connect(
            lambda checked: self.pc_method_dbscan.setChecked(not checked) if checked else None
        )
        pc_remove_layout.addWidget(self.pc_method_dbscan)
        pc_remove_layout.addWidget(self.pc_method_statistical)
        pc_remove_buttons = QHBoxLayout()
        pc_remove_buttons.addStretch()
        self.pc_remove_apply_btn = QPushButton("Apply")
        self.pc_remove_apply_btn.clicked.connect(self._on_pointcloud_apply)
        pc_remove_buttons.addWidget(self.pc_remove_apply_btn)
        self.pc_remove_cancel_btn = QPushButton("Cancel")
        self.pc_remove_cancel_btn.clicked.connect(self._on_pointcloud_cancel)
        pc_remove_buttons.addWidget(self.pc_remove_cancel_btn)
        pc_remove_layout.addLayout(pc_remove_buttons)
        self.pc_remove_controls.setVisible(False)
        pointcloud_layout.addWidget(self.pc_remove_controls)

        self.pc_align_btn = QPushButton("Align Clouds")
        self.pc_align_btn.setCheckable(True)
        self.pc_align_btn.clicked.connect(lambda: self._on_pointcloud_tool_clicked("pc_align"))
        self.pc_align_btn.setEnabled(False)
        pointcloud_layout.addWidget(self.pc_align_btn)

        self.pc_align_controls = QWidget()
        pc_align_layout = QVBoxLayout(self.pc_align_controls)
        pc_align_layout.setContentsMargins(20, 5, 5, 5)
        pc_align_layout.addWidget(QLabel("Align using RANSAC+ICP"))
        pc_align_buttons = QHBoxLayout()
        pc_align_buttons.addStretch()
        self.pc_align_apply_btn = QPushButton("Apply")
        self.pc_align_apply_btn.clicked.connect(self._on_pointcloud_apply)
        pc_align_buttons.addWidget(self.pc_align_apply_btn)
        self.pc_align_cancel_btn = QPushButton("Cancel")
        self.pc_align_cancel_btn.clicked.connect(self._on_pointcloud_cancel)
        pc_align_buttons.addWidget(self.pc_align_cancel_btn)
        pc_align_layout.addLayout(pc_align_buttons)
        self.pc_align_controls.setVisible(False)
        pointcloud_layout.addWidget(self.pc_align_controls)

        self.pc_merge_btn = QPushButton("Merge Clouds")
        self.pc_merge_btn.setCheckable(True)
        self.pc_merge_btn.clicked.connect(lambda: self._on_pointcloud_tool_clicked("pc_merge"))
        self.pc_merge_btn.setEnabled(False)
        pointcloud_layout.addWidget(self.pc_merge_btn)

        self.pc_merge_controls = QWidget()
        pc_merge_layout = QVBoxLayout(self.pc_merge_controls)
        pc_merge_layout.setContentsMargins(20, 5, 5, 5)
        pc_merge_layout.addWidget(QLabel("Cleaning methods:"))
        self.pc_merge_dbscan_check = QCheckBox("DBSCAN outlier removal")
        self.pc_merge_dbscan_check.setChecked(True)
        pc_merge_layout.addWidget(self.pc_merge_dbscan_check)
        self.pc_merge_sor_check = QCheckBox("Statistical outlier removal")
        self.pc_merge_sor_check.setChecked(True)
        pc_merge_layout.addWidget(self.pc_merge_sor_check)
        self.pc_merge_normal_check = QCheckBox("Normal consistency filter")
        self.pc_merge_normal_check.setChecked(True)
        pc_merge_layout.addWidget(self.pc_merge_normal_check)
        self.pc_merge_ror_check = QCheckBox("Radius outlier removal")
        self.pc_merge_ror_check.setChecked(False)
        pc_merge_layout.addWidget(self.pc_merge_ror_check)
        pc_merge_buttons = QHBoxLayout()
        pc_merge_buttons.addStretch()
        self.pc_merge_apply_btn = QPushButton("Apply")
        self.pc_merge_apply_btn.clicked.connect(self._on_pointcloud_apply)
        pc_merge_buttons.addWidget(self.pc_merge_apply_btn)
        self.pc_merge_cancel_btn = QPushButton("Cancel")
        self.pc_merge_cancel_btn.clicked.connect(self._on_pointcloud_cancel)
        pc_merge_buttons.addWidget(self.pc_merge_cancel_btn)
        pc_merge_layout.addLayout(pc_merge_buttons)
        self.pc_merge_controls.setVisible(False)
        pointcloud_layout.addWidget(self.pc_merge_controls)

        self.pc_mesh_btn = QPushButton("Generate Mesh")
        self.pc_mesh_btn.setCheckable(True)
        self.pc_mesh_btn.clicked.connect(lambda: self._on_pointcloud_tool_clicked("pc_mesh"))
        self.pc_mesh_btn.setEnabled(False)
        pointcloud_layout.addWidget(self.pc_mesh_btn)

        self.pc_mesh_controls = QWidget()
        pc_mesh_layout = QVBoxLayout(self.pc_mesh_controls)
        pc_mesh_layout.setContentsMargins(20, 5, 5, 5)

        pc_mesh_layout.addWidget(QLabel("Depth:"))
        self.pc_mesh_depth = QSpinBox()
        self.pc_mesh_depth.setRange(6, 12)
        self.pc_mesh_depth.setValue(9)
        pc_mesh_layout.addWidget(self.pc_mesh_depth)

        self.pc_mesh_fill_holes = QCheckBox("Fill holes")
        self.pc_mesh_fill_holes.setChecked(True)
        pc_mesh_layout.addWidget(self.pc_mesh_fill_holes)

        pc_mesh_layout.addWidget(QLabel("Max hole size (edges):"))
        self.pc_mesh_hole_size = QSpinBox()
        self.pc_mesh_hole_size.setRange(10, 1000)
        self.pc_mesh_hole_size.setValue(400)
        pc_mesh_layout.addWidget(self.pc_mesh_hole_size)

        pc_mesh_layout.addWidget(QLabel("Simplify to (triangles):"))
        self.pc_mesh_simplify = QSpinBox()
        self.pc_mesh_simplify.setRange(0, 10000000)
        self.pc_mesh_simplify.setValue(300000)
        self.pc_mesh_simplify.setSingleStep(10000)
        pc_mesh_layout.addWidget(self.pc_mesh_simplify)

        pc_mesh_layout.addWidget(QLabel("Smooth iterations:"))
        self.pc_mesh_smooth = QSpinBox()
        self.pc_mesh_smooth.setRange(0, 10)
        self.pc_mesh_smooth.setValue(1)
        pc_mesh_layout.addWidget(self.pc_mesh_smooth)

        self.pc_mesh_fill_holes.toggled.connect(
            lambda checked: self.pc_mesh_hole_size.setEnabled(checked)
        )
        pc_mesh_buttons = QHBoxLayout()
        pc_mesh_buttons.addStretch()
        self.pc_mesh_apply_btn = QPushButton("Apply")
        self.pc_mesh_apply_btn.clicked.connect(self._on_pointcloud_apply)
        pc_mesh_buttons.addWidget(self.pc_mesh_apply_btn)
        self.pc_mesh_cancel_btn = QPushButton("Cancel")
        self.pc_mesh_cancel_btn.clicked.connect(self._on_pointcloud_cancel)
        pc_mesh_buttons.addWidget(self.pc_mesh_cancel_btn)
        pc_mesh_layout.addLayout(pc_mesh_buttons)
        self.pc_mesh_controls.setVisible(False)
        pointcloud_layout.addWidget(self.pc_mesh_controls)

        layout.addWidget(pointcloud_group)

        layout.addStretch()

        self.tool_buttons = [self.move_btn, self.rotate_btn, self.quat_rotate_btn, self.scale_btn]

        for btn in self.tool_buttons:
            btn.setEnabled(False)

    def _setup_connections(self):
        self.move_x.valueChanged.connect(self.on_move_values_changed)
        self.move_y.valueChanged.connect(self.on_move_values_changed)
        self.move_z.valueChanged.connect(self.on_move_values_changed)

        self.quat_angle.valueChanged.connect(self.on_quat_rotate_values_changed)
        self.quat_axis_x.valueChanged.connect(self.on_quat_rotate_values_changed)
        self.quat_axis_y.valueChanged.connect(self.on_quat_rotate_values_changed)
        self.quat_axis_z.valueChanged.connect(self.on_quat_rotate_values_changed)

        self.rotate_x.valueChanged.connect(self.on_rotate_values_changed)
        self.rotate_y.valueChanged.connect(self.on_rotate_values_changed)
        self.rotate_z.valueChanged.connect(self.on_rotate_values_changed)

        self.scale_x.valueChanged.connect(self.on_scale_values_changed)
        self.scale_y.valueChanged.connect(self.on_scale_values_changed)
        self.scale_z.valueChanged.connect(self.on_scale_values_changed)

        self.baking_apply_btn.clicked.connect(self._on_baking_apply)
        self.baking_cancel_btn.clicked.connect(self._on_baking_cancel)

    def on_tool_selected(self, tool_name: str):
        if not self.selected_objects:
            self.logger.warning("No objects selected for transform")
            self._clear_tool_selection()
            return

        if self.current_tool and self.current_tool != tool_name:
            self.logger.info(f"Switching from {self.current_tool} to {tool_name} - canceling current tool")
            if self.current_tool == 'baking':
                self._clear_baking_tool_state()
            elif self.current_tool.startswith('pc_'):
                self._clear_pointcloud_tool_state()
            else:
                self.controller.cancel_changes()
                self._clear_tool_selection()

        for btn in self.tool_buttons:
            btn.setChecked(False)

        if tool_name == "move":
            self.move_btn.setChecked(True)
            self.move_controls.setVisible(True)
            self.rotate_controls.setVisible(False)
            self.quat_rotate_controls.setVisible(False)
            self.scale_controls.setVisible(False)
        elif tool_name == "rotate":
            self.rotate_btn.setChecked(True)
            self.move_controls.setVisible(False)
            self.rotate_controls.setVisible(True)
            self.quat_rotate_controls.setVisible(False)
            self.scale_controls.setVisible(False)
        elif tool_name == "quat_rotate":
            self.quat_rotate_btn.setChecked(True)
            self.move_controls.setVisible(False)
            self.rotate_controls.setVisible(False)
            self.quat_rotate_controls.setVisible(True)
            self.scale_controls.setVisible(False)
            self.quat_angle.setValue(0.0)
            self.quat_axis_x.setValue(1.0)
            self.quat_axis_y.setValue(0.0)
            self.quat_axis_z.setValue(0.0)
            self.quat_base_rotation = None
        elif tool_name == "scale":
            self.scale_btn.setChecked(True)
            self.move_controls.setVisible(False)
            self.rotate_controls.setVisible(False)
            self.quat_rotate_controls.setVisible(False)
            self.scale_controls.setVisible(True)

        self.current_tool = tool_name
        self.controller.set_active_tool(tool_name, self.selected_objects)

    def _clear_tool_selection(self):
        for btn in self.tool_buttons:
            btn.setChecked(False)

        self.move_controls.setVisible(False)
        self.rotate_controls.setVisible(False)
        self.quat_rotate_controls.setVisible(False)
        self.scale_controls.setVisible(False)

        self.uniform_scale.setChecked(False)

        self.current_tool = None

    def _on_bake_color_clicked(self):
        if not self.selected_objects:
            self.logger.warning("No objects selected for baking")
            self.bake_color_btn.setChecked(False)
            return

        if self.current_tool and self.current_tool != 'baking':
            if self.current_tool in ['move', 'rotate', 'scale']:
                self.controller.cancel_changes()
                self._clear_tool_selection()
            elif self.current_tool.startswith('pc_'):
                self._clear_pointcloud_tool_state()

        self.current_tool = 'baking'
        self.bake_color_btn.setChecked(True)
        self.baking_controls.setVisible(True)

    def _on_baking_apply(self):
        if self.current_tool != 'baking':
            return

        if not self.selected_objects:
            return

        no_color = self.no_color_checkbox.isChecked()
        object_names = self.selected_objects.copy()

        if self.signal_router:
            self.signal_router.emit('scene.do_baking', {
                'object_names': object_names,
                'no_color': no_color
            })

        self.baking_apply_btn.setEnabled(False)

    def _on_baking_cancel(self):
        self._clear_baking_tool_state()

    def on_done_baking(self, data):
        self._clear_baking_tool_state()

    def _clear_baking_tool_state(self):
        self.current_tool = None
        self.bake_color_btn.setChecked(False)
        self.baking_controls.setVisible(False)
        self.no_color_checkbox.setChecked(False)
        self.baking_apply_btn.setEnabled(True)

    def _on_pointcloud_tool_clicked(self, tool_name: str):
        if not self.selected_objects:
            self.logger.warning(f"No objects selected for {tool_name}")
            self._clear_pointcloud_tool_state()
            return

        if self.current_tool and self.current_tool != tool_name:
            self.logger.info(f"Switching from {self.current_tool} to {tool_name}")
            if self.current_tool == 'baking':
                self._clear_baking_tool_state()
            elif self.current_tool.startswith('pc_'):
                self._clear_pointcloud_tool_state()
            else:
                self.controller.cancel_changes()
                self._clear_tool_selection()

        self.pc_analyze_btn.setChecked(False)
        self.pc_remove_btn.setChecked(False)
        self.pc_align_btn.setChecked(False)
        self.pc_merge_btn.setChecked(False)
        self.pc_mesh_btn.setChecked(False)

        self.pc_analyze_controls.setVisible(False)
        self.pc_remove_controls.setVisible(False)
        self.pc_align_controls.setVisible(False)
        self.pc_merge_controls.setVisible(False)
        self.pc_mesh_controls.setVisible(False)

        if tool_name == "pc_analyze":
            self.pc_analyze_btn.setChecked(True)
            self.pc_analyze_controls.setVisible(True)
        elif tool_name == "pc_remove":
            self.pc_remove_btn.setChecked(True)
            self.pc_remove_controls.setVisible(True)
            if self.selected_objects:
                self.signal_router.emit('pointcloud.do_remove_plane_preview', {
                    'object_name': self.selected_objects[0]
                })
        elif tool_name == "pc_align":
            self.pc_align_btn.setChecked(True)
            self.pc_align_controls.setVisible(True)
        elif tool_name == "pc_merge":
            self.pc_merge_btn.setChecked(True)
            self.pc_merge_controls.setVisible(True)
        elif tool_name == "pc_mesh":
            self.pc_mesh_btn.setChecked(True)
            self.pc_mesh_controls.setVisible(True)

        self.current_tool = tool_name

    def _on_pointcloud_apply(self):
        if not self.current_tool or not self.current_tool.startswith('pc_'):
            return

        tool = self.current_tool

        if tool == "pc_analyze":
            if self.selected_objects:
                self.signal_router.emit('pointcloud.do_analyze_plane', {
                    'object_name': self.selected_objects[0]
                })
        elif tool == "pc_remove":
            if self.selected_objects:
                method = 'dbscan' if self.pc_method_dbscan.isChecked() else 'statistical'
                self.signal_router.emit('pointcloud.do_remove_plane', {
                    'object_name': self.selected_objects[0],
                    'margin': self.pc_margin_input.value(),
                    'method': method
                })
        elif tool == "pc_align":
            if len(self.selected_objects) >= 2:
                self.signal_router.emit('pointcloud.do_align_clouds', {
                    'source_object': self.selected_objects[0],
                    'target_object': self.selected_objects[1]
                })
        elif tool == "pc_merge":
            if len(self.selected_objects) >= 2:
                self.signal_router.emit('pointcloud.do_merge_clouds', {
                    'source_object': self.selected_objects[0],
                    'target_object': self.selected_objects[1],
                    'cleaning_params': {
                        'dbscan': self.pc_merge_dbscan_check.isChecked(),
                        'sor': self.pc_merge_sor_check.isChecked(),
                        'normal': self.pc_merge_normal_check.isChecked(),
                        'ror': self.pc_merge_ror_check.isChecked()
                    }
                })
        elif tool == "pc_mesh":
            if self.selected_objects:
                self.signal_router.emit('pointcloud.do_generate_mesh', {
                    'object_name': self.selected_objects[0],
                    'mesh_params': {
                        'depth': self.pc_mesh_depth.value(),
                        'fill_holes': self.pc_mesh_fill_holes.isChecked(),
                        'hole_size': self.pc_mesh_hole_size.value(),
                        'simplify_target': self.pc_mesh_simplify.value(),
                        'smooth_iterations': self.pc_mesh_smooth.value()
                    }
                })

    def _on_pointcloud_cancel(self):
        self._clear_pointcloud_tool_state()

    def _clear_pointcloud_tool_state(self):
        self.current_tool = None
        self.pc_analyze_btn.setChecked(False)
        self.pc_remove_btn.setChecked(False)
        self.pc_align_btn.setChecked(False)
        self.pc_merge_btn.setChecked(False)
        self.pc_mesh_btn.setChecked(False)
        self.pc_analyze_controls.setVisible(False)
        self.pc_remove_controls.setVisible(False)
        self.pc_align_controls.setVisible(False)
        self.pc_merge_controls.setVisible(False)
        self.pc_mesh_controls.setVisible(False)

    def on_move_values_changed(self):
        if self.current_tool == "move":
            position = [self.move_x.value(), self.move_y.value(), self.move_z.value()]
            self.controller.preview_move(position)

    def on_rotate_values_changed(self):
        if self.current_tool == "rotate":
            rotation = [self.rotate_x.value(), self.rotate_y.value(), self.rotate_z.value()]
            self.controller.preview_rotate(rotation)

    def on_quat_rotate_values_changed(self):
        if self.current_tool == "quat_rotate":
            if self.quat_base_rotation is None:
                return

            angle_deg = self.quat_angle.value()
            axis_x = self.quat_axis_x.value()
            axis_y = self.quat_axis_y.value()
            axis_z = self.quat_axis_z.value()

            delta_euler = self._axis_angle_to_euler(angle_deg, axis_x, axis_y, axis_z)
            final_euler = self._apply_delta_rotation(self.quat_base_rotation, delta_euler)

            rotation_deg = [np.degrees(final_euler[0]), np.degrees(final_euler[1]), np.degrees(final_euler[2])]
            self.controller.preview_rotate(rotation_deg)

    def _normalize_angle(self, angle_deg):
        return ((angle_deg + 180.0) % 360.0) - 180.0

    def _axis_angle_to_euler(self, angle_deg, axis_x, axis_y, axis_z):
        angle_deg = self._normalize_angle(angle_deg)

        axis = np.array([axis_x, axis_y, axis_z], dtype=float)
        norm = np.linalg.norm(axis)

        if norm < 1e-6:
            axis = np.array([1.0, 0.0, 0.0])
        else:
            axis = axis / norm

        theta_rad = np.radians(angle_deg)
        half_theta = theta_rad / 2.0

        w = np.cos(half_theta)
        x = axis[0] * np.sin(half_theta)
        y = axis[1] * np.sin(half_theta)
        z = axis[2] * np.sin(half_theta)

        quat = [x, y, z, w]
        r = Rotation.from_quat(quat)
        euler = r.as_euler('xyz', degrees=False)

        return euler

    def _apply_delta_rotation(self, base_euler, delta_euler):
        base_quat = Rotation.from_euler('xyz', base_euler, degrees=False)
        delta_quat = Rotation.from_euler('xyz', delta_euler, degrees=False)

        final_quat = base_quat * delta_quat
        final_euler = final_quat.as_euler('xyz', degrees=False)

        return final_euler

    def on_scale_values_changed(self):
        if self.current_tool == "scale":
            uniform = self.uniform_scale.isChecked()

            if uniform:
                values = [self.scale_x.value(), self.scale_y.value(), self.scale_z.value()]
                unique = set(values)

                if len(unique) == 2:
                    for v in values:
                        if values.count(v) == 1:
                            chosen = v
                            break
                else:
                    chosen = max(values)

                self.scale_x.blockSignals(True)
                self.scale_y.blockSignals(True)
                self.scale_z.blockSignals(True)

                self.scale_x.setValue(chosen)
                self.scale_y.setValue(chosen)
                self.scale_z.setValue(chosen)

                self.scale_x.blockSignals(False)
                self.scale_y.blockSignals(False)
                self.scale_z.blockSignals(False)

                scale = [chosen, chosen, chosen]
            else:
                scale = [self.scale_x.value(), self.scale_y.value(), self.scale_z.value()]

            self.controller.preview_scale(scale, uniform)

    def on_uniform_scale_changed(self, state):
        if state == Qt.CheckState.Checked.value:
            self.on_scale_values_changed()

    def on_apply_changes(self):
        if self.current_tool:
            self.controller.apply_changes()
            self._clear_tool_selection()

    def on_cancel_changes(self):
        if self.current_tool:
            self.controller.cancel_changes()
            self._clear_tool_selection()

    def update_tool_values(self, tool_type: str, current_values: dict):
        if not current_values or tool_type != self.current_tool:
            return

        first_obj_name = list(current_values.keys())[0]
        values = current_values[first_obj_name]

        if tool_type == "move" and 'location' in values:
            location = values['location']
            self.move_x.setValue(location[0])
            self.move_y.setValue(location[1])
            self.move_z.setValue(location[2])
        elif tool_type == "rotate" and 'rotation' in values:
            rotation = values['rotation']
            self.rotate_x.setValue(rotation[0])
            self.rotate_y.setValue(rotation[1])
            self.rotate_z.setValue(rotation[2])
        elif tool_type == "quat_rotate" and 'rotation' in values:
            rotation = values['rotation']
            self.quat_base_rotation = [
                np.radians(rotation[0]),
                np.radians(rotation[1]),
                np.radians(rotation[2])
            ]
        elif tool_type == "scale" and 'scale' in values:
            scale = values['scale']
            self.scale_x.setValue(scale[0])
            self.scale_y.setValue(scale[1])
            self.scale_z.setValue(scale[2])

    def update_selection(self, selected_names: list):
        self.selected_objects = selected_names

        has_selection = len(selected_names) > 0
        for btn in self.tool_buttons:
            btn.setEnabled(has_selection)

        self.bake_color_btn.setEnabled(has_selection)

        count = len(selected_names)
        if count == 1:
            self.pc_analyze_btn.setEnabled(True)
            self.pc_remove_btn.setEnabled(True)
            self.pc_mesh_btn.setEnabled(True)
            self.pc_align_btn.setEnabled(False)
            self.pc_merge_btn.setEnabled(False)
        elif count == 2:
            self.pc_analyze_btn.setEnabled(False)
            self.pc_remove_btn.setEnabled(False)
            self.pc_mesh_btn.setEnabled(False)
            self.pc_align_btn.setEnabled(True)
            self.pc_merge_btn.setEnabled(True)
        else:
            self.pc_analyze_btn.setEnabled(False)
            self.pc_remove_btn.setEnabled(False)
            self.pc_align_btn.setEnabled(False)
            self.pc_merge_btn.setEnabled(False)
            self.pc_mesh_btn.setEnabled(False)

        if not has_selection and self.current_tool:
            if self.current_tool == 'baking':
                self._clear_baking_tool_state()
            elif self.current_tool.startswith('pc_'):
                self._clear_pointcloud_tool_state()
            else:
                self._clear_tool_selection()

    def on_subdivide_mesh(self):
        self.controller.subdivide_mesh()
        self.logger.info("Subdivide mesh operation requested")

    def on_simplify_mesh(self):
        self.controller.simplify_mesh()
        self.logger.info("Simplify mesh operation requested")

    def on_repair_mesh(self):
        self.controller.repair_mesh()
        self.logger.info("Repair mesh operation requested")

    def get_current_tool(self) -> str:
        return self.current_tool

    def cleanup(self):
        if self.controller:
            self.controller.cleanup()