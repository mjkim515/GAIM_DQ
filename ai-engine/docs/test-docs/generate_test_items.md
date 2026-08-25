# Generate API 테스트 항목 정리

> 기준 문서: `image-generate-guide-v1.1.md`, `video-generate-guide-v1.1.md`, `text_generate_guide-v1.1.md`

## 공통

| 테스트 항목 | 테스트 사항 |
|---|---|
| 내부 API 인증 | Backend -> ai-engine 호출 시 `X-Internal-Token` 누락/오류 요청이 거부되는지 확인한다. |
| Content-Type | `Content-Type: application/json` 요청만 정상 처리되는지 확인한다. |
| Swagger 노출 | 활성 엔드포인트가 `http://127.0.0.1:8000/docs`에 노출되고, deprecated/비활성 엔드포인트는 문서 정책과 일치하는지 확인한다. |
| Frontend 직접 호출 차단 | frontend가 ai-engine을 직접 호출하지 않고 Spring Boot WAS API만 호출하는 흐름인지 확인한다. |
| 모델명 은닉 | 클라이언트 또는 WAS 요청이 provider 실제 모델명/OpenAI API key/Google 모델명을 직접 다루지 않는지 확인한다. |

## Image Generate

### 테스트 대상

- Frontend -> Backend: `POST /api/ai/image/async/generate`
- Frontend -> Backend: `GET /api/ai/image/async/job/{jobId}`
- Backend -> ai-engine: `POST /v1/image/jobs`

### 테스트 항목

| 테스트 항목 | 테스트 사항 |
|---|---|
| Job 등록 정상 처리 | 필수 필드 `purpose`, `channels`, `image_prompt`를 포함해 요청하면 `jobId`, `status=queued`, `message`가 반환되는지 확인한다. |
| 필수 필드 검증 | `purpose`, `channels`, `image_prompt`를 각각 누락했을 때 validation error가 발생하는지 확인한다. |
| 목적값 매핑 | UI 목적 `홍보`, `이벤트`, `브랜드`가 각각 `promotion`, `event`, `brand` 또는 허용 한글 값으로 정상 전달되는지 확인한다. |
| 목적값 오류 | 허용되지 않은 `purpose` 값 요청 시 실패하는지 확인한다. |
| 채널 필수 및 primary channel | `channels` 첫 번째 값이 primary channel로 사용되고, 빈 배열/누락 시 실패하는지 확인한다. |
| 플랫폼 프리셋 매핑 | Instagram 피드, 스토리, 릴스, 블로그/상세페이지, 네이버 플레이스, 배너/팝업, 직접 설정이 각각 지정된 API channel로 변환되는지 확인한다. |
| 비주얼 무드 기본값 | `visual_mood`를 생략하면 `bright`가 적용되는지 확인한다. |
| 비주얼 무드 허용값 | `bright`, `warm_cozy`, `moody`, `clean_minimal`, `premium`, `vibrant`가 정상 처리되는지 확인한다. |
| 비주얼 무드 오류 | 허용되지 않은 `visual_mood` 값 요청 시 실패 또는 명확한 경고가 발생하는지 확인한다. |
| OpenAI style 파생 | `bright`, `vibrant`는 `vivid`, 나머지 무드는 `natural`로 파생되는지 routing 결과 또는 로그로 확인한다. |
| 생성 개수 기본값 | `n`을 생략하면 기본 1장이 생성 요청되는지 확인한다. |
| 생성 개수 경계값 | `n=1`, `n=4`는 정상, `n=0`, `n=5` 이상은 실패하는지 확인한다. |
| 이미지 프롬프트 전달 | `image_prompt`가 최종 provider 프롬프트의 핵심 내용으로 포함되는지 `routing.final_prompt`로 확인한다. |
| 텍스트 삽입 | `text_to_render`를 전달하면 이미지 내 렌더링 대상 문구로 반영되는지 확인한다. |
| text_rendering 자동 반영 | `text_rendering.text`가 있고 `text_to_render`가 없을 때 서버가 `text_to_render`에 자동 반영하는지 확인한다. |
| text_rendering 세부 옵션 | `language`, `placement`, `must_render_exactly`, 폰트/색상 힌트가 요청 스키마에 맞게 수용되는지 확인한다. |
| 참조 이미지 base64 | `reference_images[].b64_json`과 `mime_type`을 전달하면 참조 이미지 기반 생성/편집 라우팅이 선택되는지 확인한다. |
| 참조 이미지 URL | URL 기반 참조 이미지가 스키마상 허용 범위 내에서 처리되는지 확인한다. |
| 참조 이미지 mime type | 지원하지 않는 `mime_type` 또는 잘못된 base64 payload 전달 시 validation error가 발생하는지 확인한다. |
| 라우팅 정책 | 일반 생성은 Google `gemini-2.5-flash-image` 우선, 텍스트 삽입/참조 이미지 편집은 OpenAI `gpt-image-2` 우선 후보가 되는지 확인한다. |
| fallback 처리 | primary provider 실패 시 다음 후보 또는 local placeholder로 fallback되고 `routing.fallback_used`, `routing.warnings`, `attempted_models`에 기록되는지 확인한다. |
| 상태 polling | `GET /api/ai/image/async/job/{jobId}`에서 `queued`, `processing`, `completed`, `failed` 상태가 정상 조회되는지 확인한다. |
| 완료 응답 | `completed` 상태에서 `images`, `modelUsed`, `provider`, `progressPct=100`, `error=null`, `routing.selected`가 포함되는지 확인한다. |
| 실패 응답 | `failed` 상태에서 `error`가 채워지고 완료 이미지 URL이 노출되지 않는지 확인한다. |
| 이미지 URL | 완료된 `images` URL이 접근 가능하고 이미지 파일로 렌더링되는지 확인한다. |
| 프롬프트 다듬기 연계 | frontend가 `/api/text/refine`에 `mode=content_prompt_rewrite`를 호출한 뒤 응답 `content`를 `image_prompt`로 전달하는지 확인한다. |
| 광고 문구 생성 연계 | 이미지 내 광고 문구가 필요할 때 `/api/text/marketing`의 `content_type=ad_copy` 결과 또는 사용자 입력이 `text_to_render`로 전달되는지 확인한다. |

