# Configuration

## Python Environment

```bash
python -m venv venv
source venv/bin/activate    # Linux
# venv\Scripts\activate     # Windows

pip install -r requirements.txt
```

Missing gRPC stubs (`server/meshwork_pb2.py`, `server/meshwork_pb2_grpc.py`) are generated on import using `grpcio-tools`. `docker/build.sh` also regenerates them.

## Docker Services

| Service | Container name | Host port | Tool | GPU |
|---------|----------------|-----------|------|-----|
| colmap | `colmap-service` | 50052 | COLMAP + OpenMVS | Optional (CPU fallback) |
| alicevision | `alicevision-service` | 50053 | AliceVision (Meshroom command line) | Required (CUDA) |
| blender | `blender-service` | 50051 | Blender headless | No |

Build and service commands run from `docker/`, where the compose files live.

### First build

Start from the repository root:

```bash
cd docker
test -f .env || cp .env.example .env
# For NVIDIA GPU mode, set GPU=true in .env before building.
./build.sh
```

`build.sh` requires Docker Compose and `grpcio-tools`. Options: `--clean` (remove existing service images before building), `--pull` (refresh base images), and a subset of `blender colmap alicevision`. GPU mode also requires the NVIDIA Container Toolkit.

**Each build stops the services and deletes `../.runtime/`, including its shared workspace and logs.** Save any files you need before rebuilding.

### Starting and checking services

Still in `docker/`, choose one startup command.

CPU (COLMAP + OpenMVS and Blender):

```bash
docker compose up -d colmap-service blender-service
```

NVIDIA GPU (all services, including AliceVision):

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Check the running services:

```bash
docker compose ps    # started services should report "healthy"
docker compose logs -f colmap-service
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

Install and configure the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), then run its [sample workload](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/sample-workload.html):

```bash
docker run --rm --runtime=nvidia --gpus all ubuntu nvidia-smi
```

`docker-compose.gpu.yml` adds the device reservations (`deploy.resources.reservations.devices`) and sets `GPU_AVAILABLE=true` inside the containers.

## Client Configuration

The GUI loads settings in this order, later sources overriding earlier ones:

1. Defaults in `config.py`.
2. `~/.meshwork/config.yaml`, written on exit and editable by hand.
3. A `.env` file in the repository root (see `.env.example`).
4. Environment variables.

Environment overrides apply to the session and are not saved to `config.yaml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `MESHWORK_BLENDER` | `127.0.0.1:50051` | Blender service endpoint |
| `MESHWORK_COLMAP` | `127.0.0.1:50052` | COLMAP service endpoint |
| `MESHWORK_ALICEVISION` | `127.0.0.1:50053` | AliceVision service endpoint |
| `MESHWORK_LOG_LEVEL` | `INFO` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |

Endpoints are either `<host>:<port>` or `unix:<socket path>`.

### Transport

The default is loopback TCP: the containers publish their ports on `127.0.0.1`, accessible from the local machine.

On Linux, Unix domain sockets are an alternative. Set these endpoints in the repository `.env`:

```
MESHWORK_BLENDER=unix:.runtime/socks/blender.sock
MESHWORK_COLMAP=unix:.runtime/socks/colmap.sock
MESHWORK_ALICEVISION=unix:.runtime/socks/alicevision.sock
```

Relative socket paths are resolved against the working directory; start the GUI from the repository root.

**Do not expose service ports to the internet.** gRPC is unauthenticated, and `Exec` / `PythonExec` can run arbitrary code in containers with the shared workspace mounted. Keep `MESHWORK_BIND_ADDR=127.0.0.1` and use an SSH tunnel for remote access, or restrict direct connections with a firewall.

## Deployment Scenarios

### Remote GPU server

