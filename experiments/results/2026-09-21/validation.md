# 실행 기록 검증 · 2026-09-21

**21조건 · 63회 · 22,743프레임 기록 검증 통과.**

고정 원본 3개를 다시 디코딩해 각 361프레임·24fps·1280×720을 확인하고, 원본·원본 검수·protocol·실행기·어댑터의 SHA-256을 모든 반복에서 대조했다.

추적기 비교의 **9,747프레임 / 36,252개 ordered box·score 항목**은 각 영상 YOLO26n 1회차 캐시와 정확히 일치한다. 프레임 번호와 시각도 같다. 원본 검출의 삭제나 순서 변경으로 추적기 비교가 달라지지 않았음을 확인했다.

전체 312개 기록 이벤트를 저장된 footpoint에서 재생성하고 프레임 이벤트·통계·CSV·summary와 대조했다. 방향/시간 매칭은 별도 exhaustive bitmask DP로 검증했으며, 재배정이 필요한 예제·빈 입력을 포함한 204개 추가 사례도 통과했다. 이벤트 대응은 신원 정답이나 검출 정확도를 뜻하지 않는다.

기존 단위 검사: Ran 41 tests in 1.350s. GPU 재추론 없이 CPU 파일 검증만 수행했다.

## 반복별 결과

| 조건 | 1회 IN/OUT · ID | 2회 IN/OUT · ID | 3회 IN/OUT · ID | 변동 |
|---|---|---|---|---|
| cache-botsort-crossing | 5/0 · 10 | 5/0 · 10 | 5/0 · 10 | 없음 |
| cache-botsort-occlusion | 0/0 · 10 | 0/0 · 10 | 0/0 · 10 | 없음 |
| cache-botsort-reentry | 5/5 · 15 | 5/5 · 15 | 5/5 · 15 | 없음 |
| cache-bytetrack-crossing | 5/0 · 12 | 5/0 · 12 | 5/0 · 12 | 없음 |
| cache-bytetrack-occlusion | 0/0 · 12 | 0/0 · 12 | 0/0 · 12 | 없음 |
| cache-bytetrack-reentry | 5/5 · 15 | 5/5 · 15 | 5/5 · 15 | 없음 |
| cache-tracktrack-crossing | 4/0 · 5 | 4/0 · 5 | 4/0 · 5 | 없음 |
| cache-tracktrack-occlusion | 0/0 · 8 | 0/0 · 8 | 0/0 · 8 | 없음 |
| cache-tracktrack-reentry | 5/5 · 14 | 5/5 · 14 | 5/5 · 14 | 없음 |
| rtdetrv2_s-crossing | 5/0 · 19 | 5/0 · 19 | 5/0 · 19 | 없음 |
| rtdetrv2_s-occlusion | 0/0 · 20 | 0/0 · 20 | 0/0 · 20 | 없음 |
| rtdetrv2_s-reentry | 5/5 · 26 | 5/5 · 26 | 5/5 · 26 | 없음 |
| yolo11n-crossing | 5/0 · 10 | 5/0 · 10 | 5/0 · 10 | 없음 |
| yolo11n-occlusion | 0/0 · 10 | 0/0 · 10 | 0/0 · 10 | 없음 |
| yolo11n-reentry | 5/5 · 23 | 5/5 · 23 | 5/5 · 23 | 없음 |
| yolo26n-crossing | 5/0 · 12 | 5/0 · 12 | 5/0 · 12 | 없음 |
| yolo26n-occlusion | 0/0 · 12 | 0/0 · 12 | 0/0 · 12 | 없음 |
| yolo26n-reentry | 5/5 · 15 | 5/5 · 15 | 5/5 · 15 | 없음 |
| yolov8n-crossing | 5/0 · 10 | 5/0 · 10 | 5/0 · 10 | 없음 |
| yolov8n-occlusion | 0/0 · 12 | 0/0 · 12 | 0/0 · 12 | 없음 |
| yolov8n-reentry | 5/5 · 16 | 5/5 · 16 | 5/5 · 16 | 없음 |

YOLO는 매 추론 시 FP32 parameter dtype을 assert한 기록을 확인했다. RT-DETRv2는 `.float()` 모델 및 FP32 변환 코드와 metadata를 확인했으며 개별 프레임 dtype 로그는 없다. 세 번의 반복은 속도 변동 관찰이며 독립 영상 표본 세 개가 아니다.

출판 기록은 모든 반복 summary·events와 1회차 tracks를 포함한다. 2·3회차 tracks 전체는 로컬에서 검증했으며 공개 raw manifest와 이 JSON에 원본 SHA-256을 남긴다. 검증 JSON의 전체 해시 목록·반복별 수치에서 재확인할 수 있다.

이 검증은 파일 일관성과 구현 계약을 평가한다. 짧은 합성 영상의 원본 AI 주석을 사람 합의 정답으로 바꾸지 않으며 HOTA·IDF1·현장 정확도를 입증하지 않는다.
