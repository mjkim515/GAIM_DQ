# AI Engine 보안 검토 및 개선 조치 요약

작성일: 2026-08-20

## 1. Null Pointer / 역참조 이슈

### 분석 결과

정적 분석에서 `model_router.py`, `prompts.py`, `veo_service.py` 중심으로 요청 객체, 선택 입력값, 외부 AI 서비스 응답에 대한 널 가능성이 지적되었다.

FastAPI와 Pydantic 요청 스키마가 필수 필드를 검증하므로 `request` 객체 자체와 필수 필드 상당수는 실제 취약점보다 오탐 가능성이 높다. 다만 선택 입력값, 리스트 인덱싱, 딕셔너리 직접 참조, 외부 Google Veo 응답 객체는 런타임에서 비정상 값이 들어올 수 있으므로 명시적 방어가 필요하다고 판단했다.

### 처리 내용

- `app/services/image/model_router.py`
  - `candidates[0]`, `routed_requests[0]` 접근 전 빈 리스트 검증 추가
  - 채널, 목적, 무드, 라벨 매핑을 안전 helper로 변경
  - 비정상 값은 `RequestValidationError`로 명확히 실패 처리

- `app/services/text/prompts.py`
  - 프롬프트 instruction 딕셔너리 직접 인덱싱을 안전 helper로 변경
  - 알 수 없는 `content_type`, mode 값은 명확한 validation error로 처리

- `app/services/video/veo_service.py`
  - Google Veo operation, response, generated video, video bytes를 단계별로 검증
  - 비어 있는 외부 응답은 `AttributeError`/`IndexError` 대신 의미 있는 `RuntimeError`로 처리
  - 참조 이미지 base64 입력은 유효하지 않으면 즉시 `RequestValidationError` 발생

### 검증

- 영향 범위 테스트 통과
  - image intent routing
  - marketing/refine prompt
  - video short validation
  - 외부 영상 응답 null/empty 방어

## 2. 부적절한 예외 처리 이슈

### 분석 결과

OpenAI, Google, 이미지 생성/편집, 텍스트 생성, 영상 생성 경로에서 외부 provider 예외가 포괄적으로 `ProviderError`로 변환되고 있었다. 예외가 완전히 무시되는 구조는 아니지만, 인증 오류, 요청 오류, rate limit, 네트워크 실패, timeout, 외부 서비스 장애를 구분하기 어려웠다.

또한 영상 및 이미지 비동기 job 실패 경로에서 `str(exc)`를 job 상태 또는 WAS callback payload에 그대로 넣는 코드가 있어 외부 provider 내부 메시지, 설정값, URI 등 민감한 세부 정보가 사용자 화면이나 상위 서비스에 노출될 가능성이 있었다.

### 처리 내용

- `app/core/exceptions.py`
  - provider 예외 하위 타입 추가
    - `ProviderAuthenticationError`
    - `ProviderRequestError`
    - `ProviderRateLimitError`
    - `ProviderTimeoutError`
    - `ProviderConnectionError`
    - `ProviderServiceUnavailableError`
  - 재시도 가능한 오류에는 `retryable=True` 부여

- `app/core/provider_errors.py`
  - OpenAI/Google provider 예외 분류 helper 추가
  - 사용자/job/callback용 일반화 메시지 helper 추가
  - fallback warning용 안전 메시지 helper 추가

- `app/services/image/openai_service.py`
  - OpenAI 이미지 생성/편집 예외를 유형별 provider 예외로 분류
  - 원본 provider 오류는 로그에만 기록하고 사용자 메시지에는 포함하지 않음

- `app/services/image/google_service.py`
  - Google 이미지 생성/편집 및 인증 설정 오류를 유형별 provider 예외로 분류
  - 서비스 계정 JSON, API key 관련 내부 설정명 또는 원문 오류가 외부 메시지에 노출되지 않도록 변경

- `app/services/text/openai_service.py`
  - OpenAI 텍스트 생성 예외를 유형별 provider 예외로 분류

