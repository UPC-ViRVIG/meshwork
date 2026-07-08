# core/executor.py
import asyncio
import time
import os
from typing import Dict, Any, Optional, Callable
from pathlib import Path
from PySide6.QtCore import QObject
from server.client_api import MeshWorkClient
from config import get_config
from logger import get_logger


class Executor:

    def _get_executor(self):
        worker_thread = self.parent()
        if not worker_thread or not hasattr(worker_thread, 'get_api'):
            return None
        return worker_thread.get_api('executor')

    def exec_blender_python(self, script_content: str, callback: Optional[Callable] = None, **kwargs):

        async def script_async():
            executor = self._get_executor()

            if executor:
                result = await executor.exec_blender_script(script_content)
                success = result.get('success', False)

                if callback:
                    callback(success, result, **kwargs)
            else:
                if callback:
                    callback(True, {'success': True, 'message': 'No executor available'}, **kwargs)

        asyncio.create_task(script_async())

    def ping(self, service: str = 'blender', message: str = "ping", callback: Optional[Callable] = None, **kwargs):

        async def ping_async():
            executor_api = self._get_executor()

            if not executor_api:
                result = {'success': False, 'error': 'Executor API not available'}
            else:
                result = await executor_api.ping_async(service, message)

            if callback:
                callback(result.get('success', False), result, **kwargs)

        asyncio.create_task(ping_async())

    def upload(self, local_path: str, remote_path: str = None, service: str = 'blender',
               callback: Optional[Callable] = None, **kwargs):

        async def upload_async():
            executor_api = self._get_executor()
            if not executor_api:
                result = {'success': False, 'error': 'Executor API not available'}
            else:
                result = await executor_api.upload_file_async(local_path, service, remote_path)

            if callback:
                callback(result.get('success', False), result, **kwargs)

        asyncio.create_task(upload_async())

    def download(self, remote_path: str, local_path: str = None, service: str = 'blender',
                 callback: Optional[Callable] = None, **kwargs):

        async def download_async():
            executor_api = self._get_executor()
            if not executor_api:
                result = {'success': False, 'error': 'Executor API not available'}
            else:
                result = await executor_api.download_file_async(remote_path, service, local_path)

            if callback:
                callback(result.get('success', False), result, **kwargs)

        asyncio.create_task(download_async())

    def delete(self, remote_path: str, service: str = 'blender', callback: Optional[Callable] = None, **kwargs):

        async def delete_async():
            executor_api = self._get_executor()
            if not executor_api:
                result = {'success': False, 'error': 'Executor API not available'}
            else:
                result = await executor_api.delete_file_async(remote_path, service)

            if callback:
                callback(result.get('success', False), result, **kwargs)

        asyncio.create_task(delete_async())

    def exec_cmd(self, service: str, command: list, cwd: str = "", env: dict = None, timeout: float = 0,
                 output_callback: Optional[Callable] = None, callback: Optional[Callable] = None, **kwargs):

        async def exec_cmd_async():
            executor_api = self._get_executor()
            if not executor_api:
                result = {'success': False, 'error': 'Executor API not available'}
            else:
                result = await executor_api.execute_command_async(service, command, cwd, env, timeout, output_callback)

            if callback:
                callback(result.get('success', False), result, **kwargs)

        asyncio.create_task(exec_cmd_async())


