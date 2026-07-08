# Configuration

Detailed setup instructions for MeshWork, including Docker service configuration, deployment scenarios, and parameter reference.

## Python Environment

```bash
# Recommended: use a virtual environment
python -m venv venv
source venv/bin/activate    # Linux
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

Key Python dependencies:
- PySide6 (Qt GUI framework)
- Open3D (point cloud processing)
- PyVista (3D visualization)
- grpcio, grpcio-tools (gRPC communication)
- numpy, scipy

## Docker Services

MeshWork uses three containerized services for reconstruction tools:

| Service | Port | Tool | GPU Required |
|---------|------|------|-------------|
| colmap | 50052 | COLMAP + OpenMVS | Optional (CPU fallback available) |
| alicevision | 50053 | AliceVision (Meshroom) | Yes (CUDA) |
| blender | 50051 | Blender 3.x headless | No |

### Starting Services

```bash
# Start all services
docker compose up -d

# Check health status
docker compose ps

# View logs
docker compose logs -f colmap
```

### Building Images

Pre-built images are provided. To rebuild from source:

```bash
docker compose build
```

Build times depend on network speed and hardware (30–60 min for first build due to CUDA toolkit and tool compilation).

### GPU Configuration

For NVIDIA GPU support, install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), then verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

GPU allocation is configured in `docker-compose.yml` under `deploy.resources.reservations`:

```yaml
services:
  alicevision:
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
              count: 1
```

To run without GPU, use the COLMAP + OpenMVS pipeline (CPU mode) and disable the AliceVision service:

```bash
docker compose up -d colmap blender
```

## Deployment Scenarios

### Local Development (Single Machine)

All services run on the same machine. Communication uses Unix domain sockets for low latency.

```
docker-compose.yml  →  default configuration, no changes needed
```

### Remote GPU Server

The GUI runs on a local laptop; reconstruction services run on a remote GPU machine.

On the remote server:
```bash
git clone https://github.com/wcjwing/meshwork.git
cd meshwork
docker compose up -d
```

On the local machine, set the service endpoints:

```bash
export MESHWORK_COLMAP_HOST=<server-ip>:50052
export MESHWORK_ALICEVISION_HOST=<server-ip>:50053
export MESHWORK_BLENDER_HOST=<server-ip>:50051

python -m meshwork
```

Note: remote deployment uses TCP sockets instead of Unix domain sockets. File transfer occurs over gRPC (chunked streaming), so network bandwidth affects upload/download speed for large datasets.

## Quality Presets

The preset system maps user-facing quality levels to tool-specific parameters:

| Preset | Image Resolution | Approx. Processing Time | Use Case |
|--------|-----------------|------------------------|----------|
| Low | 1024 px | 5–10 min | Quick preview, parameter testing |
| Medium | 2048 px | 15–30 min | General use, good quality |
| High | 4096 px | 45–90 min | Publication-quality output |

Times are approximate for ~50–80 images on a 14-core CPU with 16 GB RAM.

Expert users can override any parameter through the advanced settings panel in the reconstruction dialog.

## Point Cloud Processing Parameters

Default parameters for the automated processing pipeline:

### Plane Detection (RANSAC)
- Distance threshold: adaptive (bounding box diagonal / 50)
- Iterations: 1000
- Gravity estimation: automatic from camera poses

### Multi-scale ICP Registration
- Voxel resolutions: 5 cm → 2 cm → 1 cm
- Max iterations per level: 50
- Scale estimation range: 0.95–1.05
- Initialization: automatic selection (RANSAC features vs identity)

### Outlier Filtering
- Statistical: neighbors = 20, std_ratio = 2.0
- DBSCAN: eps = adaptive, min_points = 10
- Normal consistency: angle threshold = 30°

### Poisson Reconstruction
- Octree depth: 9 (Medium), 10 (High)
- Density-based pruning: enabled
- Manifold output: enabled

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MESHWORK_COLMAP_HOST` | `localhost:50052` | COLMAP service endpoint |
| `MESHWORK_ALICEVISION_HOST` | `localhost:50053` | AliceVision service endpoint |
| `MESHWORK_BLENDER_HOST` | `localhost:50051` | Blender service endpoint |
| `MESHWORK_WORKSPACE` | `./workspace` | Shared workspace directory |
| `MESHWORK_LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

## Platform Notes

### Linux (Ubuntu 22.04+, Mint 22)
- Fully supported, recommended platform
- Unix domain sockets used for local deployment

### Windows 10+
- Supported via Docker Desktop with WSL2 backend
- Named pipes replace Unix domain sockets
- Some path handling differences are managed automatically

### macOS
- Not officially supported (Docker GPU passthrough unavailable)
- CPU-only mode may work via Docker Desktop but is untested