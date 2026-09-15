"""Repository-local runtime locations; no developer machine paths."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT
RUNTIME = Path(os.environ.get('VISIONEYE_EXPERIMENT_RUNTIME', HERE / '.runtime')).expanduser().resolve()


def configure_cache():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR', str(RUNTIME / 'ultralytics'))
    os.environ.setdefault('YOLO_AUTOINSTALL', 'false')
    os.environ.setdefault('HF_HOME', str(RUNTIME / 'hf-cache'))
    os.environ.setdefault('TORCH_HOME', str(RUNTIME / 'torch-cache'))


def public_path(value):
    path = Path(value).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name
