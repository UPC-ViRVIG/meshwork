# Evaluation scripts

Headless scripts that call the same processing functions as the GUI
(`core/pointcloud.py`) so that the numbers reported in the paper can be
regenerated from a reconstruction output folder. Run them from the
repository root with the same Python environment as the GUI.

| Script | Purpose |
|--------|---------|
| `ablation_plane.py <output_folder>` | Radial-profile plane detector vs. full-cloud RANSAC (`segment_plane`) on the same dense cloud: plane/gravity alignment, inlier ratio, removed fraction, retention after outlier filtering, timings. `--gt-background table.ply` adds normal-angle error, offset error, precision/recall against a manually isolated background cloud. |
| `ablation_scale.py <moving.ply> <fixed.ply>` | Multi-scale ICP with and without the per-level scale search: fitness, inlier RMSE, cumulative scale, per-level records. `--source-transform t.json` passes the manual coarse alignment (`location`, `rotation` in radians, `scale`) as shown in the Transform panel. |
| `compare_reference.py <result> <reference>` | Aligns a MeshWork mesh or point cloud to an independent reference model (similarity transform) and reports nearest-neighbour distances in both directions as fractions of the reference bounding-box diagonal; `--reference-diagonal-mm` converts them to millimetres. |
| `collect_metrics.py <folder> [...]` | Renders the `stage_metrics.jsonl` files written by the GUI stages (elapsed time and key metrics per stage) as Markdown, LaTeX or JSON. |

Every script writes a JSON report next to its inputs (or to `--out`).
