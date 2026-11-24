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
| `reevaluate_alignment.py` | Re-evaluate saved final transforms without optimisation | Manifest referencing saved alignment JSON | Required `--out` report file |
| `object_loss_from_photomasks.py` | Estimate point loss from photo masks | `result_dir`, masks directory, plane-ablation JSON | `object_loss.json` beside the plane-ablation JSON |
| `plot_plane_cuts.py` | Plot detected planes and removed points | `result_dir` with `eval_plane/ablation_plane.json` | `result_dir/eval_plane/plane_cuts.png` |
| `compare_reference.py` | Bidirectional distances after similarity alignment | Result and reference geometry files | `eval_reference/compare_reference.json` beside the result geometry, with normalised and aligned clouds |
| `collect_metrics.py` | Format saved stage metrics | Result directories containing `stage_metrics.jsonl` | Standard output as Markdown; `--format` also accepts LaTeX or JSON |

For `ablation_plane.py` and `compare_reference.py`, `--out` selects an output
**directory**. For `ablation_scale.py`, `object_loss_from_photomasks.py` and
`plot_plane_cuts.py`, it selects an output **file**. `reevaluate_alignment.py`
requires a new output **file** and refuses to overwrite one. `collect_metrics.py` has no
`--out`; redirect its standard output to save a report.

For `ablation_scale.py`, `--source-transform` and `--target-transform` accept
JSON files with `location`, `rotation` (radians) and `scale` for coarse alignment
or controlled scale perturbations. Both default to identity.
See the [axe experiments](../../docs/REPRODUCTION.md#example-3-socketed-axe---multi-scan-assembly)
for the paper's settings and reference comparison.

New registration reports evaluate `fitness` and `rmse` at the final returned
object transform, using the last ICP level's samples and correspondence threshold
in target-local coordinates. The `evaluation` metadata records these choices and
coordinate mappings. Per-level `fitness` and `inlier_rmse` remain diagnostics from
ICP before that level's scale search; `rmse_after_scale` is the best pre-search or
trial ICP value, not the final output's RMSE. `level_metric_semantics` labels them.

For `ablation_scale.py`, `--seed N` resets Open3D's random seed before each variant.
For repeatable runs, also set `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1` before
launching Python and keep the same inputs and software environment. A seed alone
does not guarantee identical results across threads, versions or platforms.

To re-evaluate a saved alignment, create a manifest such as:

```json
{"cases": [{
  "id": "axe",
  "record": "/path/to/ablation_scale.json",
  "source_transform": "/path/to/source-input.json",
  "target_transform": "/path/to/target-input.json",
  "input_evidence": "Describe the saved records establishing both input transforms."
}]}
```

```bash
python scripts/eval/reevaluate_alignment.py manifest.json --out reevaluated.json
```

The transform files use the fields described above and must contain the transforms
**before** alignment, not `new_transform`. Relative paths resolve against the
manifest's directory; optional `source_ply` and `target_ply` override the saved
point-cloud paths. The script replays saved scale steps and evaluates the saved
output without ICP or RANSAC. Do not assume identity when old input transforms
are missing. Matching sample counts alone do not establish identical historical
inputs, voxel membership or software environment.

The mask script reads only the first camera entry in `cameras.txt`, which must
be `PINHOLE`, and uses its intrinsics for all views. Masks must match that
camera's image dimensions after any rotation.
Use `--mask-transpose ROTATE_270` for the
[limestone capital](../../docs/REPRODUCTION.md#example-4-limestone-capital---a-support-smaller-than-the-object).
The plotting script reads
`eval_plane/object_loss.json` when present to label object loss; otherwise it
labels the fraction of the whole cloud removed.
