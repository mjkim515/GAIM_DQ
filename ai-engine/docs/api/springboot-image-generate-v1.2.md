# Spring Boot 이미지 생성 연동 가이드

> Version: v1.2

## 요약

Spring Boot는 OpenAI/Google 모델을 직접 선택하지 않습니다.

프론트엔드에서 받은 사용자 입력을 Spring Boot API `POST /api/ai/image/async/generate`로 받고, Spring Boot가 `jobId`를 생성한 뒤 내부 API `POST /v1/image/jobs`로 전달하면, `ai-engine` worker가 모델 후보를 선택하고 fallback까지 처리합니다.

이미지 생성은 비동기 작업입니다. 프론트엔드는 Spring Boot의 `GET /api/ai/image/async/job/{jobId}`를 polling 하고, Spring Boot는 ai-engine callback으로 받은 job 상태를 반환합니다.
`GET /v1/image/status/{jobId}`는 callback 유실 보정용 fallback API입니다. 운영 상태의 source of truth는 Spring Boot DB입니다.

```text
frontend /api/ai/image/async/generate
-> Spring Boot
-> jobId 생성
-> ai-engine /v1/image/jobs
-> local storage-data/images 저장
-> Spring Boot callback(progress/completed/failed)
-> callback 유실 시 Spring Boot reconciler가 ai-engine status fallback 조회
-> frontend /api/ai/image/async/job/{jobId} polling
```

## 설정

```yaml
ai-engine:
  base-url: http://127.0.0.1:8002
  internal-token: change-this-internal-token
```

`internal-token` 값은 `ai-engine/.env`의 `WAS_INTERNAL_TOKEN`과 같아야 합니다.

## 상태 동기화 원칙

정상 경로는 ai-engine의 callback push입니다. ai-engine status API 조회는 callback push를 대체하지 않습니다.

Spring Boot 구현 기준:

1. frontend는 Spring Boot의 `GET /api/ai/image/async/job/{jobId}`만 polling합니다.
2. ai-engine worker는 `progress 5`, `progress 90`, `completed` 또는 `failed` callback을 Spring Boot로 push합니다.
3. Spring Boot는 callback을 받아 DB 상태를 갱신합니다.
4. `GET /v1/image/status/{jobId}`는 Spring Boot scheduled reconciler만 사용하는 fallback 조회 API입니다.
5. 사용자가 보는 운영 상태의 source of truth는 항상 Spring Boot DB입니다.

```text
정상 경로:
ai-engine worker -> Spring Boot callback endpoint -> Spring Boot DB -> frontend polling

선택 보정 경로:
Spring Boot scheduled reconciler -> ai-engine status API -> Spring Boot DB 보정
```

| 경로/기능 | 필수 여부 | 목적 |
|---|---:|---|
| ai-engine callback push | 필수 | 정상 상태 업데이트 |
| Spring Boot DB 상태 API | 필수 | frontend polling의 기준 상태 제공 |
| Spring Boot scheduled reconciler | 선택 | callback 유실, WAS 재시작, 일시 timeout 시 상태 보정 |
| ai-engine status API | 선택 | reconciler가 사용하는 fallback 조회 |

최소 MVP는 callback push와 Spring Boot DB 상태 API만으로 동작할 수 있습니다. 다만 callback이 유실되면 사용자가
계속 `queued` 또는 `processing` 상태를 볼 수 있으므로, 안정화 MVP 또는 실제 운영에서는 scheduled reconciler를
추가하는 것을 권장합니다.

따라서 WAS 담당자는 ai-engine status API를 frontend에 직접 노출하지 않습니다. 이 API는 callback 유실, WAS 재시작,
배포 중 callback endpoint timeout처럼 정상 callback push를 놓친 경우에만 사용합니다.

## 요청 DTO

```java
import java.util.List;

public record ImageCreateRequest(
        String purpose,
        String visual_mood,
        List<String> channels,
        String image_prompt,
        List<ReferenceImage> reference_images,
        String text_to_render,
        TextRendering text_rendering,
        Integer n
) {
}
```

