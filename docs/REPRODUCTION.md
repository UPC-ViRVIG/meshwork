# Reproducing Paper Results

GUI steps and evaluation commands for the MeshWork SoftwareX paper.

## Prerequisites

1. Install the Python dependencies and start the Docker services as described in [Configuration](CONFIGURATION.md). The examples use COLMAP + OpenMVS; only `colmap-service` and `blender-service` are needed. Check that both report `healthy` in `docker compose ps`.
2. Start the GUI with `python main.py` from the repository root.

Paper timings were measured on an Intel Core i7-10700K (8 cores / 16 threads), 32 GB RAM and an NVIDIA GeForce RTX 3070 (8 GB VRAM), using the [GPU configuration](CONFIGURATION.md#gpu-configuration). CPU-only operation was checked on an Intel Core Ultra 7 155U laptop. Timings and reconstructed point counts can vary with hardware and randomised processing steps.

## Datasets

Download the four datasets listed in [DATASETS.md](DATASETS.md), which includes image locations, licenses and attribution. Paths below use their repository names.

## GUI workflow

### Reconstruction (Tools > 3D Reconstruction..., Ctrl+R)

1. Set Input to the photograph folder and Output to a new project folder for that dataset or image subset.
2. Select Tool `COLMAP`, the Quality preset and either `Point Cloud` or `Dense Mesh`, as specified in each example.
3. Press Start. Progress and service output appear in the dialog.
4. Press Import to load the result. For `Dense Mesh` this imports the mesh; use File > Import to load `dense_points.ply` for point-cloud processing.

Each run writes to `<project folder>/recon_<timestamp>/result/`, including the dense cloud, camera poses and `reconstruction.json`. Images are copied to `<project folder>/converted/` with EXIF orientation applied (v1.0.1 onward). See [output files](CONFIGURATION.md#outputs-of-the-reconstruction-services) for details.

### Point cloud pipeline (Tools panel, Point Cloud group)

Select objects in the Scene panel, choose a tool, check its parameters and press Apply.

| Tool | Use |
|------|-----|
| Analyze Plane | Estimates gravity from camera poses, detects the support, rotates the object upright and recommends a cut Margin. |
| Remove Plane | Removes points whose signed distance to the plane is below Margin, then applies `DBSCAN` or `Statistical` filtering. The cleaned cloud is centred at its centroid, with the support normal along z. |
| Align Clouds | Select two clouds; the first listed in the Scene panel moves onto the second. For other datasets, use the Transform panel for coarse alignment if needed. |
| Merge Clouds | Select two clouds and choose the filters. Their object transforms are applied before merging in world coordinates. |
| Generate Mesh | Produces a Poisson mesh with vertex colours. |

For the paper meshes, use Depth `9`, Fill holes enabled, Max hole size `400`, Simplify to `300000` triangles and Smooth iterations `1`. Parameter details and saved filenames are in [Configuration](CONFIGURATION.md#point-cloud-processing-parameters).

File > Export saves the selected objects: meshes as OBJ, PLY or STL; point clouds as PLY or vertex-only OBJ. File > Save stores the scene as a Blender project.

### Metrics

Processing stages append timings and metrics to `stage_metrics.jsonl` beside the input cloud. Run evaluation commands from the MeshWork repository root, replacing the example paths with your result folders and filenames.

```bash
python scripts/eval/collect_metrics.py "/path/to/run/result" --format latex
```

`--last-per-stage` keeps the last record for each stage and object in each result folder. For repeated operations, sum the relevant timings separately: the paper's axe registration time includes two successive passes. The summary table's `scale` is the correction within that pass; the paper's final object scale comes from `new_transform.scale` in `3.alignment_params.yaml`.

UI latency is logged separately; see [Logging and UI latency](CONFIGURATION.md#logging-and-ui-latency).

## Example 1: Alexander the Great - baseline quality

1. Reconstruct `alexanderTheGreat/images/` with Quality `Quality` and Output `Dense Mesh`.
2. Import the result. To preserve its photo texture, keep the original OBJ, MTL and texture images from the run's `result/` folder together.

The reported run produced a textured mesh of approximately 280,000 vertices in 6.5 minutes. Image counts and settings are saved in `reconstruction.json`; timings are reported in the reconstruction log.

## Example 2: Flowerpot - background removal

1. Reconstruct all 81 photographs in `dataset_flowerpot/full_dataset/` with Quality `Balanced` and Output `Point Cloud`.
2. Import and select `dense_points`; run Analyze Plane, then Remove Plane with Method `DBSCAN`.
3. Select the cleaned cloud and run Generate Mesh with the settings above.
4. To compare outputs, repeat reconstruction with Output `Dense Mesh`.

The cleaned Poisson mesh removes the table but shows colour interpolation near the cut. The OpenMVS mesh keeps the table and photographic texture.

Compare plane detection with full-cloud RANSAC:

```bash
python scripts/eval/ablation_plane.py "/path/to/flowerpot/result"
```

Optionally add `--gt-background "/path/to/table.ply"` to measure normal-angle and offset errors, and removal precision/recall. Prepare this table-only cloud with an external point-cloud editor, keeping the dense cloud's coordinate frame.

## Example 3: Socketed axe - multi-scan assembly

1. Split the 54 photographs from one capture session into subsets A (`IMG_8835`–`IMG_8860`, 26 images) and B (`IMG_8861`–`IMG_8888`, 28 images):

   ```bash
   cd socketed-axe-version2
   mkdir -p scanA scanB
   for n in $(seq 8835 8860); do cp photos/IMG_$n.JPG scanA/; done
   for n in $(seq 8861 8888); do cp photos/IMG_$n.JPG scanB/; done
   ```

2. Reconstruct each subset into its own project folder with Quality `Balanced` and Output `Point Cloud`.
3. Import A before B. For each cloud, run Analyze Plane, then Remove Plane with Method `DBSCAN`.
4. Select both cleaned clouds, with A first in the Scene panel, and apply Align Clouds twice without manual pre-alignment.
5. Merge with `DBSCAN outlier removal`, `Statistical outlier removal` and `Normal consistency filter` enabled; leave radius filtering off.
6. Select the merged cloud and run Generate Mesh with the settings above. The saved mesh is `5.mesh_d9_s300000.ply`; repeat runs may add a suffix.

Run the scale ablation on the cleaned files, without the GUI alignment transforms:

```bash
python scripts/eval/ablation_scale.py "/path/to/scanA/result/2.cleaned_m0.068.ply" \
    "/path/to/scanB/result/2.cleaned_m0.031.ply"
```

Use the filenames produced by your run if the recommended margins differ. For the scale-perturbation experiments, add `--source-transform scale.json`, containing `{"location": [0, 0, 0], "rotation": [0, 0, 0], "scale": [0.9, 0.9, 0.9]}`. Test factors `0.9`, `1.1` and `0.8`, each five times with a separate `--out` path. This changes the cloud's scale, not the acquisition conditions. These runs test the sensitivity of the complete pipeline; their independent random initialisations do not isolate the benefit of scale search.

Compare the merged mesh with the dataset's PhotoScan reference:

```bash
python scripts/eval/compare_reference.py "/path/to/scanA/result/5.mesh_d9_s300000.ply" \
    "/path/to/socketed-axe-version2/models/Socketed_axe_DPC.ply" \
    --reference-diagonal-mm 140
```

The comparison uses a similarity alignment and reports distances relative to the reference diagonal. The dataset's enabled 0.080 m scale bar supports the 140 mm diagonal used for conversion. Both models use the same photographs, so this measures agreement between reconstructions, not absolute accuracy.

## Example 4: Limestone capital - a support smaller than the object

These steps reproduce the reconstruction run reported in the paper:

1. Reconstruct `architecturalElement/images/` with Quality `Balanced` and Output `Dense Mesh`.
2. Use File > Import to load the run's `dense_points.ply`. Select it and run Analyze Plane.
3. Run Remove Plane with Method `DBSCAN`, then Generate Mesh with the settings above.

The gallery walls are barely reconstructed, leaving a small ring of plinth points below the capital. In the reported ablation, both detected planes intersect the object. With the recommended margin, full-cloud RANSAC removes 49.8% of mask-labelled object points and the guided cut removes 18.8%; even at zero margin, losses are 25.8% and 9.0%, respectively. Reducing the margin therefore cannot guarantee preservation of the base. Users who need to preserve it can skip plane removal and retain the uncut cloud; the reported ablation uses the unadjusted recommendation.

```bash
python scripts/eval/ablation_plane.py "/path/to/capital/result"
python scripts/eval/object_loss_from_photomasks.py "/path/to/capital/result" \
    "/path/to/architecturalElement/masks" \
    "/path/to/capital/result/eval_plane/ablation_plane.json" \
    --mask-transpose ROTATE_270
python scripts/eval/plot_plane_cuts.py "/path/to/capital/result" --out capital_planes.png
```

The mask rotation matches the EXIF rotation applied to the photographs. Object labels use majority voting from projected masks, requiring at least three registered views by default. They estimate object loss and depend on mask and camera-pose accuracy.

## Troubleshooting

| Problem | Check |
|---------|-------|
| Services do not start | Run `docker compose logs` from `docker/`; check port conflicts on 50051–50053, disk space and `.runtime/` permissions. |
| GUI cannot connect | Check `docker compose ps`, published ports and the endpoint settings in the repository `.env`. For socket permission errors, use loopback TCP or rebuild the service images. |
| `Too many pings` | Check the client/server periods in [Keepalive](CONFIGURATION.md#keepalive). Rebuild service images after server-side configuration changes. |
| Dense reconstruction runs out of memory | Try `Balanced` or `Fast`; `Quality` needs more RAM. |
| Analyze Plane on an external cloud | Place the PLY in its own directory as `dense_points.ply` and import that file. Without `images.txt`, orient the cloud upright with Transform; Analyze Plane uses the scene's vertical axis. |
| AliceVision cannot detect the GPU | Check the NVIDIA Container Toolkit and run `docker compose exec alicevision-service nvidia-smi`. |
