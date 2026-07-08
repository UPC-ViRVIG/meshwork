# core/mesh.py
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject
from core.executor import Executor
from logger import get_logger


class MeshAPI(QObject, Executor):

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("Mesh API initialized")

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('mesh.do_subdivide', self.do_subdivide_mesh, 'MeshAPI')
            self.signal_router.subscribe('mesh.do_simplify', self.do_simplify_mesh, 'MeshAPI')
            self.signal_router.subscribe('mesh.do_repair', self.do_repair_mesh, 'MeshAPI')

    def do_subdivide_mesh(self, data: Dict[str, Any]):
        object_id = data.get('object_id', 'selected')
        levels = data.get('levels', 1)

        script = f"""
import bpy

bpy.ops.object.select_all(action='DESELECT')

obj = bpy.context.scene.objects.get('{object_id}')
if obj and obj.type == 'MESH':
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')

    for i in range({levels}):
        bpy.ops.mesh.subdivide()

    bpy.ops.object.mode_set(mode='OBJECT')

    print(f"Subdivided mesh {{obj.name}} with {levels} levels")
    print(f"New vertex count: {{len(obj.data.vertices)}}")
else:
    print(f"Object {{'{object_id}'}} not found or is not a mesh")
    exit(1)
"""

        def callback(success, result, **kwargs):
            if self.signal_router:
                self.signal_router.emit('mesh.done_operation', {
                    'operation_type': 'subdivide',
                    'object_id': kwargs.get('object_id', ''),
                    'success': success,
                    'error': '' if success else result.get('error', 'Unknown error')
                })

                if success:
                    self.signal_router.emit('scene.object_modified', {
                        'object_name': kwargs.get('object_id', ''),
                        'properties': {'subdivision_levels': kwargs.get('levels', 1)},
                        'needs_redraw': True
                    })

        self.exec_blender_python(script, callback, object_id=object_id, levels=levels)

    def do_simplify_mesh(self, data: Dict[str, Any]):
        object_id = data.get('object_id', 'selected')
        ratio = data.get('ratio', 0.5)

        script = f"""
import bpy

bpy.ops.object.select_all(action='DESELECT')

obj = bpy.context.scene.objects.get('{object_id}')
if obj and obj.type == 'MESH':
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    original_faces = len(obj.data.polygons)

    decimate_mod = obj.modifiers.new(name="Decimate", type='DECIMATE')
    decimate_mod.ratio = {ratio}

    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier="Decimate")

    new_faces = len(obj.data.polygons)
    reduction = (original_faces - new_faces) / original_faces * 100

    print(f"Simplified mesh {{obj.name}}")
    print(f"Face count: {{original_faces}} -> {{new_faces}} ({{reduction:.1f}}% reduction)")
else:
    print(f"Object {{'{object_id}'}} not found or is not a mesh")
    exit(1)
"""

        def callback(success, result, **kwargs):
            if self.signal_router:
                self.signal_router.emit('mesh.done_operation', {
                    'operation_type': 'simplify',
                    'object_id': kwargs.get('object_id', ''),
                    'success': success,
                    'error': '' if success else result.get('error', 'Unknown error')
                })

                if success:
                    self.signal_router.emit('scene.object_modified', {
                        'object_name': kwargs.get('object_id', ''),
                        'properties': {'simplification_ratio': kwargs.get('ratio', 0.5)},
                        'needs_redraw': True
                    })

        self.exec_blender_python(script, callback, object_id=object_id, ratio=ratio)

    def do_repair_mesh(self, data: Dict[str, Any]):
        object_id = data.get('object_id', 'selected')

        script = f"""
import bpy
import bmesh

bpy.ops.object.select_all(action='DESELECT')

obj = bpy.context.scene.objects.get('{object_id}')
if obj and obj.type == 'MESH':
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')

    bm = bmesh.from_edit_mesh(obj.data)

    original_verts = len(bm.verts)
    original_faces = len(bm.faces)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    bmesh.ops.holes_fill(bm, edges=bm.edges)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=0.0001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bmesh.update_edit_mesh(obj.data)

    new_verts = len(bm.verts)
    new_faces = len(bm.faces)

    bpy.ops.object.mode_set(mode='OBJECT')

    print(f"Repaired mesh {{obj.name}}")
    print(f"Vertices: {{original_verts}} -> {{new_verts}}")
    print(f"Faces: {{original_faces}} -> {{new_faces}}")
else:
    print(f"Object {{'{object_id}'}} not found or is not a mesh")
    exit(1)
"""

        def callback(success, result, **kwargs):
            if self.signal_router:
                self.signal_router.emit('mesh.done_operation', {
                    'operation_type': 'repair',
                    'object_id': kwargs.get('object_id', ''),
                    'success': success,
                    'error': '' if success else result.get('error', 'Unknown error')
                })

                if success:
                    self.signal_router.emit('scene.object_modified', {
                        'object_name': kwargs.get('object_id', ''),
                        'properties': {'mesh_repaired': True},
                        'needs_redraw': True
                    })

        self.exec_blender_python(script, callback, object_id=object_id)

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('MeshAPI')