```java
public record TextRendering(
        String text,
        String language,
        String placement,
        Boolean must_render_exactly,
        String font_hint,
        String color_hint
) {
}
```

```java
public record ReferenceImage(
        String image_url,
        String file_id,
        String b64_json,
        String mime_type
) {
}
```

Spring Boot가 ai-engine에 전달할 때는 WAS가 발급한 `jobId`를 포함한 job 요청 DTO로 변환합니다.

```java
public record ImageJobCreateRequest(
        String jobId,
        String purpose,
        String visual_mood,
        List<String> channels,
        String image_prompt,
        List<ReferenceImage> reference_images,
        String text_to_render,
        TextRendering text_rendering,
        Integer n
) {
}
```

## Frontend 입력 매핑

현재 이미지 생성 화면은 `ImageGeneration.jsx` 단일 화면에서 아래 입력을 구성합니다.

| UI | API 필드 | 값 |
|---|---|---|
| 목적 | `purpose` | `홍보`, `이벤트`, `브랜드` |
| 플랫폼 프리셋 | `channels[0]` | `instagram`, `instagram_story`, `instagram_reels`, `blog`, `naver_place`, `banner`, `custom` |
| 가로 세로 비율 | 라우팅용 channel context | `1:1`, `9:16`, `16:9` |
| 생성 갯수 | `n` | 1-4 |
| 비주얼 무드 (선택) | `visual_mood` | 기본 `bright` |
| 프롬프트 | `image_prompt` | 사용자 textarea 입력 |
| 이미지 참고 | `reference_images` | `b64_json`, `mime_type` |
| 문구 삽입 | `text_rendering` | 정확 렌더링 옵션 |

플랫폼 프리셋은 UI 표시명과 내부 채널 값을 분리합니다.

| 프리셋 | 표시 | `channels[0]` |
|---|---|---|
| `instagram` | Instagram 피드 (1:1) | `instagram` |
| `instagram_story` | Instagram 스토리 (9:16) | `instagram_story` |
| `instagram_reels` | Instagram 릴스 (9:16) | `instagram_reels` |
| `blog` | 블로그/상세페이지 (16:9) | `blog` |
| `naver_place` | 네이버 플레이스 (1:1) | `naver_place` |
| `banner` | 배너/팝업 (16:9) | `banner` |
| `custom` | 직접 설정 | `custom` |

## 비주얼 무드 처리

`visual_mood`는 선택값이지만 frontend 기본값은 `bright`입니다. UI에는 `현재 설정값 : 밝고 화사한`을 한 줄로 보여주고, `옵션 더보기`를 눌렀을 때 나머지 선택지를 노출합니다.

| 값 | UI 라벨 | 프롬프트 보강 | OpenAI style 파생값 |
|---|---|---|---|
| `bright` | 밝고 화사한 | 깨끗하고 밝은 하이키 조명, 선명한 색감 | `vivid` |
| `warm_cozy` | 따뜻하고 아늑한 | 따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기 | `natural` |
| `moody` | 감성적이고 깊이 있는 | 분위기 있는 저조도 조명, 깊이 있는 색감 | `natural` |
| `clean_minimal` | 깔끔하고 미니멀한 | 미니멀한 구성, 넉넉한 여백, 중립적인 색감 | `natural` |
| `premium` | 고급스럽고 세련된 | 고급스러운 질감, 정제된 구도, 세련된 시각 연출 | `natural` |
| `vibrant` | 선명하고 생동감 | 높은 채도, 활기찬 분위기, 강한 색 대비 | `vivid` |

OpenAI의 `vivid`/`natural`은 API request용 파생값입니다. 동시에 `visual_mood`는 provider와 무관하게 최종 이미지 프롬프트에 자연어 힌트로 반영합니다.

## Job 응답 DTO

```java
import java.util.List;

public record ImageJobResponse(
        String jobId,
        String status,
        String message
) {
}
```

## 상태 응답 DTO

