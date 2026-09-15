from pathlib import Path
import hashlib, os
ROOT=Path(__file__).resolve().parents[2]
from paths import configure_cache
configure_cache()

class DetectorAdapter:
    def __init__(self,device='cuda:0',model_path=None):
        import torch
        from ultralytics import YOLO,settings
        settings.update({'sync':False})
        self.device=device
        path=Path(model_path or ROOT/'visioneye'/'models'/'yolo26n.pt')
        self.model=YOLO(str(path),task='detect')
        assert self.model.names[0]=='person'
        self.metadata={'model':'YOLO26n','imgsz':640,'precision':'FP16','confidence':0.1,'person_class':0,'weights_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'preprocess':'Ultralytics BGR letterbox','device':device}
    def process(self,frame):
        result=self.model.predict(frame,classes=[0],conf=0.1,imgsz=640,device=self.device,quantize=16,verbose=False,save=False)[0]
        boxes=result.boxes.cpu().numpy()
        return [dict(xyxy=xyxy.tolist(),confidence=float(conf),track_id=None) for xyxy,conf in zip(boxes.xyxy,boxes.conf)]
