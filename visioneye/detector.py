"""One detector pass, retaining even unconfirmed boxes for privacy masking."""
from pathlib import Path
from types import SimpleNamespace
import os


class PersonTracker:
    def __init__(self, model: str, device: str = "auto", imgsz: int = 640,
                 confidence: float = 0.1, fps: float = 30):
        state = Path(__file__).resolve().parent / ".runtime"
        state.mkdir(exist_ok=True)
        os.environ.setdefault("YOLO_CONFIG_DIR", str(state))
        os.environ.setdefault("YOLO_AUTOINSTALL", "false")
        from ultralytics import YOLO, settings
        from ultralytics.trackers.byte_tracker import BYTETracker
        import torch

        settings.update({"sync": False})
        self.device = ("0" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        if self.device != "cpu" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable. Install CUDA PyTorch with setup.ps1 or use --device cpu.")
        self.model = YOLO(model, task="detect")
        if self.model.names.get(0) != "person":
            raise ValueError("This app requires a COCO detector with class 0 named person.")
        self.tracker = BYTETracker(SimpleNamespace(
            track_high_thresh=0.25, track_low_thresh=0.1, new_track_thresh=0.25,
            track_buffer=max(1, round(fps)), match_thresh=0.8, fuse_score=True,
        ))
        self.imgsz = imgsz
        self.confidence = confidence

    def process(self, frame):
        result = self.model.predict(frame, classes=[0], conf=self.confidence,
                                    imgsz=self.imgsz, device=self.device,
                                    quantize=16 if self.device != "cpu" else 32, verbose=False,
                                    save=False)[0]
        boxes = result.boxes.cpu().numpy()
        detections = [dict(xyxy=xyxy.tolist(), track_id=None, confidence=float(conf))
                      for xyxy, conf in zip(boxes.xyxy, boxes.conf)]
        tracks = self.tracker.update(boxes, frame)
        # Ultralytics 8.4.150 returns xyxy, id, score, class, original_detection_index.
        # Keep raw boxes so tentative detections are masked before a track ID exists.
        for row in tracks:
            index = int(row[-1])
            if 0 <= index < len(detections):
                detections[index]["track_id"] = int(row[4])
        return detections
