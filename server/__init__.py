# server/__init__.py
import sys as _sys
import importlib as _importlib
from pathlib import Path as _Path


def _ensure_protobuf():
    here = _Path(__file__).resolve().parent
    if (here / "meshwork_pb2.py").exists() and (here / "meshwork_pb2_grpc.py").exists():
        return
    try:
        from grpc_tools import protoc as _protoc
    except ImportError:
        return
    _protoc.main([
        "protoc",
        f"--proto_path={here}",
        f"--python_out={here}",
        f"--grpc_python_out={here}",
        str(here / "meshwork.proto"),
    ])


_ensure_protobuf()


def _alias_module(name: str):
    try:
        mod = _importlib.import_module(f".{name}", __name__)
        _sys.modules.setdefault(name, mod)
        return True
    except Exception:
        return False

for _name in [
    "meshwork_pb2",
    "meshwork_pb2_grpc",
    "utils",
    "exec_ops",
    "file_ops",
]:
    _alias_module(_name)

from .client_api import MeshWorkClient, ProgressReporter, OutputCapture, TextCapture

__all__ = [
    "MeshWorkClient",
    "ProgressReporter",
    "OutputCapture",
    "TextCapture",
]
