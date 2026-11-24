"""Re-evaluate saved alignments without running ICP or RANSAC.

Usage: python scripts/eval/reevaluate_alignment.py manifest.json --out report.json

The manifest contains a ``cases`` list. Each case supplies ``id``, ``record``
(an ablation JSON), explicit ``source_transform`` and ``target_transform``
(objects or JSON paths), and ``input_evidence`` describing their provenance.
Optional ``source_ply``/``target_ply`` override the paths in the saved record.
Transforms require location, rotation (radians, Rz @ Ry @ Rx), and scale.
The script deliberately does not infer identity transforms from missing data.

Final-level samples are reconstructed by replaying the saved scale steps about
the full source cloud's centroid, with the original voxel sizes. The stored
final object transform is then evaluated on those samples in target-local
coordinates, at twice the final voxel size. Sampling counts are checked against
the saved counts. Matching counts support reconstruction but do not prove that
unrecorded input transforms or the original software environment were identical.
"""

import argparse
import copy
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import open3d as o3d


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(value, directory):
    path = Path(value)
    return (directory / path).resolve() if not path.is_absolute() else path.resolve()


def compose_transform(value):
    vectors = {}
    for name in ('location', 'rotation', 'scale'):
        array = np.asarray(value[name], dtype=float)
        if array.shape != (3,) or not np.all(np.isfinite(array)):
            raise ValueError(f'{name} must contain three finite numbers')
        vectors[name] = array
    if np.any(vectors['scale'] == 0):
        raise ValueError('transform scale must be nonzero')
    rx, ry, rz = vectors['rotation']
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    rotation_x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    rotation_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rotation_z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation_z @ rotation_y @ rotation_x @ np.diag(vectors['scale'])
    matrix[:3, 3] = vectors['location']
    return matrix


def read_transform(value, directory):
    provenance = None
    if isinstance(value, str):
        path = resolve_path(value, directory)
        value = json.loads(path.read_text())
        provenance = {'path': str(path), 'sha256': sha256(path)}
    matrix = compose_transform(value)
    return value, matrix, provenance


def evaluate_saved_alignment(source, target, source_matrix, target_matrix, row):
    registration = row.get('registration', row)
    levels = registration['levels']
    if not levels:
        raise ValueError('saved per-level sampling and scale steps are required')
    final_matrix = compose_transform(row['new_transform'])
    raw_to_sampling = np.linalg.inv(target_matrix) @ source_matrix
    moving = copy.deepcopy(source).transform(raw_to_sampling)
    count_checks = []
    scale_product = 1.0
    for index, level in enumerate(levels):
        voxel_size = float(level['voxel_size'])
        step = float(level['scale_step'])
        if not np.isfinite(voxel_size) or voxel_size <= 0:
            raise ValueError('voxel sizes must be finite and positive')
        if not np.isfinite(step) or step <= 0:
            raise ValueError('scale steps must be finite and positive')
        source_sample = moving.voxel_down_sample(voxel_size)
        target_sample = target.voxel_down_sample(voxel_size)
        if not len(source_sample.points) or not len(target_sample.points):
            raise ValueError('empty evaluation sample')
        source_count, target_count = len(source_sample.points), len(target_sample.points)
        count_checks.append({
            'level': level.get('level', index + 1),
            'voxel_size': voxel_size,
            'source_points': source_count,
            'target_points': target_count,
            'recorded_source_points': int(level['source_points']),
            'recorded_target_points': int(level['target_points']),
            'match': source_count == int(level['source_points'])
                     and target_count == int(level['target_points']),
            'scale_step': step,
        })
        if index == len(levels) - 1:
            final_sampling_matrix = raw_to_sampling.copy()
        # Recompute the centre at each step, as the original implementation did.
        if step != 1.0:
            centre = moving.get_center()
            centred_scale = np.eye(4)
            centred_scale[:3, :3] *= step
            centred_scale[:3, 3] = (1.0 - step) * centre
            moving.scale(step, center=centre)
            raw_to_sampling = centred_scale @ raw_to_sampling
        scale_product *= step

    threshold = 2.0 * voxel_size
    evaluation_transform = (np.linalg.inv(target_matrix) @ final_matrix
                            @ np.linalg.inv(final_sampling_matrix))
    evaluation = o3d.pipelines.registration.evaluate_registration(
        source_sample, target_sample, threshold, evaluation_transform)
    original = {'fitness': float(row['fitness']), 'rmse': float(row['rmse'])}
    measured = {'fitness': float(evaluation.fitness),
                'rmse': float(evaluation.inlier_rmse),
                'correspondences': len(evaluation.correspondence_set)}
    counts_match = all(check['match'] for check in count_checks)
    return {
        'status': 'sampling_counts_match' if counts_match else 'sampling_counts_mismatch',
        'sampling_checks': count_checks,
        'recorded_metrics': original,
        'evaluated_metrics': measured,
        'metric_changes': {key: measured[key] - original[key] for key in original},
        'last_scale_step': float(levels[-1]['scale_step']),
        'replayed_scale_product': scale_product,
        'recorded_cumulative_scale': registration.get('cumulative_scale'),
        'new_transform': row['new_transform'],
        'evaluation': {
            'method': 'Open3D evaluate_registration; no optimisation',
            'coordinate_frame': 'target_local',
            'max_correspondence_distance': threshold,
            'final_voxel_size': voxel_size,
            'source_points': len(source_sample.points),
            'target_points': len(target_sample.points),
            'raw_source_to_final_sample': final_sampling_matrix.tolist(),
            'returned_source_to_world': final_matrix.tolist(),
            'sample_to_final_target': evaluation_transform.tolist(),
        },
    }


