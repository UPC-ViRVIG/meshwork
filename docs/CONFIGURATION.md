# Configuration

Setup instructions for MeshWork: Python environment, Docker services, deployment scenarios, quality presets and the parameter reference for the point cloud pipeline.

## Python Environment

```bash
python -m venv venv
source venv/bin/activate    # Linux
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

Key dependencies: PySide6 and pyvistaqt (GUI), Open3D and PyMeshLab (point cloud and mesh processing), PyVista (visualization), grpcio / grpcio-tools (service communication), numpy, PyYAML.

The gRPC stubs (`server/meshwork_pb2.py`, `server/meshwork_pb2_grpc.py`) are generated automatically the first time the `server` package is imported if `grpcio-tools` is installed. `docker/build.sh` regenerates them as well.

## Docker Services

MeshWork uses three containerized services:

| Service | Container name | Host port | Tool | GPU |
|---------|----------------|-----------|------|-----|
| colmap | `colmap-service` | 50052 | COLMAP + OpenMVS | Optional (CPU fallback) |
| alicevision | `alicevision-service` | 50053 | AliceVision (Meshroom command line) | Required (CUDA) |
| blender | `blender-service` | 50051 | Blender headless | No |

All `docker compose` commands below are run from the `docker/` directory, where the compose files live.

### First build

```bash
cd docker
./build.sh              # CPU mode
GPU=true ./build.sh     # NVIDIA GPU mode (requires the NVIDIA Container Toolkit)
```

`build.sh` checks for `docker compose` and `grpcio-tools`, generates the gRPC stubs, recreates `../.runtime/{socks,logs,workspace}` (the shared workspace mounted into every container), copies `.env.example` to `.env` when no `.env` exists, and builds the images. Options: `--clean` (rebuild without cache), `--pull` (refresh base images first), and an optional subset of `blender colmap alicevision`. The first build takes 30-60 minutes depending on network speed and hardware.

### Starting and checking services

```bash
cd docker
docker compose up -d                                                    # CPU mode
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d    # GPU mode
docker compose ps                                                       # all services should report "healthy"
docker compose logs -f colmap-service
```

To run a subset of services (for example without AliceVision on a machine without an NVIDIA GPU):

```bash
docker compose up -d colmap-service blender-service
```

### docker/.env

Variables read by `build.sh` and the compose files (defaults are used when the file is absent):

| Variable | Default | Description |
|----------|---------|-------------|
| `GPU` | `false` | `true` selects the GPU compose overlay in `build.sh` |
| `MESHWORK_BIND_ADDR` | `127.0.0.1` | Interface the service ports are published on. Set to `0.0.0.0` only to accept connections from other machines, and read the warning below first |
| `BLENDER_GRPC_PORT` / `COLMAP_GRPC_PORT` / `ALICEVISION_GRPC_PORT` | `50051` / `50052` / `50053` | Host ports for TCP access |
| `CUDA_VERSION` | `11.8.0` | CUDA base image for `blender-service` |
| `COLMAP_TAG` | `latest` | `colmap/colmap` image tag |
| `ALICEVISION_TAG` | `3.2.0-ubuntu20.04-cuda11.3.1` | `alicevision/alicevision` image tag |
| `UDS_ONLY` | `false` | Services listen on Unix domain sockets only |

### GPU configuration

Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and verify it:

```bash
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

`docker-compose.gpu.yml` adds the device reservations (`deploy.resources.reservations.devices`) and sets `GPU_AVAILABLE=true` inside the containers.

## Client Configuration

The GUI loads settings in this order, later sources overriding earlier ones:

1. Defaults in `config.py`.
2. `~/.meshwork/config.yaml` (`Documents/Meshwork/config.yaml` on Windows), written on exit and editable by hand.
3. A `.env` file in the repository root (see `.env.example`).
4. Environment variables.

Values coming from `.env` or the environment apply to the running session only; they are never written back to `~/.meshwork/config.yaml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `MESHWORK_BLENDER` | `unix:.runtime/socks/blender.sock` | Blender service endpoint |
| `MESHWORK_COLMAP` | `unix:.runtime/socks/colmap.sock` | COLMAP service endpoint |
| `MESHWORK_ALICEVISION` | `unix:.runtime/socks/alicevision.sock` | AliceVision service endpoint |
| `MESHWORK_LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

Endpoints are either `<host>:<port>` or `unix:<socket path>`.

### Transport

The default is loopback TCP, which behaves the same on Linux, Windows and macOS and uses one code path for local and remote deployments. The containers publish their ports on `127.0.0.1` only, so the services are reachable from this machine and nowhere else.

The services also listen on Unix domain sockets in `.runtime/socks/` (Linux only, marginally lower overhead). To use them, point the endpoints at the socket paths:

```
MESHWORK_BLENDER=unix:.runtime/socks/blender.sock
MESHWORK_COLMAP=unix:.runtime/socks/colmap.sock
MESHWORK_ALICEVISION=unix:.runtime/socks/alicevision.sock
```

