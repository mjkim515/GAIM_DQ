# 숏폼 영상 생성 API 가이드

> Version: v1.2

## 요약

운영 권장 구조에서 숏폼 영상 생성의 주 경로는 Spring Boot WAS가 `jobId`를 생성하고 `POST /v1/video/jobs`로 ai-engine에 전달한 뒤, `ai-engine`이 provider 실행과 WAS callback을 처리하는 방식입니다.

`POST /v1/video/jobs`는 활성 ai-engine 내부 영상 Job API입니다. frontend는 항상 Spring Boot의 `POST /api/ai/video/async/generate`를 호출하고, frontend가 `ai-engine`을 직접 호출하지 않습니다.

WAS 서버는 Google/Veo 모델명을 직접 전달하지 않습니다. `model`은 `fast`, `standard`, `lite` 중 하나만 전달하고, `ai-engine`이 내부에서 실제 provider 모델로 변환합니다.

현재 기본 영상 provider는 Google Veo입니다. `ai-engine`은 Veo 후보를 먼저 실행하고, provider 실패 또는 지원 중단 등으로 실패하면 Runway 후보로 fallback합니다. 운영 WAS 요청에는 별도 provider 필드를 보내지 않습니다.

영상 생성은 오래 걸릴 수 있으므로 Spring Boot WAS가 먼저 `jobId`를 생성하고 DB에 저장한 뒤, `ai-engine`에 `jobId`를 포함해 생성 요청을 전달합니다. `ai-engine`은 진행률, 완료, 실패를 WAS callback으로 알리고, frontend는 WAS 상태 API를 polling 합니다.

## 엔드포인트

Frontend -> Backend:

```http
POST /api/ai/video/async/generate
Content-Type: application/json
```

```http
GET /api/ai/video/async/job/{jobId}
```

Backend -> ai-engine:

```http
POST /v1/video/jobs
X-Internal-Token: {WAS_INTERNAL_TOKEN}
Content-Type: application/json
```

위 HTTP API가 현재 활성 연동 경로입니다. `POST /v1/video/jobs`는 요청 검증 후 Celery task를 `video-queue`에 등록합니다.

ai-engine 상태 조회:

```http
GET /v1/video/status/{jobId}
X-Internal-Token: {WAS_INTERNAL_TOKEN}
```

`/v1/video/status/{jobId}`는 개발 확인 및 Spring Boot scheduled reconciler fallback용입니다. 운영 상태의 source of
truth는 WAS DB이며, frontend는 ai-engine 상태 API를 직접 호출하지 않습니다.

Swagger:

```text
http://127.0.0.1:8002/docs
https://ai.idq.co.kr/gaim/docs
```

## 상태 동기화 원칙

정상 경로는 ai-engine의 callback push입니다. ai-engine status API 조회는 callback push를 대체하지 않습니다.

1. frontend는 Spring Boot의 `GET /api/ai/video/async/job/{jobId}`만 polling합니다.
2. ai-engine worker는 `progress 5`, `progress 90`, `completed` 또는 `failed` callback을 Spring Boot로 push합니다.
3. Spring Boot는 callback을 받아 WAS DB 상태를 갱신합니다.
4. `GET /v1/video/status/{jobId}`는 Spring Boot scheduled reconciler만 사용하는 fallback 조회 API입니다.
5. 사용자가 보는 운영 상태의 source of truth는 항상 Spring Boot/WAS DB입니다.

```text
정상 경로:
ai-engine worker -> Spring Boot callback endpoint -> WAS DB -> frontend polling

선택 보정 경로:
Spring Boot scheduled reconciler -> ai-engine status API -> WAS DB 보정
```

| 경로/기능 | 필수 여부 | 목적 |
|---|---:|---|
| ai-engine callback push | 필수 | 정상 상태 업데이트 |
| Spring Boot/WAS DB 상태 API | 필수 | frontend polling의 기준 상태 제공 |
| Spring Boot scheduled reconciler | 선택 | callback 유실, WAS 재시작, 일시 timeout 시 상태 보정 |
| ai-engine status API | 선택 | reconciler가 사용하는 fallback 조회 |

최소 MVP는 callback push와 WAS DB 상태 API만으로 동작할 수 있습니다. 다만 callback이 유실되면 사용자가 계속
`queued` 또는 `processing` 상태를 볼 수 있으므로, 안정화 MVP 또는 실제 운영에서는 scheduled reconciler를 추가하는
것을 권장합니다.

따라서 ai-engine status API를 frontend에 직접 노출하지 않습니다. callback 유실, WAS 재시작, 배포 중 callback
endpoint timeout처럼 정상 callback push를 놓친 경우에만 reconciler fallback으로 사용합니다.

## Celery 비동기 Job 처리 구조

