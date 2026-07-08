# gui/render.py
import numpy as np
import pyvista as pv
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from PySide6.QtWidgets import QApplication
from logger import get_logger
import random
from core.coredata import get_scene_manager, DirtyState
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class MeshStats:
    vertex_count: int
    face_count: int
    edge_count: int
    euler_characteristic: int
    face_normals: Optional[np.ndarray] = None
    edge_face_adjacency: Optional[Dict[Tuple[int, int], List[int]]] = None
    boundary_edges: Optional[Set[Tuple[int, int]]] = None
    non_manifold_edges: Optional[Set[Tuple[int, int]]] = None
    manifold_edges: Optional[Set[Tuple[int, int]]] = None
    is_manifold: Optional[bool] = None
    is_closed: Optional[bool] = None


@dataclass
class PointCloudStats:
    vertex_count: int
    has_colors: bool


def compute_edge_count_approx(faces):
    total_edges = sum(len(face) for face in faces)
    return total_edges // 2


def build_edge_face_adjacency(faces):
    edge_to_faces = defaultdict(list)
    for face_idx, face_vertices in enumerate(faces):
        n = len(face_vertices)
        for i in range(n):
            v1 = face_vertices[i]
            v2 = face_vertices[(i + 1) % n]
            edge = (min(v1, v2), max(v1, v2))
            edge_to_faces[edge].append(face_idx)
    return dict(edge_to_faces)


def classify_edges(edge_face_adjacency):
    boundary_edges = set()
    non_manifold_edges = set()
    manifold_edges = set()
    for edge, faces in edge_face_adjacency.items():
        face_count = len(faces)
        if face_count == 1:
            boundary_edges.add(edge)
        elif face_count == 2:
            manifold_edges.add(edge)
        else:
            non_manifold_edges.add(edge)
    return boundary_edges, non_manifold_edges, manifold_edges


