# Spring Boot 비디오 생성 연동 가이드

> Version: v1.1

## 요약

Spring Boot WAS는 Google/Veo 모델명을 직접 선택하지 않습니다.

프론트엔드에서 받은 숏폼 생성 요청을 Spring Boot API `POST /api/ai/video/async/generate`로 받고, Spring Boot가 `jobId`를 생성해 DB에 저장한 뒤 내부 API `POST /v1/video/jobs`로 전달하면, `ai-engine`이 `fast`, `standard`, `lite` 값을 실제 Veo 모델명으로 변환하고 영상 생성 job을 시작합니다. 기본 provider는 Google Veo이며, Google/Veo 실패 시 ai-engine이 Runway fallback 후보를 실행할 수 있습니다.

영상 생성은 비동기 작업입니다. 프론트엔드는 Spring Boot의 `GET /api/ai/video/async/job/{jobId}`를 polling 하고, Spring Boot는 DB에 저장된 job 상태를 반환합니다. `ai-engine`은 진행률, 완료, 실패 상태를 Spring Boot callback API로 전달합니다.

## 설정

Spring Boot:

```yaml
ai-engine:
  base-url: http://127.0.0.1:8002
  internal-token: change-this-internal-token
  response-timeout: 300s
```

`internal-token` 값은 `ai-engine/.env`의 `WAS_INTERNAL_TOKEN`과 같아야 합니다.

ai-engine:

```env
AI_PROVIDER_MODE=live
GOOGLE_AUTH_MODE=vertex_ai
GCP_IMAGE_LOCATION=global
GCP_VIDEO_LOCATION=us-central1
STORAGE_BACKEND=local
STORAGE_BASE_DIR=../storage-data
STORAGE_PUBLIC_BASE_URL=http://127.0.0.1:8002/gaim/generated
VIDEO_POLL_INTERVAL_SEC=10
VIDEO_MAX_WAIT_SEC=600
```

비디오/Veo provider 호출은 `GCP_VIDEO_LOCATION`을 사용합니다. 현재 권장값은 `us-central1`입니다. 생성 결과 저장소는 현재 GCS가 아니라 로컬 `storage-data/videos`입니다.

## Spring Boot 외부 API 권장

프론트엔드가 Spring Boot로 호출하는 API는 아래처럼 두 개로 둡니다.

```http
POST /api/ai/video/async/generate
GET /api/ai/video/async/job/{jobId}
```

Spring Boot 내부에서 ai-engine으로 전달하는 API:

```http
POST /v1/video/jobs
```

`GET /v1/video/status/{job_id}`는 개발/레거시 확인용입니다. 운영 상태의 source of truth는 Spring Boot DB입니다.

## 요청 DTO

```java
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import java.util.Map;

public record VideoShortCreateRequest(
        @NotBlank String jobId,
        @NotBlank String prompt,
        @NotBlank @Pattern(regexp = "standard|fast|lite") String model,
        @NotBlank @Pattern(regexp = "youtube_shorts|instagram_reels|tiktok|naver_clip") String platform,
        @NotBlank @Pattern(regexp = "textToVideo|imageToVideo|referenceToVideo") String task,
        @NotBlank @Pattern(regexp = "9:16|16:9") String aspectRatio,
        @NotNull Integer durationSeconds,
        @Valid
        VideoShortInput input,
        @Valid
        VideoShortAdvancedOverrides advanced,
        Map<String, Object> metadata
) {
}
```

```java
import java.util.List;

public record VideoShortInput(
        VideoShortMediaInput image,
        VideoShortMediaInput lastFrame,
        List<VideoShortMediaInput> referenceImages
) {
}
```

```java
public record VideoShortMediaInput(
        String gcsUri,
        String bytesBase64Encoded,
        String mimeType
) {
}
```

```java
public record VideoShortAdvancedOverrides(
        Integer sampleCount,
        String resolution,
        Boolean enhancePrompt,
        Boolean generateAudio,
        String compressionQuality,
        String resizeMode,
        String negativePrompt,
        String personGeneration,
        Integer seed,
        String storageUri,
        String pubsubTopic
) {
}
```