WAS는 queue를 직접 발행하지 않습니다. WAS는 HTTP로 `POST /v1/video/jobs`를 호출하고, `ai-engine` API 서버가 Celery task를 등록합니다.

```text
Frontend
  -> Spring Boot WAS /api/ai/video/async/generate
  -> ai-engine POST /v1/video/jobs
  -> Celery video-queue
  -> app.workers.tasks.video_tasks.generate_video_short_task
  -> provider 실행: Veo 우선, Runway fallback
  -> storage 저장
  -> WAS callback progress/completed/failed
```

Celery 설정:

- Celery app: `app.workers.celery_app.celery_app`
- 영상 task: `app.workers.tasks.video_tasks.generate_video_short_task`
- 영상 queue: `video-queue`
- 이미지 queue: `image-queue`
- broker/backend: `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, 없으면 `REDIS_URL`

아래 payload 예시는 WAS가 `POST /v1/video/jobs`에 전달하는 `VideoShortCreateRequest` body입니다. Celery task 내부에서도 같은 계약이 사용됩니다.

`input`은 영상 생성에 사용할 이미지 입력을 담고, `advanced`는 provider 옵션 override만 담습니다. `imageToVideo`와 `referenceToVideo`의 이미지 입력을 `advanced`에 넣지 않습니다.

### textToVideo 요청 body

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "영상 생성 프롬프트",
  "model": "fast",
  "platform": "instagram_reels",
  "task": "textToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "advanced": {
    "generateAudio": true
  },
  "metadata": {
    "userId": "user-id",
    "businessId": "business-id",
    "campaignId": "campaign-id"
  }
}
```

### imageToVideo 요청 body

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성",
  "model": "fast",
  "platform": "instagram_reels",
  "task": "imageToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_START_FRAME_BYTES",
      "mimeType": "image/png"
    },
    "lastFrame": {
      "bytesBase64Encoded": "BASE64_END_FRAME_BYTES",
      "mimeType": "image/png"
    }
  },
  "advanced": {
    "generateAudio": true,
    "resizeMode": "crop"
  },
  "metadata": {
    "userId": "user-id",
    "businessId": "business-id",
    "campaignId": "campaign-id"
  }
}
```

`lastFrame`은 선택입니다. 시작 이미지만 사용할 경우 `input.image`만 보내면 됩니다.

`input.image`와 `input.lastFrame`을 함께 보내는 경우는 Veo first/last frame interpolation 용도입니다. 업로드한 시작 프레임과 종료 프레임을 영상의 시간적 앵커로 유지하고, 그 사이를 자연스럽게 전환하는 데 최적화되어 있습니다.

주의:

- 시작/종료 프레임 이미지가 프롬프트의 핵심 장면과 크게 다르면 프롬프트 반영이 제한될 수 있습니다.
- 프롬프트에만 있는 새 인물, 동물, 장소, 상품을 중간 장면에 강하게 추가하는 용도에는 적합하지 않습니다.
- 예를 들어 시작/종료 프레임에 카페, 젊은 남자, 리트리버가 전혀 없다면 프롬프트에 해당 요소를 써도 결과 영상에 안정적으로 등장하지 않을 수 있습니다.
- 사용자가 업로드한 두 프레임을 유지하는 것이 우선이면 `imageToVideo + lastFrame`을 사용합니다.
- 프롬프트 장면 반영이 우선이면 `textToVideo` 또는 `referenceToVideo`를 사용하거나, 프롬프트에 맞는 시작/종료 이미지를 먼저 준비한 뒤 `imageToVideo + lastFrame`에 사용합니다.

### referenceToVideo 요청 body

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성",
  "model": "standard",
  "platform": "tiktok",
  "task": "referenceToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "input": {
    "referenceImages": [
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_1",
        "mimeType": "image/png"
      },
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_2",
        "mimeType": "image/jpeg"
      }
    ]
  },
  "advanced": {
    "generateAudio": true,
    "sampleCount": 1
  },
  "metadata": {
    "userId": "user-id",
    "businessId": "business-id",
    "campaignId": "campaign-id"
  }
}
```

`referenceImages`는 1~3장입니다. `referenceImages`는 `image` 또는 `lastFrame`과 같이 보낼 수 없습니다.

규칙:

- `jobId`는 WAS가 생성합니다.
- 요청 body는 `/v1/video/jobs`의 `VideoShortCreateRequest` 계약을 사용합니다.
- `input`은 `image`, `lastFrame`, `referenceImages` 같은 이미지 입력 필드입니다.
- `advanced`는 `generateAudio`, `sampleCount`, `resolution`, `negativePrompt`, `seed` 같은 provider 옵션 override 필드입니다.
- `metadata`는 WAS 내부 추적용이며 provider로 직접 전달하지 않습니다.
- `ai-engine` worker는 message 검증 후 provider 실행, storage 저장, WAS callback 전송만 담당합니다.

## 환경 설정

`ai-engine/.env` 기준:

```env
AI_PROVIDER_MODE=live
GOOGLE_AUTH_MODE=vertex_ai
GCP_LOCATION=us-central1
GCP_IMAGE_LOCATION=global
GCP_VIDEO_LOCATION=us-central1
STORAGE_BACKEND=local
STORAGE_BASE_DIR=../storage-data
STORAGE_PUBLIC_BASE_URL=http://127.0.0.1:8002/gaim/generated
VIDEO_POLL_INTERVAL_SEC=10
VIDEO_MAX_WAIT_SEC=600
WAS_CALLBACK_TIMEOUT_SEC=3.0
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_TASK_ALWAYS_EAGER=false
CELERY_WORKER_CONCURRENCY=3
RUNWAYML_API_SECRET=runway-local-placeholder
RUNWAY_VIDEO_MODELS=["gen4.5","gen4_turbo"]
RUNWAY_FAST_VIDEO_MODEL=gen4_turbo
RUNWAY_STANDARD_VIDEO_MODEL=gen4.5
RUNWAY_API_BASE_URL=https://api.dev.runwayml.com/v1
RUNWAY_API_VERSION=2024-11-06
```

`GCP_LOCATION`은 공통 fallback입니다. 이미지와 비디오는 모델별 지원 location이 다르므로 분리합니다.

- 이미지: `GCP_IMAGE_LOCATION=global`
- 비디오/Veo: `GCP_VIDEO_LOCATION=us-central1`

위 `GCP_*_LOCATION` 값은 Vertex AI 모델 호출 location입니다. 현재 생성 결과 저장소는 GCS가 아니라 로컬 `storage-data`입니다.

Runway는 fallback provider입니다. 운영 기본 경로는 Google Veo이며, `RUNWAYML_API_SECRET`이 없으면 Veo 실패 후 Runway fallback도 인증 오류로 실패합니다.

## Celery worker 실행

Celery worker는 FastAPI 서버와 별도 프로세스로 실행합니다. broker/backend는 Redis를 사용합니다.

로컬 개발에서는 Redis, FastAPI API 서버, Celery worker를 각각 별도 터미널에서 실행합니다.

```bash
# terminal 1
./run_redis.sh

# terminal 2
./run_server.sh

# terminal 3
./run_worker.sh
```

`run_worker.sh` 기본값:

- Celery app: `app.workers.celery_app.celery_app`
- queue: `image-queue,video-queue`
- concurrency: `CELERY_WORKER_CONCURRENCY` 기본 `3`
- log level: `info`

영상 queue만 실행하려면:

```bash
CELERY_QUEUES=video-queue ./run_worker.sh
```

동시 처리량을 조절하려면:

```bash
CELERY_WORKER_CONCURRENCY=2 ./run_worker.sh
```

Redis를 Docker로 직접 띄우는 기본 스크립트:

```bash
./run_redis.sh
```

이미 `localhost:6379`에 Redis가 실행 중이면 `run_redis.sh`는 기존 Redis를 재사용합니다.

`AI_PROVIDER_MODE=mock`에서는 실제 playable MP4가 생성되지 않으므로, Celery enqueue/callback 흐름만 확인하고 실제 영상 결과 검증은 `AI_PROVIDER_MODE=live`와 Google/Veo 인증 설정을 사용합니다. Runway fallback 또는 Runway 직접 테스트도 `AI_PROVIDER_MODE=live`와 `RUNWAYML_API_SECRET`이 필요합니다.

현재 최소 worker 정책:

- `POST /v1/video/jobs`가 요청을 검증하고 Celery task를 `video-queue`에 등록합니다.
- Celery task는 `VideoShortCreateRequest`를 다시 검증합니다.
- `AI_PROVIDER_MODE=mock`이면 실제 provider를 호출하지 않고 mock 실패 상태를 기록합니다.
- `AI_PROVIDER_MODE=live`이면 Veo 후보를 먼저 실행하고, provider 실패 시 Runway 후보를 실행합니다.
- provider가 모두 실패하면 public-safe error message로 failed callback을 전송합니다.
- Celery task 자체의 `max_retries=2`가 설정되어 있으나, 현재 provider fallback은 task 내부에서 순차 실행됩니다.
- WAS callback이 source of truth를 갱신하고, frontend는 WAS 상태 API만 polling합니다.

Docker Compose에서는 `worker` 서비스를 scale out할 수 있습니다.

```bash
docker compose up --scale worker=2
```

## WAS 구현 체크리스트

Spring Boot WAS는 영상 생성 job lifecycle의 source of truth입니다. WAS 작업자는 아래 항목을 맞춰야 합니다.

