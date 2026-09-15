# 비교 실험 재현

2026-09-15 실험은 AI 생성 영상 2개, 총 602프레임과 기존 원본 검수 이벤트 14개를 고정한 로컬 평가다. 공식 공개 가중치와 명시한 설정을 비교한다. 논문의 전체 벤치마크 재현, 실제 매장 검증, 모델 구조만의 공정 비교는 아니다.

[측정 결과 파일](../experiments/results/2026-09-15/), [고정 프로토콜](../scripts/experiments/protocol.json), [실행 코드](../scripts/experiments/compare.py), [전체 패키지 버전](../scripts/experiments/environment-versions.json)을 함께 보관한다. 공개 실행 코드는 최종 보존 코드에서 저장소 경로·환경 위치·출력 경로 정리를 반영한 복사본이다. 따라서 공개 runner의 SHA-256은 기존 실측 요약의 해시와 다르다. [해시 기록](../scripts/experiments/measured-source-hashes.json)은 측정 후 보존된 소스 스냅샷과 각 실행 요약에 실제 기록된 runner·tracker·protocol 해시를 구분한다. 초기 실행과 후반 실행의 소스 해시도 일부 다르므로 모든 실행이 단일 소스 버전이었다고 주장하지 않는다.

공개 경로 수정 후 Python/JSON 구문, CLI help, 두 영상 해시, ByteTrack CPU 박스 보존·빈 프레임·reset 계약, reference 14개 로딩을 확인했다. 검출·추적 `process`와 이벤트 매칭 함수의 AST는 최종 보존 코드와 동일하다. 공개 복사본으로 새 환경 설치와 전체 GPU 측정을 다시 실행하지는 않았다. 실측 결과는 앞서 사용한 환경의 기록이다.

## 준비 환경

실측: Windows AMD64, Python 3.12.14, RTX 4090, Torch 2.11.0+cu128, torchvision 0.26.0+cu128, Ultralytics 8.4.150. Python 3.12와 Git을 먼저 설치하고 저장소 루트에서 아래 명령을 실행한다. Linux/macOS 이식 또는 다른 GPU에서 같은 속도가 나온다는 의미는 아니다.

환경·모델·외부 코드·캐시는 `scripts/experiments/.runtime/`, 새 결과는 `runs/`에 생성되며 Git에서 제외된다. `VISIONEYE_EXPERIMENT_RUNTIME` 환경 변수로 runtime 위치를 바꿀 수 있다. 기본 YOLO 가중치는 `visioneye/models/yolo26n.pt`이다.

```powershell
py -3.12 scripts/experiments/prepare_environment.py base
py -3.12 scripts/experiments/prepare_environment.py rfdetr
py -3.12 scripts/experiments/prepare_environment.py deim
py -3.12 scripts/experiments/prepare_environment.py reid
```

준비 스크립트는 새 환경만 생성하며 기존 폴더를 덮어쓰지 않는다. 기본 환경에 CUDA Torch와 [기본 의존성](../scripts/experiments/requirements-base-lock.txt)을 설치한다. RF-DETR·DEIM은 별도 venv에서 기본 환경을 읽고 각 [RF-DETR](../scripts/experiments/requirements-rfdetr-lock.txt)·[DEIM](../scripts/experiments/requirements-deim-lock.txt) 추가 의존성만 설치한다. [ReID 의존성](../scripts/experiments/requirements-reid-lock.txt)은 별도 target으로 설치한다. 기존 환경의 NumPy·Torch·Ultralytics를 업그레이드하지 않는다. 설치에는 `--no-deps`와 전체 버전 고정 목록을 사용하고 `pip check`를 실행한다.

Python 실행기의 위치는 다음과 같다. 이후 예시에서 `$base`, `$rf`, `$deim`은 현재 셸에서만 쓰는 변수다.

```powershell
$base = 'scripts/experiments/.runtime/base-env/Scripts/python.exe'
$rf = 'scripts/experiments/.runtime/rfdetr-env/Scripts/python.exe'
$deim = 'scripts/experiments/.runtime/deim-env/Scripts/python.exe'
& $base -B scripts/download_model.py
& $base -B scripts/experiments/prepare_rfdetr.py
& $base -B scripts/experiments/prepare_deim.py
& $base -B scripts/experiments/prepare_reid_model.py
```