## Video Generate

### 테스트 대상

- Frontend -> Backend: `POST /api/ai/video/async/generate`
- Frontend -> Backend: `GET /api/ai/video/async/job/{jobId}`
- Backend -> ai-engine: `POST /v1/video/jobs`
- 개발/레거시 확인용: `GET /v1/video/status/{job_id}`
- Celery task: `app.workers.tasks.video_tasks.generate_video_short_task`
- Celery queue: `video-queue`

### 테스트 항목

| 테스트 항목 | 테스트 사항 |
|---|---|
| Job 등록 정상 처리 | 유효한 영상 생성 요청 시 `jobId`, `status=queued`, `message`가 즉시 반환되는지 확인한다. |
| WAS jobId 발급 | WAS가 생성한 `jobId`가 요청 body에 포함되고, callback/status에서도 동일하게 유지되는지 확인한다. |
| Celery task 등록 | `POST /v1/video/jobs`가 요청 검증 후 Celery task를 `video-queue`에 등록하는지 확인한다. |
| Celery task 재검증 | Celery task 내부에서 `VideoShortCreateRequest` 계약을 다시 검증하는지 확인한다. |
| 필수 필드 검증 | `prompt`, `model`, `platform`, `task`, `aspectRatio`, `durationSeconds` 누락 시 validation error가 발생하는지 확인한다. |
| 모델 값 검증 | `model`이 `fast`, `standard`, `lite`일 때 각각 Veo provider 모델로 매핑되고, 다른 값은 실패하는지 확인한다. |
| 플랫폼 값 검증 | `youtube_shorts`, `instagram_reels`, `tiktok`, `naver_clip`가 정상 처리되고, 미지원 플랫폼은 실패하는지 확인한다. |
| task 값 검증 | `textToVideo`, `imageToVideo`, `referenceToVideo`가 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| 화면비 검증 | `aspectRatio`가 `9:16`, `16:9`일 때 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| 영상 길이 검증 | `durationSeconds`가 `4`, `6`, `8`일 때 정상 처리되고, 다른 값은 `422 Validation Error`가 발생하는지 확인한다. |
| textToVideo 입력 규칙 | `task=textToVideo`에서 `input`을 보내지 않으면 정상, `input.image` 등 입력 이미지를 같이 보내면 실패하는지 확인한다. |
| imageToVideo 입력 규칙 | `task=imageToVideo`에서 `input.image`가 필수이고, 누락 시 실패하는지 확인한다. |
| imageToVideo lastFrame | `input.lastFrame`은 `input.image`가 있을 때만 허용되고, 단독 전달 시 실패하는지 확인한다. |
| referenceToVideo 입력 규칙 | `task=referenceToVideo`에서 `input.referenceImages` 1~3장이 필수이고, 누락/0장/4장 이상은 실패하는지 확인한다. |
| referenceImages 충돌 | `referenceImages`를 `image` 또는 `lastFrame`과 같이 보내면 실패하는지 확인한다. |
| 입력 이미지 base64 | `bytesBase64Encoded`와 `mimeType` 조합이 정상 처리되는지 확인한다. |
| 입력 이미지 GCS URI | `gcsUri`와 `mimeType` 조합이 스키마상 정상 처리되는지 확인한다. |
| 이미지 입력 상호 배타 | `gcsUri`와 `bytesBase64Encoded`를 동시에 보내면 `422 Validation Error`가 발생하는지 확인한다. |
| 이미지 mime type | `image/png`, `image/jpeg`만 허용되고 다른 MIME type은 실패하는지 확인한다. |
| advanced 기본값 | `advanced`를 생략하면 `sampleCount=1`, `resolution=720p`, `enhancePrompt=true`, `generateAudio=true`, `compressionQuality=optimized`, `resizeMode=crop` 기본값이 적용되는지 확인한다. |
| sampleCount 경계값 | `sampleCount=1`, `sampleCount=4`는 정상, 0 또는 5 이상은 실패하는지 확인한다. |
| resolution 검증 | `720p`, `1080p`는 정상, 다른 값은 실패하는지 확인한다. |
| generateAudio 검증 | `generateAudio=true/false`가 provider 옵션으로 정상 반영되는지 확인한다. |
| resizeMode 검증 | `crop`, `pad`가 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| seed 경계값 | `seed=0`, `seed=2147483647`은 정상, 음수 또는 초과값은 실패하는지 확인한다. |
| fps 미지원 | WAS 요청에 `fps`를 넣지 않는지 확인하고, provider에 전달될 경우 `Unsupported output video frame rate` 오류가 발생하지 않도록 검증한다. |
| 상태 polling | WAS 상태 API에서 `processing`, `completed`, `failed` 상태가 조회되고 terminal 상태에서 polling이 종료되는지 확인한다. |
| 진행 중 응답 | `processing` 상태에서 `videoUrl=null`, `error=null`, `progressPct`가 반환되는지 확인한다. |
| 완료 응답 | `completed` 상태에서 재생 가능한 `videoUrl`, `error=null`, `progressPct=100`이 반환되는지 확인한다. |
| 실패 응답 | `failed` 상태에서 `videoUrl=null`, `error` 메시지, `progressPct=100`이 반환되는지 확인한다. |
| MP4 재생성 | 완료된 `videoUrl`이 브라우저/프론트에서 직접 재생 가능한 MP4 파일인지 확인한다. |
| polling 주기 | frontend가 약 7초 또는 권장 5~10초 간격으로 polling하고, `VIDEO_MAX_WAIT_SEC=600` 정책에 맞게 timeout을 처리하는지 확인한다. |
| callback 처리 | ai-engine이 progress/completed/failed callback을 WAS에 보내고 WAS DB 상태가 갱신되는지 확인한다. |
| callback 보안 | WAS callback 수신 API가 `X-Internal-Token`으로 보호되는지 확인한다. |
| callback retry | callback 실패 시 `WAS_CALLBACK_MAX_RETRIES`, `WAS_CALLBACK_RETRY_DELAY_SEC`, `WAS_CALLBACK_TIMEOUT_SEC` 설정대로 재시도되는지 확인한다. |
| Redis 기동 | Celery broker/backend로 사용할 Redis가 `run_redis.sh` 또는 기존 `localhost:6379` 인스턴스로 준비되는지 확인한다. |
| worker 기동 | `run_worker.sh` 실행 시 Celery app, queue, concurrency, log level 기본값이 가이드와 일치하는지 확인한다. |
| 영상 queue 단독 실행 | `CELERY_QUEUES=video-queue ./run_worker.sh`로 영상 queue만 처리할 수 있는지 확인한다. |
| worker 동시성 | `CELERY_WORKER_CONCURRENCY` 값에 따라 Celery worker 동시 처리량이 제어되는지 확인한다. |
| provider 실행 순서 | `AI_PROVIDER_MODE=live`에서 Veo 후보를 먼저 실행하고, provider 실패 시 Runway 후보로 fallback하는지 확인한다. |
| provider 전체 실패 | Veo와 Runway가 모두 실패하면 public-safe error message로 failed callback을 전송하는지 확인한다. |
| Celery retry 정책 | Celery task 자체의 `max_retries=2` 설정이 적용되고, provider fallback은 task 내부에서 순차 실행되는지 확인한다. |
| live/mock 차이 | `AI_PROVIDER_MODE=mock`에서는 실제 playable MP4가 생성되지 않고 Celery enqueue/callback 흐름만 확인하며, 실제 결과 검증은 `AI_PROVIDER_MODE=live`에서 수행하는지 확인한다. |
| GCP location | Veo 호출 location이 `GCP_VIDEO_LOCATION=us-central1`로 설정되어 404 model not found가 발생하지 않는지 확인한다. |
| Runway 인증 | Runway fallback 또는 직접 테스트 시 `RUNWAYML_API_SECRET`이 없으면 인증 오류로 실패하는지 확인한다. |
| 저장 경로 | 로컬 기준 `{STORAGE_BASE_DIR}/videos/{uuid}.mp4`에 저장되고 `{STORAGE_PUBLIC_BASE_URL}/videos/{uuid}.mp4`로 노출되는지 확인한다. |