`fps`는 요청 DTO에 넣지 않습니다. Veo 3.1은 24 FPS를 사용하므로 WAS에서 설정하지 않습니다.

현재 frontend 파일 업로드 흐름은 이미지를 base64로 읽어 `bytesBase64Encoded`에 담아 전달합니다. `gcsUri`와 `storageUri`는 스키마상 남겨두되, 현재 로컬 storage 우선 흐름에서는 일반적으로 사용하지 않습니다.

## 요청 필드

아래 표는 Spring Boot WAS API 계약 기준입니다. `ai-engine`은 일부 기본값과 자동 추론을 지원하지만, WAS는 운영 추적과 플랫폼별 정책 적용을 위해 기본 선택값을 명시해서 전달합니다.

| 필드 | 필수 | 설명 |
|---|---:|---|
| `jobId` | 예 | Spring Boot WAS가 생성한 job ID. ai-engine은 이 값을 그대로 사용 |
| `prompt` | 예 | 영상 생성 프롬프트 |
| `model` | 예 | `fast`, `standard`, `lite` |
| `platform` | 예 | `youtube_shorts`, `instagram_reels`, `tiktok`, `naver_clip` |
| `task` | 예 | `textToVideo`, `imageToVideo`, `referenceToVideo` |
| `aspectRatio` | 예 | `9:16`, `16:9` |
| `durationSeconds` | 예 | `4`, `6`, `8` |
| `input` | 조건부 | `imageToVideo`는 `input.image` 필수, `referenceToVideo`는 `input.referenceImages` 필수, `textToVideo`는 보내지 않음 |
| `advanced` | 아니오 | 바꾸고 싶은 고급 옵션만 전달 |
| `metadata` | 아니오 | WAS 추적용 데이터. provider로 전달되지 않음 |

## 모델 매핑

Google/Veo 1순위 모델:

| WAS 요청값 | ai-engine Google/Veo 모델 |
|---|---|
| `fast` | `google/veo-3.1-fast-generate-001` |
| `standard` | `google/veo-3.1-generate-001` |
| `lite` | `google/veo-3.1-lite-generate-001` |

예외: `referenceToVideo`는 Veo reference image 조합 안정성을 위해 `model` 요청값과 관계없이 `google/veo-3.1-generate-001`로 보정합니다.

Runway fallback 모델:

| task | WAS 요청값 | Runway fallback 모델 |
|---|---|---|
| `textToVideo` | `fast`, `standard`, `lite` | `runway/gen4.5` |
| `imageToVideo`, `referenceToVideo` | `fast`, `lite` | `runway/gen4_turbo` |
| `imageToVideo`, `referenceToVideo` | `standard` | `runway/gen4.5` |

`referenceToVideo` 자동 보정:

- frontend에서 스타일 레퍼런스를 선택하면 요청 payload가 `model=standard`, `durationSeconds=8`로 자동 보정됩니다.
- ai-engine도 방어적으로 `referenceToVideo`를 standard/8초로 정규화합니다.
- Spring Boot는 `referenceToVideo` 요청을 전달할 때 `model=standard`, `durationSeconds=8`을 권장합니다.

## 응답 DTO

생성 요청 응답:

```java
public record VideoJobResponse(
        String jobId,
        String status,
        String message
) {
}
```

상태 조회 응답:

```java
public record VideoStatusResponse(
        String jobId,
        String status,
        String videoUrl,
        String error,
        Integer progressPct,
        String provider,
        String modelUsed,
        Boolean fallbackUsed,
        List<String> warnings
) {
}
```

`status` 값:

| 값 | 설명 |
|---|---|
| `queued` | 생성 요청 접수 |
| `processing` | 생성 중 |
| `completed` | 생성 완료. `videoUrl` 사용 가능 |
| `failed` | 실패. `error` 확인 필요 |

