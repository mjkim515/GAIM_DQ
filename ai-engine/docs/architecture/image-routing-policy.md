# 이미지 모델 라우팅 정책

> Version: v1.1

## 운영 진입점

이미지 생성의 활성 운영 진입점은 `POST /v1/image/jobs`입니다.

```text
backend WAS -> ai-engine POST /v1/image/jobs
ai-engine worker -> provider routing/generation
ai-engine worker -> backend WAS callback(progress/completed/failed)
frontend -> backend WAS GET /api/ai/image/async/job/{jobId}
```

`POST /v1/image/generate` 동기 경로는 더 이상 운영 경로가 아니며, 코드에서도 라우트 등록이 주석 처리되어 Swagger에 노출되지 않습니다.

## 핵심 원칙

1. 텍스트 렌더링 요청이 있으면 OpenAI GPT Image를 우선 사용합니다.
2. OpenAI 텍스트 렌더링이 실패하면 Google Nano Banana로 fallback합니다.
3. 텍스트가 없고 참조 이미지가 있으면 Google Nano Banana를 우선 사용합니다.
4. 텍스트와 참조 이미지가 모두 없으면 Google Nano Banana를 우선 사용합니다.
5. 브랜드 목소리와 카피 말투는 텍스트 API 전용 입력입니다. 이미지 API는 비주얼 무드만 받습니다.
6. 모든 provider 후보가 실패하면 local placeholder를 반환합니다.
7. 운영 흐름에서는 routing 결과와 warning이 job 완료 callback/status payload에 반영됩니다.

## 모델군

### Google

- Nano Banana: `gemini-2.5-flash-image`

### OpenAI

| 역할 | 환경 변수 | 기본 모델 |
|---|---|---|
| 텍스트 정확도 | `OPENAI_TEXT_ACCURACY_IMAGE_MODEL` | `gpt-image-2` |
| 고품질 생성 | `OPENAI_QUALITY_IMAGE_MODEL` | `gpt-image-2` |
| 표준 생성 | `OPENAI_STANDARD_IMAGE_MODEL` | `gpt-image-1.5` |
| 비용/속도 fallback | `OPENAI_FAST_IMAGE_MODEL` | `gpt-image-1-mini` |
| 참조 이미지 편집 | `OPENAI_EDIT_IMAGE_MODEL` | `gpt-image-2` |

## `/v1/image/jobs` 후보 순서

아래 후보 순서는 `POST /v1/image/jobs`로 등록된 이미지 worker job이 실제 provider를 실행할 때 적용합니다.

### 텍스트 + 참조 이미지

1. OpenAI `OPENAI_TEXT_ACCURACY_IMAGE_MODEL`, edit
2. Google `gemini-2.5-flash-image`, edit
3. local `default-placeholder`

### 텍스트만 있음

1. OpenAI `OPENAI_TEXT_ACCURACY_IMAGE_MODEL`, generate
2. Google `gemini-2.5-flash-image`, generate
3. local `default-placeholder`

### 참조 이미지만 있음

1. Google `gemini-2.5-flash-image`, edit
2. OpenAI `OPENAI_EDIT_IMAGE_MODEL`, edit
3. local `default-placeholder`

### 브랜드 요청

조건:

```text
purpose = 브랜드 / brand
```

후보:

1. Google `gemini-2.5-flash-image`
2. OpenAI `OPENAI_QUALITY_IMAGE_MODEL`
3. local `default-placeholder`

### 일반 홍보/이벤트 요청

1. Google `gemini-2.5-flash-image`
2. OpenAI `OPENAI_STANDARD_IMAGE_MODEL`
3. local `default-placeholder`

`visual_mood`는 모델 선택 조건이 아니라 최종 이미지 프롬프트와 OpenAI `style` 파생값에 사용합니다. frontend에서는 `비주얼 무드 (선택)`으로 표시되며, 기본값은 `bright`입니다. 기본 화면에는 `현재 설정값 : 밝고 화사한`만 보이고, `옵션 더보기`를 눌렀을 때 나머지 무드 옵션이 표시됩니다.

| UI 라벨 | visual_mood | 프롬프트 변환 | OpenAI style |
|---|---|---|---|
| 밝고 화사한 | `bright` | 깨끗하고 밝은 하이키 조명, 선명한 색감 | `vivid` |
| 따뜻하고 아늑한 | `warm_cozy` | 따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기 | `natural` |
| 감성적이고 깊이 있는 | `moody` | 분위기 있는 저조도 조명, 깊이 있는 색감 | `natural` |
| 깔끔하고 미니멀한 | `clean_minimal` | 미니멀한 구성, 넉넉한 여백, 중립적인 색감 | `natural` |
| 고급스럽고 세련된 | `premium` | 고급스러운 질감, 정제된 구도, 세련된 시각 연출 | `natural` |
| 선명하고 생동감 | `vibrant` | 높은 채도, 활기찬 분위기, 강한 색 대비 | `vivid` |

OpenAI style은 provider 요청 객체의 파생값입니다. Provider별 SDK 호출에서 style 지원 여부가 다를 수 있으므로, 실제 전달 여부는 OpenAI service 구현의 지원 모델 조건을 따릅니다. 어떤 경우에도 프롬프트 변환은 항상 적용됩니다.

## 크기 정책

Google은 채널별 aspect ratio를 사용합니다.

| 채널 | 크기 |
|---|---|
| `instagram_feed` | `1:1` |
| `instagram_story` | `9:16` |
| `instagram_reels` | `9:16` |
| `naver_place` | `1:1` |
| `blog` | `16:9` |
| `banner` | `16:9` |
| `custom` | `1:1` |

OpenAI는 채널별 pixel size를 사용합니다.

| 채널 | 크기 |
|---|---|
| `instagram_feed` | `1024x1024` |
| `instagram_story` | `1024x1536` |
| `instagram_reels` | `1024x1536` |
| `naver_place` | `1024x1024` |
| `blog` | `1536x1024` |
| `banner` | `1536x1024` |
| `custom` | `1024x1024` |

## 검증 정책

- OpenAI provider는 `OPENAI_IMAGE_MODELS`에 있는 모델만 허용합니다.
- Google provider는 `NANO_BANANA_MODELS`에 있는 모델만 허용합니다.
- Imagen 4 모델은 2026-08-17 shutdown 이후 지원하지 않습니다.
- Nano Banana 참조 이미지는 최대 14장입니다.
- OpenAI 참조 이미지는 최대 10장입니다.

## Fallback warning

텍스트 요청에서 OpenAI가 실패하고 Nano Banana로 fallback하면 job 완료 callback/status payload의 routing warning에 아래 메시지를 포함할 수 있습니다.

```json
{
  "warnings": [
    "OpenAI text rendering failed; fell back to Google Nano Banana, Korean text accuracy may be lower."
  ]
}
```

## 테스트용 provider 직접 호출

아래 API는 provider 동작을 직접 확인하기 위한 테스트용/비운영 경로입니다.

- `POST /v1/image/provider-generate`
- `POST /v1/image/provider-generate-with-reference`
- `POST /v1/image/intent` (deprecated)

운영 연동과 frontend/backend 정식 흐름은 항상 `POST /v1/image/jobs`를 기준으로 합니다.
