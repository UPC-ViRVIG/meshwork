# server/client_api.py
import asyncio
import inspect
from pathlib import Path
from typing import Optional, Dict, Any, Callable, AsyncIterator, Union

import grpc
from grpc import aio
from google.protobuf.duration_pb2 import Duration

import meshwork_pb2
import meshwork_pb2_grpc
from file_ops import FileOperations
from exec_ops import OutputProcessor
from utils import ConnectionManager, format_duration, format_bytes


class MeshWorkClient:
    """Main client API for MeshWork services"""

    def __init__(self, service_name: str = "blender", address: Optional[str] = None):
        self.service_name = service_name
        self.address = ConnectionManager.get_service_address(service_name, address)
        self.channel = None
        self.stub = None
        self._connected = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self):
        """Connect to the service"""
        if self._connected:
            return

        self.channel = await ConnectionManager.create_channel(self.address, self.service_name)
        self.stub = meshwork_pb2_grpc.MeshWorkStub(self.channel)
        self._connected = True

    async def close(self):
        """Close connection"""
        if self.channel and self._connected:
            await self.channel.close()
            self._connected = False

    async def ping(self, message: str = "hello") -> dict:
        """Send ping request"""
        if not self._connected:
            await self.connect()

        try:
            request = meshwork_pb2.PingRequest(message=message)
            response = await self.stub.Ping(request)
            return {
                'success': True,
                'message': response.message,
                'timestamp': response.timestamp.ToDatetime(),
                'service': self.service_name
            }
        except grpc.RpcError as e:
            return {
                'success': False,
                'error': e.details(),
                'service': self.service_name
            }

    async def upload_file(self, local_path: str, remote_path: Optional[str] = None,
                         chunk_size: int = 64*1024, progress_callback: Optional[Callable] = None) -> dict:
        """Upload file or directory to service"""
        if not self._connected:
            await self.connect()

        local_file = Path(local_path)
        if not local_file.exists():
            return {'success': False, 'error': f"Local path not found: {local_path}"}

        if remote_path is None:
            remote_path = local_file.name

        try:
            # Determine file type and size
            if local_file.is_file():
                file_size = local_file.stat().st_size
                upload_type = "file"
            elif local_file.is_dir():
                # For directories, we need to estimate tar size
                # For progress tracking, we'll calculate total file sizes
                file_size = sum(f.stat().st_size for f in local_file.rglob('*') if f.is_file())
                upload_type = "directory"
            else:
                return {'success': False, 'error': f"Unsupported path type: {local_path}"}

            uploaded_bytes = 0

            async def upload_with_progress():
                nonlocal uploaded_bytes
                async for chunk in FileOperations.create_upload_chunks(local_file, remote_path, chunk_size):
                    uploaded_bytes += len(chunk.data)
                    if progress_callback:
                        await progress_callback('upload', uploaded_bytes, file_size)
                    yield chunk

            response = await self.stub.UploadFile(upload_with_progress())

            result = {
                'success': response.success,
                'message': response.message,
                'remote_path': response.file_path,
                'bytes_written': response.bytes_written,
                'file_size': file_size,
                'type': upload_type,
                'files_extracted': response.files_extracted,
                'service': self.service_name
            }

            if not response.success:
                result['error'] = response.message

            return result

        except grpc.RpcError as e:
            return {
                'success': False,
                'error': e.details(),
                'service': self.service_name
            }

    async def download_file(self, remote_path: str, local_path: Optional[str] = None,
                          chunk_size: int = 64*1024, progress_callback: Optional[Callable] = None) -> dict:
        """Download file or directory from service"""
        if not self._connected:
            await self.connect()

        if local_path is None:
            local_path = Path(remote_path).name

        try:
            request = meshwork_pb2.FileDownloadRequest(
                file_path=remote_path,
                chunk_size=chunk_size
            )

            download_stream = self.stub.DownloadFile(request)

            # Add progress tracking
            async def download_with_progress():
                downloaded_bytes = 0
                total_size = 0
                download_type = None
                async for response in download_stream:
                    if response.total_size > 0:
                        total_size = response.total_size
                    if download_type is None and response.type != meshwork_pb2.FILE_TYPE_UNSPECIFIED:
                        download_type = "file" if response.type == meshwork_pb2.FILE else "directory"
                    if response.data:
                        downloaded_bytes += len(response.data)
                        if progress_callback and total_size > 0:
                            await progress_callback('download', downloaded_bytes, total_size)
                    yield response

            result = await FileOperations.save_download_stream(
                download_with_progress(), Path(local_path)
            )

            result['service'] = self.service_name
            result['local_path'] = local_path
            result['remote_path'] = remote_path

            return result

        except grpc.RpcError as e:
            return {
                'success': False,
                'error': e.details(),
                'service': self.service_name
            }

    async def delete_file(self, remote_path: str) -> dict:
        """Delete file or directory from service"""
        if not self._connected:
            await self.connect()

        try:
            request = meshwork_pb2.FileDeleteRequest(file_path=remote_path)
            response = await self.stub.DeleteFile(request)

            delete_type = "file" if response.type == meshwork_pb2.FILE else "directory"

            result = {
                'success': response.success,
                'message': response.message,
                'remote_path': response.file_path,
                'type': delete_type,
                'files_deleted': response.files_deleted,
                'service': self.service_name
            }

            if not response.success:
                result['error'] = response.message

            return result

        except grpc.RpcError as e:
            return {
                'success': False,
                'error': e.details(),
                'service': self.service_name
            }

    def _detect_callback_type(self, callback: Callable) -> str:
        """Detect if callback expects bytes or text based on type annotations or parameter names"""
        if callback is None:
            return 'bytes'  # Default

        try:
            sig = inspect.signature(callback)
            params = list(sig.parameters.values())

            if len(params) >= 2:
                # Check type annotation of second parameter (data parameter)
                data_param = params[1]
                if data_param.annotation == str:
                    return 'text'
                elif data_param.annotation == bytes:
                    return 'bytes'

                # Check parameter name hints
                if 'text' in data_param.name.lower():
                    return 'text'
                elif 'data' in data_param.name.lower() or 'bytes' in data_param.name.lower():
                    return 'bytes'

            # Default to bytes for backward compatibility
            return 'bytes'

        except Exception:
            # If inspection fails, default to bytes
            return 'bytes'

    async def _create_callback_wrapper(self, original_callback: Callable, callback_type: str):
        """Create appropriate callback wrapper based on detected type"""
        if callback_type == 'text':
            async def text_callback_wrapper(stream_type: str, data: bytes):
                try:
                    text = data.decode('utf-8', errors='replace')
                    if inspect.iscoroutinefunction(original_callback):
                        await original_callback(stream_type, text)
                    else:
                        original_callback(stream_type, text)
                except Exception as e:
                    # Fallback for encoding errors
                    error_text = f"[Encoding error: {e}]\n"
                    if inspect.iscoroutinefunction(original_callback):
                        await original_callback('stderr', error_text)
                    else:
                        original_callback('stderr', error_text)
            return text_callback_wrapper
        else:
            # Return original callback for bytes
            return original_callback

    async def execute_command(self, command: list, cwd: str = "", env: Optional[Dict[str, str]] = None,
                            timeout: float = 0, output_callback: Optional[Callable] = None,
                            use_pty: Optional[bool] = None, pty_rows: int = 24, pty_cols: int = 80) -> dict:
        """Execute shell command with PTY support"""
        if not self._connected:
            await self.connect()

        try:
            request = meshwork_pb2.ExecRequest()
            request.argv.extend(command)
            if cwd:
                request.cwd = cwd
            if env:
                for k, v in env.items():
                    request.env[k] = v
            if timeout > 0:
                request.timeout.seconds = int(timeout)
                request.timeout.nanos = int((timeout % 1) * 1e9)

            # PTY configuration
            if use_pty is not None:
                request.use_pty = use_pty
            if pty_rows != 24:
                request.pty_rows = pty_rows
            if pty_cols != 80:
                request.pty_cols = pty_cols

            # Enable compression for large output
            request.preferred_codec = meshwork_pb2.CODEC_LZ4
            request.compress_threshold = 1024

            # Auto-detect callback type and create wrapper
            final_callback = None
            if output_callback:
                callback_type = self._detect_callback_type(output_callback)
                final_callback = await self._create_callback_wrapper(output_callback, callback_type)

            output_stream = self.stub.Exec(request)
            result = await OutputProcessor.process_output_stream(output_stream, final_callback)

            result['success'] = result['exit_info']['exit_code'] == 0 if result['exit_info'] else False
            result['service'] = self.service_name
            result['command'] = command

            return result

        except grpc.RpcError as e:
            return {
                'success': False,
                'error': e.details(),
                'service': self.service_name
            }

    async def execute_command_realtime(self, command: list, cwd: str = "", env: Optional[Dict[str, str]] = None,
                                     timeout: float = 0, output_callback: Optional[Callable] = None,
                                     pty_rows: int = 24, pty_cols: int = 80) -> dict:
        """Execute command with PTY for guaranteed real-time output"""
        return await self.execute_command(
            command=command, cwd=cwd, env=env, timeout=timeout,
            output_callback=output_callback, use_pty=True,
            pty_rows=pty_rows, pty_cols=pty_cols
        )

    async def execute_python(self, script_content: str = None, script_file: str = None,
                           timeout: float = 0, output_callback: Optional[Callable] = None) -> dict:
        """Execute Python script"""
        if not self._connected:
            await self.connect()

        if script_file and Path(script_file).exists():
            with open(script_file, 'r', encoding='utf-8') as f:
                script_content = f.read()

        if not script_content:
            return {
                'success': False,
                'error': 'No script content provided',
                'service': self.service_name
            }

        try:
            request = meshwork_pb2.PythonExecRequest()
            request.script_content = script_content
            if timeout > 0:
                request.timeout.seconds = int(timeout)
                request.timeout.nanos = int((timeout % 1) * 1e9)

            # Enable compression for large output
            request.preferred_codec = meshwork_pb2.CODEC_LZ4
            request.compress_threshold = 1024

            # Auto-detect callback type and create wrapper
            final_callback = None
            if output_callback:
                callback_type = self._detect_callback_type(output_callback)
                final_callback = await self._create_callback_wrapper(output_callback, callback_type)

            output_stream = self.stub.PythonExec(request)
            result = await OutputProcessor.process_output_stream(output_stream, final_callback)

            result['success'] = result['exit_info']['exit_code'] == 0 if result['exit_info'] else False
            result['service'] = self.service_name
            result['script_type'] = 'python'

            return result

        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                return {
                    'success': False,
                    'error': f'Python execution not supported on {self.service_name} service',
                    'service': self.service_name
                }
            else:
                return {
                    'success': False,
                    'error': e.details(),
                    'service': self.service_name
                }


