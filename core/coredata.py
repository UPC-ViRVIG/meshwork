# core/coredata.py
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Any, Union, ClassVar
import numpy as np
import copy
import pyvista as pv
import time
import hashlib

class _UnchangedType:
    def __repr__(self):
        return 'UNCHANGED'

UNCHANGED = _UnchangedType()

class ObjectType(Enum):
    MESH = "MESH"
    EMPTY = "EMPTY"

class SelectionMode(Enum):
    OBJECT = auto()
    VERTEX = auto()
    EDGE = auto()
    FACE = auto()

class DirtyState(Enum):
    NONE = "none"
    TRANSFORM_ONLY = "transform_only"
    TOPOLOGY_CHANGE = "topology_change"

def calculate_mesh_hash(vertices: np.ndarray, faces: List[List[int]]) -> str:
    vertices_bytes = vertices.tobytes()
    faces_str = str(faces)
    combined = vertices_bytes + faces_str.encode()
    return hashlib.md5(combined).hexdigest()

def calculate_transform_hash(location: np.ndarray, rotation: np.ndarray, scale: np.ndarray) -> str:
    transform_str = f"{location.tolist()}_{rotation.tolist()}_{scale.tolist()}"
    return hashlib.md5(transform_str.encode()).hexdigest()

def calculate_pointcloud_signature(vertices: np.ndarray, vertex_colors: Optional[np.ndarray] = None) -> str:
    vertex_count = len(vertices) if vertices is not None else 0
    color_count = len(vertex_colors) if vertex_colors is not None else 0
    return f"pc_{vertex_count}_{color_count}"

def calculate_mesh_change_signature(vertices: np.ndarray, faces: List[List[int]], vertex_colors: Optional[np.ndarray] = None) -> str:
    if not faces:
        return calculate_pointcloud_signature(vertices, vertex_colors)
    else:
        base_hash = calculate_mesh_hash(vertices, faces)
        if vertex_colors is None:
            return f"{base_hash}_NOCOLOR"
        else:
            colors_bytes = vertex_colors.tobytes()
            colors_hash = hashlib.md5(colors_bytes).hexdigest()[:8]
            return f"{base_hash}_{colors_hash}"

@dataclass
class MeshData:
    vertices: np.ndarray
    faces: List[List[int]]

    normals: Optional[np.ndarray] = None
    vertex_colors: Optional[np.ndarray] = None

    def __post_init__(self):
        if self.vertex_colors is not None:
            self.vertex_colors = np.array(self.vertex_colors, dtype=np.uint8)
            if len(self.vertex_colors) != len(self.vertices):
                raise ValueError("Vertex colors count must match vertices count")
            if self.vertex_colors.shape[1] != 4:
                raise ValueError("Vertex colors must be RGBA format")

    @property
    def vertex_count(self) -> int:
        return len(self.vertices) if self.vertices is not None else 0

    @property
    def face_count(self) -> int:
        return len(self.faces) if self.faces is not None else 0

    @property
    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        if self.vertices is not None and len(self.vertices) > 0:
            return (np.min(self.vertices, axis=0), np.max(self.vertices, axis=0))
        return (np.zeros(3), np.zeros(3))

    def has_vertex_colors(self) -> bool:
        return self.vertex_colors is not None

    def calculate_geometry_hash(self) -> str:
        return calculate_mesh_hash(self.vertices, self.faces)

    def get_render_data(self) -> Dict[str, Any]:
        data = {
            'vertices': self.vertices.tolist() if len(self.vertices) > 0 else [],
            'faces': self.faces.copy() if self.faces else [],
            'vertex_count': self.vertex_count,
            'face_count': self.face_count
        }

        if self.vertex_colors is not None:
            data['vertex_colors'] = self.vertex_colors.tolist()

        return data

    def to_pyvista(self) -> Optional[Any]:
        pv_faces = []
        for face in self.faces:
            pv_faces.append(len(face))
            pv_faces.extend(face)

        mesh = pv.PolyData(self.vertices, np.array(pv_faces))

        if self.normals is not None:
            mesh.point_data['normals'] = self.normals

        if self.vertex_colors is not None:
            mesh.point_data['vertex_colors'] = self.vertex_colors

        return mesh

    @classmethod
    def from_pyvista(cls, pv_mesh: Any) -> 'MeshData':
        vertices = pv_mesh.points

        faces = []
        pv_faces = pv_mesh.faces
        i = 0
        while i < len(pv_faces):
            n_points = pv_faces[i]
            i += 1
            face = pv_faces[i:i+n_points].tolist()
            faces.append(face)
            i += n_points

        normals = pv_mesh.point_data.get('normals')
        colors = pv_mesh.point_data.get('vertex_colors')

        return cls(
            vertices=vertices,
            faces=faces,
            normals=normals,
            vertex_colors=colors
        )

    def copy(self) -> 'MeshData':
        return MeshData(
            vertices=self.vertices.copy(),
            faces=copy.deepcopy(self.faces),
            normals=self.normals.copy() if self.normals is not None else None,
            vertex_colors=self.vertex_colors.copy() if self.vertex_colors is not None else None,
        )