class RenderObjectData:
    def __init__(self, name, vertices, faces, location,
                 rotation, scale, selected, dirty_state,
                 vertex_colors=None):
        self.logger = get_logger()
        self.name = name
        self.vertices = np.array(vertices) if vertices else np.array([])
        self.faces = faces if faces else []
        self.location = np.array(location)
        self.rotation = np.array(rotation)
        self.scale = np.array(scale)
        self.selected = selected
        self.dirty_state = dirty_state
        self._mesh_stats = None
        self._stats_flags = (False, False)
        self.opt_feature_angle = None
        self.opt_feature_angle_invalid = False

        if vertex_colors is not None:
            colors_array = np.array(vertex_colors, dtype=np.uint8)
            if colors_array.shape[1] == 4:
                self.vertex_colors = colors_array[:, :3].astype(np.float32) / 255.0
            else:
                self.vertex_colors = colors_array.astype(np.float32) / 255.0
        else:
            self.vertex_colors = None

    def is_pointcloud(self):
        return len(self.faces) == 0

    def get_transform_matrix(self):
        return build_transform_matrix(self.location, self.rotation, self.scale)

    def _matches_flags(self, need_normals, need_adjacency):
        cached_normals, cached_adjacency = self._stats_flags
        has_normals = not need_normals or cached_normals
        has_adjacency = not need_adjacency or cached_adjacency
        return has_normals and has_adjacency

    def _compute_pointcloud_stats(self):
        vertex_count = len(self.vertices)
        has_colors = self.vertex_colors is not None
        return PointCloudStats(vertex_count=vertex_count, has_colors=has_colors)

    def _compute_mesh_stats(self, compute_normals, compute_adjacency):
        if len(self.vertices) == 0:
            return MeshStats(
                vertex_count=0,
                face_count=0,
                edge_count=0,
                euler_characteristic=0,
                face_normals=None,
                edge_face_adjacency=None,
                boundary_edges=None,
                non_manifold_edges=None,
                manifold_edges=None,
                is_manifold=None,
                is_closed=None
            )

        import time
        start_time = time.time()

        vertex_count = len(self.vertices)
        face_count = len(self.faces)

        if compute_adjacency:
            edge_to_faces = build_edge_face_adjacency(self.faces)
            edge_count = len(edge_to_faces)
            boundary_edges, non_manifold_edges, manifold_edges = classify_edges(edge_to_faces)
            is_manifold = len(non_manifold_edges) == 0
            is_closed = len(boundary_edges) == 0
        else:
            edge_count = compute_edge_count_approx(self.faces)
            edge_to_faces = None
            boundary_edges = None
            non_manifold_edges = None
            manifold_edges = None
            is_manifold = None
            is_closed = None

        euler = vertex_count - edge_count + face_count

        face_normals = None
        if compute_normals:
            pv_mesh = create_pyvista_mesh(self)
            pv_mesh_normals = pv_mesh.compute_normals(
                point_normals=False,
                cell_normals=True
            )
            if 'Normals' in pv_mesh_normals.cell_data:
                face_normals = pv_mesh_normals.cell_data['Normals'].astype(np.float32)
            else:
                self.logger.warning(f"Failed to compute face normals for {self.name}")

        elapsed = (time.time() - start_time) * 1000
        self.logger.debug(
            f"{self.name} computed: V={vertex_count}, F={face_count}, E={edge_count}, "
            f"normals={compute_normals}, adjacency={compute_adjacency}, "
            f"time={elapsed:.1f}ms"
        )

        return MeshStats(
            vertex_count=vertex_count,
            face_count=face_count,
            edge_count=edge_count,
            euler_characteristic=euler,
            face_normals=face_normals,
            edge_face_adjacency=edge_to_faces,
            boundary_edges=boundary_edges,
            non_manifold_edges=non_manifold_edges,
            manifold_edges=manifold_edges,
            is_manifold=is_manifold,
            is_closed=is_closed
        )

    def mesh_stats(self, compute_normals=False, compute_adjacency=False, force_recompute=False):
        if not force_recompute and self._mesh_stats is not None:
            if self._matches_flags(compute_normals, compute_adjacency):
                self.logger.debug(f"{self.name} returning cached stats")
                return self._mesh_stats

        if self.is_pointcloud():
            stats = self._compute_pointcloud_stats()
            self._stats_flags = (False, False)
        else:
            stats = self._compute_mesh_stats(compute_normals, compute_adjacency)
            self._stats_flags = (compute_normals, compute_adjacency)

        self._mesh_stats = stats
        return stats


def build_transform_matrix(location, rotation, scale):
    T = np.eye(4)
    T[:3, 3] = location

    rx, ry, rz = rotation

    Rx = np.array([[1, 0, 0, 0],
                   [0, np.cos(rx), -np.sin(rx), 0],
                   [0, np.sin(rx), np.cos(rx), 0],
                   [0, 0, 0, 1]])

    Ry = np.array([[np.cos(ry), 0, np.sin(ry), 0],
                   [0, 1, 0, 0],
                   [-np.sin(ry), 0, np.cos(ry), 0],
                   [0, 0, 0, 1]])

    Rz = np.array([[np.cos(rz), -np.sin(rz), 0, 0],
                   [np.sin(rz), np.cos(rz), 0, 0],
                   [0, 0, 1, 0],
                   [0, 0, 0, 1]])

    R = Rz @ Ry @ Rx

    S = np.eye(4)
    S[0, 0], S[1, 1], S[2, 2] = scale

    return T @ R @ S


def create_pyvista_mesh(obj):
    if obj.is_pointcloud():
        mesh = pv.PolyData(obj.vertices)
        if obj.vertex_colors is not None and len(obj.vertex_colors) == len(obj.vertices):
            mesh.point_data['colors'] = obj.vertex_colors
    else:
        faces_array = []
        for face in obj.faces:
            face_with_count = [len(face)] + list(face)
            faces_array.extend(face_with_count)
        mesh = pv.PolyData(obj.vertices, np.array(faces_array))
        if obj.vertex_colors is not None and len(obj.vertex_colors) == len(obj.vertices):
            mesh.point_data['colors'] = obj.vertex_colors

    mesh.field_data['object_name'] = obj.name
    return mesh