```java
import java.util.List;

public record ImageStatusResponse(
        String jobId,
        String status,
        List<String> images,
        String provider,
        String modelUsed,
        String error,
        Integer progressPct
) {
}
```

`images`, `provider`, `modelUsed`는 `completed` 상태에서 채워집니다. 실패 시 `error`가 채워집니다.

라우팅 상세가 필요한 경우 ai-engine completed callback payload에 포함하도록 확장할 수 있지만, 현재 Spring Boot 상태 DTO의 기본 계약은 위 필드 중심입니다.

## Callback 수신 API

`ai-engine`은 이미지 생성 job의 진행률과 최종 결과를 Spring Boot callback API로 push합니다. Spring Boot는 이 API를 internal endpoint로 열어두고, 수신한 payload를 `jobId` 기준으로 DB에 반영합니다.

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

Docker Compose로 ai-engine을 실행하고 Spring Boot backend가 host에서 `8080`으로 실행 중이면, 컨테이너 내부의 `localhost`는 host가 아닙니다. 이 경우 `ai-engine/.env`는 아래처럼 설정합니다.

```env
WAS_BASE_URL=http://host.docker.internal:8080
```

현재 `ai-engine` callback 송신 구현:

```text
ai-engine/app/services/callbacks.py
```

이미지 worker는 작업 시작 후 progress `5`, provider 생성 완료 후 progress `90`, 저장 완료 후 `completed` callback을 보냅니다. 실패하면 `failed` callback을 보냅니다. `5`, `90`은 OpenAI/Google provider가 제공하는 실제 진행률이 아니라 backend와 frontend가 상태 문구를 전환하기 위한 synthetic progress hint입니다.

Callback 송신은 최대 3회 재시도됩니다. 재시도는 이미지 생성을 다시 수행하는 것이 아니라, progress/result callback payload만 다시 전송합니다. 따라서 Spring Boot callback update 로직은 같은 `jobId`에 대해 idempotent해야 합니다.

### Progress callback

```json
{
  "progress": 5
}
```

Spring Boot는 progress callback을 받으면 해당 job을 `processing`으로 전환하고 `progressPct`를 갱신합니다.

```java
public record ImageJobProgressRequest(
        Integer progress
) {
}
```

### Completed callback

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

### Failed callback

```json
{
  "status": "failed",
  "error": "provider request failed",
  "durationMs": 12345
}
```

```java
import java.util.List;

public record ImageJobCallbackRequest(
        String status,
        List<String> images,
        String provider,
        String modelUsed,
        String error,
        Long durationMs
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
            @RequestBody ImageJobProgressRequest request
    ) {
        if (!aiEngineProperties.internalToken().equals(internalToken)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        aiJobService.updateImageProgress(jobId, request.progress());
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{jobId}")
    public ResponseEntity<Void> updateResult(
            @PathVariable String jobId,
            @RequestHeader("X-Internal-Token") String internalToken,
            @RequestBody ImageJobCallbackRequest request
    ) {
        if (!aiEngineProperties.internalToken().equals(internalToken)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        aiJobService.updateImageResult(jobId, request);
        return ResponseEntity.noContent().build();
    }
}
```

## DB 상태 전이 규칙

Spring Boot 운영 구현에서는 callback으로 받은 상태를 DB에 저장합니다. 현재 repo의 테스트 backend는 `ConcurrentHashMap` 기반 `ImageJobStore`를 사용하지만, 운영 backend에서는 같은 책임을 DB repository/service로 옮깁니다.

| 시점 | DB status | 처리 |
|---|---|---|
| 생성 요청 수신 | `queued` 또는 `pending` | `jobId`, 사용자, 사업장, 요청 payload 저장 |
| ai-engine queued 응답 수신 | `queued` | queue 등록 확인 시간 저장 |
| progress callback 수신 | `processing` | `progressPct` 갱신 |
| completed callback 수신 | `completed` | `images`, `provider`, `modelUsed`, `durationMs`, `progressPct=100` 저장 |
| failed callback 수신 | `failed` | `error`, `durationMs`, `progressPct=100` 저장 |

