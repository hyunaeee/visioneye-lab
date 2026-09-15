"""Download the pinned upstream model; no weights are bundled in this repository."""
from pathlib import Path
import hashlib
import os

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "visioneye" / "models" / "yolo26n.pt"
target.parent.mkdir(parents=True, exist_ok=True)
state = ROOT / "visioneye" / ".runtime"
state.mkdir(exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(state))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
from ultralytics import settings
from ultralytics.utils.downloads import attempt_download_asset
settings.update({"sync": False})
downloaded = Path(attempt_download_asset(str(target), repo="ultralytics/assets", release="v8.4.0"))
expected = "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
actual = hashlib.sha256(downloaded.read_bytes()).hexdigest()
if actual != expected:
    raise RuntimeError("Model SHA256 differs from the recorded experiment; do not treat this as an exact reproduction.")
print("Ready: visioneye/models/yolo26n.pt")