- frontend 요청은 WAS의 `/api/ai/video/async/generate`에서만 받습니다.
- WAS가 `jobId`를 생성합니다.
- WAS DB에 job을 `pending` 또는 `queued` 상태로 저장합니다.
- 사용자의 business/campaign 권한과 quota를 ai-engine 호출 전에 검증합니다.
- WAS는 `/v1/video/jobs` body와 동일한 계약으로 ai-engine에 HTTP 요청을 보냅니다.
- `metadata`에는 `userId`, `businessId`, `campaignId` 등 WAS 추적 정보를 넣습니다.
- callback 수신 API는 `X-Internal-Token`으로 보호합니다.
- progress/completed/failed callback을 수신하면 WAS DB의 job 상태를 갱신합니다.
- frontend status polling은 WAS DB 기준 API만 사용합니다.

ai-engine은 아래 책임만 수행합니다.

- `/v1/video/jobs` 요청 검증
- Celery `video-queue` task enqueue
- Celery video task 실행
- WAS가 전달한 `jobId` 사용
- `fast`, `standard`, `lite`를 실제 provider 후보로 변환
- Veo 우선 provider 호출 및 Runway fallback
- 생성 결과 storage 저장
- WAS로 progress/completed/failed callback 전송

ai-engine은 사용자 인증, 권한 검증, 과금/quota 판정, frontend status API의 source of truth를 담당하지 않습니다.

## 요청 필드

아래 표는 WAS 연동 계약 기준입니다. `ai-engine` 내부 스키마에는 일부 기본값과 자동 추론이 있지만, WAS는 운영 추적과 플랫폼별 정책 적용을 위해 기본 선택값을 명시해서 보냅니다.

| 필드 | 필수 | 설명 |
|---|---:|---|
| `prompt` | 예 | 영상 생성 프롬프트 |
| `model` | 예 | `fast`, `standard`, `lite` |
| `platform` | 예 | `youtube_shorts`, `instagram_reels`, `tiktok`, `naver_clip` |
| `task` | 예 | `textToVideo`, `imageToVideo`, `referenceToVideo` |
| `aspectRatio` | 예 | `9:16`, `16:9` |
| `durationSeconds` | 예 | `4`, `6`, `8` |
| `input` | 조건부 | `imageToVideo`는 `input.image` 필수, `referenceToVideo`는 `input.referenceImages` 필수, `textToVideo`는 보내지 않음 |
| `advanced` | 아니오 | 고급 override 옵션 |
| `metadata` | 아니오 | WAS 내부 추적용 데이터. provider로 전달하지 않음 |
| `providerOverride` | 아니오 | ai-engine Swagger/provider 진단용. 운영 WAS 요청에서는 보내지 않음 |

## 모델 매핑

Google/Veo는 WAS의 `model` tier를 아래 모델로 변환합니다.

| WAS 요청값 | 1순위 Google/Veo 모델 |
|---|---|
| `fast` | `google/veo-3.1-fast-generate-001` |
| `standard` | `google/veo-3.1-generate-001` |
| `lite` | `google/veo-3.1-lite-generate-001` |

예외: `referenceToVideo`는 Veo reference image 조합 안정성을 위해 `model` 요청값과 관계없이 `google/veo-3.1-generate-001`로 보정합니다.

Runway fallback은 task에 따라 다릅니다.

| task | WAS 요청값 | Runway fallback 모델 |
|---|---|---|
| `textToVideo` | `fast`, `standard`, `lite` | `runway/gen4.5` |
| `imageToVideo`, `referenceToVideo` | `fast`, `lite` | `runway/gen4_turbo` |
| `imageToVideo`, `referenceToVideo` | `standard` | `runway/gen4.5` |

`gen4_turbo`는 Runway image-to-video 후보로만 사용합니다. Runway text-to-video 직접 테스트와 fallback은 `gen4.5`를 사용합니다.

`providerOverride`가 없으면 Google/Veo를 먼저 실행하고 실패 시 Runway 후보로 fallback합니다. ai-engine Swagger에서 `providerOverride: "runway"`를 보내면 Veo를 건너뛰고 Runway 후보만 직접 테스트합니다. 이 필드는 backend DTO에 노출하지 않는 진단용 필드입니다.

Runway API의 현재 video generation duration은 2~10초 범위이므로 WAS 계약의 `4`, `6`, `8`초를 그대로 전달합니다. `ai-engine`은 Runway payload 생성 시 2~10초 범위만 방어적으로 허용합니다.

`referenceToVideo`는 Veo reference image 조합 안정성을 위해 자동 보정합니다.

- provider 모델: `google/veo-3.1-generate-001`
- duration: `8`초
- frontend에서 스타일 레퍼런스를 선택하면 요청 payload가 자동으로 `model=standard`, `durationSeconds=8`로 보정됩니다.
- ai-engine도 방어적으로 `referenceToVideo`를 standard/8초로 정규화합니다.

## Runway 직접 테스트