def evaluate_manifest(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    directory = manifest_path.parent
    clouds, hashes = {}, {}

    def cloud_info(path):
        if path not in clouds:
            cloud = o3d.io.read_point_cloud(str(path))
            if not len(cloud.points) or not np.all(np.isfinite(np.asarray(cloud.points))):
                raise ValueError(f'empty or nonfinite point cloud: {path}')
            clouds[path] = cloud
            hashes[path] = sha256(path)
        return clouds[path], {'path': str(path), 'sha256': hashes[path],
                              'points': len(clouds[path].points)}

    results = []
    for case in manifest['cases']:
        result = {'id': case['id'], 'input_evidence': case.get('input_evidence')}
        try:
            if not result['input_evidence']:
                raise ValueError('input_evidence must describe how transforms were obtained')
            record_path = resolve_path(case['record'], directory)
            record = json.loads(record_path.read_text())
            result['record'] = {'path': str(record_path), 'sha256': sha256(record_path)}
            source_path = resolve_path(case.get('source_ply', record.get('source')), directory)
            target_path = resolve_path(case.get('target_ply', record.get('target')), directory)
            source, result['source'] = cloud_info(source_path)
            target, result['target'] = cloud_info(target_path)
            source_values, source_matrix, source_file = read_transform(case['source_transform'], directory)
            target_values, target_matrix, target_file = read_transform(case['target_transform'], directory)
            result['input_transforms'] = {
                'source': source_values, 'target': target_values,
                'source_matrix': source_matrix.tolist(), 'target_matrix': target_matrix.tolist(),
                'source_file': source_file, 'target_file': target_file,
            }
            default_variants = [key for key in ('with_scale', 'without_scale') if key in record]
            variants = case.get('variants', default_variants or ['saved'])
            result['variants'] = {}
            for variant in variants:
                row = record if variant == 'saved' else record[variant]
                result['variants'][variant] = evaluate_saved_alignment(
                    source, target, source_matrix, target_matrix, row)
            result['status'] = ('sampling_counts_match' if all(
                value['status'] == 'sampling_counts_match' for value in result['variants'].values())
                else 'sampling_counts_mismatch')
        except (KeyError, TypeError, ValueError, OSError, np.linalg.LinAlgError) as error:
            result['status'] = 'unavailable'
            result['error'] = f'{type(error).__name__}: {error}'
        results.append(result)
        print(f"{result['id']}: {result['status']}", flush=True)
    return {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'manifest': {'path': str(manifest_path), 'sha256': sha256(manifest_path)},
        'script_sha256': sha256(__file__),
        'environment': {'python': sys.version, 'python_executable': sys.executable,
                        'numpy': np.__version__, 'open3d': o3d.__version__,
                        'platform': platform.platform()},
        'protocol': 'Replay saved centred scale steps; reconstruct original final-level '
                    'voxel samples; evaluate the saved final object transform without '
                    'optimisation. No assumption that old metrics already describe that transform.',
        'limitations': 'Matching sample counts do not establish original input-transform '
                      'provenance, identical sample membership, or an identical original '
                      'Open3D environment. Consult input_evidence for each case.',
        'cases': results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('--out already exists; choose a new path to preserve previous results')
    report = evaluate_manifest(args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(f'written: {args.out}')
    return 0 if all(case['status'] == 'sampling_counts_match' for case in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
