# core/scene.py
from PySide6.QtCore import QObject
from core.coredata import (SceneObject, SelectionData, SelectionMode, ObjectType, MeshData,
                          create_mesh_object, get_scene_manager, DirtyState)
from core.executor import Executor
from logger import get_logger
from typing import Dict, List, Optional, Set, Any
import time
import json
import msgpack
import base64
import numpy as np

class SceneManager(QObject, Executor):

    def __init__(self, signal_router=None, worker=None, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.worker = worker
        self.logger = get_logger()

        self.scene_manager = get_scene_manager()
        self.selection_mode: SelectionMode = SelectionMode.OBJECT

        self.USE_OPTIMIZED_FORMAT = True
        self.USE_POINTCLOUD_SAMPLING = True
        self.MAX_POINTCLOUD_VERTICES = 100000
        self.POINTCLOUD_DETECTION_THRESHOLD = 0.1
        self.COORDINATE_SCALE_FACTOR = 1.0

        self.sampling_stats = {}

        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('scene.do_add_object', self.do_add_object, 'SceneManager')
            self.signal_router.subscribe('scene.do_remove_object', self.do_remove_object, 'SceneManager')
            self.signal_router.subscribe('scene.do_select_object', self.do_select_object, 'SceneManager')
            self.signal_router.subscribe('scene.do_clear_selection', self.do_clear_selection, 'SceneManager')
            self.signal_router.subscribe('scene.do_select_all', self.do_select_all, 'SceneManager')
            self.signal_router.subscribe('scene.do_clear_scene', self.do_clear_scene, 'SceneManager')
            self.signal_router.subscribe('scene.object_modified', self.do_object_modified, 'SceneManager')
            self.signal_router.subscribe('scene.add_primitive', self.do_add_primitive, 'SceneManager')
            self.signal_router.subscribe('scene.request_sync', self.do_request_sync, 'SceneManager')
            self.signal_router.subscribe('scene.do_baking', self.do_baking, 'SceneManager')

    def do_request_sync(self, data: Dict[str, Any]):
        async def sync_scene():
            await self._sync_scene()

        import asyncio
        asyncio.create_task(sync_scene())

    def do_add_object(self, data: Dict[str, Any]):
        pass

    def do_remove_object(self, data: Dict[str, Any]):
        selected_names = self.scene_manager.get_selected_names()

        if not selected_names:
            self.logger.info("No objects selected for deletion")
            return

        self.logger.info(f"Deleting objects: {selected_names}")

        script = f"""
import bpy

deleted_objects = []
selected_names = {selected_names}

for name in selected_names:
    if name in bpy.data.objects:
        obj = bpy.data.objects[name]
        bpy.data.objects.remove(obj, do_unlink=True)
        deleted_objects.append(name)

if deleted_objects:
    bpy.context.view_layer.update()
    print(f"Deleted objects: {{', '.join(deleted_objects)}}")
else:
    print("No objects found to delete")
"""

        def callback(success, result, **kwargs):
            if success:
                self.logger.info(f"Deleted objects: {kwargs.get('selected_names', [])}")
            else:
                self.logger.error(f"Failed to delete objects: {result.get('error', 'Unknown error')}")

            if self.signal_router:
                self.signal_router.emit('scene.request_sync', {})

        self.exec_blender_python(script, callback, selected_names=selected_names)

    def do_select_object(self, data: Dict[str, Any]):
        object_name = data.get('object_name', '')
        extend = data.get('extend', False)

        success = self.scene_manager.select_object(object_name, extend)

        if success:
            self._emit_render_update()

        self._emit_selection_changed(success)

    def do_clear_selection(self, data: Dict[str, Any]):
        self.scene_manager.clear_all_selections()
        self._emit_render_update()
        self._emit_selection_changed(True)

    def do_select_all(self, data: Dict[str, Any]):
        self.scene_manager.select_all()
        self._emit_render_update()
        self._emit_selection_changed(True)

    def do_clear_scene(self, data: Dict[str, Any]):
        self.scene_manager.objects.clear()
        self._emit_render_update()
        self._emit_selection_changed(True)

    def do_object_modified(self, data: Dict[str, Any]):
        pass

    def _generate_primitive_script(self, primitive_type: str, params: Dict = None) -> str:
        if params is None:
            params = {}

        location = params.get('location', [0, 0, 0])

        primitive_ops = {
            'cube': 'bpy.ops.mesh.primitive_cube_add',
            'sphere': 'bpy.ops.mesh.primitive_uv_sphere_add',
            'cylinder': 'bpy.ops.mesh.primitive_cylinder_add',
            'cone': 'bpy.ops.mesh.primitive_cone_add',
            'torus': 'bpy.ops.mesh.primitive_torus_add',
            'monkey': 'bpy.ops.mesh.primitive_monkey_add'
        }

        blender_op = primitive_ops.get(primitive_type)
        if not blender_op:
            return ""

        script = f"""
import bpy

bpy.ops.object.select_all(action='DESELECT')

objects_before = len(bpy.context.scene.objects)

{blender_op}(location=({location[0]}, {location[1]}, {location[2]}))

objects_after = len(bpy.context.scene.objects)

if objects_after > objects_before:
    new_obj = bpy.context.scene.objects[-1]
    print(f"Created {{new_obj.type}} object: {{new_obj.name}}")
else:
    print("Failed to create object")
    exit(1)
"""
        return script

    def do_add_primitive(self, data: Dict[str, Any]):
        primitive_type = data.get('type', '')
        params = data.get('params', {})

        self.logger.info(f"Adding primitive: {primitive_type}")

        script = self._generate_primitive_script(primitive_type, params)

        if not script:
            self.logger.error(f"Unknown primitive type: {primitive_type}")
            return

        def callback(success, result, **kwargs):
            if success:
                self.logger.info(f"Created primitive: {kwargs.get('primitive_type', '')}")
            else:
                self.logger.error(f"Failed to create primitive: {result.get('error', 'Unknown error')}")

            if self.signal_router:
                self.signal_router.emit('scene.request_sync', {})

        self.exec_blender_python(script, callback, primitive_type=primitive_type)

    def _emit_selection_changed(self, success: bool):
        if not self.signal_router:
            return

        all_objects = []

        for obj in self.scene_manager.get_all_objects().values():
            obj_info = {
                'name': obj.name,
                'type': obj.type.value,
                'selected': obj.selected
            }
            all_objects.append(obj_info)

        self.signal_router.emit('scene.done_selection_changed', {
            'all_objects': all_objects
        })

    def _emit_render_update(self):
        if self.signal_router:
            render_data = self.to_render()
            self.signal_router.emit('scene.render_data_updated', {
                'render_data': render_data
            })

    def to_render(self) -> Dict[str, Any]:
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

    def _generate_optimized_script(self) -> str:
        max_vertices = self.MAX_POINTCLOUD_VERTICES

        script = f"""
import bpy
import json
import msgpack
import base64
import numpy as np

SIZE_THRESHOLD = 999999999
MAX_POINTCLOUD_VERTICES = {max_vertices}

def is_point_cloud(mesh):
    return len(mesh.polygons) == 0

def classify_mesh_type(vertex_count, face_count):
    if face_count == 0:
        return "POINT_CLOUD"

    face_vertex_ratio = face_count / vertex_count if vertex_count > 0 else 0

    if face_vertex_ratio < 0.1:
        return "POINT_CLOUD"
    elif vertex_count > 1000000 and face_vertex_ratio < 0.5:
        return "DENSE_POINT_CLOUD"
    else:
        return "REGULAR_MESH"

def should_sample_object(obj_type, vertex_count):
    if obj_type in ["POINT_CLOUD", "DENSE_POINT_CLOUD"]:
        return vertex_count > MAX_POINTCLOUD_VERTICES
    return False

def uniform_sampling_indices(vertex_count, target_count):
    if vertex_count <= target_count:
        return list(range(vertex_count))

    step = vertex_count // target_count
    indices = list(range(0, vertex_count, step))
    return indices[:target_count]

def detect_coordinate_range(vertices):
    if not vertices:
        return 1.0

    coords_array = np.array(vertices)
    max_coord = np.max(np.abs(coords_array))

    if max_coord > 65000:
        return 65000.0 / max_coord
    return 1.0

def convert_vertices_sampled(mesh, indices, scale_factor):
    vertex_count = len(indices)
    vertices = np.zeros((vertex_count, 3), dtype=np.float32)

    for i, idx in enumerate(indices):
        v = mesh.vertices[idx]
        vertices[i] = [v.co.x * scale_factor, v.co.y * scale_factor, v.co.z * scale_factor]

    return vertices.astype(np.float16)

def convert_colors_sampled(mesh, indices):
    vertex_count = len(indices)
    vertex_colors = None

    if hasattr(mesh, 'color_attributes') and mesh.color_attributes:
        active_color_attr = mesh.color_attributes.active_color
        if active_color_attr and active_color_attr.domain == 'POINT':
            colors = np.zeros((vertex_count, 3), dtype=np.uint8)
            for i, idx in enumerate(indices):
                color = active_color_attr.data[idx].color
                colors[i] = [
                    int(color[0] * 255),
                    int(color[1] * 255),
                    int(color[2] * 255)
                ]
            vertex_colors = colors

    elif hasattr(mesh, 'vertex_colors') and mesh.vertex_colors:
        active_vc = mesh.vertex_colors.active
        if active_vc:
            colors = np.zeros((vertex_count, 3), dtype=np.uint8)
            for i, idx in enumerate(indices):
                if idx < len(active_vc.data):
                    color = active_vc.data[idx].color
                    colors[i] = [
                        int(color[0] * 255),
                        int(color[1] * 255),
                        int(color[2] * 255)
                    ]
            vertex_colors = colors

    return vertex_colors

def convert_vertices_optimized(mesh, scale_factor):
    vertex_count = len(mesh.vertices)
    vertices = np.zeros((vertex_count, 3), dtype=np.float32)

    for i, v in enumerate(mesh.vertices):
        vertices[i] = [v.co.x * scale_factor, v.co.y * scale_factor, v.co.z * scale_factor]

    return vertices.astype(np.float16)

def convert_colors_optimized(mesh, vertex_count):
    vertex_colors = None

    if hasattr(mesh, 'color_attributes') and mesh.color_attributes:
        active_color_attr = mesh.color_attributes.active_color
        if active_color_attr and active_color_attr.domain == 'POINT':
            colors = np.zeros((vertex_count, 3), dtype=np.uint8)
            for i in range(vertex_count):
                color = active_color_attr.data[i].color
                colors[i] = [
                    int(color[0] * 255),
                    int(color[1] * 255),
                    int(color[2] * 255)
                ]
            vertex_colors = colors

    elif hasattr(mesh, 'vertex_colors') and mesh.vertex_colors:
        active_vc = mesh.vertex_colors.active
        if active_vc:
            colors = np.zeros((vertex_count, 3), dtype=np.uint8)
            for i in range(vertex_count):
                if i < len(active_vc.data):
                    color = active_vc.data[i].color
                    colors[i] = [
                        int(color[0] * 255),
                        int(color[1] * 255),
                        int(color[2] * 255)
                    ]
            vertex_colors = colors

    return vertex_colors

def estimate_data_size(scene_data):
    total_size = 0
    for obj_data in scene_data.get('objects', []):
        if 'mesh' in obj_data:
            mesh = obj_data['mesh']

            if 'format_version' in mesh and 'optimized' in mesh['format_version']:
                vertex_count = mesh.get('vertex_count', 0)
                total_size += vertex_count * 6
                total_size += vertex_count * 3
            else:
                vertices = mesh.get('vertices', [])
                faces = mesh.get('faces', [])
                colors = mesh.get('vertex_colors', [])
                total_size += len(vertices) * 12
                total_size += len(faces) * 12
                total_size += len(colors) * 4

    return total_size

scene_data = {{
    'objects': []
}}

for obj in bpy.context.scene.objects:
    if obj.type not in ['MESH', 'EMPTY']:
        continue

    obj_data = {{
        'name': obj.name,
        'type': obj.type,
        'location': list(obj.location),
        'rotation': list(obj.rotation_euler),
        'scale': list(obj.scale),
        'selected': False,
        'client_source_directory': obj.get("client_source_directory", "")
    }}

    if obj.type == 'MESH' and obj.data:
        mesh = obj.data
        vertex_count = len(mesh.vertices)
        face_count = len(mesh.polygons)

        if vertex_count > 0:
            obj_type = classify_mesh_type(vertex_count, face_count)

            if should_sample_object(obj_type, vertex_count):
                print(f"Processing {{obj_type}}: {{obj.name}} with {{vertex_count:,}} vertices")

                indices = uniform_sampling_indices(vertex_count, MAX_POINTCLOUD_VERTICES)
                sampled_count = len(indices)

                print(f"Sampled {{sampled_count:,}} points (step: every {{vertex_count // sampled_count}} vertices)")

                temp_vertices = [[mesh.vertices[i].co.x, mesh.vertices[i].co.y, mesh.vertices[i].co.z] for i in indices[:1000]]
                scale_factor = detect_coordinate_range(temp_vertices)

                vertices_f16 = convert_vertices_sampled(mesh, indices, scale_factor)
                colors_u8 = convert_colors_sampled(mesh, indices)

                obj_data['mesh'] = {{
                    'format_version': 'v3_sampled_optimized',
                    'original_vertex_count': vertex_count,
                    'vertex_count': sampled_count,
                    'coordinate_scale': scale_factor,
                    'sampling_step': vertex_count // sampled_count,
                    'vertices_f16': base64.b64encode(vertices_f16.tobytes()).decode('ascii'),
                    'faces': []
                }}

                if colors_u8 is not None:
                    obj_data['mesh']['colors_u8'] = base64.b64encode(colors_u8.tobytes()).decode('ascii')
                    print(f"Encoded {{sampled_count:,}} vertex colors")

            elif obj_type == "REGULAR_MESH":
                print(f"Processing regular mesh: {{obj.name}} with {{vertex_count:,}} vertices, {{face_count:,}} faces")

                temp_vertices = [[v.co.x, v.co.y, v.co.z] for v in mesh.vertices[:1000]]
                scale_factor = detect_coordinate_range(temp_vertices)

                vertices_f16 = convert_vertices_optimized(mesh, scale_factor)
                colors_u8 = convert_colors_optimized(mesh, vertex_count)

                faces = []
                for poly in mesh.polygons:
                    faces.append(list(poly.vertices))

                obj_data['mesh'] = {{
                    'format_version': 'v2_optimized',
                    'vertex_count': vertex_count,
                    'face_count': len(faces),
                    'coordinate_scale': scale_factor,
                    'vertices_f16': base64.b64encode(vertices_f16.tobytes()).decode('ascii'),
                    'faces': faces
                }}

                if colors_u8 is not None:
                    obj_data['mesh']['colors_u8'] = base64.b64encode(colors_u8.tobytes()).decode('ascii')

    scene_data['objects'].append(obj_data)

estimated_size = estimate_data_size(scene_data)
use_msgpack = estimated_size > SIZE_THRESHOLD

print(f"Total estimated size: {{estimated_size:,}} bytes")

if use_msgpack:
    result = msgpack.packb(scene_data)
    encoded = base64.b64encode(result).decode('ascii')
    print("MSGPACK_START")
    print(encoded)
    print("MSGPACK_END")
else:
    print("JSON_START")
    print(json.dumps(scene_data))
    print("JSON_END")
"""
        return script

    def _parse_script_output(self, output: str) -> Optional[Dict[str, Any]]:
        if "MSGPACK_START" in output:
            start_idx = output.find("MSGPACK_START") + len("MSGPACK_START\n")
            end_idx = output.find("\nMSGPACK_END")

            if end_idx == -1:
                self.logger.error("Invalid MessagePack format: missing end marker")
                return None

            encoded_data = output[start_idx:end_idx].strip()
            if not encoded_data:
                self.logger.error("Empty MessagePack data")
                return None

            binary_data = base64.b64decode(encoded_data)
            scene_data = msgpack.unpackb(binary_data)
            self.logger.info(f"Parsed scene data using MessagePack format, size: {len(encoded_data)} chars")
            return scene_data

        elif "JSON_START" in output:
            start_idx = output.find("JSON_START") + len("JSON_START\n")
            end_idx = output.find("\nJSON_END")

            if end_idx == -1:
                json_data = output[start_idx:]
            else:
                json_data = output[start_idx:end_idx]

            scene_data = json.loads(json_data)
            self.logger.info(f"Parsed scene data using JSON format, size: {len(json_data)} chars")
            self.logger.info(f"Parsed scene JSON content:\n{json_data[:300]}")
            return scene_data

        else:
            scene_data = json.loads(output)
            self.logger.info("Parsed scene data using legacy JSON format")
            return scene_data

    def _parse_optimized_sampled_data(self, mesh_data_dict: Dict[str, Any]) -> tuple:
        vertex_count = mesh_data_dict.get('vertex_count', 0)
        coordinate_scale = mesh_data_dict.get('coordinate_scale', 1.0)

        vertices = None
        vertex_colors = None

        vertices_f16_encoded = mesh_data_dict.get('vertices_f16')
        if vertices_f16_encoded and vertex_count > 0:
            vertices_bytes = base64.b64decode(vertices_f16_encoded)
            vertices_f16 = np.frombuffer(vertices_bytes, dtype=np.float16).reshape(-1, 3)
            vertices = (vertices_f16.astype(np.float32) / coordinate_scale)

        colors_u8_encoded = mesh_data_dict.get('colors_u8')
        if colors_u8_encoded and vertex_count > 0:
            colors_bytes = base64.b64decode(colors_u8_encoded)
            colors_rgb = np.frombuffer(colors_bytes, dtype=np.uint8).reshape(-1, 3)

            vertex_colors = np.zeros((colors_rgb.shape[0], 4), dtype=np.uint8)
            vertex_colors[:, :3] = colors_rgb
            vertex_colors[:, 3] = 255

        return vertices, vertex_colors

    def _parse_optimized_mesh_data(self, mesh_data_dict: Dict[str, Any]) -> tuple:
        vertex_count = mesh_data_dict.get('vertex_count', 0)
        coordinate_scale = mesh_data_dict.get('coordinate_scale', 1.0)

        vertices = None
        vertex_colors = None

        vertices_f16_encoded = mesh_data_dict.get('vertices_f16')
        if vertices_f16_encoded and vertex_count > 0:
            vertices_bytes = base64.b64decode(vertices_f16_encoded)
            vertices_f16 = np.frombuffer(vertices_bytes, dtype=np.float16).reshape(-1, 3)
            vertices = (vertices_f16.astype(np.float32) / coordinate_scale)

        colors_u8_encoded = mesh_data_dict.get('colors_u8')
        if colors_u8_encoded and vertex_count > 0:
            colors_bytes = base64.b64decode(colors_u8_encoded)
            colors_rgb = np.frombuffer(colors_bytes, dtype=np.uint8).reshape(-1, 3)

            vertex_colors = np.zeros((colors_rgb.shape[0], 4), dtype=np.uint8)
            vertex_colors[:, :3] = colors_rgb
            vertex_colors[:, 3] = 255

        return vertices, vertex_colors

    async def _sync_scene(self) -> bool:
        saved_selection = self.scene_manager.get_selected_names()
        executor = self._get_executor()
        if not executor:
            self.logger.warning("No executor available for scene sync")
            return False

        script = self._generate_optimized_script()

        result = await executor.exec_blender_script(script)

        if not result.get('success', False):
            self.logger.error(f"Scene sync script failed: {result.get('error', 'Unknown error')}")
            self._emit_selection_changed(True)
            return False

        output = result.get('stdout', '').strip()
        if not output:
            self.logger.warning("No output from scene sync script")
            self._emit_selection_changed(True)
            return False

        scene_data = self._parse_script_output(output)
        if scene_data is None:
            self.logger.error("Failed to parse scene data")
            self._emit_selection_changed(True)
            return False

        self._update_scene_from_data(scene_data, saved_selection)

        change_summary = self.scene_manager.get_change_summary()
        if any(len(objects) > 0 for objects in change_summary.values()):
            self.logger.info(f"Scene sync changes: {change_summary}")

        self._emit_render_update()
        self._emit_selection_changed(True)

        self.logger.info("Scene synchronization completed")
        return True

    def _update_scene_from_data(self, scene_data: Dict[str, Any], saved_selection: List[str] = None):
        if saved_selection is None:
            saved_selection = []

        processed_objects = set()

        for obj_data in scene_data.get('objects', []):
            name = obj_data.get('name', 'unnamed')
            obj_type_str = obj_data.get('type', 'UNKNOWN')

            if obj_type_str == 'MESH':
                obj_type = ObjectType.MESH
            elif obj_type_str == 'EMPTY':
                obj_type = ObjectType.EMPTY
            else:
                continue

            processed_objects.add(name)

            location = obj_data.get('location', [0, 0, 0])
            rotation = obj_data.get('rotation', [0, 0, 0])
            scale = obj_data.get('scale', [1, 1, 1])
            selected = name in saved_selection
            source_directory = obj_data.get('client_source_directory', '')
            existing_obj = self.scene_manager.get_object(name)
            if existing_obj:
                existing_obj.selected = selected
                obj = existing_obj
            else:
                obj = SceneObject(
                    name=name,
                    type=obj_type,
                    location=np.array(location),
                    rotation=np.array(rotation),
                    scale=np.array(scale),
                    selected=selected,
                    source_directory=source_directory
                )

                self.scene_manager.add_object(obj)

            if obj_type == ObjectType.MESH:
                mesh_data_dict = obj_data.get('mesh')
                if mesh_data_dict:
                    format_version = mesh_data_dict.get('format_version', 'legacy')

                    if format_version == 'v3_sampled_optimized':
                        vertices, vertex_colors = self._parse_optimized_sampled_data(mesh_data_dict)
                        faces = mesh_data_dict.get('faces', [])
                    elif format_version == 'v2_optimized':
                        vertices, vertex_colors = self._parse_optimized_mesh_data(mesh_data_dict)
                        faces = mesh_data_dict.get('faces', [])
                    else:
                        vertices = mesh_data_dict.get('vertices', [])
                        faces = mesh_data_dict.get('faces', [])
                        vertex_colors = mesh_data_dict.get('vertex_colors')

                        if vertices:
                            vertices = np.array(vertices)
                        if vertex_colors:
                            vertex_colors = np.array(vertex_colors, dtype=np.uint8)

                    if vertices is not None and len(vertices) > 0:
                        if not obj.mesh_data:
                            mesh_data = MeshData(
                                vertices=vertices,
                                faces=faces,
                                vertex_colors=vertex_colors
                            )
                            obj.mesh_data = mesh_data

                        obj.update_mesh(
                            vertices=vertices,
                            faces=faces,
                            vertex_colors=vertex_colors,
                            location=np.array(location),
                            rotation=np.array(rotation),
                            scale=np.array(scale),
                            force_color_update=True
                        )

        objects_to_remove = []
        for name in self.scene_manager.get_all_objects():
            if name not in processed_objects:
                objects_to_remove.append(name)

        for name in objects_to_remove:
            self.scene_manager.remove_object(name)

    def do_baking(self, data: Dict[str, Any]):
        object_names = data.get('object_names', [])
        no_color = data.get('no_color', False)

        if not object_names:
            self.logger.warning("No objects selected for baking")
            return

        operation = "Clearing colors" if no_color else "Baking"
        self.logger.info(f"{operation} for {len(object_names)} objects")

        script = self._generate_baking_script(object_names, no_color)

        def callback(success, result, **kwargs):
            obj_names = kwargs.get('object_names', [])
            no_col = kwargs.get('no_color', False)

            if success:
                stdout = result.get('stdout', '')
                parsed = self._parse_baking_result(stdout, no_col)

                if no_col:
                    if parsed['count'] > 0:
                        self.logger.info(f"Cleared colors from {parsed['count']} objects")
                else:
                    self.logger.info(f"Baked {parsed['count']} objects")
                    if parsed['skipped']:
                        skipped_str = ', '.join(parsed['skipped'])
                        self.logger.info(f"Skipped objects (no material): {skipped_str}")
            else:
                error = result.get('error', 'Unknown error')
                self.logger.error(f"Baking operation failed: {error}")

            if self.signal_router:
                self.signal_router.emit('scene.request_sync', {})

            if self.signal_router:
                self.signal_router.emit('scene.done_baking', {
                    'success': success,
                    'object_names': obj_names
                })

        self.exec_blender_python(script, callback,
                                object_names=object_names,
                                no_color=no_color)

    def _generate_baking_script(self, object_names: List[str], no_color: bool) -> str:
        if no_color:
            return self._generate_clear_colors_script(object_names)
        else:
            return self._generate_bake_colors_script(object_names)

    def _generate_clear_colors_script(self, object_names: List[str]) -> str:
        script = f"""
import bpy

object_names = {object_names}
cleared_count = 0

for obj_name in object_names:
    obj = bpy.data.objects.get(obj_name)
    if not obj or obj.type != 'MESH':
        continue

    mesh = obj.data

    if 'meshwork_baked' in mesh.color_attributes:
        mesh.color_attributes.remove(mesh.color_attributes['meshwork_baked'])
        cleared_count += 1

print(f"CLEARED: {{cleared_count}}")
"""
        return script

    def _generate_bake_colors_script(self, object_names: List[str]) -> str:
        script = f"""
import bpy

object_names = {object_names}
baked_count = 0
skipped_objects = []

for obj_name in object_names:
    obj = bpy.data.objects.get(obj_name)
    if not obj or obj.type != 'MESH':
        continue

    mesh = obj.data
    material = obj.active_material

    if not material or not material.use_nodes:
        skipped_objects.append(obj_name)
        continue

    bsdf = None
    for node in material.node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            bsdf = node
            break

    if not bsdf:
        skipped_objects.append(obj_name)
        continue

    if 'meshwork_baked' in mesh.color_attributes:
        mesh.color_attributes.remove(mesh.color_attributes['meshwork_baked'])

    color_attr = mesh.color_attributes.new(
        name='meshwork_baked',
        type='BYTE_COLOR',
        domain='POINT'
    )

    base_color_input = bsdf.inputs['Base Color']
    vertex_count = len(mesh.vertices)

    if not base_color_input.is_linked:
        color = base_color_input.default_value
        for i in range(vertex_count):
            color_attr.data[i].color = color
    else:
        from_node = base_color_input.links[0].from_node

        if from_node.type != 'TEX_IMAGE':
            skipped_objects.append(obj_name)
            continue

        image = from_node.image
        if not image:
            skipped_objects.append(obj_name)
            continue

        if len(mesh.uv_layers) == 0:
            skipped_objects.append(obj_name)
            continue

        uv_layer = mesh.uv_layers.active if mesh.uv_layers.active else mesh.uv_layers[0]

        width, height = image.size
        channels = image.channels
        pixels = list(image.pixels)

        expected_pixel_count = width * height * channels
        actual_pixel_count = len(pixels)

        if actual_pixel_count != expected_pixel_count:
            skipped_objects.append(obj_name)
            continue

        if actual_pixel_count == 0:
            skipped_objects.append(obj_name)
            continue

        vertex_to_loops = [[] for _ in range(vertex_count)]
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                loop = mesh.loops[loop_idx]
                vertex_to_loops[loop.vertex_index].append(loop_idx)

        default_color = (0.8, 0.8, 0.8, 1.0)

        for vertex_idx in range(vertex_count):
            loop_indices = vertex_to_loops[vertex_idx]
            if not loop_indices:
                color_attr.data[vertex_idx].color = default_color
                continue

            loop_idx = loop_indices[0]
            uv = uv_layer.data[loop_idx].uv

            uv_x = max(0.0, min(1.0, uv.x))
            uv_y = max(0.0, min(1.0, uv.y))

            x = int(uv_x * (width - 1))
            y = int(uv_y * (height - 1))
            x = max(0, min(x, width - 1))
            y = max(0, min(y, height - 1))

            pixel_idx = (y * width + x) * channels

            if pixel_idx < 0 or pixel_idx + channels - 1 >= actual_pixel_count:
                color_attr.data[vertex_idx].color = default_color
                continue

            if channels == 4:
                r = pixels[pixel_idx]
                g = pixels[pixel_idx + 1]
                b = pixels[pixel_idx + 2]
                a = pixels[pixel_idx + 3]
            elif channels == 3:
                r = pixels[pixel_idx]
                g = pixels[pixel_idx + 1]
                b = pixels[pixel_idx + 2]
                a = 1.0
            else:
                r = g = b = pixels[pixel_idx]
                a = 1.0

            color_attr.data[vertex_idx].color = (r, g, b, a)

    mesh.color_attributes.active_color = color_attr
    baked_count += 1

print(f"BAKED: {{baked_count}}")
if skipped_objects:
    print(f"SKIPPED: {{','.join(skipped_objects)}}")
"""
        return script

    def _parse_baking_result(self, stdout: str, no_color: bool) -> Dict[str, Any]:
        result = {
            'count': 0,
            'skipped': []
        }

        if no_color:
            if 'CLEARED:' in stdout:
                parts = stdout.split('CLEARED:')
                if len(parts) > 1:
                    count_str = parts[1].strip().split()[0]
                    result['count'] = int(count_str)
        else:
            if 'BAKED:' in stdout:
                parts = stdout.split('BAKED:')
                if len(parts) > 1:
                    count_str = parts[1].strip().split()[0]
                    result['count'] = int(count_str)

            if 'SKIPPED:' in stdout:
                parts = stdout.split('SKIPPED:')
                if len(parts) > 1:
                    skipped_str = parts[1].strip()
                    if skipped_str:
                        result['skipped'] = [s.strip() for s in skipped_str.split(',')]

        return result

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('SceneManager')