class ProgressReporter:
    """Helper class for progress reporting"""

    def __init__(self, description: str = ""):
        self.description = description
        self.last_reported = 0

    async def __call__(self, operation: str, current: int, total: int):
        """Progress callback implementation"""
        if total > 0:
            percent = (current / total) * 100
            # Report every 5% or at completion
            if percent - self.last_reported >= 5 or current == total:
                print(f"{self.description} {operation}: {format_bytes(current)}/{format_bytes(total)} ({percent:.1f}%)")
                self.last_reported = percent


class OutputCapture:
    """Helper class for capturing command output (bytes)"""

    def __init__(self):
        self.stdout_data = []
        self.stderr_data = []

    async def __call__(self, stream_type: str, data: bytes):
        """Output callback implementation for bytes"""
        if stream_type == 'stdout':
            self.stdout_data.append(data)
        elif stream_type == 'stderr':
            self.stderr_data.append(data)

    def get_stdout(self) -> str:
        """Get captured stdout as string"""
        return b''.join(self.stdout_data).decode('utf-8', errors='replace')

    def get_stderr(self) -> str:
        """Get captured stderr as string"""
        return b''.join(self.stderr_data).decode('utf-8', errors='replace')


class TextCapture:
    """Helper class for capturing command output (text)"""

    def __init__(self):
        self.stdout_lines = []
        self.stderr_lines = []

    def __call__(self, stream_type: str, text: str):
        """Output callback implementation for text"""
        if stream_type == 'stdout':
            self.stdout_lines.append(text)
        elif stream_type == 'stderr':
            self.stderr_lines.append(text)

    def get_stdout(self) -> str:
        """Get captured stdout as string"""
        return ''.join(self.stdout_lines)

    def get_stderr(self) -> str:
        """Get captured stderr as string"""
        return ''.join(self.stderr_lines)