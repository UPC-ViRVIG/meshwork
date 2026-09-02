# core/signal_router.py
from PySide6.QtCore import QObject, Signal, Qt, QThread
from collections import defaultdict
from typing import Dict, List, Callable, Any
import copy
from logger import get_logger

# Signal definitions
BASEOPS_SIGNALS = {
    'baseops.do_undo': {
        'data': {},
        'receivers': ['BaseopsAPI']
    },
    'baseops.do_redo': {
        'data': {},
        'receivers': ['BaseopsAPI']
    }
}

SCENE_DO_SIGNALS = {
    'scene.do_add_object': {
        'data': {'object_data': dict},
        'receivers': ['SceneManager']
    },
    'scene.do_remove_object': {
        'data': {},
        'receivers': ['SceneManager']
    },
    'scene.do_select_object': {
        'data': {'object_name': str, 'extend': bool},
        'receivers': ['SceneManager']
    },
    'scene.do_clear_selection': {
        'data': {},
        'receivers': ['SceneManager']
    },
    'scene.do_select_all': {
        'data': {},
        'receivers': ['SceneManager']
    },
    'scene.do_clear_scene': {
        'data': {},
        'receivers': ['SceneManager']
    },
    'scene.do_toggle_visibility': {
        'data': {'object_name': str},
        'receivers': ['SceneManager']
    }
}

SCENE_DONE_SIGNALS = {
    'scene.done_selection_changed': {
        'data': {'all_objects': list},
        'receivers': ['ScenePanel', 'ToolsPanel']
    },
    'scene.done_scene_cleared': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ScenePanel', 'View', 'StatusBar']
    }
}

EXECUTOR_SIGNALS = {
    'executor.do_execute_script': {
        'data': {'script': str, 'timeout': float},
        'receivers': ['ExecutorAPI']
    },
    'executor.incremental_output': {
        'data': {'stream': str, 'text': str, 'timestamp': float},
        'receivers': ['ScriptConsole']
    },
    'executor.done_script_executed': {
        'data': {'success': bool, 'result': dict, 'duration': float},
        'receivers': ['ScriptEditor']
    },
    'executor.do_upload_file': {
        'data': {'local_path': str, 'remote_path': str, 'service': str},
        'receivers': ['ExecutorAPI']
    },
    'executor.done_file_transferred': {
        'data': {'operation_type': str, 'file_path': str, 'success': bool, 'error': str},
        'receivers': ['MenuHandler', 'StatusBar']
    }
}

