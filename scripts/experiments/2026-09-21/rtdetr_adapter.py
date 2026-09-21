"""Official RT-DETRv2-S/R18vd detector for the fixed VisionEye comparison.

Run using an environment prepared from this folder's requirements. The adapter is stateless and emits
person boxes in original BGR frame pixels; the common runner owns tracking.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
import torch
import torchvision.transforms as T
import yaml

BASE = Path(__file__).resolve().parent / '.runtime' / 'rtdetr'
REPO = BASE / 'repo'
CODE = REPO / 'rtdetrv2_pytorch'
CONFIG = CODE / 'configs/rtdetrv2/rtdetrv2_r18vd_120e_coco.yml'
CODE_REVISION = '29320b6fd828f8e0987a71426cf2d961b09dfed7'
CHECKPOINT = 'rtdetrv2_r18vd_120e_coco_rerun_48.1.pth'
CHECKPOINT_SHA256 = '2ace52184b620204004509b72752ac7bfe64aadaf7fc1d076b18df8ab5a5c77e'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _config_hashes(path, collected=None):
    collected = {} if collected is None else collected
    path = Path(path).resolve()
    name = path.relative_to(CODE).as_posix()
    if name in collected:
        return collected
    collected[name] = _sha(path)
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    for include in config.get('__include__', []):
        _config_hashes(path.parent / include, collected)
    return collected


class DetectorAdapter:
    def __init__(self, device='cuda:0', model_path=None):
        self.device = torch.device(device)
        checkpoint = Path(model_path).expanduser().resolve() if model_path else BASE / 'weights' / CHECKPOINT
        digest = _sha(checkpoint)
        if digest != CHECKPOINT_SHA256:
            raise ValueError('Use the fixed official RT-DETRv2-S 48.1 checkpoint')
        if str(CODE) not in sys.path:
            sys.path.insert(0, str(CODE))
        if 'src' in sys.modules:
            origin = Path(sys.modules['src'].__file__).resolve()
            if not origin.is_relative_to(CODE):
                raise RuntimeError('Another repository owns module src; run each detector in a separate process')
        from src.core import YAMLConfig
        from src.data.dataset import mscoco_category2name, mscoco_category2label

        assert mscoco_category2name[1] == 'person'
        assert mscoco_category2label[1] == 0
        cfg = YAMLConfig(str(CONFIG))
        assert cfg.yaml_cfg['num_classes'] == 80
        assert cfg.yaml_cfg['eval_spatial_size'] == [640, 640]
        assert cfg.yaml_cfg['PResNet']['depth'] == 18
        # The complete checkpoint supplies backbone weights. Avoid an unrelated
        # ImageNet initialization download before the strict full-model load.
        cfg.yaml_cfg['PResNet']['pretrained'] = False
        state = torch.load(checkpoint, map_location='cpu', weights_only=True)
        state_dict = state['ema']['module']
        self.model = cfg.model
        self.model.load_state_dict(state_dict, strict=True)
        self.model = self.model.deploy().to(self.device).float().eval()
        self.model.requires_grad_(False)
        self.postprocessor = cfg.postprocessor.deploy().to(self.device)
        self.threshold = 0.1
        self.transform = T.Compose([T.Resize((640, 640)), T.ToTensor()])
        self.metadata = {
            'model': 'RT-DETRv2-S', 'backbone': 'ResNet18-vd',
            'adapter': 'rtdetr_adapter.DetectorAdapter',
            'code_repo': 'https://github.com/lyuwenyu/RT-DETR',
            'code_revision': CODE_REVISION,
            'checkpoint': CHECKPOINT,
            'checkpoint_url': 'https://github.com/lyuwenyu/storage/releases/download/v0.2/' + CHECKPOINT,
            'checkpoint_sha256': digest, 'checkpoint_state': 'ema.module',
            'config': CONFIG.relative_to(REPO).as_posix(),
            'config_sha256': _sha(CONFIG), 'config_include_sha256': _config_hashes(CONFIG),
            'config_override': 'PResNet.pretrained=False before strict complete checkpoint load; no model architecture change',
            'adapter_sha256': _sha(__file__), 'license': 'Apache-2.0',
            'device': str(self.device), 'input_size': [640, 640],
            'batch_size': 1, 'precision': 'FP32', 'confidence': self.threshold,
            'preprocessing': 'Official PIL RGB bilinear Resize 640x640 (warp), ToTensor float32 /255; no ImageNet normalization',
            'preprocessing_source': 'rtdetrv2_pytorch/references/deploy/rtdetrv2_torch.py',
            'person_class': 0, 'person_coco_category_id': 1,
            'label_mapping': 'Postprocessor deploy returns contiguous COCO labels before category remapping; label 0 is person',
            'box_format': 'Original-image xyxy pixels; official normalized cxcywh-to-xyxy multiplied by [width,height,width,height]',
            'postprocessing': 'Official focal top-300; class 0; confidence>=0.1; frame bounds clipping; no additional NMS',
            'strict_checkpoint_load': True, 'deploy_conversion': True,
            'compile': False, 'autocast': False, 'tracking': 'None; common runner owns tracking',
            'torch_version': torch.__version__, 'torchvision_version': importlib.metadata.version('torchvision'),
            'scope': 'Official pretrained checkpoint comparison; not a reproduction of paper COCO AP or TensorRT T4 FPS',
        }

    def reset(self):
        """Detector-only adapter: no frame history or track state to reset."""
        return None

    @torch.inference_mode()
    def process(self, frame):
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('Expected HxWx3 uint8 BGR frame')
        height, width = frame.shape[:2]
        if min(height, width) < 1:
            raise ValueError('Frame must not be empty')
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        tensor = self.transform(image).unsqueeze(0).to(self.device)
        original_size = torch.tensor([[width, height]], device=self.device)
        labels, boxes, scores = self.postprocessor(self.model(tensor), original_size)
        keep = (labels[0] == 0) & (scores[0] >= self.threshold)
        boxes = boxes[0][keep].float().cpu().numpy()
        scores = scores[0][keep].float().cpu().numpy()
        output = []
        for box, confidence in zip(boxes, scores):
            if not np.isfinite(box).all() or not np.isfinite(confidence):
                continue
            box[[0, 2]] = np.clip(box[[0, 2]], 0, width)
            box[[1, 3]] = np.clip(box[[1, 3]], 0, height)
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            output.append({'xyxy': box.tolist(), 'confidence': float(confidence), 'track_id': None})
        return output