## Callback 수신 API

`ai-engine`은 비디오 생성 job의 진행률과 최종 결과를 Spring Boot callback API로 push합니다. Spring Boot는 이 API를 internal endpoint로 열어두고, 수신한 payload를 `jobId` 기준으로 DB에 반영합니다. 프론트엔드는 이 callback API를 직접 호출하지 않습니다.

```http
POST /internal/callback/jobs/{jobId}/progress
POST /internal/callback/jobs/{jobId}
```

모든 callback 요청에는 내부 토큰이 포함됩니다.

```http
X-Internal-Token: change-this-internal-token
```

Spring Boot의 `ai-engine.internal-token` 값과 `ai-engine/.env`의 `WAS_INTERNAL_TOKEN` 값은 반드시 같아야 합니다. `ai-engine`은 `WAS_BASE_URL`을 기준으로 callback URL을 생성합니다.

```env
WAS_BASE_URL=http://localhost:8080
WAS_INTERNAL_TOKEN=change-this-internal-token
WAS_CALLBACK_TIMEOUT_SEC=1.0
```

현재 `ai-engine` callback 송신 구현:

```text
ai-engine/app/services/callbacks.py
```

비디오 worker는 작업 시작 후 progress `5`, provider 생성 완료 후 progress `90`, 저장 완료 후 `completed` callback을 보냅니다. 실패하면 `failed` callback을 보냅니다.

### Progress callback

```json
{
  "progress": 5
}
```

Spring Boot는 progress callback을 받으면 해당 job을 `processing`으로 전환하고 `progressPct`를 갱신합니다.

```java
public record VideoJobProgressRequest(
        Integer progress
) {
}
```

### Completed callback

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

Spring Boot는 `resultUrl`을 DB의 `videoUrl` 또는 결과 URL 컬럼에 저장해서 프론트엔드 상태 응답의 `videoUrl`로 반환합니다.

### Failed callback

```json
{
  "status": "failed",
  "error": "provider request failed",
  "durationMs": 12345
}
```

Google/Veo가 실패하고 Runway fallback까지 실패한 경우 `warnings`가 함께 올 수 있습니다.

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

```java
import java.util.List;

public record VideoJobCallbackRequest(
        String status,
        String resultUrl,
        String error,
        Long durationMs,
        String provider,
        String modelUsed,
        Boolean fallbackUsed,
        List<String> warnings
) {
}
```

## Callback Controller 예시

이미지와 비디오 callback endpoint는 같은 URL을 사용할 수 있습니다. Spring Boot는 `jobId`가 이미지 job인지 비디오 job인지 DB의 job type 또는 table로 구분해서 업데이트합니다.

```java
@RestController
@RequestMapping("/internal/callback/jobs")
public class AiJobCallbackController {

    private final AiJobService aiJobService;
    private final AiEngineProperties aiEngineProperties;

    public AiJobCallbackController(
            AiJobService aiJobService,
            AiEngineProperties aiEngineProperties
    ) {
        this.aiJobService = aiJobService;
        this.aiEngineProperties = aiEngineProperties;
    }

    @PostMapping("/{jobId}/progress")
    public ResponseEntity<Void> updateProgress(
            @PathVariable String jobId,
            @RequestHeader("X-Internal-Token") String internalToken,
            @RequestBody VideoJobProgressRequest request
    ) {
        if (!aiEngineProperties.internalToken().equals(internalToken)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        aiJobService.updateVideoProgress(jobId, request.progress());
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{jobId}")
    public ResponseEntity<Void> updateResult(
            @PathVariable String jobId,
            @RequestHeader("X-Internal-Token") String internalToken,
            @RequestBody VideoJobCallbackRequest request
    ) {
        if (!aiEngineProperties.internalToken().equals(internalToken)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        aiJobService.updateVideoResult(jobId, request);
        return ResponseEntity.noContent().build();
    }
}
```

## DB 상태 전이 규칙