def _get_field_data_value(mesh, key):
    try:
        if key not in mesh.field_data:
            return None
        return mesh.field_data[key]
    except Exception:
        return None


def apply_auto_smooth_fixed(mesh, feature_angle=30.0):
    if len(mesh.points) == 0:
        return mesh
    if len(mesh.faces) == 0:
        return mesh

    object_name = _get_field_data_value(mesh, 'object_name')

    smoothed = mesh.copy()
    smoothed = smoothed.compute_normals(
        point_normals=True,
        cell_normals=False,
        feature_angle=feature_angle,
        split_vertices=True,
    )

    if object_name is not None:
        smoothed.field_data['object_name'] = object_name

    return smoothed


def apply_transform_to_mesh(mesh, matrix):
    return mesh.transform(matrix, inplace=False)


class SceneRenderer:
    DEFAULT_CAMERA_POSITION = (15, -15, 15)
    DEFAULT_CAMERA_FOCAL_POINT = (0, 0, 0)
    DEFAULT_CAMERA_UP = (0, 0, 1)
    DEFAULT_CAMERA_VIEW_ANGLE = 30
    DEFAULT_CAMERA_PARALLEL_PROJECTION = False

    def __init__(self, plotter):
        self.logger = get_logger()
        self._plotter = plotter
        self._mesh_actors = {}
        self._selection_actors = {}
        self._original_meshes = {}
        self._render_objects = {}
        self._grid_actors = []
        self._axes_actor = None
        self.max_pointcloud_points = 100000

        self._saved_camera_state = None

        self.selection_config = {
            'mesh_line_width': 2.5,
            'mesh_color': [0.2, 1.0, 0.2],
            'adaptive_default_feature_angle': 15.0,
            'adaptive_min_ratio': 0.01,
            'adaptive_max_ratio': 0.05,
            'adaptive_angle_min': 0.01,
            'adaptive_angle_max': 179.99,
            'adaptive_max_iterations': 8,
            'pointcloud_size_multiplier': 1.8,
            'pointcloud_color_blend_ratio': 0.3,
            'pointcloud_highlight_color': [0.2, 1.0, 0.2, 1.0]
        }

        self.setup_lighting()
        self.setup_grid()
        self.setup_default_camera()

    def setup_default_camera(self):
        self._plotter.camera.position = self.DEFAULT_CAMERA_POSITION
        self._plotter.camera.focal_point = self.DEFAULT_CAMERA_FOCAL_POINT
        self._plotter.camera.up = self.DEFAULT_CAMERA_UP
        self._plotter.camera.view_angle = self.DEFAULT_CAMERA_VIEW_ANGLE
        self._plotter.camera.parallel_projection = self.DEFAULT_CAMERA_PARALLEL_PROJECTION

    def _save_camera_state(self):
        try:
            parallel_scale = self._plotter.camera.parallel_scale
        except Exception:
            parallel_scale = 1.0
        self._saved_camera_state = {
            'position': tuple(self._plotter.camera.position),
            'focal_point': tuple(self._plotter.camera.focal_point),
            'up': tuple(self._plotter.camera.up),
            'view_angle': self._plotter.camera.view_angle,
            'parallel_projection': self._plotter.camera.parallel_projection,
            'parallel_scale': parallel_scale,
        }

    def _restore_camera_state(self):
        if self._saved_camera_state is None:
            return
        self._plotter.camera.position = self._saved_camera_state['position']
        self._plotter.camera.focal_point = self._saved_camera_state['focal_point']
        self._plotter.camera.up = self._saved_camera_state['up']
        self._plotter.camera.view_angle = self._saved_camera_state['view_angle']
        self._plotter.camera.parallel_projection = self._saved_camera_state['parallel_projection']
        try:
            self._plotter.camera.parallel_scale = self._saved_camera_state['parallel_scale']
        except Exception:
            pass

    def setup_lighting(self):
        self._plotter.remove_all_lights()

        key_light = pv.Light(
            position=(8, 8, 10),
            focal_point=(0, 0, 0),
            color=[1.0, 0.95, 0.9],
            intensity=0.6
        )
        self._plotter.add_light(key_light)

        fill_light = pv.Light(
            position=(-4, -4, -6),
            focal_point=(0, 0, 0),
            color=[0.9, 0.95, 1.0],
            intensity=0.2
        )
        self._plotter.add_light(fill_light)

        rim_light = pv.Light(
            position=(0, -8, 2),
            focal_point=(0, 0, 0),
            color='white',
            intensity=0.15
        )
        self._plotter.add_light(rim_light)

        ambient_light = pv.Light(intensity=0.8)
        self._plotter.add_light(ambient_light)

    def setup_grid(self):
        self._clear_grid()

        grid = self._plotter.add_mesh(
            pv.Plane(
                center=(0, 0, 0),
                direction=(0, 0, 1),
                i_size=100,
                j_size=100,
                i_resolution=20,
                j_resolution=20
            ),
            color='gray',
            opacity=0.05,
            show_edges=True,
            edge_color='white',
            line_width=1,
            pickable=False
        )
        self._grid_actors.append(grid)

        self._axes_actor = self._plotter.add_axes(
            xlabel='X',
            ylabel='Y',
            zlabel='Z',
            line_width=2
        )

    def update_scene(self, objects_data):
        self._save_camera_state()
        current_names = set()

        for obj_data in objects_data:
            name = obj_data.get('name', 'unnamed')
            current_names.add(name)

            dirty_state = obj_data.get('dirty_state', 'none')

            if name not in self._render_objects or dirty_state == 'topology_change':
                render_obj = RenderObjectData(
                    name=name,
                    vertices=obj_data.get('vertices', []),
                    faces=obj_data.get('faces', []),
                    location=obj_data.get('location', [0, 0, 0]),
                    rotation=obj_data.get('rotation', [0, 0, 0]),
                    scale=obj_data.get('scale', [1, 1, 1]),
                    selected=obj_data.get('selected', False),
                    dirty_state=dirty_state,
                    vertex_colors=obj_data.get('vertex_colors')
                )
                self._render_objects[name] = render_obj

            elif dirty_state == 'transform_only':
                render_obj = self._render_objects[name]
                render_obj.location = np.array(obj_data.get('location', [0, 0, 0]))
                render_obj.rotation = np.array(obj_data.get('rotation', [0, 0, 0]))
                render_obj.scale = np.array(obj_data.get('scale', [1, 1, 1]))
                render_obj.selected = obj_data.get('selected', False)
                render_obj.dirty_state = dirty_state

            else:
                render_obj = self._render_objects[name]
                render_obj.selected = obj_data.get('selected', False)
                render_obj.dirty_state = dirty_state

            if len(render_obj.vertices) > 0:
                self._process_object_update(render_obj)

        objects_to_remove = set(self._mesh_actors.keys()) - current_names
        for name in objects_to_remove:
            self._remove_object_actors(name)
            if name in self._render_objects:
                del self._render_objects[name]

        self._restore_camera_state()
        self._plotter.render()

    def _process_object_update(self, obj):
        if obj.dirty_state == 'topology_change':
            self._handle_topology_change(obj)
        elif obj.dirty_state == 'transform_only':
            self._handle_transform_only(obj)
        else:
            existing_selected = obj.name in self._selection_actors
            if obj.selected != existing_selected:
                self._handle_selection_change(obj)

    def _handle_topology_change(self, obj):
        self._remove_object_actors(obj.name)

        obj.opt_feature_angle = None
        obj.opt_feature_angle_invalid = False

        obj.mesh_stats(compute_normals=False, compute_adjacency=False, force_recompute=True)

        mesh = create_pyvista_mesh(obj)

        if not obj.is_pointcloud():
            mesh = apply_auto_smooth_fixed(mesh, feature_angle=30.0)

        self._original_meshes[obj.name] = mesh.copy()

        transform_matrix = obj.get_transform_matrix()
        transformed_mesh = apply_transform_to_mesh(mesh, transform_matrix)

        self._create_main_actor(obj, transformed_mesh)

        if obj.selected:
            self._create_intelligent_selection_effects(obj, transformed_mesh)

        scene_manager = get_scene_manager()
        scene_obj = scene_manager.get_object(obj.name)
        if scene_obj:
            scene_obj.dirty_state = DirtyState.NONE

    def _handle_transform_only(self, obj):
        if obj.name not in self._original_meshes:
            return

        original_mesh = self._original_meshes[obj.name]
        transform_matrix = obj.get_transform_matrix()
        transformed_mesh = apply_transform_to_mesh(original_mesh, transform_matrix)

        if obj.name in self._mesh_actors:
            actor = self._mesh_actors[obj.name]
            mapper = actor.GetMapper()
            mapper.SetInputData(transformed_mesh)
            mapper.Modified()
            actor.Modified()

        if obj.name in self._selection_actors:
            self._update_selection_actor(obj, transformed_mesh)

        scene_manager = get_scene_manager()
        scene_obj = scene_manager.get_object(obj.name)
        if scene_obj:
            scene_obj.dirty_state = DirtyState.NONE

    def _handle_selection_change(self, obj):
        self._save_camera_state()

        if obj.selected:
            if obj.name in self._original_meshes:
                original = self._original_meshes[obj.name]
                transform_matrix = obj.get_transform_matrix()
                current_mesh = apply_transform_to_mesh(original, transform_matrix)
                self._create_intelligent_selection_effects(obj, current_mesh)
        else:
            if obj.name in self._selection_actors:
                self._plotter.remove_actor(self._selection_actors[obj.name])
                del self._selection_actors[obj.name]

        self._restore_camera_state()

    def _create_intelligent_selection_effects(self, obj, mesh):
        if obj.is_pointcloud():
            self._create_pointcloud_enhanced_selection(obj, mesh)
        else:
            self._create_mesh_feature_edge_selection(obj, mesh)

    def _create_pointcloud_enhanced_selection(self, obj, mesh):
        if len(mesh.points) == 0:
            return

        selected_mesh = mesh.copy()
        config = self.selection_config

        highlight_colors = self._calculate_pointcloud_highlight_colors(mesh, config)
        size_multiplier = config['pointcloud_size_multiplier']
        original_size = 2.0
        highlight_size = original_size * size_multiplier

        render_params = {
            'point_size': highlight_size,
            'render_points_as_spheres': True,
            'pickable': False
        }

        if highlight_colors is not None:
            selected_mesh.point_data['highlight_colors'] = highlight_colors
            render_params['scalars'] = 'highlight_colors'
            render_params['rgb'] = True
        else:
            render_params['color'] = config['pointcloud_highlight_color'][:3]

        selection_actor = self._plotter.add_mesh(selected_mesh, **render_params)
        self._selection_actors[obj.name] = selection_actor

    def _calculate_pointcloud_highlight_colors(self, mesh, config):
        highlight_color = np.array(config['pointcloud_highlight_color'])
        blend_ratio = config['pointcloud_color_blend_ratio']

        if 'colors' in mesh.point_data:
            original_colors = mesh.point_data['colors']
            if original_colors.shape[1] == 3:
                alpha_channel = np.ones((len(original_colors), 1)) * 255
                original_colors = np.hstack([original_colors, alpha_channel])

            blended = original_colors.astype(np.float32) * (1.0 - blend_ratio) + \
                     (highlight_color * 255).astype(np.float32) * blend_ratio
            return np.clip(blended, 0, 255).astype(np.uint8)

        point_count = mesh.n_points
        return np.tile((highlight_color * 255).astype(np.uint8), (point_count, 1))

    def _create_mesh_feature_edge_selection(self, obj, mesh):
        if len(mesh.faces) == 0:
            return

        config = self.selection_config
        total_edges = obj.mesh_stats().edge_count

        if not obj.opt_feature_angle_invalid and total_edges > 2000:
            total_edges = obj.mesh_stats().edge_count
            baseline_edges = mesh.extract_feature_edges(
                boundary_edges=True,
                non_manifold_edges=True,
                feature_angle=0.0,
                manifold_edges=False
            )
            baseline_count = baseline_edges.n_cells if baseline_edges else 0
            adjustable_edges = total_edges - baseline_count

            min_ratio = config['adaptive_min_ratio']
            max_ratio = config['adaptive_max_ratio']
            min_target = int(total_edges * min_ratio)
            max_target = int(total_edges * max_ratio)

            if obj.opt_feature_angle is not None:
                feature_angle = obj.opt_feature_angle
            else:
                feature_angle = config['adaptive_default_feature_angle']

            feature_angle_min = config['adaptive_angle_min']
            feature_angle_max = config['adaptive_angle_max']
            max_iterations = config['adaptive_max_iterations']

            feature_edges = None
            feature_count = 0

            for iteration in range(max_iterations):
                feature_edges = mesh.extract_feature_edges(
                    boundary_edges=True,
                    non_manifold_edges=True,
                    feature_angle=feature_angle,
                    manifold_edges=False
                )

                feature_count = feature_edges.n_cells if feature_edges else 0
                feature_count += adjustable_edges

                self.logger.debug(
                    f"{obj.name} feature angle: {feature_angle:.1f} -> "
                    f"{feature_count}/{total_edges} edges ({feature_count/total_edges*100:.1f}%), "
                    f"iterations: {iteration+1}"
                )

                if min_target <= feature_count <= max_target:
                    obj.opt_feature_angle = feature_angle
                    self.logger.debug(
                        f"{obj.name} feature angle: {feature_angle:.1f} -> "
                        f"{feature_count}/{total_edges} edges ({feature_count/total_edges*100:.1f}%), "
                        f"iterations: {iteration+1}"
                    )
                    break

                if feature_angle_max - feature_angle_min < 0.1:
                    break

                if feature_count < min_target:
                    feature_angle_max = feature_angle
                    feature_angle = (feature_angle_min + feature_angle) / 2.0
                else:
                    feature_angle_min = feature_angle
                    feature_angle = (feature_angle + feature_angle_max) / 2.0

            if feature_edges and feature_edges.n_points > 0 and min_target <= feature_count <= max_target:
                obj.opt_feature_angle = feature_angle
                outline_actor = self._plotter.add_mesh(
                    feature_edges,
                    color=config['mesh_color'],
                    line_width=config['mesh_line_width'],
                    pickable=False,
                    style='wireframe'
                )
                self._selection_actors[obj.name] = outline_actor
                return

            self.logger.info(f"{obj.name} adaptive selection failed, using all edges")
            obj.opt_feature_angle_invalid = True

        all_edges = mesh.extract_feature_edges(
            boundary_edges=True,
            non_manifold_edges=True,
            feature_angle=0.1,
            manifold_edges=True
        )

        if all_edges and all_edges.n_points > 0:
            outline_actor = self._plotter.add_mesh(
                all_edges,
                color=config['mesh_color'],
                line_width=config['mesh_line_width'],
                pickable=False,
                style='wireframe'
            )
            self._selection_actors[obj.name] = outline_actor

    def _update_selection_actor(self, obj, transformed_mesh):
        if obj.name in self._selection_actors:
            self._plotter.remove_actor(self._selection_actors[obj.name])
            del self._selection_actors[obj.name]

        if obj.selected:
            self._create_intelligent_selection_effects(obj, transformed_mesh)

    def _create_main_actor(self, obj, mesh):
        mesh.field_data['object_name'] = obj.name

        if obj.is_pointcloud():
            vertices = mesh.points
            vertex_colors = obj.vertex_colors

            if len(vertices) > self.max_pointcloud_points:
                indices = random.sample(range(len(vertices)), self.max_pointcloud_points)
                indices.sort()
                vertices = vertices[indices]
                if vertex_colors is not None:
                    vertex_colors = vertex_colors[indices]
                mesh = pv.PolyData(vertices)
                if vertex_colors is not None:
                    mesh.point_data['colors'] = vertex_colors
                mesh.field_data['object_name'] = obj.name

            render_params = {
                'name': obj.name,
                'pickable': True,
                'point_size': 2.0,
                'render_points_as_spheres': True
            }

            if 'colors' in mesh.point_data:
                render_params['scalars'] = 'colors'
                render_params['rgb'] = True
            else:
                render_params['color'] = [0.8, 0.8, 0.8]
        else:
            render_params = {
                'name': obj.name,
                'pickable': True,
                'smooth_shading': True
            }

            if 'colors' in mesh.point_data:
                render_params['scalars'] = 'colors'
                render_params['rgb'] = True
            else:
                render_params['color'] = [0.8, 0.8, 0.8]

        actor = self._plotter.add_mesh(mesh, **render_params)
        self._mesh_actors[obj.name] = actor

    def _remove_object_actors(self, name):
        if name in self._mesh_actors:
            self._plotter.remove_actor(self._mesh_actors[name])
            del self._mesh_actors[name]

        if name in self._selection_actors:
            self._plotter.remove_actor(self._selection_actors[name])
            del self._selection_actors[name]

        if name in self._original_meshes:
            del self._original_meshes[name]

    def clear_scene(self):
        for actor in list(self._mesh_actors.values()):
            self._plotter.remove_actor(actor)
        self._mesh_actors.clear()

        for actor in list(self._selection_actors.values()):
            self._plotter.remove_actor(actor)
        self._selection_actors.clear()

        self._original_meshes.clear()
        self._render_objects.clear()

    def set_view(self, view_type):
        current_position = np.array(self._plotter.camera.position)
        current_focal = np.array(self._plotter.camera.focal_point)
        current_distance = np.linalg.norm(current_position - current_focal)

        if view_type.lower() == "top":
            new_position = current_focal + np.array([0, 0, current_distance])
            self._plotter.camera.position = new_position
            self._plotter.camera.up = (0, 1, 0)
            self._plotter.camera.parallel_projection = True
        elif view_type.lower() == "front":
            new_position = current_focal + np.array([0, -current_distance, 0])
            self._plotter.camera.position = new_position
            self._plotter.camera.up = (0, 0, 1)
            self._plotter.camera.parallel_projection = True
        elif view_type.lower() == "side":
            new_position = current_focal + np.array([current_distance, 0, 0])
            self._plotter.camera.position = new_position
            self._plotter.camera.up = (0, 0, 1)
            self._plotter.camera.parallel_projection = True
        else:
            direction = np.array(self.DEFAULT_CAMERA_POSITION) / np.linalg.norm(self.DEFAULT_CAMERA_POSITION)
            new_position = current_focal + direction * current_distance
            self._plotter.camera.position = new_position
            self._plotter.camera.up = self.DEFAULT_CAMERA_UP
            self._plotter.camera.view_angle = self.DEFAULT_CAMERA_VIEW_ANGLE
            self._plotter.camera.parallel_projection = self.DEFAULT_CAMERA_PARALLEL_PROJECTION

        self._plotter.render()

    def toggle_grid(self, visible):
        for actor in self._grid_actors:
            if visible:
                actor.VisibilityOn()
            else:
                actor.VisibilityOff()
        self._plotter.render()

    def toggle_axes(self, visible):
        if self._axes_actor is None:
            return
        try:
            if hasattr(self._axes_actor, 'SetEnabled'):
                self._axes_actor.SetEnabled(1 if visible else 0)
            elif hasattr(self._axes_actor, 'VisibilityOn'):
                if visible:
                    self._axes_actor.VisibilityOn()
                else:
                    self._axes_actor.VisibilityOff()
            else:
                self._axes_actor.SetVisibility(1 if visible else 0)
        except Exception:
            pass
        self._plotter.render()

    def reset_camera(self):
        self._plotter.camera.position = self.DEFAULT_CAMERA_POSITION
        self._plotter.camera.focal_point = self.DEFAULT_CAMERA_FOCAL_POINT
        self._plotter.camera.up = self.DEFAULT_CAMERA_UP
        self._plotter.camera.view_angle = self.DEFAULT_CAMERA_VIEW_ANGLE
        self._plotter.camera.parallel_projection = self.DEFAULT_CAMERA_PARALLEL_PROJECTION
        self._plotter.render()

    def _clear_grid(self):
        for actor in self._grid_actors:
            self._plotter.remove_actor(actor)
        self._grid_actors = []