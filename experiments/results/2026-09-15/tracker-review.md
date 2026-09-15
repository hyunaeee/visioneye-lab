# 캐시 추적 검사와 국소 원본 검토

GPU 추론 없이 완료된 기록과 동일 원본 프레임만 읽었다. 프레임 번호는 0부터 시작하며 시간은 frame / 24다. 아래 검토는 AI 시각 검토이며 사람의 ID 정답 주석이 아니다.

총 18개 실행의 5,418프레임 레코드, 순서가 있는 31,689개 검출 항목을 검사했다. 모든 frame·timestamp·xyxy·confidence가 해당 YOLO repeat1 캐시와 정확히 일치했다.

| 클립 | 프레임 / 반복 | 원본 검출 항목 / 반복 | IN / OUT | ByteTrack ID | TrackTrack OFF / ON ID |
|---|---:|---:|---:|---:|---:|
| 다인 | 361 | 3,143 | 4 / 8 | 22 | 18 / 18 |
| 두 사람 | 241 | 378 | 1 / 1 | 2 | 2 / 2 |

각 설정의 3반복은 모든 프레임의 ID 할당이 동일했다. TrackTrack ON/OFF 설정 차이는 with_reid뿐이며, 두 클립 602프레임 전체에서 ID 할당도 동일했다. 이번 입력에서는 ReID의 추가 효과가 관측되지 않았다. ID 개수는 사람 수가 아니다.

| 클립 | ByteTrack ID 있음 / 없음 검출 항목 | TrackTrack OFF·ON ID 있음 / 없음 검출 항목 |
|---|---:|---:|
| 다인 | 3,028 / 115 | 2,737 / 406 |
| 두 사람 | 365 / 13 | 356 / 22 |

이 수치는 검출 항목 기준이며 추적 정확도나 미검출률이 아니다. 모든 설정에서 ID가 없는 원본 박스도 그대로 보존했다.

## 코트 인물: ID 복귀와 공백

동일 원본의 코트 인물 이동을 확대 이미지로 확인했다. 기존 검토 박스와 IoU 0.5 이상인 후보의 좌표·신뢰도·ID를 JSON에 F250–360 전부 기록했다. 기존 박스는 검토 위치를 잡는 도구이며 정답 궤적이 아니다.

| 구간 | ByteTrack | TrackTrack OFF와 ON |
|---|---|---|
| F250–285 | ID16 | ID12 |
| F286 | ID16 + ID 없는 겹친 박스 | ID12 + ID 없는 겹친 박스 |
| F287–290 | ID16·35가 겹친 두 박스에 할당 | ID12 + ID 없는 겹친 박스 |
| F291 | ID16·35 | 두 박스 모두 ID 없음 |
| F292–293 | ID35 | ID 없음 |
| F294 | ID35 | ID12 복귀 |

따라서 이 국소 구간에서 TrackTrack은 새 ID 대신 기존 ID12로 복귀했지만 F291–293의 3프레임(0.125초) 공백이 있다. 더 뒤의 화면 위쪽 경계에서 F352–354와 F360에도 ID가 없다. 연속 추적이 완전해졌다는 뜻은 아니다. 큰 중복 박스는 코트와 인접한 보라색 셔츠 인물 쪽까지 걸쳐 있어 단순 ID 개수만으로 전체 분절 개선을 단정할 수 없다.

| F291 원본 xyxy | confidence | ByteTrack ID | TrackTrack OFF·ON ID |
|---|---:|---:|---|
| [812, 1.875, 850, 101.875] | 0.548828125 | 35 | 없음 |
| [813, 0, 867, 102.375] | 0.1041259765625 | 16 | 없음 |

F294 박스 [809, 0.5, 846, 96.125], confidence 0.64892578125: ByteTrack35, TrackTrack OFF·ON12.

## 검출기 두 프레임 spot check

동일 SHA의 원본과 각 검출기의 crowd/rep01을 사용했다. threshold 0.1을 바꾸지 않았다. 좌표·점수 원값은 JSON의 detector_spot_checks에 저장했다.

| F0 왼쪽 아래 잘린 인물 | 해당 영역 박스 수 | confidence |
|---|---:|---|
| yolo | 0 | 없음 |
| rfdetr | 2 | 0.420506209, 0.188982636 |
| deim | 3 | 0.257830948, 0.122619316, 0.103780173 |

YOLO에는 해당 박스가 없고 RF-DETR와 DEIM에는 있으나, 두 모델 모두 같은 위치에 겹친 추가 박스도 낸다. F0 한 장의 관찰을 전체 재현율 개선으로 해석하지 않는다.

| F291 코트 영역 | 원본 xyxy (표시 6자리 반올림) | confidence | ByteTrack ID |
|---|---|---:|---|
| yolo | [812, 1.875, 850, 101.875] | 0.548828125 | 35 |
| yolo | [813, 0, 867, 102.375] | 0.104125977 | 16 |
| rfdetr | [811.716003, 0.521287, 854.303711, 102.948891] | 0.823298633 | 19 |
| rfdetr | [811.408813, 0, 853.938599, 100.140961] | 0.129538193 | 없음 |
| deim | [807.751709, 0.363504, 858.179871, 103.554611] | 0.525175095 | 66 |
| deim | [809.273926, 0.404027, 867.966064, 103.941284] | 0.46609208 | 34 |

세 검출기 모두 코트 영역에 크게 겹친 박스가 두 개 남아 있다. RF-DETR의 낮은 점수 박스는 ID가 없고, DEIM의 두 박스에는 ID66·34가 있다. 근처 인물과 부분 박스를 포함한 전체 crop 검출도 JSON에 보존했다. 모델별 confidence는 서로 보정된 점수가 아니며 해상도·전처리·정밀도도 다르다.

## 재현 정보와 한계

ReID는 Ultralytics8.4.150 구현과 공식 yolo26n-reid.onnx, FP32, CUDAExecutionProvider를 사용했다. ONNX 입력 크기는 동적이며 실제 native 전처리의 기본 crop은 224였다. 원 논문의 전체 파이프라인 재현이 아니라 동일 검출 캐시에 대한 설치된 TrackTrack 구현 비교다.

ID 정답 주석이 없어 IDF1·HOTA·ID switch 수·분절률은 산출하지 않았다. 별도 정답 없이 사람 수나 절대 점유 정확도도 판단하지 않는다. 그림의 반투명/경계 표시에는 프라이버시 보호 효과가 없다.

원본 캐시 파일 SHA256:

- crowd: `962d0458ddfd7e0703bc8ca5cc5dc8d2ddbaba24b55024036ca899088ce1bb4d`
- two-person: `2c80a5162404d68e35436b740a946abd45baa0e541825171397d83e2a78705d7`

검사 이미지:

- [ByteTrack 코트](tracker-review-crowd/cached-byte-crowd-coat.jpg)
- [TrackTrack 코트](tracker-review-crowd/cached-track-crowd-coat.jpg)
- [TrackTrack ReID 코트](tracker-review-crowd/cached-reid-crowd-coat.jpg)
- [원본과 검출기 spot checks](tracker-review-crowd/detector-spot-checks.jpg)

기계 판독 상세: [tracker-review.json](tracker-review.json). 생성 코드: build_tracker_review.py; 전체 캐시 검증 코드: audit_tracker_results.py.
