# core/recon.py
from typing import Dict, List, Optional, Any
import os
import time
import tempfile
from pathlib import Path
from PySide6.QtCore import QObject
from core.executor import Executor
from logger import get_logger
from config import get_config


class ReconAPI(QObject, Executor):

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.config = get_config()

        self.local_project_dir = ""
        self.remote_project_dir = ""
        self.current_recon_dir = ""
        self.images_uploaded = False
        self.is_running = False
        self.current_tool = "colmap"

        self._pending_execution = None
        self._quality_mapping = self._load_quality_mapping()
        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("RECON API initialized")

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('recon.start', self.do_start_reconstruction, 'ReconAPI')
            self.signal_router.subscribe('recon.cancel', self.do_cancel_reconstruction, 'ReconAPI')
            self.signal_router.subscribe('recon.delete_cache', self.do_delete_cache, 'ReconAPI')
            self.signal_router.subscribe('recon.reset', self.do_reset, 'ReconAPI')

    def _load_quality_mapping(self, tool=None) -> Dict[str, Dict[str, Any]]:
        if tool is None:
            tool = self.current_tool

        recon_config = self.config.get("reconstruction", default={})
        tool_config = recon_config.get(tool, {})
        quality_levels = tool_config.get("quality_levels", {})

        if not quality_levels or not isinstance(quality_levels, dict):
            self.logger.warning(f"Invalid or missing quality_levels config for {tool}, using fallback")
            if tool == "alicevision":
                return {
                    'fast': {
                        'feature_density': 'low',
                        'max_features_per_image': 4000,
                        'depth_downscale': 6,
                        'max_tcams': 6,
                        'texture_size': 2048,
                        'max_input_points': 2000000
                    }
                }
            else:
                return {
                    'fast': {
                        'max_image_size': 1600,
                        'max_features': 4096,
                        'max_num_matches': 8192,
                        'num_threads': 4,
                        'resolution_level': 4,
                        'max_resolution': 480,
                        'number_views': 2,
                        'densify_iters': 1,
                        'densify_geometric_iters': 0,
                        'densify_sub_resolution_levels': 0,
                        'densify_max_threads': 4,
                        'refine_scales': 1,
                        'refine_decimate': 10,
                        'texmesh_resolution_level': 2
                    }
                }

        validated_mapping = {}
        for level_name, params in quality_levels.items():
            if self._validate_quality_params(params, tool):
                validated_mapping[level_name] = params
            else:
                self.logger.warning(f"Invalid quality params for level {level_name} in {tool}, skipping")

        if not validated_mapping:
            self.logger.warning(f"No valid quality levels found for {tool}, using fallback")
            return self._load_quality_mapping(tool)

        self.logger.info(f"Loaded {len(validated_mapping)} quality levels for {tool}: {list(validated_mapping.keys())}")
        return validated_mapping

    def _validate_quality_params(self, params: Dict[str, Any], tool: str) -> bool:
        if not isinstance(params, dict):
            return False

        if tool == "alicevision":
            required_keys = ['feature_density', 'max_features_per_image', 'depth_downscale', 'texture_size']
        else:
            required_keys = [
                'max_image_size', 'max_features', 'max_num_matches', 'num_threads',
                'resolution_level', 'max_resolution', 'number_views',
                'densify_iters', 'densify_geometric_iters', 'densify_sub_resolution_levels',
                'densify_max_threads', 'refine_scales', 'refine_decimate',
                'texmesh_resolution_level'
            ]

        for key in required_keys:
            if key not in params:
                return False
            if key == 'feature_density':
                if params[key] not in ['low', 'normal', 'high']:
                    return False
            elif not isinstance(params[key], int):
                return False

        return True

    def _get_quality_params(self, quality_level: str) -> Dict[str, Any]:
        return self._quality_mapping.get(quality_level, self._quality_mapping.get('fast', {}))

    def _get_remote_img_dir(self) -> str:
        return f"{self.remote_project_dir}/img"

    def _get_remote_recon_dir(self) -> str:
        return f"{self.remote_project_dir}/{self.current_recon_dir}"

    def _get_local_recon_dir(self) -> str:
        return f"{self.local_project_dir}/{self.current_recon_dir}"

    def _get_local_converted_dir(self) -> str:
        return f"{self.local_project_dir}/converted"

    def _generate_recon_dir_name(self) -> str:
        return f"recon_{int(time.time())}"

    def _build_recon_command(self, params: Dict[str, Any], output_type: str) -> List[str]:
        workspace_dir = self._get_remote_recon_dir()

        if self.current_tool == "alicevision":
            command = [
                '/app/recon.sh',
                '--workspace', workspace_dir,
                '--output-type', output_type,
                '--feature-density', str(params.get('feature_density', 'low')),
                '--max-features-per-image', str(params.get('max_features_per_image', 4000)),
                '--depth-downscale', str(params.get('depth_downscale', 6)),
                '--texture-size', str(params.get('texture_size', 2048))
            ]

            if 'max_tcams' in params:
                command.extend(['--max-tcams', str(params['max_tcams'])])
            if 'texture_downscale' in params:
                command.extend(['--texture-downscale', str(params['texture_downscale'])])
            if 'max_input_points' in params:
                command.extend(['--max-input-points', str(params['max_input_points'])])

        else:
            refine_decimate = params['refine_decimate'] / 100.0
            command = [
                '/app/recon.sh',
                '--workspace', workspace_dir,
                '--output-type', output_type,
                '--max-image-size', str(params['max_image_size']),
                '--max-features', str(params['max_features']),
                '--max-num-matches', str(params['max_num_matches']),
                '--num-threads', str(params['num_threads']),
                '--resolution-level', str(params['resolution_level']),
                '--max-resolution', str(params['max_resolution']),
                '--number-views', str(params['number_views']),
                '--densify-iters', str(params['densify_iters']),
                '--densify-geometric-iters', str(params['densify_geometric_iters']),
                '--densify-sub-resolution', str(params['densify_sub_resolution_levels']),
                '--densify-max-threads', str(params['densify_max_threads']),
                '--refine-scales', str(params['refine_scales']),
                '--refine-decimate', str(refine_decimate),
                '--texmesh-resolution-level', str(params['texmesh_resolution_level']),
            ]

        return command

    def _emit_progress(self, message: str, stream_type: str = 'stdout'):
        if self.signal_router:
            self.signal_router.emit('recon.progress', {
                'stream_type': stream_type,
                'message': message,
                'timestamp': time.time()
            })

    def _handle_script_output(self, stream_type: str, content: str):
        if not content.strip():
            return
        self._emit_progress(content.strip(), stream_type)

    def _generate_link_commands(self, selected_basenames: List[str]) -> List[str]:
        commands = []
        remote_img_dir = self._get_remote_img_dir()
        remote_converted_dir = f"{self._get_remote_recon_dir()}/converted"

        commands.append(f"mkdir -p {remote_converted_dir}")
        self._emit_progress(f"Linking {len(selected_basenames)} images")

        for basename in selected_basenames:
            find_and_link_cmd = (
                f"for f in {remote_img_dir}/{basename}.*; do "
                f"if [ -f \"$f\" ]; then "
                f"ln \"$f\" {remote_converted_dir}/ && echo \"Linked $(basename $f)\"; "
                f"break; "
                f"fi; "
                f"done"
            )
            commands.append(find_and_link_cmd)
            self.logger.debug(f"Link pattern for {basename}: {basename}.*")

        return commands

    def _build_combined_command(self, selected_basenames: List[str], params: Dict[str, Any], output_type: str) -> str:
        link_commands = self._generate_link_commands(selected_basenames)
        recon_command = self._build_recon_command(params, output_type)
        unbuffered_recon_command = f"PYTHONUNBUFFERED=1 {' '.join(recon_command)}"
        all_commands = link_commands + [unbuffered_recon_command]
        return ' && '.join(all_commands)

    def _step1_upload_images(self, start_time: float, tool: str):
        converted_dir = self._get_local_converted_dir()

        if not os.path.exists(converted_dir):
            error_msg = f"Converted directory not found: {converted_dir}"
            self.logger.error(error_msg)
            self._handle_step_failure("upload", error_msg, tool, time.time() - start_time)
            return

        if self.images_uploaded:
            self.logger.info("Images already uploaded, skipping upload step")
            self._step2_prepare_and_execute(start_time, tool)
            return

        self.logger.info(f"Starting upload of converted directory: {converted_dir}")
        self._emit_progress(f"Uploading converted images from {os.path.basename(converted_dir)}")

        def upload_callback(success, result, **kwargs):
            if success:
                self.images_uploaded = True
                self.logger.info("Converted images uploaded successfully")
                self._emit_progress("Image upload completed successfully")
                self._step2_prepare_and_execute(kwargs.get('start_time'), kwargs.get('tool'))
            else:
                error_msg = result.get('error', 'Upload failed')
                self.logger.error(f"Failed to upload converted images: {error_msg}")
                self._handle_step_failure("upload", error_msg, kwargs.get('tool', ''),
                                        time.time() - kwargs.get('start_time', 0))

        remote_img_dir = self._get_remote_img_dir()
        self.upload(converted_dir, remote_img_dir, self.current_tool, upload_callback,
                   start_time=start_time, tool=tool)

    def _step2_prepare_and_execute(self, start_time: float, tool: str):
        if not self._pending_execution:
            self.logger.error("No pending execution parameters")
            self._handle_step_failure("prepare", "Missing execution parameters", tool,
                                    time.time() - start_time)
            return

        execution = self._pending_execution
        selected_basenames = execution['selected_basenames']
        params = execution['params']
        output_type = execution['output_type']

        self._emit_progress(f"Preparing reconstruction for {len(selected_basenames)} images")

        combined_command = self._build_combined_command(selected_basenames, params, output_type)
        command = ['/bin/bash', '-c', combined_command]

        self.logger.info(f"Starting {self.current_tool} reconstruction process")
        self._emit_progress(f"Starting {self.current_tool.upper()} reconstruction process")

        def output_callback(stream_type: str, content: str):
            self._handle_script_output(stream_type, content)

        def exec_callback(success, result, **kwargs):
            if success:
                self.logger.info("Reconstruction execution completed successfully")
                self._emit_progress("Reconstruction completed, preparing results")
                self._step3_download_results(kwargs.get('start_time'), kwargs.get('tool'))
            else:
                error_msg = result.get('error', 'Execution failed')
                self.logger.error(f"Reconstruction execution failed: {error_msg}")
                self._handle_step_failure("execution", error_msg, kwargs.get('tool', ''),
                                        time.time() - kwargs.get('start_time', 0))

        self.exec_cmd(
            service=self.current_tool,
            command=command,
            output_callback=output_callback,
            timeout=3600,
            callback=exec_callback,
            start_time=start_time,
            tool=tool
        )

    def _step3_download_results(self, start_time: float, tool: str):
        remote_result_dir = f"{self._get_remote_recon_dir()}/result"
        local_result_dir = f"{self._get_local_recon_dir()}/result"

        self.logger.info(f"Starting download of results to: {local_result_dir}")
        self._emit_progress("Downloading reconstruction results")

        def download_callback(success, result, **kwargs):
            duration = time.time() - kwargs.get('start_time', 0)

            if success:
                self.logger.info("Results downloaded successfully")
                self._emit_progress("Results downloaded successfully")
                self._emit_completion(True, "", kwargs.get('tool', ''), duration)
                self._emit_import_ready()
            else:
                error_msg = result.get('error', 'Download failed')
                self.logger.error(f"Failed to download results: {error_msg}")
                self._emit_completion(False, error_msg, kwargs.get('tool', ''), duration)

            self._cleanup_reconstruction_state()

        os.makedirs(os.path.dirname(local_result_dir), exist_ok=True)

        self.download(remote_result_dir, local_result_dir, self.current_tool, download_callback,
                     start_time=start_time, tool=tool)

    def _handle_step_failure(self, step: str, error_msg: str, tool: str, duration: float):
        self.logger.error(f"Step '{step}' failed for {tool}: {error_msg}")
        self._emit_progress(f"Error in {step} step: {error_msg}", 'stderr')
        self._emit_completion(False, f"{step.capitalize()} failed: {error_msg}", tool, duration)
        self._cleanup_reconstruction_state()

    def _cleanup_reconstruction_state(self):
        self.is_running = False
        self._pending_execution = None

    def do_start_reconstruction(self, data: Dict[str, Any]):
        tool = data.get('tool', 'colmap')
        self.current_tool = tool
        self._quality_mapping = self._load_quality_mapping()

        self.local_project_dir = data.get('project_dir', '')
        selected_basenames = data.get('selected_images', [])
        config = data.get('config', {})

        self.logger.info(f"Starting {tool} reconstruction")
        self.logger.info(f"Selected basenames: {selected_basenames}")

        if not self.local_project_dir:
            self._emit_completion(False, "Invalid project directory", tool)
            return

        if not os.path.exists(self.local_project_dir):
            self._emit_completion(False, "Project directory does not exist", tool)
            return

        converted_dir = self._get_local_converted_dir()
        if not os.path.exists(converted_dir):
            self._emit_completion(False, "Converted directory does not exist", tool)
            return

        if not selected_basenames:
            self._emit_completion(False, "No images selected", tool)
            return

        quality_level = config.get('quality_level', 'fast')
        output_type = config.get('output_type', 'point_cloud')

        params = self._get_quality_params(quality_level)
        if not params:
            self._emit_completion(False, f"Invalid quality level: {quality_level}", tool)
            return

        project_name = os.path.basename(self.local_project_dir.rstrip('/\\'))
        self.remote_project_dir = f"/workspace/{project_name}"
        self.current_recon_dir = self._generate_recon_dir_name()

        self.is_running = True
        start_time = time.time()

        self._pending_execution = {
            'selected_basenames': selected_basenames,
            'params': params,
            'output_type': output_type
        }

        self._emit_progress(f"Initializing {tool} reconstruction with {len(selected_basenames)} images")
        self._step1_upload_images(start_time, tool)

    def do_cancel_reconstruction(self, data: Dict[str, Any]):
        self.logger.info("Reconstruction cancellation requested")

        if not self.is_running:
            self.logger.warning("No reconstruction running to cancel")
            return

        kill_command = ['pkill', '-f', 'recon.sh']

        def cancel_callback(success: bool, result: Dict[str, Any], **kwargs):
            if success:
                self.logger.info("Reconstruction process terminated")
                self._emit_progress("Reconstruction cancelled by user", 'stderr')
            else:
                self.logger.warning("Failed to terminate reconstruction process")

            self._cleanup_reconstruction_state()

        self.exec_cmd(
            service=self.current_tool,
            command=kill_command,
            callback=cancel_callback
        )

    def do_delete_cache(self, data: Dict[str, Any]):
        self.logger.info("Delete cache requested")

        project_dir = data.get('project_dir', '')
        target_remote_dir = ""

        if self.remote_project_dir:
            target_remote_dir = self.remote_project_dir
            self.logger.info(f"Using existing remote directory: {target_remote_dir}")
        elif project_dir:
            project_name = os.path.basename(project_dir.rstrip('/\\'))
            target_remote_dir = f"/workspace/{project_name}"
            self.logger.info(f"Calculated remote directory from project_dir: {target_remote_dir}")
        else:
            self.logger.warning("No remote directory available for deletion")
            return

        delete_command = ['rm', '-rf', target_remote_dir]

        def delete_callback(success: bool, result: Dict[str, Any], **kwargs):
            if success:
                self.logger.info(f"Remote directory deleted: {target_remote_dir}")
                self._emit_progress("Remote results deleted successfully")
            else:
                error_msg = result.get('error', 'Delete failed')
                self.logger.warning(f"Failed to delete remote directory: {error_msg}")
                self._emit_progress(f"Delete failed: {error_msg}", 'stderr')

            self._reset_session_state()

        self._emit_progress(f"Deleting remote directory: {target_remote_dir}")
        self.exec_cmd(
            service=self.current_tool,
            command=delete_command,
            callback=delete_callback
        )

    def do_reset(self, data: Dict[str, Any]):
        self.logger.info("Reconstruction reset requested")
        self.current_tool = "colmap"
        self._quality_mapping = self._load_quality_mapping()
        self._reset_session_state()
        self.logger.info("Reconstruction state reset to defaults")

    def _reset_session_state(self):
        self.remote_project_dir = ""
        self.current_recon_dir = ""
        self.images_uploaded = False
        self.is_running = False
        self._pending_execution = None

    def _emit_completion(self, success: bool, error_message: str, tool: str, duration: float = 0.0):
        if self.signal_router:
            self.signal_router.emit('recon.completed', {
                'success': success,
                'error_message': error_message,
                'tool': tool,
                'duration': duration
            })

    def _emit_import_ready(self):
        if not self.signal_router:
            return

        available_files = self._scan_result_files()

        self.signal_router.emit('recon.import_ready', {
            'project_dir': self.local_project_dir,
            'result_dir_name': self.current_recon_dir,
            'available_files': available_files
        })

    def _scan_result_files(self) -> Dict[str, str]:
        available_files = {}

        if not self.current_recon_dir or not self.local_project_dir:
            return available_files

        result_path = f"{self._get_local_recon_dir()}/result"

        if not os.path.exists(result_path):
            return available_files

        if self.current_tool == "alicevision":
            point_cloud_files = ['dense_points.ply', 'sparse_points.ply']
            for filename in point_cloud_files:
                file_path = os.path.join(result_path, filename)
                if os.path.exists(file_path):
                    available_files['point_cloud'] = file_path
                    break

            mesh_files = ['textured_mesh.obj']
            for filename in mesh_files:
                file_path = os.path.join(result_path, filename)
                if os.path.exists(file_path):
                    available_files['dense_mesh'] = file_path
                    break
        else:
            point_cloud_files = ['dense_points.ply', 'points.ply', 'sparse_points.ply']
            for filename in point_cloud_files:
                file_path = os.path.join(result_path, filename)
                if os.path.exists(file_path):
                    available_files['point_cloud'] = file_path
                    break

            mesh_files = ['mesh.obj', 'mesh.ply', 'scene_mesh.ply', 'textured_mesh.obj']
            for filename in mesh_files:
                file_path = os.path.join(result_path, filename)
                if os.path.exists(file_path):
                    available_files['dense_mesh'] = file_path
                    break

        return available_files

    def get_project_status(self) -> Optional[Dict[str, Any]]:
        return {
            'local_project_dir': self.local_project_dir,
            'remote_project_dir': self.remote_project_dir,
            'current_recon_dir': self.current_recon_dir,
            'current_tool': self.current_tool,
            'images_uploaded': self.images_uploaded,
            'is_running': self.is_running
        }

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ReconAPI')

        self._cleanup_reconstruction_state()
        self.images_uploaded = False