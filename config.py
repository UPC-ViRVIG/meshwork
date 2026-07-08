# config.py
import os
import platform
import yaml
from pathlib import Path

DEFAULT_CONFIG = {
    "gui": {
        "theme": "dark",
        "window": {
            "width": 1280,
            "height": 720,
            "maximized": True
        },
        "panels": {
            "tools": {"visible": True, "width": 250},
            "scene": {"visible": True, "width": 250},
            "material": {"visible": False, "width": 300},
            "render": {"visible": False, "width": 300}
        },
        "script": {
            "height": 150,
            "font_size": 10,
            "auto_save": True,
            "max_console_lines": 1000,
            "syntax_check_enabled": True
        },
    },
    "core": {
        "temp_dir": "~/.meshwork/temp",
        "undo_levels": 32,
        "preview_quality": "medium",
        "auto_sync": True
    },
    "comm": {
        "socket_path": "/tmp/meshwork_blender.sock",
        "timeout": 30,
        "buffer_size": 1048576,
        "compression": True,
        "grpc": {
            "max_message_size_mb": 1000,
            "keepalive_time_ms": 30000,
            "keepalive_timeout_ms": 10000,
            "keepalive_permit_without_calls": True,
            "connection_timeout_ms": 60000,
            "retry_attempts": 3
        }
    },
    "server": {
        "services": {
            "blender": "unix:.runtime/socks/blender.sock",
            "colmap": "unix:.runtime/socks/colmap.sock",
            "alicevision": "unix:.runtime/socks/alicevision.sock"
        }
    },
    "reconstruction": {
        "quality_levels": ["fast", "balanced", "quality"],
        "default_tool": "colmap",
        "default_quality": "balanced",
        "default_output_type": "point_cloud",
        "colmap": {
            "quality_levels": {
                "fast": {
                    "max_image_size": 1600,
                    "max_features": 4096,
                    "max_num_matches": 8192,
                    "num_threads": 4,
                    "resolution_level": 4,
                    "max_resolution": 480,
                    "number_views": 2,
                    "densify_iters": 1,
                    "densify_geometric_iters": 0,
                    "densify_sub_resolution_levels": 0,
                    "densify_max_threads": 4,
                    "refine_scales": 1,
                    "refine_decimate": 10,
                    "texmesh_resolution_level": 2
                },
                "balanced": {
                    "max_image_size": 1600,
                    "max_features": 8192,
                    "max_num_matches": 16384,
                    "num_threads": 4,
                    "resolution_level": 3,
                    "max_resolution": 1600,
                    "number_views": 3,
                    "densify_iters": 2,
                    "densify_geometric_iters": 1,
                    "densify_sub_resolution_levels": 1,
                    "densify_max_threads": 2,
                    "refine_scales": 2,
                    "refine_decimate": 10,
                    "texmesh_resolution_level": 1
                },
                "quality": {
                    "max_image_size": 2048,
                    "max_features": 16384,
                    "max_num_matches": 32768,
                    "num_threads": 4,
                    "resolution_level": 2,
                    "max_resolution": 1600,
                    "number_views": 3,
                    "densify_iters": 3,
                    "densify_geometric_iters": 1,
                    "densify_sub_resolution_levels": 2,
                    "densify_max_threads": 2,
                    "refine_scales": 2,
                    "refine_decimate": 15,
                    "texmesh_resolution_level": 1
                }
            }
        },
        "alicevision": {
            "quality_levels": {
                "fast": {
                    "feature_density": "low",
                    "max_features_per_image": 4000,
                    "depth_downscale": 6,
                    "max_tcams": 6,
                    "texture_size": 2048,
                    "max_input_points": 2000000,
                    "geometric_error_threshold": 1.0,
                    "distance_ratio": 0.8,
                    "max_reprojection_error": 4.0
                },
                "standard": {
                    "feature_density": "normal",
                    "max_features_per_image": 8000,
                    "depth_downscale": 4,
                    "max_tcams": 10,
                    "texture_size": 4096,
                    "max_input_points": 5000000,
                    "geometric_error_threshold": 0.5,
                    "distance_ratio": 0.8,
                    "max_reprojection_error": 4.0
                },
                "high": {
                    "feature_density": "high",
                    "max_features_per_image": 15000,
                    "depth_downscale": 2,
                    "max_tcams": 15,
                    "texture_size": 8192,
                    "texture_downscale": 2,
                    "max_input_points": 20000000,
                    "geometric_error_threshold": 0.0,
                    "distance_ratio": 0.8,
                    "max_reprojection_error": 2.0
                }
            }
        }
    },
    "logging": {
        "level": "INFO",
        "file": "~/.meshwork/logs/app.log",
        "max_size": 10485760,
        "backup_count": 5
    }
}

class Config:
    def __init__(self, config_file=None):
        self.config_file = config_file or Path.home() / ".meshwork" / "config.yaml"
        self.config = DEFAULT_CONFIG.copy()
        self.load()
        self._update_platform_settings()

    def _update_platform_settings(self):
        if platform.system() == "Windows":
            self.config["comm"]["socket_path"] = r"\\.\pipe\meshwork_blender"
            base_dir = Path.home() / "Documents" / "Meshwork"
            self.config["core"]["temp_dir"] = str(base_dir / "temp")
            self.config["logging"]["file"] = str(base_dir / "logs" / "app.log")

    def load(self):
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                loaded_config = yaml.safe_load(f)
            self._update_dict(self.config, loaded_config)

    def _update_dict(self, target, source):
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._update_dict(target[key], value)
            else:
                target[key] = value

    def save(self):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            yaml.dump(self.config, f, indent=2)

    def get(self, section, key=None, default=None):
        if key is None:
            return self.config.get(section, default)
        return self.config.get(section, {}).get(key, default)

    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value

    def get_service_address(self, service_name: str) -> str:
        services = self.config.get("server", {}).get("services", {})
        return services.get(service_name, "localhost")

    def create_dirs(self):
        temp_dir = Path(self.get("core", "temp_dir", "")).expanduser()
        log_file = Path(self.get("logging", "file", "")).expanduser()
        temp_dir.mkdir(parents=True, exist_ok=True)
        log_file.parent.mkdir(parents=True, exist_ok=True)

_config_instance = None

def get_config():
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance