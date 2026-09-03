# G-AIM AI Engine 구현 및 실행 가이드

FastAPI 기반 AI 콘텐츠 생성 마이크로서비스인 `ai-engine`의 구현 상태, 실행 방법, 테스트 방법을 정리한 문서입니다.

## 역할

`ai-engine`은 Spring Boot WAS 뒤에서 동작하는 AI 생성 엔진입니다.

```text
React
-> Spring Boot
-> FastAPI ai-engine
-> OpenAI / Google Vertex AI
-> Storage Adapter
-> 생성 결과 URL 반환
```

`ai-engine`이 담당하는 범위:

- 텍스트 생성
- 이미지 생성
- 참조 이미지 기반 이미지 편집
- 영상 생성 요청과 상태 조회
- 생성 파일 저장
- 생성 결과 URL 반환

`ai-engine`이 담당하지 않는 범위:

- 사용자 인증
- 점포/캠페인 DB 조회
- 콘텐츠 이력 저장
- 마케팅 정책 결정
- 프론트엔드 화면 상태 관리

Spring Boot가 사용자/점포/캠페인 데이터를 바탕으로 요청을 구성하고, `ai-engine`은 전달받은 요청을 실행합니다.

## 주요 디렉터리

```text
ai-engine/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── api/v1/
│   │   ├── router.py
│   │   ├── text.py
│   │   ├── image.py
│   │   └── video.py
│   ├── schemas/
│   ├── services/
│   │   ├── text/
│   │   ├── image/
│   │   │   ├── create_service.py
│   │   │   ├── model_router.py
│   │   │   ├── openai_service.py
│   │   │   ├── google_service.py
│   │   │   ├── mock_assets.py
│   │   │   ├── references.py
│   │   │   └── storage.py
│   │   └── video/
│   ├── storage/
│   ├── workers/
│   │   └── tasks/
│   │       └── video_tasks.py
│   └── core/
├── docs/
├── tests/
├── docker/
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── .env
```

## API 엔드포인트

헬스체크는 인증 없이 호출할 수 있습니다.

```http
GET /health
```

AI API는 Spring Boot 내부 호출을 전제로 하며 `X-Internal-Token` 헤더가 필요합니다.

```http
POST /v1/text/generate
POST /v1/text/brand
POST /v1/text/marketing
POST /v1/text/refine

GET  /v1/image/models
POST /v1/image/jobs
POST /v1/image/provider-generate
POST /v1/image/provider-generate-with-reference
POST /v1/image/intent

POST /v1/video/jobs
POST /v1/video/provider-generate
GET  /v1/video/status/{job_id}
```

이미지 생성의 기본 진입점은 `POST /v1/image/jobs`입니다.

- `/v1/image/jobs`: Spring Boot에서 사용하는 비동기 job API
- `/v1/image/generate`: 제거/비활성 상태인 레거시 동기 API. Swagger에 노출하지 않음
- `/v1/image/provider-generate`: provider/model을 직접 지정하는 테스트/직접 호출 API
- `/v1/image/provider-generate-with-reference`: 참조 이미지 기반 직접 호출 API
- `/v1/image/intent`: deprecated, 테스트/호환용 API

숏폼 영상 생성의 기본 진입점은 `POST /v1/video/jobs`입니다.

- `/v1/video/jobs`: Spring Boot에서 사용하는 비동기 숏폼 영상 job API
- `/v1/video/provider-generate`: provider 모델명을 직접 전달하는 테스트/직접 호출 API
- `/v1/video/status/{job_id}`: 개발/레거시 상태 조회 API

## 내부 인증

`app/core/security.py`에서 `X-Internal-Token`을 검증합니다.

```env
WAS_INTERNAL_TOKEN=change-this-internal-token
```

Swagger 또는 REST 호출 시:

```http
X-Internal-Token: change-this-internal-token
```

`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GCP_SERVICE_ACCOUNT_JSON`은 외부 요청 헤더에 넣지 않습니다. Provider 인증 정보는 `ai-engine` 내부 환경변수로만 관리합니다.

## 실행 모드

`AI_PROVIDER_MODE`로 실제 provider 호출 여부를 제어합니다.

```env
AI_PROVIDER_MODE=mock
```

mock 모드:

- 실제 OpenAI/Google 호출 없음
- 텍스트는 샘플 문자열 반환
- 이미지는 공통 mock PNG 저장
- 영상은 재생 가능한 MP4를 만들지 않고 `failed` 상태와 안내 오류 메시지를 반환
- Swagger 구조 확인과 자동 테스트에 적합

```env
AI_PROVIDER_MODE=live
```

live 모드:

- OpenAI 텍스트/이미지 실제 호출
- Google Vertex AI 이미지/영상 실제 호출
- `.env`의 OpenAI/GCP 인증 정보 필요

## 저장소 구조

현재 저장소는 로컬 파일 디렉터리입니다. 생성 결과는 repository 루트의 `storage-data` 아래에 저장되고, `STORAGE_PUBLIC_BASE_URL` 기준 URL로 반환됩니다.

핵심 파일:

```text
app/storage/protocols.py
app/storage/local.py
app/storage/factory.py
```

현재 저장 흐름:

```text
AI 생성 결과 bytes
-> StorageAdapter.put_bytes()
-> STORAGE_BASE_DIR/images 또는 STORAGE_BASE_DIR/videos 저장
-> STORAGE_PUBLIC_BASE_URL 기준 URL 반환
```

개발 기본 설정:

```env
STORAGE_BACKEND=local
STORAGE_BASE_DIR=../storage-data
STORAGE_PUBLIC_BASE_URL=http://127.0.0.1:8002/gaim/generated
```

현재 개발 환경의 실제 저장 위치 예:

```text
/Users/mjkim/project/G-AIM/GAIM_Source/storage-data/images/{uuid}.png
/Users/mjkim/project/G-AIM/GAIM_Source/storage-data/videos/{uuid}.mp4
```

테스트에서는 `tests/conftest.py`가 `STORAGE_BASE_DIR`을 테스트별 임시 디렉터리로 바꿉니다. 따라서 테스트 mock 파일은 `ai-engine/.test-storage`에 누적되지 않습니다.

향후 GCS/S3 같은 외부 storage로 이전할 때는 `app/storage/protocols.py`의 `StorageAdapter` 계약을 유지하고 `app/storage/factory.py`에서 backend를 선택하도록 확장합니다. `GCP_IMAGE_LOCATION`, `GCP_VIDEO_LOCATION`은 Google Vertex AI 모델 호출 location이며, 현재 로컬 파일 저장 위치를 의미하지 않습니다.

## OpenAI 이미지 모델 정책

지원 모델:

```text
gpt-image-2
gpt-image-1.5
gpt-image-1
gpt-image-1-mini
```

역할별 기본값:

| 역할 | 환경 변수 | 기본 모델 |
|---|---|---|
| 기본 generate fallback | `OPENAI_DEFAULT_IMAGE_MODEL` | `gpt-image-1.5` |
| 표준 생성 | `OPENAI_STANDARD_IMAGE_MODEL` | `gpt-image-1.5` |
| 고품질 생성 | `OPENAI_QUALITY_IMAGE_MODEL` | `gpt-image-2` |
| 비용/속도 fallback | `OPENAI_FAST_IMAGE_MODEL` | `gpt-image-1-mini` |
| 참조 이미지 편집 | `OPENAI_EDIT_IMAGE_MODEL` | `gpt-image-2` |
| 텍스트 정확도 | `OPENAI_TEXT_ACCURACY_IMAGE_MODEL` | `gpt-image-2` |

`gpt-image-2`는 OpenAI Organization Verification이 필요할 수 있습니다. 검증되지 않은 조직에서는 `403`이 발생할 수 있으므로, 일반 생성 기본값은 `gpt-image-1.5`를 사용합니다.

텍스트 렌더링 정확도가 중요한 경우에는 `gpt-image-2`를 우선 사용하고, 실패하면 Google Nano Banana로 fallback합니다.

## Google 이미지 모델 정책

Google provider는 Vertex AI 서비스 계정 인증을 사용합니다.

```env
GOOGLE_AUTH_MODE=vertex_ai
GCP_PROJECT_ID=...
GCP_LOCATION=us-central1
GCP_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
```

지원 모델:

```text
Nano Banana
- gemini-2.5-flash-image
```

Imagen 4 모델은 2026-08-17 shutdown 이후 지원하지 않습니다. 추후 Nano Banana 3.x 계열을 추가할 때는 모델 스펙 차이를 검토한 뒤 별도 후보군으로 추가합니다.

`GCP_LOCATION`은 사용자 지역이 한국이어도 임의로 `asia-*`로 바꾸면 안 됩니다. 모델이 실제로 배포된 Vertex AI location을 사용해야 합니다. 현재 이미지 모델 기본 location은 `global`입니다.

## 이미지 생성 라우팅

`POST /v1/image/jobs`는 클라이언트가 모델을 직접 선택하지 않습니다. 요청 내용으로 Google/OpenAI 후보를 만들고 worker에서 순차적으로 실행합니다. 라우팅 정책 자체는 `create_image()`와 `model_router.py` 단위 테스트로 검증합니다.

라우팅 핵심:

1. 텍스트 렌더링 요청이 있으면 OpenAI GPT Image를 우선 사용합니다.
2. OpenAI 텍스트 렌더링이 실패하면 Google Nano Banana로 fallback합니다.
3. 텍스트가 없고 참조 이미지가 있으면 Google Nano Banana edit을 우선 사용합니다.
4. 고품질/브랜드 요청은 Google Nano Banana를 우선 사용하고 OpenAI 고품질 모델을 fallback으로 둡니다.
5. 일반 생성은 Google Nano Banana를 우선 사용하고 OpenAI 표준 모델을 fallback으로 둡니다.
6. 모든 provider가 실패하면 local placeholder를 반환합니다.

텍스트 + 참조 이미지:

```text
1. OpenAI gpt-image-2 edit
2. Google gemini-2.5-flash-image edit
3. local default-placeholder
```

텍스트만 있음:

```text
1. OpenAI gpt-image-2 generate
2. Google gemini-2.5-flash-image generate
3. local default-placeholder
```

참조 이미지만 있음:

```text
1. Google gemini-2.5-flash-image edit
2. OpenAI gpt-image-2 edit
3. local default-placeholder
```

상세 정책은 [이미지 모델 라우팅 정책](./image-routing-policy-v1.1.md)을 기준으로 합니다.

### Frontend 이미지 생성 입력

현재 frontend 이미지 생성 화면은 `PresetStep`, `ImageSetupStep`, `ImageSetupResult` 3단계가 아니라 `ImageGeneration.jsx` 단일 화면입니다.

주요 입력 매핑:

| UI | API 필드 | 값 |
|---|---|---|
| 목적 | `purpose` | `홍보`, `이벤트`, `브랜드` |
| 플랫폼 프리셋 | `channels[0]` | `instagram`, `instagram_story`, `instagram_reels`, `blog`, `naver_place`, `banner`, `custom` |
| 생성 갯수 | `n` | 1-4 |
| 비주얼 무드 (선택) | `visual_mood` | 기본 `bright` |
| 프롬프트 | `image_prompt` | 사용자 입력 |
| 이미지 참고 | `reference_images` | `b64_json`, `mime_type` |
| 문구 삽입 | `text_rendering` | 정확 렌더링 옵션 |

`visual_mood`는 UI 선택값이지만 기본값이 있습니다. 화면에는 `현재 설정값 : 밝고 화사한`과 `옵션 더보기` 버튼을 한 줄에 표시하고, 옵션 확장 시 나머지 무드를 보여줍니다.

| 값 | UI 라벨 | 프롬프트 보강 | OpenAI style 파생값 |
|---|---|---|---|
| `bright` | 밝고 화사한 | 깨끗하고 밝은 하이키 조명, 선명한 색감 | `vivid` |
| `warm_cozy` | 따뜻하고 아늑한 | 따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기 | `natural` |
| `moody` | 감성적이고 깊이 있는 | 분위기 있는 저조도 조명, 깊이 있는 색감 | `natural` |
| `clean_minimal` | 깔끔하고 미니멀한 | 미니멀한 구성, 넉넉한 여백, 중립적인 색감 | `natural` |
| `premium` | 고급스럽고 세련된 | 고급스러운 질감, 정제된 구도, 세련된 시각 연출 | `natural` |
| `vibrant` | 선명하고 생동감 | 높은 채도, 활기찬 분위기, 강한 색 대비 | `vivid` |

OpenAI `style` 파라미터는 `visual_mood`에서 파생되는 provider 요청값입니다. 동시에 같은 값은 최종 이미지 프롬프트에도 자연어 힌트로 반영되어 Google fallback에서도 의도가 유지됩니다.

