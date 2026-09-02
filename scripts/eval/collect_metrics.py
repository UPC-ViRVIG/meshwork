import argparse
import json
from pathlib import Path

STAGE_COLUMNS = {
    'analyze_plane': [
        ('n_points', 'points'), ('plane_method', 'method'), ('gravity_source', 'gravity'),
        ('plane_gravity_alignment', 'align'), ('recommended_margin', 'margin'),
        ('mean_point_spacing', 'spacing'),
    ],
    'remove_plane': [
        ('input_points', 'in'), ('output_points', 'out'), ('retention_rate', 'retention'),
        ('method', 'method'), ('margin', 'margin'),
    ],
    'align_clouds': [
        ('fitness', 'fitness'), ('rmse', 'rmse'), ('cumulative_scale', 'scale'),
        ('init_method', 'init'), ('voxel_size', 'voxel'),
    ],
    'merge_clouds': [
        ('input.merged_points', 'in'), ('output.final_points', 'out'),
        ('output.reduction_percent', 'reduction_pct'),
    ],
    'generate_mesh': [
        ('statistics.input_points', 'in'), ('statistics.output_vertices', 'vertices'),
        ('statistics.output_triangles', 'triangles'), ('parameters.depth', 'depth'),
    ],
}


def lookup(data, dotted):
    current = data
    for part in dotted.split('.'):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def label_for(path):
    resolved = path.resolve()
    parts = [p for p in resolved.parts if p not in ('/', 'result')]
    return '/'.join(parts[-2:]) if len(parts) >= 2 else resolved.name


def load_records(dirs):
    rows = []
    for d in dirs:
        path = Path(d) / 'stage_metrics.jsonl'
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                record['dataset'] = label_for(Path(d))
                rows.append(record)
    return rows


def fmt(value):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.4g}'
    return str(value)


def render(rows, fmt_name):
    header = ['dataset', 'stage', 'object', 'elapsed_s', 'details']
    lines = []
    for r in rows:
        columns = STAGE_COLUMNS.get(r['stage'], [])
        metrics = r.get('metrics', {}) or {}
        details = ', '.join(f'{label}={fmt(lookup(metrics, key))}' for key, label in columns)
        lines.append([r['dataset'], r['stage'], str(r.get('object', '-')), f"{r['elapsed_s']:.1f}", details])
    if fmt_name == 'json':
        return json.dumps(rows, indent=2)
    if fmt_name == 'latex':
        out = ['\\begin{tabular}{lllrl}', '\\hline', ' & '.join(header) + ' \\\\', '\\hline']
        for line in lines:
            out.append(' & '.join(cell.replace('_', '\\_') for cell in line) + ' \\\\')
        out += ['\\hline', '\\end{tabular}']
        return '\n'.join(out)
    out = ['| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    for line in lines:
        out.append('| ' + ' | '.join(line) + ' |')
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dirs', nargs='+')
    parser.add_argument('--format', choices=['markdown', 'latex', 'json'], default='markdown')
    parser.add_argument('--last-per-stage', action='store_true')
    args = parser.parse_args()

    rows = load_records(args.dirs)
    if args.last_per_stage:
        latest = {}
        for r in rows:
            latest[(r['dataset'], r['stage'], r.get('object'))] = r
        rows = list(latest.values())
    print(render(rows, args.format))


if __name__ == '__main__':
    main()