운영 규칙:

- `completed`, `failed`는 terminal status입니다.
- terminal status 이후 늦게 도착한 progress callback은 무시합니다.
- 같은 completed/failed callback이 중복 도착해도 같은 결과가 되도록 idempotent하게 처리합니다.
- ai-engine queued 응답이 늦게 도착해도 이미 `processing`, `completed`, `failed`로 진행된 DB 상태를 `queued`로 되돌리지 않습니다.
- `processing` 이후 `queued`로 되돌아가는 상태 역전은 허용하지 않습니다.
- 알 수 없는 `jobId` callback은 404로 거절하거나 204 응답 후 보안 로그만 남기는 정책 중 하나로 통일합니다.
- callback 유실에 대비해 오래 `queued` 또는 `processing`에 머문 job은 Spring Boot scheduled reconciler가 ai-engine status API로 보정하는 fallback polling을 둘 수 있습니다.

### Idempotent update 구현 가이드

운영 DB repository 구현은 Spring Boot/WAS 담당 영역입니다. 다만 repository가 DB든 현재 테스트용
`ConcurrentHashMap`이든 service 계층의 상태 전이 규칙은 같아야 합니다.

권장 상태 순서:

```text
pending/queued -> processing -> completed
pending/queued -> processing -> failed
pending/queued -> failed
```

구현 기준:

- `completed`, `failed`는 terminal 상태이며 이후 callback은 상태를 되돌리지 않습니다.
- 같은 terminal callback이 중복 도착하면 같은 값으로 upsert하고 성공 응답을 반환합니다.
- terminal 이후 늦게 도착한 progress callback은 무시하고 성공 응답을 반환합니다.
- `queued` 응답이 늦게 처리되어도 기존 `processing`, `completed`, `failed`를 `queued`로 되돌리지 않습니다.
- 알 수 없는 `jobId`는 운영 정책에 따라 `404` 또는 `204 + security log` 중 하나로 통일합니다.

예시:

```java
@Transactional
public void updateImageProgress(String jobId, int progress) {
    AiImageJob job = imageJobRepository.findByJobIdForUpdate(jobId)
            .orElseThrow(() -> new UnknownAiJobException(jobId));

    if (job.isTerminal()) {
        return;
    }

    job.markProcessing(Math.max(job.getProgressPct(), progress));
}

@Transactional
public void updateImageResult(String jobId, ImageJobCallbackRequest callback) {
    AiImageJob job = imageJobRepository.findByJobIdForUpdate(jobId)
            .orElseThrow(() -> new UnknownAiJobException(jobId));

    if (job.isTerminal()) {
        job.mergeSameTerminalCallback(callback);
        return;
    }

    if ("completed".equals(callback.status())) {
        job.markCompleted(
                callback.images(),
                callback.provider(),
                callback.modelUsed(),
                callback.durationMs()
        );
        return;
    }

    if ("failed".equals(callback.status())) {
        job.markFailed(callback.error(), callback.durationMs());
        return;
    }

    throw new IllegalArgumentException("Unsupported ai-engine callback status: " + callback.status());
}
```

DB repository 구현 시에는 `job_id`에 unique index를 두고, callback update는 row lock 또는 optimistic locking으로
동시 callback 경합을 막습니다.

### WAS 담당자 필수 체크리스트

아래 항목은 Spring Boot/WAS에서 직접 구현 또는 테스트로 확인해야 합니다.

