# Reproducing Paper Results

Step-by-step instructions for reproducing the results presented in the SoftwareX paper:

> **MeshWork: A Python Framework for Automated Geometry Processing in 3D Reconstruction Workflows**

## Prerequisites

Before starting, ensure you have completed the basic setup described in [README.md](../README.md):

1. Python 3.10+ with dependencies installed (`pip install -r requirements.txt`)
2. Docker services running (`docker compose up -d`)
3. Verify services are healthy: `docker compose ps` — all services should show `healthy`

Hardware used in the paper:
- **Alexander, Flowerpot**: workstation with 14-core CPU, 16 GB RAM
- **Aloe plant**: same workstation (no GPU required for processing)

All examples use the COLMAP + OpenMVS pipeline unless noted otherwise.

## Dataset Downloads

See [DATASETS.md](DATASETS.md) for full source and license information. Quick download links:

| Dataset    | Download |
|------------|----------|
| Alexander  | `git clone https://github.com/BritishMuseumDH/alexanderTheGreat.git` |
| Flowerpot  | `git clone https://github.com/natowi/dataset_flowerpot.git` |
| Aloe plant | https://www.agisoft.com/downloads/sample-data/ (Depth images) |

## Example 1: Alexander the Great — Baseline Quality

**Objective**: Demonstrate end-to-end reconstruction quality on clean museum data.

**Expected results**: ~280,000 vertex watertight mesh, ~18 min processing time.

### Steps

```bash
# 1. Download dataset
git clone https://github.com/BritishMuseumDH/alexanderTheGreat.git
```

2. Launch MeshWork: `python -m meshwork`

3. Import images:
   - **File → Import Images** — select all `.jpg` files from the `alexanderTheGreat/raw/` directory

4. Run reconstruction:
   - **Reconstruct → Start Pipeline**
   - Select pipeline: **COLMAP + OpenMVS**
   - Select quality preset: **High**
   - Click **Start**

5. Wait for completion (~18 minutes). Progress is displayed in the status bar.

6. The reconstructed mesh appears in the 3D viewport. Inspect facial features and drapery detail.

7. Export result:
   - **File → Export Mesh** — saves as `.ply` or `.obj`

### Expected Output

- Watertight mesh with approximately 280,000 vertices
- Photo-based texture with preserved color fidelity
- Detail visible in facial features, hair, and drapery folds

## Example 2: Flowerpot — Background Removal Pipeline

**Objective**: Demonstrate the automated plane detection and cleaning pipeline, and compare two processing strategies.

### Steps

```bash
# 1. Download dataset
git clone https://github.com/natowi/dataset_flowerpot.git
```

2. Launch MeshWork and import images from `dataset_flowerpot/full_dataset/`

3. Run reconstruction (COLMAP + OpenMVS, **Medium** preset)

4. After reconstruction completes, the raw point cloud includes the table surface.

#### Method A: Point Cloud Cleaning + Poisson Reconstruction

5a. Open the processing dialog: **Process → Point Cloud Processing**

6a. Run **Plane Detection & Removal**:
    - The gravity-aligned RANSAC algorithm detects the table surface
    - Review the margin analysis and accept the suggested threshold
    - The table geometry is removed

7a. Run **Outlier Filtering**:
    - Select **DBSCAN + Statistical** strategy
    - Accept default parameters

8a. Run **Surface Reconstruction**:
    - Select **Poisson reconstruction**
    - The result shows a watertight mesh but with color interpolation artifacts near the removed table region

#### Method B: Direct OpenMVS Mesh Generation

5b. Instead of point cloud cleaning, run **Reconstruct → Generate Mesh (OpenMVS)**

6b. The OpenMVS pipeline generates a textured mesh directly with photo-based texture mapping

#### Comparison

- Method A produces a watertight closed surface but shows color artifacts from Poisson hole-filling near the pot's base
- Method B preserves higher visual fidelity through photo-based texturing
- Method B is preferred when photo-mesh correspondences remain intact; Method A is necessary when correspondences are lost (e.g., after multi-scan registration)

## Example 3: Aloe Plant — Tolerance to Optical Artifacts

**Objective**: Demonstrate reconstruction from consumer-grade iPad Pro capture with depth-of-field blur.

### Steps

1. Download the "Depth images" dataset from https://www.agisoft.com/downloads/sample-data/

2. Launch MeshWork and import the 29 images

3. Run reconstruction (COLMAP + OpenMVS, **Medium** preset)

4. Run point cloud processing:
   - **Plane Detection & Removal** with conservative parameters
   - **Outlier Filtering** with tighter statistical thresholds to distinguish botanical structure from noise

5. Examine the result:
   - Overall botanical form is preserved
   - Approximately 65% of point density retained after filtering
   - Fine spines show some degradation in heavily blurred regions

### Notes

- This dataset is more challenging than the others due to optical blur
- Parameter adjustment from defaults is expected for this type of input
- The result demonstrates the framework's tolerance to imperfect capture conditions, not its optimal quality

## Troubleshooting

**Docker services won't start**: Check `docker compose logs` for error details. Common issues: port conflicts (50051-50053), insufficient disk space for container images.

**Reconstruction fails at dense stage**: Ensure sufficient RAM (16 GB recommended). For large datasets, try **Medium** preset instead of **High** to reduce memory usage.

**GPU not detected by AliceVision**: Verify NVIDIA Container Toolkit is installed and `nvidia-smi` works inside containers: `docker compose exec alicevision nvidia-smi`

**Slow processing on CPU**: COLMAP + OpenMVS can run CPU-only but will be significantly slower. Expected times in the paper assume the hardware listed above.