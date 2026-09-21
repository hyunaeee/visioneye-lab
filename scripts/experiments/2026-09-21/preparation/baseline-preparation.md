# 기준 모델 준비 · 2026-09-21

Ultralytics **8.4.150**의 기존 환경을 사용했다. 패키지 설치·업데이트는 없으며 이 준비 단계에서 GPU 추론은 실행하지 않았다. 모델 출처·크기·SHA256·계약 검사 결과·전체 추적기 설정은 `baseline-preparation.json`에 기록했다.

## 실행 계약

```python
from baseline_adapter import DetectorAdapter, TrackerAdapter

detector = DetectorAdapter(model="yolov8n", device="cuda:0")
tracker = TrackerAdapter("bytetrack", fps=24, device="0")
raw = detector.process(frame)       # uint8 HWC BGR input
tracked = tracker.process(frame, raw)
```

검출기 선택: `yolo26n`, `yolov8n`, `yolo11n`. 추적기 선택: `bytetrack`, `botsort`, `tracktrack`. `reset()`은 프레임 이력과 ID를 초기화한다. 상위 구현의 전역 ID 카운터를 공유하므로 추적기 인스턴스는 순차 실행한다.

## 검출 설정

세 모델 모두 FP32, batch 1, 실제 입력 640×640, `rect=False`, COCO person 0, confidence 0.1, IoU 0.7, max_det 300, 증강 OFF다. COCO 사전학습 가중치는 공식 [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0)에서 내려받고 SHA256으로 고정했다. 기존 YOLO26n 파일은 앞선 실험의 해시와 일치함을 확인해 재사용했다.

이 버전의 `predict`는 **`nms=None`에서 one-to-many + 외부 NMS**를 사용한다. YOLO26n의 이름만으로 NMS-free를 가정하지 않는다. 세 모델의 실제 `backend.end2end=False`, runtime parameter dtype `float32`, 전처리 텐서 `(1, 3, 640, 640)`를 CPU에서 확인했다. NMS-free YOLO26을 비교하려면 별도 조건인 `nms=False`로 명시해야 하며 이번 조건에 포함하지 않는다.

| 모델 | 체크포인트 파라미터 수 | 실행 모델 파라미터 수 · fusion 후 |
|---|---:|---:|
| YOLO26n | 2,572,280 | 2,408,932 |
| YOLOv8n | 3,157,200 | 3,151,904 |
| YOLO11n | 2,624,080 | 2,616,248 |

`n`이라는 이름이 같아도 파라미터 수와 연산량이 같지 않다. 공식 문서의 참고 FLOPs는 [YOLOv8n 8.7G](https://docs.ultralytics.com/models/yolov8), [YOLO11n 6.5G](https://docs.ultralytics.com/models/yolo11), [YOLO26n 5.5G](https://docs.ultralytics.com/models/yolo26)이며, 문서의 실행 경로·fusion 기준에 종속된다. 특히 YOLO26 표는 NMS-free branch 제거/fusion 기준을 설명한다. 이 수치는 이번 실험에서 측정한 FLOPs가 아니다.

## 추적 설정

검출 캐시의 원본 박스·신뢰도·순서를 그대로 반환하고, 추적기의 `original_index`로 ID만 연결한다. 저신뢰도·미확정 검출을 결과에서 삭제하지 않는다. 분리된 low/high confidence 부분집합 인덱스를 전체 검출 인덱스로 오해하면 검사에서 실패한다. 중복 인덱스/ID, 소수 인덱스/ID, 범위 초과, 클래스 변경을 거부한다.

| 추적기 | high | low | new | match |
|---|---:|---:|---:|---:|
| ByteTrack | 0.25 | 0.10 | 0.25 | 0.80 |
| BoT-SORT | 0.25 | 0.10 | 0.25 | 0.80 |
| TrackTrack | 0.60 | 0.25 | 0.70 | 0.70 |

위 임계값은 설치된 버전의 기본값이며 평가 영상에 맞춰 조정하지 않는다. 모든 추적기에 `track_buffer=round(fps)`를 적용해 약 1초로 맞춘다. 24fps 입력의 실제 `max_frames_lost`/`max_time_lost`는 24다. 기존 실험의 TrackTrack 기본 buffer 30과 달라 새로 평가해야 한다.

BoT-SORT와 TrackTrack은 `with_reid=False`, `gmc_method='none'`이다. 고정 카메라 조건으로 BoT-SORT의 카메라 움직임 보정 이득은 평가하지 않는다. TrackTrack의 loose-NMS 검출 복구도 공통 검출 풀을 유지하기 위해 사용하지 않는다. 이는 Ultralytics 구현·해당 설정의 비교이며 각 논문의 전체 재현이 아니다.

## CPU 확인

```powershell
& work/.venv/Scripts/python.exe -B work/robustness-2026-09-21/baseline-preparation.py --download
& work/.venv/Scripts/python.exe -B work/robustness-2026-09-21/baseline-preparation.py --cpu-contract --cpu-model-smoke
```

세 추적기에 대해 원본 박스·점수 보존, 검출 순서 변경 후 ID 매핑, 저신뢰도 검출 보존, 입력 불변, 빈 프레임, reset 재현성을 확인했다. 잘못된 상위 출력 6가지씩 모두 거부했다. 기존 crowd 영상 첫 프레임에서 세 검출기 CPU 추론을 확인했으며, 이 smoke 프레임의 검출 개수는 성능평가로 사용하지 않는다. 검사 종료 시 CUDA 초기화 여부는 `False`였다.
