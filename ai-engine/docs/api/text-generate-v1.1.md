# 텍스트 생성 API 가이드

> Version: v1.1

## 요약

`ai-engine`의 텍스트 API는 로컬 비즈니스 마케팅 문구를 생성하거나 기존 입력 문구를 목적에 맞게 다듬는 내부 API입니다.

Spring Boot WAS가 프론트엔드 입력을 받아 내부 토큰을 붙여 `ai-engine`으로 전달합니다. OpenAI 모델명과 API Key는 클라이언트가 다루지 않습니다.

```text
frontend /api/text/brand     -> backend -> ai-engine /v1/text/brand
frontend /api/text/marketing -> backend -> ai-engine /v1/text/marketing
frontend /api/text/refine    -> backend -> ai-engine /v1/text/refine
```

권장 API:

- `POST /v1/text/brand`: 브랜드 프로필 기반 텍스트 생성
- `POST /v1/text/marketing`: 상품/주제 기반 마케팅 텍스트 생성
- `POST /v1/text/refine`: 기존 입력 문구 또는 콘텐츠 생성 프롬프트 개선

테스트/호환용 `POST /v1/text/generate`는 유지하지만 신규 기능은 목적별 엔드포인트를 사용합니다.

## 엔드포인트

```http
POST /v1/text/brand
POST /v1/text/marketing
POST /v1/text/refine
POST /v1/text/generate - 테스트용
X-Internal-Token: {WAS_INTERNAL_TOKEN}
Content-Type: application/json
```

Swagger:

```text
http://127.0.0.1:8002/docs
```

## 공통 응답

```json
{
  "content": "강원도 수제 감자빵, 촉촉한 식감으로 오늘의 간식을 특별하게 만들어보세요.",
  "model_used": "gpt-4o-mini",
  "tokens_used": 120
}
```

- `content`: 생성 또는 개선된 최종 텍스트
- `model_used`: 실제 사용 모델. mock 모드에서는 `mock:{model}`
- `tokens_used`: provider가 반환한 토큰 수. mock 모드에서는 추정값

## 모델 선택 정책

`/v1/text/marketing`은 요청 본문에서 `model`을 받지 않습니다. ai-engine 내부 정책으로 모델을 선택합니다.

현재 정책:

| endpoint | 조건 | 선택 모델 |
|---|---|---|
| `/v1/text/brand` | `auto` 또는 기본 경로 | `gpt-4o-mini` |
| `/v1/text/marketing` | 전체 | `gpt-4o-mini` |
| `/v1/text/refine` | `content_prompt_rewrite` + `auto` | `gpt-5.5` |
| `/v1/text/refine` | `copy_rewrite` + `auto` | `gpt-4o-mini` |

`/v1/text/brand`와 `/v1/text/refine`은 기존 호환을 위해 `model` 필드를 받을 수 있습니다. `/v1/text/marketing`은 프론트 UI 흐름에 맞춰 모델 선택을 서버 정책으로 고정합니다.

## 마케팅 텍스트 생성

`POST /v1/text/marketing`은 현재 `TextGeneration.jsx`의 생성 유형과 정보 입력 UI에 대응하는 API입니다.

### content_type

| 값 | 설명 |
|---|---|
| `product_detail` | 상품 상세페이지에 사용할 구매 설득형 설명 |
| `ad_copy` | 클릭과 구매를 유도하는 광고 문구/카피 |
| `sns_post` | 인스타, 블로그, 소식 등에 사용할 게시글 본문 |
| `customer_message` | 문의, 배송, 교환, 리뷰 등 고객 응답 문구 |

### input

| 필드 | 필수 | 설명 |
|---|---:|---|
| `topic` | 예 | 상품/주제. 예: `강원도 수제 감자빵` |
| `purpose` | 예 | 목적 |
| `tone` | 예 | 느낌/톤 |
| `target_audience` | 아니오 | 타겟 고객 |
| `highlight_points` | 아니오 | 강조하고 싶은 포인트 목록 |

`purpose` 값:

- `instagram_promotion`
- `blog_promotion`
- `product_detail_page`
- `ad_click`
- `customer_response`

`tone` 값:

- `emotional`
- `practical`
- `premium`
- `lively`
- `professional`

### options

