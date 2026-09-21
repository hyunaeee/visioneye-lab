# 신원 앵커 검수

잠긴 원본 3개 episode를 각 7조건의 rep01에 대조했다. 21쌍은 같은 원본의 반복 비교이며 독립 영상 21개가 아니다. 다른 실행 사이의 ID 숫자는 비교하지 않았다.

후보 기준: 수동 앵커와 IoU ≥ 0.20, 또는 예측 중심이 앵커 안에 있고 IoU ≥ 0.10. 공간 대응은 근사 후보 선정이다. 각 결과의 원본+예측 box 패널을 AI가 시각 확인했으며, 자동 대응과 시각 확인은 JSON에서 별도 필드로 남겼다.

| 조건 | 벽 가림 F18→192 | 화면 밖 복귀 F120→240 | 짧은 교행 F48→72 |
|---|---|---|---|
| YOLO26n + ByteTrack | 1→5 · ID 변경 | —→18 · ID 미배정 | 7→7 · 동일 ID |
| YOLOv8n + ByteTrack | 1→2 · ID 변경 | —→18 · 후보 누락 | 5→5 · 동일 ID |
| YOLO11n + ByteTrack | —→3 · 후보 누락 | 7→32 · ID 변경 | 7→7 · 동일 ID |
| RT-DETRv2-S + ByteTrack | 1→19 · ID 변경·중복 box | 5→51 · ID 변경 | 5→5 · 동일 ID |
| YOLO26n cache + ByteTrack | 1→5 · ID 변경 | —→18 · ID 미배정 | 7→7 · 동일 ID |
| YOLO26n cache + BoT-SORT | 1→5 · ID 변경 | —→13 · ID 미배정 | 7→7 · 동일 ID |
| YOLO26n cache + TrackTrack | 1→2 · ID 변경 | —→— · ID 미배정 | 7→7 · 동일 ID |

가림·화면 밖 구간의 동일인은 원본 검수에서도 likely다. 두 앵커에서 같은 ID가 보여도 사이의 모든 프레임에서 신원을 유지했다는 뜻은 아니다. 긴 부재는 공통 24프레임 lost buffer를 초과하므로 이후 새 ID가 생기는 동작 자체가 구현 오류를 뜻하지 않는다.

ReID OFF·GMC none 조건이며 추적기별 기본 연결 임계값은 다르다. 세 episode만으로 일반적인 신원 성능 순위를 만들지 않는다. HOTA·IDF1·MOTA·검출 recall은 산출하지 않았다. crossing 영상은 잠긴 bbox 앵커가 없어 제외했다.

[전체 증거 이미지](../../../web/assets/stress-identity-review.jpg) · [기계 판독 기록](identity-review.json)

RT-DETRv2-S 벽 가림 전 F18에는 같은 빨간 인물에 겹치는 후보 3개가 있다. ID 1 하나와 ID 없는 box 둘이며 중복된 추적 ID 셋은 아니다. 자동 공간 대응은 다중 후보로 남기고, 시각 검수에서 유일한 ID 1과 가림 후 ID 19를 별도 기록했다.

추가 계수 실패: 원근 영상에서 TrackTrack은 세 반복 모두 IN 4 / source 5였다. 선두 회색 상의 S01(F134–138)이 누락됐다. ByteTrack과 BoT-SORT는 F135에 같은 캐시 box를 ID 4로 계수했지만, TrackTrack은 해당 box에 ID를 배정하지 않았다. 이 대상의 발을 포함하는 박스 후보(F0–138)의 최대 score 0.674920은 TrackTrack 신규 트랙 기준 >0.7보다 낮았다. counter에는 ID가 있는 점만 들어가므로, 직접 확인된 원인은 신규 ID 미성립에 따른 counter 입력 누락이다. max-gap 재설정으로 잃은 이벤트가 아니다. 비교적 높은 신규 트랙 임계값·원래 박스의 혼합/중복 검출이 있는 해당 구성의 사례이며 임계값을 바꾼 대조 실험은 하지 않았다.

ByteTrack 12개, BoT-SORT 10개, TrackTrack 5개의 ID 총수만 보고 TrackTrack이 개선됐다고 판단할 수 없다. 이 영상에서는 ID 수가 적으면서 확인된 출입 이벤트 한 건도 놓쳤다.
