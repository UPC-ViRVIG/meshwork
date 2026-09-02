import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from logger import setup_logger
from core.pointcloud import PointcloudAPI, ALIGN_CONFIG, MERGE_CONFIG, MESH_CONFIG, _json_default


def make_api():
    setup_logger()
    return PointcloudAPI(signal_router=None, worker=None, parent=None)


def identity_transform():
    return {
        'location': np.zeros(3),
        'rotation': np.zeros(3),
        'scale': np.ones(3),
    }


def load_transform(path):
    if path is None:
        return identity_transform()
    with open(path) as f:
        data = json.load(f)
    return {
        'location': np.asarray(data.get('location', [0, 0, 0]), dtype=float),
        'rotation': np.asarray(data.get('rotation', [0, 0, 0]), dtype=float),
        'scale': np.asarray(data.get('scale', [1, 1, 1]), dtype=float),
    }


def dump_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2, default=_json_default)


def fmt(value):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.4f}'
    return str(value)