Runway fallback을 강제로 확인하려면 ai-engine Swagger에서 `/v1/video/jobs`에 `providerOverride: "runway"`를 포함합니다. 운영 frontend/WAS 경로에서는 이 필드를 보내지 않습니다.

필수 조건:

- `AI_PROVIDER_MODE=live`
- `RUNWAYML_API_SECRET` 설정
- Redis 실행
- FastAPI 서버 실행
- Celery worker 실행

Text to Video:

```json
{
  "jobId": "runway-text-test-1",
  "prompt": "따뜻한 조명의 동네 카페에서 시그니처 라떼가 테이블 위에 놓이고 카메라가 천천히 다가가는 숏폼 광고",
  "model": "fast",
  "providerOverride": "runway",
  "platform": "instagram_reels",
  "task": "textToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "advanced": {
    "generateAudio": false
  },
  "metadata": {
    "source": "ai-engine-swagger-runway-test"
  }
}
```

Image to Video:

```json
{
  "jobId": "runway-image-test-1",
  "prompt": "첫 프레임의 제품 구도는 유지하고, 따뜻한 자연광과 부드러운 카메라 푸시인으로 짧은 광고 영상 생성",
  "model": "standard",
  "providerOverride": "runway",
  "platform": "instagram_reels",
  "task": "imageToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_IMAGE_BYTES",
      "mimeType": "image/png"
    }
  },
  "advanced": {
    "generateAudio": false
  },
  "metadata": {
    "source": "ai-engine-swagger-runway-test"
  }
}
```

Runway `imageToVideo` fallback은 `bytesBase64Encoded` 또는 공개 접근 가능한 `https://` 이미지 URL을 사용합니다. `gs://` URI는 Runway가 직접 읽을 수 없으므로 Swagger 직접 테스트에는 사용하지 않습니다.

## task와 input 계약

WAS는 모든 영상 생성 요청에 `jobId`를 반드시 포함합니다. 외부 JSON 필드명은 `jobId`이고, `ai-engine` 내부 Python 코드는 `job_id`로 다룹니다.

WAS는 `task`를 반드시 명시합니다. `ai-engine`은 방어적으로 자동 추론을 지원하지만, WAS 연동에서는 사용하지 않습니다.

| task | input 규칙 |
|---|---|
| `textToVideo` | `input`을 보내지 않음 |
| `imageToVideo` | `input.image` 필수. `input.lastFrame`은 선택 |
| `referenceToVideo` | `input.referenceImages` 1~3장 필수 |

명시한 `task`와 입력이 충돌하면 `422 Validation Error`가 발생합니다.

`imageToVideo`에서 `input.image`와 `input.lastFrame`을 함께 쓰면 first/last frame interpolation으로 처리합니다. 이 모드는 두 이미지를 첫 장면과 마지막 장면으로 유지하는 제약이 강하므로, 프롬프트가 두 이미지와 다른 인물, 동물, 장소, 상품을 새로 추가하도록 요구하면 반영이 약하거나 누락될 수 있습니다.

예:

- `task=textToVideo`인데 `input.image`를 보내면 실패
- `task=imageToVideo`인데 `input.image`가 없으면 실패
- `task=referenceToVideo`인데 `input.referenceImages`가 없으면 실패

## 입력 이미지

현재 frontend 업로드 흐름은 로컬 파일을 browser에서 base64로 읽어 `bytesBase64Encoded`로 전달하는 방식을 우선 사용합니다.

```json
{
  "bytesBase64Encoded": "BASE64_IMAGE_BYTES",
  "mimeType": "image/jpeg"
}
```

URI 입력도 스키마상 지원합니다. 현재 운영 저장소는 로컬 우선이며, GCS storage로 이전할 때 `gcsUri` 입력을 본격적으로 사용할 수 있습니다.

```json
{
  "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
  "mimeType": "image/png"
}
```

제약:

- `mimeType`: `image/png` 또는 `image/jpeg`
- `gcsUri`와 `bytesBase64Encoded` 중 정확히 하나만 전달
- `referenceImages`: 1~3장
- `referenceImages`는 `image`, `lastFrame`과 같이 전달할 수 없음
- `lastFrame`은 `image`가 있을 때만 전달 가능

## 고급 설정

`advanced`는 바꾸고 싶은 값만 전달합니다. 생략한 값은 `ai-engine` 기본값을 사용합니다.

| 필드 | 기본값 | 설명 |
|---|---|---|
| `sampleCount` | `1` | 생성 개수. 1~4 |
| `resolution` | `720p` | `720p`, `1080p` |
| `enhancePrompt` | `true` | provider prompt enhancement |
| `generateAudio` | `true` | 오디오 생성 여부 |
| `compressionQuality` | `optimized` | `optimized`, `lossless` |
| `resizeMode` | `crop` | `crop`, `pad` |
| `negativePrompt` | 없음 | 제외할 요소 |
| `personGeneration` | 없음 | `dont_allow`, `allow_adult`, `allowAll` |
| `seed` | 없음 | 0~2147483647 |
| `storageUri` | 없음 | provider 출력 GCS 경로. 현재 로컬 storage 우선 흐름에서는 일반적으로 사용하지 않음 |
| `pubsubTopic` | 없음 | provider progress Pub/Sub topic |

