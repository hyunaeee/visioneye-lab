"""RF-DETR Small 1.10.1 detector for the fixed VisionEye comparison.

Run with .runtime/rfdetr-env/Scripts/python.exe. The separate environment reads
the base environment's site-packages through a .pth file without replacing them.
Input: OpenCV BGR uint8 HWC frames. Output: original-image xyxy pixel coordinates.
No tracker, counting, threshold tuning, torch.compile, ONNX or TensorRT is used.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
from pathlib import Path
from typing import Any
from paths import RUNTIME, configure_cache, public_path

import numpy as np


class DetectorAdapter:
    CONFIDENCE_THRESHOLD = 0.1
    INPUT_SIZE = 512
    PERSON_CLASS_ID = 1  # Native COCO category ID; NOT the flat class_names index 0.

    def __init__(self, device: str = 'cuda:0', model_path: str | Path | None = None):
        owned = RUNTIME
        configure_cache()
        weights = Path(model_path) if model_path is not None else owned / 'rfdetr-models' / 'rf-detr-small.pth'
        weights = weights.expanduser().resolve()
        if not weights.is_file():
            raise FileNotFoundError(f'Official RF-DETR Small checkpoint is missing: {weights}')

        # Keep any optional library cache inside the experiment's own environment.
        # Explicit user cache settings remain authoritative; weights use an explicit path.
        os.environ.setdefault('RF_HOME', str(owned / 'rfdetr-models'))
        os.environ.setdefault('HF_HOME', str(owned / 'rfdetr-env' / 'hf-cache'))
        os.environ.setdefault('TORCH_HOME', str(owned / 'rfdetr-env' / 'torch-cache'))

        import torch
        from rfdetr import RFDETRSmall
        from rfdetr.assets.coco_classes import COCO_CLASS_NAMES, COCO_CLASSES

        version = importlib.metadata.version('rfdetr')
        if version != '1.10.1':
            raise RuntimeError(f'This fixed adapter requires rfdetr==1.10.1, found {version}')
        if COCO_CLASSES.get(self.PERSON_CLASS_ID) != 'person':
            raise RuntimeError('Unexpected native COCO person mapping')

        self._torch = torch
        self._model = RFDETRSmall(pretrain_weights=str(weights), device=device, resolution=self.INPUT_SIZE)
        # The official COCO checkpoint uses a sparse 91-slot classifier while the
        # human-readable class_names list contains 80 names beginning with person.
        if list(self._model.class_names) != list(COCO_CLASS_NAMES):
            raise ValueError('This adapter expects official COCO weights, not a custom-class checkpoint')
        slots = int(self._model.model.model.class_embed.out_features)
        if slots <= len(COCO_CLASS_NAMES):
            raise ValueError('Expected sparse native COCO category IDs for the pretrained checkpoint')
        if int(self._model.model_config.resolution) != self.INPUT_SIZE:
            raise RuntimeError('RF-DETR Small native 512 resolution was not retained')

        digest = hashlib.sha256()
        with weights.open('rb') as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(block)
        self.metadata: dict[str, Any] = {
            'name': 'RF-DETR Small',
            'adapter': 'DetectorAdapter',
            'package': f'rfdetr=={version}',
            'torch': torch.__version__,
            'device': str(device),
            'model_path': public_path(weights),
            'model_sha256': digest.hexdigest(),
            'model_source': 'https://storage.googleapis.com/rfdetr/small_coco/checkpoint_best_regular.pth',
            'license': 'Apache-2.0',
            'confidence_threshold': self.CONFIDENCE_THRESHOLD,
            'threshold_tuned': False,
            'input_size': [self.INPUT_SIZE, self.INPUT_SIZE],
            'input_color': 'BGR uint8 HWC converted to contiguous RGB uint8 HWC',
            'preprocessing': 'Official predict: square bilinear resize, antialias=False, ImageNet normalization; no letterbox',
            'normalization_mean': [0.485, 0.456, 0.406],
            'normalization_std': [0.229, 0.224, 0.225],
            'box_format': 'xyxy in original input pixels; official postprocess restores original height and width',
            'person_class_id': self.PERSON_CLASS_ID,
            'class_id_scheme': 'Sparse native COCO category IDs; class_names[0] is not detector class_id 0',
            'classifier_slots': slots,
            'configured_num_classes': int(self._model.model.args.num_classes),
            'precision': 'float32 default pretrained PyTorch model',
            'backend': 'PyTorch eager, official predict, no compile/export/optimize_for_inference',
            'gradients': False,
            'tracking': 'None; root runner supplies the shared ByteTrack/counter',
        }

    def process(self, frame: np.ndarray) -> list[dict[str, Any]]:
        """Detect people without changing scale or generating tracking identities."""
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise TypeError('Expected an OpenCV uint8 NumPy frame')
        if frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 1:
            raise ValueError('Expected a nonempty HWC frame with three BGR channels')
        height, width = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        with self._torch.no_grad():
            detections = self._model.predict(
                rgb, threshold=self.CONFIDENCE_THRESHOLD, include_source_image=False
            )
        if len(detections.xyxy) == 0:
            return []
        if detections.class_id is None or detections.confidence is None:
            raise RuntimeError('RF-DETR did not return class IDs and confidence scores')

        people: list[dict[str, Any]] = []
        for box, score, class_id in zip(detections.xyxy, detections.confidence, detections.class_id):
            confidence = float(score)
            if int(class_id) != self.PERSON_CLASS_ID or not np.isfinite(confidence) or confidence < self.CONFIDENCE_THRESHOLD:
                continue
            xyxy = np.asarray(box, dtype=np.float64).copy()
            if xyxy.shape != (4,) or not np.isfinite(xyxy).all():
                continue
            # predict() already returns original-image coordinates. This is only
            # a bounds guard, never a 512-to-source rescaling.
            xyxy[[0, 2]] = np.clip(xyxy[[0, 2]], 0, width)
            xyxy[[1, 3]] = np.clip(xyxy[[1, 3]], 0, height)
            if xyxy[2] <= xyxy[0] or xyxy[3] <= xyxy[1]:
                continue
            people.append({'xyxy': xyxy.tolist(), 'confidence': confidence, 'track_id': None})
        return people
