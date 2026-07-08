# MeshWork

A Python framework for automated geometry processing in 3D reconstruction workflows.

MeshWork integrates heterogeneous photogrammetry and mesh-processing tools (COLMAP, AliceVision, OpenMVS, Blender) into a unified, automated pipeline with an interactive GUI. It is designed for cultural heritage digitization, architectural documentation, and digital content creation.

## Features

- **End-to-end reconstruction**: from unordered photographs to textured meshes
- **Two reconstruction paths**: COLMAP + OpenMVS (CPU/GPU flexible) or AliceVision (GPU-optimized)
- **Automated point cloud processing**: RANSAC plane detection, multi-scale ICP registration, multi-strategy outlier filtering, Poisson surface reconstruction
- **Quality presets**: Low / Medium / High one-click presets with full expert parameter access
- **Interactive 3D visualization**: PyVista-based viewport with real-time manipulation
- **Containerized deployment**: Docker isolates all tool dependencies; single `docker compose up` to start

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
git clone https://github.com/wcjwing/meshwork.git
cd meshwork

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Start containerized services
docker compose up -d

# 4. Launch the GUI
python -m meshwork
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for detailed setup options including remote GPU deployment.

## Reproducing Paper Results

If you are reviewing or reproducing results from the SoftwareX paper, see [docs/REPRODUCTION.md](docs/REPRODUCTION.md) for step-by-step instructions for each dataset.

## Documentation

- [REPRODUCTION.md](docs/REPRODUCTION.md) — Reproducing paper results
- [DATASETS.md](docs/DATASETS.md) — Dataset sources, licenses, and download links
- [CONFIGURATION.md](docs/CONFIGURATION.md) — Docker setup, deployment options, parameter reference

## Project Structure

```
meshwork/
├── meshwork/              # Python package
│   ├── ui/                # Qt/PySide6 presentation layer
│   ├── logic/             # Business logic, scene management
│   ├── processing/        # Point cloud algorithms (Open3D)
│   ├── infrastructure/    # gRPC clients, Docker coordination
│   └── signals/           # Signal router, event definitions
├── services/              # Docker service definitions
│   ├── colmap/            # COLMAP + OpenMVS container
│   ├── alicevision/       # AliceVision container
│   └── blender/           # Blender headless container
├── proto/                 # gRPC protocol buffer definitions
├── docs/                  # Documentation
├── docker-compose.yml     # Service orchestration
├── requirements.txt       # Python dependencies
└── README.md
```

## Citation

If you use MeshWork in your research, please cite:

```bibtex
@article{wang2026meshwork,
  title     = {MeshWork: A Python Framework for Automated Geometry Processing
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