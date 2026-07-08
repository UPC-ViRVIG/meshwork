#!/usr/bin/env python3
# server/main.py
import asyncio
import os
import sys
from pathlib import Path

# Check Blender environment
try:
    import bpy
    BLENDER_ENV = True
    print(f"Running in Blender Python environment")
    print(f"Blender version: {bpy.app.version_string}")
except ImportError:
    BLENDER_ENV = False
    print("Running in standard Python environment")

import grpc
from grpc import aio
from google.protobuf.timestamp_pb2 import Timestamp

import meshwork_pb2
import meshwork_pb2_grpc
from file_ops import FileOperations
from exec_ops import ExecutionOperations, PythonExecutionQueue
from utils import get_workspace_path, setup_environment_detection, ConnectionManager


class MeshWorkService(meshwork_pb2_grpc.MeshWorkServicer):
    """Main gRPC service implementation"""

    def __init__(self, service_type="blender", python_queue=None):
        self.service_type = service_type
        self.workspace = get_workspace_path()
        self.python_queue = python_queue
        print(f"Service type: {service_type}")
        print(f"Workspace: {self.workspace}")

    async def Ping(self, request, context):
        """Simple ping implementation"""
        response = meshwork_pb2.PingResponse()
        response.message = f"pong: {request.message}"
        response.timestamp.GetCurrentTime()
        return response

    async def UploadFile(self, request_iterator, context):
        """Handle streaming file upload"""
        return await FileOperations.handle_upload_stream(request_iterator, self.workspace)

    async def DownloadFile(self, request, context):
        """Handle streaming file download"""
        async for response in FileOperations.create_download_stream(
            request.file_path, request.chunk_size or 64*1024, self.workspace
        ):
            yield response

    async def DeleteFile(self, request, context):
        """Handle file/directory deletion"""
        return await FileOperations.handle_delete_request(request.file_path, self.workspace)

    async def Exec(self, request, context):
        """Execute shell command"""
        # Setup compression config
        compression_config = {
            'preferred_codec': request.preferred_codec,
            'compress_threshold': request.compress_threshold
        }

        # Convert timeout
        timeout = 0
        if request.timeout.seconds > 0 or request.timeout.nanos > 0:
            timeout = request.timeout.seconds + request.timeout.nanos / 1e9

        # Convert environment
        env_vars = dict(request.env) if request.env else None

        # Handle PTY parameters
        use_pty = request.use_pty if request.HasField('use_pty') else None
        pty_rows = request.pty_rows if request.pty_rows > 0 else 24
        pty_cols = request.pty_cols if request.pty_cols > 0 else 80

        # Validate PTY settings
        if pty_rows > 200 or pty_cols > 500:
            # Reasonable limits for terminal size
            pty_rows = min(pty_rows, 200)
            pty_cols = min(pty_cols, 500)

        async for frame in ExecutionOperations.execute_command(
            list(request.argv), request.cwd, env_vars, timeout, compression_config,
            use_pty, pty_rows, pty_cols
        ):
            yield frame

    async def PythonExec(self, request, context):
        """Execute Python script"""
        # Check if this service supports Python execution
        if self.service_type in ["colmap", "alicevision"]:
            context.abort(grpc.StatusCode.UNIMPLEMENTED,
                         f"Python execution not supported on {self.service_type} service")
            return

        # Blender service requires Blender environment
        if self.service_type == "blender" and not BLENDER_ENV:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                         "Blender environment not available for Python execution")
            return

        # Setup compression config
        compression_config = {
            'preferred_codec': request.preferred_codec,
            'compress_threshold': request.compress_threshold
        }

        # Convert timeout
        timeout = 0
        if request.timeout.seconds > 0 or request.timeout.nanos > 0:
            timeout = request.timeout.seconds + request.timeout.nanos / 1e9

        # Execute Python using the queue (main thread execution)
        async for frame in ExecutionOperations.execute_python_direct(
            request.script_content, timeout, compression_config, self.python_queue
        ):
            yield frame


async def create_service(service_type="blender"):
    """Create and initialize service with Python execution queue"""
    python_queue = None

    # Only create Python queue for services that support Python execution
    if service_type in ["blender"]:
        python_queue = PythonExecutionQueue(max_queue_size=50)
        await python_queue.start()
        print(f"Python execution queue started for {service_type} service")

    service = MeshWorkService(service_type, python_queue)
    return service, python_queue


async def serve():
    """Start the gRPC service"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--service', default='blender', help='Service type')
    parser.add_argument('--port', type=int, default=50051, help='Service port')
    args, unknown = parser.parse_known_args()

    # Setup environment
    env_info = setup_environment_detection()
    for key, value in env_info.items():
        print(f"{key}: {value}")

    # Create service with Python queue
    service_instance, python_queue = await create_service(args.service)

    # Get gRPC options for server
    server_options = ConnectionManager.get_grpc_options(is_uds=False)

    # Create gRPC server with options
    server = aio.server(options=server_options)
    meshwork_pb2_grpc.add_MeshWorkServicer_to_server(service_instance, server)

    # Check if UDS_ONLY mode is enabled
    uds_only = os.environ.get('UDS_ONLY', 'false').lower() in ('true', '1', 'yes')

    # Always setup Unix Domain Socket
    socket_path = f"/socks/{args.service}.sock"
    os.makedirs(os.path.dirname(socket_path), exist_ok=True)
    if os.path.exists(socket_path):
        os.unlink(socket_path)

    server.add_insecure_port(f'unix:{socket_path}')
    print(f"{args.service.upper()} Service listening on UDS: {socket_path}")

    # Also setup TCP socket if not in UDS_ONLY mode
    if not uds_only:
        tcp_addr = f"0.0.0.0:{args.port}"
        server.add_insecure_port(tcp_addr)
        print(f"{args.service.upper()} Service listening on TCP: {tcp_addr}")
    else:
        print(f"{args.service.upper()} Service running in UDS_ONLY mode")

    print(f"GPU Available: {os.getenv('GPU_AVAILABLE', 'unknown')}")
    print(f"CUDA Devices: {os.getenv('CUDA_VISIBLE_DEVICES', 'unknown')}")

    # PTY availability check
    from exec_ops import ExecutionOperations
    pty_available = ExecutionOperations._pty_available()
    print(f"PTY Available: {pty_available}")

    await server.start()
    print(f"{args.service.upper()} Service started successfully!")

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        print("Server shutting down...")

        # Stop Python queue gracefully
        if python_queue:
            print("Stopping Python execution queue...")
            await python_queue.stop()
            print("Python execution queue stopped")

        await server.stop(5)


if __name__ == "__main__":
    asyncio.run(serve())