Spring Boot 운영 구현에서는 callback으로 받은 상태를 DB에 저장합니다. 현재 repo의 테스트 backend는 `ConcurrentHashMap` 기반 `VideoJobStore`를 사용하지만, 운영 backend에서는 같은 책임을 DB repository/service로 옮깁니다.

| 시점 | DB status | 처리 |
|---|---|---|
| 생성 요청 수신 | `queued` 또는 `pending` | `jobId`, 사용자, 사업장, 요청 payload 저장 |
| ai-engine queued 응답 수신 | `queued` | queue 등록 확인 시간 저장 |
| progress callback 수신 | `processing` | `progressPct` 갱신 |
| completed callback 수신 | `completed` | `resultUrl`, `provider`, `modelUsed`, `fallbackUsed`, `warnings`, `durationMs`, `progressPct=100` 저장 |
| failed callback 수신 | `failed` | `error`, `warnings`, `durationMs`, `progressPct=100` 저장 |

운영 규칙:

- `completed`, `failed`는 terminal status입니다.
- terminal status 이후 늦게 도착한 progress callback은 무시합니다.
- 같은 completed/failed callback이 중복 도착해도 같은 결과가 되도록 idempotent하게 처리합니다.
- `processing` 이후 `queued`로 되돌아가는 상태 역전은 허용하지 않습니다.
- 알 수 없는 `jobId` callback은 404로 거절하거나 204 응답 후 보안 로그만 남기는 정책 중 하나로 통일합니다.
- callback 유실에 대비해 오래 `queued` 또는 `processing`에 머문 job은 Spring Boot scheduled reconciler가 ai-engine status API로 보정하는 fallback polling을 둘 수 있습니다.

## WebClient 호출

```java
public Mono<VideoJobResponse> createShort(VideoShortCreateRequest request) {
    return aiEngineWebClient.post()
            .uri("/v1/video/jobs")
            .header("X-Internal-Token", internalToken)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .bodyToMono(VideoJobResponse.class);
}
```

## Controller 예시

```java
@RestController
@RequestMapping("/api/ai/video/async")
public class VideoShortController {

    private final AiEngineVideoClient aiEngineVideoClient;
    private final VideoJobService videoJobService;

    public VideoShortController(AiEngineVideoClient aiEngineVideoClient, VideoJobService videoJobService) {
        this.aiEngineVideoClient = aiEngineVideoClient;
        this.videoJobService = videoJobService;
    }

    @PostMapping("/generate")
    public Mono<VideoJobResponse> createShort(@Valid @RequestBody VideoShortCreateRequest request) {
        String jobId = UUID.randomUUID().toString();
        VideoShortCreateRequest aiEngineRequest = request.withJobId(jobId);
        videoJobService.createPendingJob(jobId, request);
        return aiEngineVideoClient.createShort(aiEngineRequest);
    }

    @GetMapping("/job/{jobId}")
    public VideoStatusResponse getStatus(@PathVariable String jobId) {
        return videoJobService.getAuthorizedStatus(jobId);
    }
}
```

## Text to Video 예시

```java
VideoShortAdvancedOverrides advanced = new VideoShortAdvancedOverrides(
        null,
        null,
        null,
        true,
        null,
        null,
        null,
        null,
        null,
        null,
        null
);

VideoShortCreateRequest request = new VideoShortCreateRequest(
        "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
        "벚꽃이 만발한 호숫가 근처를 골드리트리버와 함께 한 남자가 걷고 있어",
        "fast",
        "youtube_shorts",
        "textToVideo",
        "9:16",
        4,
        null,
        advanced,
        Map.of("campaignId", "campaign-1")
);
```

JSON:

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

## Image to Video 예시

현재 기본 흐름은 로컬 파일 업로드를 base64로 변환해 전달하는 방식입니다.

