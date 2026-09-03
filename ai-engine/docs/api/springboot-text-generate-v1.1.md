# Spring Boot 텍스트 생성 연동 가이드

> Version: v1.1

## 요약

Spring Boot는 OpenAI 모델과 API Key를 직접 다루지 않습니다. 프론트엔드에서 받은 입력을 목적별 텍스트 API로 전달하면 `ai-engine`이 내부 정책에 따라 모델을 선택하고 OpenAI 또는 mock 응답을 반환합니다.

```text
frontend /api/text/brand
-> Spring Boot
-> ai-engine /v1/text/brand

frontend /api/text/marketing
-> Spring Boot
-> ai-engine /v1/text/marketing

frontend /api/text/refine
-> Spring Boot
-> ai-engine /v1/text/refine
```

Spring Boot 연동 대상:

- `POST /v1/text/brand`
- `POST /v1/text/marketing`
- `POST /v1/text/refine`

테스트/호환용 `POST /v1/text/generate`는 이 연동 가이드에서 제외합니다.

## 설정

```yaml
ai-engine:
  base-url: http://127.0.0.1:8002
  internal-token: change-this-internal-token
```

`internal-token` 값은 `ai-engine/.env`의 `WAS_INTERNAL_TOKEN`과 같아야 합니다.

## 공통 응답 DTO

```java
public record TextResponse(
        String content,
        String model_used,
        Integer tokens_used
) {
}
```

## WebClient 호출

```java
public Mono<TextResponse> generateBrandText(BrandTextRequest request) {
    return aiEngineWebClient.post()
            .uri("/v1/text/brand")
            .header("X-Internal-Token", internalToken)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .bodyToMono(TextResponse.class);
}

public Mono<TextResponse> generateMarketingText(MarketingTextRequest request) {
    return aiEngineWebClient.post()
            .uri("/v1/text/marketing")
            .header("X-Internal-Token", internalToken)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .bodyToMono(TextResponse.class);
}

public Mono<TextResponse> refineText(RefineTextRequest request) {
    return aiEngineWebClient.post()
            .uri("/v1/text/refine")
            .header("X-Internal-Token", internalToken)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .bodyToMono(TextResponse.class);
}
```

## 공통 DTO

```java
import java.util.List;

public record BrandProfile(
        String name,
        String category,
        String location,
        String description,
        String brand_voice,
        String target_audience,
        List<String> strengths
) {
}
```

## 마케팅 텍스트 생성

`POST /v1/text/marketing`은 현재 텍스트 생성 화면의 `생성 유형`과 `정보 입력`을 그대로 받습니다. Spring Boot는 `model`, `language`, `business`를 보내지 않습니다.

### DTO

```java
public record MarketingTextRequest(
        String content_type,
        MarketingTextInput input,
        MarketingTextOptions options
) {
}

public record MarketingTextInput(
        String topic,
        String purpose,
        String tone,
        String target_audience,
        List<String> highlight_points
) {
}

public record MarketingTextOptions(
        String length,
        Integer number_of_variations,
        List<String> must_include,
        List<String> must_avoid,
        Boolean allow_hashtags,
        Boolean allow_emoji,
        Integer max_tokens
) {
}
```

지원 `content_type`:

| 값 | 설명 |
|---|---|
| `product_detail` | 상품 상세 설명 |
| `ad_copy` | 광고 문구/카피 |
| `sns_post` | SNS 게시글 |
| `customer_message` | 고객 응답/메시지 |

지원 `purpose`:

- `instagram_promotion`
- `blog_promotion`
- `product_detail_page`
- `ad_click`
- `customer_response`

지원 `tone`:

- `emotional`
- `practical`
- `premium`
- `lively`
- `professional`

### 상품 상세 설명 예시

```java
MarketingTextRequest request = new MarketingTextRequest(
        "product_detail",
        new MarketingTextInput(
                "강원도 수제 감자빵",
                "instagram_promotion",
                "emotional",
                "20~30대 여성",
                List.of("촉촉한 식감", "국내산 감자")
        ),
        new MarketingTextOptions(
                "short",
                3,
                List.of(),
                List.of(),
                false,
                false,
                500
        )
);
```

### SNS 게시글 예시

```java
MarketingTextRequest request = new MarketingTextRequest(
        "sns_post",
        new MarketingTextInput(
                "강원도 수제 감자빵",
                "instagram_promotion",
                "lively",
                "춘천 여행 중인 20~30대",
                List.of("갓 구운 빵", "카페에서 바로 픽업")
        ),
        new MarketingTextOptions(
                "medium",
                2,
                List.of("춘천"),
                List.of("과장된 할인 표현"),
                true,
                true,
                700
        )
);
```

## 브랜드 텍스트 생성

`POST /v1/text/brand`는 브랜드 단위 텍스트 자산을 생성합니다.