Relative socket paths are resolved against the working directory, so start the GUI from the repository root. The containers run as root and relax the socket permissions at startup so that the desktop user can connect; images built before this was added create sockets that only root can use, which shows up as `connect failed: Permission denied`.

**Do not publish the service ports on a public interface.** The services expose `Exec` and `PythonExec`, which run arbitrary commands and Python code inside the containers with the shared workspace mounted, and gRPC is unauthenticated here. Keep `MESHWORK_BIND_ADDR=127.0.0.1` unless the port is protected by other means, and reach a remote server over an SSH tunnel or a private network rather than by opening the port to the internet.

### Keepalive

Over TCP the client sends HTTP/2 keepalive pings every `comm.grpc.keepalive_time_ms` (30 s) so that a dead connection is detected during long operations. The services accept pings no more often than `comm.grpc.min_ping_interval_ms` (10 s) and do not count ping strikes, so stages that produce no output for minutes (exhaustive feature matching, dense reconstruction) are not terminated. If these two settings are changed, keep the server tolerance below the client period, otherwise gRPC aborts the call with `Too many pings`. Unix domain sockets use no keepalive at all. Changing the values requires rebuilding the service images (`cd docker && docker compose build`).

## Deployment Scenarios

### Local (single machine)

All services run on the same machine and are reached over loopback TCP. No configuration changes are needed.

### Remote GPU server

The GUI runs on a laptop; reconstruction services run on a remote GPU machine.

