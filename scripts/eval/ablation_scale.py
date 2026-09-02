import argparse
import time
from pathlib import Path

from _common import make_api, load_transform, dump_json, ALIGN_CONFIG


def run_variant(api, source_ply, target_ply, source_transform, target_transform, estimate_scale):
    ALIGN_CONFIG['estimate_scale'] = estimate_scale
    t0 = time.perf_counter()
    result = api._compute_alignment(source_ply, target_ply, dict(source_transform), dict(target_transform))
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
    args = parser.parse_args()

    api = make_api()
    source_transform = load_transform(args.source_transform)
    target_transform = load_transform(args.target_transform)
    default_flag = ALIGN_CONFIG['estimate_scale']

    results = {
        'source': str(args.source_ply.resolve()),
        'target': str(args.target_ply.resolve()),
        'with_scale': run_variant(api, args.source_ply, args.target_ply,
                                  source_transform, target_transform, True),
        'without_scale': run_variant(api, args.source_ply, args.target_ply,
                                     source_transform, target_transform, False),
    }
    ALIGN_CONFIG['estimate_scale'] = default_flag

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
