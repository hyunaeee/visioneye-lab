"""Pinned FP32 YOLO baselines and fixed-box tracker adapters.

Construct trackers sequentially: Ultralytics trackers share a global ID counter.
No model download, dependency installation, or GPU inference happens on import.
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PINNED_ULTRALYTICS = "8.4.150"
MODEL_FILES = {
    "yolo26n": ROOT / "outputs" / "visioneye" / "models" / "yolo26n.pt",
    "yolov8n": HERE / "models" / "yolov8n.pt",
    "yolo11n": HERE / "models" / "yolo11n.pt",
}
MODEL_NAMES = {"yolo26n": "YOLO26n", "yolov8n": "YOLOv8n", "yolo11n": "YOLO11n"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ultralytics():
    state = HERE / ".runtime"
    state.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ["YOLO_CONFIG_DIR"] = str(state)
    import ultralytics
    if ultralytics.__version__ != PINNED_ULTRALYTICS:
        raise RuntimeError(f"Expected Ultralytics {PINNED_ULTRALYTICS}, got {ultralytics.__version__}")
    ultralytics.settings.update({"sync": False})
    return ultralytics


def _frame_contract(frame):
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or
            frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 1):
        raise ValueError("frame must be a nonempty uint8 HWC BGR image")


class DetectorAdapter:
    def __init__(self, model="yolo26n", device="cuda:0", model_path=None):
        if model not in MODEL_FILES:
            raise ValueError(f"model must be one of {list(MODEL_FILES)}")
        package = _ultralytics()
        path = Path(model_path) if model_path is not None else MODEL_FILES[model]
        if not path.is_file():
            raise FileNotFoundError(f"Prepare the official weights before inference: {path.name}")
        self.device = str(device)
        self.model = package.YOLO(str(path), task="detect")
        if self.model.names.get(0) != "person":
            raise RuntimeError("Checkpoint class 0 is not COCO person")
        self.predict_options = dict(classes=[0], conf=0.1, imgsz=640, rect=False,
                                    batch=1, quantize=32, iou=0.7, max_det=300,
                                    nms=None, agnostic_nms=False, augment=False,
                                    device=self.device, verbose=False, save=False,
                                    stream=False)
        self.metadata = {
            "model": MODEL_NAMES[model], "model_key": model, "precision": "FP32",
            "imgsz": 640, "tensor_input_size_px": [640, 640], "rect": False,
            "batch": 1, "confidence": 0.1, "person_class": 0, "max_det": 300,
            "iou": 0.7, "nms_option": None, "end_to_end": False,
            "postprocess": "native one-to-many head and class-aware external NMS, IoU 0.7",
            "preprocess": "Ultralytics BGR to RGB, letterbox to 640x640, float32/255",
            "weights_file": path.name, "weights_sha256": sha256(path),
            "parameters_loaded": sum(p.numel() for p in self.model.model.parameters()),
            "device": self.device, "ultralytics_version": package.__version__,
            "adapter_sha256": sha256(__file__),
            "capacity_note": "Nano variants are not parameter-count or FLOP matched across model generations.",
        }

    def process(self, frame):
        _frame_contract(frame)
        result = self.model.predict(frame, **self.predict_options)[0]
        boxes = result.boxes.cpu().numpy()
        if len(boxes) and not np.all(boxes.cls == 0):
            raise RuntimeError("Non-person class returned from person-only inference")
        # Check the runtime precision, rather than just trusting a CLI flag.
        import torch
        if next(self.model.predictor.model.model.parameters()).dtype != torch.float32:
            raise RuntimeError("FP32 comparison silently used a different model precision")
        if self.model.predictor.model.end2end:
            raise RuntimeError("Common external-NMS comparison unexpectedly selected an end-to-end head")
        self.metadata["runtime_parameter_dtype"] = "float32"
        self.metadata["runtime_parameters_fused"] = sum(p.numel() for p in self.model.predictor.model.model.parameters())
        return [dict(xyxy=xyxy.tolist(), confidence=float(score), track_id=None)
                for xyxy, score in zip(boxes.xyxy, boxes.conf)]


class TrackerAdapter:
    """Retain every input box/score/order; attach IDs via upstream original index."""
    def __init__(self, kind, fps, device="0"):
        if kind not in {"bytetrack", "botsort", "tracktrack"}:
            raise ValueError("kind must be bytetrack, botsort, or tracktrack")
        if not math.isfinite(float(fps)) or float(fps) <= 0:
            raise ValueError("fps must be finite and positive")
        package = _ultralytics()
        from ultralytics.engine.results import Boxes
        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.trackers.bot_sort import BOTSORT
        from ultralytics.trackers.track_tracker import TRACKTRACK
        from ultralytics.utils import YAML
        package_root = Path(package.__file__).resolve().parent
        cfg_path = package_root / "cfg" / "trackers" / f"{kind}.yaml"
        cfg = YAML.load(cfg_path)
        native_cfg = copy.deepcopy(cfg)
        cfg["track_buffer"] = max(1, round(float(fps)))
        if kind != "bytetrack":
            cfg.update(with_reid=False, gmc_method="none", model="auto", device="cpu")
        implementation = {"bytetrack": (BYTETracker, "byte_tracker.py"),
                          "botsort": (BOTSORT, "bot_sort.py"),
                          "tracktrack": (TRACKTRACK, "track_tracker.py")}[kind]
        self.tracker = implementation[0](SimpleNamespace(**cfg))
        if getattr(self.tracker, "encoder", None) is not None:
            raise RuntimeError("ReID OFF experiment unexpectedly initialized an encoder")
        self._Boxes = Boxes
        self.frames_processed = 0
        self._metadata = {
            "kind": kind, "fps": float(fps), "requested_device": str(device),
            "tracker_compute": "CPU NumPy association; no ReID network",
            "ultralytics_version": package.__version__, "numpy_version": np.__version__,
            "native_config": native_cfg, "config": cfg,
            "config_overrides": {k: v for k, v in cfg.items() if native_cfg.get(k) != v},
            "max_lost_frames": getattr(self.tracker, "max_frames_lost", getattr(self.tracker, "max_time_lost", None)),
            "track_buffer_seconds": cfg["track_buffer"] / float(fps),
            "buffer_policy": "Common rounded one-second track buffer for all three trackers",
            "reid_enabled": False, "camera_motion_compensation": "none",
            "raw_detections_preserved": True, "raw_detection_index_validation": "strict",
            "loose_nms_recovery": False,
            "adapter_sha256": sha256(__file__), "tracker_yaml_sha256": sha256(cfg_path),
            "tracker_implementation_sha256": sha256(package_root / "trackers" / implementation[1]),
            "comparison_scope": "Pinned Ultralytics implementations on identical postprocessed boxes; native association thresholds; not full paper reproductions",
            "threshold_note": "ByteTrack/BoT-SORT high=.25 low=.1 new=.25 match=.8; TrackTrack high=.6 low=.25 new=.7 match=.7",
            "distinct_track_ids_are_people_count": False,
        }
        self.reset()

    @property
    def metadata(self):
        result = copy.deepcopy(self._metadata)
        result["frames_processed_since_reset"] = self.frames_processed
        return result

    def reset(self):
        self.tracker.reset()
        self.frames_processed = 0

    def process(self, frame, detections):
        _frame_contract(frame)
        preserved, data = [], []
        for detection in detections:
            box = np.asarray(detection["xyxy"], dtype=float)
            score = float(detection["confidence"])
            if box.shape != (4,) or not np.isfinite(box).all() or box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Each detection must have a finite xyxy box with positive area")
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError("Detection confidence must be finite in [0,1]")
            preserved.append(dict(xyxy=box.tolist(), confidence=score, track_id=None))
            data.append([*box.tolist(), score, 0.0])
        boxes = self._Boxes(np.asarray(data, dtype=np.float32).reshape((-1, 6)), orig_shape=frame.shape[:2])
        tracks = self.tracker.update(boxes, frame)
        seen_indices, seen_ids = set(), set()
        for row in tracks:
            row = np.asarray(row)
            if row.shape != (8,) or not np.isfinite(row).all():
                raise RuntimeError("Unexpected tracker row: expected finite [xyxy,id,score,cls,original_index]")
            raw_index, raw_id = float(row[-1]), float(row[4])
            if not raw_index.is_integer() or not raw_id.is_integer():
                raise RuntimeError("Tracker original index and ID must be integral")
            index, track_id = int(raw_index), int(raw_id)
            if not 0 <= index < len(preserved) or track_id <= 0:
                raise RuntimeError("Invalid tracker original index or nonpositive ID")
            if index in seen_indices or track_id in seen_ids:
                raise RuntimeError("Duplicate original-index or track-ID assignment")
            if float(row[6]) != 0.0:
                raise RuntimeError("Tracker changed COCO person class")
            seen_indices.add(index)
            seen_ids.add(track_id)
            preserved[index]["track_id"] = track_id
        self.frames_processed += 1
        return preserved
