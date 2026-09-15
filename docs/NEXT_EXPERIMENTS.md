# VisionEye 비교 실험 설계

확인일: **2026-09-15, Asia/Seoul**. 공식 논문·저장소·문서를 웹에서 확인했다. 후속 실행에서 **TrackTrack·ReID, RF-DETR Small, DEIMv2-S 비교를 완료**했다. SAM 3.1은 공식 가중치 접근 승인 필요로 보류했다. [실측 결과](COMPARISON_RESULTS.md)와 [재현 방법](EXPERIMENT_REPRODUCTION.md)을 참고한다. 아래는 실행 전에 작성한 후보 선정 근거와 설계이며, 미실행 항목은 전체 GT 주석·현장 평가·최적화 등으로 구분한다.

**권장 순서: TrackTrack ReID → RF-DETR Small → DEIMv2-S → SAM 3.1.** 현재 관찰한 ID 분절을 추적기만 바꿔 먼저 점검하고, 화면 가장자리 검출 누락은 검출기 비교로 분리하는 순서다. 인기도 순위가 아니다.

## 기존 실측

| 자료 | 기존 결과 | 해석 범위 |
|---|---|---|
| YOLO26n + ByteTrack, AI 보행 영상 | 241프레임, 24fps 원본, IN 1 / OUT 1, 처리 구간 26.45fps | 원본 출입 검수 2건과 대응 |
| 같은 파이프라인, AI 군중 영상 | 361프레임, 24fps 원본, IN 4 / OUT 8, 처리 구간 24.08fps | 원본만 본 AI 시각 검수 12건과 일대일 대응; 고유 추적 ID 22개는 고유 인원 22명이 아님 |
| 현재 평가 한계 | AI 생성 원본 2개, 총 602프레임·출입 주석 14건 | 인간 합의 정답, 전 프레임 박스·ID·마스크 정답, 현장 성능 검증 없음 |

근거: [2인 실행 요약](../web/assets/higgsfield-summary.json), [군중 실행 요약](../web/assets/crowd-summary.json), [군중 원본 AI 검수](../web/assets/crowd-source-review.json), [군중 이벤트 대조](../web/assets/crowd-review-comparison.json). 위 FPS는 초기화 등을 제외한 **앱 처리 구간** 지표다. HOTA·IDF1·검출 누락률·가림 통과율은 기존 결과로 계산하지 않는다. 초기 실내 인원이 불명확하므로 절대 재실 정확도도 평가하지 않는다.

## 후보 4개

### 1. TrackTrack + ReID — ID 분절

