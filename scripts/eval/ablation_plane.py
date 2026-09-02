import argparse
import time
from pathlib import Path

import numpy as np
import open3d as o3d
import yaml

from _common import make_api, dump_json, fmt


def plane_metrics(points, plane_model, gravity, threshold, margin):
    a, b, c, d = plane_model
    normal = np.array([a, b, c], dtype=float)
    norm = np.linalg.norm(normal)
    signed = (points @ normal + d) / norm
    return {
        'plane_model': [float(x) for x in plane_model],
        'inlier_ratio': float(np.mean(np.abs(signed) <= threshold)),
        'gravity_alignment': float(abs(np.dot(normal / norm, gravity))),
        'removed_fraction_at_margin': float(np.mean(signed <= margin)),
    }


def full_cloud_ransac(pcd, gravity, threshold, iterations):
    plane_model, inliers = pcd.segment_plane(
        distance_threshold=threshold, ransac_n=3, num_iterations=iterations)
    a, b, c, d = plane_model
    if np.dot(np.array([a, b, c]), gravity) > 0:
        a, b, c, d = -a, -b, -c, -d
    return [float(a), float(b), float(c), float(d)], len(inliers)


def write_stage1_yaml(path, plane_model, gravity, margin, method):
    data = {
        'version': '1.2',
        'plane_method': method,
        'plane_model': plane_model,
        'gravity_direction': [float(x) for x in gravity],
        'recommended_margin': float(margin),
    }
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def gt_background_mask(points, gt_background_ply, tolerance):
    gt = o3d.io.read_point_cloud(str(gt_background_ply))
    probe = o3d.geometry.PointCloud()
    probe.points = o3d.utility.Vector3dVector(points)
    dists = np.asarray(probe.compute_point_cloud_distance(gt))
    return dists <= tolerance, gt


def precision_recall(pred_removed, gt_background):
    tp = float(np.sum(pred_removed & gt_background))
    fp = float(np.sum(pred_removed & ~gt_background))
    fn = float(np.sum(~pred_removed & gt_background))
    precision = tp / (tp + fp) if tp + fp > 0 else float('nan')
    recall = tp / (tp + fn) if tp + fn > 0 else float('nan')
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else float('nan')
    return {'precision': precision, 'recall': recall, 'f1': f1}


def signed_distance(points, model):
    normal = np.array(model[:3], dtype=float)
    return (points @ normal + model[3]) / np.linalg.norm(normal)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_dir', type=Path)
    parser.add_argument('--margin', type=float, default=None)
    parser.add_argument('--method', choices=['dbscan', 'statistical'], default='dbscan')
    parser.add_argument('--ransac-iterations', type=int, default=1000)
    parser.add_argument('--gt-background', type=Path, default=None)
    parser.add_argument('--gt-tolerance', type=float, default=None)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    out_dir = (args.out or source_dir / 'eval_plane').resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    api = make_api()
    dense_ply = source_dir / 'dense_points.ply'
    pcd = o3d.io.read_point_cloud(str(dense_ply))
    points = np.asarray(pcd.points)
    bbox_diag = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    threshold = bbox_diag / 50

    results = {}

    rp_yaml = out_dir / 'stage1_radial_profile.yaml'
    t0 = time.perf_counter()
    ok, _ = api._process_analyze_sync(source_dir, rp_yaml)
    rp_time = time.perf_counter() - t0
    if not ok:
        raise SystemExit('radial-profile analysis failed')
    with open(rp_yaml) as f:
        rp = yaml.safe_load(f)
    gravity = np.asarray(rp['gravity_direction'], dtype=float)
    margin = args.margin if args.margin is not None else float(rp['recommended_margin'])

    results['radial_profile'] = {
        'analysis_time_s': rp_time,
        'plane_method': rp['plane_method'],
        'margin': margin,
        **plane_metrics(points, rp['plane_model'], gravity, threshold, margin),
    }

    t0 = time.perf_counter()
    fc_model, fc_inliers = full_cloud_ransac(pcd, gravity, threshold, args.ransac_iterations)
    fc_time = time.perf_counter() - t0
    fc_yaml = out_dir / 'stage1_full_cloud_ransac.yaml'
    write_stage1_yaml(fc_yaml, fc_model, gravity, margin, 'full_cloud_ransac')
    results['full_cloud_ransac'] = {
        'analysis_time_s': fc_time,
        'plane_method': 'full_cloud_ransac',
        'margin': margin,
        'ransac_inliers': int(fc_inliers),
        **plane_metrics(points, fc_model, gravity, threshold, margin),
    }

    if args.gt_background is not None:
        tolerance = args.gt_tolerance if args.gt_tolerance is not None else threshold * 0.5
        background, gt_pcd = gt_background_mask(points, args.gt_background, tolerance)
        gt_model, _ = full_cloud_ransac(gt_pcd, gravity, threshold, args.ransac_iterations)
        gt_normal = np.array(gt_model[:3]) / np.linalg.norm(gt_model[:3])
        centroid = points.mean(axis=0)
        offset_gt = float(signed_distance(centroid[None, :], gt_model)[0])
        for key in ('radial_profile', 'full_cloud_ransac'):
            model = results[key]['plane_model']
            normal = np.array(model[:3]) / np.linalg.norm(model[:3])
            offset_pred = float(signed_distance(centroid[None, :], model)[0])
            cos_angle = np.clip(abs(np.dot(normal, gt_normal)), -1.0, 1.0)
            results[key]['gt_normal_angle_deg'] = float(np.degrees(np.arccos(cos_angle)))
            results[key]['gt_offset_error_rel'] = float(abs(offset_pred - offset_gt) / bbox_diag)
            results[key].update(precision_recall(signed_distance(points, model) <= margin, background))
        results['ground_truth'] = {
            'file': str(args.gt_background.resolve()),
            'tolerance': tolerance,
            'background_fraction': float(np.mean(background)),
            'plane_model': gt_model,
        }

    for key, stage1 in (('radial_profile', rp_yaml), ('full_cloud_ransac', fc_yaml)):
        out_ply = out_dir / f'cleaned_{key}.ply'
        out_yaml = out_dir / f'removal_{key}.yaml'
        t0 = time.perf_counter()
        ok = api._process_remove_sync(dense_ply, stage1, margin, args.method, out_ply, out_yaml)
        results[key]['removal_time_s'] = time.perf_counter() - t0
        results[key]['removal_ok'] = bool(ok)
        if ok:
            with open(out_yaml) as f:
                removal = yaml.safe_load(f)
            results[key]['input_points'] = removal.get('input_points')
            results[key]['output_points'] = removal.get('output_points')
            results[key]['retention_rate'] = removal.get('retention_rate')

    results['dataset'] = {
        'source_dir': str(source_dir),
        'n_points': int(len(points)),
        'bbox_diagonal': bbox_diag,
        'distance_threshold': threshold,
        'gravity_direction': [float(x) for x in gravity],
        'outlier_method': args.method,
    }
    report_path = out_dir / 'ablation_plane.json'
    dump_json(report_path, results)

    columns = ['plane_method', 'analysis_time_s', 'inlier_ratio', 'gravity_alignment',
               'removed_fraction_at_margin', 'retention_rate', 'removal_time_s',
               'gt_normal_angle_deg', 'gt_offset_error_rel', 'precision', 'recall']
    print('variant\t' + '\t'.join(columns))
    for key in ('radial_profile', 'full_cloud_ransac'):
        row = results[key]
        print(key + '\t' + '\t'.join(fmt(row.get(c)) for c in columns))
    print(f'written: {report_path}')


if __name__ == '__main__':
    main()