TRANSFORM_SIGNALS = {
    'transform.tool_activated': {
        'data': {'tool_type': str, 'selected_objects': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.tool_ready': {
        'data': {'tool_type': str, 'current_values': dict},
        'receivers': ['ToolsPanel']
    },
    'transform.preview_move': {
        'data': {'object_names': list, 'position': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.preview_rotate': {
        'data': {'object_names': list, 'rotation': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.preview_scale': {
        'data': {'object_names': list, 'scale': list, 'uniform': bool},
        'receivers': ['BaseopsAPI']
    },
    'transform.apply_changes': {
        'data': {'object_names': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.cancel_changes': {
        'data': {'object_names': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.apply_transform': {
        'data': {'object_name': str, 'location': list, 'rotation': list, 'scale': list},
        'receivers': ['BaseopsAPI']
    },
    'transform.done_apply_transform': {
        'data': {'success': bool, 'object_name': str, 'error': str},
        'receivers': ['PointcloudAPI']
    }
}

API_SIGNALS = {
    'mesh.do_subdivide': {
        'data': {'object_id': str, 'levels': int},
        'receivers': ['MeshAPI']
    },
    'mesh.do_simplify': {
        'data': {'object_id': str, 'ratio': float},
        'receivers': ['MeshAPI']
    },
    'mesh.do_repair': {
        'data': {'object_id': str},
        'receivers': ['MeshAPI']
    },
    'mesh.done_operation': {
        'data': {'operation_type': str, 'object_id': str, 'success': bool, 'error': str},
        'receivers': ['ToolsPanel', 'StatusBar']
    },
    'render.do_render_image': {
        'data': {'config': dict},
        'receivers': ['RenderAPI']
    },
    'render.done_render_completed': {
        'data': {'operation_type': str, 'output_path': str, 'success': bool, 'duration': float},
        'receivers': ['RenderPanel', 'StatusBar']
    }
}

POINTCLOUD_SIGNALS = {
    'pointcloud.do_analyze_plane': {
        'data': {'object_name': str},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_analyze_plane': {
        'data': {'success': bool, 'yaml_path': str, 'error': str},
        'receivers': ['ToolsController']
    },
    'pointcloud.do_remove_plane': {
        'data': {'object_name': str, 'margin': float, 'method': str},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_remove_plane': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ToolsController']
    },
    'pointcloud.do_remove_plane_preview': {
        'data': {'object_name': str},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_remove_plane_preview': {
        'data': {'recommended_margin': float},
        'receivers': ['ToolsController']
    },
    'pointcloud.do_align_clouds': {
        'data': {'source_object': str, 'target_object': str},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_align_clouds': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ToolsController']
    },
    'pointcloud.do_merge_clouds': {
        'data': {'source_object': str, 'target_object': str, 'cleaning_params': dict},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_merge_clouds': {
        'data': {'success': bool, 'output_file': str, 'error': str},
        'receivers': ['ToolsController']
    },
    'pointcloud.do_generate_mesh': {
        'data': {'object_name': str, 'mesh_params': dict},
        'receivers': ['PointcloudAPI']
    },
    'pointcloud.done_generate_mesh': {
        'data': {'success': bool, 'mesh_file': str, 'error': str},
        'receivers': ['ToolsController']
    }
}

SCENE_SIGNALS = {
    'scene.object_added': {
        'data': {'object_name': str, 'object_type': str, 'properties': dict},
        'receivers': ['ScenePanel', 'View', 'StatusBar']
    },
    'scene.object_removed': {
        'data': {'object_name': str},
        'receivers': ['ScenePanel', 'View', 'StatusBar']
    },
    'scene.object_modified': {
        'data': {'object_name': str, 'properties': dict, 'needs_redraw': bool},
        'receivers': ['SceneManager']
    },
    'scene.redraw_needed': {
        'data': {'dirty_objects': list},
        'receivers': ['View']
    },
    'scene.add_primitive': {
        'data': {'type': str, 'params': dict},
        'receivers': ['SceneManager']
    },
    'scene.render_data_updated': {
        'data': {'render_data': dict},
        'receivers': ['View', 'PointcloudAPI']
    },
    'scene.load_mesh_files': {
        'data': {'file_paths': list, 'import_settings': dict},
        'receivers': ['SceneManager']
    },
    'scene.load_pointcloud_files': {
        'data': {'file_paths': list, 'import_settings': dict},
        'receivers': ['SceneManager']
    },
    'scene.load_camera_data': {
        'data': {'file_paths': list, 'import_settings': dict},
        'receivers': ['SceneManager']
    },
    'scene.request_sync': {
        'data': {},
        'receivers': ['SceneManager']
    },
    'scene.do_baking': {
        'data': {'object_names': list, 'no_color': bool},
        'receivers': ['SceneManager']
    },
    'scene.done_baking': {
        'data': {'success': bool, 'object_names': list},
        'receivers': ['ToolsPanel']
    }
}

VIEW_SIGNALS = {
    'view.tool_changed': {
        'data': {'tool_name': str, 'tool_config': dict},
        'receivers': ['View']
    },
    'view.camera_changed': {
        'data': {'camera_position': tuple, 'view_type': str},
        'receivers': ['StatusBar']
    },
    'view.reset_camera': {
        'data': {},
        'receivers': ['View']
    },
    'view.reset_layout': {
        'data': {},
        'receivers': ['MainWindow']
    },
    'view.toggle_bounds': {
        'data': {'visible': bool},
        'receivers': ['View']
    }
}

STATUS_SIGNALS = {
    'status.message': {
        'data': {'text': str, 'level': str, 'duration': int},
        'receivers': ['StatusBar']
    },
    'status.progress': {
        'data': {'operation_id': str, 'progress': float, 'message': str},
        'receivers': ['ProgressBar', 'StatusBar']
    }
}

FILE_SIGNALS = {
    'file.transfer_progress': {
        'data': {'operation_id': str, 'bytes_transferred': int, 'total_bytes': int, 'speed': float},
        'receivers': ['ProgressDialog', 'StatusBar']
    },
    'file.operation_completed': {
        'data': {'operation_type': str, 'file_path': str, 'success': bool, 'error': str},
        'receivers': ['MenuHandler', 'StatusBar']
    }
}

RECONSTRUCTION_SIGNALS = {
    'recon.start': {
        'data': {'tool': str, 'project_dir': str, 'selected_images': list, 'config': dict},
        'receivers': ['ReconAPI']
    },
    'recon.progress': {
        'data': {'stream_type': str, 'message': str, 'timestamp': float},
        'receivers': ['ReconWindow']
    },
    'recon.completed': {
        'data': {'success': bool, 'error_message': str, 'tool': str, 'duration': float},
        'receivers': ['ReconWindow']
    },
    'recon.cancel': {
        'data': {},
        'receivers': ['ReconAPI']
    },
    'recon.import_ready': {
        'data': {'project_dir': str, 'result_dir_name': str, 'available_files': dict},
        'receivers': ['ReconWindow']
    },
    'recon.delete_cache': {
        'data': {'project_dir': str},
        'receivers': ['ReconAPI']
    },
    'recon.reset': {
        'data': {},
        'receivers': ['ReconAPI']
    }
}

PROJECT_SIGNALS = {
    'project.do_new': {
        'data': {},
        'receivers': ['ProjectAPI']
    },
    'project.do_open': {
        'data': {'file_path': str},
        'receivers': ['ProjectAPI']
    },
    'project.do_save': {
        'data': {'file_path': str},
        'receivers': ['ProjectAPI']
    },
    'project.do_save_as': {
        'data': {'file_path': str},
        'receivers': ['ProjectAPI']
    },
    'project.do_import': {
        'data': {'file_path': str},
        'receivers': ['ProjectAPI']
    },
    'project.do_export': {
        'data': {'file_path': str},
        'receivers': ['ProjectAPI']
    },
    'project.done_new': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ProjectState']
    },
    'project.done_open': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ProjectState']
    },
    'project.done_save': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ProjectState']
    },
    'project.done_import': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ProjectState', 'PointCloudAPI']
    },
    'project.done_export': {
        'data': {'success': bool, 'error': str},
        'receivers': ['ProjectState']
    }
}

