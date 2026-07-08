# core/pointcloud.py

from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QObject
from core.coredata import get_scene_manager
import asyncio
import numpy as np
import open3d as o3d
import yaml
import copy
import pymeshlab

from core.executor import Executor
from logger import get_logger

MERGE_CONFIG = {
    'dedup_voxel': None,
    'final_voxel': None,
    'dbscan_eps': 0.02,
    'dbscan_min_pts': 0.0005,
    'dbscan_ds_factor': 500,
    'sor_neighbors': 20,
    'sor_std': 2.0,
    'normal_neighbors': 30,
    'normal_angle': 20.0,
    'ror_neighbors': 16,
    'ror_radius': None,
}

MESH_CONFIG = {
    'density_quantile': 0.01,
    'poisson_width': 0,
    'poisson_scale': 1.1,
    'poisson_linear_fit': False,
    'normal_search_ratio': 100,
}

class PointcloudAPI(QObject, Executor):

    def __init__(self, signal_router=None, worker=None, parent=None):
        QObject.__init__(self, parent)
        Executor.__init__(self)

        self.signal_router = signal_router
        self.worker = worker
        self.logger = get_logger()
        self.pending_import = None

        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("PointCloud API initialized")

    def _setup_signal_handlers(self):
        self.signal_router.subscribe('pointcloud.do_analyze_plane', self.do_analyze_plane, 'PointcloudAPI')
        self.signal_router.subscribe('pointcloud.do_remove_plane', self.do_remove_plane, 'PointcloudAPI')
        self.signal_router.subscribe('pointcloud.do_remove_plane_preview', self.do_remove_plane_preview, 'PointcloudAPI')
        self.signal_router.subscribe('pointcloud.do_align_clouds', self.do_align_clouds, 'PointcloudAPI')
        self.signal_router.subscribe('pointcloud.do_merge_clouds', self.do_merge_clouds, 'PointcloudAPI')
        self.signal_router.subscribe('pointcloud.do_generate_mesh', self.do_generate_mesh, 'PointcloudAPI')
        self.signal_router.subscribe('project.done_import', self.on_done_import, 'PointcloudAPI')
        self.signal_router.subscribe('transform.done_apply_transform', self.on_transform_applied, 'PointcloudAPI')
        self.signal_router.subscribe('scene.render_data_updated', self.on_render_data_updated, 'PointcloudAPI')

    # Utility methods

    def _get_unique_output_path(self, base_path: Path) -> Path:
        if not base_path.exists():
            return base_path

        stem = base_path.stem
        suffix = base_path.suffix
        parent = base_path.parent

        counter = 1
        while counter < 100:
            new_path = parent / f"{stem}_{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1

        return base_path

    def _save_yaml(self, path: Path, params: dict):
        try:
            with open(path, 'w') as f:
                yaml.dump(params, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"Saved parameters to {path}")
        except IOError as e:
            self.logger.error(f"Failed to save YAML: {e}")
            raise

    def _load_yaml(self, path: Path) -> dict:
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except (FileNotFoundError, yaml.YAMLError) as e:
            self.logger.error(f"Failed to load YAML: {e}")
            raise

    def _find_stage1_yaml(self, source_dir: Path) -> Optional[Path]:
        yaml_path = source_dir / "1.stage1_params.yaml"
        if yaml_path.exists():
            return yaml_path
        return None

    def _find_ply_by_obj_name(self, directory: Path, obj_name: str) -> Path:
        ply_path = directory / f"{obj_name}.ply"

        if ply_path.exists():
            return ply_path

        error_msg = (
            f"PLY file not found for object '{obj_name}'\n"
            f"Expected path: {ply_path}\n"
            f"Directory: {directory}"
        )
        self.logger.error(error_msg)
        raise FileNotFoundError(error_msg)

    def _get_merge_operations_suffix(self, cleaning_params: Dict[str, bool]) -> str:
        operations = []
        if cleaning_params.get('dbscan'):
            operations.append('dbscan')
        if cleaning_params.get('sor'):
            operations.append('sor')
        if cleaning_params.get('normal'):
            operations.append('normal')
        if cleaning_params.get('ror'):
            operations.append('ror')

        return '_'.join(operations) if operations else 'raw'

    def _compute_alignment_rotation(self, gravity_dir: np.ndarray) -> np.ndarray:
        target_gravity = np.array([0.0, 0.0, -1.0])

        gravity_normalized = gravity_dir / np.linalg.norm(gravity_dir)

        dot_product = np.clip(np.dot(gravity_normalized, target_gravity), -1.0, 1.0)

        if dot_product > 0.9999:
            return np.array([0.0, 0.0, 0.0])

        if dot_product < -0.9999:
            axis = np.array([1.0, 0.0, 0.0])
            angle = np.pi
        else:
            axis = np.cross(gravity_normalized, target_gravity)
            axis = axis / np.linalg.norm(axis)
            angle = np.arccos(dot_product)

        c = np.cos(angle)
        s = np.sin(angle)
        t = 1 - c
        x, y, z = axis

        align_matrix = np.array([
            [t*x*x + c,    t*x*y - s*z,  t*x*z + s*y],
            [t*x*y + s*z,  t*y*y + c,    t*y*z - s*x],
            [t*x*z - s*y,  t*y*z + s*x,  t*z*z + c]
        ])

        return self._matrix_to_euler(align_matrix)

    def _euler_to_matrix(self, euler: np.ndarray) -> np.ndarray:
        rx, ry, rz = euler

        cx, sx = np.cos(rx), np.sin(rx)
        cy, sy = np.cos(ry), np.sin(ry)
        cz, sz = np.cos(rz), np.sin(rz)

        Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
        Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

        return Rz @ Ry @ Rx

    def _matrix_to_euler(self, matrix: np.ndarray) -> np.ndarray:
        sy = np.sqrt(matrix[0, 0]**2 + matrix[1, 0]**2)

        singular = sy < 1e-6

        if not singular:
            x = np.arctan2(matrix[2, 1], matrix[2, 2])
            y = np.arctan2(-matrix[2, 0], sy)
            z = np.arctan2(matrix[1, 0], matrix[0, 0])
        else:
            x = np.arctan2(-matrix[1, 2], matrix[1, 1])
            y = np.arctan2(-matrix[2, 0], sy)
            z = 0

        return np.array([x, y, z])

    def _compose_transform_matrix(self, location: np.ndarray, rotation: np.ndarray, scale: np.ndarray) -> np.ndarray:
        """Compose 4x4 transform matrix from location, rotation (euler), scale"""
        rot_matrix = self._euler_to_matrix(rotation)

        transform = np.eye(4)
        transform[:3, :3] = rot_matrix @ np.diag(scale)
        transform[:3, 3] = location

        return transform

    def _decompose_transform_matrix(self, matrix: np.ndarray) -> tuple:
        """Decompose 4x4 matrix to location, rotation (euler), scale"""
        location = matrix[:3, 3]

        rot_scale = matrix[:3, :3]
        scale_x = np.linalg.norm(rot_scale[:, 0])
        scale_y = np.linalg.norm(rot_scale[:, 1])
        scale_z = np.linalg.norm(rot_scale[:, 2])
        scale = np.array([scale_x, scale_y, scale_z])

        rot_matrix = rot_scale / scale
        rotation = self._matrix_to_euler(rot_matrix)

        return location, rotation, scale

    def do_analyze_plane(self, data: Dict[str, Any]):
        object_name = data.get('object_name')

        async def analyze_async():
            scene_object_manager = get_scene_manager()
            obj = scene_object_manager.get_object(object_name)

            if obj is None:
                self.logger.error(f"Object not found: {object_name}")
                self.signal_router.emit('pointcloud.done_analyze_plane', {
                    'success': False,
                    'yaml_path': '',
                    'error': f'Object not found: {object_name}'
                })
                return

            source_dir = Path(obj.source_directory)
            if not source_dir.exists():
                self.logger.error(f"Source directory not found: {source_dir}")
                self.signal_router.emit('pointcloud.done_analyze_plane', {
                    'success': False,
                    'yaml_path': '',
                    'error': 'Source directory not found'
                })
                return

            images_txt = source_dir / "images.txt"
            dense_ply = source_dir / "dense_points.ply"

            if not images_txt.exists():
                self.logger.error(f"Missing images.txt in {source_dir}")
                self.signal_router.emit('pointcloud.done_analyze_plane', {
                    'success': False,
                    'yaml_path': '',
                    'error': 'Missing images.txt'
                })
                return

            if not dense_ply.exists():
                self.logger.error(f"Missing dense_points.ply in {source_dir}")
                self.signal_router.emit('pointcloud.done_analyze_plane', {
                    'success': False,
                    'yaml_path': '',
                    'error': 'Missing dense_points.ply'
                })
                return

            output_yaml = source_dir / "1.stage1_params.yaml"

            self.logger.info(f"Starting plane analysis for {object_name}")

            try:
                loop = asyncio.get_event_loop()
                result, gravity_dir = await loop.run_in_executor(
                    None,
                    self._process_analyze_sync,
                    source_dir,
                    output_yaml
                )

                if result and gravity_dir is not None:
                    self.logger.info(f"Plane analysis complete for {object_name}")

                    new_rotation = self._compute_alignment_rotation(gravity_dir)

                    self.logger.info(
                        f"Gravity alignment: gravity_dir={gravity_dir.tolist()}, "
                        f"new_rotation={new_rotation.tolist()}"
                    )

                    self.pending_import = {
                        'operation': 'analyze',
                        'obj_name': object_name,
                        'yaml_path': str(output_yaml)
                    }

                    self.signal_router.emit('transform.apply_transform', {
                        'object_name': object_name,
                        'location': obj.location.tolist(),
                        'rotation': new_rotation.tolist(),
                        'scale': obj.scale.tolist()
                    })
                else:
                    self.logger.error(f"Plane analysis failed for {object_name}")
                    self.signal_router.emit('pointcloud.done_analyze_plane', {
                        'success': False,
                        'yaml_path': '',
                        'error': 'Analysis processing failed'
                    })
            except Exception as e:
                self.logger.error(f"Error in analyze: {e}", exc_info=True)
                self.signal_router.emit('pointcloud.done_analyze_plane', {
                    'success': False,
                    'yaml_path': '',
                    'error': str(e)
                })

        asyncio.create_task(analyze_async())

    def do_remove_plane(self, data: Dict[str, Any]):
        object_name = data.get('object_name')
        margin = data.get('margin')
        method = data.get('method')

        async def remove_async():
            scene_object_manager = get_scene_manager()
            obj = scene_object_manager.get_object(object_name)

            if obj is None:
                self.logger.error(f"Object not found: {object_name}")
                self.signal_router.emit('pointcloud.done_remove_plane', {
                    'success': False,
                    'error': f'Object not found: {object_name}'
                })
                return

            cached_location = obj.location.copy()
            cached_rotation = obj.rotation.copy()
            cached_scale = obj.scale.copy()

            source_dir = Path(obj.source_directory)
            if not source_dir.exists():
                self.logger.error(f"Source directory not found: {source_dir}")
                self.signal_router.emit('pointcloud.done_remove_plane', {
                    'success': False,
                    'error': 'Source directory not found'
                })
                return

            stage1_yaml = self._find_stage1_yaml(source_dir)
            if stage1_yaml is None:
                self.logger.warning("Stage1 params not found, using default plane")

            base_name = f"2.cleaned_m{margin}.ply"
            output_ply = source_dir / base_name
            output_ply = self._get_unique_output_path(output_ply)
            obj_name = output_ply.stem
            yaml_name = output_ply.stem.replace("cleaned", "removal") + ".yaml"
            output_yaml = output_ply.parent / yaml_name

            input_ply = source_dir / "dense_points.ply"

            if not input_ply.exists():
                self.logger.error(f"Input point cloud not found: {input_ply}")
                self.signal_router.emit('pointcloud.done_remove_plane', {
                    'success': False,
                    'error': 'Input point cloud not found'
                })
                return

            self.logger.info(f"Starting plane removal for {object_name}")

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._process_remove_sync,
                    input_ply,
                    stage1_yaml,
                    margin,
                    method,
                    output_ply,
                    output_yaml
                )

                if result:
                    self.logger.info(f"Plane removal complete: {output_ply}")
                    self.pending_import = {
                        'operation': 'remove',
                        'obj_name': obj_name,
                        'location': cached_location,
                        'rotation': cached_rotation,
                        'scale': cached_scale,
                        'import_status': 'pending'
                    }
                    self.signal_router.emit('project.do_import', {
                        'file_path': str(output_ply)
                    })
                else:
                    self.logger.error(f"Plane removal failed for {object_name}")
                    self.signal_router.emit('pointcloud.done_remove_plane', {
                        'success': False,
                        'error': 'Removal processing failed'
                    })
            except Exception as e:
                self.logger.error(f"Error in remove: {e}", exc_info=True)
                self.signal_router.emit('pointcloud.done_remove_plane', {
                    'success': False,
                    'error': str(e)
                })

        asyncio.create_task(remove_async())

    def do_remove_plane_preview(self, data: Dict[str, Any]):
        object_name = data.get('object_name')

        async def preview_async():
            scene_object_manager = get_scene_manager()
            obj = scene_object_manager.get_object(object_name)

            recommended_margin = 0.05

            if obj is not None:
                source_dir = Path(obj.source_directory)
                stage1_yaml = self._find_stage1_yaml(source_dir)

                if stage1_yaml and stage1_yaml.exists():
                    try:
                        params = self._load_yaml(stage1_yaml)
                        recommended_margin = params.get('recommended_margin', 0.05)
                    except Exception:
                        pass

            self.signal_router.emit('pointcloud.done_remove_plane_preview', {
                'recommended_margin': recommended_margin
            })

        asyncio.create_task(preview_async())

    def do_align_clouds(self, data: Dict[str, Any]):
        source_object = data.get('source_object')
        target_object = data.get('target_object')

        async def align_async():
            scene_object_manager = get_scene_manager()
            source_obj = scene_object_manager.get_object(source_object)
            target_obj = scene_object_manager.get_object(target_object)

            if source_obj is None:
                self.logger.error(f"Source object not found: {source_object}")
                self.signal_router.emit('pointcloud.done_align_clouds', {
                    'success': False,
                    'error': f'Source object not found: {source_object}'
                })
                return

            if target_obj is None:
                self.logger.error(f"Target object not found: {target_object}")
                self.signal_router.emit('pointcloud.done_align_clouds', {
                    'success': False,
                    'error': f'Target object not found: {target_object}'
                })
                return

            source_dir = Path(source_obj.source_directory)
            target_dir = Path(target_obj.source_directory)

            try:
                source_ply = self._find_ply_by_obj_name(source_dir, source_object)
            except FileNotFoundError as e:
                self.logger.error(f"Source file lookup failed: {e}")
                self.signal_router.emit('pointcloud.done_align_clouds', {
                    'success': False,
                    'error': f'Source PLY not found: {source_object}.ply'
                })
                return

            try:
                target_ply = self._find_ply_by_obj_name(target_dir, target_object)
            except FileNotFoundError as e:
                self.logger.error(f"Target file lookup failed: {e}")
                self.signal_router.emit('pointcloud.done_align_clouds', {
                    'success': False,
                    'error': f'Target PLY not found: {target_object}.ply'
                })
                return

            source_transform = {
                'location': np.array(source_obj.location),
                'rotation': np.array(source_obj.rotation),
                'scale': np.array(source_obj.scale)
            }
            target_transform = {
                'location': np.array(target_obj.location),
                'rotation': np.array(target_obj.rotation),
                'scale': np.array(target_obj.scale)
            }

            self.logger.info(f"Aligning: {source_object} -> {target_object} (source moves)")

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._compute_alignment,
                    source_ply,
                    target_ply,
                    source_transform,
                    target_transform
                )

                if result is None:
                    self.logger.error("Alignment computation failed")
                    self.signal_router.emit('pointcloud.done_align_clouds', {
                        'success': False,
                        'error': 'Alignment computation failed'
                    })
                    return

                new_location = result['location']
                new_rotation = result['rotation']
                new_scale = result['scale']
                fitness = result['fitness']
                rmse = result['rmse']

                self.logger.info(f"Alignment complete: fitness={fitness:.4f}, rmse={rmse:.6f}")

                yaml_path = source_dir / "3.alignment_params.yaml"
                try:
                    self._save_yaml(yaml_path, {
                        'source_object': source_object,
                        'target_object': target_object,
                        'moved_object': source_object,
                        'fitness': float(fitness),
                        'rmse': float(rmse),
                        'new_transform': {
                            'location': new_location.tolist(),
                            'rotation': new_rotation.tolist(),
                            'scale': new_scale.tolist()
                        }
                    })
                except IOError as e:
                    self.logger.warning(f"Failed to save alignment params: {e}")

                self.signal_router.emit('transform.apply_transform', {
                    'object_name': source_object,
                    'location': new_location.tolist(),
                    'rotation': new_rotation.tolist(),
                    'scale': new_scale.tolist()
                })

                self.pending_import = {
                    'operation': 'align',
                    'source_object': source_object
                }

            except Exception as e:
                self.logger.error(f"Error in align: {e}", exc_info=True)
                self.signal_router.emit('pointcloud.done_align_clouds', {
                    'success': False,
                    'error': str(e)
                })

        asyncio.create_task(align_async())

    def do_merge_clouds(self, data: Dict[str, Any]):
        source_object = data.get('source_object')
        target_object = data.get('target_object')
        cleaning_params = data.get('cleaning_params', {})

        async def merge_async():
            scene_object_manager = get_scene_manager()
            source_obj = scene_object_manager.get_object(source_object)
            target_obj = scene_object_manager.get_object(target_object)

            if source_obj is None:
                self.logger.error(f"Source object not found: {source_object}")
                self.signal_router.emit('pointcloud.done_merge_clouds', {
                    'success': False,
                    'error': f'Source object not found: {source_object}'
                })
                return

            if target_obj is None:
                self.logger.error(f"Target object not found: {target_object}")
                self.signal_router.emit('pointcloud.done_merge_clouds', {
                    'success': False,
                    'error': f'Target object not found: {target_object}'
                })
                return

            source_dir = Path(source_obj.source_directory)
            target_dir = Path(target_obj.source_directory)
            source_transform = {
                'location': np.array(source_obj.location),
                'rotation': np.array(source_obj.rotation),
                'scale': np.array(source_obj.scale)
            }
            target_transform = {
                'location': np.array(target_obj.location),
                'rotation': np.array(target_obj.rotation),
                'scale': np.array(target_obj.scale)
            }

            try:
                source_ply = self._find_ply_by_obj_name(source_dir, source_object)
            except FileNotFoundError as e:
                self.logger.error(f"Source file lookup failed: {e}")
                self.signal_router.emit('pointcloud.done_merge_clouds', {
                    'success': False,
                    'error': f'Source PLY not found: {source_object}.ply'
                })
                return

            try:
                target_ply = self._find_ply_by_obj_name(target_dir, target_object)
            except FileNotFoundError as e:
                self.logger.error(f"Target file lookup failed: {e}")
                self.signal_router.emit('pointcloud.done_merge_clouds', {
                    'success': False,
                    'error': f'Target PLY not found: {target_object}.ply'
                })
                return

            output_dir = source_dir
            suffix = self._get_merge_operations_suffix(cleaning_params)
            base_name = f"4.merged_{suffix}.ply"
            output_ply = output_dir / base_name
            output_ply = self._get_unique_output_path(output_ply)
            output_filename = output_ply.name

            self.logger.info(f"Starting merge: {source_object} + {target_object}")

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._process_merge_sync,
                source_ply,
                target_ply,
                cleaning_params,
                output_dir,
                output_filename,
                source_object,
                target_object,
                source_transform,
                target_transform
            )

            if result is None:
                self.logger.error("Merge processing failed")
                self.signal_router.emit('pointcloud.done_merge_clouds', {
                    'success': False,
                    'error': 'Merge processing failed'
                })
                return

            self.logger.info(f"Merge complete: {result['ply_path']}")

            self.pending_import = {
                'operation': 'merge',
                'location': np.array([0.0, 0.0, 0.0]),
                'rotation': np.array([0.0, 0.0, 0.0]),
                'scale': np.array([1.0, 1.0, 1.0]),
                'import_status': 'pending'
            }

            self.signal_router.emit('project.do_import', {
                'file_path': str(result['ply_path'])
            })

        asyncio.create_task(merge_async())

    def do_generate_mesh(self, data: Dict[str, Any]):
        object_name = data.get('object_name')
        mesh_params = data.get('mesh_params', {})

        async def mesh_async():
            scene_object_manager = get_scene_manager()
            obj = scene_object_manager.get_object(object_name)

            if obj is None:
                self.logger.error(f"Object not found: {object_name}")
                self.signal_router.emit('pointcloud.done_generate_mesh', {
                    'success': False,
                    'error': f'Object not found: {object_name}'
                })
                return

            source_dir = Path(obj.source_directory)

            depth = mesh_params.get('depth', 9)
            simplify_target = mesh_params.get('simplify_target', 0)

            if simplify_target == 0:
                base_name = f"5.mesh_d{depth}.ply"
            else:
                base_name = f"5.mesh_d{depth}_s{simplify_target}.ply"

            output_ply = source_dir / base_name
            output_ply = self._get_unique_output_path(output_ply)

            yml_name = output_ply.stem.replace("mesh", "meshing") + ".yml"
            output_yml = output_ply.parent / yml_name

            try:
                input_ply = self._find_ply_by_obj_name(source_dir, object_name)
            except FileNotFoundError as e:
                self.logger.error(f"Input file lookup failed: {e}")
                self.signal_router.emit('pointcloud.done_generate_mesh', {
                    'success': False,
                    'error': f'Input PLY not found: {object_name}.ply'
                })
                return

            self.logger.info(f"Starting mesh generation for {object_name}")

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    self._process_mesh_sync,
                    input_ply,
                    mesh_params,
                    output_ply,
                    output_yml
                )

                if result:
                    self.logger.info(f"Mesh generation complete: {output_ply}")
                    self.pending_import = {
                        'operation': 'mesh',
                        'original_object': object_name,
                        'delete_original': False
                    }
                    self.signal_router.emit('project.do_import', {
                        'file_path': str(output_ply)
                    })
                else:
                    self.logger.error(f"Mesh generation failed")
                    self.signal_router.emit('pointcloud.done_generate_mesh', {
                        'success': False,
                        'error': 'Mesh processing failed'
                    })
            except Exception as e:
                self.logger.error(f"Error in mesh: {e}", exc_info=True)
                self.signal_router.emit('pointcloud.done_generate_mesh', {
                    'success': False,
                    'error': str(e)
                })

        asyncio.create_task(mesh_async())

    def on_done_import(self, data: Dict[str, Any]):
        if self.pending_import is None:
            return

        operation = self.pending_import.get('operation', 'unknown')
        success = data.get('success', False)

        self.logger.info(f"on_done_import: operation={operation}, success={success}")

        if success:
            self.pending_import['import_status'] = 'success'
        else:
            self.pending_import['import_status'] = 'failed'
            self.pending_import = None
            if operation == 'remove':
                self.signal_router.emit('pointcloud.done_remove_plane', {
                    'success': False,
                    'error': 'Import failed'
                })
            elif operation == 'mesh':
                self.signal_router.emit('pointcloud.done_generate_mesh', {
                    'success': False,
                    'mesh_file': '',
                    'error': 'Import failed'
                })
            return

    def on_render_data_updated(self, data: Dict[str, Any]):
        if self.pending_import is None:
            return

        operation = self.pending_import.get('operation')
        if operation not in ['remove', 'merge']:
            return

        import_status = self.pending_import.get('import_status')
        self.logger.info(f"on_render_data_updated: operation={operation}, import_status={import_status}")

        if import_status == 'pending':
            return
        elif import_status == 'failed':
            self.pending_import = None
            self.signal_router.emit('pointcloud.done_remove_plane', {
                'success': False,
                'error': 'Import failed'
            })
            return

        obj_name = self.pending_import.get('obj_name')
        if not obj_name:
            self.logger.warning("on_render_data_updated: obj_name missing from pending_import")
            return

        scene_object_manager = get_scene_manager()
        obj = scene_object_manager.get_object(obj_name)

        if obj is None:
            self.logger.warning(f"on_render_data_updated: object not found in scene: {obj_name}")
            return

        location = self.pending_import.get('location')
        rotation = self.pending_import.get('rotation')
        scale = self.pending_import.get('scale')

        if location is not None and rotation is not None and scale is not None:
            self.logger.info(
                f"on_render_data_updated: applying transform to {obj_name}: "
                f"loc={location.tolist()}, rot={rotation.tolist()}, scale={scale.tolist()}"
            )
            self.signal_router.emit('transform.apply_transform', {
                'object_name': obj_name,
                'location': location.tolist(),
                'rotation': rotation.tolist(),
                'scale': scale.tolist()
            })
        else:
            self.logger.warning(
                f"on_render_data_updated: transform fields missing for {obj_name}: "
                f"location={location}, rotation={rotation}, scale={scale}"
            )

    def on_transform_applied(self, data: Dict[str, Any]):
        if self.pending_import is None:
            self.logger.warning("on_transform_applied: received signal but pending_import is None")
            return

        operation = self.pending_import.get('operation')
        success = data.get('success', False)
        error = data.get('error', '')

        self.logger.info(f"on_transform_applied: operation={operation}, success={success}, error='{error}'")

        if operation == 'remove':
            self.pending_import = None
            self.signal_router.emit('pointcloud.done_remove_plane', {
                'success': success,
                'error': error
            })
        elif operation == 'analyze':
            yaml_path = self.pending_import.get('yaml_path', '')
            self.pending_import = None
            self.signal_router.emit('pointcloud.done_analyze_plane', {
                'success': success,
                'yaml_path': yaml_path if success else '',
                'error': error
            })
        elif operation == 'align':
            self.pending_import = None
            self.signal_router.emit('pointcloud.done_align_clouds', {
                'success': success,
                'error': error
            })
        elif operation == 'merge':
            self.pending_import = None
            self.signal_router.emit('pointcloud.done_merge_clouds', {
                'success': success,
                'error': error
            })

    def _process_analyze_sync(self, source_dir: Path, output_yaml: Path) -> bool:
        images_txt = source_dir / "images.txt"
        dense_ply = source_dir / "dense_points.ply"

        cameras = []
        try:
            with open(images_txt, 'r') as f:
                lines = f.readlines()
        except IOError:
            self.logger.error(f"Failed to read images.txt: {images_txt}")
            return False, None

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#') or len(line) == 0:
                i += 1
                continue

            parts = line.split()
            if len(parts) >= 10:
                qw, qx, qy, qz = map(float, parts[1:5])
                tx, ty, tz = map(float, parts[5:8])
                cameras.append({
                    'quat': np.array([qw, qx, qy, qz]),
                    'trans': np.array([tx, ty, tz])
                })
                i += 2
            else:
                i += 1

        if len(cameras) == 0:
            self.logger.error(f"No valid camera entries found in {images_txt}")
            return False, None

        def quaternion_to_rotation_matrix(q):
            qw, qx, qy, qz = q
            R = np.array([
                [1 - 2*(qy**2 + qz**2), 2*(qx*qy - qw*qz), 2*(qx*qz + qw*qy)],
                [2*(qx*qy + qw*qz), 1 - 2*(qx**2 + qz**2), 2*(qy*qz - qw*qx)],
                [2*(qx*qz - qw*qy), 2*(qy*qz + qw*qx), 1 - 2*(qx**2 + qy**2)]
            ])
            return R

        camera_up_vectors = []
        for cam in cameras:
            R = quaternion_to_rotation_matrix(cam['quat'])
            camera_y = R[1, :]
            camera_up_vectors.append(-camera_y)

        camera_up_vectors = np.array(camera_up_vectors)
        mean_up = camera_up_vectors.mean(axis=0)
        mean_up_normalized = mean_up / np.linalg.norm(mean_up)
        gravity_direction = -mean_up_normalized

        self.logger.info(f"Parsed {len(cameras)} cameras, gravity_direction={gravity_direction.tolist()}")

        pcd = o3d.io.read_point_cloud(str(dense_ply))
        if len(pcd.points) == 0:
            self.logger.error(f"Dense point cloud is empty: {dense_ply}")
            return False, None

        points = np.asarray(pcd.points)
        bbox_min = points.min(axis=0)
        bbox_max = points.max(axis=0)
        bbox_size = bbox_max - bbox_min
        bbox_diag = np.linalg.norm(bbox_size)

        voxel_size = bbox_diag / 500
        pcd_down = pcd.voxel_down_sample(voxel_size)
        points_down = np.asarray(pcd_down.points)

        g_norm = gravity_direction / np.linalg.norm(gravity_direction)
        h = points @ g_norm

        h_range_total = float(h.max() - h.min())
        bucket_width_est = h_range_total / 50.0
        global_distance_threshold = bbox_diag / 50

        self.logger.info(
            f"Point cloud: n={len(points)}, bbox_diag={bbox_diag:.4f}, "
            f"global_dist_thresh={global_distance_threshold:.4f}, "
            f"h_range={h_range_total:.4f}, bucket_width={bucket_width_est:.4f}"
        )

        rp_candidates = self._compute_radial_profile(points, gravity_direction, source_dir)
        self.logger.info(f"Radial profile returned {len(rp_candidates)} candidates")

        _MIN_SUBSET_POINTS = 500
        _GRAVITY_ALIGN_THRESH = 0.7

        for c in rp_candidates:
            c['n_background_points'] = 0
            c['subset_failure'] = 'not_attempted'
            c['ransac_inlier_ratio'] = float('nan')
            c['ransac_gravity_alignment'] = float('nan')
            c['ransac_plane_model'] = None
            c['computed_margin'] = float('nan')
            c['bg_sd_pct99'] = float('nan')
            c['h_bg_min'] = float('nan')
            c['h_bg_max'] = float('nan')
            c['selected_as_best'] = 0

            if c.get('failure_reason', ''):
                c['subset_failure'] = f"profile_failure:{c['failure_reason']}"
                self.logger.debug(
                    f"Candidate ({c['metric']},{c['strategy']}) skipped: {c['failure_reason']}"
                )
                continue

            h_low_raw = c.get('selected_h_low', '')
            h_high_raw = c.get('selected_h_high', '')
            if h_low_raw == '' or h_high_raw == '':
                c['subset_failure'] = 'no_h_range'
                continue

            h_bg_min = min(float(h_low_raw), float(h_high_raw))
            h_bg_max = max(float(h_low_raw), float(h_high_raw))
            c['h_bg_min'] = h_bg_min
            c['h_bg_max'] = h_bg_max

            bg_mask = (h >= h_bg_min) & (h <= h_bg_max)
            n_bg = int(bg_mask.sum())
            c['n_background_points'] = n_bg

            self.logger.debug(
                f"Candidate ({c['metric']},{c['strategy']}): "
                f"h_bg=[{h_bg_min:.4f},{h_bg_max:.4f}], n_bg={n_bg}"
            )

            if n_bg < _MIN_SUBSET_POINTS:
                c['subset_failure'] = f'insufficient_subset_points:{n_bg}'
                self.logger.warning(
                    f"Candidate ({c['metric']},{c['strategy']}): "
                    f"only {n_bg} background points, need {_MIN_SUBSET_POINTS}"
                )
                continue

            bg_points = points[bg_mask]
            bg_pcd = o3d.geometry.PointCloud()
            bg_pcd.points = o3d.utility.Vector3dVector(bg_points)

            h_thickness = abs(h_bg_max - h_bg_min)
            local_threshold = h_thickness / 4.0 if h_thickness > 0 else global_distance_threshold
            sub_dist_thresh = float(np.clip(local_threshold, 0.001, global_distance_threshold))

            self.logger.debug(
                f"Candidate ({c['metric']},{c['strategy']}): "
                f"subset RANSAC on {n_bg} pts, "
                f"dist_thresh={sub_dist_thresh:.4f} "
                f"(local={local_threshold:.4f}, global={global_distance_threshold:.4f})"
            )

            try:
                sub_plane, sub_inliers = bg_pcd.segment_plane(
                    distance_threshold=sub_dist_thresh,
                    ransac_n=3,
                    num_iterations=1000
                )
                sa, sb, sc, sd = sub_plane
                sub_normal = np.array([sa, sb, sc])
                sub_normal_norm = np.linalg.norm(sub_normal)
                sub_normal_normalized = sub_normal / sub_normal_norm
                sub_inlier_ratio = len(sub_inliers) / n_bg
                sub_gravity_align = abs(np.dot(sub_normal_normalized, g_norm))

                if np.dot(sub_normal_normalized, g_norm) > 0:
                    sa, sb, sc, sd = -sa, -sb, -sc, -sd
                    sub_normal_normalized = -sub_normal_normalized

                c['ransac_plane_model'] = [float(sa), float(sb), float(sc), float(sd)]
                c['ransac_inlier_ratio'] = float(sub_inlier_ratio)
                c['ransac_gravity_alignment'] = float(sub_gravity_align)
                c['subset_failure'] = ''

                bg_sds = (bg_points @ np.array([sa, sb, sc]) + sd) / sub_normal_norm
                pct99_bg_sd = float(np.percentile(bg_sds, 99))
                margin_raw = pct99_bg_sd + (bucket_width_est / 2.0)
                margin_src = f'bg_pct99={pct99_bg_sd:.4f}+half_bkt={bucket_width_est/2:.4f}'

                c['bg_sd_pct99'] = pct99_bg_sd
                c['computed_margin'] = float(np.clip(margin_raw, 0.005, 0.50))

                self.logger.info(
                    f"Candidate ({c['metric']},{c['strategy']}): "
                    f"inlier_ratio={sub_inlier_ratio:.4f}, "
                    f"gravity_alignment={sub_gravity_align:.4f}, "
                    f"n_bg={n_bg}, h_bg=[{h_bg_min:.4f},{h_bg_max:.4f}], "
                    f"bg_sd_pct99={pct99_bg_sd:.4f}, "
                    f"margin_raw={margin_raw:.4f}, "
                    f"computed_margin={c['computed_margin']:.4f} [{margin_src}]"
                )

            except Exception as e:
                c['subset_failure'] = 'ransac_exception'
                self.logger.warning(
                    f"Candidate ({c['metric']},{c['strategy']}): RANSAC failed: {e}"
                )

        valid_candidates = [
            c for c in rp_candidates
            if c.get('subset_failure', 'not_attempted') == ''
            and float(c.get('ransac_gravity_alignment', 0.0)) >= _GRAVITY_ALIGN_THRESH
        ]

        self.logger.info(
            f"Candidate selection: {len(valid_candidates)} valid "
            f"(gravity_align>={_GRAVITY_ALIGN_THRESH}) "
            f"out of {len(rp_candidates)} total"
        )

        plane_method = 'gravity_projection'
        best_margin = 0.05
        a, b, c, d = 0.0, 0.0, 1.0, 0.0

        if valid_candidates:
            h_min_boundary = min(
                c['h_bg_min'] for c in valid_candidates
                if not (isinstance(c['h_bg_min'], float) and np.isnan(c['h_bg_min']))
            )
            _AGGR_ALPHA = 0.1

            def _score(c):
                ir = float(c.get('ransac_inlier_ratio', 0.0))
                hb = float(c.get('h_bg_min', h_min_boundary))
                penalty = (hb - h_min_boundary) / h_range_total if h_range_total > 0 else 0.0
                return ir - _AGGR_ALPHA * penalty

            best = max(valid_candidates, key=_score)
            best['selected_as_best'] = 1

            a, b, c, d = best['ransac_plane_model']
            best_margin = best['computed_margin']
            plane_method = 'radial_profile_ransac'

            self.logger.info(
                f"Best candidate: ({best['metric']},{best['strategy']}), "
                f"inlier_ratio={best['ransac_inlier_ratio']:.4f}, "
                f"gravity_alignment={best['ransac_gravity_alignment']:.4f}, "
                f"plane_model={[round(x, 4) for x in [a, b, c, d]]}, "
                f"h_bg_min={best.get('h_bg_min', '')}, "
                f"computed_margin={best_margin:.4f}"
            )

        else:
            self.logger.warning(
                f"No valid radial-profile candidates "
                f"(all failed or gravity_align<{_GRAVITY_ALIGN_THRESH}). "
                f"Attempting fallbacks."
            )

            fallback_with_h = [
                x for x in rp_candidates if x.get('selected_h_low', '') != ''
            ]

            if fallback_with_h:
                fb = max(fallback_with_h, key=lambda x: x.get('n_background_points', 0))
                h_boundary = float(fb.get('h_bg_min') or fb.get('selected_h_low', 0))
                up = -g_norm
                a, b, c, d = float(up[0]), float(up[1]), float(up[2]), float(h_boundary)
                plane_method = 'radial_profile_gravity'
                best_margin = float(np.clip(bucket_width_est * 0.5, 0.01, 0.40))
                self.logger.info(
                    f"Fallback A (radial_profile_gravity): "
                    f"h_boundary={h_boundary:.4f} "
                    f"from ({fb['metric']},{fb['strategy']}), "
                    f"n_bg={fb.get('n_background_points', 0)}, "
                    f"margin={best_margin:.4f}"
                )
            else:
                up = -g_norm
                proj_up = points_down @ up
                table_height_proj = float(np.percentile(proj_up, 2))
                a, b, c, d = float(up[0]), float(up[1]), float(up[2]), -table_height_proj
                heights_fb = points_down @ up - table_height_proj
                best_margin = float(np.clip(float(np.percentile(heights_fb, 7.5)), 0.02, 0.40))
                plane_method = 'gravity_projection'
                self.logger.info(
                    f"Fallback B (gravity_projection): "
                    f"table_height={table_height_proj:.4f}, "
                    f"margin={best_margin:.4f}"
                )

        pm_normal = np.array([a, b, c])
        if np.linalg.norm(pm_normal) > 0:
            pm_normal_normalized = pm_normal / np.linalg.norm(pm_normal)
            if np.dot(pm_normal_normalized, g_norm) > 0:
                a, b, c, d = -a, -b, -c, -d
                self.logger.info("Sign flip applied to plane normal")

        plane_model_final = [float(a), float(b), float(c), float(d)]

        margin_candidates_list = [
            0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10,
            0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20,
            0.22, 0.25, 0.30, 0.35, 0.40
        ]
        pm_n_arr = np.array([a, b, c])
        pm_n_norm = float(np.linalg.norm(pm_n_arr))
        plane_model_final = [float(a), float(b), float(c), float(d)]
        margin_scores = []
        for m in margin_candidates_list:
            sds = (points_down @ pm_n_arr + d) / pm_n_norm
            retention = float(np.sum(sds > m) / len(points_down))
            margin_scores.append({'margin': float(m), 'retention': retention})

        check_sds = (points_down @ pm_n_arr + d) / pm_n_norm
        retention_at_best = float(np.sum(check_sds > best_margin) / len(points_down))
        self.logger.info(
            f"Retention at recommended_margin={best_margin:.4f}: "
            f"{retention_at_best:.4f} ({int(retention_at_best * len(points_down))}/{len(points_down)} downsampled pts)"
        )

        alternatives = [
            float(np.clip(best_margin * 0.5, 0.005, 0.50)),
            float(best_margin),
            float(np.clip(best_margin * 1.5, 0.005, 0.50)),
        ]

        enriched_path = source_dir / "1.plane_candidates.csv"
        import csv
        with open(enriched_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'metric', 'strategy', 'failure_reason',
                'selected_bucket_start', 'selected_bucket_end',
                'selected_h_low', 'selected_h_high',
                'h_bg_min', 'h_bg_max',
                'n_background_points', 'subset_failure',
                'ransac_inlier_ratio', 'ransac_gravity_alignment',
                'ransac_plane_model', 'bg_sd_pct99', 'computed_margin',
                'selected_as_best'
            ])
            for cand in rp_candidates:
                ir = cand.get('ransac_inlier_ratio', float('nan'))
                ga = cand.get('ransac_gravity_alignment', float('nan'))
                cm = cand.get('computed_margin', float('nan'))
                pct99 = cand.get('bg_sd_pct99', float('nan'))
                hbmin = cand.get('h_bg_min', float('nan'))
                hbmax = cand.get('h_bg_max', float('nan'))

                def _fmt(v):
                    return '' if (isinstance(v, float) and np.isnan(v)) else round(v, 6)

                writer.writerow([
                    cand.get('metric', ''),
                    cand.get('strategy', ''),
                    cand.get('failure_reason', ''),
                    cand.get('selected_bucket_start', ''),
                    cand.get('selected_bucket_end', ''),
                    cand.get('selected_h_low', ''),
                    cand.get('selected_h_high', ''),
                    _fmt(hbmin),
                    _fmt(hbmax),
                    cand.get('n_background_points', ''),
                    cand.get('subset_failure', ''),
                    _fmt(ir),
                    _fmt(ga),
                    str(cand['ransac_plane_model']) if cand.get('ransac_plane_model') else '',
                    _fmt(pct99),
                    _fmt(cm),
                    cand.get('selected_as_best', 0),
                ])
        self.logger.info(f"Enriched candidates CSV written: {enriched_path}")

        result = {
            'version': '1.2',
            'plane_method': plane_method,
            'plane_model': plane_model_final,
            'gravity_direction': gravity_direction.tolist(),
            'recommended_margin': float(best_margin),
            'alternative_margins': alternatives,
            'margin_test_results': margin_scores,
            'n_points_original': int(len(pcd.points)),
            'bbox_diagonal': float(bbox_diag)
        }

        try:
            self._save_yaml(output_yaml, result)
        except IOError:
            self.logger.error(f"Failed to save analysis YAML: {output_yaml}")
            return False, None

        self.logger.info(
            f"Plane analysis saved: method={plane_method}, "
            f"plane_model={[round(x, 4) for x in plane_model_final]}, "
            f"recommended_margin={best_margin:.4f}, "
            f"n_points={len(pcd.points)}, bbox_diag={bbox_diag:.4f}"
        )

        return True, gravity_direction

    def _process_remove_sync(self, input_ply: Path, stage1_yaml: Optional[Path],
                            margin: float, method: str, output_ply: Path,
                            output_yaml: Path) -> bool:
        pcd = o3d.io.read_point_cloud(str(input_ply))
        if len(pcd.points) == 0:
            self.logger.error(f"Input point cloud is empty: {input_ply}")
            return False

        n_original = len(pcd.points)
        self.logger.info(f"Remove plane: input={input_ply.name}, n_points={n_original}, margin={margin}, method={method}")

        if stage1_yaml is not None:
            try:
                params = self._load_yaml(stage1_yaml)
                plane_model = params['plane_model']
                plane_method = params.get('plane_method', 'unknown')
                self.logger.info(
                    f"Loaded stage1 params from {stage1_yaml.name}: "
                    f"plane_method={plane_method}, plane_model={[round(x,4) for x in plane_model]}"
                )
            except (IOError, KeyError) as e:
                self.logger.warning(f"Failed to load stage1 YAML ({e}), using default plane y=0")
                plane_model = [0, 1, 0, 0]
        else:
            self.logger.warning("No stage1 YAML provided, using default plane y=0")
            plane_model = [0, 1, 0, 0]

        a, b, c, d = plane_model
        points = np.asarray(pcd.points)
        normal_norm = np.linalg.norm([a, b, c])

        signed_distances = (points @ np.array([a, b, c]) + d) / normal_norm

        self.logger.info(
            f"Signed distances: min={signed_distances.min():.4f}, "
            f"max={signed_distances.max():.4f}, "
            f"mean={signed_distances.mean():.4f}, "
            f"pct5={float(np.percentile(signed_distances, 5)):.4f}, "
            f"pct95={float(np.percentile(signed_distances, 95)):.4f}"
        )

        keep_mask = signed_distances > margin
        n_kept = int(np.sum(keep_mask))
        n_removed = n_original - n_kept
        self.logger.info(
            f"Plane cut at margin={margin}: keeping {n_kept}/{n_original} points "
            f"({100*n_kept/n_original:.1f}%), removed {n_removed}"
        )

        pcd_no_table = pcd.select_by_index(np.where(keep_mask)[0])

        if len(pcd_no_table.points) == 0:
            self.logger.error("Zero points remain after plane cut - margin too large or plane model incorrect")
            return False

        if method == 'dbscan':
            pcd_clean = self._remove_outliers_dbscan(pcd_no_table)
        else:
            pcd_clean = self._remove_outliers_statistical(pcd_no_table)

        if pcd_clean is None or len(pcd_clean.points) == 0:
            self.logger.error(f"Outlier removal ({method}) produced empty cloud from {n_kept} input points")
            return False

        n_final = len(pcd_clean.points)
        self.logger.info(
            f"Outlier removal ({method}): {n_kept} -> {n_final} points "
            f"({100*n_final/n_original:.1f}% of original)"
        )

        o3d.io.write_point_cloud(str(output_ply), pcd_clean)
        self.logger.info(f"Written cleaned cloud: {output_ply.name} ({n_final} points)")

        params = {
            'input_file': input_ply.name,
            'margin': float(margin),
            'method': method,
            'plane_params_file': stage1_yaml.name if stage1_yaml else None,
            'input_points': n_original,
            'output_points': n_final,
            'retention_rate': float(n_final / n_original)
        }

        try:
            self._save_yaml(output_yaml, params)
        except IOError:
            self.logger.error(f"Failed to save removal YAML: {output_yaml}")
            return False

        return True

    def _remove_outliers_dbscan(self, pcd):
        points_original = np.asarray(pcd.points)
        n_original = len(points_original)

        bbox_min = points_original.min(axis=0)
        bbox_max = points_original.max(axis=0)
        bbox_diag = np.linalg.norm(bbox_max - bbox_min)

        downsample_voxel = bbox_diag / 500
        pcd_down = pcd.voxel_down_sample(downsample_voxel)
        n_down = len(pcd_down.points)

        if n_down == 0:
            return None

        points_down = np.asarray(pcd_down.points)

        eps = bbox_diag * 0.02
        min_points = max(20, int(n_down * 0.0005))

        labels = np.array(pcd_down.cluster_dbscan(eps=eps, min_points=min_points, print_progress=False))

        unique_labels = set(labels)
        n_clusters = len(unique_labels) - (1 if -1 in unique_labels else 0)

        if n_clusters == 0:
            return None

        cluster_sizes = []
        for label in unique_labels:
            if label == -1:
                continue
            cluster_size = (labels == label).sum()
            cluster_sizes.append((label, cluster_size))

        cluster_sizes.sort(key=lambda x: x[1], reverse=True)
        main_label = cluster_sizes[0][0]

        main_mask_down = (labels == main_label)
        main_points_down = points_down[main_mask_down]

        pcd_main = o3d.geometry.PointCloud()
        pcd_main.points = o3d.utility.Vector3dVector(main_points_down)
        kdtree = o3d.geometry.KDTreeFlann(pcd_main)

        search_radius = downsample_voxel * 1.5
        keep_mask = np.zeros(n_original, dtype=bool)

        for j in range(n_original):
            k, idx, _ = kdtree.search_radius_vector_3d(pcd.points[j], search_radius)
            if k > 0:
                keep_mask[j] = True

        pcd_clean = pcd.select_by_index(np.where(keep_mask)[0])
        return pcd_clean

    def _remove_outliers_statistical(self, pcd):
        points = np.asarray(pcd.points)
        centroid = points.mean(axis=0)
        distances = np.linalg.norm(points - centroid, axis=1)

        q1 = np.percentile(distances, 25)
        q3 = np.percentile(distances, 75)
        iqr = q3 - q1

        threshold = q3 + 3.0 * iqr
        keep_mask = distances <= threshold

        pcd_clean = pcd.select_by_index(np.where(keep_mask)[0])
        return pcd_clean

    def _compute_radial_profile(self, points: np.ndarray, gravity_direction: np.ndarray,
                                output_dir: Path, n_buckets: int = 50) -> None:
        import csv

        n_total = len(points)
        n_min = max(10, int(n_total * 0.005))

        g = gravity_direction / np.linalg.norm(gravity_direction)

        h = points @ g

        h_min = float(h.min())
        h_max = float(h.max())
        h_range = h_max - h_min

        self.logger.info(
            f"Radial profile: n_total={n_total}, n_min={n_min}, "
            f"h_min={h_min:.4f}, h_max={h_max:.4f}, h_range={h_range:.4f}, "
            f"n_buckets={n_buckets}"
        )

        h_med = float(np.median(h))
        proj_along_g = np.outer(h, g)
        perp = points - proj_along_g
        c_perp = np.median(perp, axis=0)
        O = h_med * g + c_perp

        axis_proj = np.dot(points - O, g)
        radial_vecs = (points - O) - np.outer(axis_proj, g)
        r = np.linalg.norm(radial_vecs, axis=1)

        edges = np.linspace(h_min, h_max, n_buckets + 1)
        bucket_indices = np.searchsorted(edges, h, side='right') - 1
        bucket_indices = np.clip(bucket_indices, 0, n_buckets - 1)

        bucket_h_centers = 0.5 * (edges[:-1] + edges[1:])

        bucket_n = np.zeros(n_buckets, dtype=int)
        bucket_mean_r = np.full(n_buckets, np.nan)
        bucket_mean_r2 = np.full(n_buckets, np.nan)
        bucket_p90_r = np.full(n_buckets, np.nan)
        bucket_std_r = np.full(n_buckets, np.nan)
        bucket_combo = np.full(n_buckets, np.nan)

        for k in range(n_buckets):
            mask = bucket_indices == k
            nk = int(mask.sum())
            bucket_n[k] = nk
            if nk < n_min:
                continue
            rk = r[mask]
            mean_r = float(np.mean(rk))
            mean_r2 = float(np.mean(rk ** 2))
            p90_r = float(np.percentile(rk, 90))
            std_r = float(np.std(rk))
            combo = mean_r * float(np.log1p(nk))
            bucket_mean_r[k] = mean_r
            bucket_mean_r2[k] = mean_r2
            bucket_p90_r[k] = p90_r
            bucket_std_r[k] = std_r
            bucket_combo[k] = combo

        profile_path = output_dir / "1.radial_profile.csv"
        with open(profile_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'bucket_index', 'h_center', 'n_points',
                'mean_r', 'mean_r2', 'p90_r', 'combo',
                'valid', 'interpolated'
            ])
            for k in range(n_buckets):
                valid = 0 if np.isnan(bucket_mean_r[k]) else 1
                writer.writerow([
                    k,
                    round(bucket_h_centers[k], 6),
                    bucket_n[k],
                    '' if np.isnan(bucket_mean_r[k]) else round(bucket_mean_r[k], 6),
                    '' if np.isnan(bucket_mean_r2[k]) else round(bucket_mean_r2[k], 6),
                    '' if np.isnan(bucket_p90_r[k]) else round(bucket_p90_r[k], 6),
                    '' if np.isnan(bucket_combo[k]) else round(bucket_combo[k], 6),
                    valid,
                    0,
                ])

        self.logger.info(f"Radial profile written: {profile_path} ({n_buckets} buckets)")

        metrics = {
            'mean_r': bucket_mean_r,
            'mean_r2': bucket_mean_r2,
            'p90_r': bucket_p90_r,
            'combo': bucket_combo,
        }

        valid_any = ~np.isnan(bucket_mean_r)
        if valid_any.any():
            first_v = int(np.where(valid_any)[0][0])
            last_v = int(np.where(valid_any)[0][-1])
            for metric_arr in metrics.values():
                for k in range(first_v + 1, last_v):
                    if np.isnan(metric_arr[k]):
                        left = k - 1
                        while left > first_v and np.isnan(metric_arr[left]):
                            left -= 1
                        right = k + 1
                        while right < last_v and np.isnan(metric_arr[right]):
                            right += 1
                        if not np.isnan(metric_arr[left]) and not np.isnan(metric_arr[right]):
                            t = float(k - left) / float(right - left)
                            metric_arr[k] = metric_arr[left] + t * (metric_arr[right] - metric_arr[left])
            n_interpolated = int(sum(
                1 for k in range(first_v + 1, last_v)
                if bucket_n[k] < n_min
                and not np.isnan(bucket_mean_r[k])
            ))
            if n_interpolated > 0:
                self.logger.info(f"Interpolated {n_interpolated} isolated empty buckets in middle region")

        candidates = []

        for metric_name, metric_values in metrics.items():
            valid_mask = ~np.isnan(metric_values)
            valid_indices = np.where(valid_mask)[0]

            if len(valid_indices) < 2:
                candidates.append({
                    'metric': metric_name,
                    'strategy': 'A',
                    'failure_reason': 'insufficient_valid_buckets',
                    'selected_bucket_start': '',
                    'selected_bucket_end': '',
                    'selected_h_low': '',
                    'selected_h_high': '',
                })
                candidates.append({
                    'metric': metric_name,
                    'strategy': 'B',
                    'failure_reason': 'insufficient_valid_buckets',
                    'selected_bucket_start': '',
                    'selected_bucket_end': '',
                    'selected_h_low': '',
                    'selected_h_high': '',
                })
                candidates.append({
                    'metric': metric_name,
                    'strategy': 'C',
                    'failure_reason': 'insufficient_valid_buckets',
                    'selected_bucket_start': '',
                    'selected_bucket_end': '',
                    'selected_h_low': '',
                    'selected_h_high': '',
                })
                continue

            bottom_valid = valid_indices[-1]

            strategy_a = {'metric': metric_name, 'strategy': 'A', 'failure_reason': ''}
            if len(valid_indices) >= 2:
                vals = metric_values[valid_indices]
                diffs = np.abs(np.diff(vals))
                max_diff_pos = int(np.argmax(diffs))
                k_star = valid_indices[max_diff_pos + 1]
                bottom_range = valid_indices[valid_indices >= k_star]
                if len(bottom_range) == 0:
                    bottom_range = np.array([bottom_valid])
                strategy_a['selected_bucket_start'] = int(bottom_range[-1])
                strategy_a['selected_bucket_end'] = int(bottom_range[0])
                strategy_a['selected_h_low'] = round(float(bucket_h_centers[bottom_range[-1]]), 6)
                strategy_a['selected_h_high'] = round(float(bucket_h_centers[bottom_range[0]]), 6)
            else:
                strategy_a['failure_reason'] = 'insufficient_valid_buckets'
                strategy_a['selected_bucket_start'] = ''
                strategy_a['selected_bucket_end'] = ''
                strategy_a['selected_h_low'] = ''
                strategy_a['selected_h_high'] = ''
            candidates.append(strategy_a)

            strategy_b = {'metric': metric_name, 'strategy': 'B', 'failure_reason': ''}
            vals_valid = metric_values[valid_indices]
            if len(np.unique(vals_valid)) < 2:
                strategy_b['failure_reason'] = 'constant_metric'
                strategy_b['selected_bucket_start'] = ''
                strategy_b['selected_bucket_end'] = ''
                strategy_b['selected_h_low'] = ''
                strategy_b['selected_h_high'] = ''
            else:
                v_min = vals_valid.min()
                v_max = vals_valid.max()
                best_thresh = v_min
                best_score = -1.0
                for t_idx in range(len(vals_valid) - 1):
                    thresh = 0.5 * (vals_valid[t_idx] + vals_valid[t_idx + 1])
                    below = vals_valid[vals_valid <= thresh]
                    above = vals_valid[vals_valid > thresh]
                    if len(below) == 0 or len(above) == 0:
                        continue
                    w0 = len(below) / len(vals_valid)
                    w1 = len(above) / len(vals_valid)
                    var_between = w0 * w1 * (below.mean() - above.mean()) ** 2
                    if var_between > best_score:
                        best_score = var_between
                        best_thresh = thresh
                selected_b = []
                for idx in sorted(valid_indices, reverse=True):
                    if metric_values[idx] >= best_thresh:
                        selected_b.append(idx)
                    else:
                        break
                if len(selected_b) == 0:
                    selected_b = [int(bottom_valid)]
                strategy_b['selected_bucket_start'] = int(selected_b[-1])
                strategy_b['selected_bucket_end'] = int(selected_b[0])
                strategy_b['selected_h_low'] = round(float(bucket_h_centers[selected_b[-1]]), 6)
                strategy_b['selected_h_high'] = round(float(bucket_h_centers[selected_b[0]]), 6)
            candidates.append(strategy_b)

            strategy_c = {'metric': metric_name, 'strategy': 'C', 'failure_reason': ''}
            vals_valid = metric_values[valid_indices]
            window = 3
            if len(vals_valid) >= window:
                kernel = np.ones(window) / window
                smoothed = np.convolve(vals_valid, kernel, mode='same')
            else:
                smoothed = vals_valid.copy()
            peaks = []
            for i in range(1, len(smoothed) - 1):
                if smoothed[i] > smoothed[i - 1] and smoothed[i] > smoothed[i + 1]:
                    peaks.append(i)
            if len(peaks) < 2:
                strategy_c['failure_reason'] = 'single_peak' if len(peaks) == 1 else 'no_peaks'
                strategy_c['selected_bucket_start'] = ''
                strategy_c['selected_bucket_end'] = ''
                strategy_c['selected_h_low'] = ''
                strategy_c['selected_h_high'] = ''
            else:
                bottom_peak_pos = peaks[-1]
                first_valley = bottom_peak_pos
                for i in range(bottom_peak_pos - 1, -1, -1):
                    if smoothed[i] < smoothed[i + 1]:
                        first_valley = i
                    else:
                        break
                selected_c_valid = valid_indices[first_valley:bottom_peak_pos + 1]
                if len(selected_c_valid) == 0:
                    selected_c_valid = np.array([valid_indices[bottom_peak_pos]])
                strategy_c['selected_bucket_start'] = int(selected_c_valid[-1])
                strategy_c['selected_bucket_end'] = int(selected_c_valid[0])
                strategy_c['selected_h_low'] = round(float(bucket_h_centers[selected_c_valid[-1]]), 6)
                strategy_c['selected_h_high'] = round(float(bucket_h_centers[selected_c_valid[0]]), 6)
            candidates.append(strategy_c)

        candidates_path = output_dir / "1.radial_profile_candidates_raw.csv"
        with open(candidates_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'metric', 'strategy', 'failure_reason',
                'selected_bucket_start', 'selected_bucket_end',
                'selected_h_low', 'selected_h_high'
            ])
            for c in candidates:
                writer.writerow([
                    c['metric'], c['strategy'], c['failure_reason'],
                    c.get('selected_bucket_start', ''),
                    c.get('selected_bucket_end', ''),
                    c.get('selected_h_low', ''),
                    c.get('selected_h_high', ''),
                ])

        self.logger.info(
            f"Raw candidates written: {candidates_path} "
            f"({len(candidates)} entries = {len(metrics)} metrics x 3 strategies)"
        )

        return candidates

    def _remove_outliers_by_normal(self, pcd, nb_neighbors=None, angle_threshold=None):
        if nb_neighbors is None:
            nb_neighbors = MERGE_CONFIG['normal_neighbors']
        if angle_threshold is None:
            angle_threshold = MERGE_CONFIG['normal_angle']

        n_original = len(pcd.points)
        points = np.asarray(pcd.points)
        bbox_diag = np.linalg.norm(points.max(axis=0) - points.min(axis=0))

        if not pcd.has_normals():
            search_radius = bbox_diag / 200
            pcd.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(
                    radius=search_radius, max_nn=30
                )
            )

        normals = np.asarray(pcd.normals)
        kdtree = o3d.geometry.KDTreeFlann(pcd)

        angle_threshold_rad = np.deg2rad(angle_threshold)
        keep_mask = np.ones(n_original, dtype=bool)

        batch_size = 10000
        for i in range(0, n_original, batch_size):
            end_i = min(i + batch_size, n_original)

            for j in range(i, end_i):
                k, idx, _ = kdtree.search_knn_vector_3d(pcd.points[j], nb_neighbors + 1)

                if k < 2:
                    keep_mask[j] = False
                    continue

                current_normal = normals[j]
                neighbor_normals = normals[idx[1:]]

                dot_products = np.abs(np.dot(neighbor_normals, current_normal))
                dot_products = np.clip(dot_products, -1.0, 1.0)
                angles = np.arccos(dot_products)
                mean_angle = np.mean(angles)

                if mean_angle > angle_threshold_rad:
                    keep_mask[j] = False

        n_kept = np.sum(keep_mask)
        pcd_clean = pcd.select_by_index(np.where(keep_mask)[0])

        return pcd_clean

    def _remove_outliers_radius(self, pcd, nb_points=None, radius=None):
        if nb_points is None:
            nb_points = MERGE_CONFIG['ror_neighbors']

        points = np.asarray(pcd.points)
        bbox_diag = np.linalg.norm(points.max(axis=0) - points.min(axis=0))

        if radius is None:
            radius = bbox_diag / 500

        n_before = len(pcd.points)
        cl, ind = pcd.remove_radius_outlier(nb_points=nb_points, radius=radius)
        pcd_clean = pcd.select_by_index(ind)

        return pcd_clean

    def _compute_alignment(self, source_ply: Path, target_ply: Path,
                        source_transform: dict, target_transform: dict) -> Optional[dict]:
        """Compute alignment transform for source to match target"""

        self.logger.info("="*60)
        self.logger.info("ALIGNMENT DEBUG START")
        self.logger.info("="*60)

        self.logger.info(f"Source PLY: {source_ply.name}")
        self.logger.info(f"Target PLY: {target_ply.name}")
        self.logger.info(f"Source transform: loc={source_transform['location']}, rot={source_transform['rotation']}, scale={source_transform['scale']}")
        self.logger.info(f"Target transform: loc={target_transform['location']}, rot={target_transform['rotation']}, scale={target_transform['scale']}")

        pcd_source = o3d.io.read_point_cloud(str(source_ply))
        pcd_target = o3d.io.read_point_cloud(str(target_ply))

        if len(pcd_source.points) == 0 or len(pcd_target.points) == 0:
            self.logger.error("Empty point cloud detected")
            return None

        self.logger.info(f"Point cloud sizes: source={len(pcd_source.points)}, target={len(pcd_target.points)}")

        T_s = self._compose_transform_matrix(
            source_transform['location'],
            source_transform['rotation'],
            source_transform['scale']
        )
        T_t = self._compose_transform_matrix(
            target_transform['location'],
            target_transform['rotation'],
            target_transform['scale']
        )

        self.logger.info("Transform matrices:")
        self.logger.info(f"T_s determinant: {np.linalg.det(T_s[:3,:3]):.6f}")
        self.logger.info(f"T_t determinant: {np.linalg.det(T_t[:3,:3]):.6f}")

        T_relative = np.linalg.inv(T_t) @ T_s
        self.logger.info("T_relative (source in target coords):")
        for i in range(3):
            self.logger.info(f"  [{T_relative[i,0]:8.4f} {T_relative[i,1]:8.4f} {T_relative[i,2]:8.4f} {T_relative[i,3]:8.4f}]")

        pcd_source_in_target = pcd_source.transform(T_relative)

        points_source = np.asarray(pcd_source_in_target.points)
        points_target = np.asarray(pcd_target.points)

        source_center = points_source.mean(axis=0)
        target_center = points_target.mean(axis=0)
        center_distance = np.linalg.norm(source_center - target_center)

        self.logger.info(f"After transform to target coords:")
        self.logger.info(f"  Source center: [{source_center[0]:.4f}, {source_center[1]:.4f}, {source_center[2]:.4f}]")
        self.logger.info(f"  Target center: [{target_center[0]:.4f}, {target_center[1]:.4f}, {target_center[2]:.4f}]")
        self.logger.info(f"  Center distance: {center_distance:.4f}")

        bbox_source = points_source.max(axis=0) - points_source.min(axis=0)
        bbox_target = points_target.max(axis=0) - points_target.min(axis=0)
        avg_diag = (np.linalg.norm(bbox_source) + np.linalg.norm(bbox_target)) / 2

        voxel_size = avg_diag / 200
        self.logger.info(f"Voxel size for registration: {voxel_size:.6f}")
        self.logger.info(f"Center distance / avg_diag: {center_distance / avg_diag:.4f}")

        source_down = pcd_source_in_target.voxel_down_sample(voxel_size)
        target_down = pcd_target.voxel_down_sample(voxel_size)

        self.logger.info(f"Downsampled: source={len(source_down.points)}, target={len(target_down.points)}")

        source_down.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 2, max_nn=30)
        )
        target_down.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 2, max_nn=30)
        )

        source_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            source_down,
            o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 5, max_nn=100)
        )
        target_fpfh = o3d.pipelines.registration.compute_fpfh_feature(
            target_down,
            o3d.geometry.KDTreeSearchParamHybrid(radius=voxel_size * 5, max_nn=100)
        )

        self.logger.info(f"FPFH features: source_dim={source_fpfh.dimension()}, target_dim={target_fpfh.dimension()}")

        distance_threshold = voxel_size * 1.5
        self.logger.info(f"RANSAC distance threshold: {distance_threshold:.6f}")

        result_ransac = o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
            source_down, target_down, source_fpfh, target_fpfh, True,
            distance_threshold,
            o3d.pipelines.registration.TransformationEstimationPointToPoint(False),
            3,
            [
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
                o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(distance_threshold)
            ],
            o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999)
        )

        self.logger.info(f"RANSAC result: fitness={result_ransac.fitness:.6f}, rmse={result_ransac.inlier_rmse:.6f}")
        self.logger.info("RANSAC transformation:")
        for i in range(3):
            self.logger.info(f"  [{result_ransac.transformation[i,0]:8.4f} {result_ransac.transformation[i,1]:8.4f} {result_ransac.transformation[i,2]:8.4f} {result_ransac.transformation[i,3]:8.4f}]")

        if result_ransac.fitness < 0.05:
            self.logger.warning(f"Low RANSAC fitness: {result_ransac.fitness}")

        self.logger.info("Testing RANSAC vs Identity initial transforms")

        test_voxel = voxel_size
        source_test = pcd_source_in_target.voxel_down_sample(test_voxel)
        target_test = pcd_target.voxel_down_sample(test_voxel)

        source_test.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=test_voxel * 2, max_nn=30)
        )
        target_test.estimate_normals(
            search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=test_voxel * 2, max_nn=30)
        )

        test_identity = o3d.pipelines.registration.registration_icp(
            source_test, target_test,
            test_voxel * 2.0,
            np.eye(4),
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=10)
        )

        test_ransac = o3d.pipelines.registration.registration_icp(
            source_test, target_test,
            test_voxel * 2.0,
            result_ransac.transformation,
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=10)
        )

        self.logger.info(f"Identity init: fitness={test_identity.fitness:.6f}, rmse={test_identity.inlier_rmse:.6f}")
        self.logger.info(f"RANSAC init: fitness={test_ransac.fitness:.6f}, rmse={test_ransac.inlier_rmse:.6f}")

        if test_identity.inlier_rmse < test_ransac.inlier_rmse:
            self.logger.info("Using Identity transform (better rmse)")
            current_transform = np.eye(4)
        else:
            self.logger.info("Using RANSAC transform (better rmse)")
            current_transform = result_ransac.transformation

        voxel_sizes = [voxel_size, voxel_size * 0.6, voxel_size * 0.3]

        self.logger.info(f"Starting multi-scale ICP with {len(voxel_sizes)} scales")

        cumulative_scale = 1.0
        pcd_source_scaled = copy.deepcopy(pcd_source_in_target)

        for idx, vs in enumerate(voxel_sizes):
            source_down_icp = pcd_source_scaled.voxel_down_sample(vs)
            target_down_icp = pcd_target.voxel_down_sample(vs)

            source_down_icp.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=vs * 3, max_nn=30)
            )
            target_down_icp.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=vs * 3, max_nn=30)
            )

            result_icp = o3d.pipelines.registration.registration_icp(
                source_down_icp, target_down_icp,
                vs * 2.0,
                current_transform,
                o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=50)
            )

            current_transform = result_icp.transformation

            # Scale estimation through exhaustive testing
            scale_candidates = [0.95, 0.97, 0.99, 1.0, 1.01, 1.03, 1.05]
            best_scale = 1.0
            best_rmse = result_icp.inlier_rmse

            for test_scale in scale_candidates:
                test_source = copy.deepcopy(source_down_icp)
                test_source.scale(test_scale, center=test_source.get_center())

                test_result = o3d.pipelines.registration.registration_icp(
                    test_source, target_down_icp,
                    vs * 2.0,
                    current_transform,
                    o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                    o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=3)
                )

                if test_result.inlier_rmse < best_rmse:
                    best_rmse = test_result.inlier_rmse
                    best_scale = test_scale

            # Apply best scale to source point cloud
            if best_scale != 1.0:
                pcd_source_scaled.scale(best_scale, center=pcd_source_scaled.get_center())
                cumulative_scale *= best_scale
                cumulative_scale = np.clip(cumulative_scale, 0.8, 1.5)
                self.logger.info(f"ICP scale {idx+1}/{len(voxel_sizes)} (voxel={vs:.6f}): fitness={result_icp.fitness:.6f}, rmse={best_rmse:.6f}, best_scale={best_scale:.6f}, cumulative={cumulative_scale:.6f}")
            else:
                self.logger.info(f"ICP scale {idx+1}/{len(voxel_sizes)} (voxel={vs:.6f}): fitness={result_icp.fitness:.6f}, rmse={result_icp.inlier_rmse:.6f}, scale=1.0 (no adjustment)")

        T_align_local = current_transform
        self.logger.info("Final T_align_local (in target coords):")
        for i in range(3):
            self.logger.info(f"  [{T_align_local[i,0]:8.4f} {T_align_local[i,1]:8.4f} {T_align_local[i,2]:8.4f} {T_align_local[i,3]:8.4f}]")
        self.logger.info(f"Cumulative scale factor: {cumulative_scale:.6f}")

        self.logger.info("Computing final transform: T_source_new = T_t @ T_align_local @ inv(T_t) @ T_s")
        A = T_t @ T_align_local
        B = np.linalg.inv(T_t)
        C = B @ T_s
        T_source_new = A @ C

        self.logger.info("T_source_new:")
        for i in range(3):
            self.logger.info(f"  [{T_source_new[i,0]:8.4f} {T_source_new[i,1]:8.4f} {T_source_new[i,2]:8.4f} {T_source_new[i,3]:8.4f}]")

        new_location, new_rotation, new_scale = self._decompose_transform_matrix(T_source_new)

        # Apply cumulative scale adjustment
        new_scale = new_scale * cumulative_scale
        # Constrain to reasonable range relative to original scale
        new_scale = np.clip(new_scale, source_transform['scale'] * 0.8, source_transform['scale'] * 1.5)

        self.logger.info(f"Decomposed result:")
        self.logger.info(f"  new_location: [{new_location[0]:.6f}, {new_location[1]:.6f}, {new_location[2]:.6f}]")
        self.logger.info(f"  new_rotation: [{new_rotation[0]:.6f}, {new_rotation[1]:.6f}, {new_rotation[2]:.6f}]")
        self.logger.info(f"  new_scale: [{new_scale[0]:.6f}, {new_scale[1]:.6f}, {new_scale[2]:.6f}]")

        self.logger.info("="*60)
        self.logger.info("ALIGNMENT DEBUG END")
        self.logger.info("="*60)

        return {
            'location': new_location,
            'rotation': new_rotation,
            'scale': new_scale,
            'fitness': result_icp.fitness,
            'rmse': result_icp.inlier_rmse
        }

    def _process_merge_sync(self, ply1: Path, ply2: Path, cleaning_params: dict,
                        output_dir: Path, output_filename: str,
                        obj1_name: str, obj2_name: str,
                        source_transform: dict, target_transform: dict) -> Optional[dict]:

        self.logger.info("="*80)
        self.logger.info("MERGE AND CLEAN")
        self.logger.info("="*80)

        self.logger.info(f"Loading source: {ply1}")
        pcd1 = o3d.io.read_point_cloud(str(ply1))
        if len(pcd1.points) == 0:
            self.logger.error("Source point cloud is empty")
            return None
        n1 = len(pcd1.points)
        self.logger.info(f"  Source points: {n1:,}")

        self.logger.info(f"Loading target: {ply2}")
        pcd2 = o3d.io.read_point_cloud(str(ply2))
        if len(pcd2.points) == 0:
            self.logger.error("Target point cloud is empty")
            return None
        n2 = len(pcd2.points)
        self.logger.info(f"  Target points: {n2:,}")

        self.logger.info("Applying transforms to world coordinates...")
        T_source = self._compose_transform_matrix(
            source_transform['location'],
            source_transform['rotation'],
            source_transform['scale']
        )
        T_target = self._compose_transform_matrix(
            target_transform['location'],
            target_transform['rotation'],
            target_transform['scale']
        )

        pcd1.transform(T_source)
        pcd2.transform(T_target)
        self.logger.info("  Transforms applied")

        self.logger.info("Merging point clouds in world coordinates...")
        merged = pcd1 + pcd2
        n_merged = len(merged.points)
        self.logger.info(f"  Merged: {n1:,} + {n2:,} = {n_merged:,} points")

        points_merged = np.asarray(merged.points)
        bbox_diag = np.linalg.norm(points_merged.max(axis=0) - points_merged.min(axis=0))

        dedup_voxel = MERGE_CONFIG['dedup_voxel']
        if dedup_voxel is None:
            dedup_voxel = bbox_diag / 1000
        self.logger.info(f"Deduplication voxel size: {dedup_voxel:.6f}")

        self.logger.info("Removing duplicates...")
        merged_dedup = merged.voxel_down_sample(dedup_voxel)
        n_dedup = len(merged_dedup.points)
        self.logger.info(f"  After dedup: {n_dedup:,} points ({n_dedup/n_merged*100:.1f}%)")

        result_pcd = merged_dedup

        if cleaning_params.get('dbscan', False):
            self.logger.info("Running DBSCAN outlier removal...")
            result_pcd = self._remove_outliers_dbscan(result_pcd)
            if result_pcd is None:
                self.logger.warning("DBSCAN failed, skipping")
                result_pcd = merged_dedup
            else:
                self.logger.info(f"  After DBSCAN: {len(result_pcd.points):,} points")

        if cleaning_params.get('sor', False):
            self.logger.info("Running statistical outlier removal...")
            nb_neighbors = MERGE_CONFIG['sor_neighbors']
            std_ratio = MERGE_CONFIG['sor_std']
            n_before = len(result_pcd.points)
            cl, ind = result_pcd.remove_statistical_outlier(
                nb_neighbors=nb_neighbors,
                std_ratio=std_ratio
            )
            result_pcd = result_pcd.select_by_index(ind)
            n_after = len(result_pcd.points)
            self.logger.info(f"  After SOR: {n_after:,} points (removed {n_before-n_after:,})")

        if cleaning_params.get('normal', True):
            self.logger.info("Running normal-based outlier removal...")
            result_pcd = self._remove_outliers_by_normal(result_pcd)
            if result_pcd is not None:
                self.logger.info(f"  After normal filter: {len(result_pcd.points):,} points")

        if cleaning_params.get('ror', False):
            self.logger.info("Running radius outlier removal...")
            result_pcd = self._remove_outliers_radius(result_pcd)
            if result_pcd is not None:
                self.logger.info(f"  After ROR: {len(result_pcd.points):,} points")

        final_voxel = MERGE_CONFIG['final_voxel']
        if final_voxel is None:
            final_voxel = bbox_diag / 800
        self.logger.info(f"Final downsampling voxel size: {final_voxel:.6f}")

        self.logger.info("Final downsampling...")
        final_pcd = result_pcd.voxel_down_sample(final_voxel)
        n_final = len(final_pcd.points)
        self.logger.info(f"  Final points: {n_final:,} ({n_final/n_merged*100:.1f}% of merged)")

        ply_path = output_dir / output_filename
        ply_filename = output_filename
        self.logger.info(f"Saving point cloud: {ply_path}")
        o3d.io.write_point_cloud(str(ply_path), final_pcd)

        params_data = {
            'merge_operation': {
                'source_object': obj1_name,
                'target_object': obj2_name
            },
            'cleaning_enabled': {
                'dbscan': cleaning_params.get('dbscan', False),
                'sor': cleaning_params.get('sor', False),
                'normal': cleaning_params.get('normal', True),
                'ror': cleaning_params.get('ror', False)
            },
            'parameters_used': {
                'dedup_voxel': float(dedup_voxel),
                'final_voxel': float(final_voxel),
                'dbscan': {
                    'eps': MERGE_CONFIG['dbscan_eps'],
                    'min_pts_ratio': MERGE_CONFIG['dbscan_min_pts'],
                    'downsample_factor': MERGE_CONFIG['dbscan_ds_factor']
                },
                'sor': {
                    'nb_neighbors': MERGE_CONFIG['sor_neighbors'],
                    'std_ratio': MERGE_CONFIG['sor_std']
                },
                'normal': {
                    'nb_neighbors': MERGE_CONFIG['normal_neighbors'],
                    'angle_threshold': MERGE_CONFIG['normal_angle']
                },
                'ror': {
                    'nb_points': MERGE_CONFIG['ror_neighbors'],
                    'radius': MERGE_CONFIG['ror_radius']
                }
            },
            'statistics': {
                'input': {
                    'source_points': int(n1),
                    'target_points': int(n2),
                    'merged_points': int(n_merged)
                },
                'output': {
                    'final_points': int(n_final),
                    'removed_points': int(n_merged - n_final),
                    'reduction_percent': float((n_merged - n_final) / n_merged * 100)
                }
            }
        }

        file_stem = Path(output_filename).stem
        params_path = output_dir / f"{file_stem}_params.yml"
        self.logger.info(f"Saving parameters: {params_path}")
        try:
            self._save_yaml(params_path, params_data)
        except IOError as e:
            self.logger.error(f"Failed to save params: {e}")
            return None

        final_points = np.asarray(final_pcd.points)
        bbox_min = final_points.min(axis=0)
        bbox_max = final_points.max(axis=0)
        bbox_size = bbox_max - bbox_min
        final_bbox_diag = np.linalg.norm(bbox_size)

        meta_data = {
            'object_id': file_stem,
            'name': file_stem,
            'type': 'pointcloud',
            'created': datetime.now().isoformat(),
            'point_cloud': {
                'file': ply_filename,
                'points': int(n_final),
                'has_colors': final_pcd.has_colors(),
                'has_normals': final_pcd.has_normals()
            },
            'bounding_box': {
                'min': bbox_min.tolist(),
                'max': bbox_max.tolist(),
                'size': bbox_size.tolist(),
                'diagonal': float(final_bbox_diag)
            },
            'source_info': {
                'merged_from': [
                    {'source': obj1_name, 'points': int(n1)},
                    {'target': obj2_name, 'points': int(n2)}
                ],
                'operation': 'merge_and_clean',
                'params_file': f"{file_stem}_params.yml"
            }
        }

        meta_path = output_dir / f"{file_stem}_meta.yml"
        self.logger.info(f"Saving metadata: {meta_path}")
        try:
            self._save_yaml(meta_path, meta_data)
        except IOError as e:
            self.logger.error(f"Failed to save metadata: {e}")
            return None

        self.logger.info("="*80)
        self.logger.info("MERGE COMPLETED")
        self.logger.info("="*80)

        return {
            'ply_path': ply_path,
            'meta_path': meta_path,
            'params_path': params_path
        }

    def _fill_holes_pymeshlab(self, mesh, max_hole_size):
        temp_dir = Path("output/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_input = temp_dir / "temp_mesh_input.ply"
        temp_output = temp_dir / "temp_mesh_filled.ply"

        o3d.io.write_triangle_mesh(str(temp_input), mesh,
                                write_vertex_colors=True,
                                write_vertex_normals=True)

        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(str(temp_input))

        ms.meshing_remove_duplicate_faces()
        ms.meshing_remove_duplicate_vertices()
        ms.meshing_remove_unreferenced_vertices()
        ms.meshing_repair_non_manifold_edges(method=0)
        ms.meshing_repair_non_manifold_vertices(vertdispratio=0)

        ms.meshing_close_holes(maxholesize=max_hole_size)

        ms.save_current_mesh(str(temp_output))

        mesh_filled = o3d.io.read_triangle_mesh(str(temp_output))

        temp_input.unlink()
        temp_output.unlink()

        return mesh_filled

    def _process_mesh_sync(self, input_ply: Path, mesh_params: dict,
                        output_ply: Path, output_yml: Path) -> bool:

        depth = mesh_params.get('depth', 9)
        fill_holes = mesh_params.get('fill_holes', False)
        hole_size = mesh_params.get('hole_size', 400)
        simplify_target = mesh_params.get('simplify_target', 0)
        smooth_iterations = mesh_params.get('smooth_iterations', 0)

        self.logger.info("="*80)
        self.logger.info("MESH GENERATION")
        self.logger.info("="*80)

        self.logger.info(f"Loading point cloud: {input_ply}")
        pcd = o3d.io.read_point_cloud(str(input_ply))
        if len(pcd.points) == 0:
            self.logger.error("Empty point cloud")
            return False

        n_points = len(pcd.points)
        self.logger.info(f"  Points: {n_points:,}")

        points = np.asarray(pcd.points)
        bbox_diag = np.linalg.norm(points.max(axis=0) - points.min(axis=0))
        self.logger.info(f"  BBox diagonal: {bbox_diag:.4f}")

        if not pcd.has_normals():
            self.logger.info("Estimating normals...")
            search_radius = bbox_diag / MESH_CONFIG['normal_search_ratio']
            pcd.estimate_normals(
                search_param=o3d.geometry.KDTreeSearchParamHybrid(radius=search_radius, max_nn=30)
            )
            pcd.orient_normals_consistent_tangent_plane(k=15)
            self.logger.info("  Normals estimated")
        else:
            self.logger.info("  Point cloud has normals")

        self.logger.info(f"Poisson reconstruction (depth={depth})...")
        mesh, densities = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(
            pcd,
            depth=depth,
            width=MESH_CONFIG['poisson_width'],
            scale=MESH_CONFIG['poisson_scale'],
            linear_fit=MESH_CONFIG['poisson_linear_fit']
        )
        n_vertices = len(mesh.vertices)
        n_triangles = len(mesh.triangles)
        self.logger.info(f"  Vertices: {n_vertices:,}, Triangles: {n_triangles:,}")

        self.logger.info("Removing low density vertices...")
        densities = np.asarray(densities)
        threshold = np.quantile(densities, MESH_CONFIG['density_quantile'])
        vertices_to_remove = densities < threshold
        mesh.remove_vertices_by_mask(vertices_to_remove)
        self.logger.info(f"  After cleanup: {len(mesh.vertices):,} vertices, {len(mesh.triangles):,} triangles")

        if fill_holes:
            self.logger.info(f"Filling holes (max size={hole_size} edges)...")
            mesh = self._fill_holes_pymeshlab(mesh, hole_size)
            self.logger.info(f"  After fill: {len(mesh.vertices):,} vertices, {len(mesh.triangles):,} triangles")

        if simplify_target > 0 and len(mesh.triangles) > simplify_target:
            self.logger.info(f"Simplifying mesh to {simplify_target:,} triangles...")
            mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=simplify_target)
            self.logger.info(f"  After simplify: {len(mesh.vertices):,} vertices, {len(mesh.triangles):,} triangles")

        if smooth_iterations > 0:
            self.logger.info(f"Smoothing mesh ({smooth_iterations} iterations)...")
            mesh = mesh.filter_smooth_simple(number_of_iterations=smooth_iterations)
            self.logger.info("  Smoothing complete")

        self.logger.info(f"Saving mesh: {output_ply}")
        o3d.io.write_triangle_mesh(str(output_ply), mesh,
                                write_vertex_colors=True,
                                write_vertex_normals=True)

        final_vertices = np.asarray(mesh.vertices)
        final_bbox_min = final_vertices.min(axis=0)
        final_bbox_max = final_vertices.max(axis=0)
        final_bbox_size = final_bbox_max - final_bbox_min

        params_data = {
            'mesh_generation': {
                'timestamp': datetime.now().isoformat(),
                'input_file': input_ply.name
            },
            'parameters': {
                'depth': int(depth),
                'fill_holes': bool(fill_holes),
                'hole_size': int(hole_size),
                'simplify_target': int(simplify_target),
                'smooth_iterations': int(smooth_iterations),
                'density_quantile': float(MESH_CONFIG['density_quantile'])
            },
            'statistics': {
                'input_points': int(n_points),
                'output_vertices': int(len(mesh.vertices)),
                'output_triangles': int(len(mesh.triangles)),
                'bbox_size': final_bbox_size.tolist(),
                'bbox_diagonal': float(np.linalg.norm(final_bbox_size))
            }
        }

        self.logger.info(f"Saving parameters: {output_yml}")
        try:
            self._save_yaml(output_yml, params_data)
        except IOError as e:
            self.logger.error(f"Failed to save params: {e}")
            return False

        self.logger.info("="*80)
        self.logger.info("MESH GENERATION COMPLETE")
        self.logger.info("="*80)

        return True