- `app/services/video/veo_service.py`
  - `_JOBS[job_id].error`와 `notify_job_failed()`에 `str(exc)` 대신 일반화된 공개 오류 메시지 사용
  - 원본 예외는 `logger.exception()`으로 내부 로그에만 기록

- `app/workers/tasks/image_tasks.py`
  - 이미지 job 실패 callback과 return payload에서 원본 예외 문자열 제거

- `app/services/image/create_service.py`, `app/api/v1/image.py`
  - fallback warning에서 provider 원문 오류 제거
  - provider/model/rank와 일반화된 실패 사유만 노출

### 검증

- 영향 범위 테스트 통과
  - provider rate limit 분류 및 `retryable=True`
  - image fallback warning에 원본 exception 문자열 미노출
  - image job callback/return payload에 원본 exception 문자열 미노출
  - video job 공개 오류 메시지에 원본 provider 상세정보 미노출

## 3. 하드코드 중요정보 이슈

### 분석 결과

정적 분석에서 `prompts.py`, `veo_service.py`의 `naver_clip`, `Naver Clip` 문자열이 하드코드 중요정보로 탐지되었다.

해당 문자열은 API key, 인증 토큰, 비밀번호, 암호화 키가 아니라 지원 플랫폼을 구분하기 위한 일반 상수와 표시명이다. 따라서 이 항목은 정적분석 규칙에 따른 오탐으로 판단했다.

### 추가 점검 결과

오탐과 별개로 로컬 `ai-engine/.env` 파일에 실제 secret으로 보이는 항목이 존재하는 것을 확인했다.

- OpenAI API key 형태의 값
- Google API key 형태의 값
- Google service account JSON 및 private key 형태의 값

보안상 이 문서에는 실제 값을 기록하지 않는다.

`ai-engine/.gitignore`에는 `.env`가 포함되어 있어 git 추적은 차단되어 있었다. 다만 Docker build context나 배포 산출물에 포함될 가능성을 줄이기 위해 `.dockerignore`가 필요했다.

### 처리 내용

- `ai-engine/.dockerignore` 추가
  - `.env`, `.env.*` 차단
  - `.env.example`은 예외로 허용
  - `.venv`, cache, local storage, `.git` 차단
  - `*.pem`, `*.key`, service account JSON 패턴 차단

### 운영 권고

- 현재 로컬 `.env`에 있었던 OpenAI/Google/API/service account secret은 노출된 것으로 간주하고 폐기 및 재발급해야 한다.
- 운영 배포에서는 `.env` 파일을 이미지에 복사하지 말고 환경변수 또는 secret manager로 주입해야 한다.
- 후보 방식:
  - GCP Secret Manager
  - AWS Secrets Manager
  - Kubernetes Secret
  - 서버 로컬에만 존재하는 compose `env_file`
  - CI/CD secret injection

## 4. 검증 현황

### 통과한 검증

- 수정 파일 문법 검사 통과
- 직접 영향 범위 테스트 통과
  - Null safety 관련 테스트
  - provider 예외 분류 테스트
  - job/callback 공개 오류 메시지 마스킹 테스트
  - 기존 image intent, video short, text generation 주요 경로

### 전체 테스트 현황

전체 `ai-engine` 테스트 실행 결과는 다음과 같다.

- `47 passed`
- `10 failed`

남은 실패는 이번 보안 수정으로 새로 발생한 회귀가 아니라 기존 상태와 동일한 항목이다.

- deprecated `/v1/image/generate` 경로를 기대하는 테스트가 현재 API 등록 상태와 맞지 않아 404 발생
- OpenAPI schema ordering을 고정 순서로 기대하는 테스트 실패

## 5. 남은 조치

- 로컬 `.env`에 존재하던 실제 OpenAI/Google/service account secret 폐기 및 재발급
- 배포 파이프라인에서 `.env` 또는 service account 파일이 이미지에 포함되지 않는지 확인
- CI 단계에 secret scanning 추가 검토
- deprecated `/v1/image/generate` 관련 테스트와 실제 API 정책 정리
