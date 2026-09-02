# server/utils.py
import os
import hashlib
import lz4.frame
import re
import ipaddress
from pathlib import Path
from typing import Optional, Dict, Any, Callable, AsyncIterator, Tuple

import grpc
from grpc import aio

import meshwork_pb2


class ConnectionManager:
    """Manages gRPC connections with fallback logic"""

    @staticmethod
    def _load_env_file() -> Dict[str, str]:
        search_paths = [
            Path(__file__).parent.parent / "docker" / ".env",
            Path(__file__).parent.parent / "docker" / ".env.example",
        ]
        for env_path in search_paths:
            if env_path.exists():
                result = {}
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            result[key.strip()] = value.strip()
                return result
        return {}

    @staticmethod
    def get_service_address(service_name: str, override_addr: Optional[str] = None) -> str:
        if override_addr:
            return override_addr

        env_key = f"MESHWORK_{service_name.upper()}"

        env_value = os.environ.get(env_key)
        if env_value:
            return env_value

        env_file = ConnectionManager._load_env_file()
        if env_key in env_file:
            return env_file[env_key]

        return "localhost"

    @staticmethod
    def get_grpc_options(is_uds: bool = False, is_server: bool = False) -> list:
        """Get gRPC channel/server options based on connection type and role"""
        try:
            from config import get_config
            config = get_config()
            grpc_config = config.get("comm", "grpc", {})
        except:
            grpc_config = {}

        # Base message size limit (1GB default)
        max_message_size = grpc_config.get("max_message_size_mb", 1000) * 1024 * 1024

        options = [
            ('grpc.max_receive_message_length', max_message_size),
            ('grpc.max_send_message_length', max_message_size),
        ]

        keepalive_time = grpc_config.get("keepalive_time_ms", 30000)
        keepalive_timeout = grpc_config.get("keepalive_timeout_ms", 10000)
        keepalive_permit = grpc_config.get("keepalive_permit_without_calls", True)
        min_ping_interval = grpc_config.get("min_ping_interval_ms", 10000)

        if is_server:
            options.extend([
                ('grpc.keepalive_time_ms', keepalive_time),
                ('grpc.keepalive_timeout_ms', keepalive_timeout),
                ('grpc.keepalive_permit_without_calls', keepalive_permit),
                ('grpc.http2.max_ping_strikes', 0),
                ('grpc.http2.min_ping_interval_without_data_ms',
                 max(1000, min(min_ping_interval, keepalive_time))),
            ])
        elif not is_uds:
            options.extend([
                ('grpc.keepalive_time_ms', keepalive_time),
                ('grpc.keepalive_timeout_ms', keepalive_timeout),
                ('grpc.keepalive_permit_without_calls', keepalive_permit),
                ('grpc.http2.max_pings_without_data', 0),
                ('grpc.http2.min_time_between_pings_ms',
                 max(1000, min(min_ping_interval, keepalive_time))),
            ])

        return options

    @staticmethod
    def _is_valid_ipv4(address: str) -> bool:
        """Check if address is valid IPv4"""
        try:
            parts = address.split('.')
            return len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts)
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _is_valid_ipv6(address: str) -> bool:
        """Check if address is valid IPv6"""
        try:
            ipaddress.IPv6Address(address)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_valid_domain(address: str) -> bool:
        """Check if address is valid domain or hostname"""
        pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$'
        return bool(re.match(pattern, address))

    @staticmethod
    def _is_valid_port(port_str: str) -> bool:
        """Check if port string is valid port number"""
        try:
            port = int(port_str)
            return 1 <= port <= 65535
        except (ValueError, TypeError):
            return False

    @staticmethod
    async def create_channel(address: str, service_name: str = "blender"):
        """Create gRPC channel with Unix socket fallback"""
        socket_path = ""
        is_uds = False

        # Step 1: Handle localhost with default socket path
        if address == 'localhost':
            socket_path = f"../.runtime/socks/{service_name}.sock"
        else:
            # Step 2: Parse unix prefix
            if address.startswith('unix://'):
                socket_path = address[7:]
            elif address.startswith('unix:'):
                socket_path = address[5:]

        # Step 3: Check socket path existence
        if socket_path:
            if Path(socket_path).exists():
                print(f"Using Unix socket: {socket_path}")
                is_uds = True
                options = ConnectionManager.get_grpc_options(is_uds=True)
                return aio.insecure_channel(f'unix:{socket_path}', options=options)
            else:
                print(f"Warning: Unix socket not found at {socket_path}")
                print("Falling back to local TCP connection")
                address = "127.0.0.1"
                socket_path = ""

        # Step 4: Handle network address
        host = address
        port = None

        # Parse existing port
        if address.startswith('[') and ']:' in address:
            # IPv6 with port: [::1]:8080
            host, port_str = address.rsplit(']:', 1)
            host = host[1:]
            if not ConnectionManager._is_valid_port(port_str):
                raise ValueError(f"Invalid port number: {port_str}")
            port = int(port_str)
        elif ':' in address and not ConnectionManager._is_valid_ipv6(address):
            # IPv4 or hostname with port
            host, port_str = address.rsplit(':', 1)
            if port_str:
                if not ConnectionManager._is_valid_port(port_str):
                    raise ValueError(f"Invalid port number: {port_str}")
                port = int(port_str)

        # Validate host format
        if not (ConnectionManager._is_valid_ipv4(host) or
                ConnectionManager._is_valid_ipv6(host) or
                ConnectionManager._is_valid_domain(host) or
                host in ['localhost', '127.0.0.1', '::1']):
            raise ValueError(f"Invalid address format: {host}")

        # Add default port if needed
        if port is None:
            port_map = {'blender': 50051, 'colmap': 50052, 'alicevision': 50053}
            port = port_map.get(service_name, 50051)

        # Construct final address
        if ConnectionManager._is_valid_ipv6(host):
            final_address = f"[{host}]:{port}"
        else:
            final_address = f"{host}:{port}"

        print(f"Using TCP address: {final_address}")
        options = ConnectionManager.get_grpc_options(is_uds=False)
        return aio.insecure_channel(final_address, options=options)


