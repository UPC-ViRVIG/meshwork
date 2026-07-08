# core/project.py
from typing import Dict, Optional, Any
import os
import time
from pathlib import Path
from PySide6.QtCore import QObject
from core.executor import Executor
from core.coredata import get_scene_manager
from logger import get_logger


class ProjectAPI(QObject, Executor):

    SUPPORTED_IMPORT_FORMATS = ['.obj', '.ply', '.stl']
    SUPPORTED_EXPORT_FORMATS = ['.obj', '.ply', '.stl']

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.scene_manager = get_scene_manager()
        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("Project API initialized")

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('project.do_new', self.do_new_project, 'ProjectAPI')
            self.signal_router.subscribe('project.do_open', self.do_open_project, 'ProjectAPI')
            self.signal_router.subscribe('project.do_save', self.do_save_project, 'ProjectAPI')
            self.signal_router.subscribe('project.do_import', self.do_import_file, 'ProjectAPI')
            self.signal_router.subscribe('project.do_export', self.do_export_file, 'ProjectAPI')

    def do_new_project(self, data: Dict[str, Any]):
        self.logger.info("Creating new project")

        script = """
import bpy

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

for material in bpy.data.materials:
    bpy.data.materials.remove(material)

for mesh in bpy.data.meshes:
    bpy.data.meshes.remove(mesh)

print("New project created")
"""

        def callback(success, result, **kwargs):
            if success:
                if self.signal_router:
                    self.signal_router.emit('scene.request_sync', {})
                self.logger.info("New project created successfully")
            else:
                self.logger.error(f"Failed to create new project: {result.get('error', 'Unknown error')}")

            if self.signal_router:
                self.signal_router.emit('project.done_new', {
                    'success': success,
                    'error': result.get('error', '') if not success else ''
                })

        self.exec_blender_python(script, callback)

    def do_open_project(self, data: Dict[str, Any]):
        file_path = data.get('file_path', '')
        if not file_path:
            self.logger.error("No file path provided for open")
            return

        self.logger.info(f"Opening project: {file_path}")

        temp_filename = self._generate_temp_filename(file_path)

        def upload_callback(success, result, **kwargs):
            if not success:
                self.logger.error(f"Failed to upload file: {result.get('error', 'Unknown error')}")
                if self.signal_router:
                    self.signal_router.emit('project.done_open', {
                        'success': False,
                        'error': result.get('error', 'Upload failed')
                    })
                return

            script = f"""
import bpy

try:
    bpy.ops.wm.open_mainfile(filepath='/workspace/{temp_filename}')
    print("Project opened successfully")
except Exception as e:
    print(f"Error opening project: {{str(e)}}")
    exit(1)
"""

            def script_callback(success, result, **kwargs):
                def cleanup_callback(cleanup_success, cleanup_result, **kwargs):
                    if success:
                        if self.signal_router:
                            self.signal_router.emit('scene.request_sync', {})
                        self.logger.info("Project opened successfully")
                    else:
                        self.logger.error(f"Failed to open project: {result.get('error', 'Unknown error')}")

                    if self.signal_router:
                        self.signal_router.emit('project.done_open', {
                            'success': success,
                            'error': result.get('error', '') if not success else ''
                        })

                self.delete(temp_filename, callback=cleanup_callback)

            self.exec_blender_python(script, script_callback)

        self.upload(file_path, temp_filename, callback=upload_callback)

    def do_save_project(self, data: Dict[str, Any]):
        file_path = data.get('file_path', '')
        if not file_path:
            self.logger.error("No file path provided for save")
            return

        self.logger.info(f"Saving project to: {file_path}")

        temp_filename = self._generate_temp_filename(file_path)

        script = f"""
import bpy

try:
    bpy.ops.wm.save_as_mainfile(filepath='/workspace/{temp_filename}')
    print("Project saved successfully")
except Exception as e:
    print(f"Error saving project: {{str(e)}}")
    exit(1)
"""

        def script_callback(success, result, **kwargs):
            if not success:
                self.logger.error(f"Failed to save project: {result.get('error', 'Unknown error')}")
                self._cleanup_temp_path(temp_filename)
                if self.signal_router:
                    self.signal_router.emit('project.done_save', {
                        'success': False,
                        'error': result.get('error', 'Save failed')
                    })
                return

            def download_callback(success, result, **kwargs):
                def cleanup_callback(cleanup_success, cleanup_result, **kwargs):
                    if self.signal_router:
                        self.signal_router.emit('project.done_save', {
                            'success': success,
                            'error': result.get('error', '') if not success else ''
                        })

                    if success:
                        self.logger.info("Project saved successfully")
                    else:
                        self.logger.error(f"Failed to download saved file: {result.get('error', 'Unknown error')}")

                self.delete(temp_filename, callback=cleanup_callback)

            if success:
                self.download(temp_filename, kwargs.get('target_path'),
                             callback=download_callback, target_path=kwargs.get('target_path', ''))
            else:
                self.logger.error(f"Failed to download saved file: {result.get('error', 'Unknown error')}")
                self._cleanup_temp_path(temp_filename)

        self.exec_blender_python(script, script_callback, target_path=file_path)

    def do_import_file(self, data: Dict[str, Any]):
        file_path = data.get('file_path', '')
        if not file_path:
            self.logger.error("No file path provided for import")
            return

        file_format = self._get_file_format(file_path)
        if file_format not in self.SUPPORTED_IMPORT_FORMATS:
            self.logger.error(f"Unsupported import format: {file_format}")
            if self.signal_router:
                self.signal_router.emit('project.done_import', {
                    'success': False,
                    'error': f'Unsupported format: {file_format}'
                })
            return

        self.logger.info(f"Importing file: {file_path} (format: {file_format})")

        dir_path = os.path.dirname(file_path)
        client_parent_dir = str(Path(file_path).parent)
        filename = os.path.basename(file_path)
        temp_dir_name = self._generate_temp_dirname(dir_path)

        def upload_callback(success, result, **kwargs):
            if not success:
                self.logger.error(f"Failed to upload directory: {result.get('error', 'Unknown error')}")
                if self.signal_router:
                    self.signal_router.emit('project.done_import', {
                        'success': False,
                        'error': result.get('error', 'Upload failed')
                    })
                return

            script = self._generate_import_script(
                kwargs.get('file_format', ''),
                kwargs.get('temp_dir_name', ''),
                kwargs.get('filename', ''),
                client_parent_dir
            )

            if not script:
                self.logger.error(f"No import script for format: {kwargs.get('file_format', '')}")
                self._cleanup_temp_path(kwargs.get('temp_dir_name', ''))
                if self.signal_router:
                    self.signal_router.emit('project.done_import', {
                        'success': False,
                        'error': f'No importer for format: {kwargs.get("file_format", "")}'
                    })
                return

            def import_callback(success, result, **kwargs):
                if not success:
                    self.logger.error(f"Failed to import file: {result.get('error', 'Unknown error')}")
                    self._cleanup_temp_path(kwargs.get('temp_dir_name', ''))
                    if self.signal_router:
                        self.signal_router.emit('project.done_import', {
                            'success': False,
                            'error': result.get('error', 'Import failed')
                        })
                    return

                pack_script = self._generate_texture_pack_script()

                def pack_callback(pack_success, pack_result, **kwargs):
                    if pack_success:
                        self.logger.info("Textures packed successfully")
                    else:
                        self.logger.warning(f"Texture packing had issues: {pack_result.get('error', '')}")

                    def cleanup_callback(cleanup_success, cleanup_result, **kwargs):
                        if self.signal_router:
                            self.signal_router.emit('scene.request_sync', {})
                        self.logger.info(f"File imported successfully: {os.path.basename(kwargs.get('original_path', ''))}")

                        if self.signal_router:
                            self.signal_router.emit('project.done_import', {
                                'success': True,
                                'error': ''
                            })

                    self.delete(kwargs.get('temp_dir_name', ''), callback=cleanup_callback,
                               original_path=kwargs.get('original_path', ''))

                self.exec_blender_python(pack_script, pack_callback,
                                       temp_dir_name=kwargs.get('temp_dir_name', ''),
                                       original_path=kwargs.get('original_path', ''))

            self.exec_blender_python(script, import_callback,
                                   temp_dir_name=kwargs.get('temp_dir_name', ''),
                                   original_path=kwargs.get('original_path', ''))

        self.upload(dir_path, temp_dir_name, callback=upload_callback,
                   file_format=file_format, temp_dir_name=temp_dir_name,
                   filename=filename, original_path=file_path)

    def do_export_file(self, data: Dict[str, Any]):
        file_path = data.get('file_path', '')
        if not file_path:
            self.logger.error("No file path provided for export")
            return

        file_format = self._get_file_format(file_path)
        if file_format not in self.SUPPORTED_EXPORT_FORMATS:
            self.logger.error(f"Unsupported export format: {file_format}")
            if self.signal_router:
                self.signal_router.emit('project.done_export', {
                    'success': False,
                    'error': f'Unsupported format: {file_format}'
                })
            return

        self.logger.info(f"Exporting selected objects to: {file_path} (format: {file_format})")

        selected_objects = self.scene_manager.get_selected_names()
        if not selected_objects:
            self.logger.error("No objects selected for export")
            if self.signal_router:
                self.signal_router.emit('project.done_export', {
                    'success': False,
                    'error': 'No objects selected for export'
                })
            return

        temp_filename = self._generate_temp_filename(file_path)
        script = self._generate_export_script(file_format, temp_filename, selected_objects)

        if not script:
            self.logger.error(f"No export script for format: {file_format}")
            if self.signal_router:
                self.signal_router.emit('project.done_export', {
                    'success': False,
                    'error': f'No exporter for format: {file_format}'
                })
            return

        def script_callback(success, result, **kwargs):
            if not success:
                self.logger.error(f"Failed to export file: {result.get('error', 'Unknown error')}")
                if self.signal_router:
                    self.signal_router.emit('project.done_export', {
                        'success': False,
                        'error': result.get('error', 'Export failed')
                    })
                return

            def download_callback(success, result, **kwargs):
                def cleanup_callback(cleanup_success, cleanup_result, **kwargs):
                    if self.signal_router:
                        self.signal_router.emit('project.done_export', {
                            'success': success,
                            'error': result.get('error', '') if not success else ''
                        })

                    if success:
                        self.logger.info(f"File exported successfully: {os.path.basename(kwargs.get('target_path', ''))}")
                    else:
                        self.logger.error(f"Failed to download exported file: {result.get('error', 'Unknown error')}")

                self.delete(temp_filename, callback=cleanup_callback,
                           target_path=kwargs.get('target_path', ''))

            if success:
                self.download(temp_filename, kwargs.get('target_path'),
                             callback=download_callback, target_path=kwargs.get('target_path', ''))
            else:
                self.logger.error(f"Failed to download exported file: {result.get('error', 'Unknown error')}")
                self._cleanup_temp_path(temp_filename)

        self.exec_blender_python(script, script_callback, target_path=file_path)

    def _generate_import_script(self, file_format: str, temp_dir_name: str, filename: str, client_parent_dir: str = '') -> str:
        format_map = {
            '.obj': 'obj_import',
            '.ply': 'ply_import',
            '.stl': 'stl_import'
        }

        import_op = format_map.get(file_format)
        if not import_op:
            return ""

        remote_file_path = f'/workspace/{temp_dir_name}/{filename}'

        return f"""
import bpy

bpy.ops.wm.{import_op}(filepath='{remote_file_path}')

imported_objects = [obj for obj in bpy.context.selected_objects]

if imported_objects:
    client_parent_dir = "{client_parent_dir}"
    for obj in imported_objects:
        if client_parent_dir:
            obj["client_source_directory"] = client_parent_dir
    print(f"Imported {{len(imported_objects)}} objects")
else:
    print("No objects imported")
    exit(1)
"""

    def _generate_texture_pack_script(self) -> str:
        return """
import bpy

packed_count = 0
failed_count = 0

for img in bpy.data.images:
    if img.source == 'FILE' and not img.packed_file:
        if img.filepath:
            try:
                img.pack()
                packed_count += 1
            except Exception as e:
                failed_count += 1

print(f"Texture packing completed: packed={packed_count}, failed={failed_count}")
"""

    def _generate_export_script(self, file_format: str, temp_filename: str, selected_objects: list) -> str:
        format_map = {
            '.obj': 'obj_export',
            '.ply': 'ply_export',
            '.stl': 'stl_export'
        }

        export_op = format_map.get(file_format)
        if not export_op:
            return ""

        return f"""
import bpy

bpy.ops.object.select_all(action='DESELECT')

selected_names = {selected_objects}
selected_count = 0

for name in selected_names:
    if name in bpy.context.scene.objects:
        obj = bpy.context.scene.objects[name]
        obj.select_set(True)
        selected_count += 1

if selected_count == 0:
    print("No valid objects found for export")
    exit(1)

bpy.ops.wm.{export_op}(filepath='/workspace/{temp_filename}', export_selected_objects=True)

bpy.ops.object.select_all(action='DESELECT')

print("{file_format.upper()} export completed")
"""

    def _generate_temp_filename(self, original_path: str) -> str:
        return os.path.basename(original_path)

    def _generate_temp_dirname(self, dir_path: str) -> str:
        dir_name = os.path.basename(dir_path.rstrip(os.sep))
        timestamp = int(time.time())
        return f"{dir_name}_{timestamp}"

    def _get_file_format(self, file_path: str) -> str:
        return Path(file_path).suffix.lower()

    def _cleanup_temp_path(self, temp_path: str):
        def cleanup_callback(success, result, **kwargs):
            if not success:
                self.logger.warning(f"Failed to cleanup temp path: {temp_path}")

        self.delete(temp_path, callback=cleanup_callback)

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ProjectAPI')