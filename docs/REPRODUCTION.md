# Reproducing Paper Results

Step-by-step instructions for reproducing the results reported in the SoftwareX paper:

> **MeshWork: A Python Framework for Assisted Geometry Processing in 3D Reconstruction Workflows**

## Prerequisites

1. Complete the Quick Start in [README.md](../README.md): `pip install -r requirements.txt`, then `cd docker && ./build.sh && docker compose up -d`, then `python main.py` from the repository root.
2. Inside `docker/`, `docker compose ps` lists `colmap-service` and `blender-service` as `healthy`. AliceVision is not needed for the examples below; on machines without an NVIDIA GPU start only `docker compose up -d colmap-service blender-service`.

Hardware used for the timings reported in the paper: Intel Core i7-10700K (8 cores / 16 threads), 32 GB RAM, NVIDIA GeForce RTX 3070 (8 GB VRAM). CPU-only operation was verified on a laptop with an Intel Core Ultra 7 155U and integrated graphics; timings on other hardware will differ.

All examples use the COLMAP + OpenMVS path (`Tool: COLMAP` in the reconstruction dialog).

## Datasets

See [DATASETS.md](DATASETS.md) for sources, licenses and attribution.

| Dataset | Download | Photographs |
|---------|----------|-------------|
| Alexander the Great | `git clone https://github.com/BritishMuseumDH/alexanderTheGreat.git` | `alexanderTheGreat/images/` (57) |
| Flowerpot | `git clone https://github.com/natowi/dataset_flowerpot.git` | `dataset_flowerpot/full_dataset/` (81) |
| Socketed axe | `git clone https://github.com/MicroPasts/socketed-axe-version2.git` | `socketed-axe-version2/photos/` (54); reference model in `models/` |

## GUI workflow

### Reconstruction (Tools > 3D Reconstruction..., Ctrl+R)

1. Input > Browse...: select the folder containing the photographs.
2. Output > Browse...: select an empty output folder. Everything produced for this dataset is written there.
3. Settings: Tool `COLMAP`; Quality `Fast`, `Balanced` or `Quality`; Output `Point Cloud` (dense point cloud, the input of the point cloud pipeline) or `Dense Mesh` (OpenMVS textured mesh).
4. Start. Progress and the console output of the services stream into the dialog; the viewport stays interactive while the job runs.
5. Import loads the result into the scene. The output folder now contains `dense_points.ply`, `cameras.txt`, `images.txt`, `reconstruction.json` and, for `Dense Mesh`, the textured mesh (`.obj`, `.mtl`, `.jpg`).

### Point cloud pipeline (Tools panel, Point Cloud group)

Select the object(s) in the Scene panel, press the tool button, adjust the parameters that appear, then Apply (Cancel closes the tool without changes).

| Tool | What it does | Result |
|------|--------------|--------|
| Analyze Plane | Estimates gravity from `images.txt`, detects the supporting plane, rotates the object upright and fills in the recommended Margin | `1.stage1_params.yaml`, `1.radial_profile.csv`, `1.plane_candidates.csv` |
| Remove Plane | Removes points closer than Margin to the plane, then `DBSCAN` or `Statistical` outlier removal | new object `2.cleaned_m<margin>` in a canonical frame (plane at z = 0) |
| Align Clouds | Requires two selected objects: the one listed first in the Scene panel is moved onto the other (FPFH + RANSAC initialization, multi-scale ICP with scale estimation). Pre-align roughly with the Transform panel when the scans are far apart | transform of the moving object updated; `3.alignment_params.yaml` in its folder |
| Merge Clouds | Requires two selected objects: concatenates them in the frame of the one listed second in the Scene panel and applies the ticked filters | new object `4.merged_<filters>` |
| Generate Mesh | Poisson reconstruction with the given Depth, optional hole filling and smoothing | new object `5.mesh_d<depth>` (vertex colours) |

File > Export... saves the selected object as `.obj`, `.ply` or `.stl`; File > Save stores the scene as a `.blend` project.

### Metrics

Every pipeline stage appends its elapsed time and key metrics to `stage_metrics.jsonl` in the output folder of the object it processed. Collect them for the paper tables with

```bash
python scripts/eval/collect_metrics.py <output folder> [<output folder> ...] --last-per-stage --format latex
```

The UI event-loop latency during processing is logged to `~/.meshwork/logs/ui_latency.csv` (see [CONFIGURATION.md](CONFIGURATION.md)).

## Example 1: Alexander the Great - baseline quality

**Objective**: end-to-end reconstruction quality on clean museum data.

1. Reconstruction: photographs `alexanderTheGreat/images/`, Quality `Quality`, Output `Dense Mesh`.
2. Import the result and inspect facial features, hair and drapery folds.
3. File > Export... as `.obj` to keep the photo texture.

**Expected output**: a watertight textured mesh of approximately 280,000 vertices produced in about 18 minutes on the hardware listed above. `reconstruction.json` records the image count, the sparse point count and the timings of the reconstruction stages.

## Example 2: Flowerpot - background removal

**Objective**: automated supporting-plane detection and cleaning, and a comparison of two mesh generation strategies.

1. Reconstruction: all 81 photographs of `dataset_flowerpot/full_dataset/`, Quality `Balanced`, Output `Point Cloud`.
2. Import; select the imported point cloud (`dense_points`); Analyze Plane > Apply. The object is rotated upright and Margin is filled in with the recommended value.
3. Remove Plane with Method `DBSCAN` > Apply. `2.cleaned_m<margin>` appears without the table and the supporting geometry.
4. Select the cleaned object; Generate Mesh (Depth 9) > Apply. This is method A: cleaned point cloud + Poisson reconstruction (vertex-coloured mesh).
5. Method B: run the reconstruction again with Output `Dense Mesh` to obtain the OpenMVS mesh with photo-based textures.