`fps`는 요청 필드가 아닙니다. Veo 3.1은 24 FPS를 사용하므로 WAS에서 설정하지 않습니다.

Veo 3.1 계열에서는 `generateAudio=true`가 기본 정책입니다. ai-engine은 Google provider 호출 시 `true`를 명시적으로 보내지 않고 모델 기본 오디오 동작에 맡깁니다. `generateAudio=false`일 때만 `generate_audio=false`를 provider config에 전달합니다. 이는 Vertex/Gemini API surface별 `generate_audio=true` 처리 차이 때문에 오디오가 빠지는 회귀를 피하기 위한 정책입니다.

## Text to Video 예시

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "벚꽃이 만발한 호숫가 근처를 골드리트리버와 함께 한 남자가 걷고 있어",
  "model": "fast",
  "platform": "youtube_shorts",
  "task": "textToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "advanced": {
    "generateAudio": true
  },
  "metadata": {
    "campaignId": "campaign-1"
  }
}
```

curl:

```bash
curl -X POST 'http://127.0.0.1:8002/v1/video/jobs' \
  -H 'accept: application/json' \
  -H 'X-Internal-Token: change-this-internal-token' \
  -H 'Content-Type: application/json' \
  -d '{
    "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
    "prompt": "벚꽃이 만발한 호숫가 근처를 골드리트리버와 함께 한 남자가 걷고 있어",
    "model": "fast",
    "platform": "youtube_shorts",
    "task": "textToVideo",
    "aspectRatio": "9:16",
    "durationSeconds": 4,
    "advanced": {
      "generateAudio": true
    },
    "metadata": {
      "campaignId": "campaign-1"
    }
  }'
```

## Image to Video 예시

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성",
  "model": "fast",
  "platform": "instagram_reels",
  "task": "imageToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_IMAGE_BYTES",
      "mimeType": "image/png"
    }
  }
}
```

첫 프레임과 마지막 프레임을 함께 지정할 수도 있습니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "첫 장면에서 마지막 장면으로 자연스럽게 이어지는 숏폼 생성",
  "model": "fast",
  "task": "imageToVideo",
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_START_FRAME_BYTES",
      "mimeType": "image/png"
    },
    "lastFrame": {
      "bytesBase64Encoded": "BASE64_END_FRAME_BYTES",
      "mimeType": "image/png"
    }
  }
}
```

## Reference to Video 예시

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "prompt": "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성",
  "model": "standard",
  "platform": "tiktok",
  "task": "referenceToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "input": {
    "referenceImages": [
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_BYTES",
        "mimeType": "image/png"
      }
    ]
  }
}
```

주의:

- Veo 3.1 production 모델은 reference image to video 지원 여부가 모델/버전에 따라 다를 수 있습니다.
- 실패 시 status의 `error` 필드를 WAS 로그에 남겨야 합니다.

## 생성 응답

