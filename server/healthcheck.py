#!/usr/bin/env python3
# server/healthcheck.py
import os
import sys
import grpc
from pathlib import Path

# Import generated protobuf code
try:
    import meshwork_pb2
    import meshwork_pb2_grpc
    from utils import ConnectionManager
except ImportError:
    print("ERROR: protobuf modules not found")
    sys.exit(1)

def check_service_health(service_name, port):
    """Check service health status"""
    uds_only = os.environ.get('UDS_ONLY', 'false').lower() in ('true', '1', 'yes')

    # Determine connection method
    if uds_only:
        # UDS only mode - check Unix socket
        socket_path = f"/socks/{service_name}.sock"
        if not Path(socket_path).exists():
            print(f"ERROR: Socket not found: {socket_path}")
            return False
        address = f'unix:{socket_path}'
        options = ConnectionManager.get_grpc_options(is_uds=True)
    else:
        # Production mode - check TCP connection directly
        address = f'localhost:{port}'
        options = ConnectionManager.get_grpc_options(is_uds=False)

    try:
        # Create gRPC connection
        channel = grpc.insecure_channel(address, options=options)
        stub = meshwork_pb2_grpc.MeshWorkStub(channel)

        # Send ping request
        request = meshwork_pb2.PingRequest(message='health_check')
        response = stub.Ping(request, timeout=5.0)

        # Verify response
        if response.message and 'pong' in response.message.lower():
            print(f"OK: {service_name} service healthy via {address}")
            channel.close()
            return True
        else:
            print(f"ERROR: Invalid ping response from {service_name}")
            channel.close()
            return False

    except grpc.RpcError as e:
        print(f"ERROR: gRPC error - {e.code()}: {e.details()}")
        return False
    except Exception as e:
        print(f"ERROR: Connection failed - {str(e)}")
        return False

if __name__ == "__main__":
    service_name = os.environ.get('SERVICE_NAME', 'unknown')
    service_port = int(os.environ.get('SERVICE_PORT', '50051'))

    if service_name == 'unknown':
        print("ERROR: SERVICE_NAME environment variable not set")
        sys.exit(1)

    success = check_service_health(service_name, service_port)
    sys.exit(0 if success else 1)