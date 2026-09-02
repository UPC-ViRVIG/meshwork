#!/bin/bash
# docker/build.sh

set -e

show_help() {
    cat << EOF
Usage: $0 [OPTIONS] [SERVICES]

Build MeshWork services

OPTIONS:
    --clean              Clean build (remove existing images)
    --pull               Pull latest base images first
    --help               Show this help

SERVICES (optional, default: all):
    blender              Blender service
    colmap               COLMAP service
    alicevision          AliceVision service

EXAMPLES:
    $0                   Build all services (CPU mode)
    $0 --clean           Clean build all services
    $0 --pull            Pull latest and build all

    Set GPU=true in .env to enable GPU mode.

RUNTIME:
    docker compose up -d
    docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

EOF
}

CLEAN=false
PULL=false
SERVICES=()

if docker compose version > /dev/null 2>&1; then
    DC="docker compose"
elif docker-compose version > /dev/null 2>&1; then
    DC="docker-compose"
else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found"
    exit 1
fi

if [ -f ".env" ]; then
    set -o allexport
    source .env
    set +o allexport
elif [ -f ".env.example" ]; then
    set -o allexport
    source .env.example
    set +o allexport
fi

GPU="${GPU:-false}"

if [ "$GPU" = "true" ]; then
    DC_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
else
    DC_FILES="-f docker-compose.yml"
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --pull)
            PULL=true
            shift
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        blender|colmap|alicevision)
            SERVICES+=("$1")
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

if [ ${#SERVICES[@]} -eq 0 ]; then
    SERVICES=("blender" "colmap" "alicevision")
fi

export CUDA_VERSION="${CUDA_VERSION:-11.8.0}"
export COLMAP_TAG="${COLMAP_TAG:-latest}"
export ALICEVISION_TAG="${ALICEVISION_TAG:-3.2.0-ubuntu20.04-cuda11.3.1}"

echo "Building MeshWork Services"
echo "=========================="
echo "Services to build: ${SERVICES[*]}"
echo "Using: $DC"
echo "GPU mode: $GPU"
echo ""

if ! python -c "import grpc_tools" 2>/dev/null; then
    echo "ERROR: grpcio-tools not found in current Python environment"
    echo "Please install it: pip install grpcio-tools"
    exit 1
fi

echo "Stopping running containers..."
$DC $DC_FILES down 2>/dev/null || true
sleep 1

echo "Generating protobuf code..."
cd ../server
rm -f meshwork_pb2.py meshwork_pb2_grpc.py

python -m grpc_tools.protoc \
    --proto_path=. \
    --python_out=. \
    --grpc_python_out=. \
    meshwork.proto

if [ ! -f "meshwork_pb2.py" ] || [ ! -f "meshwork_pb2_grpc.py" ]; then
    echo "ERROR: Failed to generate protobuf files"
    exit 1
fi
echo "Generated: meshwork_pb2.py, meshwork_pb2_grpc.py"

cd ../docker

echo ""
echo "Creating runtime directories..."
rm -rf ../.runtime 2>/dev/null || sudo rm -rf ../.runtime
mkdir -p ../.runtime/{socks,logs,workspace}
chmod 755 ../.runtime/{socks,logs,workspace}

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
fi

if [ "$PULL" = true ]; then
    echo ""
    echo "Pulling base images..."

    if [[ " ${SERVICES[*]} " =~ " blender " ]]; then
        docker pull nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04 || echo "Warning: Failed to pull CUDA image"
    fi

    if [[ " ${SERVICES[*]} " =~ " colmap " ]]; then
        docker pull colmap/colmap:${COLMAP_TAG} || echo "Warning: Failed to pull COLMAP image"
    fi

    if [[ " ${SERVICES[*]} " =~ " alicevision " ]]; then
        docker pull alicevision/alicevision:${ALICEVISION_TAG} || echo "Warning: Failed to pull AliceVision image"
    fi

    echo ""
fi

if [ "$CLEAN" = true ]; then
    echo "Cleaning existing images..."
    for service in "${SERVICES[@]}"; do
        case $service in
            blender)
                docker rmi blender-service:latest 2>/dev/null || true
                ;;
            colmap)
                docker rmi colmap-service:latest 2>/dev/null || true
                ;;
            alicevision)
                docker rmi alicevision-service:latest 2>/dev/null || true
                ;;
        esac
    done
    echo ""
fi

echo "Building services..."
build_start_time=$(date +%s)

for service in "${SERVICES[@]}"; do
    echo "Building $service service..."
    service_start_time=$(date +%s)

    case $service in
        blender)
            $DC $DC_FILES build blender-service
            ;;
        colmap)
            $DC $DC_FILES build colmap-service
            ;;
        alicevision)
            $DC $DC_FILES build alicevision-service
            ;;
    esac

    service_end_time=$(date +%s)
    service_duration=$((service_end_time - service_start_time))
    echo "$service build completed in ${service_duration}s"
    echo ""
done

build_end_time=$(date +%s)
total_duration=$((build_end_time - build_start_time))

echo "================================================================"
echo "Build Summary"
echo "================================================================"
echo "Services built: ${SERVICES[*]}"
echo "GPU mode: $GPU"
echo "Total build time: ${total_duration}s"
echo ""
if [ "$GPU" = "true" ]; then
    echo "To start: $DC -f docker-compose.yml -f docker-compose.gpu.yml up -d"
else
    echo "To start: $DC up -d"
fi