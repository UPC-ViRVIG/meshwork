# core/render.py
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject
from core.executor import Executor
from logger import get_logger


class RenderAPI(QObject, Executor):

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.logger = get_logger()
        self.render_settings = {}

    def initialize(self):
        self.logger.info("Render API initialized")

    async def render_image(self, config: Dict[str, Any] = None) -> bool:
        self.logger.info(f"Starting image render with config: {config}")

        render_config = self.render_settings.copy()
        if config:
            render_config.update(config)

        script = f"""
import bpy
import os

scene = bpy.context.scene
render = scene.render

render.resolution_x = {render_config.get('resolution_x', 1920)}
render.resolution_y = {render_config.get('resolution_y', 1080)}
render.resolution_percentage = {render_config.get('resolution_percentage', 100)}

render.image_settings.file_format = '{render_config.get('file_format', 'PNG')}'
render.image_settings.color_mode = '{render_config.get('color_mode', 'RGBA')}'

output_path = '{render_config.get('output_path', '/tmp/render_output.png')}'
render.filepath = output_path

render.engine = '{render_config.get('engine', 'CYCLES')}'

if render.engine == 'CYCLES':
    scene.cycles.samples = {render_config.get('samples', 128)}
    scene.cycles.use_denoising = {str(render_config.get('use_denoising', True)).lower()}

camera_name = '{render_config.get('camera', '')}'
if camera_name and camera_name in bpy.data.objects:
    scene.camera = bpy.data.objects[camera_name]

print(f"Starting render with engine: {{render.engine}}")
print(f"Resolution: {{render.resolution_x}}x{{render.resolution_y}}")
print(f"Output: {{output_path}}")

bpy.ops.render.render(write_still=True)

print("Render completed successfully")
print(f"Image saved to: {{output_path}}")
"""

        def callback(success, result, **kwargs):
            if self.signal_router:
                output_path = kwargs.get('output_path', '/tmp/render_output.png')

        executor = self._get_executor()
        if executor:
            result = await executor.exec_blender_script(script)
            callback(result.get('success', False), result, output_path=render_config.get('output_path', '/tmp/render_output.png'))
            return result.get('success', False)
        else:
            return True

    async def get_available_cameras(self) -> List[str]:
        executor = self._get_executor()
        if executor:
            script = """
import bpy

cameras = []
for obj in bpy.data.objects:
    if obj.type == 'CAMERA':
        cameras.append(obj.name)

if cameras:
    print("Available cameras:", ",".join(cameras))
else:
    print("No cameras found")
"""

            result = await executor.exec_blender_script(script)

            if result['success']:
                output = result.get('stdout', '')
                if 'Available cameras:' in output:
                    camera_names = output.split('Available cameras:')[1].strip().split(',')
                    return [name.strip() for name in camera_names if name.strip()]
                return []
            else:
                return []
        else:
            return ['Camera']

    async def set_active_camera(self, camera_name: str) -> bool:
        self.logger.info(f"Setting active camera: {camera_name}")

        script = f"""
import bpy

camera_obj = bpy.data.objects.get('{camera_name}')
if camera_obj and camera_obj.type == 'CAMERA':
    bpy.context.scene.camera = camera_obj
    print(f"Active camera set to: {{camera_obj.name}}")
else:
    print(f"Camera '{camera_name}' not found")
    exit(1)
"""

        def callback(success, result, **kwargs):
            if self.signal_router:
                camera_name = kwargs.get('camera_name', '')

        executor = self._get_executor()
        if executor:
            result = await executor.exec_blender_script(script)
            callback(result.get('success', False), result, camera_name=camera_name)
            return result.get('success', False)
        else:
            return True