class CompressionUtils:
    """Compression and decompression utilities"""

    @staticmethod
    def compress_if_needed(data: bytes, threshold: int = 1024,
                          preferred_codec: int = meshwork_pb2.CODEC_LZ4) -> Tuple[bytes, int]:
        """Compress data if above threshold"""
        if preferred_codec == meshwork_pb2.CODEC_LZ4 and len(data) >= threshold:
            return lz4.frame.compress(data), meshwork_pb2.CODEC_LZ4
        return data, meshwork_pb2.CODEC_NONE

    @staticmethod
    def decompress_if_needed(data: bytes, codec: int) -> bytes:
        """Decompress data based on codec"""
        if codec == meshwork_pb2.CODEC_LZ4:
            return lz4.frame.decompress(data)
        return data


class ChecksumUtils:
    """File checksum utilities"""

    @staticmethod
    def calculate_file_checksum(file_path: Path) -> str:
        """Calculate MD5 checksum of file"""
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def calculate_data_checksum(data: bytes) -> str:
        """Calculate MD5 checksum of data"""
        return hashlib.md5(data).hexdigest()


def get_workspace_path() -> Path:
    """Get workspace directory path"""
    workspace = Path("/workspace")
    workspace.mkdir(exist_ok=True)
    return workspace


def validate_workspace_path(workspace: Path, relative_path: str) -> bool:
    """Validate that a relative path resolves to within the workspace directory"""
    try:
        # Normalize the workspace path
        workspace_resolved = workspace.resolve()

        # Join and resolve the target path
        target_path = (workspace / relative_path).resolve()

        # Check if the resolved target path is within the workspace
        try:
            target_path.relative_to(workspace_resolved)
            return True
        except ValueError:
            # Path is outside workspace
            return False

    except (OSError, ValueError):
        # Invalid path or resolution failed
        return False


def setup_environment_detection():
    """Setup environment detection variables"""
    env_vars = {}

    # GPU detection
    try:
        import subprocess
        subprocess.run(['nvidia-smi'], capture_output=True, check=True)
        env_vars['GPU_AVAILABLE'] = 'true'
    except (subprocess.CalledProcessError, FileNotFoundError):
        env_vars['GPU_AVAILABLE'] = 'false'

    # Blender detection
    try:
        import bpy
        env_vars['BLENDER_ENV'] = 'true'
        env_vars['BLENDER_VERSION'] = bpy.app.version_string
    except ImportError:
        env_vars['BLENDER_ENV'] = 'false'

    return env_vars


def format_duration(seconds: float) -> str:
    """Format duration in human readable format"""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m{secs:.1f}s"


def format_bytes(byte_count: int) -> str:
    """Format byte count in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if byte_count < 1024:
            return f"{byte_count:.1f}{unit}"
        byte_count /= 1024
    return f"{byte_count:.1f}TB"