On the server:
```bash
git clone https://github.com/UPC-ViRVIG/meshwork.git
cd meshwork/docker
test -f .env || cp .env.example .env
# Set GPU=true in .env.
./build.sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

On the client, forward the server ports through SSH:

```bash
ssh -N -L 50051:127.0.0.1:50051 -L 50052:127.0.0.1:50052 -L 50053:127.0.0.1:50053 user@server
```

Keep the default client endpoints when using the tunnel. For direct access, set `MESHWORK_BIND_ADDR=0.0.0.0` in the server's `docker/.env`, restrict access with a firewall, and set the client's repository `.env`:

```
MESHWORK_BLENDER=<server-ip>:50051
MESHWORK_COLMAP=<server-ip>:50052
MESHWORK_ALICEVISION=<server-ip>:50053
```

Start the GUI from the repository root with `python main.py`. Images and results are transferred over gRPC.

## Quality Presets

In **Tools > 3D Reconstruction**, choose `COLMAP` (COLMAP + OpenMVS) or `AliceVision`, a quality preset (`Fast`, `Balanced` or `Quality`), and an output (`Point Cloud` or textured `Dense Mesh`). `Balanced` is the default. Presets are defined under `reconstruction` in `config.py`; COLMAP + OpenMVS uses:

| Preset | Max image size (SfM) | Max features / image | Dense resolution level | Densify iterations | Mesh refinement scales |
|--------|----------------------|----------------------|------------------------|--------------------|------------------------|
| Fast | 1600 px | 4096 | 4 (max 480 px) | 1 | 1 |
| Balanced | 1600 px | 8192 | 3 (max 1600 px) | 2 | 2 |
| Quality | 2048 px | 16384 | 2 (max 1600 px) | 3 | 2 |

Override preset values in `~/.meshwork/config.yaml` under `reconstruction.colmap.quality_levels` or `reconstruction.alicevision.quality_levels`.

## Point Cloud Processing Parameters

The main distance thresholds use the cloud's bounding-box diagonal `D`. Plane detection also uses fixed safety bounds in scene units, listed below. Models without ground control have no metric scale.

Output names below are patterns: `<...>` denotes a parameter value or filter selection. Repeated runs can add a numeric suffix to avoid overwriting existing results.

### Plane detection (Analyze Plane)

`Analyze Plane` and `Remove Plane` read `dense_points.ply` from the selected object's source directory. For an external cloud, put a PLY copy with this name in its own directory and import that copy. Keep matching `images.txt` alongside it if camera poses are available.

- Gravity: negated, normalized mean of the camera up-vectors in `images.txt` (COLMAP text model). This assumes upright photographs after EXIF orientation. Without camera poses, gravity follows the scene vertical axis; orient the object upright in the Transform panel first.
- Radial profiles: 50 height layers along gravity; each records the mean, mean square and 90th percentile of radial distance, plus the mean multiplied by `log(1 + point count)`. Profile changes identify candidate support regions.
- Plane fit: candidate regions span the centres of their outermost selected layers. RANSAC (`ransac_n` 3, 1000 iterations) fits subsets of at least 500 points. The threshold is one quarter of the distance between the region boundaries, clipped to `[0.001, D/50]`; for zero thickness it is `D/50`. Candidates with |cos(normal, gravity)| < 0.7 are rejected; the score is inlier ratio minus 0.1 times a height penalty. If no candidate passes, gravity-aligned fallbacks use the profile boundary or the 2nd height percentile.
- Margin: 99th percentile of candidate-point signed distances above the plane, plus half a height layer, clipped to `[0.005, 0.5]` scene units. The two fallbacks use bounds `[0.01, 0.4]` and `[0.02, 0.4]`. Inspect and adjust the margin before removal.
- Outputs: `1.stage1_params.yaml`, `1.radial_profile.csv`, `1.radial_profile_candidates_raw.csv`, `1.plane_candidates.csv`.

### Plane removal (Remove Plane)

- Points with signed distance to the plane below the margin are removed.
- Outlier removal: DBSCAN (eps = 0.02 D, minimum cluster size 0.05 % of the points, computed on a D/500 voxel downsample) or statistical (20 neighbours, 2.0 standard deviations).
- The result is centered at its centroid with the support normal along z, and written as `2.cleaned_m<margin>.ply` with `2.removal_m<margin>.yaml`.

### Registration (Align Clouds)

- Voxel size v = D/200, using the average diagonal of both clouds; each voxel is represented by its point centroid. Normals use 30 neighbours within 2v.
- Global initialization: FPFH features (radius 5v) with RANSAC (distance 1.5v, 100000 iterations, confidence 0.999), compared against the identity with 10 point-to-plane ICP iterations each; the starting transform whose trial has the lower inlier RMSE is used.
- Multi-scale point-to-plane ICP at voxel sizes v, 0.6v and 0.3v, at most 50 iterations per level, correspondence distance 2 voxels.
- Scale estimation: after every level the candidate factors 0.95, 0.97, 0.99, 1.0, 1.01, 1.03 and 1.05 are tested with 3 ICP iterations each. The factor with the lowest trial RMSE is applied only if it improves on the pre-search RMSE; the trial rigid transforms are discarded. The cumulative factor is clipped to [0.8, 1.5].
- ICP levels and scale-search settings live in `ALIGN_CONFIG` in `core/pointcloud.py`; setting `estimate_scale` to `False` disables the scale search (used by `scripts/eval/ablation_scale.py`).
- Final fitness and inlier RMSE evaluate the actual returned transform on the last ICP level's samples, using the same correspondence threshold in target-local coordinates. Per-level fitness and inlier RMSE describe ICP before scale search; `rmse_after_scale` is the best pre-search or trial ICP value, not the final output's RMSE.
- Outputs: `3.alignment_params.yaml` (fitness, inlier RMSE, initialization, per-level records, cumulative scale, resulting transform).

### Merge and cleaning (Merge Clouds)

- Both clouds are transformed into world coordinates and concatenated; duplicates are removed with a D/1000 voxel, the result is downsampled with a D/800 voxel.
- Optional filters: DBSCAN outlier removal, statistical outlier removal (20 neighbours, 2.0 standard deviations), normal consistency (30 neighbours, 20 degrees), radius outlier removal (16 neighbours within 5 downsampling voxels).
- Outputs: `4.merged_<filters>.ply`, `4.merged_<filters>_params.yml`, `4.merged_<filters>_meta.yml`.

### Poisson reconstruction (Generate Mesh)

- Screened Poisson reconstruction with octree depth 9 by default (adjustable in the panel), scale 1.1; vertices in the lowest 1 % of the density distribution are pruned.
- Optional hole filling (PyMeshLab, maximum hole size in edges) and Laplacian smoothing.
- The mesh carries vertex colours interpolated from the point cloud; photo textures are only available on meshes produced directly by the reconstruction services (`Dense Mesh` output).
- Outputs: `5.mesh_d<depth>.ply` and `5.meshing_d<depth>.yml`; simplification adds `_s<target>` before the extension.

### Stage metrics

Each stage appends a JSON line to `stage_metrics.jsonl` in the object's source directory: stage name, elapsed wall-clock time and key metrics. See [Metrics](REPRODUCTION.md#metrics) for collection commands.

## Outputs of the reconstruction services

Images are copied to `<project folder>/converted/` before upload, with EXIF orientation applied. Reconstruction results are written to `<project folder>/recon_<timestamp>/result/`:

- **COLMAP + OpenMVS:** `dense_points.ply`, `cameras.txt`, `images.txt` (COLMAP text model), and `reconstruction.json` (image count, sparse point count, engine settings). `Dense Mesh` also produces the textured OpenMVS mesh (`.obj`, `.mtl`, `.jpg`).
- **AliceVision:** `sparse_points.abc`, the dense cloud and `reconstruction.json`. `Dense Mesh` also produces the textured mesh.

Console output is streamed into the reconstruction dialog and the application log.

## Import and export

Meshes support `.obj`, `.ply` and `.stl`; point clouds support `.ply` and vertex-only `.obj`. Processing stages use `.ply`. To export, select the objects in the Scene panel first.

## Logging and UI latency

- Application log: `~/.meshwork/logs/app.log` (rotating, level from `logging.level` or `MESHWORK_LOG_LEVEL`).
- UI responsiveness: the main thread samples the delay of a 100 ms timer and writes p50 / p95 / p99 / max event-loop latency every 30 s to `~/.meshwork/logs/ui_latency.csv`. Configure or disable it under `gui.latency_monitor` (`enabled`, `interval_ms`, `report_interval_s`) in `~/.meshwork/config.yaml`.

## Platform Notes

### Linux (Ubuntu 22.04+, Mint 22)

- Tested platform.

### Windows 10+

- Supported via Docker Desktop with the WSL2 backend.
- Use the default loopback TCP endpoints.
- Logs and temporary files are stored under `Documents/Meshwork/`; configuration remains in `~/.meshwork/config.yaml`.

### macOS

- Not officially supported (no Docker GPU passthrough). The COLMAP + OpenMVS path can run CPU-only through Docker Desktop with TCP endpoints, but this configuration is untested.

## Keepalive

Client TCP keepalive settings are under `comm.grpc` in `~/.meshwork/config.yaml`: `keepalive_time_ms` defaults to 30 s and `min_ping_interval_ms` to 10 s. Unix-socket clients omit keepalive options.

The service images do not include the client configuration. They use the defaults in `server/utils.py` (also 30 s and 10 s); changing those defaults requires rebuilding the images and recreating the containers. If customizing keepalive, keep the server's minimum ping interval below the client's ping period.