## Text Generate

### 테스트 대상

- `POST /v1/text/brand`
- `POST /v1/text/marketing`
- `POST /v1/text/refine`
- 테스트/호환용: `POST /v1/text/generate`

### 테스트 항목

| 테스트 항목 | 테스트 사항 |
|---|---|
| 공통 응답 구조 | 정상 응답에 `content`, `model_used`, `tokens_used`가 포함되는지 확인한다. |
| content 유효성 | `content`가 빈 문자열이 아니고 요청 목적에 맞는 최종 텍스트인지 확인한다. |
| model_used 표시 | live 모드에서는 실제 모델명, mock 모드에서는 `mock:{model}` 형식으로 표시되는지 확인한다. |
| tokens_used 표시 | live 모드에서는 provider 토큰 수, mock 모드에서는 추정 토큰 수가 반환되는지 확인한다. |
| marketing 모델 고정 | `/v1/text/marketing` 요청 본문에서 `model`을 받지 않고 내부 정책으로 `gpt-4o-mini`가 선택되는지 확인한다. |
| brand 모델 정책 | `/v1/text/brand`에서 `model=auto` 또는 기본 경로가 `gpt-4o-mini`로 처리되는지 확인한다. |
| refine 모델 정책 | `/v1/text/refine`에서 `content_prompt_rewrite + auto`는 `gpt-5.5`, `copy_rewrite + auto`는 `gpt-4o-mini`로 처리되는지 확인한다. |
| marketing 필수 필드 | `content_type`, `input.topic`, `input.purpose`, `input.tone` 누락 시 validation error가 발생하는지 확인한다. |
| marketing content_type | `product_detail`, `ad_copy`, `sns_post`, `customer_message`가 각각 정상 처리되는지 확인한다. |
| marketing content_type 오류 | 허용되지 않은 `content_type` 값 요청 시 실패하는지 확인한다. |
| purpose 값 검증 | `instagram_promotion`, `blog_promotion`, `product_detail_page`, `ad_click`, `customer_response`가 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| tone 값 검증 | `emotional`, `practical`, `premium`, `lively`, `professional`이 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| target_audience 선택값 | `target_audience` 생략/입력 요청이 모두 정상 처리되고, 입력 시 결과 톤에 반영되는지 확인한다. |
| highlight_points 선택값 | `highlight_points` 생략/빈 배열/다중 배열 입력이 정상 처리되고, 입력 시 결과에 반영되는지 확인한다. |
| length 기본값 | `options.length` 생략 시 `short`가 적용되는지 확인한다. |
| length 값 검증 | `short`, `medium`, `long`이 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| number_of_variations 기본값 | `number_of_variations` 생략 시 3개 변형 생성 정책이 적용되는지 확인한다. |
| number_of_variations 경계값 | 1과 10은 정상, 0 또는 11 이상은 실패하는지 확인한다. |
| must_include 반영 | `must_include`에 지정한 표현이 결과에 포함되는지 확인한다. |
| must_avoid 반영 | `must_avoid`에 지정한 표현이 결과에 포함되지 않는지 확인한다. |
| allow_hashtags | `allow_hashtags=true`일 때 해시태그가 허용되고, false일 때 불필요한 해시태그가 생성되지 않는지 확인한다. |
| allow_emoji | `allow_emoji=true`일 때 이모지가 허용되고, false일 때 이모지가 생성되지 않는지 확인한다. |
| max_tokens 기본값 | `max_tokens` 생략 시 500 기본값이 적용되는지 확인한다. |
| max_tokens 제한 | 낮은 `max_tokens`와 높은 `max_tokens` 요청에서 응답 길이와 `tokens_used`가 정책에 맞게 제어되는지 확인한다. |
| product_detail 생성 | 상품 상세페이지용 구매 설득형 설명이 생성되는지 확인한다. |
| ad_copy 생성 | 클릭/구매 유도 광고 카피가 생성되는지 확인한다. |
| sns_post 생성 | SNS/블로그 게시글 본문 형식으로 생성되는지 확인한다. |
| customer_message 생성 | 문의/배송/교환/리뷰 등 고객 응답 문구가 전문적인 톤으로 생성되는지 확인한다. |
| brand 필수 필드 | `/v1/text/brand`에서 `mode`, `brand` 누락 시 validation error가 발생하는지 확인한다. |
| brand mode | `profile_summary`, `brand_ad_copy`, `brand_image_prompt`가 각각 정상 처리되는지 확인한다. |
| brand mode 오류 | 허용되지 않은 `mode` 값 요청 시 실패하는지 확인한다. |
| brand language 기본값 | `language` 생략 시 `ko`가 적용되는지 확인한다. |
| brand language 값 | `ko`, `en`이 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| brand 문맥 반영 | `brand.name`, `category`, `location`, `description`, `brand_voice`, `target_audience`, `strengths`가 결과에 적절히 반영되는지 확인한다. |
| refine 필수 필드 | `/v1/text/refine`에서 `mode`, `input` 누락 시 validation error가 발생하는지 확인한다. |
| refine mode | `content_prompt_rewrite`, `copy_rewrite`가 정상 처리되고, 다른 값은 실패하는지 확인한다. |
| refine language 기본값 | `language` 생략 시 `ko`가 적용되는지 확인한다. |
| refine target 선택값 | `target.channel`, `platform`, `tone`, `format`, `visualMood`, `aspectRatio`, `durationSeconds`가 입력될 때 결과에 반영되는지 확인한다. |
| 이미지 프롬프트 재작성 | `mode=content_prompt_rewrite`, `target.format=image_prompt` 요청 결과가 이미지 생성 API의 `image_prompt`에 그대로 전달 가능한지 확인한다. |
| 영상 프롬프트 재작성 | `mode=content_prompt_rewrite`, `target.format=shortform_video_prompt` 요청 결과가 영상 생성 API의 `prompt`에 그대로 전달 가능한지 확인한다. |
| 짧은 카피 재작성 | `mode=copy_rewrite`, `target.format=short_copy` 요청 결과가 광고/게시 카피로 바로 사용할 수 있는지 확인한다. |
| refine 응답 형식 제한 | `content_prompt_rewrite` 응답 `content`에 `프롬프트 재작성:`, `이유:`, 제목, 설명, bullet, Markdown이 포함되지 않는지 확인한다. |
| 테스트용 generate | `/v1/text/generate`가 호환용으로 동작하고 `model`, `prompt`, `business_info`, `content_type`, `max_tokens` 요청을 처리하는지 확인한다. |
| 신규 기능 경로 | 신규 텍스트 기능이 범용 `/v1/text/generate`가 아니라 목적별 `/v1/text/brand`, `/v1/text/marketing`, `/v1/text/refine`을 사용하는지 확인한다. |
| frontend 연계 | `/api/text/marketing`, `/api/text/refine`, `/api/text/brand`가 backend를 거쳐 ai-engine 목적별 엔드포인트로 전달되는지 확인한다. |
