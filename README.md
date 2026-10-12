# MeshWork

MeshWork is a Python desktop application for reconstructing objects from photographs and processing the resulting point clouds and meshes. It focuses on close-range objects, such as archaeological finds photographed on a table or plinth, where reconstructions often include the supporting surface and may cover only part of the object.

Users inspect intermediate results, adjust parameters such as the support-removal margin, and choose when to align, merge or mesh their scans.

## Features

- **Reconstruction**: point clouds or textured meshes using COLMAP + OpenMVS or AliceVision
- **Point cloud processing**: supporting-plane removal, scan alignment with scale estimation, outlier filtering and Poisson meshing
- **Quality presets**: Fast / Balanced / Quality
- **3D viewer**: inspect, position and export objects in a PyVista viewport

## Requirements

- Python 3.10+
- Docker Engine (with Docker Compose)
- NVIDIA GPU + CUDA drivers (optional, required for AliceVision; COLMAP can run CPU-only)
- OS: Windows 10+ or Linux (Ubuntu 22.04+ tested)

## Quick Start

These Bash commands start COLMAP + OpenMVS and Blender in CPU mode on Linux. For GPU setup or other platforms, see [Configuration](docs/CONFIGURATION.md).

```bash
# 1. Clone the repository
git clone https://github.com/UPC-ViRVIG/meshwork.git
cd meshwork

# 2. Create a Python environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Build and start the required services
cd docker
./build.sh colmap blender
docker compose up -d colmap-service blender-service
docker compose ps       # wait until both services report "healthy"
cd ..

# 4. Launch the GUI
python main.py
```

For later sessions, run `docker compose up -d colmap-service blender-service` from `docker/`, then launch the GUI from the repository root with the Python environment active. The default client endpoints connect to the local containers without additional configuration.

Rebuilding with `build.sh` stops existing services and recreates `.runtime/`, deleting its shared workspace and logs. Save any files you need before rebuilding.

## Documentation

- [REPRODUCTION.md](docs/REPRODUCTION.md) — Reproducing paper results
- [DATASETS.md](docs/DATASETS.md) — Dataset sources, licenses, and download links
- [CONFIGURATION.md](docs/CONFIGURATION.md) — Docker setup, deployment options, parameter reference
- [scripts/eval/README.md](scripts/eval/README.md) — Evaluation scripts (plane-detection and scale ablations, reference comparison, metrics tables)

## Architecture

The Qt/PyVista GUI runs on the main thread and communicates with a processing worker through signals. Reconstruction and Blender operations use gRPC services in Docker containers.

```
┌──────────────┐    Signals   ┌─────────────────┐    gRPC     ┌──────────────────┐    Invoke   ┌──────────────┐
│ Presentation │◄────────────►│  Business Logic │◄───────────►│ Infrastructure   │◄───────────►│External Tools│
│  Qt/PySide6  │   UI updates │  Scene mgmt,    │  Streaming  │ Docker containers│   Output    │ COLMAP,      │
│  PyVista     │              │  Open3D algos   │             │ gRPC services    │             │ AliceVision, │
│  Dialogs     │              │  Orchestration  │             │ Format convert   │             │ OpenMVS,     │
└──────────────┘              └─────────────────┘             └──────────────────┘             │ Blender      │
  Main thread                  Worker thread                   Async I/O                       └──────────────┘
```

## Project Structure

```
meshwork/
├── main.py                # GUI entry point
├── config.py              # Defaults, ~/.meshwork/config.yaml, .env and MESHWORK_* overrides
├── core/                  # Business logic (worker thread)
│   ├── pointcloud.py      #   plane detection, registration, merging, Poisson meshing, stage metrics
│   ├── recon.py           #   reconstruction orchestration and quality presets
│   └── scene.py, project.py, signal_router.py, worker_thread.py
├── gui/                   # Qt/PySide6 presentation layer (main thread)
│   └── main.py, menu.py, view.py, render.py, panel_tools.py, win_recon.py, latency_monitor.py
├── server/                # gRPC service code shared by the containers and the client
│   └── meshwork.proto, main.py, client_api.py, recon_colmap.sh, recon_alicevision.sh
├── docker/                # Dockerfiles, docker-compose.yml, docker-compose.gpu.yml, build.sh, .env.example
├── scripts/eval/          # Reproducible evaluation scripts
├── docs/                  # CONFIGURATION.md, DATASETS.md, REPRODUCTION.md
├── requirements.txt
├── CITATION.cff
└── README.md
```

## Citation

If you use MeshWork in your research, please cite:

```bibtex
@article{wang2026meshwork,
  title     = {MeshWork: A Python Framework for Assisted Geometry Processing
               in 3D Reconstruction Workflows},
  author    = {Wang, Chunjie and Andujar, Carlos and Chica, Antonio},
  journal   = {SoftwareX},
  year      = {2026},
  note      = {Manuscript submitted}
}
```

## License

MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgements

Developed within the [ViRVIG](https://www.virvig.eu/) group at Universitat Politècnica de Catalunya, Barcelona.

The examples use datasets from British Museum Digital Humanities, Natowi and MicroPasts. Sources, licenses and full attribution are listed in [DATASETS.md](docs/DATASETS.md).
