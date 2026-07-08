# core/base_ops.py
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject
from core.executor import Executor
from core.coredata import get_scene_manager
from logger import get_logger
import numpy as np
import math


class BaseopsAPI(QObject, Executor):

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.scene_manager = get_scene_manager()
        self.current_tool = None
        self.preview_objects = []
        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("Baseops API initialized")

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('baseops.do_undo', self.do_undo, 'BaseopsAPI')
            self.signal_router.subscribe('baseops.do_redo', self.do_redo, 'BaseopsAPI')
            self.signal_router.subscribe('transform.tool_activated', self.do_tool_activated, 'BaseopsAPI')
            self.signal_router.subscribe('transform.preview_move', self.do_preview_move, 'BaseopsAPI')
            self.signal_router.subscribe('transform.preview_rotate', self.do_preview_rotate, 'BaseopsAPI')
            self.signal_router.subscribe('transform.preview_scale', self.do_preview_scale, 'BaseopsAPI')
            self.signal_router.subscribe('transform.apply_changes', self.do_apply_changes, 'BaseopsAPI')
            self.signal_router.subscribe('transform.cancel_changes', self.do_cancel_changes, 'BaseopsAPI')
            self.signal_router.subscribe('transform.apply_transform', self.do_apply_transform, 'BaseopsAPI')

    def do_undo(self, data: Dict[str, Any]):
        pass

    def do_redo(self, data: Dict[str, Any]):
        pass

    def do_tool_activated(self, data: Dict[str, Any]):
        tool_type = data.get('tool_type', '')
        selected_objects = data.get('selected_objects', [])

        self.logger.info(f"Activating transform tool: {tool_type}")

        if self.current_tool and self.preview_objects:
            self._cancel_current_tool()

        self.current_tool = tool_type
        self.preview_objects = selected_objects.copy()

        current_values = {}

        for obj_name in selected_objects:
            obj = self.scene_manager.get_object(obj_name)
            if obj:
                obj._create_snapshot()

                current_values[obj_name] = {
                    'location': obj.location.tolist(),
                    'rotation': [math.degrees(r) for r in obj.rotation.tolist()],
                    'scale': obj.scale.tolist()
                }

        if self.signal_router:
            self.signal_router.emit('transform.tool_ready', {
                'tool_type': tool_type,
                'current_values': current_values
            })

        self.logger.info(f"Tool {tool_type} ready for {len(selected_objects)} objects")

    def do_preview_move(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])
        position = data.get('position', [0, 0, 0])

        self.logger.debug(f"Preview move: {object_names} to {position}")

        for obj_name in object_names:
            obj = self.scene_manager.get_object(obj_name)
            if obj and obj.is_in_preview_mode:
                obj.update_transform(location=np.array(position, dtype=float))

        self._emit_render_update()

    def do_preview_rotate(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])
        rotation = data.get('rotation', [0, 0, 0])

        rotation_rad = [math.radians(r) for r in rotation]

        self.logger.debug(f"Preview rotate: {object_names} to {rotation}")

        for obj_name in object_names:
            obj = self.scene_manager.get_object(obj_name)
            if obj and obj.is_in_preview_mode:
                obj.update_transform(rotation=np.array(rotation_rad, dtype=float))

        self._emit_render_update()

    def do_preview_scale(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])
        scale = data.get('scale', [1, 1, 1])
        uniform = data.get('uniform', False)

        if uniform and len(scale) > 0:
            uniform_scale = scale[0]
            scale = [uniform_scale, uniform_scale, uniform_scale]

        self.logger.debug(f"Preview scale: {object_names} to {scale}")

        for obj_name in object_names:
            obj = self.scene_manager.get_object(obj_name)
            if obj and obj.is_in_preview_mode:
                obj.update_transform(scale=np.array(scale, dtype=float))

        self._emit_render_update()

    def do_apply_changes(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])

        if not self.current_tool or not self.preview_objects:
            return

        self.logger.info(f"Applying {self.current_tool} changes to {len(object_names)} objects")

        script = self._generate_transform_script()

        def callback(success, result, **kwargs):
            if success:
                self.logger.info(f"Transform {self.current_tool} applied successfully")
                self._clear_tool_state()

                if self.signal_router:
                    self.signal_router.emit('scene.request_sync', {})
            else:
                self.logger.error(f"Transform {self.current_tool} failed: {result.get('error', 'Unknown error')}")

        self.exec_blender_python(script, callback)

    def do_cancel_changes(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])

        if not self.current_tool or not self.preview_objects:
            return

        self.logger.info(f"Canceling {self.current_tool} changes")

        self._cancel_current_tool()

        if self.signal_router:
            self.signal_router.emit('scene.request_sync', {})

    def do_apply_transform(self, data: Dict[str, Any]):
        object_name = data.get('object_name')
        location = data.get('location')
        rotation = data.get('rotation')
        scale = data.get('scale')

        obj = self.scene_manager.get_object(object_name)
        if obj is None:
            self.signal_router.emit('transform.done_apply_transform', {
                'success': False,
                'object_name': object_name,
                'error': f'Object not found: {object_name}'
            })
            return

        self.logger.info(f"Applying transform to {object_name}")

        object_transforms = [{
            'name': object_name,
            'location': location,
            'rotation': rotation,
            'scale': scale
        }]
        script = self._generate_transform_script(object_transforms)

        def callback(success, result, **kwargs):
            if success:
                obj.location = np.array(location, dtype=float)
                obj.rotation = np.array(rotation, dtype=float)
                obj.scale = np.array(scale, dtype=float)

                self.signal_router.emit('scene.request_sync', {})

                self.signal_router.emit('transform.done_apply_transform', {
                    'success': True,
                    'object_name': object_name,
                    'error': ''
                })
            else:
                error_msg = result.get('error', 'Unknown error')
                self.logger.error(f"Transform apply failed for {object_name}: {error_msg}")

                self.signal_router.emit('transform.done_apply_transform', {
                    'success': False,
                    'object_name': object_name,
                    'error': error_msg
                })

        self.exec_blender_python(script, callback)

    def _generate_transform_script(self, object_transforms=None) -> str:
        script_lines = ["import bpy", ""]

        if object_transforms is None:
            if not self.current_tool or not self.preview_objects:
                return ""

            for obj_name in self.preview_objects:
                obj = self.scene_manager.get_object(obj_name)
                if not obj or not obj.is_in_preview_mode:
                    continue

                location = obj.location.tolist()
                rotation = obj.rotation.tolist()
                scale = obj.scale.tolist()

                script_lines.extend([
                    f"obj = bpy.context.scene.objects.get('{obj_name}')",
                    f"if obj:",
                    f"    obj.location = {location}",
                    f"    obj.rotation_euler = {rotation}",
                    f"    obj.scale = {scale}",
                    f"    print(f'Updated {{obj.name}}: loc={location}, rot={rotation}, scale={scale}')",
                    ""
                ])
        else:
            for obj_data in object_transforms:
                obj_name = obj_data['name']
                location = obj_data['location']
                rotation = obj_data['rotation']
                scale = obj_data['scale']

                script_lines.extend([
                    f"obj = bpy.context.scene.objects.get('{obj_name}')",
                    f"if obj:",
                    f"    obj.location = {location}",
                    f"    obj.rotation_euler = {rotation}",
                    f"    obj.scale = {scale}",
                    f"    print(f'Applied transform to {{obj.name}}')",
                    ""
                ])

        script_lines.append("print('Transform operation completed')")
        return "\n".join(script_lines)

    def _cancel_current_tool(self):
        for obj_name in self.preview_objects:
            obj = self.scene_manager.get_object(obj_name)
            if obj and obj.is_in_preview_mode:
                obj.cancel_changes()

        self._clear_tool_state()
        self._emit_render_update()

    def _clear_tool_state(self):
        for obj_name in self.preview_objects:
            obj = self.scene_manager.get_object(obj_name)
            if obj and obj.is_in_preview_mode:
                obj.apply_changes()

        self.current_tool = None
        self.preview_objects = []

    def _emit_render_update(self):
        if self.signal_router:
            render_data = self._get_render_data()
            self.signal_router.emit('scene.render_data_updated', {
                'render_data': render_data
            })

    def _get_render_data(self) -> Dict[str, Any]:
        render_objects = []
        selected_names = []

        for obj in self.scene_manager.get_all_objects().values():
            obj_data = {
                'name': obj.name,
                'type': obj.type.value,
                'location': obj.location.tolist(),
                'rotation': obj.rotation.tolist(),
                'scale': obj.scale.tolist(),
                'selected': obj.selected,
                'dirty_state': obj.dirty_state.value
            }

            if obj.has_mesh and obj.mesh_data:
                obj_data['vertices'] = obj.mesh_data.vertices.tolist()
                obj_data['faces'] = obj.mesh_data.faces.copy()

                if obj.mesh_data.vertex_colors is not None:
                    obj_data['vertex_colors'] = obj.mesh_data.vertex_colors.tolist()

            render_objects.append(obj_data)

            if obj.selected:
                selected_names.append(obj.name)

        return {
            'objects': render_objects,
            'selected_objects': selected_names
        }

    def move_object(self, object_id: str, delta: tuple) -> bool:
        pass

    def rotate_object(self, object_id: str, rotation: tuple) -> bool:
        pass

    def scale_object(self, object_id: str, scale: tuple) -> bool:
        pass

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('BaseopsAPI')