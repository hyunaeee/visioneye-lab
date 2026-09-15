"""Fixed-detection comparison of Ultralytics 8.4.150 trackers.

All variants consume the same post-NMS person detections and preserve every raw
box in their output. TrackTrack's loose-NMS recovery is intentionally unavailable
because it would alter that common detection pool. This compares Ultralytics'
implementation, not a full reproduction of the TrackTrack paper.

Construct and use one adapter at a time: upstream trackers share a global ID
counter. reset() keeps the ReID encoder while clearing temporal state and IDs.
"""
from __future__ import annotations

import hashlib
from importlib import metadata as package_metadata
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from paths import RUNTIME

import numpy as np


HERE = RUNTIME
DEFAULT_REID_MODEL = HERE / "models" / "yolo26n-reid.onnx"
REID_PACKAGES = HERE / "reid-packages"


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _add_isolated_packages():
    """Use only the dedicated additive dependencies; never install at runtime."""
    if not REID_PACKAGES.is_dir():
        raise RuntimeError("Missing runtime reid-packages; run prepare_environment.py reid first")
    forbidden = [name for name in ("numpy", "torch", "torchvision", "ultralytics", "cv2")
                 if (REID_PACKAGES / name).exists()]
    if forbidden:
        raise RuntimeError(f"Isolated ONNX target must not shadow shared packages: {forbidden}")
    if str(REID_PACKAGES) not in sys.path:
        sys.path.insert(0, str(REID_PACKAGES))


def _device_name(value):
    value = str(value)
    if value.isdecimal():
        return "cuda:" + value
    if value in {"cpu", "cuda"} or value.startswith("cuda:"):
        return "cuda:0" if value == "cuda" else value
    if value == "auto":
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    raise ValueError("device must be cpu, auto, a CUDA index, or cuda:<index>")