@dataclass
class SelectionData:
    object_name: str

    selected_vertices: Set[int] = field(default_factory=set)
    selected_edges: Set[Tuple[int, int]] = field(default_factory=set)
    selected_faces: Set[int] = field(default_factory=set)

    selection_mode: SelectionMode = SelectionMode.OBJECT

    def has_any_selection(self) -> bool:
        return len(self.selected_vertices) > 0 or len(self.selected_edges) > 0 or len(self.selected_faces) > 0

    def clear_all(self):
        self.selected_vertices.clear()
        self.selected_edges.clear()
        self.selected_faces.clear()

@dataclass
class ObjectSnapshot:
    location: np.ndarray
    rotation: np.ndarray
    scale: np.ndarray
    mesh_data: Optional['MeshData'] = None

    @classmethod
    def create_from(cls, obj: 'SceneObject') -> 'ObjectSnapshot':
        snapshot = cls(
            location=obj.location.copy(),
            rotation=obj.rotation.copy(),
            scale=obj.scale.copy(),
        )

        if obj.mesh_data:
            snapshot.mesh_data = obj.mesh_data.copy()

        return snapshot

    def restore_to(self, obj: 'SceneObject'):
        obj.location = self.location.copy()
        obj.rotation = self.rotation.copy()
        obj.scale = self.scale.copy()

        if self.mesh_data and obj.mesh_data:
            obj.mesh_data.vertices = self.mesh_data.vertices.copy()
            obj.mesh_data.faces = copy.deepcopy(self.mesh_data.faces)
            if self.mesh_data.normals is not None:
                obj.mesh_data.normals = self.mesh_data.normals.copy()
            if self.mesh_data.vertex_colors is not None:
                obj.mesh_data.vertex_colors = self.mesh_data.vertex_colors.copy()