class ExecutorAPI(QObject):

    def __init__(self, signal_router, parent=None):
        super().__init__(parent)
        self.signal_router = signal_router
        self.config = get_config()
        self.logger = get_logger()
        self.blender_client = None
        self.colmap_client = None
        self.alicevision_client = None
        self._setup_signal_handlers()

    def initialize(self):
        self.logger.info("Executor API initialized")

    def _setup_signal_handlers(self):
        if self.signal_router:
            self.signal_router.subscribe('executor.do_execute_script', self.do_execute_script, 'ExecutorAPI')
            self.signal_router.subscribe('executor.do_upload_file', self.do_upload_file, 'ExecutorAPI')

    def do_execute_script(self, data: Dict[str, Any]):
        script = data.get('script', '')
        timeout = data.get('timeout', 0.0)

        self.logger.info(f"Execute script request: timeout={timeout}")
        self.logger.info(f"Script content length: {len(script)} chars")
        self.logger.debug(f"Script content preview: {script[:200]}...")

        if not script.strip():
            self.logger.warning("Empty script provided")
            self._send_script_completion(False, {'error': 'Empty script'})
            return

        async def execute_async():
            start_time = time.time()
            result = await self.exec_blender_script_async(script, timeout)
            duration = time.time() - start_time
            result['duration'] = duration

            self.logger.info(f"Script execution completed: success={result.get('success')}, duration={duration:.3f}s")
            self._send_script_completion(result['success'], result)

        asyncio.create_task(execute_async())

    async def do_upload_file(self, data: Dict[str, Any]):
        local_path = data.get('local_path', '')
        remote_path = data.get('remote_path', '')
        service = data.get('service', 'blender')

        result = await self.upload_file_async(local_path, service, remote_path)

        if self.signal_router:
            self.signal_router.emit('executor.done_file_transferred', {
                'operation_type': 'upload',
                'file_path': local_path,
                'success': result['success'],
                'error': result.get('error', '')
            })

    def _send_script_completion(self, success: bool, result: dict):
        self.logger.debug(f"Sending completion signal: success={success}")
        if self.signal_router:
            self.signal_router.emit('executor.done_script_executed', {
                'success': success,
                'result': result,
                'duration': result.get('duration', 0.0)
            })

    def get_service_address(self, service_name: str) -> str:
        return self.config.get_service_address(service_name)

    async def _exec_blender_script(self, script_content: str, timeout: float = 30.0, output_callback: Optional[Callable] = None) -> dict:
        self.logger.info(f"Executing Blender script (length: {len(script_content)})")
        self.logger.debug(f"Script timeout: {timeout}s")
        self.logger.info(f"Full script content:\n{script_content[:100]}")

        if not self.blender_client:
            address = self.get_service_address('blender')
            self.logger.debug(f"Creating Blender client for address: {address}")
            self.blender_client = MeshWorkClient('blender', address)
            await self.blender_client.connect()
            self.logger.debug("Blender client connected successfully")

        output_lines = []
        error_lines = []

        async def collect_output(stream_type: str, text: str):
            self.logger.debug(f"Script output [{stream_type}]: {text.strip()}")

            if stream_type == 'stdout':
                output_lines.append(text)
            elif stream_type == 'stderr':
                error_lines.append(text)

            if output_callback:
                if asyncio.iscoroutinefunction(output_callback):
                    await output_callback(stream_type, text)
                else:
                    output_callback(stream_type, text)

        self.logger.info("Calling client_api.execute_python")

        result = await self.blender_client.execute_python(
            script_content=script_content,
            timeout=timeout,
            output_callback=collect_output
        )

        self.logger.info(f"Client API returned: success={result.get('success')}")
        self.logger.debug(f"Full client result: {result}")

        result['stdout'] = ''.join(output_lines)
        result['stderr'] = ''.join(error_lines)

        self.logger.info(f"Collected stdout length: {len(result['stdout'])} chars")
        self.logger.info(f"Collected stderr length: {len(result['stderr'])} chars")

        if result['stdout']:
            self.logger.debug(f"Stdout content: {result['stdout']}")
        if result['stderr']:
            self.logger.debug(f"Stderr content: {result['stderr']}")

        if result['success']:
            self.logger.info("Blender script completed successfully")
        else:
            error_msg = result.get('error', 'Unknown error')
            self.logger.error(f"Blender script failed: {error_msg}")

        return result

    async def exec_blender_script(self, script_content: str, timeout: float = 30.0) -> dict:
        def output_callback(stream_type: str, text: str):
            if stream_type == 'stdout' and text.strip():
                self.logger.debug(f"Script stdout: {text.strip()[:100]}")
            elif stream_type == 'stderr' and text.strip():
                self.logger.warning(f"Script stderr: {text.strip()}")

        return await self._exec_blender_script(script_content, timeout, output_callback)

    async def exec_blender_script_async(self, script_content: str, timeout: float = 30.0) -> dict:
        async def output_callback(stream_type: str, text: str):
            if self.signal_router:
                self.signal_router.emit('executor.incremental_output', {
                    'stream': stream_type,
                    'text': text,
                    'timestamp': time.time()
                })

        return await self._exec_blender_script(script_content, timeout, output_callback)

    async def _get_or_create_client(self, service: str) -> MeshWorkClient:
        if service == 'blender':
            if not self.blender_client:
                self.blender_client = MeshWorkClient(service, self.get_service_address(service))
                await self.blender_client.connect()
            return self.blender_client
        elif service == 'colmap':
            if not self.colmap_client:
                self.colmap_client = MeshWorkClient(service, self.get_service_address(service))
                await self.colmap_client.connect()
            return self.colmap_client
        elif service == 'alicevision':
            if not self.alicevision_client:
                self.alicevision_client = MeshWorkClient(service, self.get_service_address(service))
                await self.alicevision_client.connect()
            return self.alicevision_client
        else:
            raise ValueError(f"Unknown service: {service}")

    async def upload_file_async(self, local_path: str, service: str = 'blender',
                               remote_path: Optional[str] = None) -> dict:
        if not Path(local_path).exists():
            return {'success': False, 'error': f'File not found: {local_path}'}

        client = await self._get_or_create_client(service)
        result = await client.upload_file(local_path, remote_path)

        if result['success']:
            self.logger.info(f"File uploaded to {service}")
        else:
            self.logger.error(f"Upload failed: {result.get('error', 'Unknown error')}")

        return result

    async def download_file_async(self, remote_path: str, service: str = 'blender',
                                 local_path: Optional[str] = None) -> dict:
        client = await self._get_or_create_client(service)
        result = await client.download_file(remote_path, local_path)

        if result['success']:
            self.logger.info(f"File downloaded from {service}")
        else:
            self.logger.error(f"Download failed: {result.get('error', 'Unknown error')}")

        return result

    async def delete_file_async(self, remote_path: str, service: str = 'blender') -> dict:
        client = await self._get_or_create_client(service)
        result = await client.delete_file(remote_path)

        if result['success']:
            self.logger.info(f"File deleted from {service}")
        else:
            self.logger.error(f"Delete failed: {result.get('error', 'Unknown error')}")

        return result

    async def execute_command_async(self, service: str, command: list, cwd: str = "", env: dict = None,
                                  timeout: float = 0, output_callback: Optional[Callable] = None) -> dict:
        address = self.get_service_address(service)
        client = None
        use_pty = output_callback is not None

        if service == 'blender':
            if not self.blender_client:
                self.blender_client = MeshWorkClient('blender', address)
                await self.blender_client.connect()
            client = self.blender_client
        elif service == 'colmap':
            if not self.colmap_client:
                self.colmap_client = MeshWorkClient('colmap', address)
                await self.colmap_client.connect()
            client = self.colmap_client
        elif service == 'alicevision':
            if not self.alicevision_client:
                self.alicevision_client = MeshWorkClient('alicevision', address)
                await self.alicevision_client.connect()
            client = self.alicevision_client

        cmd_str = ' '.join(command)
        self.logger.info(f"Executing {service} command: {cmd_str}")
        if use_pty:
            self.logger.debug(f"Using PTY mode for real-time output")

        result = await client.execute_command(
            command=command,
            cwd=cwd,
            env=env,
            timeout=timeout,
            output_callback=output_callback,
            use_pty=use_pty
        )

        if result['success']:
            self.logger.info(f"{service} command completed")
        else:
            self.logger.error(f"{service} command failed: {result.get('error', 'Unknown error')}")

        return result

    async def ping_async(self, service: str = 'blender', message: str = 'hello') -> dict:
        address = self.get_service_address(service)
        async with MeshWorkClient(service, address) as client:
            return await client.ping(message)

    async def close_connections(self):
        if self.blender_client:
            await self.blender_client.close()
            self.blender_client = None
        if self.colmap_client:
            await self.colmap_client.close()
            self.colmap_client = None
        if self.alicevision_client:
            await self.alicevision_client.close()
            self.alicevision_client = None
        self.logger.info("All client connections closed")

    def cleanup(self):
        if self.signal_router:
            self.signal_router.unsubscribe_all('ExecutorAPI')