## `/v1/image/jobs` 요청 예시

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "purpose": "홍보",
  "visual_mood": "vibrant",
  "channels": ["instagram"],
  "image_prompt": "과일 가게 할인 행사 홍보 이미지",
  "text_rendering": {
    "text": "오늘 딸기 30% 할인",
    "language": "ko",
    "placement": "bottom",
    "must_render_exactly": true
  },
  "n": 1
}
```

`text_rendering.text`가 있고 `text_to_render`가 없으면 서버가 자동으로 `text_to_render`에 반영합니다.

## 직접 provider 호출 API

`/v1/image/provider-generate`와 `/v1/image/provider-generate-with-reference`는 Swagger 테스트나 provider별 직접 검증에 사용합니다.

OpenAI 직접 호출에서 `model`이 없으면:

- 참조 이미지가 없으면 `OPENAI_STANDARD_IMAGE_MODEL`
- 참조 이미지가 있으면 `OPENAI_EDIT_IMAGE_MODEL`

Google 직접 호출은 요청의 `model`이 Google 지원 모델 목록에 있어야 합니다.

## 영상 생성

`POST /v1/video/jobs`는 숏폼 영상 생성의 기본 API입니다. Spring Boot와 frontend는 Google/Veo 모델명을 직접 전달하지 않고 `fast`, `standard`, `lite` 중 하나를 전달합니다. `ai-engine`은 이를 실제 Vertex AI Veo 모델로 변환합니다.

지원 모델:

```text
veo-3.1-fast-generate-001
veo-3.1-generate-001
veo-3.1-lite-generate-001
```

영상 모델은 `.env`에서 확인하고 조정할 수 있습니다.

```env
GOOGLE_DEFAULT_VIDEO_MODEL=veo-3.1-fast-generate-001
GOOGLE_FAST_VIDEO_MODEL=veo-3.1-fast-generate-001
GOOGLE_STANDARD_VIDEO_MODEL=veo-3.1-generate-001
GOOGLE_LITE_VIDEO_MODEL=veo-3.1-lite-generate-001
GOOGLE_VIDEO_MODELS=["veo-3.1-fast-generate-001","veo-3.1-generate-001","veo-3.1-lite-generate-001"]
```

Veo 3.0 모델(`veo-3.0-fast-generate-001`, `veo-3.0-generate-001`)은 2026-06-30 shutdown 이후 지원하지 않습니다.

현재 구현은 `POST /v1/video/jobs`에서 Celery `video-queue`에 작업을 등록하고, worker가 provider 실행 후 WAS callback으로 progress/completed/failed를 전달합니다. `_JOBS` 인메모리 상태는 개발/레거시 status 조회용이며 12시간 TTL cleanup이 적용됩니다.

```text
POST /v1/video/jobs
-> job_id 즉시 반환
-> Celery worker에서 Veo/Runway provider 실행
-> 완료 시 STORAGE_BASE_DIR/videos 저장
-> WAS callback으로 resultUrl 전달

GET /v1/video/status/{job_id}
-> 개발/레거시 용도로 queued / processing / completed / failed 조회
```

`/v1/video/jobs` 요청 계약:

```text
model: fast | standard | lite
task: textToVideo | imageToVideo | referenceToVideo
aspectRatio: 9:16 | 16:9
durationSeconds: 4 | 6 | 8
```

`POST /v1/video/provider-generate`는 provider 모델명을 직접 전달하는 테스트/직접 호출 API입니다. 이 API는 `duration_seconds`를 4/6/8초로 보정합니다.

`AI_PROVIDER_MODE=mock`에서는 영상 job이 즉시 `failed`가 됩니다. mock 모드는 API 구조와 validation 확인용이며, 실제 재생 가능한 MP4를 만들려면 `AI_PROVIDER_MODE=live`와 Google Vertex AI 인증이 필요합니다.

운영에서는 인프로세스 background task 대신 Redis/Celery, Cloud Run Jobs, Queue 기반 worker 중 하나로 교체하는 것이 적합합니다.

## 실행 방법

위치 이동:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Source/ai-engine
```

가상환경 생성:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

의존성 설치:

```bash
pip install -r requirements-dev.txt
```

환경변수 생성:

```bash
cp .env.example .env
```

개발 기본값:

