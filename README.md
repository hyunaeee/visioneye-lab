# VisionEye Lab

[뷰어](https://visioneye-lab.vercel.app) · [포트폴리오](https://aengdo.vercel.app/work/visioneye/) · [다음 실험](docs/NEXT_EXPERIMENTS.md)

YOLO26n + ByteTrack로 사람을 추적하고 유한한 출입선의 IN/OUT을 집계하는 로컬 Python 앱과 정적 결과 뷰어입니다. 웹에서는 저장된 영상·CSV·JSON을 재생하며 모델을 실행하지 않습니다.

- `web/`: 배포할 정적 루트. HTML/CSS/JavaScript와 약 10MB의 예제 자산.
- `visioneye/`: 로컬 분석·보정·마스킹 앱과 41개 자동 테스트.
- `scripts/`: 모델 다운로드, 실제 검출 평가, 반투명 비교 영상 생성.
- [다음 비교 실험 후보](docs/NEXT_EXPERIMENTS.md): 추적·검출·마스크 비교 설계. 제안이며 미실행.
- `PUBLISH_FILES.json`: 게시 대상 파일 크기·SHA256 목록.

## 웹 실행

저장소 루트에서 `python scripts/serve.py --port 8000`을 실행하고 `http://127.0.0.1:8000`을 엽니다. Python 표준 라이브러리만 사용하며 영상 탐색에 필요한 HTTP Range 요청을 지원합니다. 기본 정적 루트는 `web/`입니다. 빌드·Node 의존성은 없습니다. Python 폴더는 웹에 배포하지 않습니다. Google Fonts를 불러오며 연결이 없으면 CSS 대체 글꼴을 사용합니다.

## Python 실행 · 테스트

개발 환경은 Windows, Python 3.12.14, RTX 4090 24GB, PyTorch 2.11.0+cu128입니다. 아래 PowerShell 명령은 저장소 루트 기준입니다. 모델·가상환경은 포함하지 않았습니다.

```powershell
.\visioneye\setup.ps1 -PythonPath python
# NVIDIA CUDA 대신 CPU만 사용하려면 위 명령에 -CPU 추가
$pyVision = '.\visioneye\.venv\Scripts\python.exe'
& $pyVision scripts/download_model.py
& $pyVision visioneye/app.py --demo --config visioneye/demo-config.json --headless --save-video
& $pyVision visioneye/app.py --source web/assets/crowd-source.mp4 --save-video
Push-Location visioneye
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
Pop-Location
```

`visioneye/Start Demo.cmd`, `Select Video.cmd`, `Calibrate Video.cmd`도 사용할 수 있습니다. 앱은 `visioneye/runs/`에 새 실행 폴더를 만듭니다. 실시간 입력은 `--source 0` 또는 지원 URL을 받지만 실제 카메라·RTSP 운용은 검증하지 않았습니다. macOS/Linux 설치·GUI·CUDA 환경은 이 저장소에서 검증하지 않았습니다.

직접 의존성은 고정되어 있고 `requirements-observed-cu128.txt`에는 실행 환경 전체 버전을 기록했습니다. CPU 결과나 다른 하드웨어의 속도·검출값이 같다고 보장하지 않습니다.

GitHub Actions는 Python 3.12에서 NumPy·OpenCV headless만 설치해 기존 41개 테스트를 실행하고, Node.js 22로 웹 JavaScript 구문을 검사합니다. CI에는 Torch·CUDA·모델을 설치하지 않으며 모델 추론과 실제 카메라 입력을 평가하지 않습니다.

## 실험 재현

```powershell
& $pyVision scripts/evaluate_generated.py --source web/assets/crowd-source.mp4 --output runs/crowd
& $pyVision scripts/render_comparison.py --source web/assets/crowd-source.mp4 --evaluation runs/crowd --output runs/crowd-overlay
& $pyVision scripts/evaluate_generated.py --source web/assets/higgsfield-source.mp4 --output runs/two-person
```

출력 폴더는 기존에 없어야 합니다. 평가기는 매 프레임 `PersonTracker.process`를 1회 실행해 `events.csv`, `tracks.jsonl`, `summary.json`, solid 마스킹 `dashboard.mp4`를 저장합니다. 비교 렌더러는 저장된 검출 좌표만 사용하고 YOLO를 다시 실행하지 않습니다. H.264 출력에서 원본과 프레임 수·해상도·FPS·시간축을 확인합니다. 모델 및 입력 SHA256은 기록에 남습니다.

고정 설정은 YOLO26n, `imgsz=640`, `confidence=0.1`, GPU 자동 선택, 선 `(0.1,0.55)→(0.9,0.55)`, 아래 방향 IN, 경계 여유 8px입니다. `floor_quad=null`이고 초기 실내 인원은 확인되지 않아 계산 기준 0을 사용했습니다. 원본 영상은 실제 측정에 사용한 파일 그대로 포함했습니다. 입력 프레임 내용이 바뀌는 재인코딩은 재현 실험에 사용하지 마세요.

## 기록된 결과와 범위

| 입력 | 관측 IN / OUT | 프레임 | 처리 구간 | 초기화 포함 벽시계 |
|---|---:|---:|---:|---:|
| 다인 AI 생성 영상 | 4 / 8 | 361 / 24fps | 14.991초 · 24.08fps | 19.722초 · 약 18.30fps |
| 2인 AI 생성 영상 | 1 / 1 | 241 / 24fps | 9.112초 · 26.45fps | 10.826초 · 약 22.26fps |

처리 구간은 읽기·검출·추적·집계·기존 solid 대시보드 렌더·기록·추적 로그·첫 추론 워밍업을 포함합니다. 모델 초기화·최종 기록 마무리·별도 반투명 오버레이 후처리는 제외합니다. 단일 파일 실행값으로, 실시간 카메라 지연이나 장시간 처리 보장이 아닙니다.

다인 영상의 12건 대조는 **YOLO 결과를 보지 않은 AI의 원본 시각 검수**입니다. 사람 검수자의 주석·합의 정답이나 현장 정확도 평가가 아닙니다. 생성 프롬프트의 의도 인원·동선은 정답으로 사용하지 않았습니다. 화면 가장자리 검출 누락과 ID 16→35 중복·분절을 확인했습니다. 22개 고유 ID는 22명이 아닙니다. 초기 인원이 불명확해 절대 재실 정확도는 평가하지 않았습니다.

로컬 앱 기본 마스킹은 `solid`입니다. 웹 비교 영상의 채움 12% 오버레이는 사람 얼굴·몸이 보이는 시각화이며 **`privacy_protection=false`**입니다. solid 모드도 검출되지 않은 사람을 가리지 못합니다.

웹의 실험 설계에 있는 24개 이상 클립, 2시간 촬영, 500건 출입, precision/recall·IDF1·HOTA·가림률 목표, 5분 반복·8시간 운용은 **제안한 미실행 계획**입니다. 실제 CCTV·웹캠, 전 프레임 검출/가림 정답, 촬영→표시 지연, 장시간 운용은 검증하지 않았습니다.

## 자산 · 라이선스

예제 원본은 Higgsfield로 생성한 AI 영상, 비교 영상은 해당 원본과 실제 YOLO 좌표의 후처리입니다. 합성 데모는 Python으로 그린 도형과 사전 생성 검출을 사용하며 모델 추론이 없습니다. 공개 bus.jpg 원본이나 모델 가중치는 포함하지 않았습니다.

기존 프로젝트 소스에서 자체 LICENSE 파일을 찾지 못해 새 프로젝트 라이선스·기업 소유권을 임의로 지정하지 않았습니다. 제3자 구성요소와 생성 자산의 조건은 별도로 적용됩니다. 확인한 패키지 라이선스와 모델 정보는 `THIRD_PARTY_NOTICES.md`를 참고하세요.