| 항목 | 필수 여부 | 기준 |
|---|---:|---|
| `jobId` unique 제약 | 필수 | 같은 `jobId`가 두 번 생성/저장되지 않음 |
| callback update transaction | 필수 | 상태 조회와 변경이 하나의 transaction에서 수행됨 |
| row lock 또는 optimistic locking | 필수 | progress/result callback 동시 도착 시 상태가 꼬이지 않음 |
| progress idempotency | 필수 | 같은 progress가 여러 번 와도 무해하고 `progressPct`가 감소하지 않음 |
| terminal idempotency | 필수 | 같은 completed/failed callback이 여러 번 와도 결과가 중복 저장되지 않음 |
| terminal 이후 progress 무시 | 필수 | `completed`/`failed` 이후 progress가 와도 상태를 되돌리지 않음 |
| terminal 간 충돌 정책 | 필수 | `completed` 이후 `failed`, `failed` 이후 `completed` 처리 정책이 고정됨 |
| unknown `jobId` 정책 | 필수 | 404 또는 204+security log 중 하나로 통일 |
| scheduled reconciler | 선택 | callback 유실 보정이 필요할 때만 구현 |

권장 terminal 간 충돌 정책:

| 현재 DB 상태 | 들어온 callback | 권장 처리 |
|---|---|---|
| `completed` | `completed` | 같은 결과로 upsert 또는 무시 후 성공 응답 |
| `completed` | `failed` | 무시 후 성공 응답. 이미 노출 가능한 결과가 있으므로 실패로 되돌리지 않음 |
| `failed` | `failed` | 같은 결과로 upsert 또는 무시 후 성공 응답 |
| `failed` | `completed` | `images`가 있으면 completed로 보정 허용. 없으면 무시 또는 오류 로그 |
| `completed`/`failed` | `progress` | 무시 후 성공 응답 |

MVP에서 최소로 필요한 것은 scheduled reconciler가 아니라 위 idempotent update 규칙입니다. reconciler는 callback이
유실됐을 때 오래 멈춘 job을 보정하는 선택 기능입니다.

### Stuck job reconciler

정상 경로는 callback push입니다. reconciler는 callback 유실, WAS 재시작, 배포 중 callback endpoint timeout을
보정하기 위한 fallback입니다.

권장 기준:

| 대상 | 조건 | 처리 |
|---|---|---|
| `queued` | queue 등록 후 2분 이상 callback 없음 | ai-engine status 조회 |
| `processing` | 마지막 progress 이후 3분 이상 변화 없음 | ai-engine status 조회 |
| `processing` | 생성 시작 후 10~15분 이상 terminal 없음 | ai-engine status 조회 후 결과 없으면 실패 처리 |
| terminal | `completed`, `failed` | reconciler 대상 제외 |

이미지 보정용 ai-engine endpoint:

```http
GET /v1/image/status/{jobId}
X-Internal-Token: change-this-internal-token
```

응답 예:

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "images": [
    "http://127.0.0.1:8002/gaim/generated/images/358dd53d-6983-42b1-a949-f3dd71f25684.png"
  ],
  "provider": "google",
  "modelUsed": "gemini-2.5-flash-image",
  "error": null,
  "progressPct": 100,
  "durationMs": 12345
}
```

주의:

- ai-engine status API는 운영 source of truth가 아니라 callback 유실 보정용 fallback입니다.
- ai-engine이 Redis에 저장한 `jobId -> Celery taskId` 매핑과 Celery result backend TTL이 남아 있을 때만 보정할 수 있습니다.
- status API가 `Unknown job_id`를 반환하고 WAS job deadline도 초과했다면 WAS는 해당 job을 `failed`로 마감합니다.
- reconciler는 같은 job을 여러 번 보정해도 안전하도록 callback update와 동일한 idempotent service를 호출해야 합니다.

## ai-engine 내부 생성 결과

worker 내부에서 provider 실행이 성공하면 ai-engine은 아래 형태의 생성 결과를 callback payload로 변환합니다. Celery result backend에는 최종 상태와 함께 callback 전송 성공 여부가 `callbacks` 객체로 남습니다. 이 값은 장애 분석용이며, frontend에 제공하는 운영 source of truth는 Spring Boot DB 상태입니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "durationMs": 12345,
  "callbacks": {
    "started": true,
    "finalizing": true,
    "completed": true
  }
}
```

