"""Download the official Ultralytics YOLO26n ReID ONNX asset, without inference."""
import hashlib
import json
from pathlib import Path
import urllib.request
from paths import RUNTIME

HERE = RUNTIME
MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-reid.onnx"
target = HERE / "models" / "yolo26n-reid.onnx"
target.parent.mkdir(parents=True, exist_ok=True)
if not target.exists():
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "VisionEye-reproducibility", "Cache-Control": "no-cache"})
    partial = target.with_suffix(".onnx.part")
    with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    partial.replace(target)
record = {
    "filename": target.name, "bytes": target.stat().st_size,
    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    "source": MODEL_URL, "official_documentation": "https://docs.ultralytics.com/modes/track/#enabling-re-identification-reid",
    "inference_performed": False,
}
if record['sha256'] != '8529c383197ae4c468eda535d1b165f8b4162cf17bf5fbcff49c7cb6455bc0bb':
    raise RuntimeError('Official ReID asset differs from the measured checkpoint')
(target.parent / "yolo26n-reid.provenance.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record, indent=2))