생성 요청은 즉시 job을 반환합니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "queued",
  "message": "숏폼 영상 생성이 시작되었습니다. task=textToVideo"
}
```

WAS는 이미 저장한 `jobId`의 상태를 `pending`에서 `queued` 또는 `processing`으로 갱신하고, 이후 callback으로 상태를 업데이트합니다.

## Callback 전달 계약

`ai-engine`은 비디오 job 상태를 frontend에 직접 제공하지 않습니다. 운영 흐름에서 frontend status API의 source of truth는 backend WAS DB입니다. `ai-engine`은 provider 실행 중 발생한 진행률과 최종 결과를 Spring Boot WAS callback endpoint로 push합니다.

Callback URL은 `ai-engine/.env`의 `WAS_BASE_URL` 기준으로 생성됩니다.

```env
WAS_BASE_URL=http://localhost:8080
WAS_INTERNAL_TOKEN=change-this-internal-token
WAS_CALLBACK_TIMEOUT_SEC=1.0
```

Docker Compose로 ai-engine을 실행하고 Spring Boot backend가 host에서 `8080`으로 실행 중이면, 컨테이너 내부의 `localhost`는 host가 아니므로 아래처럼 설정합니다.

```env
WAS_BASE_URL=http://host.docker.internal:8080
```

Callback endpoint:

```http
POST /internal/callback/jobs/{jobId}/progress
POST /internal/callback/jobs/{jobId}
```

모든 callback에는 내부 토큰을 포함합니다.

```http
X-Internal-Token: {WAS_INTERNAL_TOKEN}
```

현재 callback 송신 구현:

```text
ai-engine/app/services/callbacks.py
```

Callback 송신은 일시적인 backend 지연이나 네트워크 흔들림에 대비해 최대 3회 재시도합니다. 재시도는 provider 작업을 다시 실행하는 것이 아니라, 이미 계산된 progress/result payload를 backend WAS에 다시 전달하는 동작입니다. Spring Boot callback API는 같은 `jobId` callback이 중복 도착해도 같은 결과가 되도록 idempotent하게 처리해야 합니다.

비디오 worker는 아래 순서로 callback을 보냅니다. `progress=5`, `progress=90`은 Veo/Runway provider가 제공하는 실제 진행률이 아니라 backend와 frontend가 상태 문구를 전환하기 위한 synthetic progress hint입니다.

1. 작업 시작 직후 `progress=5` (`started`)
2. provider 생성 완료 후 storage 저장 전 `progress=90` (`finalizing`)
3. storage 저장 완료 후 `completed`
4. 예외 발생 시 `failed`

Progress callback:

```json
{
  "progress": 5
}
```

Completed callback:

```json
{
  "status": "completed",
  "resultUrl": "http://127.0.0.1:8002/gaim/generated/videos/c2814445-0491-432a-ad99-268a6b3e7440.mp4",
  "durationMs": 12345,
  "provider": "google",
  "modelUsed": "veo-3.1-fast-generate-001",
  "fallbackUsed": false,
  "warnings": []
}
```

Spring Boot WAS는 `resultUrl`을 DB의 `videoUrl` 또는 결과 URL 컬럼에 저장하고, frontend 상태 응답에서는 `videoUrl`로 노출합니다.

Failed callback:

```json
{
  "status": "failed",
  "error": "provider request failed",
  "durationMs": 12345,
  "warnings": [
    "Rank 1 google/veo-3.1-fast-generate-001 failed: provider request failed",
    "Rank 2 runway/gen4.5 failed: provider authentication failed"
  ]
}
```

Celery task result는 더 이상 무조건 `queued`로 남지 않습니다. worker가 provider 실행을 마치면 Redis result backend에는 실제 최종 상태와 callback 전송 성공 여부가 남습니다. 이 값은 운영 source of truth가 아니라 장애 분석용 관측 데이터입니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "videoUrl": "http://127.0.0.1:8002/gaim/generated/videos/c2814445-0491-432a-ad99-268a6b3e7440.mp4",
  "durationMs": 12345,
  "provider": "google",
  "modelUsed": "veo-3.1-fast-generate-001",
  "fallbackUsed": false,
  "warnings": [],
  "callbacks": {
    "started": true,
    "finalizing": true,
    "completed": true
  }
}
```

Backend WAS 권장 상태 전이:

| 시점 | WAS DB status | 설명 |
|---|---|---|
| WAS 생성 요청 수신 | `queued` 또는 `pending` | `jobId`, 사용자, 사업장, 요청 payload 저장 |
| `/v1/video/jobs` queued 응답 | `queued` | ai-engine queue 등록 확인 |
| progress callback | `processing` | `progressPct` 갱신 |
| completed callback | `completed` | `resultUrl`, `provider`, `modelUsed`, `fallbackUsed`, `warnings`, `durationMs`, `progressPct=100` 저장 |
| failed callback | `failed` | `error`, `warnings`, `durationMs`, `progressPct=100` 저장 |

운영 주의사항:

- `completed`, `failed`는 terminal status입니다.
- terminal status 이후 늦게 도착한 progress callback은 무시합니다.
- callback은 중복 도착할 수 있으므로 `jobId` 기준 idempotent하게 처리합니다.
- ai-engine의 queued 응답이 늦게 도착해도 이미 `processing`, `completed`, `failed`로 진행된 DB 상태를 `queued`로 되돌리지 않습니다.
- `processing` 이후 `queued`로 되돌리는 상태 역전은 허용하지 않습니다.
- callback이 유실될 수 있으므로 오래 `queued` 또는 `processing`에 머문 job은 backend scheduled reconciler가 ai-engine 상태 조회 API로 보정하는 fallback polling을 둘 수 있습니다.
- `provider=runway` 또는 `fallbackUsed=true`면 Runway fallback 결과입니다. 현재 Runway fallback 영상은 별도 오디오 합성 없이 무음으로 취급합니다.
- 상세 Spring Boot Controller/DTO 예시는 [Spring Boot 연동 가이드](./springboot-video-generate-guide-v1.2.md)를 기준으로 합니다.

## 상태 조회

```bash
curl -X GET 'http://127.0.0.1:8080/api/ai/video/async/job/f3325b10-bfcc-4ef3-814e-b1fcd47338fd'
```

