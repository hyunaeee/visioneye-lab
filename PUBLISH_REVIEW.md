# 게시 준비 기록

권장 영문 GitHub description:

> YOLO26 people tracking and directional counting with a local Python pipeline and a synchronized video review viewer.

정적 사이트 루트: `web/`. 빌드 단계와 Node 의존성은 없습니다. Python 앱과 재현 스크립트는 저장소 소스에 포함하고 정적 웹 배포에는 포함하지 않습니다.

허용한 파일: 앱·테스트 소스, 설정, 실행기, 정적 HTML/CSS/JS, AI 예제 MP4·JPG, 정리된 CSV·JSON, 의존성 버전, 설명·제3자 라이선스 문서. `PUBLISH_FILES.json`에 상대 경로·크기·SHA256을 기록했습니다. 이 목록 자체는 재귀 해시를 피하기 위해 목록에서 제외합니다.

제외한 파일: Git 이력, `.openai/hosting.json`, Vercel 연결 상태, 가상환경, 모델 가중치, 캐시, 실행 로그, 인증정보, 개발 PC 절대경로가 포함된 원시 실행 요약, 다운로드 URL·작업 ID가 있는 생성 서비스 로그.

원본 사이트·앱 폴더를 수정하지 않았습니다. 복사본의 실행 경로만 새 구조에 맞추고 설치 의존성을 고정했습니다. 2인 실험의 검수 표현을 AI 시각 검수로 명확히 했습니다. 웹 원본 MP4는 측정에 사용한 원본 바이트로 교체해 재현용 입력 SHA256을 보존했습니다. 게시·커밋·원격 연결은 실행하지 않았습니다.

프로젝트 전체에 적용할 라이선스는 기존 소스에 없어 지정하지 않았습니다. `THIRD_PARTY_NOTICES.md`의 제3자 구성요소·생성 자산 조건을 별도로 확인할 수 있습니다.

복사본 검증: 기존 자동 테스트 41개 통과. 평가기·비교 렌더러 CLI 도움말 및 모듈 경로 확인. Python 구문과 정적 자산 참조 확인. 실제 사용자 경로·인증정보 패턴과 제외 대상 파일이 게시 파일에 없는지 검사했습니다. 새 PC 의존성 설치나 모델 다운로드, GitHub/Vercel 게시 자체는 실행하지 않았습니다.
