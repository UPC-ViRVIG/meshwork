import argparse, glob, json, os
import numpy as np, open3d as o3d
from PIL import Image

def load_cameras(result_dir):
    cam = [l.split() for l in open(os.path.join(result_dir, 'cameras.txt')) if not l.startswith('#')][0]
    assert cam[1] == 'PINHOLE', cam
    W, H = int(cam[2]), int(cam[3]); fx, fy, cx, cy = map(float, cam[4:8])
    imgs = {}
    for l in open(os.path.join(result_dir, 'images.txt')):
        if l.startswith('#'): continue
        p = l.split()
        if len(p) >= 10 and p[-1].lower().endswith(('.jpg', '.jpeg', '.png')):
            w, x, y, z = map(float, p[1:5]); t = np.array(list(map(float, p[5:8])))
            R = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                          [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                          [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
            imgs[p[-1]] = (R, t)
    return (W, H, fx, fy, cx, cy), imgs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('result_dir'); ap.add_argument('masks_dir'); ap.add_argument('ablation_json')
    ap.add_argument('--mask-transpose', default=None); ap.add_argument('--min-views', type=int, default=3)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    (W, H, fx, fy, cx, cy), imgs = load_cameras(a.result_dir)
    masks = {os.path.basename(f).split('_mask')[0]: f for f in glob.glob(os.path.join(a.masks_dir, '*_mask.*'))}
    use = [n for n in imgs if os.path.splitext(n)[0] in masks]
    P = np.asarray(o3d.io.read_point_cloud(os.path.join(a.result_dir, 'dense_points.ply')).points); N = len(P)
    seen = np.zeros(N, int); inside = np.zeros(N, int)
    for n in use:
        R, t = imgs[n]; m = Image.open(masks[os.path.splitext(n)[0]])
        if a.mask_transpose: m = m.transpose(getattr(Image.Transpose, a.mask_transpose))
        assert m.size == (W, H), (m.size, (W, H))
        M = np.array(m.convert('L')) > 127
        X = P @ R.T + t; z = X[:, 2]; ok = z > 1e-6
        u = np.full(N, -1.0); v = np.full(N, -1.0)
        u[ok] = fx * X[ok, 0] / z[ok] + cx; v[ok] = fy * X[ok, 1] / z[ok] + cy
        inb = ok & (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
        seen[inb] += 1; inside[inb] += M[v[inb].astype(int), u[inb].astype(int)]
    obj = (seen >= a.min_views) & (inside >= 0.5 * seen)
    d = json.load(open(a.ablation_json)); g = np.array(d['dataset']['gravity_direction']); g /= np.linalg.norm(g)
    margin = d['radial_profile']['margin']; thr = d['dataset']['distance_threshold']
    report = {'points': N, 'images_with_mask': len(use), 'object_points': int(obj.sum()), 'object_fraction': float(obj.mean()), 'margin': margin}
    for k in ('radial_profile', 'full_cloud_ransac'):
        pa, pb, pc, pd = d[k]['plane_model']; n = np.array([pa, pb, pc]); nn = np.linalg.norm(n)
        sd = (P @ n + pd) / nn; inl = np.abs(sd) <= thr; removed = sd <= margin
        report[k] = {'gravity_alignment': float(abs(n @ g) / nn), 'inlier_fraction': float(inl.mean()),
                     'inliers_object_fraction': float(obj[inl].mean()), 'removed_fraction': float(removed.mean()),
                     'object_points_removed': float(removed[obj].mean()), 'background_points_removed': float(removed[~obj].mean()),
                     'kept_object_purity': float(obj[~removed].mean())}
    out = a.out or os.path.join(os.path.dirname(a.ablation_json), 'object_loss.json')
    json.dump(report, open(out, 'w'), indent=2); print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
