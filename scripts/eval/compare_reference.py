import argparse
import time
from pathlib import Path

import numpy as np
import open3d as o3d

from _common import make_api, identity_transform, dump_json


def load_as_points(path, n_samples):
    mesh = o3d.io.read_triangle_mesh(str(path))
    if len(mesh.triangles) > 0:
        return mesh.sample_points_uniformly(number_of_points=n_samples), 'mesh'
    pcd = o3d.io.read_point_cloud(str(path))
    if len(pcd.points) == 0:
        raise SystemExit(f'no geometry loaded from {path}')
    return pcd, 'pointcloud'


def normalize(pcd):
    points = np.asarray(pcd.points)
    center = points.mean(axis=0)
    diag = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    out = o3d.geometry.PointCloud()
    out.points = o3d.utility.Vector3dVector((points - center) / diag)
    return out, center, diag


def distance_stats(source, target):
    d = np.asarray(source.compute_point_cloud_distance(target))
    return {
        'mean': float(d.mean()),
        'median': float(np.median(d)),
        'rms': float(np.sqrt(np.mean(d ** 2))),
        'p95': float(np.percentile(d, 95)),
        'max': float(d.max()),
        'within_0.5pct_diag': float(np.mean(d <= 0.005)),
        'within_1pct_diag': float(np.mean(d <= 0.01)),
    }


def scaled(stats, factor):
    return {k: v * factor for k, v in stats.items() if not k.startswith('within')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('result', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--samples', type=int, default=500000)
    parser.add_argument('--reference-diagonal-mm', type=float, default=None)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()

    api = make_api()
    out_dir = (args.out or args.result.resolve().parent / 'eval_reference').resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    result_pcd, result_kind = load_as_points(args.result, args.samples)
    ref_pcd, ref_kind = load_as_points(args.reference, args.samples)

    result_norm, _, result_diag = normalize(result_pcd)
    ref_norm, _, ref_diag = normalize(ref_pcd)

    source_ply = out_dir / 'result_normalized.ply'
    target_ply = out_dir / 'reference_normalized.ply'
    o3d.io.write_point_cloud(str(source_ply), result_norm)
    o3d.io.write_point_cloud(str(target_ply), ref_norm)

    t0 = time.perf_counter()
    alignment = api._compute_alignment(source_ply, target_ply, identity_transform(), identity_transform())
    align_time = time.perf_counter() - t0
    if alignment is None:
        raise SystemExit('alignment failed')

    transform = api._compose_transform_matrix(alignment['location'], alignment['rotation'], alignment['scale'])
    aligned = o3d.geometry.PointCloud(result_norm)
    aligned.transform(transform)
    o3d.io.write_point_cloud(str(out_dir / 'result_aligned.ply'), aligned)

    forward = distance_stats(aligned, ref_norm)
    backward = distance_stats(ref_norm, aligned)
    report = {
        'result': {
            'file': str(args.result.resolve()),
            'kind': result_kind,
            'points': int(len(result_pcd.points)),
            'bbox_diagonal': result_diag,
        },
        'reference': {
            'file': str(args.reference.resolve()),
            'kind': ref_kind,
            'points': int(len(ref_pcd.points)),
            'bbox_diagonal': ref_diag,
        },
        'alignment': {
            'elapsed_s': align_time,
            'fitness': float(alignment['fitness']),
            'rmse': float(alignment['rmse']),
            'registration': alignment['registration'],
            'scale_ratio_result_to_reference': float(np.mean(alignment['scale'])) * ref_diag / result_diag,
        },
        'distance_units': 'fraction of reference bounding-box diagonal',
        'result_to_reference': forward,
        'reference_to_result': backward,
    }
    if args.reference_diagonal_mm:
        report['distance_units_mm'] = f'scaled by reference diagonal = {args.reference_diagonal_mm} mm'
        report['result_to_reference_mm'] = scaled(forward, args.reference_diagonal_mm)
        report['reference_to_result_mm'] = scaled(backward, args.reference_diagonal_mm)

    report_path = out_dir / 'compare_reference.json'
    dump_json(report_path, report)

    print('direction\tmean\tmedian\trms\tp95\tmax\twithin_1pct')
    for name, stats in (('result->reference', forward), ('reference->result', backward)):
        print(f"{name}\t{stats['mean']:.5f}\t{stats['median']:.5f}\t{stats['rms']:.5f}\t"
              f"{stats['p95']:.5f}\t{stats['max']:.5f}\t{stats['within_1pct_diag']:.4f}")
    print(f"alignment fitness={alignment['fitness']:.4f} rmse={alignment['rmse']:.6f} ({align_time:.1f}s)")
    print(f'written: {report_path}')


if __name__ == '__main__':
    main()