```env
APP_ENV=development
AI_PROVIDER_MODE=mock
WAS_INTERNAL_TOKEN=change-this-internal-token
STORAGE_BACKEND=local
STORAGE_BASE_DIR=../storage-data
STORAGE_PUBLIC_BASE_URL=http://127.0.0.1:8002/gaim/generated
```

실제 OpenAI 호출:

```env
AI_PROVIDER_MODE=live
OPENAI_API_KEY=...
OPENAI_DEFAULT_IMAGE_MODEL=gpt-image-1.5
OPENAI_STANDARD_IMAGE_MODEL=gpt-image-1.5
OPENAI_TEXT_ACCURACY_IMAGE_MODEL=gpt-image-2
OPENAI_EDIT_IMAGE_MODEL=gpt-image-2
```

실제 Google Vertex AI 호출:

```env
AI_PROVIDER_MODE=live
GOOGLE_AUTH_MODE=vertex_ai
GCP_PROJECT_ID=...
GCP_LOCATION=us-central1
GCP_IMAGE_LOCATION=global
GCP_VIDEO_LOCATION=us-central1
GCP_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
```

`GCP_SERVICE_ACCOUNT_JSON`은 여러 줄 JSON이 아니라 단일 라인 문자열로 넣어야 합니다.

`GCP_IMAGE_LOCATION`, `GCP_VIDEO_LOCATION`은 Vertex AI 모델 호출 location입니다. 생성 파일 저장 위치는 별도의 `STORAGE_BASE_DIR`/`STORAGE_PUBLIC_BASE_URL` 설정을 따르며, 현재 기본값은 로컬 `storage-data`입니다.

서버 실행:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Swagger:

```text
http://127.0.0.1:8002/docs
```

## 테스트 방법

헬스체크:

```bash
curl http://127.0.0.1:8002/health
```

이미지 job enqueue 테스트:

```bash
curl -X POST http://127.0.0.1:8002/v1/image/jobs \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: change-this-internal-token" \
  -d '{
    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
    "purpose": "홍보",
    "visual_mood": "vibrant",
    "channels": ["instagram"],
    "image_prompt": "과일 가게 할인 행사 홍보 이미지",
    "text_rendering": {
      "text": "오늘 딸기 30% 할인",
      "language": "ko",
      "placement": "bottom",
      "must_render_exactly": true
    },
    "n": 1
  }'
```

이미지 모델 목록:

```bash
curl "http://127.0.0.1:8002/v1/image/models?provider=openai" \
  -H "X-Internal-Token: change-this-internal-token"

curl "http://127.0.0.1:8002/v1/image/models?provider=google" \
  -H "X-Internal-Token: change-this-internal-token"
```

영상 생성:

```bash
curl -X POST http://127.0.0.1:8002/v1/video/jobs \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: change-this-internal-token" \
  -d '{
    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
    "prompt": "신선한 생선이 생선 가게 앞에서 한마리씩 튀어오르는 숏폼 영상",
    "model": "fast",
    "platform": "instagram_reels",
    "task": "textToVideo",
    "aspectRatio": "9:16",
    "durationSeconds": 4
  }'
```

자동 테스트:

```bash
pytest tests -q
```

또는:

```bash
.venv/bin/python -m pytest tests -q
```

## Spring Boot 연동 기준

Spring Boot는 OpenAI/Google 키를 직접 다루지 않습니다. 내부 REST API로 `ai-engine`만 호출합니다.

Spring Boot 이미지 생성 기본 호출:

```http
POST /v1/image/jobs HTTP/1.1
Host: 127.0.0.1:8002
Content-Type: application/json
X-Internal-Token: change-this-internal-token
```

Spring Boot가 저장할 값:

- `images[0]`
- `model_used`
- `provider`
- `routing.selected`
- `routing.fallback_used`
- `routing.warnings`

상세 연동 예시는 [Spring Boot 이미지 생성 연동 가이드](./springboot-image-generate-guide-v1.1.md)를 기준으로 합니다.

## 관련 문서

- [이미지 생성 API 가이드](./image-generate-guide-v1.1.md)
- [이미지 모델 라우팅 정책](./image-routing-policy-v1.1.md)
- [이미지 생성 코드 실행 흐름](./image-code-flow-v1.1.md)
- [Spring Boot 이미지 생성 연동 가이드](./springboot-image-generate-guide-v1.1.md)