| 필드 | 기본 | 설명 |
|---|---:|---|
| `length` | `short` | `short`, `medium`, `long` |
| `number_of_variations` | `3` | 생성 변형 개수, 1~10 |
| `must_include` | `[]` | 반드시 포함할 표현 |
| `must_avoid` | `[]` | 피해야 할 표현 |
| `allow_hashtags` | `false` | 해시태그 허용 여부 |
| `allow_emoji` | `false` | 이모지 허용 여부 |
| `max_tokens` | `500` | 최대 토큰 수 |

### 상품 상세 설명 예시

```json
{
  "content_type": "product_detail",
  "input": {
    "topic": "강원도 수제 감자빵",
    "purpose": "instagram_promotion",
    "tone": "emotional",
    "target_audience": "20~30대 여성",
    "highlight_points": ["촉촉한 식감", "국내산 감자"]
  },
  "options": {
    "length": "short",
    "number_of_variations": 3,
    "must_include": [],
    "must_avoid": [],
    "allow_hashtags": false,
    "allow_emoji": false,
    "max_tokens": 500
  }
}
```

### 광고 문구 예시

```json
{
  "content_type": "ad_copy",
  "input": {
    "topic": "춘천 감자빵 선물세트",
    "purpose": "ad_click",
    "tone": "premium",
    "target_audience": "강원도 여행 기념품을 찾는 고객",
    "highlight_points": ["개별 포장", "선물용 추천"]
  },
  "options": {
    "length": "short",
    "number_of_variations": 4,
    "must_include": ["선물세트"],
    "must_avoid": ["전국 1등"],
    "allow_hashtags": false,
    "allow_emoji": false,
    "max_tokens": 500
  }
}
```

### SNS 게시글 예시

```json
{
  "content_type": "sns_post",
  "input": {
    "topic": "강원도 수제 감자빵",
    "purpose": "instagram_promotion",
    "tone": "lively",
    "target_audience": "춘천 여행 중인 20~30대",
    "highlight_points": ["갓 구운 빵", "카페에서 바로 픽업"]
  },
  "options": {
    "length": "medium",
    "number_of_variations": 2,
    "must_include": ["춘천"],
    "must_avoid": ["과장된 할인 표현"],
    "allow_hashtags": true,
    "allow_emoji": true,
    "max_tokens": 700
  }
}
```

### 고객 응답 예시

```json
{
  "content_type": "customer_message",
  "input": {
    "topic": "감자빵 택배 가능 여부 문의",
    "purpose": "customer_response",
    "tone": "professional",
    "target_audience": "온라인 문의 고객",
    "highlight_points": ["정확한 안내", "친절한 답변"]
  },
  "options": {
    "length": "short",
    "number_of_variations": 2,
    "must_include": ["확인 후 안내"],
    "must_avoid": ["확정되지 않은 배송 약속"],
    "allow_hashtags": false,
    "allow_emoji": false,
    "max_tokens": 500
  }
}
```

## 브랜드 텍스트 생성

`POST /v1/text/brand`는 브랜드 단위 텍스트 자산을 생성합니다.

요청 필드:

| 필드 | 필수 | 설명 |
|---|---:|---|
| `model` | 아니오 | `gpt-4o-mini`, `gpt-5.5`, `auto`. 기본 `gpt-4o-mini` |
| `mode` | 예 | 생성할 브랜드 텍스트 유형 |
| `language` | 아니오 | `ko` 또는 `en`. 기본 `ko` |
| `brand` | 예 | 브랜드 프로필 |

지원 mode:

| mode | 설명 |
|---|---|
| `profile_summary` | 브랜드 소개 요약 |
| `brand_ad_copy` | 브랜드 상시 광고 카피 |
| `brand_image_prompt` | 브랜드 대표 이미지 프롬프트 |

예시:

```json
{
  "model": "auto",
  "mode": "profile_summary",
  "language": "ko",
  "brand": {
    "name": "강릉 커피집",
    "category": "카페",
    "location": "강릉",
    "description": "직접 로스팅한 원두와 계절 음료를 판매하는 동네 카페",
    "brand_voice": "따뜻하고 차분한",
    "target_audience": "강릉 여행객과 지역 단골",
    "strengths": ["직접 로스팅", "계절 음료", "조용한 좌석"]
  }
}
```

## 텍스트 리파인