```java
VideoShortMediaInput image = new VideoShortMediaInput(
        null,
        "BASE64_IMAGE_BYTES",
        "image/png"
);

VideoShortInput input = new VideoShortInput(
        image,
        null,
        null
);

VideoShortCreateRequest request = new VideoShortCreateRequest(
        "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
        "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성",
        "fast",
        "instagram_reels",
        "imageToVideo",
        "9:16",
        4,
        input,
        null,
        null
);
```

JSON:

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

`input.image`에 `input.lastFrame`을 추가로 함께 보내는 경우는 Veo first/last frame interpolation 용도입니다. 업로드한 시작 프레임과 종료 프레임을 영상의 시간적 앵커로 유지하고, 그 사이를 자연스럽게 전환하는 데 최적화되어 있습니다.

주의:

- 시작/종료 프레임 이미지가 프롬프트의 핵심 장면과 크게 다르면 프롬프트 반영이 제한될 수 있습니다.
- 프롬프트에만 있는 새 인물, 동물, 장소, 상품을 중간 장면에 강하게 추가하는 용도에는 적합하지 않습니다.
- 예를 들어 시작/종료 프레임에 카페, 젊은 남자, 리트리버가 전혀 없다면 프롬프트에 해당 요소를 써도 결과 영상에 안정적으로 등장하지 않을 수 있습니다.
- 사용자가 업로드한 두 프레임을 유지하는 것이 우선이면 `imageToVideo + lastFrame`을 사용합니다.
- 프롬프트 장면 반영이 우선이면 `textToVideo` 또는 `referenceToVideo`를 사용하거나, 프롬프트에 맞는 시작/종료 이미지를 먼저 준비한 뒤 `imageToVideo + lastFrame`에 사용합니다.

## Reference to Video 예시

`referenceToVideo`는 `model=standard`, `durationSeconds=8`을 사용합니다. frontend는 스타일 레퍼런스 선택 시 이 값을 자동 보정하고, ai-engine도 방어적으로 같은 보정을 적용합니다.

```java
VideoShortMediaInput reference = new VideoShortMediaInput(
        null,
        "BASE64_REFERENCE_IMAGE_BYTES",
        "image/png"
);

VideoShortInput input = new VideoShortInput(
        null,
        null,
        List.of(reference)
);

VideoShortCreateRequest request = new VideoShortCreateRequest(
        "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
        "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성",
        "standard",
        "tiktok",
        "referenceToVideo",
        "9:16",
        8,
        input,
        null,
        null
);
```

JSON:

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

`gcsUri` 입력은 추후 GCS 기반 asset 저장소를 도입할 때 사용할 수 있습니다. 현재 로컬 파일 업로드 경로에서는 `bytesBase64Encoded`를 우선 사용합니다.

## Polling 흐름

1. Spring Boot가 `jobId`를 생성하고 DB에 `pending` 상태로 저장한다.
2. Spring Boot가 `jobId`를 포함해 `POST /v1/video/jobs`를 호출한다.
3. 프론트엔드는 Spring Boot의 `GET /api/ai/video/async/job/{jobId}`를 주기적으로 호출한다.
4. Spring Boot는 DB에 저장된 상태를 반환한다.
5. `ai-engine` callback으로 progress/completed/failed를 수신하면 DB 상태를 업데이트한다.
6. `status=completed`면 `videoUrl`을 저장하고 프론트에 노출한다.
7. `status=failed`면 `error`를 로그에 남기고 실패 상태를 프론트에 전달한다.

권장 polling 간격:

- 5~10초
- 현재 frontend 구현은 약 7초 간격으로 `/api/ai/video/async/job/{jobId}`를 조회
- `completed` 또는 `failed`가 되면 중단
- ai-engine 기본 최대 대기 시간은 `VIDEO_MAX_WAIT_SEC=600`

현재 repo의 Spring Boot 구현은 DB 연동 전 단계이므로 `VideoJobStore` 인메모리 저장소로 `jobId`와 상태를 관리합니다. 운영 전환 시 이 저장소를 MySQL 기반 repository로 교체해야 합니다.

