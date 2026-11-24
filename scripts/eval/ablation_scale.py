import argparse
import hashlib
import platform
import time
from pathlib import Path

import numpy as np
import open3d as o3d

from _common import make_api, load_transform, dump_json, ALIGN_CONFIG


def run_variant(api, source_ply, target_ply, source_transform, target_transform, estimate_scale,
                seed=None):
    if seed is not None:
        o3d.utility.random.seed(seed)
    previous_flag = ALIGN_CONFIG['estimate_scale']
    t0 = time.perf_counter()
    try:
        ALIGN_CONFIG['estimate_scale'] = estimate_scale
        result = api._compute_alignment(source_ply, target_ply, dict(source_transform), dict(target_transform))
    finally:
        ALIGN_CONFIG['estimate_scale'] = previous_flag
    elapsed = time.perf_counter() - t0
    if result is None:
        return {'estimate_scale': estimate_scale, 'elapsed_s': elapsed, 'ok': False}
    registration = result['registration']
    return {
        'estimate_scale': estimate_scale,
        'elapsed_s': elapsed,
        'ok': True,
        'fitness': float(result['fitness']),
        'rmse': float(result['rmse']),
        'init_method': registration['init_method'],
        'voxel_size': registration['voxel_size'],
        'cumulative_scale': registration['cumulative_scale'],
        'levels': registration['levels'],
        'level_metric_semantics': registration['level_metric_semantics'],
        'evaluation': registration['evaluation'],
        'new_transform': {
            'location': result['location'].tolist(),
            'rotation': result['rotation'].tolist(),
            'scale': result['scale'].tolist(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source_ply', type=Path)
    parser.add_argument('target_ply', type=Path)
    parser.add_argument('--source-transform', type=Path, default=None)
    parser.add_argument('--target-transform', type=Path, default=None)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--seed', type=int, default=None,
                        help='Reset the Open3D seed before each variant; use one thread for repeatability.')
    args = parser.parse_args()

    api = make_api()
    source_transform = load_transform(args.source_transform)
    target_transform = load_transform(args.target_transform)
    results = {
        'source': str(args.source_ply.resolve()),
        'target': str(args.target_ply.resolve()),
        'input_transforms': {'source': source_transform, 'target': target_transform},
        'input_sha256': {
            'source': hashlib.sha256(args.source_ply.read_bytes()).hexdigest(),
            'target': hashlib.sha256(args.target_ply.read_bytes()).hexdigest(),
        },
        'environment': {'python': platform.python_version(), 'numpy': np.__version__,
                        'open3d': o3d.__version__},
        'seed': args.seed,
        'alignment_config': dict(ALIGN_CONFIG),
        'with_scale': run_variant(api, args.source_ply, args.target_ply,
                                  source_transform, target_transform, True, args.seed),
        'without_scale': run_variant(api, args.source_ply, args.target_ply,
                                     source_transform, target_transform, False, args.seed),
    }

    out_path = args.out or args.source_ply.resolve().parent / 'ablation_scale.json'
    dump_json(out_path, results)

    print('variant\tfitness\trmse\tcumulative_scale\tinit\telapsed_s')
    for key in ('with_scale', 'without_scale'):
        row = results[key]
        if not row['ok']:
            print(f'{key}\tfailed')
            continue
        print(f"{key}\t{row['fitness']:.4f}\t{row['rmse']:.6f}\t"
              f"{row['cumulative_scale']:.4f}\t{row['init_method']}\t{row['elapsed_s']:.1f}")
    print(f'written: {out_path}')


if __name__ == '__main__':
    main()