```java
public record BrandTextRequest(
        String model,
        String mode,
        String language,
        BrandProfile brand
) {
}
```

지원 mode:

| mode | 설명 |
|---|---|
| `profile_summary` | 브랜드 소개 요약 |
| `brand_ad_copy` | 브랜드 상시 광고 카피 |
| `brand_image_prompt` | 브랜드 대표 이미지 프롬프트 |

예시:

```java
BrandTextRequest request = new BrandTextRequest(
        "auto",
        "profile_summary",
        "ko",
        new BrandProfile(
                "강릉 커피집",
                "카페",
                "강릉",
                "직접 로스팅한 원두와 계절 음료를 판매하는 동네 카페",
                "따뜻하고 차분한",
                "강릉 여행객과 지역 단골",
                List.of("직접 로스팅", "계절 음료", "조용한 좌석")
        )
);
```

## 텍스트 리파인

`POST /v1/text/refine`은 사용자가 작성한 기존 문구 또는 콘텐츠 생성 프롬프트를 목적에 맞게 개선합니다.

```java
public record RefineTextRequest(
        String model,
        String mode,
        String language,
        BrandProfile brand,
        RefineInput input,
        RefineTarget target
) {
}

public record RefineInput(String text) {
}

public record RefineTarget(
        String channel,
        String platform,
        String tone,
        String format,
        String visualMood,
        String aspectRatio,
        Integer durationSeconds
) {
}
```

지원 mode:

| mode | 설명 |
|---|---|
| `content_prompt_rewrite` | 이미지/영상 등 콘텐츠 생성 프롬프트를 더 구체적으로 재작성 |
| `copy_rewrite` | 광고 문구나 게시글 문구를 목표 채널과 톤에 맞게 개선 |

이미지 프롬프트 재작성 예시:

```java
RefineTextRequest request = new RefineTextRequest(
        "auto",
        "content_prompt_rewrite",
        "ko",
        new BrandProfile(
                "강릉 커피집",
                "카페",
                null,
                null,
                "따뜻하고 차분한",
                null,
                List.of()
        ),
        new RefineInput("카페에서 라떼 사진"),
        new RefineTarget(
                "instagram_story",
                null,
                "감성적",
                "image_prompt",
                "warm_cozy",
                "9:16",
                null
        )
);
```

`target.format=image_prompt`인 경우 `visualMood`와 `aspectRatio`를 함께 전달해야 UI에서 선택한 시각 무드와 화면 비율이 재작성 프롬프트에 반영됩니다.

## Spring Boot가 직접 보내지 않는 값

아래 값은 Spring Boot가 직접 보내지 않습니다.

- OpenAI API Key
- provider
- temperature
- marketing API의 `model`
- marketing API의 `language`
- marketing API의 `business`
- 테스트용 `/v1/text/generate` 요청

`/v1/text/marketing` 모델은 ai-engine 내부 정책으로 선택합니다. 현재는 전체 marketing 타입에 `gpt-4o-mini`를 사용합니다. `/v1/text/refine`의 `content_prompt_rewrite`는 `auto`일 때 `gpt-5.5`를 사용합니다.

## 이미지/영상 생성 API와 연결

이미지 프롬프트를 다듬는 경우:

1. Spring Boot가 `/v1/text/refine`에 `mode=content_prompt_rewrite`, `target.format=image_prompt`로 요청합니다.
2. 응답의 `content`를 이미지 생성 요청의 `image_prompt`로 전달합니다.
3. Spring Boot가 `/v1/image/jobs`를 호출합니다.

숏폼 영상 프롬프트를 다듬는 경우:

1. Spring Boot가 `/v1/text/refine`에 `mode=content_prompt_rewrite`, `target.format=shortform_video_prompt`로 요청합니다.
2. 응답의 `content`를 영상 생성 요청의 `prompt`로 전달합니다.
3. Spring Boot가 `/v1/video/jobs`를 호출합니다.

## curl 확인

### 마케팅 텍스트

```bash
curl -X POST http://127.0.0.1:8002/v1/text/marketing \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: change-this-internal-token" \
  -d '{
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
  }'
```

### 텍스트 리파인

```bash
curl -X POST http://127.0.0.1:8002/v1/text/refine \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: change-this-internal-token" \
  -d '{
    "model": "auto",
    "mode": "copy_rewrite",
    "language": "ko",
    "input": {
      "text": "이번 주 라떼 할인하니까 많이 오세요"
    },
    "target": {
      "channel": "push",
      "tone": "friendly",
      "format": "short_copy"
    }
  }'
```

## 관련 문서

- [텍스트 생성 API 가이드](./text_generate_guide-v1.1.md)
- [Spring Boot 이미지 생성 연동 가이드](./springboot-image-generate-guide-v1.1.md)