On the server:
```bash
git clone https://github.com/UPC-ViRVIG/meshwork.git
cd meshwork/docker
GPU=true ./build.sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

The server publishes its ports on `127.0.0.1` by default. The safe way to reach them from the client is an SSH tunnel:

```bash
ssh -N -L 50051:127.0.0.1:50051 -L 50052:127.0.0.1:50052 -L 50053:127.0.0.1:50053 user@server
```

The client then keeps the default `127.0.0.1` endpoints and needs no `.env` at all. To expose the ports directly instead, set `MESHWORK_BIND_ADDR=0.0.0.0` in `docker/.env` on the server, restrict access with a firewall, and create `.env` in the repository root on the client:

```
MESHWORK_BLENDER=<server-ip>:50051
MESHWORK_COLMAP=<server-ip>:50052
MESHWORK_ALICEVISION=<server-ip>:50053
```

Start the GUI with `python main.py`. Images and results are transferred over gRPC (chunked streaming), so network bandwidth affects upload and download times for large datasets.

## Quality Presets

The reconstruction dialog (Tools > 3D Reconstruction) offers the tools `COLMAP` (COLMAP + OpenMVS) and `AliceVision`, the quality presets `Fast`, `Balanced` (default) and `Quality`, and the outputs `Point Cloud` (dense point cloud) or `Dense Mesh` (textured mesh). Each preset maps to a parameter set per tool in `config.py` (`reconstruction` section); the COLMAP + OpenMVS mapping is:

| Preset | Max image size (SfM) | Max features / image | Dense resolution level | Densify iterations | Mesh refinement scales |
|--------|----------------------|----------------------|------------------------|--------------------|------------------------|
| Fast | 1600 px | 4096 | 4 (max 480 px) | 1 | 1 |
| Balanced | 1600 px | 8192 | 3 (max 1600 px) | 2 | 2 |
| Quality | 2048 px | 16384 | 2 (max 1600 px) | 3 | 2 |

Any value can be overridden per preset in `~/.meshwork/config.yaml` under `reconstruction.colmap.quality_levels` or `reconstruction.alicevision.quality_levels`. Processing time depends strongly on hardware; the timings reported in the paper are listed in [REPRODUCTION.md](REPRODUCTION.md).

## Point Cloud Processing Parameters

All distance thresholds are expressed relative to the bounding-box diagonal `D` of the cloud being processed, so the pipeline does not require a metric scale (photogrammetric reconstructions without ground control have an arbitrary scale).

### Plane detection (Analyze Plane)
- Gravity direction: mean of the camera up-vectors parsed from `images.txt` (COLMAP text model). When `images.txt` is absent (for example an imported point cloud from a laser scanner), the vertical axis of the scene as the object is currently oriented is used instead; orient the object upright with the Transform panel first.
- Radial profile: points are projected along gravity into 50 height layers; per layer the mean, mean square and 90th percentile of the radial distance from the axis and a count-weighted combination are computed, and the layers with the largest radial extent identify candidate background regions.
- Plane fit: RANSAC (`ransac_n` 3, 1000 iterations) on each candidate background subset with a distance threshold derived from `D/50` and the local layer statistics. Candidates whose normal deviates from gravity (|cos| < 0.7) are rejected; the best candidate maximizes the inlier ratio minus 0.1 times a height penalty. Two fallbacks (gravity normal at the profile height; gravity normal at the 2nd height percentile) keep the stage from failing.
- Margin: a recommended cut distance above the plane is derived from the candidate and can be edited before removal.
- Outputs: `1.stage1_params.yaml`, `1.radial_profile.csv`, `1.plane_candidates.csv`.

### Plane removal (Remove Plane)
- Points with signed distance to the plane below the margin are removed.
- Outlier removal: DBSCAN (eps = 0.02 D, minimum cluster size 0.05 % of the points, computed on a D/500 voxel downsample) or statistical (20 neighbours, 2.0 standard deviations).
- The result is written in a canonical frame (plane at z = 0, centroid at the origin) as `2.cleaned_m<margin>.ply` with `2.removal_m<margin>.yaml`.

### Registration (Align Clouds)
- Downsampling voxel v = D/200 (average of both clouds); normals from 30 neighbours within 2v.
- Global initialization: FPFH features (radius 5v) with RANSAC (distance 1.5v, 100000 iterations, confidence 0.999), compared against the identity with 10 point-to-plane ICP iterations each; the lower inlier RMSE is kept.
- Multi-scale point-to-plane ICP at voxel sizes v, 0.6v and 0.3v, at most 50 iterations per level, correspondence distance 2 voxels.
- Scale estimation: after every level the candidate factors 0.95, 0.97, 0.99, 1.0, 1.01, 1.03 and 1.05 are tested with 3 ICP iterations and the factor with the lowest RMSE is applied; the cumulative factor is clipped to [0.8, 1.5].
- These values live in `ALIGN_CONFIG` in `core/pointcloud.py`; `estimate_scale` switches the scale search off (used by `scripts/eval/ablation_scale.py`).
- Outputs: `3.alignment_params.yaml` (fitness, inlier RMSE, initialization, per-level records, cumulative scale, resulting transform).

### Merge and cleaning (Merge Clouds)
- Both clouds are transformed into the target frame and concatenated; duplicates are removed with a D/1000 voxel, the result is downsampled with a D/800 voxel.
- Optional filters: DBSCAN outlier removal, statistical outlier removal (20 neighbours, 2.0 standard deviations), normal consistency (30 neighbours, 20 degrees), radius outlier removal (16 neighbours within 5 downsampling voxels).
- Outputs: `4.merged_<filters>.ply`, `4.merged_<filters>_params.yml`, `4.merged_<filters>_meta.yml`.

### Poisson reconstruction (Generate Mesh)
- Screened Poisson reconstruction with octree depth 9 by default (adjustable in the panel), scale 1.1; vertices in the lowest 1 % of the density distribution are pruned.
- Optional hole filling (PyMeshLab, maximum hole size in edges) and Laplacian smoothing.
- The mesh carries vertex colours interpolated from the point cloud; photo textures are only available on meshes produced directly by the reconstruction services (`Dense Mesh` output).
- Outputs: `5.mesh_d<depth>.ply`, `5.meshing_d<depth>.yml`.

### Stage metrics
Every stage above appends one JSON line to `stage_metrics.jsonl` in the object's source directory with the stage name, elapsed wall-clock time and its key metrics. `python scripts/eval/collect_metrics.py <folder>` renders these files as a table.

## Outputs of the reconstruction services

For the COLMAP + OpenMVS path the output folder contains `dense_points.ply`, `cameras.txt`, `images.txt` (COLMAP text model), `reconstruction.json` (image count, sparse point count, timings) and, for `Dense Mesh`, the textured OpenMVS mesh (`.obj`, `.mtl`, `.jpg`). The AliceVision path writes `sparse_points.abc`, the dense cloud, the textured mesh and `reconstruction.json`. Console output of every service run is streamed into the reconstruction dialog and into `~/.meshwork/logs/app.log`.

## Logging and UI latency

- Application log: `~/.meshwork/logs/app.log` (rotating, level from `logging.level` or `MESHWORK_LOG_LEVEL`).
- UI responsiveness: the main thread samples the delay of a 100 ms timer and writes p50 / p95 / p99 / max event-loop latency every 30 s to `~/.meshwork/logs/ui_latency.csv`. Configure or disable it under `gui.latency_monitor` (`enabled`, `interval_ms`, `report_interval_s`) in `~/.meshwork/config.yaml`.

## Platform Notes

### Linux (Ubuntu 22.04+, Mint 22)
- Fully supported, recommended platform.
- Unix domain sockets are used for local deployment.

### Windows 10+
- Supported via Docker Desktop with the WSL2 backend.
- Use TCP endpoints (`MESHWORK_COLMAP=127.0.0.1:50052` etc. in the repository `.env`); named pipes replace Unix domain sockets for the local Blender connection.
- Configuration and logs are stored under `Documents/Meshwork/`.

### macOS
- Not officially supported (no Docker GPU passthrough). The COLMAP + OpenMVS path can run CPU-only through Docker Desktop with TCP endpoints, but this configuration is untested.