@dataclass
class SceneObject:
    name: str
    type: ObjectType

    location: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
    rotation: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
    scale: np.ndarray = field(default_factory=lambda: np.array([1.0, 1.0, 1.0]))

    source_directory: str = ""

    selected: bool = False
    mesh_data: Optional[MeshData] = None
    original_snapshot: Optional[ObjectSnapshot] = field(default=None, init=False)

    dirty_state: DirtyState = field(default=DirtyState.NONE, init=False)
    mesh_hash: Optional[str] = field(default=None, init=False)
    transform_hash: Optional[str] = field(default=None, init=False)

    def __post_init__(self):
        self.mesh_hash = self._calculate_current_mesh_signature()
        self.transform_hash = self._calculate_current_transform_hash()

    @property
    def is_in_preview_mode(self) -> bool:
        return self.original_snapshot is not None

    @property
    def needs_blender_sync(self) -> bool:
        return self.dirty_state == DirtyState.TOPOLOGY_CHANGE

    @property
    def needs_redraw(self) -> bool:
        return self.dirty_state != DirtyState.NONE

    @property
    def has_mesh(self) -> bool:
        return self.type == ObjectType.MESH and self.mesh_data is not None

    @property
    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        if self.has_mesh:
            return self.mesh_data.bounds
        else:
            return (self.location, self.location)

    def is_pointcloud(self) -> bool:
        return self.has_mesh and not self.mesh_data.faces

    def _calculate_current_mesh_signature(self) -> str:
        if not self.has_mesh:
            return ""
        return calculate_mesh_change_signature(
            self.mesh_data.vertices,
            self.mesh_data.faces,
            self.mesh_data.vertex_colors
        )

    def _calculate_current_transform_hash(self) -> str:
        return calculate_transform_hash(self.location, self.rotation, self.scale)

    def _update_dirty_state_based_on_changes(self, new_mesh_signature: str, new_transform_hash: str):
        mesh_changed = (self.mesh_hash != new_mesh_signature)
        transform_changed = (self.transform_hash != new_transform_hash)

        if mesh_changed:
            new_state = DirtyState.TOPOLOGY_CHANGE
        elif transform_changed:
            new_state = DirtyState.TRANSFORM_ONLY
        else:
            new_state = DirtyState.NONE

        self.dirty_state = new_state

        if mesh_changed:
            self.mesh_hash = new_mesh_signature
        if transform_changed:
            self.transform_hash = new_transform_hash

    def update_transform(self, location: Optional[np.ndarray] = None,
                        rotation: Optional[np.ndarray] = None,
                        scale: Optional[np.ndarray] = None):
        new_location = np.array(location) if location is not None else self.location
        new_rotation = np.array(rotation) if rotation is not None else self.rotation
        new_scale = np.array(scale) if scale is not None else self.scale
        new_transform_hash = calculate_transform_hash(new_location, new_rotation, new_scale)

        if self.transform_hash != new_transform_hash:
            if not self.is_in_preview_mode:
                self._create_snapshot()

            if location is not None:
                self.location = np.array(location)
            if rotation is not None:
                self.rotation = np.array(rotation)
            if scale is not None:
                self.scale = np.array(scale)

        current_mesh_signature = self._calculate_current_mesh_signature()
        self._update_dirty_state_based_on_changes(current_mesh_signature, new_transform_hash)

    def update_mesh(self, vertices: Optional[np.ndarray] = None,
                   faces: Optional[List[List[int]]] = None,
                   normals: Optional[np.ndarray] = None,
                   vertex_colors = UNCHANGED,
                   location: Optional[np.ndarray] = None,
                   rotation: Optional[np.ndarray] = None,
                   scale: Optional[np.ndarray] = None,
                   force_color_update: bool = False):
        if not self.has_mesh:
            return

        new_vertices = vertices if vertices is not None else self.mesh_data.vertices
        new_faces = faces if faces is not None else self.mesh_data.faces

        if force_color_update:
            new_vertex_colors = vertex_colors
        else:
            if vertex_colors is UNCHANGED:
                new_vertex_colors = self.mesh_data.vertex_colors
            else:
                new_vertex_colors = vertex_colors

        new_location = np.array(location) if location is not None else self.location
        new_rotation = np.array(rotation) if rotation is not None else self.rotation
        new_scale = np.array(scale) if scale is not None else self.scale

        new_mesh_signature = calculate_mesh_change_signature(new_vertices, new_faces, new_vertex_colors)
        new_transform_hash = calculate_transform_hash(new_location, new_rotation, new_scale)

        if self.mesh_hash != new_mesh_signature or self.transform_hash != new_transform_hash:
            if not self.is_in_preview_mode:
                self._create_snapshot()

            if vertices is not None:
                self.mesh_data.vertices = vertices
            if faces is not None:
                self.mesh_data.faces = faces
            if normals is not None:
                self.mesh_data.normals = normals

            if force_color_update:
                self.mesh_data.vertex_colors = new_vertex_colors
            elif vertex_colors is not UNCHANGED:
                self.mesh_data.vertex_colors = vertex_colors

            if location is not None:
                self.location = np.array(location)
            if rotation is not None:
                self.rotation = np.array(rotation)
            if scale is not None:
                self.scale = np.array(scale)

        self._update_dirty_state_based_on_changes(new_mesh_signature, new_transform_hash)

    def apply_changes(self):
        if self.is_in_preview_mode:
            self.original_snapshot = None

    def cancel_changes(self):
        if self.is_in_preview_mode and self.original_snapshot:
            self.original_snapshot.restore_to(self)
            self.original_snapshot = None
            self.dirty_state = DirtyState.TRANSFORM_ONLY

    def _create_snapshot(self):
        self.original_snapshot = ObjectSnapshot.create_from(self)

    def copy(self) -> 'SceneObject':
        new_obj = SceneObject(
            name=self.name + "_copy",
            type=self.type,
            location=self.location.copy(),
            rotation=self.rotation.copy(),
            scale=self.scale.copy(),
            source_directory=self.source_directory,
            selected=False,
            mesh_data=self.mesh_data.copy() if self.mesh_data else None,
        )
        return new_obj


