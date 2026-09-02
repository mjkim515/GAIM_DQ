# 이미지 생성 API 가이드

> Version: v1.2

## 요약

`POST /v1/image/jobs`는 ai-engine 내부 이미지 생성 Job 등록 API입니다. frontend는 Spring Boot의 `POST /api/ai/image/async/generate`를 호출하고, backend가 `jobId`를 발급해 내부 토큰과 함께 `POST /v1/image/jobs`로 전달합니다.

클라이언트는 OpenAI/Google 모델명을 직접 고르지 않습니다. 목적, 비주얼 무드, 이미지 채널, 프롬프트, 참조 이미지, 텍스트 렌더링 정보를 전달하면 `ai-engine` worker가 내부에서 모델 후보를 선택하고 fallback까지 처리합니다.

`POST /v1/image/jobs`는 최종 이미지를 동기 반환하지 않습니다. 생성 결과는 ai-engine callback으로 backend WAS에 반영되고, frontend는 `GET /api/ai/image/async/job/{jobId}`를 polling합니다.

기존 `POST /v1/image/intent`는 테스트/호환용으로만 유지하며 deprecated 상태입니다. `POST /v1/image/generate` 동기 라우트는 비활성/주석 처리되어 Swagger에 노출되지 않습니다.

## 엔드포인트

Frontend -> Backend:

```http
POST /api/ai/image/async/generate
Content-Type: application/json
```

```http
GET /api/ai/image/async/job/{jobId}
```

Backend -> ai-engine:

```http
POST /v1/image/jobs
X-Internal-Token: {WAS_INTERNAL_TOKEN}
Content-Type: application/json
```

Callback 유실 보정용 ai-engine fallback 조회:

```http
GET /v1/image/status/{jobId}
X-Internal-Token: {WAS_INTERNAL_TOKEN}
```

이 status API는 frontend 직접 호출용이 아닙니다. Spring Boot scheduled reconciler가 callback 유실을 보정할 때만
사용합니다.

Swagger:

```text
http://127.0.0.1:8002/docs
```

## 상태 동기화 원칙

정상 경로는 ai-engine의 callback push입니다. ai-engine status API 조회는 callback push를 대체하지 않습니다.

1. frontend는 Spring Boot의 `GET /api/ai/image/async/job/{jobId}`만 polling합니다.
2. ai-engine worker는 `progress 5`, `progress 90`, `completed` 또는 `failed` callback을 Spring Boot로 push합니다.
3. Spring Boot는 callback을 받아 WAS DB 상태를 갱신합니다.
4. `GET /v1/image/status/{jobId}`는 Spring Boot scheduled reconciler만 사용하는 fallback 조회 API입니다.
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

## 요청 필드

| 필드 | 필수 | 설명 |
|---|---:|---|
| `purpose` | 예 | `홍보`, `이벤트`, `브랜드` 또는 `promotion`, `event`, `brand` |
| `visual_mood` | 아니오 | 이미지 전용 비주얼 무드. `bright`, `warm_cozy`, `moody`, `clean_minimal`, `premium`, `vibrant`. 기본 `bright` |
| `channels` | 예 | 이미지 규격 채널 목록. 첫 번째 값이 primary channel |
| `image_prompt` | 예 | 이미지 설명 |
| `reference_images` | 아니오 | 참조 이미지 목록 |
| `text_to_render` | 아니오 | 이미지 안에 정확히 넣을 문구 |
| `text_rendering` | 아니오 | 문구, 언어, 위치, 폰트/색상 힌트 |
| `n` | 아니오 | 생성 장수. 기본 1, 최대 4 |

`text_rendering.text`가 있고 `text_to_render`가 없으면 서버가 자동으로 `text_to_render`에 반영합니다.

backend가 ai-engine에 전달하는 `ImageJobRequest`에는 위 필드에 더해 WAS가 발급한 `jobId`가 포함됩니다.

### Frontend 입력 매핑

현재 frontend는 단일 `ImageGeneration` 화면에서 설정, 생성 요청, 결과 확인을 처리합니다. 기존 `PresetStep`, `ImageSetupStep`, `ImageSetupResult` 3단계 화면은 사용하지 않습니다.

| UI 항목 | API 반영 |
|---|---|
| 목적: 홍보 / 이벤트 / 브랜드 | `purpose`: `promotion` / `event` / `brand` |
| 플랫폼 프리셋 | `channels[0]` |
| 생성 개수 | `n` |
| 비주얼 무드 (선택) | `visual_mood`; 기본 `bright` |
| 생성할 이미지 설명 | `image_prompt` |
| 이미지 텍스트 삽입하기 | `text_to_render`, `text_rendering` |
| 참조 이미지 사용하기 | `reference_images` |

플랫폼 프리셋 매핑:

