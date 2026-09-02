# MeshWork

A Python framework for assisted geometry processing in 3D reconstruction workflows.

MeshWork integrates heterogeneous photogrammetry and mesh-processing tools (COLMAP, AliceVision, OpenMVS, Blender) into a unified, semi-automated pipeline with an interactive GUI. It is designed for cultural heritage digitization, architectural documentation, and digital content creation.

## Features

- **End-to-end reconstruction**: from unordered photographs to textured meshes
- **Two reconstruction paths**: COLMAP + OpenMVS (CPU/GPU flexible) or AliceVision (GPU-optimized)
- **Assisted point cloud processing**: gravity-guided supporting-plane detection, multi-scale ICP registration with scale estimation, multi-strategy outlier filtering, Poisson surface reconstruction
- **Quality presets**: Fast / Balanced / Quality one-click presets; every underlying parameter can be overridden in `~/.meshwork/config.yaml`
- **Interactive 3D visualization**: PyVista-based viewport with real-time manipulation
- **Containerized deployment**: Docker isolates all tool dependencies; one build script prepares and starts every service

## Architecture

```
┌──────────────┐    Signals   ┌─────────────────┐    gRPC     ┌──────────────────┐    Invoke   ┌──────────────┐
│ Presentation │◄────────────►│  Business Logic │◄───────────►│ Infrastructure   │◄───────────►│External Tools│
│  Qt/PySide6  │   UI updates │  Scene mgmt,    │  Streaming  │ Docker containers│   Output    │ COLMAP,      │
│  PyVista     │              │  Open3D algos   │             │ gRPC services    │             │ AliceVision, │
│  Dialogs     │              │  Orchestration  │             │ Format convert   │             │ OpenMVS,     │
└──────────────┘              └─────────────────┘             └──────────────────┘             │ Blender      │
  Main thread                  Worker thread                   Async I/O                       └──────────────┘
```

An event-driven signal router provides thread-safe communication between the UI main thread and the business logic worker thread, maintaining interface responsiveness during long-running reconstruction operations.

## Requirements

- Python 3.10+
- Docker Engine (with Docker Compose)
- NVIDIA GPU + CUDA drivers (optional, required for AliceVision; COLMAP can run CPU-only)
- OS: Windows 10+ or Linux (Ubuntu 22.04+ tested)

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/UPC-ViRVIG/meshwork.git
cd meshwork

# 2. Install Python dependencies (a virtual environment is recommended)
pip install -r requirements.txt

# 3. Build and start the containerized services (first build: 30-60 min)
cd docker
./build.sh              # CPU mode; use  GPU=true ./build.sh  for NVIDIA GPU support
docker compose up -d    # GPU mode: docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
docker compose ps       # wait until all three services report "healthy"
cd ..

# 4. Launch the GUI
python main.py
```

`build.sh` generates the gRPC stubs, creates the shared `.runtime/` workspace, copies
`docker/.env.example` to `docker/.env` if needed and builds the three images. After the
first build, step 3 reduces to `docker compose up -d` inside `docker/`. The containers
publish their ports on `127.0.0.1` only and the GUI connects to those loopback endpoints
by default, so no client configuration is needed. To reach a remote server, or to use the
Unix domain sockets in `.runtime/socks/` instead, copy `.env.example` to `.env` in the
repository root and edit the `MESHWORK_*` addresses.

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for detailed setup options including
remote GPU deployment, and [docs/REPRODUCTION.md](docs/REPRODUCTION.md) for the exact
GUI steps used for the paper examples.

## Reproducing Paper Results

If you are reviewing or reproducing results from the SoftwareX paper, see [docs/REPRODUCTION.md](docs/REPRODUCTION.md) for step-by-step instructions for each dataset.

## Documentation

- [REPRODUCTION.md](docs/REPRODUCTION.md) — Reproducing paper results
- [DATASETS.md](docs/DATASETS.md) — Dataset sources, licenses, and download links
- [CONFIGURATION.md](docs/CONFIGURATION.md) — Docker setup, deployment options, parameter reference
- [scripts/eval/README.md](scripts/eval/README.md) — Evaluation scripts (plane-detection and scale ablations, reference comparison, metrics tables)

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

Validation datasets provided by:
- British Museum Digital Humanities (Alexander the Great, CC-BY-NC-SA)
- Natowi (Flowerpot, CC-BY-SA 4.0)