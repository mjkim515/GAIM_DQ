# 이미지 생성 API 가이드

> Version: v1.1

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

Swagger:

```text
http://127.0.0.1:8002/docs
```

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
- [Spring Boot 연동 가이드](./springboot-image-generate-guide-v1.1.md)