가중치는 저장소에 포함하지 않는다. 위 스크립트는 공식 URL에서 다운로드하고 아래 SHA-256을 검증한다. 파일이 바뀌면 중단하며 다른 가중치로 조용히 대체하지 않는다.

| 모델 | 공식 배포·고정 버전 | SHA-256 |
|---|---|---|
| YOLO26n | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0) | `9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef` |
| RF-DETR Small | [rfdetr 1.10.1의 공식 registry](https://github.com/roboflow/rf-detr/blob/1.10.1/src/rfdetr/assets/model_weights.py) | `d81979a9213a2109345158ce9232668df4c1ae52e9b8db3f2ec0a8cbad959b33` |
| DEIMv2-S | [공식 HF revision cf0540f](https://huggingface.co/Intellindust/DEIMv2_DINOv3_S_COCO/tree/cf0540f3f319bb8ecbe132624358a35a7beb86d5) | `fe545b150766b8761a696f7b1d92ea138fafe8e02a7398823e0c62d2a5867956` |
| YOLO26n ReID | [공식 ONNX](https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-reid.onnx) | `8529c383197ae4c468eda535d1b165f8b4162cf17bf5fbcff49c7cb6455bc0bb` |

DEIM 코드는 commit `1d2ca42171570c713e78fc6a766ec5104b7f4724`를 사용한다. paired `config.json`의 SHA-256은 `c815791122b6be862d5c5902b3557771bda640acd0ca21ca9999c540eb6e6853`이다. 가중치와 함께 게시된 `interaction_indexes=[5,8,11]`을 유지했으며 현재 S training YAML의 `[3,7,11]`과 차이를 metadata에 기록한다. 전처리는 공식 `tools/inference/torch_inf.py`와 S validation YAML의 ImageNet normalization을 따른다. 예시 HF notebook은 normalization을 생략한다. 결과를 본 뒤 설정을 선택하지 않았다.

## 고정 데이터와 실행

입력은 `web/assets/crowd-source.mp4`(361프레임)와 `web/assets/higgsfield-source.mp4`(241프레임)다. 둘 다 1280×720, 24fps이며 실행기가 프로토콜의 SHA-256과 프레임 수를 확인한다. 기존 원본 검수 구간은 `crowd-source-review.json`과 `higgsfield-summary.json`에서 읽는다.

검출 비교는 모델별 기본 해상도·정밀도를 유지한다: YOLO26n 640 FP16, RF-DETR Small 512 FP32, DEIMv2-S 640 FP32. confidence 0.1, person 클래스, 동일 ByteTrack·출입선·히스테리시스를 적용한다. 같은 FLOPs·해상도·정밀도로 맞춘 비교가 아니다.

아래 명령은 GPU를 동시에 사용하지 않도록 순서대로 실행한다. 각 모델·영상별 3회 반복, 매회 첫 프레임 5회 warmup 후 추적 상태를 초기화한다. 이미 존재하는 출력 폴더에는 쓰지 않으므로 재실행 시 `--output runs/새이름`을 지정한다.

```powershell
foreach ($clip in @('crowd', 'two-person')) {
  & $base -B scripts/experiments/compare.py --engine yolo --clip $clip
  & $rf -B scripts/experiments/compare.py --engine rfdetr --clip $clip
  & $deim -B scripts/experiments/compare.py --engine deim --clip $clip
}
```

추적 비교는 해당 영상의 YOLO26n 첫 반복 검출 박스·점수를 재사용한다. 검출을 다시 실행하지 않는다. 공통 입력은 post-NMS 검출이므로 TrackTrack의 추가 loose-NMS 복구는 제외한다. TrackTrack OFF/ON은 `with_reid`만 다르고 GMC는 고정 카메라에 맞춰 `none`이다. ByteTrack과 TrackTrack은 각각 문서화된 다른 기본 threshold를 사용하므로 두 tracker의 비교는 전체 설정 비교다. Ultralytics 구현 평가이며 TrackTrack 논문의 전체 재현이 아니다.

```powershell
foreach ($clip in @('crowd', 'two-person')) {
  foreach ($tracker in @('bytetrack', 'tracktrack', 'tracktrack-reid')) {
    & $base -B scripts/experiments/compare.py --engine yolo --tracker $tracker --clip $clip --cache "runs/yolo-bytetrack-$clip/rep01/tracks.jsonl" --output "runs/cache-$tracker-$clip"
  }
}
```

ReID는 onnxruntime-gpu 1.23.2의 CUDAExecutionProvider를 확인하며 조용한 CPU fallback은 실패 처리한다. PyTorch의 CUDA12/cuDNN9 DLL을 읽는다. 측정 ONNX의 입력은 dynamic shape이고, 실제 Ultralytics crop 크기 224는 metadata에 기록한다. 별도 re-identification 학습은 없다.

## 결과 해석

각 반복은 `summary.json`, `events.csv`, `tracks.jsonl`, 상위 폴더는 `aggregate.json`을 생성한다. CUDA 동기화 후 detector·tracker·counter·telemetry 지연의 p50/p95와 처리 FPS를 기록한다. 처리 FPS에는 영상 읽기·검출·추적·집계·telemetry가 포함되고 초기화·warmup·렌더링·비디오 인코딩은 제외된다. cached tracker FPS는 검출 시간이 제외되므로 전체 pipeline FPS와 직접 비교하지 않는다.

GPU 메모리는 PyTorch allocated/reserved와 100ms 간격 NVML 전체 장치 메모리를 구분한다. ONNX Runtime 사용량은 PyTorch 통계만으로 포착되지 않는다. NVML 값에는 디스플레이 등 다른 사용량도 포함되며 순간 최대치를 놓칠 수 있다.

이벤트는 동일 영상·방향·시간 구간 안에서 일대일 최대 매칭한다. 1차는 기존 검수 구간, 2차는 각 구간을 ±0.5초 확장한 결과를 각각 보존한다. 매칭 수의 분모는 reference event 수이며, 예측 이벤트 수와 양쪽 unmatched 수도 함께 기록한다. 이는 AI 원본 검수와의 방향·시간 일치율이다. 자동 매칭은 동일 인물인지 검증하지 않는다.

초기 실내 인원은 unknown이다. 내부 계산의 0은 산술 기준점이므로 occupancy를 실제 실내 인원으로 해석하지 않는다. distinct predicted ID 수는 사람 수가 아니며, ID가 줄었다는 이유만으로 우수한 tracker로 선정하지 않는다. 사람별 지속 ID·전체 프레임 박스·mask 정답과 사람 검수 합의가 없어 HOTA, IDF1, 사람 recall, segmentation accuracy를 계산하지 않는다. 2개 짧은 AI 영상의 결과를 다른 장소나 일반 CCTV로 일반화하지 않는다.

## 라이선스와 미실행 항목

[DEIMv2 License](https://github.com/Intellindust-AI-Lab/DEIMv2/blob/1d2ca42171570c713e78fc6a766ec5104b7f4724/LICENSE.md)는 비상업 연구·개인 실험·평가를 허용하며 상용 사용에는 별도 라이선스를 요구한다. RF-DETR의 사용 코드·모델 표기는 [공식 라이선스](https://github.com/roboflow/rf-detr/blob/1.10.1/LICENSE)를 따른다. YOLO·TrackTrack 구현과 ReID 자료는 [Ultralytics 라이선스](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)의 적용 범위를 확인한다. 프로젝트의 라이선스가 외부 자료의 라이선스를 대체하지 않는다.

SAM3.1은 [공식 revision](https://huggingface.co/facebook/sam3.1/tree/daa63191845a41281374e725f4c9e51c7a824460)의 체크포인트 요청이 HTTP 401로 거부돼 제외했다. 승인된 계정 접근이 필요하다. [공개 상태 기록](../scripts/experiments/sam-status.json)에는 모델 revision·HTTP 상태·이유만 남겼으며 실행 성능 수치는 없다.

공개 요약에는 개발 PC 절대 경로·토큰을 포함하지 않는다. 체크포인트, 외부 repository 전체, venv, site-packages, 캐시는 게시하지 않는다.