**논문:** *Focusing on Tracks for Online Multi-Object Tracking*, CVPR 2025(2025년 6월). 모든 후보 검출을 활용하는 TPA와 중복 트랙 생성을 줄이는 TAI를 제안한다. [논문 원문](https://openaccess.thecvf.com/content/CVPR2025/papers/Shim_Focusing_on_Tracks_for_Online_Multi-Object_Tracking_CVPR_2025_paper.pdf), [저자 공식 코드](https://github.com/kamkyu94/TrackTrack)

**실행 후보:** 현재 YOLO26n을 유지하고 Ultralytics의 `tracktrack.yaml`을 사용한다. 8.4.63부터 제공되며 ReID를 선택적으로 켤 수 있다. 고정 카메라에서는 `gmc_method: none`, ReID는 `with_reid: True`와 명시적 `yolo26n-reid.onnx`를 후보 설정으로 고정한다. `auto`는 특징 추출 경로가 달라질 수 있어 비교 설정에서 피한다. 기존 실측 환경의 Ultralytics 8.4.150에 `tracktrack.yaml`이 있는 것까지 읽기 전용으로 확인했다. [공식 추적 문서](https://docs.ultralytics.com/modes/track/)

**가설·실험:** 동일 YOLO 검출 결과에 ByteTrack / TrackTrack ReID OFF / TrackTrack ReID ON을 적용한다. 사람별 ID 분절·ID switch·가림 후 ID 회복과 추가 지연을 비교한다. 추가 검출이 없는 상황에서 ReID만으로 검출 누락이 해결된다고 가정하지 않는다.

**4090 적합성·난이도:** 낮음~중간으로 예상. 검출기를 유지하고 작은 추가 인코더를 붙이는 구성이다. 실제 메모리·속도는 미측정이다. 저자 코드는 YOLOX·FastReID와 구형 환경을 사용하며, 논문은 NMS에서 버려진 후보도 이용한다. 따라서 Ultralytics 구현 비교를 **논문 완전 재현**이라고 부르면 안 된다. 저자 구현 그대로의 재현은 별도 과제로 둔다.

### 2. RF-DETR Small — 가장자리·부분 인물 검출

**논문:** *RF-DETR: Neural Architecture Search for Real-Time Detection Transformers*, 초판 2025-11-12, 개정 2026-02-03, ICLR 2026. 공식 최신 릴리스로 확인한 버전은 **1.10.1, 2026-09-07**이다. [논문](https://arxiv.org/abs/2511.09554), [공식 저장소](https://github.com/roboflow/rf-detr), [릴리스](https://github.com/roboflow/rf-detr/releases/tag/1.10.1)

**실행 후보:** 사전 학습 `RFDETRSmall`, person 검출을 원본 좌표로 변환해 **기존 ByteTrack과 집계기에 연결**한다. 공식 Small 입력은 512×512, 모델은 약 32.1M 파라미터다. Nano도 약 30.5M이므로 이름만 보고 YOLO26n과 같은 연산 규모로 취급하지 않는다. 초기 비교는 재학습 없이 진행한다. [공식 모델 표·Python 추론 예시](https://github.com/roboflow/rf-detr)

**가설·실험:** Transformer 기반 검출로 화면 가장자리·일부가 잘린 사람의 재현율이 개선되는지, 같은 tracker에서 출입·궤적이 어떻게 달라지는지 확인한다. 일반 장면과 가장자리 표본의 recall을 분리하고, false positive와 지연 증가도 함께 본다.

**4090 적합성·난이도:** 중간으로 예상. 배치 1의 Small 추론과 기존 tracker 연결이 우선 범위다. 새 환경, 전처리·좌표·클래스 매핑 어댑터가 필요하다. 공식 COCO 수치와 다른 GPU의 지연을 VisionEye 성능으로 옮기지 않는다. 패키지와 선택한 N/S/M/L 가중치는 Apache 2.0 표시를 확인했으며, XL/2XL은 별도 조건이므로 이번 후보에서 제외한다. [공식 라이선스 구분](https://github.com/roboflow/rf-detr#license)

### 3. DEIMv2-S — DINOv3 특징과 검출 비용

**논문:** *Real-Time Object Detection Meets DINOv3*, 초판 2025-09-25, 최신 확인 개정 2026-01-26. 모델 시리즈 공개는 **2025-09-26**이며 공식 저장소는 2026년 8월 업데이트도 안내한다. [논문](https://arxiv.org/abs/2509.20787), [공식 저장소](https://github.com/Intellindust-AI-Lab/DEIMv2), [공식 프로젝트](https://intellindust-ai-lab.github.io/projects/DEIMv2/)

**실행 후보:** 사전 학습 S(약 9.7M) + 동일 ByteTrack. S/M/L/X는 DINOv3 사전 학습 또는 증류 특징을 사용한다. **N/Pico/Femto/Atto는 HGNetv2 계열**이므로 N을 실행하고 DINOv3 효과라고 설명하면 안 된다. S를 주 실험, N을 연산 비용 비교용 보조 실험으로 둘 수 있다. [논문의 모델 구분](https://arxiv.org/abs/2509.20787)

**가설·실험:** 가장자리·작은 사람 검출에서 특징 표현의 이득이 실제 오검출·누락 및 출입 이벤트로 이어지는지 확인한다. RF-DETR와 마찬가지로 tracker·출입선은 유지한다. DEIMv2-S와 YOLO26n의 차이는 모델 크기·사전 학습도 포함하므로 아키텍처만의 인과 효과로 해석하지 않는다.

**4090 적합성·난이도:** 중간. 공식 단일 `cuda:0` 이미지·영상 PyTorch 추론 경로가 있다. TensorRT 비교는 다음 단계로 분리하며, 공식 저장소는 FP16 오류 수정과 함께 TensorRT ≥10.6을 명시한다. 24GB 내 실제 사용량은 미측정이다. 현재 라이선스는 비상업적 연구·평가를 허용하고 상업 사용은 별도 계약을 요구하므로, 향후 제품 적용 후보를 고를 때 차이가 있다. [추론·배포 안내](https://github.com/Intellindust-AI-Lab/DEIMv2), [현재 라이선스](https://github.com/Intellindust-AI-Lab/DEIMv2/blob/main/LICENSE.md)

최신성을 혼동하지 않도록 덧붙이면, 같은 연구팀은 2026-03-20 후속 **EdgeCrafter**도 공개 안내했다. 이 문서의 후보는 공개 추론 경로가 확인된 DEIMv2-S로 한정하며, 이를 2026년 9월의 가장 최신 검출기라고 주장하지 않는다. [연구팀 공식 업데이트](https://github.com/Intellindust-AI-Lab/DEIMv2)

### 4. SAM 3.1 — 시간에 따른 마스크·객체 유지

**공개:** **2026-03-27** SAM 3.1 Object Multiplex. 기반 논문 *SAM 3: Segment Anything with Concepts* 초판은 2025-11-20, 3.1을 반영한 개정은 2026-03-28이다. 여러 객체를 함께 처리하는 공유 메모리 방식으로 영상 추적 계산을 줄인다. [공식 릴리스](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md), [논문](https://arxiv.org/abs/2511.16719), [공식 코드](https://github.com/facebookresearch/sam3)

**실행 후보:** 텍스트 프롬프트를 `person`으로 고정하고 순방향 영상 추론을 진행한다. 수동 클릭·중간 프롬프트 수정·미래 프레임을 보는 역방향 보정은 별도 모드로 분리한다. 마스크와 지속 ID를 사용하므로 검출기만 교체한 실험과 구분한 **전체 시스템 비교**다.

**가설·실험:** 검출 박스가 짧게 끊기는 구간에서 사람 영역의 가림 연속성이 좋아지는지 확인한다. 출입 비교에는 마스크의 바깥 박스 바닥점을 사용하고 동일 집계 로직을 유지한다. 가림 면적 재현율·노출 지속시간·ID 안정성과 비용을 측정한다. 더 정교한 윤곽이 자동으로 더 안전한 가림을 뜻하지 않으므로, 박스 가림보다 늘어난 노출 픽셀도 확인한다.

**4090 적합성·난이도:** 높음·조건부. Python ≥3.12, PyTorch ≥2.7, CUDA ≥12.6 요구는 현재 환경 계열과 맞지만, 체크포인트 접근 승인과 별도 환경이 필요하다. 우선 단일 GPU·짧은 클립·배치 1의 오프라인 실험으로 계획한다. **4090 24GB에서 해당 객체 수를 처리하는 메모리와 FPS는 확인하지 않았다.** 공식 H100 속도 향상을 4090 성능으로 환산하지 않는다. [설치·가중치 접근](https://github.com/facebookresearch/sam3#installation), [공식 영상 예제](https://github.com/facebookresearch/sam3/blob/main/examples/sam3.1_video_predictor_example.ipynb)

## 고정 데이터 비교안 — 다음 작업

1. **입력·설정 잠금:** 기존 AI 영상 2개의 SHA256, 24fps 전체 602프레임, 순서·해상도·사전 고정 선 `(128,396)→(1152,396)`·아래 IN·8px 밴드·관측 공백 정책을 고정한다. 재실 대신 IN/OUT와 순증감을 평가한다. 모델·패키지·가중치 hash, 정밀도, resize/letterbox, 임계값, 저장 옵션을 manifest에 남긴다.
2. **정답 보강:** 기존 14개 원본 검수 이벤트와 시간 구간은 변경하지 않는다. 추적 평가에는 모든 평가 프레임의 사람 박스와 지속 GT ID, 가림 평가에는 지정 프레임의 보이는 사람 마스크를 별도로 주석한다. 초기·말기 등장, 가장자리, 가림을 표본에서 빼지 않는다. 주석이 애매한 객체는 unknown으로 표시하고 평가 제외 수를 공개한다. 인간 검수를 거치지 않으면 계속 'AI 시각 검수 기준'으로 표시한다.
3. **한 번에 한 요소:** tracker 실험은 저장된 동일 YOLO 박스·점수를 재사용한다. ReID ON/OFF는 인코더 외 설정도 동일하게 유지한다. detector 실험은 동일 ByteTrack·집계기를 유지한다. SAM 3.1은 별도 전체 시스템 실험으로 둔다.
4. **해상도·점수 공정성:** 기본 비교는 각 모델이 지원하는 권장 입력 크기를 명시한 실용 성능 비교다. 동일 크기 비교는 모든 후보가 지원하는 크기를 확인한 뒤 별도로 설계한다. 모델 confidence 0.1을 동일 의미의 확률로 취급하지 않는다. 전체 PR 곡선과 고정 운영점을 함께 보고하고, 임계값 조정은 평가 영상 외 별도 조정 세트에서만 한다.
5. **측정 반복:** GPU 1개·배치 1로 모델별 같은 반복 횟수(예: 3회)를 정한다. 초기 기동, 워밍업 후 검출/추적, 렌더·저장 포함 전체 처리 구간을 분리해 p50/p95·FPS·최대 VRAM을 기록한다. GPU 완료 시점까지 타이밍에 반영한다. 파일 처리 지연을 실제 카메라 촬영→표시 지연으로 부르지 않는다. 동일 영상 재실행 3회는 정확도 표본 3배가 아니다.

| 비교 축 | 지표와 분모 | 이 데이터에서 가능한 해석 |
|---|---|---|
| 출입 | 같은 인물·방향·클립의 일대일 대응, 고정 검수 구간 포함 여부; TP/FP/FN 및 precision·recall; 방향별 절대 집계 오차 | 14개 검수 이벤트의 회귀 검사. 넓힌 ±0.5초 결과는 사전 정의한 보조 민감도 분석으로만 분리 |
| 검출 | 전 주석 사람 박스가 분모인 person recall·AP; 영상 바깥 5% 띠와 겹치는 GT 박스를 '가장자리'로 미리 정의해 별도 보고 | 검출된 사람만 분모로 쓰면 안 됨. 프레임당 검출 수 감소만으로 품질을 판단하지 않음 |
| 추적 | IDF1, HOTA/AssA, ID switch·분절 수, 동일 GT 인물의 가림 후 ID 회복 | 지속 GT ID 주석이 있어야 계산. 고유 예측 ID 22개만으로 분절률 계산 불가 |
| 가림 | 전체 주석 사람-프레임별 가림 면적 비율, 누락한 사람-프레임 수, 연속 노출 시간, 불필요하게 가린 배경 비율 | 정교한 윤곽과 누락 위험을 함께 비교. 자동 익명화 보장으로 해석하지 않음 |
| 비용 | 처리 단계별 p50/p95, 전체 처리 FPS, 최대 VRAM, 초기 로드·워밍업 시간 | 동일 4090·동일 조건의 새 비교에서만 우열 판단 |

추적·마스크 지표는 저자들의 [TrackEval 공식 구현](https://github.com/JonathonLuiten/TrackEval)을 사용한다. **클립 2개로 현장 일반화나 신뢰할 만한 클립 간 95% 신뢰구간을 주장하지 않는다.** 먼저 각 클립의 원자료와 실패 사례를 비교하고, 현장 성능 판단은 별도의 다양한 실제 영상 평가로 넘긴다.

선정 기준은 '출입을 유지하면서 ID 분절·가림 누락이 줄었는가, 그 비용은 얼마인가'다. 실제 결과가 나오기 전에는 후보를 개선 모델이나 승자로 표시하지 않는다.