RECON_SIGNALS = {
    'recon.folder_changed': {
        'data': {'folder_type': str, 'path': str},
        'receivers': ['ImagePreviewPanel']
    },
    'recon.image_converted': {
        'data': {'src_path': str, 'dst_path': str, 'success': bool, 'error': str, 'pingpong': str},
        'receivers': ['ImagePreviewPanel']
    },
    'recon.image_all_converted': {
        'data': {'phase': str, 'success_count': int, 'total_count': int},
        'receivers': ['ReconWindow']
    },
    'recon.selection_changed': {
        'data': {'selected_images': list, 'total_images': int},
        'receivers': ['ReconWindow']
    }
}


class SignalRouter(QObject):

    baseops_do_undo = Signal(dict)
    baseops_do_redo = Signal(dict)

    scene_object_added = Signal(dict)
    scene_object_removed = Signal(dict)
    scene_object_modified = Signal(dict)
    scene_redraw_needed = Signal(dict)
    scene_add_primitive = Signal(dict)
    scene_render_data_updated = Signal(dict)
    scene_load_mesh_files = Signal(dict)
    scene_load_pointcloud_files = Signal(dict)
    scene_load_camera_data = Signal(dict)
    scene_request_sync = Signal(dict)
    scene_do_baking = Signal(dict)
    scene_done_baking = Signal(dict)

    view_tool_changed = Signal(dict)
    view_camera_changed = Signal(dict)
    view_reset_camera = Signal(dict)
    view_reset_layout = Signal(dict)

    view_toggle_bounds = Signal(dict)
    status_message = Signal(dict)
    status_progress = Signal(dict)

    file_transfer_progress = Signal(dict)
    file_operation_completed = Signal(dict)

    worker_initialized = Signal(dict)

    scene_do_add_object = Signal(dict)
    scene_do_remove_object = Signal(dict)
    scene_do_select_object = Signal(dict)
    scene_do_clear_selection = Signal(dict)
    scene_do_select_all = Signal(dict)
    scene_do_clear_scene = Signal(dict)
    scene_do_toggle_visibility = Signal(dict)

    scene_done_selection_changed = Signal(dict)
    scene_done_scene_cleared = Signal(dict)

    executor_do_execute_script = Signal(dict)
    executor_incremental_output = Signal(dict)
    executor_done_script_executed = Signal(dict)
    executor_do_upload_file = Signal(dict)
    executor_done_file_transferred = Signal(dict)

    transform_tool_activated = Signal(dict)
    transform_tool_ready = Signal(dict)
    transform_preview_move = Signal(dict)
    transform_preview_rotate = Signal(dict)
    transform_preview_scale = Signal(dict)
    transform_apply_changes = Signal(dict)
    transform_cancel_changes = Signal(dict)
    transform_apply_transform = Signal(dict)
    transform_done_apply_transform = Signal(dict)

    mesh_do_subdivide = Signal(dict)
    mesh_do_simplify = Signal(dict)
    mesh_do_repair = Signal(dict)
    mesh_done_operation = Signal(dict)

    render_do_render_image = Signal(dict)
    render_done_render_completed = Signal(dict)

    recon_start = Signal(dict)
    recon_progress = Signal(dict)
    recon_completed = Signal(dict)
    recon_cancel = Signal(dict)
    recon_import_ready = Signal(dict)
    recon_delete_cache = Signal(dict)
    recon_reset = Signal(dict)

    project_do_new = Signal(dict)
    project_do_open = Signal(dict)
    project_do_save = Signal(dict)
    project_do_save_as = Signal(dict)
    project_do_import = Signal(dict)
    project_do_export = Signal(dict)
    project_done_new = Signal(dict)
    project_done_open = Signal(dict)
    project_done_save = Signal(dict)
    project_done_import = Signal(dict)
    project_done_export = Signal(dict)

    recon_folder_changed = Signal(dict)
    recon_image_converted = Signal(dict)
    recon_image_all_converted = Signal(dict)
    recon_selection_changed = Signal(dict)

    pointcloud_do_analyze_plane = Signal(dict)
    pointcloud_done_analyze_plane = Signal(dict)
    pointcloud_do_remove_plane = Signal(dict)
    pointcloud_done_remove_plane = Signal(dict)
    pointcloud_do_remove_plane_preview = Signal(dict)
    pointcloud_done_remove_plane_preview = Signal(dict)
    pointcloud_do_align_clouds = Signal(dict)
    pointcloud_done_align_clouds = Signal(dict)
    pointcloud_do_merge_clouds = Signal(dict)
    pointcloud_done_merge_clouds = Signal(dict)
    pointcloud_do_generate_mesh = Signal(dict)
    pointcloud_done_generate_mesh = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger()

        self.channels = {
            **BASEOPS_SIGNALS,
            **SCENE_DO_SIGNALS,
            **SCENE_DONE_SIGNALS,
            **EXECUTOR_SIGNALS,
            **TRANSFORM_SIGNALS,
            **API_SIGNALS,
            **POINTCLOUD_SIGNALS,
            **SCENE_SIGNALS,
            **VIEW_SIGNALS,
            **STATUS_SIGNALS,
            **FILE_SIGNALS,
            **RECONSTRUCTION_SIGNALS,
            **PROJECT_SIGNALS,
            **RECON_SIGNALS
        }

        self.subscribers = defaultdict(list)
        self.thread_connections = defaultdict(dict)

        self.signal_map = {
            'baseops.do_undo': self.baseops_do_undo,
            'baseops.do_redo': self.baseops_do_redo,
            'scene.object_added': self.scene_object_added,
            'scene.object_removed': self.scene_object_removed,
            'scene.object_modified': self.scene_object_modified,
            'scene.redraw_needed': self.scene_redraw_needed,
            'scene.add_primitive': self.scene_add_primitive,
            'scene.render_data_updated': self.scene_render_data_updated,
            'scene.load_mesh_files': self.scene_load_mesh_files,
            'scene.load_pointcloud_files': self.scene_load_pointcloud_files,
            'scene.load_camera_data': self.scene_load_camera_data,
            'scene.request_sync': self.scene_request_sync,
            'scene.do_baking': self.scene_do_baking,
            'scene.done_baking': self.scene_done_baking,
            'view.tool_changed': self.view_tool_changed,
            'view.camera_changed': self.view_camera_changed,
            'view.reset_camera': self.view_reset_camera,
            'view.reset_layout': self.view_reset_layout,
            'view.toggle_bounds': self.view_toggle_bounds,
            'status.message': self.status_message,
            'status.progress': self.status_progress,
            'file.transfer_progress': self.file_transfer_progress,
            'file.operation_completed': self.file_operation_completed,
            'scene.do_add_object': self.scene_do_add_object,
            'scene.do_remove_object': self.scene_do_remove_object,
            'scene.do_select_object': self.scene_do_select_object,
            'scene.do_clear_selection': self.scene_do_clear_selection,
            'scene.do_select_all': self.scene_do_select_all,
            'scene.do_clear_scene': self.scene_do_clear_scene,
            'scene.do_toggle_visibility': self.scene_do_toggle_visibility,
            'scene.done_selection_changed': self.scene_done_selection_changed,
            'scene.done_scene_cleared': self.scene_done_scene_cleared,
            'executor.do_execute_script': self.executor_do_execute_script,
            'executor.incremental_output': self.executor_incremental_output,
            'executor.done_script_executed': self.executor_done_script_executed,
            'executor.do_upload_file': self.executor_do_upload_file,
            'executor.done_file_transferred': self.executor_done_file_transferred,
            'transform.tool_activated': self.transform_tool_activated,
            'transform.tool_ready': self.transform_tool_ready,
            'transform.preview_move': self.transform_preview_move,
            'transform.preview_rotate': self.transform_preview_rotate,
            'transform.preview_scale': self.transform_preview_scale,
            'transform.apply_changes': self.transform_apply_changes,
            'transform.cancel_changes': self.transform_cancel_changes,
            'transform.apply_transform': self.transform_apply_transform,
            'transform.done_apply_transform': self.transform_done_apply_transform,
            'mesh.do_subdivide': self.mesh_do_subdivide,
            'mesh.do_simplify': self.mesh_do_simplify,
            'mesh.do_repair': self.mesh_do_repair,
            'mesh.done_operation': self.mesh_done_operation,
            'render.do_render_image': self.render_do_render_image,
            'render.done_render_completed': self.render_done_render_completed,
            'recon.start': self.recon_start,
            'recon.progress': self.recon_progress,
            'recon.completed': self.recon_completed,
            'recon.cancel': self.recon_cancel,
            'recon.import_ready': self.recon_import_ready,
            'recon.delete_cache': self.recon_delete_cache,
            'recon.reset': self.recon_reset,
            'project.do_new': self.project_do_new,
            'project.do_open': self.project_do_open,
            'project.do_save': self.project_do_save,
            'project.do_save_as': self.project_do_save_as,
            'project.do_import': self.project_do_import,
            'project.do_export': self.project_do_export,
            'project.done_new': self.project_done_new,
            'project.done_open': self.project_done_open,
            'project.done_save': self.project_done_save,
            'project.done_import': self.project_done_import,
            'project.done_export': self.project_done_export,
            'recon.folder_changed': self.recon_folder_changed,
            'recon.image_converted': self.recon_image_converted,
            'recon.image_all_converted': self.recon_image_all_converted,
            'recon.selection_changed': self.recon_selection_changed,
            'pointcloud.do_analyze_plane': self.pointcloud_do_analyze_plane,
            'pointcloud.done_analyze_plane': self.pointcloud_done_analyze_plane,
            'pointcloud.do_remove_plane': self.pointcloud_do_remove_plane,
            'pointcloud.done_remove_plane': self.pointcloud_done_remove_plane,
            'pointcloud.do_remove_plane_preview': self.pointcloud_do_remove_plane_preview,
            'pointcloud.done_remove_plane_preview': self.pointcloud_done_remove_plane_preview,
            'pointcloud.do_align_clouds': self.pointcloud_do_align_clouds,
            'pointcloud.done_align_clouds': self.pointcloud_done_align_clouds,
            'pointcloud.do_merge_clouds': self.pointcloud_do_merge_clouds,
            'pointcloud.done_merge_clouds': self.pointcloud_done_merge_clouds,
            'pointcloud.do_generate_mesh': self.pointcloud_do_generate_mesh,
            'pointcloud.done_generate_mesh': self.pointcloud_done_generate_mesh
        }

    def emit(self, signal_name: str, data: Dict[str, Any]) -> bool:
        if signal_name not in self.channels:
            self.logger.warning(f"Unknown signal: {signal_name}")
            return False

        expected_data = self.channels[signal_name]['data']
        if not self._validate_data(data, expected_data):
            self.logger.error(f"Invalid data for signal {signal_name}: {data}")
            return False

        safe_data = self._serialize_data(data)

        qt_signal = self.signal_map.get(signal_name)
        if qt_signal:
            qt_signal.emit(safe_data)
            return True
        else:
            self.logger.error(f"No Qt signal found for {signal_name}")
            return False

    def subscribe(self, signal_name: str, callback: Callable, receiver_name: str):
        if signal_name not in self.channels:
            self.logger.warning(f"Unknown signal for subscription: {signal_name}")
            return False

        qt_signal = self.signal_map.get(signal_name)
        if qt_signal:
            connection_type = self._detect_connection_type(callback)
            qt_signal.connect(callback, connection_type)
            self.subscribers[signal_name].append((callback, receiver_name))
            self.logger.debug(f"{receiver_name} subscribed to {signal_name}")
            return True
        else:
            self.logger.error(f"No Qt signal found for {signal_name}")
            return False

    def _detect_connection_type(self, callback: Callable):
        if hasattr(callback, '__self__'):
            callback_obj = callback.__self__
            if hasattr(callback_obj, 'thread'):
                callback_thread = callback_obj.thread()
                current_thread = QThread.currentThread()
                if callback_thread != current_thread:
                    return Qt.QueuedConnection
        return Qt.AutoConnection

    def _serialize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return copy.deepcopy(data)

    def unsubscribe(self, signal_name: str, callback: Callable):
        if signal_name in self.subscribers:
            qt_signal = self.signal_map.get(signal_name)
            if qt_signal:
                qt_signal.disconnect(callback)

            original_count = len(self.subscribers[signal_name])
            self.subscribers[signal_name] = [
                (cb, name) for cb, name in self.subscribers[signal_name]
                if cb != callback
            ]
            removed = original_count - len(self.subscribers[signal_name])
            if removed > 0:
                self.logger.debug(f"Removed {removed} subscription(s) for {signal_name}")

    def unsubscribe_all(self, receiver_name: str):
        removed_count = 0
        for signal_name in list(self.subscribers.keys()):
            callbacks_to_remove = [
                cb for cb, name in self.subscribers[signal_name]
                if name == receiver_name
            ]

            qt_signal = self.signal_map.get(signal_name)
            if qt_signal:
                for callback in callbacks_to_remove:
                    qt_signal.disconnect(callback)

            original_count = len(self.subscribers[signal_name])
            self.subscribers[signal_name] = [
                (cb, name) for cb, name in self.subscribers[signal_name]
                if name != receiver_name
            ]
            removed_count += original_count - len(self.subscribers[signal_name])

        if removed_count > 0:
            self.logger.debug(f"Removed {removed_count} subscription(s) for {receiver_name}")

    def get_channel_info(self, signal_name: str) -> Dict[str, Any]:
        if signal_name in self.channels:
            info = self.channels[signal_name].copy()
            info['subscriber_count'] = len(self.subscribers[signal_name])
            info['subscribers'] = [name for _, name in self.subscribers[signal_name]]
            return info
        return {}

    def list_channels(self) -> List[str]:
        return list(self.channels.keys())

    def _validate_data(self, data: Dict[str, Any], expected: Dict[str, Any]) -> bool:
        for key, expected_type in expected.items():
            if key not in data:
                self.logger.error(f"Missing required key: {key}")
                return False

            if not isinstance(data[key], expected_type):
                if data[key] is None and expected_type in [str, int, float, dict, list]:
                    continue
                self.logger.error(f"Invalid type for {key}: expected {expected_type}, got {type(data[key])}")
                return False

        return True