class TrackerAdapter:
    def __init__(self, kind, fps, device="0", reid_model=None):
        if kind not in {"bytetrack", "tracktrack", "tracktrack-reid"}:
            raise ValueError("Unknown tracker kind")
        if not math.isfinite(float(fps)) or float(fps) <= 0:
            raise ValueError("fps must be finite and positive")
        self.kind, self.fps = kind, float(fps)
        self.device = _device_name(device)
        self.frames_processed = 0
        self.reid_enabled = kind == "tracktrack-reid"
        model_path = Path(reid_model).resolve() if reid_model is not None else DEFAULT_REID_MODEL
        state = HERE / "ultralytics"
        state.mkdir(parents=True, exist_ok=True)
        os.environ["YOLO_AUTOINSTALL"] = "false"
        os.environ["YOLO_CONFIG_DIR"] = str(state)
        if self.reid_enabled:
            if not model_path.is_file() or model_path.suffix.lower() != ".onnx":
                raise ValueError("An explicit existing ONNX ReID model is required")
            _add_isolated_packages()

        import ultralytics
        import torch
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.trackers.track_tracker import TRACKTRACK
        from ultralytics.utils import YAML
        if ultralytics.__version__ != "8.4.150":
            raise RuntimeError("This comparison is pinned to Ultralytics 8.4.150")
        self._Boxes = Boxes
        package_root = Path(ultralytics.__file__).resolve().parent
        cfg_path = package_root / "cfg" / "trackers" / "tracktrack.yaml"
        if kind == "bytetrack":
            # Exactly the baseline settings used by VisionEye PersonTracker.
            cfg = dict(track_high_thresh=0.25, track_low_thresh=0.1,
                       new_track_thresh=0.25, track_buffer=max(1, round(self.fps)),
                       match_thresh=0.8, fuse_score=True)
            self.tracker = BYTETracker(SimpleNamespace(**cfg))
        else:
            cfg = YAML.load(cfg_path)
            # Both TrackTrack variants have identical values except with_reid.
            cfg.update(gmc_method="none", with_reid=self.reid_enabled,
                       model=str(model_path), device=self.device)
            if self.reid_enabled:
                import onnxruntime as ort
                if self.device.startswith("cuda"):
                    if not torch.cuda.is_available():
                        raise RuntimeError("CUDA requested but PyTorch CUDA is unavailable")
                    if "CUDAExecutionProvider" not in ort.get_available_providers():
                        raise RuntimeError("CUDA requested but isolated ONNX Runtime lacks CUDAExecutionProvider")
                    # Load the matching CUDA12/cuDNN9 DLLs shipped by existing PyTorch.
                    if hasattr(ort, "preload_dlls"):
                        ort.preload_dlls(directory=str(Path(torch.__file__).resolve().parent / "lib"))
            self.tracker = TRACKTRACK(SimpleNamespace(**cfg))

        encoder = getattr(self.tracker, "encoder", None)
        backend = getattr(encoder, "model", None)
        session = getattr(backend, "session", None)
        providers = session.get_providers() if session is not None else []
        if self.reid_enabled and self.device.startswith("cuda") and "CUDAExecutionProvider" not in providers:
            raise RuntimeError("ReID silently fell back to CPU; aborting this GPU experiment")
        self._metadata = {
            "kind": self.kind, "fps": self.fps, "requested_device": str(device),
            "reid_device": self.device if self.reid_enabled else None,
            "tracker_compute": "CPU NumPy association; ReID device recorded separately",
            "max_lost_frames": getattr(self.tracker, "max_frames_lost", getattr(self.tracker, "max_time_lost", None)),
            "config": cfg, "ultralytics_version": ultralytics.__version__,
            "numpy_version": np.__version__, "torch_version": torch.__version__,
            "adapter_sha256": _sha256(__file__),
            "tracker_implementation_sha256": _sha256(package_root / "trackers" /
                ("byte_tracker.py" if kind == "bytetrack" else "track_tracker.py")),
            "tracktrack_yaml_sha256": _sha256(cfg_path) if kind != "bytetrack" else None,
            "reid_enabled": self.reid_enabled,
            "reid_model": model_path.name if self.reid_enabled else None,
            "reid_model_sha256": _sha256(model_path) if self.reid_enabled else None,
            "reid_runtime_version": package_metadata.version("onnxruntime-gpu") if self.reid_enabled else None,
            "reid_providers": providers,
            "reid_provider_options": session.get_provider_options() if session is not None else {},
            "reid_inputs": [{"name": t.name, "shape": t.shape, "type": t.type}
                            for t in session.get_inputs()] if session is not None else [],
            "reid_outputs": [{"name": t.name, "shape": t.shape, "type": t.type}
                             for t in session.get_outputs()] if session is not None else [],
            "reid_fp16": bool(getattr(encoder, "fp16", False)),
            "reid_crop_size": int(encoder.imgsz) if encoder is not None else None,
            "reid_preprocess": "Ultralytics ReID crop, RGB, float32/255, bilinear resize; model static size overrides default" if self.reid_enabled else None,
            "association_precision": "upstream float32 detection arrays and native NumPy Kalman/association arithmetic",
            "raw_detections_preserved": True, "raw_detection_index_validation": "strict",
            "loose_nms_recovery": False,
            "comparison_scope": "Ultralytics TrackTrack implementation on fixed post-NMS detections; not full paper reproduction",
            "distinct_track_ids_are_people_count": False,
        }
        self.reset()

    @property
    def metadata(self):
        import copy
        result = copy.deepcopy(self._metadata)
        result["frames_processed_since_reset"] = self.frames_processed
        return result

    def reset(self):
        """Discard frame history and reset upstream IDs while retaining encoder."""
        self.tracker.reset()
        self.frames_processed = 0

    def process(self, frame, detections):
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a uint8 BGR image")
        if not frame.shape[0] or not frame.shape[1]:
            raise ValueError("frame cannot be empty")
        preserved = []
        data = []
        for detection in detections:
            box = np.asarray(detection["xyxy"], dtype=float)
            score = float(detection["confidence"])
            if box.shape != (4,) or not np.isfinite(box).all() or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Each raw detection needs one finite xyxy box with positive area")
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Detection confidence must be finite in [0,1]")
            preserved.append(dict(xyxy=box.tolist(), confidence=score, track_id=None))
            data.append([*box.tolist(), score, 0.0])  # class 0 is COCO person
        array = np.asarray(data, dtype=np.float32).reshape((-1, 6))
        boxes = self._Boxes(array, orig_shape=frame.shape[:2])
        # No predictor, second detector pass, native features or loose-NMS extras.
        tracks = self.tracker.update(boxes, frame)
        seen_indices, seen_ids = set(), set()
        for row in tracks:
            row = np.asarray(row)
            if row.shape != (8,) or not np.isfinite(row).all():
                raise RuntimeError("Unexpected upstream tracker row shape or nonfinite values")
            raw_index, raw_id = float(row[-1]), float(row[4])
            if not raw_index.is_integer() or not raw_id.is_integer():
                raise RuntimeError("Tracker index and ID must be integral")
            index, track_id = int(raw_index), int(raw_id)
            if not 0 <= index < len(preserved) or track_id < 0:
                raise RuntimeError("Tracker returned an invalid original detection index or track ID")
            if index in seen_indices or track_id in seen_ids:
                raise RuntimeError("Tracker returned duplicate detection-index or track-ID assignments")
            if int(row[6]) != 0:
                raise RuntimeError("Tracker changed the COCO person class")
            seen_indices.add(index)
            seen_ids.add(track_id)
            preserved[index]["track_id"] = track_id
        self.frames_processed += 1
        return preserved