**Comparison**: method A yields a closed surface but shows colour interpolation artifacts near the removed table region; method B preserves higher visual fidelity through photo texturing and is preferred whenever the photo-mesh correspondence is intact. Method A is required when that correspondence is lost, for example after multi-scan merging (Example 3).

**Ablation** (plane detector vs. plain full-cloud RANSAC on the same cloud):

```bash
python scripts/eval/ablation_plane.py <output folder>
python scripts/eval/ablation_plane.py <output folder> --gt-background <table.ply>
```

`<table.ply>` is a table-only cloud isolated by hand (select and delete the object points in the GUI, then File > Export...); with it the script also reports the normal-angle and offset errors of both planes and the precision/recall of the removed points.

## Example 3: Socketed axe - multi-scan assembly

**Objective**: the complete assisted multi-scan pipeline (plane removal, registration with scale estimation, merging, meshing) on a real archaeological artifact.

1. The 54 photographs (`IMG_8835.JPG` to `IMG_8888.JPG`) come from a single capture session. Split them into two disjoint subsets and reconstruct each into its own output folder (Quality `Balanced`, Output `Point Cloud`): subset A = `IMG_8835`-`IMG_8860` (26 images), subset B = `IMG_8861`-`IMG_8888` (28 images).

   ```bash
   cd socketed-axe-version2
   mkdir -p scanA scanB
   for n in $(seq 8835 8860); do cp photos/IMG_$n.JPG scanA/; done
   for n in $(seq 8861 8888); do cp photos/IMG_$n.JPG scanB/; done
   ```

   The two partial reconstructions therefore have independent, slightly different scales and reference frames, which is the situation the registration stage is designed for.
2. For each imported scan: Analyze Plane > Apply, then Remove Plane (`DBSCAN`) > Apply. Both cleaned scans are now in canonical frames (table at z = 0, centroid at the origin).
3. Coarse alignment: the cleaned scan listed first in the Scene panel (scan A, imported first) is the one that will move. Select it and rotate/translate it with the Transform panel until it roughly overlaps scan B.
4. Select both cleaned scans; Align Clouds > Apply. Scan A is registered onto scan B. `3.alignment_params.yaml` in scan A's folder contains the fitness, the inlier RMSE, the initialization that won (RANSAC or identity), the per-level records and the estimated scale factor.
5. Keep the same selection; Merge Clouds with `DBSCAN outlier removal` and `Statistical outlier removal` ticked > Apply.
6. Select the merged object; Generate Mesh (Depth 9) > Apply. File > Export... to save the result.

The final mesh is a Poisson surface with vertex colours; the per-scan OpenMVS meshes keep their photo textures, but the merged cloud has no photo correspondence any more (see the limitations discussed in the paper).

**Ablations and reference comparison**:

```bash
# multi-scale ICP with and without the scale search
python scripts/eval/ablation_scale.py <scan A folder>/2.cleaned_m<margin>.ply <scan B folder>/2.cleaned_m<margin>.ply --source-transform coarse.json

# distance of the MeshWork result to the PhotoScan reference model distributed with the dataset
python scripts/eval/compare_reference.py <scan A folder>/5.mesh_d9.ply socketed-axe-version2/models/Socketed_axe_DPC.ply
```

`coarse.json` holds the transform of scan A after step 3 as shown in the Transform panel (`{"location": [x, y, z], "rotation": [rx, ry, rz], "scale": [sx, sy, sz]}`, rotation in radians). `compare_reference.py` aligns the result to the reference with a similarity transform and reports nearest-neighbour distances as fractions of the reference bounding-box diagonal (`--reference-diagonal-mm` converts them to millimetres when the physical size is known).

## Troubleshooting

**Docker services do not start**: inside `docker/`, check `docker compose logs`. Common causes: ports 50051-50053 in use, insufficient disk space for the images, `.runtime/` owned by root from a previous build (re-run `./build.sh`).

**The GUI cannot connect to the services**: verify `docker compose ps` shows `healthy` and that the ports are published (`127.0.0.1:50051-50053`). Without a `.env` file the client uses those loopback endpoints. If the endpoints were changed to `unix:` socket paths and the connection fails with `Permission denied`, the running containers predate the socket permission fix; rebuild them (`cd docker && docker compose build && docker compose up -d`) or switch back to TCP.

**Reconstruction stops with "Too many pings"**: the gRPC server closed the connection because the client keepalive was faster than the server tolerated during a stage that produces no output for minutes (exhaustive feature matching on larger image sets). Rebuild the service images so they pick up the current keepalive policy (`cd docker && docker compose build && docker compose up -d`), or run the services over Unix domain sockets, where no keepalive pings are sent.

**Reconstruction fails in the dense stage**: ensure enough RAM (16 GB minimum, 32 GB recommended for `Quality`). Use `Balanced` or `Fast` to reduce memory usage.

**Analyze Plane reports that images.txt is missing**: the object was not produced by the reconstruction dialog (for example an imported laser scan). Orient it upright with the Transform panel; the stage then uses the scene vertical axis as the gravity direction.

**GPU not detected by AliceVision**: verify that the NVIDIA Container Toolkit is installed and that `docker compose exec alicevision-service nvidia-smi` works.

**Slow processing on CPU**: COLMAP + OpenMVS runs CPU-only but considerably slower; the timings in the paper assume the hardware listed above.