`POST /v1/text/refine`은 기존 입력 문구를 목적에 맞게 개선합니다. 이미지 생성 프롬프트와 숏폼 영상 프롬프트를 다듬을 때도 같은 `content_prompt_rewrite` 모드를 사용합니다.

요청 필드:

| 필드 | 필수 | 설명 |
|---|---:|---|
| `model` | 아니오 | `gpt-4o-mini`, `gpt-5.5`, `auto`. 기본 `auto` |
| `mode` | 예 | `content_prompt_rewrite` 또는 `copy_rewrite` |
| `language` | 아니오 | `ko` 또는 `en`. 기본 `ko` |
| `brand` | 아니오 | 브랜드 문맥 |
| `input` | 예 | 개선할 원문 |
| `target` | 아니오 | 목표 채널, 톤, 포맷, 화면 비율, 시각 무드 |

`target` 주요 필드:

| 필드 | 설명 |
|---|---|
| `channel` | 이미지/SNS/영상 채널 |
| `platform` | 숏폼 영상 플랫폼 |
| `tone` | 원하는 톤 |
| `format` | 재작성 결과를 넣을 대상 필드. 예: `image_prompt`, `shortform_video_prompt`, `short_copy` |
| `visualMood` | 이미지 프롬프트 재작성 시 선택한 시각 무드 |
| `aspectRatio` | 이미지/영상 화면 비율 |
| `durationSeconds` | 숏폼 영상 길이 |

이미지 프롬프트 재작성 예시:

```json
{
  "model": "auto",
  "mode": "content_prompt_rewrite",
  "language": "ko",
  "brand": {
    "name": "강릉 커피집",
    "category": "카페",
    "location": "강릉 교동",
    "description": "로컬 원두와 수제 디저트를 판매하는 동네 카페",
    "brand_voice": "따뜻하고 차분한"
  },
  "input": {
    "text": "카페에서 라떼 사진"
  },
  "target": {
    "channel": "instagram_story",
    "tone": "감성적",
    "format": "image_prompt",
    "visualMood": "warm_cozy",
    "aspectRatio": "9:16"
  }
}
```

`content_prompt_rewrite` 응답 규칙:

- `content`에는 최종 콘텐츠 생성 프롬프트만 반환합니다.
- `프롬프트 재작성:`, `이유:`, 제목, 설명, bullet, Markdown을 포함하지 않습니다.
- 응답 `content`는 `target.format`이 가리키는 생성 API 프롬프트 필드로 그대로 전달할 수 있어야 합니다.

## 기본 텍스트 생성

`POST /v1/text/generate`는 테스트용 범용 마케팅 문구 생성 API입니다.

```json
{
  "model": "gpt-4o-mini",
  "prompt": "옥수수 크림 라떼 신메뉴를 소개해줘",
  "business_info": {
    "name": "강릉 커피집",
    "category": "카페"
  },
  "content_type": "sns",
  "max_tokens": 500
}
```

## 사용 흐름 예시

마케팅 텍스트 생성:

1. frontend가 `/api/text/marketing`에 `content_type`과 `input`, `options`를 전달합니다.
2. backend가 `/v1/text/marketing`으로 전달합니다.
3. 응답의 `content`를 콘텐츠 이력, 게시 예약, 복사/저장 흐름에 사용합니다.

이미지 프롬프트 다듬기:

1. frontend가 `/api/text/refine`에 `mode=content_prompt_rewrite`, `target.format=image_prompt`로 요청합니다.
2. UI에서 선택한 `channel`, `visualMood`, `aspectRatio`를 `target`에 함께 전달합니다.
3. backend가 `/v1/text/refine`으로 전달합니다.
4. 응답의 `content`를 그대로 `/api/ai/image/async/generate` 요청의 `image_prompt`에 넣습니다.

숏폼 영상 프롬프트 다듬기:

1. frontend가 `/api/text/refine`에 `mode=content_prompt_rewrite`, `target.format=shortform_video_prompt`로 요청합니다.
2. backend가 `/v1/text/refine`으로 전달합니다.
3. 응답의 `content`를 그대로 `/api/ai/video/async/generate` 요청의 `prompt`에 넣습니다.

## 관련 문서

- [AI Engine 구현 및 실행 가이드](./ai-engine-implementation-guide.md)
- [이미지 생성 API 가이드](./image-generate-guide-v1.1.md)