`GET /v1/video/status/{jobId}`는 개발 확인 및 Spring Boot reconciler fallback용이며 Swagger에서 deprecated로
표시됩니다. 운영 상태의 source of truth는 WAS DB입니다.

Veo 오디오 생성 여부를 확인할 때는 상태 응답의 `provider`, `modelUsed`, `fallbackUsed`를 먼저 확인합니다. `provider=google`, `modelUsed=veo-3.1-*`, `fallbackUsed=false`면 Veo 결과이고, `provider=runway` 또는 `fallbackUsed=true`면 Runway fallback 결과입니다. Runway fallback 영상은 현재 별도 오디오 합성 없이 무음으로 취급합니다.

진행 중:

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "processing",
  "videoUrl": null,
  "error": null,
  "progressPct": 5
}
```

완료:

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "videoUrl": "http://127.0.0.1:8002/gaim/generated/videos/c2814445-0491-432a-ad99-268a6b3e7440.mp4",
  "error": null,
  "progressPct": 100,
  "provider": "google",
  "modelUsed": "veo-3.1-fast-generate-001",
  "fallbackUsed": false,
  "warnings": []
}
```

실패:

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "failed",
  "videoUrl": null,
  "error": "Provider error message",
  "progressPct": 100,
  "warnings": [
    "Rank 1 google/veo-3.1-fast-generate-001 failed: provider request failed",
    "Rank 2 runway/gen4.5 failed: provider authentication failed"
  ]
}
```

## Polling 권장

- 최초 요청 후 5~10초 간격으로 조회
- 현재 frontend 구현은 약 7초 간격으로 `/api/ai/video/async/job/{jobId}`를 조회
- `completed` 또는 `failed`가 되면 polling 종료
- `VIDEO_MAX_WAIT_SEC` 기본값은 600초
- WAS는 생성 요청을 오래 붙잡지 않고 job 등록 응답을 즉시 반환해야 합니다.

## 저장 위치

로컬 storage 기준:

```text
{STORAGE_BASE_DIR}/videos/{uuid}.mp4
```

현재 개발 환경 예:

```text
/Users/mjkim/project/G-AIM/GAIM_Org/storage-data/videos/{uuid}.mp4
```

외부 URL:

```text
{STORAGE_PUBLIC_BASE_URL}/videos/{uuid}.mp4
```

현재는 GCS에 생성 결과를 저장하지 않습니다. 추후 GCS/S3 등 외부 storage로 이전하면 `StorageAdapter` 구현과 `STORAGE_PUBLIC_BASE_URL` 정책이 바뀔 수 있으며, 입력 이미지도 `gcsUri` 중심으로 전환할 수 있습니다.

## 자주 발생하는 오류

### 422 Validation Error

주요 원인:

- `X-Internal-Token` 헤더 누락
- `durationSeconds`가 `4`, `6`, `8`이 아님
- `task=textToVideo`인데 `input`을 같이 전달
- `gcsUri`와 `bytesBase64Encoded`를 동시에 전달
- `referenceImages`와 `image`/`lastFrame`을 같이 전달

### 404 model not found

Veo 모델 location이 잘못된 경우입니다.

`GCP_VIDEO_LOCATION=us-central1` 설정을 확인합니다.

### Unsupported output video frame rate

`fps`를 provider에 전달하면 발생할 수 있습니다. WAS 요청에는 `fps`를 넣지 않습니다.

### Mock video generation does not create playable MP4

`AI_PROVIDER_MODE=mock` 상태입니다. 실제 영상을 만들려면 `AI_PROVIDER_MODE=live`가 필요합니다.

### generateAudio=true인데 오디오가 없음

확인 순서:

1. 상태 응답의 `provider`, `modelUsed`, `fallbackUsed`를 확인합니다.
2. `provider=runway` 또는 `fallbackUsed=true`면 Runway fallback 결과이므로 현재 경로에서는 무음입니다.
3. `provider=google`이고 `modelUsed=veo-3.1-*`이면 Veo 결과입니다. 이 경우 prompt에 명시적인 audio cue가 있는지 확인합니다.
4. 결과 mp4 파일을 `ffprobe`로 확인해 오디오 stream이 실제로 없는지 확인합니다.

대사/나레이션을 유도하려면 prompt에 직접 포함합니다.

```text
Cheerful Korean female narrator says: "사랑스런 감자밭 카페에 오세요."
Soft acoustic background music and gentle cafe ambience.
```

## WAS 구현 체크리스트

1. 생성 요청을 보낸다.
2. WAS가 발급한 `jobId`를 요청에 포함한다.
3. ai-engine callback으로 progress/completed/failed를 수신한다.
4. `completed`면 `videoUrl`을 저장한다.
5. `failed`면 `error`를 WAS 로그와 사용자-facing 실패 상태에 반영한다.
6. `videoUrl`은 MP4 파일 URL이며 브라우저/프론트에서 직접 재생 가능하다.
