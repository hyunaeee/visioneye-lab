# RT-DETRv2-S 준비 기록

2026-09-21. 공식 COCO 체크포인트를 사용하는 ResNet18-vd·640·FP32 검출 어댑터를 준비했다. GPU 추론과 전체 영상 실험은 공통 실행기가 담당한다.

## 실행 인터페이스

- Python: `work/robustness-2026-09-21/rtdetr/env/Scripts/python.exe -B`.
- Module: `work/robustness-2026-09-21/rtdetr_adapter.py`.
- Constructor: `DetectorAdapter(device='cuda:0', model_path=None)`.
- `process(frame)`: H×W×3 uint8 BGR 입력 → 원본 픽셀 `xyxy`, float `confidence`, `track_id: None` 목록.
- `reset()`: 상태가 없는 검출기의 no-op. 추적·출입 판정·GPU 동기화는 공통 실행기의 책임이다.
- `metadata`: 모델·설정·가중치·어댑터 해시, 클래스·전처리·정밀도·라이선스. 개발 PC 절대 경로를 포함하지 않는다.

## 고정 자료

| 항목 | 값 |
|---|---|
| 공식 repository | https://github.com/lyuwenyu/RT-DETR |
| Code revision | `29320b6fd828f8e0987a71426cf2d961b09dfed7` |
| Config | `rtdetrv2_pytorch/configs/rtdetrv2/rtdetrv2_r18vd_120e_coco.yml` |
| Config SHA-256 | `3fc6fda05f01ac16a90cf4116bd3793682fa780979ac37b09f459a66bd21cc54` |
| 공식 checkpoint | [rtdetrv2_r18vd_120e_coco_rerun_48.1.pth](https://github.com/lyuwenyu/storage/releases/download/v0.2/rtdetrv2_r18vd_120e_coco_rerun_48.1.pth) |
| Release / asset | `v0.2` / `188285253` |
| Checkpoint bytes | 81,198,974 |
| Checkpoint SHA-256 | `2ace52184b620204004509b72752ac7bfe64aadaf7fc1d076b18df8ab5a5c77e` |

공식 README의 RT-DETRv2-S 행이 위 설정·checkpoint를 연결한다. 파일명 48.1은 제공자가 붙인 벤치마크 이름이며 이 프로젝트에서 측정한 정확도가 아니다. 체크포인트의 `ema.module`을 `torch.load(weights_only=True)`로 읽고 strict load한 뒤 공식 deploy 변환을 적용한다. 완전한 가중치를 로드하므로 초기 생성 단계의 `PResNet.pretrained`만 False로 설정해 별도 ImageNet 초기값 다운로드를 생략한다. 아키텍처와 학습된 파라미터는 바꾸지 않는다. config include 6개 파일의 해시는 `metadata-cpu.json`에 기록했다.

## 전처리·좌표·클래스

[공식 PyTorch 배포 예제](https://github.com/lyuwenyu/RT-DETR/blob/29320b6fd828f8e0987a71426cf2d961b09dfed7/rtdetrv2_pytorch/references/deploy/rtdetrv2_torch.py)에 맞춰 BGR→RGB PIL, bilinear 640×640 warp resize, ToTensor로 0–1 FP32 변환을 적용한다. letterbox와 ImageNet mean/std normalization은 없다. 배치 1, AMP·compile·TensorRT 없이 FP32로 실행한다.

공식 postprocessor는 normalized cxcywh를 xyxy로 바꾸고 `[width,height,width,height]`를 곱한다. 따라서 입력 원본 크기는 `[[width,height]]` 순서다. deploy mode는 COCO category로 remap하기 전 contiguous label을 반환하므로 **person은 label 0**, 원 COCO category는 1이다. 공식 category 사전으로 이 매핑을 확인한다.

focal top-300 결과에서 person과 confidence ≥ 0.1만 유지한다. 원본 프레임 바깥 좌표를 clip하고 비정상·퇴화 박스를 제외한다. 추가 NMS는 없다. 이 설정 차이는 다른 모델과의 비교 metadata에 보존한다.

## 환경·검증

기존 `work/.venv`를 변경하지 않았다. 별도 env의 `.pth`가 기존 Torch·torchvision·NumPy 등을 읽으며 추가 의존성만 새 env에 설치했다. Python 3.12.14 / Torch 2.11.0+cu128 / torchvision 0.26.0+cu128 / NumPy 2.5.2이다. 추가 의존성 버전은 `requirements-local-lock.txt`, 전체 54개 visible package는 `environment-versions.json`에 기록했다.

`pip check`, 공식 코드 import, CPU 모델 생성, EMA strict checkpoint load, deploy 변환을 통과했다. `verify_cpu.py`는 실제 detector forward 대신 synthetic head를 공식 postprocessor에 넣어 1280×720 좌표 복원·RGB·정규화·person mapping·threshold·clip·빈 박스 제외·잘못된 입력·reset 계약을 검증했고 통과했다. 결과는 `validation.json`이다. 실제 detector forward, GPU smoke와 FPS 측정은 수행하지 않았다.

## 재준비 명령

프로젝트 루트 기준의 Windows PowerShell 명령이다. 기존 준비 폴더에는 clone·env 생성 명령을 반복하지 않는다. 새 코드 checkout에 적용한다.

```powershell
git -c http.sslBackend=openssl clone https://github.com/lyuwenyu/RT-DETR.git work/robustness-2026-09-21/rtdetr/repo
git -C work/robustness-2026-09-21/rtdetr/repo checkout --detach 29320b6fd828f8e0987a71426cf2d961b09dfed7
& 'work/.venv/Scripts/python.exe' -B work/robustness-2026-09-21/rtdetr/prepare_environment.py
& 'work/robustness-2026-09-21/rtdetr/env/Scripts/python.exe' -B work/robustness-2026-09-21/rtdetr/prepare_assets.py
& 'work/robustness-2026-09-21/rtdetr/env/Scripts/python.exe' -B work/robustness-2026-09-21/rtdetr/verify_cpu.py
```

`prepare_assets.py`는 공식 GitHub release의 이름·크기·고정 SHA-256을 확인한다. `assets.json`에 release ID·asset ID·URL을 남긴다. 토큰이나 로그인은 필요하지 않다.

## 라이선스와 범위

공식 repository는 [Apache-2.0](https://github.com/lyuwenyu/RT-DETR/blob/29320b6fd828f8e0987a71426cf2d961b09dfed7/LICENSE)을 제공하며 별도 checkpoint 라이선스 표시는 이 배포에서 확인되지 않았다. 원문 SHA-256은 환경 기록에 남겼다. 라이선스 고지와 외부 자료의 적용 조건은 유지한다.

이는 공식 사전학습 모델을 이용한 로컬 비교 준비다. 제공자 논문의 COCO AP나 T4 TensorRT FP16 FPS 재현이 아니다. 체크포인트·외부 repository·환경·캐시는 public Git에 게시하지 않는다.