| UI 프리셋 | API channel | 기본 UI 비율 |
|---|---|---|
| Instagram 피드 | `instagram` | `1:1` |
| Instagram 스토리 | `instagram_story` | `9:16` |
| Instagram 릴스 | `instagram_reels` | `9:16` |
| 블로그/상세페이지 | `blog` | `16:9` |
| 네이버 플레이스 | `naver_place` | `1:1` |
| 배너/팝업 | `banner` | `16:9` |
| 직접 설정 | `custom` | `1:1` |

비주얼 무드는 frontend에서 `비주얼 무드 (선택)`으로 표시됩니다. 기본 화면에는 `현재 설정값 : 밝고 화사한`과 `옵션 더보기` 버튼만 보이며, 버튼을 누르면 나머지 무드 옵션이 펼쳐집니다. 사용자가 직접 선택하지 않아도 기본값 `bright`가 사용됩니다.

| UI 라벨 | `visual_mood` | 프롬프트 힌트 | OpenAI style 파생값 |
|---|---|---|---|
| 밝고 화사한 | `bright` | 깨끗하고 밝은 하이키 조명, 선명한 색감 | `vivid` |
| 따뜻하고 아늑한 | `warm_cozy` | 따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기 | `natural` |
| 감성적이고 깊이 있는 | `moody` | 분위기 있는 저조도 조명, 깊이 있는 색감 | `natural` |
| 깔끔하고 미니멀한 | `clean_minimal` | 미니멀한 구성, 넉넉한 여백, 중립적인 색감 | `natural` |
| 고급스럽고 세련된 | `premium` | 고급스러운 질감, 정제된 구도, 세련된 시각 연출 | `natural` |
| 선명하고 생동감 | `vibrant` | 높은 채도, 활기찬 분위기, 강한 색 대비 | `vivid` |

`visual_mood`는 모델 선택 조건이 아니라 최종 이미지 프롬프트의 시각 무드 힌트로 삽입됩니다. OpenAI 후보 요청에는 `bright`/`vibrant`는 `vivid`, 나머지는 `natural`로 파생됩니다.

현재 frontend에서 파일로 업로드한 참조 이미지는 backend 요청 전에 base64 payload로 변환됩니다.

```json
{
  "b64_json": "BASE64_IMAGE_BYTES",
  "mime_type": "image/png"
}
```

URL 기반 참조 이미지도 스키마상 사용할 수 있지만, 현재 frontend 업로드 흐름은 `b64_json`을 우선 사용합니다.

## 기본 생성 예시

```json
{
  "purpose": "홍보",
  "channels": ["instagram"],
  "image_prompt": "신선한 과일을 판매하는 밝고 깔끔한 상점 이미지",
  "visual_mood": "warm_cozy",
  "n": 3
}
```

예상 라우팅:

1. Google `gemini-2.5-flash-image`
2. OpenAI standard image model
3. local placeholder

## 텍스트 삽입 예시

```json
{
  "purpose": "홍보",
  "channels": ["instagram"],
  "image_prompt": "과일 가게 할인 행사 홍보 이미지",
  "text_rendering": {
    "text": "오늘 딸기 30% 할인",
    "language": "ko",
    "placement": "bottom",
    "must_render_exactly": true
  },
  "visual_mood": "vibrant",
  "n": 1
}
```

예상 라우팅:

1. OpenAI `gpt-image-2`
2. Google `gemini-2.5-flash-image`
3. local placeholder

## 참조 이미지 기반 텍스트 삽입 예시

```json
{
  "purpose": "이벤트",
  "channels": ["instagram"],
  "image_prompt": "참조 이미지를 기반으로 봄맞이 이벤트 광고 이미지로 편집하고 문구를 넣어줘",
  "reference_images": [
    {
      "b64_json": "BASE64_IMAGE_BYTES",
      "mime_type": "image/png"
    }
  ],
  "text_to_render": "오늘의 신선 과일",
  "visual_mood": "bright",
  "n": 1
}
```

예상 라우팅:

1. OpenAI `gpt-image-2` edit
2. Google `gemini-2.5-flash-image` edit
3. local placeholder

## Job 응답 구조

`POST /api/ai/image/async/generate`와 `POST /v1/image/jobs`는 최종 이미지가 아니라 queued job을 반환합니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "queued",
  "message": "이미지 생성 작업이 큐에 등록되었습니다."
}
```

## 상태 응답 구조

frontend는 backend WAS의 `GET /api/ai/image/async/job/{jobId}`를 polling합니다. 완료 상태에는 생성 이미지 URL과 provider 정보가 포함됩니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "images": ["http://127.0.0.1:8002/gaim/generated/images/xxx.png"],
  "modelUsed": "gemini-2.5-flash-image",
  "provider": "google",
  "error": null,
  "progressPct": 100,
  "routing": {
    "primary_channel": "instagram_feed",
    "final_prompt": "...",
    "selected_rank": 1,
    "selected": {
      "rank": 1,
      "provider": "google",
      "model": "gemini-2.5-flash-image",
      "operation": "generate",
      "size": "1:1",
      "n": 3,
      "reason": "..."
    },
    "attempted_models": [],
    "fallback_used": false,
    "warnings": []
  }
}
```

확인할 필드:

- `status`: `queued`, `processing`, `completed`, `failed`
- `images`: 생성된 이미지 URL
- `modelUsed`: 실제 성공한 모델
- `provider`: 실제 성공한 provider
- `progressPct`: 진행률
- `error`: 실패 사유
- `routing.final_prompt`: provider에 전달된 최종 프롬프트
- `routing.selected`: 선택된 후보
- `routing.attempted_models`: 실제 시도한 후보 목록
- `routing.fallback_used`: fallback 발생 여부
- `routing.warnings`: provider 실패 또는 품질 경고

## Callback 전달 계약

`ai-engine`은 이미지 job 상태를 frontend에 직접 제공하지 않습니다. 운영 흐름에서 frontend status API의 source of truth는 backend WAS DB입니다. `ai-engine`은 provider 실행 중 발생한 진행률과 최종 결과를 Spring Boot WAS callback endpoint로 push합니다.

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

이미지 worker는 아래 순서로 callback을 보냅니다. `progress=5`, `progress=90`은 OpenAI/Google provider가 제공하는 실제 진행률이 아니라 backend와 frontend가 상태 문구를 전환하기 위한 synthetic progress hint입니다.

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
  "images": [
    "http://127.0.0.1:8002/gaim/generated/images/358dd53d-6983-42b1-a949-f3dd71f25684.png"
  ],
  "provider": "google",
  "modelUsed": "gemini-2.5-flash-image",
  "durationMs": 12345
}
```

Failed callback:

```json
{
  "status": "failed",
  "error": "provider request failed",
  "durationMs": 12345
}
```

Celery result backend에는 provider 작업 결과와 함께 callback 전송 성공 여부가 남습니다. 이 값은 운영 source of truth가 아니라 장애 분석용 관측 데이터입니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "images": [
    "http://127.0.0.1:8002/gaim/generated/images/358dd53d-6983-42b1-a949-f3dd71f25684.png"
  ],
  "provider": "google",
  "modelUsed": "gemini-2.5-flash-image",
  "durationMs": 12345,
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
| `/v1/image/jobs` queued 응답 | `queued` | ai-engine queue 등록 확인 |
| progress callback | `processing` | `progressPct` 갱신 |
| completed callback | `completed` | `images`, `provider`, `modelUsed`, `durationMs`, `progressPct=100` 저장 |
| failed callback | `failed` | `error`, `durationMs`, `progressPct=100` 저장 |

운영 주의사항:

- `completed`, `failed`는 terminal status입니다.
- terminal status 이후 늦게 도착한 progress callback은 무시합니다.
- callback은 중복 도착할 수 있으므로 `jobId` 기준 idempotent하게 처리합니다.
- ai-engine의 queued 응답이 늦게 도착해도 이미 `processing`, `completed`, `failed`로 진행된 DB 상태를 `queued`로 되돌리지 않습니다.
- `processing` 이후 `queued`로 되돌리는 상태 역전은 허용하지 않습니다.
- callback이 유실될 수 있으므로 오래 `queued` 또는 `processing`에 머문 job은 backend scheduled reconciler가 ai-engine 상태 조회 API로 보정하는 fallback polling을 둘 수 있습니다.
- 상세 Spring Boot Controller/DTO 예시는 [Spring Boot 연동 가이드](./springboot-image-generate-guide-v1.2.md)를 기준으로 합니다.

## Frontend 사용 흐름

이미지 생성 화면은 단일 `ImageGeneration` 화면에서 필요에 따라 텍스트 API를 먼저 호출한 뒤 이미지 API를 호출합니다.

1. 플랫폼 프리셋, 생성 개수, 목적, 프롬프트를 한 화면에서 설정합니다.
2. `비주얼 무드 (선택)`은 기본 `bright`로 시작하며, `옵션 더보기`를 눌러 변경할 수 있습니다.
3. 프롬프트를 다듬을 때 frontend가 `/api/text/refine`에 `mode=content_prompt_rewrite`로 요청합니다.
4. 이미지 안에 넣을 광고 문구가 필요하면 `/api/text/marketing`에 `content_type=ad_copy`로 요청하거나, 사용자가 직접 입력한 문구를 `text_to_render`로 전달합니다.
5. 참조 이미지 파일은 browser에서 `b64_json`, `mime_type` payload로 변환합니다.
6. frontend가 `/api/ai/image/async/generate`로 이미지 생성을 요청합니다.
7. backend가 `jobId`를 발급하고 `/v1/image/jobs`로 전달합니다.
8. ai-engine worker가 모델 라우팅과 fallback을 처리하고 backend WAS callback으로 상태를 갱신합니다.
9. frontend가 `/api/ai/image/async/job/{jobId}`를 polling해 진행률과 완료 이미지를 표시합니다.

## 관련 문서

- [모델 라우팅 정책](../internal-docs/image-routing-policy-v1.1.md)
- [코드 실행 흐름](../internal-docs/image-code-flow-v1.1.md)
- [Spring Boot 연동 가이드](./springboot-image-generate-guide-v1.2.md)
