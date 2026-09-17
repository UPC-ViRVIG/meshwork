import argparse, json, os
import numpy as np
import open3d as o3d
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def unit_plane(model):
    n = np.asarray(model[:3], dtype=float)
    k = np.linalg.norm(n)
    return n / k, float(model[3]) / k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('result_dir')
    ap.add_argument('--out', default=None)
    ap.add_argument('--samples', type=int, default=260000)
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    ev_dir = os.path.join(a.result_dir, 'eval_plane')
    d = json.load(open(os.path.join(ev_dir, 'ablation_plane.json')))
    loss_path = os.path.join(ev_dir, 'object_loss.json')
    loss = json.load(open(loss_path)) if os.path.exists(loss_path) else None
    pc = o3d.io.read_point_cloud(os.path.join(a.result_dir, 'dense_points.ply'))
    P = np.asarray(pc.points)
    C = np.asarray(pc.colors) if pc.has_colors() else np.full((len(P), 3), 0.5)
    g = np.asarray(d['dataset']['gravity_direction'], dtype=float)
    g /= np.linalg.norm(g)
    up = -g
    margin = float(d['radial_profile']['margin'])
    ng, dg = unit_plane(d['radial_profile']['plane_model'])
    nr, dr = unit_plane(d['full_cloud_ransac']['plane_model'])
    ev = np.cross(ng, nr)
    ev /= np.linalg.norm(ev)
    e2 = up - (up @ ev) * ev
    e2 /= np.linalg.norm(e2)
    e1 = np.cross(e2, ev)
    X, Y = P @ e1, P @ e2
    cx, cy = np.median(X), np.median(Y)
    rx = np.percentile(np.abs(X - cx), 99.5)
    ry = np.percentile(np.abs(Y - cy), 99.5)
    xl = (cx - 1.05 * rx, cx + 1.05 * rx)
    yl = (cy - 1.05 * ry, cy + 1.05 * ry)
    rem_g = (P @ ng + dg) <= margin
    rem_r = (P @ nr + dr) <= margin
    idx = np.random.default_rng(a.seed).choice(len(P), min(a.samples, len(P)), replace=False)

    def label(key, rem):
        if loss is not None:
            return '%.1f%% of the object removed' % (100 * loss[key]['object_points_removed'])
        return '%.1f%% of the cloud removed' % (100 * rem.mean())

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 4.9))
    titles = ['(a) dense cloud with the two detected planes',
              '(b) gravity-guided cut, ' + label('radial_profile', rem_g),
              '(c) full-cloud RANSAC cut, ' + label('full_cloud_ransac', rem_r)]
    for ax, title, rem in zip(axes, titles, [None, rem_g, rem_r]):
        if rem is None:
            ax.scatter(X[idx], Y[idx], s=0.25, c=C[idx], marker='.', linewidths=0, rasterized=True)
        else:
            keep = idx[~rem[idx]]
            gone = idx[rem[idx]]
            ax.scatter(X[keep], Y[keep], s=0.25, c=C[keep], marker='.', linewidths=0, rasterized=True)
            ax.scatter(X[gone], Y[gone], s=0.25, c='#d62728', marker='.', linewidths=0, alpha=0.55, rasterized=True)
        ax.set_xlim(xl)
        ax.set_ylim(yl)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(title, fontsize=8.5)

    def line(ax, n, dd, style, text, off=0.0):
        a1, a2 = n @ e1, n @ e2
        if abs(a2) > 1e-6:
            xs = np.array(xl)
            ys = -(a1 * xs + dd - off) / a2
        else:
            xs = np.full(2, -(dd - off) / a1)
            ys = np.array(yl)
        ax.plot(xs, ys, style, lw=1.2, label=text)

    ax = axes[0]
    line(ax, ng, dg, 'b-', 'gravity-guided (support)')
    line(ax, ng, dg, 'b--', 'recommended margin', margin)
    line(ax, nr, dr, 'r-', 'full-cloud RANSAC')
    line(ax, nr, dr, 'r--', None, margin)
    ax.set_xlim(xl)
    ax.set_ylim(yl)
    ax.legend(fontsize=7, loc='lower left', framealpha=0.9)
    plt.tight_layout()
    out = a.out or os.path.join(ev_dir, 'plane_cuts.png')
    plt.savefig(out, dpi=a.dpi)
    print(out)


if __name__ == '__main__':
    main()
