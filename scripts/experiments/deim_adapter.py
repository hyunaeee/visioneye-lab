"""DEIMv2-S detector-only adapter for the fixed VisionEye experiments.

Use .runtime/deim-env/Scripts/python.exe -B. The isolated environment
reads the existing CUDA Torch installation; it never upgrades that environment.
Official HF config is used with its paired safetensors checkpoint, rather than
mixing it with the currently different training YAML interaction indexes.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
from paths import RUNTIME, configure_cache, public_path

import cv2
import numpy as np
import torch
from PIL import Image
from safetensors.torch import load_model
from torchvision import transforms as T

ROOT = RUNTIME
REPO = ROOT / 'deim' / 'repo'
WEIGHTS = ROOT / 'deim' / 'weights'
CODE_REVISION = '1d2ca42171570c713e78fc6a766ec5104b7f4724'


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_model(config: dict) -> torch.nn.Module:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from engine.backbone import DINOv3STAs
    from engine.deim import HybridEncoder, DEIMTransformer
    from engine.deim.postprocessor import PostProcessor
    from engine.data.dataset.coco_dataset import mscoco_category2label, mscoco_category2name

    assert mscoco_category2name[1] == 'person'
    assert mscoco_category2label[1] == 0

    class OfficialHubModel(torch.nn.Module):
        # Same component naming as the author's hf_models.ipynb wrapper.
        def __init__(self):
            super().__init__()
            self.backbone = DINOv3STAs(**config['DINOv3STAs'])
            self.encoder = HybridEncoder(**config['HybridEncoder'])
            self.decoder = DEIMTransformer(**config['DEIMTransformer'])
            self.postprocessor = PostProcessor(**config['PostProcessor'])

        def forward(self, image, original_size):
            output = self.decoder(self.encoder(self.backbone(image)))
            return self.postprocessor(output, original_size)

    return OfficialHubModel()


class DetectorAdapter:
    """Real DEIMv2-S inference, BGR uint8 input and original-pixel person boxes."""

    def __init__(self, device='cuda:0', model_path=None):
        configure_cache()
        self.device = torch.device(device)
        self.model_path = Path(model_path).resolve() if model_path else WEIGHTS / 'model.safetensors'
        self.config_path = self.model_path.parent / 'config.json'
        if self.model_path.suffix != '.safetensors':
            raise ValueError('Use the official paired model.safetensors and config.json')
        config = json.loads(self.config_path.read_text(encoding='utf-8'))
        if config['DEIMTransformer']['eval_spatial_size'] != [640, 640]:
            raise ValueError('This experiment is fixed to native DEIMv2-S 640x640 input')
        self.model = _build_model(config)
        # The official Hub artifact deduplicates shared decoder.up/reg_scale
        # tensors. load_model validates those shared aliases instead of treating
        # them as missing weights, as a plain load_state_dict(load_file()) would.
        missing, unexpected = load_model(self.model, str(self.model_path), strict=True, device='cpu')
        if missing or unexpected:
            raise RuntimeError('Official checkpoint did not load strictly')
        self.model.eval()
        # Official DEIM.deploy() conversion, after strict training-state load.
        for module in self.model.modules():
            if hasattr(module, 'convert_to_deploy'):
                module.convert_to_deploy()
        self.model.postprocessor.deploy()
        self.model.to(self.device)
        self.model.requires_grad_(False)
        self.threshold = 0.1
        self.transforms = T.Compose([
            T.Resize((640, 640)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        self.metadata = {
            'model': 'DEIMv2-S',
            'adapter': 'deim_adapter.DetectorAdapter',
            'model_repo': 'Intellindust/DEIMv2_DINOv3_S_COCO',
            'model_revision': 'cf0540f3f319bb8ecbe132624358a35a7beb86d5',
            'code_repo': 'https://github.com/Intellindust-AI-Lab/DEIMv2',
            'code_revision': CODE_REVISION,
            'model_sha256': _sha256(self.model_path),
            'config_sha256': _sha256(self.config_path),
            'model_path': public_path(self.model_path),
            'config_source': 'Official HF config paired with checkpoint',
            'experiment_scope': 'Official published checkpoint comparison; not a reproduction of the paper benchmark',
            'config_difference': 'HF paired interaction_indexes=[5,8,11]; current repo S training YAML uses [3,7,11]. Paired HF value is retained.',
            'backbone': config['DINOv3STAs'],
            'device': str(self.device),
            'input_size': [640, 640],
            'preprocessing': 'BGR->RGB PIL, torchvision bilinear Resize 640x640 (warp), ToTensor, ImageNet normalize',
            'preprocessing_source': 'Official tools/inference/torch_inf.py and S validation YAML; the illustrative hf_models.ipynb omits Normalize',
            'dtype': 'float32',
            'threshold': self.threshold,
            'person_label': 0,
            'person_coco_category_id': 1,
            'label_mapping': 'PostProcessor.deploy returns contiguous COCO labels; person category 1 maps to label 0',
            'postprocessing': 'Official top-300 focal scores; person filter; score>=0.1; clip xyxy to original frame; no additional NMS',
            'deploy_conversion': True,
            'strict_checkpoint_load': True,
            'torch_version': torch.__version__,
            'torchvision_version': importlib.metadata.version('torchvision'),
            'safetensors_version': importlib.metadata.version('safetensors'),
        }

    @torch.inference_mode()
    def process(self, frame: np.ndarray) -> list[dict]:
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError('Expected an HxWx3 uint8 BGR frame')
        height, width = frame.shape[:2]
        if width == 0 or height == 0:
            raise ValueError('Frame cannot be empty')
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        tensor = self.transforms(image).unsqueeze(0).to(self.device)
        # The official postprocessor expects (width,height), not (height,width).
        original_size = torch.tensor([[width, height]], device=self.device)
        labels, boxes, scores = self.model(tensor, original_size)
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