```java
public record Routing(
        String primary_channel,
        String final_prompt,
        Integer selected_rank,
        Candidate selected,
        List<Candidate> attempted_models,
        Boolean fallback_used,
        List<String> warnings
) {
}

public record Candidate(
        Integer rank,
        String provider,
        String model,
        String operation,
        String size,
        Integer n,
        String reason
) {
}
```

## WebClient 호출

```java
public Mono<ImageJobResponse> createImageJob(ImageJobCreateRequest request) {
    return aiEngineWebClient.post()
            .uri("/v1/image/jobs")
            .header("X-Internal-Token", internalToken)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .bodyToMono(ImageJobResponse.class);
}
```

## 일반 이미지 생성

```java
ImageCreateRequest request = new ImageCreateRequest(
        "홍보",
        "warm_cozy",
        List.of("instagram"),
        "신선한 과일을 판매하는 밝고 깔끔한 상점 이미지",
        null,
        null,
        null,
        3
);
```

## 텍스트 삽입 이미지 생성

```java
TextRendering textRendering = new TextRendering(
        "오늘 딸기 30% 할인",
        "ko",
        "bottom",
        true,
        null,
        null
);

ImageCreateRequest request = new ImageCreateRequest(
        "홍보",
        "vibrant",
        List.of("instagram"),
        "과일 가게 할인 행사 홍보 이미지",
        null,
        null,
        textRendering,
        1
);
```

## 참조 이미지 기반 생성

현재 frontend 업로드 흐름은 파일을 base64로 읽어서 `b64_json`과 `mime_type`으로 전달합니다.

```java
ReferenceImage reference = new ReferenceImage(
        null,
        null,
        "BASE64_IMAGE_BYTES",
        "image/png"
);

ImageCreateRequest request = new ImageCreateRequest(
        "이벤트",
        "bright",
        List.of("instagram"),
        "참조 이미지를 활용해서 과일 가게 봄맞이 이벤트 이미지로 만들어줘",
        List.of(reference),
        null,
        null,
        1
);
```

`image_url`은 스키마상 지원되지만, 현재 frontend 로컬 파일 업로드 흐름에서는 `b64_json`을 우선 사용합니다.

## 참조 이미지 기반 텍스트 삽입

```java
ImageCreateRequest request = new ImageCreateRequest(
        "이벤트",
        "warm_cozy",
        List.of("instagram"),
        "참조 이미지를 기반으로 봄맞이 이벤트 광고 이미지로 편집하고 문구를 넣어줘",
        List.of(reference),
        null,
        new TextRendering(
                "오늘의 신선 과일",
                "ko",
                "bottom",
                true,
                null,
                null
        ),
        1
);
```

## Spring Boot가 직접 보내지 않는 값

아래 값은 Spring Boot가 직접 보내지 않습니다.

- `provider`
- `model`
- `quality`
- `size`
- `quality_priority`
- `text_importance`
- OpenAI API Key
- Google API Key
- GCP Service Account

텍스트 정확도 여부는 `text_to_render` 또는 `text_rendering` 존재 여부를 보고 `ai-engine`이 내부에서 판단합니다.

## 상태 확인 포인트

- `status`: `queued`, `processing`, `completed`, `failed`
- `images`: 생성된 이미지 URL
- `modelUsed`: 실제 성공한 모델
- `provider`: 실제 성공한 provider
- `progressPct`: 진행률
- `error`: 실패 사유

텍스트 요청에서 OpenAI가 실패하고 Nano Banana로 fallback하면 ai-engine callback/status payload의 routing warning에 한글 텍스트 정확도 저하 가능성이 기록될 수 있습니다.

현재 개발 환경에서 생성 이미지는 로컬 storage에 저장되고 completed 상태의 `images` URL로 반환됩니다.

```text
/Users/mjkim/project/G-AIM/GAIM_Source/storage-data/images/{uuid}.png
http://127.0.0.1:8002/gaim/generated/images/{uuid}.png

```

## curl 확인

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

Spring Boot 상태 조회:

```bash
curl -X GET http://127.0.0.1:8080/api/ai/image/async/job/f3325b10-bfcc-4ef3-814e-b1fcd47338fd
```