## 완료 응답 예시

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "videoUrl": "http://127.0.0.1:8002/gaim/generated/videos/c2814445-0491-432a-ad99-268a6b3e7440.mp4",
  "error": null,
  "progressPct": 100
}
```

`videoUrl`은 MP4 파일 URL입니다. 프론트엔드는 이 URL을 `<video>` 태그 또는 다운로드 링크로 사용할 수 있습니다.

현재 개발 환경의 저장 위치:

```text
/Users/mjkim/project/G-AIM/GAIM_Source/storage-data/videos/{uuid}.mp4
http://127.0.0.1:8002/gaim/generated/videos/{uuid}.mp4
```

현재는 GCS에 생성 결과를 저장하지 않습니다. 추후 GCS/S3 등 외부 storage로 이전하면 `StorageAdapter` 구현, `STORAGE_PUBLIC_BASE_URL`, 입력 이미지 URI 정책이 바뀔 수 있습니다.

## 입력 검증 규칙

Spring Boot에서도 아래 규칙을 검증하는 것이 좋습니다.

- `durationSeconds`: `4`, `6`, `8`
- `model`: `fast`, `standard`, `lite`
- `aspectRatio`: `9:16`, `16:9`
- `task`: `textToVideo`, `imageToVideo`, `referenceToVideo`
- `mimeType`: `image/png`, `image/jpeg`
- `gcsUri`와 `bytesBase64Encoded` 중 정확히 하나만 전달
- `referenceImages`: 1~3장
- `referenceImages`는 `image`, `lastFrame`과 같이 전달하지 않음
- `lastFrame`은 `image`가 있을 때만 전달
- `task=textToVideo`면 `input`을 전달하지 않음
- `fps`는 전달하지 않음

`imageToVideo`에서 `input.image`와 `input.lastFrame`을 함께 쓰면 first/last frame interpolation으로 처리합니다. 이 모드는 두 이미지를 첫 장면과 마지막 장면으로 유지하는 제약이 강하므로, 프롬프트가 두 이미지와 다른 인물, 동물, 장소, 상품을 새로 추가하도록 요구하면 반영이 약하거나 누락될 수 있습니다.

## 자주 발생하는 오류

### 422 Validation Error

주요 원인:

- `X-Internal-Token` 누락
- `durationSeconds`가 `4`, `6`, `8`이 아님
- `task=textToVideo`인데 `input`이 있음
- `imageToVideo`인데 `input.image`가 없음
- `referenceToVideo`인데 `input.referenceImages`가 없음
- `gcsUri`와 `bytesBase64Encoded`를 동시에 전달

### 404 model not found

Veo model location 문제입니다.

`ai-engine/.env`에서 아래 값을 확인합니다.

```env
GCP_VIDEO_LOCATION=us-central1
```

### Unsupported output video frame rate

`fps`를 전달하면 발생할 수 있습니다. Spring Boot request DTO에 `fps`를 넣지 않습니다.

### Mock video generation does not create playable MP4

`AI_PROVIDER_MODE=mock` 상태입니다. mock 모드는 재생 가능한 MP4를 만들지 않고 job을 `failed`로 완료합니다. 실제 영상을 생성하려면 `AI_PROVIDER_MODE=live`가 필요합니다.

## curl 확인

ai-engine 직접 호출:

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

Spring Boot 상태 조회:

```bash
curl -X GET 'http://127.0.0.1:8080/api/ai/video/async/job/{jobId}'
```

ai-engine 내부 상태 조회는 개발/레거시 확인용입니다. Swagger에서도 deprecated로 표시되며 운영 상태의 source of truth는 Spring Boot입니다.

```bash
curl -X GET 'http://127.0.0.1:8002/v1/video/status/{jobId}' \
  -H 'X-Internal-Token: change-this-internal-token'
```

Spring Boot 경유 호출:

```bash
curl -X POST 'http://127.0.0.1:8080/api/ai/video/async/generate' \
  -H 'Content-Type: application/json' \
  -d '{
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
