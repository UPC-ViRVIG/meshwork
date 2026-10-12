# Evaluation scripts

Run these scripts from the repository root with the GUI's Python environment.
The plane and registration experiments use the processing functions in
`core/pointcloud.py`. For dataset commands and result interpretation, see
[REPRODUCTION.md](../../docs/REPRODUCTION.md).

`result_dir` is a run's `recon_<timestamp>/result/` folder.

| Script | Purpose | Main input | Default output |
|--------|---------|------------|----------------|
| `ablation_plane.py` | Guided detector vs. full-cloud RANSAC | `result_dir` | `result_dir/eval_plane/ablation_plane.json`, with intermediate clouds and parameters |
| `ablation_scale.py` | Registration with and without scale search | Moving and fixed PLY files | `ablation_scale.json` beside the moving cloud |
| `object_loss_from_photomasks.py` | Estimate point loss from photo masks | `result_dir`, masks directory, plane-ablation JSON | `object_loss.json` beside the plane-ablation JSON |
| `plot_plane_cuts.py` | Plot detected planes and removed points | `result_dir` with `eval_plane/ablation_plane.json` | `result_dir/eval_plane/plane_cuts.png` |
| `compare_reference.py` | Bidirectional distances after similarity alignment | Result and reference geometry files | `eval_reference/compare_reference.json` beside the result geometry, with normalised and aligned clouds |
| `collect_metrics.py` | Format saved stage metrics | Result directories containing `stage_metrics.jsonl` | Standard output as Markdown; `--format` also accepts LaTeX or JSON |

For `ablation_plane.py` and `compare_reference.py`, `--out` selects an output
**directory**. For `ablation_scale.py`, `object_loss_from_photomasks.py` and
`plot_plane_cuts.py`, it selects an output **file**. `collect_metrics.py` has no
`--out`; redirect its standard output to save a report.

For `ablation_scale.py`, `--source-transform` and `--target-transform` accept
JSON files with `location`, `rotation` (radians) and `scale` for coarse alignment
or controlled scale perturbations. Both default to identity.
See the [axe experiments](../../docs/REPRODUCTION.md#example-3-socketed-axe---multi-scan-assembly)
for the paper's settings and reference comparison.

The mask script reads only the first camera entry in `cameras.txt`, which must
be `PINHOLE`, and uses its intrinsics for all views. Masks must match that
camera's image dimensions after any rotation.
Use `--mask-transpose ROTATE_270` for the
[limestone capital](../../docs/REPRODUCTION.md#example-4-limestone-capital---a-support-smaller-than-the-object).
The plotting script reads
`eval_plane/object_loss.json` when present to label object loss; otherwise it
labels the fraction of the whole cloud removed.