class SceneObjectManager:
    def __init__(self):
        self.objects: Dict[str, SceneObject] = {}

    def add_object(self, obj: SceneObject) -> bool:
        if obj.name in self.objects:
            return False
        self.objects[obj.name] = obj
        return True

    def remove_object(self, name: str) -> bool:
        if name not in self.objects:
            return False
        del self.objects[name]
        return True

    def get_object(self, name: str) -> Optional[SceneObject]:
        return self.objects.get(name)

    def get_all_objects(self) -> Dict[str, SceneObject]:
        return self.objects.copy()

    def get_selected_objects(self) -> List[SceneObject]:
        return [obj for obj in self.objects.values() if obj.selected]

    def get_selected_names(self) -> List[str]:
        return [name for name, obj in self.objects.items() if obj.selected]

    def clear_all_selections(self):
        for obj in self.objects.values():
            obj.selected = False

    def select_object(self, name: str, extend: bool = False) -> bool:
        if name not in self.objects:
            return False

        if extend:
            self.objects[name].selected = not self.objects[name].selected
        else:
            self.clear_all_selections()
            self.objects[name].selected = True
        return True

    def select_all(self) -> bool:
        for obj in self.objects.values():
            obj.selected = True
        return True

    def has_selections(self) -> bool:
        return any(obj.selected for obj in self.objects.values())

    def get_selection_count(self) -> int:
        return sum(1 for obj in self.objects.values() if obj.selected)

    def get_change_summary(self) -> Dict[str, List[str]]:
        summary = {
            'topology_changed': [],
            'transform_only': [],
            'none': []
        }

        for name, obj in self.objects.items():
            if obj.dirty_state == DirtyState.TOPOLOGY_CHANGE:
                summary['topology_changed'].append(name)
            elif obj.dirty_state == DirtyState.TRANSFORM_ONLY:
                summary['transform_only'].append(name)
            else:
                summary['none'].append(name)

        return summary

def create_mesh_object(name: str, vertices: np.ndarray, faces: List[List[int]],
                      location: np.ndarray = None, **kwargs) -> SceneObject:
    mesh_data = MeshData(vertices=vertices, faces=faces)

    obj = SceneObject(
        name=name,
        type=ObjectType.MESH,
        location=location if location is not None else np.array([0.0, 0.0, 0.0]),
        mesh_data=mesh_data,
        **kwargs
    )

    return obj

scene_object_manager = SceneObjectManager()
component_selection: Optional[SelectionData] = None

def get_scene_manager() -> SceneObjectManager:
    return scene_object_manager