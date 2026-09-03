# 멀티유저 AI 생성 SaaS — 비동기 아키텍처 설계 (MVP)

> 영상/이미지 생성 서비스 기준 — G-AIM 프로젝트

-----

## 1. 전체 아키텍처 Overview

```
[Client]
    ↓  REST API
[Spring Boot WAS]
    ↓  Job 저장 (MySQL) + 상태 캐시 (Redis) + Job 발행
[Message Queue]  ← RabbitMQ or Redis Streams
    ↓
[ai-engine Worker]  ← Python
    ↓  생성 완료 후 직접 업로드
[Object Storage]  ← S3 / R2
    ↓  URL + 완료 콜백
[Spring Boot WAS]
    ↓
[Client]  ← Polling (기본) or SSE (선택)
```

> **핵심 원칙**: 요청은 즉시 `jobId` 반환 → Worker가 백그라운드 처리 → 완료 시 콜백 + 알림

-----

## 2. Queue 시스템

**추천: RabbitMQ or Redis Streams** (Spring Boot 환경에서 BullMQ/Node보다 자연스러움)

```
┌─────────────────────────────────────┐
│           Queue 분리 전략            │
├─────────────────┬───────────────────┤
│  image-queue    │   video-queue     │
│  (빠름 ~10초)   │   (느림 ~3분)     │
│  concurrency: 5 │   concurrency: 2  │
└─────────────────┴───────────────────┘
```

- **우선순위 큐**: 유료 사용자 → 일반 사용자
- **Dead Letter Queue**: 최대 3회 재시도 실패 시 별도 보관
- **Idempotency-Key**: 중복 요청 방지 (같은 jobId 재발행 차단)

-----

## 3. Job 상태 저장 전략 — DB + Redis 역할 분리

> **DB가 진실의 원천(source of truth), Redis는 속도를 위한 캐시**

### MySQL (영구 저장)

```sql
CREATE TABLE jobs (
    id           VARCHAR(36) PRIMARY KEY,  -- jobId (UUID)
    user_id      VARCHAR(36) NOT NULL,
    type         ENUM('image', 'video') NOT NULL,
    status       ENUM('pending', 'processing', 'done', 'failed') NOT NULL,
    prompt       TEXT,
    result_url   VARCHAR(500),
    error_msg    VARCHAR(500),
    created_at   DATETIME NOT NULL,
    completed_at DATETIME
);
```

### Redis (캐시 + PubSub)

```json
// 캐시: job:{jobId}  TTL: 1시간
{
  "status": "processing",
  "progress": 45,
  "resultUrl": "https://..."
}

// PubSub channel: job-update:{jobId}
// → SSE 실시간 전달용
```

|저장소      |역할                           |비고       |
|---------|-----------------------------|---------|
|**MySQL**|Job 이력 영구 저장, source of truth|히스토리 / 통계|
|**Redis**|빠른 상태 조회 캐시, SSE PubSub      |TTL 1시간  |

-----

## 4. Spring Boot WAS 역할

### 담당하는 것 ✅

```
✅ POST /api/generate/image|video
   → MySQL에 Job 레코드 INSERT (status: pending)
   → Redis에 status 캐시
   → Queue에 Job 발행
   → jobId 즉시 반환

✅ GET /api/jobs/{jobId}
   → Redis 먼저 조회 (빠름)
   → Redis miss 시 MySQL 조회

✅ GET /api/jobs/{jobId}/stream  (SSE, 선택적)
   → Redis PubSub 구독 → 클라이언트 Push

✅ POST /internal/callback/jobs/{jobId}
   → ai-engine 완료 콜백 수신
   → MySQL status, result_url 업데이트
   → Redis 캐시 업데이트
   → SSE 알림 (연결된 경우)

✅ POST /internal/callback/jobs/{jobId}/progress
   → ai-engine 진행률 콜백 수신
   → Redis progress 업데이트
   → SSE 알림

✅ GET /api/jobs/my
   → MySQL에서 사용자 Job 목록 조회
```

### 담당하지 않는 것 ❌

```
❌ S3 직접 업로드  →  ai-engine Worker가 담당
❌ AI 모델 호출
❌ 진행률 직접 계산
```

### REST API 엔드포인트 목록

|Method  |URL                                       |설명                      |
|--------|------------------------------------------|------------------------|
|`POST`  |`/api/generate/image`                     |이미지 생성 Job 제출 → jobId 반환|
|`POST`  |`/api/generate/video`                     |영상 생성 Job 제출 → jobId 반환 |
|`GET`   |`/api/jobs/{jobId}`                       |Job 상태 조회 (폴링용)         |
|`GET`   |`/api/jobs/{jobId}/stream`                |SSE 실시간 스트림 (선택)        |
|`GET`   |`/api/jobs/my`                            |내 Job 목록 조회             |
|`DELETE`|`/api/jobs/{jobId}`                       |Job 취소                  |
|`POST`  |`/internal/callback/jobs/{jobId}`         |ai-engine 완료 콜백 (내부용)   |
|`POST`  |`/internal/callback/jobs/{jobId}/progress`|ai-engine 진행률 콜백 (내부용)  |

### Spring Boot 코드 예시

```java
// 1. Job 제출
@PostMapping("/api/generate/image")
public ResponseEntity<JobResponse> generateImage(@RequestBody GenerateRequest req) {
    String jobId = UUID.randomUUID().toString();

    // MySQL 저장 (source of truth)
    jobRepository.save(new Job(jobId, req.getUserId(), "pending"));

    // Redis 캐시
    redisTemplate.opsForValue().set("job:" + jobId,
        new JobStatus("pending"), 1, TimeUnit.HOURS);

    // Queue 발행
    jobQueueService.enqueue(jobId, req);

    return ResponseEntity.ok(new JobResponse(jobId));
}

// 2. 상태 조회 (Redis 우선 → MySQL fallback)
@GetMapping("/api/jobs/{jobId}")
public JobStatus getJobStatus(@PathVariable String jobId) {
    JobStatus cached = redisTemplate.opsForValue().get("job:" + jobId);
    if (cached != null) return cached;
    return jobRepository.findById(jobId).toStatus();
}

// 3. ai-engine 완료 콜백 수신
@PostMapping("/internal/callback/jobs/{jobId}")
public void onJobComplete(@PathVariable String jobId,
                          @RequestBody JobResult result) {
    // MySQL 업데이트 (source of truth)
    jobRepository.updateDone(jobId, result.getUrl());

    // Redis 캐시 업데이트
    redisTemplate.opsForValue().set("job:" + jobId,
        new JobStatus("done", result.getUrl()), 1, TimeUnit.HOURS);

    // SSE 알림 (연결된 경우)
    sseService.notify(jobId, result);
}
```

-----

## 5. ai-engine Worker 역할

### 담당하는 것 ✅

```
✅ Queue에서 Job 수신
✅ 프롬프트로 이미지/영상 생성
✅ 생성 결과를 S3에 직접 업로드  (Spring Boot 거치지 않음)
✅ 완료 후 Spring Boot 콜백 호출
   POST /internal/callback/jobs/{jobId}
   body: { resultUrl, status, durationMs }
✅ 실패 시 Retry (최대 3회, exponential backoff)
✅ Pseudo-progress 중간 알림 (선택)
   POST /internal/callback/jobs/{jobId}/progress
   body: { progress: 30 }  ← 타임 기반 추정값
```

### 담당하지 않는 것 ❌

```
❌ Redis 직접 접근
❌ MySQL 직접 접근
❌ 상태 관리
```

### ai-engine 코드 예시 (Python)

```python
# worker/image_worker.py
async def handle_job(job: Job):
    callback_base = f"{SPRING_BOOT_URL}/internal/callback/jobs/{job.id}"

    try:
        # 1. Pseudo-progress 알림 (시작)
        await http.post(f"{callback_base}/progress", {"progress": 10})

        # 2. AI 모델 호출 (생성만 집중)
        result_bytes = await ai_model.generate(job.prompt)

        # 3. S3 직접 업로드
        url = await s3_client.upload(result_bytes, key=f"results/{job.id}.png")

        # 4. 완료 콜백
        await http.post(callback_base, {
            "status": "done",
            "resultUrl": url,
            "durationMs": elapsed_ms
        })

    except Exception as e:
        # 실패 콜백 (최대 3회 retry 후)
        await http.post(callback_base, {"status": "failed", "error": str(e)})


# Retry 전략 (exponential backoff)
@retry(max_attempts=3, backoff=exponential(base=2))
async def ai_model_generate(prompt):
    return await model.generate(prompt)
```

-----

## 6. 클라이언트 상태 확인 전략

> **Polling 기본 + SSE 선택** (Safari / iOS / PWA 안정성 고려)

```
기본: Polling
  → 2초마다 GET /api/jobs/{jobId}
  → done or failed 받으면 중단
  → 구현 간단, 모든 환경 안정적

선택: SSE
  → GET /api/jobs/{jobId}/stream 연결
  → 브라우저 지원 시 자동 사용
  → 연결 끊기면 Polling으로 자동 fallback
```

### Pseudo-progress UX

> 실제 AI API는 정확한 진행률을 제공하지 않는 경우가 많음 → **시간 기반 추정값** 사용

```
이미지 생성 예상 10초:
  0s  → progress: 0%   "생성 중..."
  3s  → progress: 30%  "이미지 분석 중..."
  7s  → progress: 70%  "디테일 처리 중..."
  완료 → progress: 100% "완료!"
```

-----

## 7. MVP에서 제외한 것 (2차 이후)

|항목                         |이유           |
|---------------------------|-------------|
|GPU Memory Aware Scheduling|모델 1개면 불필요   |
|AI Orchestration Layer     |멀티 모델 전환 시 도입|
|Circuit Breaker            |트래픽 증가 후 도입  |
|비용 추적 / quota 제한           |2차 과금 모듈과 함께 |
|Content Moderation Pipeline|2차 안전 모듈과 함께 |
|Webhook 보안                 |외부 연동 시 도입   |

-----

## 8. MVP 핵심 원칙 요약

```
1. DB(MySQL)가 진실의 원천  →  Redis는 속도를 위한 캐시일 뿐
2. S3 업로드는 Worker가  →  Spring Boot는 URL만 받음
3. Polling 기본, SSE는 보너스 (fallback 구현 필수)
4. ai-engine은 생성 + 업로드 + 콜백만
5. Spring Boot는 상태관리 + 알림 + API 전담
6. Retry는 ai-engine Worker 내부에서 최대 3회
7. GPU 스케줄링 / Orchestration은 2차
```

-----

## 9. 기술 스택 (MVP 기준)

|항목             |추천 기술                             |
|---------------|----------------------------------|
|**WAS**        |Spring Boot                       |
|**Queue**      |RabbitMQ or Redis Streams         |
|**DB**         |MySQL                             |
|**캐시 / PubSub**|Redis 7+                          |
|**Storage**    |AWS S3 / Cloudflare R2            |
|**실시간 알림**     |Polling 기본 + SSE 선택               |
|**ai-engine**  |Python (FastAPI or Worker process)|

-----

## 10. G-AIM 적용 타당성 검토 및 단계별 적용 권장안

### 결론

이 문서의 큰 방향은 G-AIM 아키텍처에 타당하다.

G-AIM처럼 Spring Boot WAS가 사용자, 비즈니스, 권한, DB를 관리하고 `ai-engine`이 AI 생성 실행을 담당하는 구조라면, **Job lifecycle의 소유권은 Spring Boot WAS에 두는 것이 맞다.**

다만 이 문서의 Queue, Redis, SSE, DLQ, retry 전략을 모두 한 번에 적용하기보다는 현재 G-AIM 코드 상태에 맞춰 단계적으로 적용하는 것이 적절하다.

### 타당한 핵심 원칙

#### 1. jobId는 WAS가 생성하고 관리해야 한다

`jobId`는 단순한 작업 번호가 아니라 사용자 요청 이력의 식별자다.

따라서 다음 데이터와 함께 WAS DB에서 관리되어야 한다.

- `userId`
- `businessId`
- `campaignId`
- 생성 타입
- 요청 payload
- 상태
- 결과 URL
- 실패 사유
- 생성/완료 시각

프론트엔드가 `GET /api/jobs/{jobId}` 또는 `GET /api/video/status/{jobId}`를 호출할 때, WAS는 반드시 현재 로그인 사용자가 해당 job을 조회할 권한이 있는지 확인해야 한다.

이 권한 검증은 `ai-engine`이 아니라 WAS의 책임이다.

#### 2. DB가 source of truth이고 Redis는 보조 캐시여야 한다

MySQL은 영구 이력, 사용자별 조회, 실패 이력, 통계, 과금 근거를 담당한다.

Redis는 빠른 상태 조회, TTL 캐시, SSE/PubSub 같은 UX 보조 기능을 담당한다.

따라서 최종 상태의 기준은 항상 MySQL이어야 하며, Redis는 없어도 서비스의 정합성이 깨지지 않는 보조 계층으로 두는 것이 맞다.

#### 3. ai-engine은 상태 저장소가 아니라 실행기여야 한다

`ai-engine`은 다음 역할에 집중해야 한다.

- Queue 또는 내부 API에서 job 수신
- 프롬프트와 옵션을 바탕으로 AI 모델 호출
- 결과 파일 업로드
- 진행률, 완료, 실패 callback 전송

반대로 `ai-engine`은 다음 역할을 맡지 않는 것이 좋다.

- 사용자 권한 관리
- `userId + jobId` 매핑 관리
- MySQL 직접 접근
- Redis 직접 접근
- 장기 job 이력 관리

Python worker가 WAS DB 스키마와 권한 모델을 직접 알기 시작하면 서비스 경계가 흐려지고 운영 복잡도가 커진다.

### 현재 G-AIM 코드와의 차이

현재 `ai-engine`은 1차로 WAS 발급 `jobId`를 받아 callback을 보내는 구조까지 반영되어 있다. 다만 Queue/Redis/SSE까지 포함한 완전한 운영형 멀티유저 구조는 아직 아니다.

- 영상 생성 요청은 외부 JSON 필드 `jobId`를 필수로 받고, 내부 Python에서는 `job_id`로 사용한다.
- `ai-engine`은 완료/실패/progress를 Spring Boot callback으로 전달한다.
- `_JOBS` 메모리 dict와 `GET /v1/video/status/{job_id}`는 개발/레거시 확인용으로 남아 있다.
- RabbitMQ 기반 자체 video worker를 사용한다. Celery placeholder는 제거되었다.
- 이미지 생성은 아직 job 기반 비동기가 아니라 동기 API다.

이 구조는 단일 로컬 프로세스에서는 동작할 수 있지만, 다음 상황에서는 문제가 된다.

- 개발/레거시 status endpoint는 `ai-engine` 재시작 시 상태가 소실될 수 있음
- Queue worker 수평 확장은 아직 미구현
- 사용자별 권한 검증 불가
- 사용자 작업 이력 조회 및 과금 근거 관리 어려움
- 장애 발생 시 재시도와 복구 흐름 불명확

### 단계별 적용 권장안

#### 1차: Job 소유권 정리

가장 먼저 적용해야 할 범위다.

Spring Boot WAS:

- 인증 사용자 확인
- `jobId` 생성
- DB에 `userId + businessId + jobId + status=pending` 저장
- `ai-engine`에 `jobId` 포함 요청
- 프론트엔드에 `jobId` 즉시 반환
- callback 수신 후 DB 상태 업데이트
- 프론트엔드 polling 요청에 DB 기준 상태 반환

ai-engine:

- WAS가 전달한 `jobId`를 그대로 사용한다. 반영 완료.
- 자체 `uuid4()` job 생성은 제거했다. 반영 완료.
- 완료/실패/progress를 WAS callback으로 전달한다. 반영 완료.
- `_JOBS` 메모리 상태 의존은 운영 흐름에서는 제거했지만, 개발/레거시 status endpoint 호환용으로 남아 있다.

Frontend:

- WAS가 반환한 `jobId`로 WAS 상태 API만 polling
- `ai-engine` 상태 API를 직접 알지 않음

#### 2차: Queue 도입

트래픽 증가, 긴 영상 작업 안정화, worker 수평 확장이 필요해지는 시점에 적용한다.

- RabbitMQ 또는 Redis Streams 도입
- image queue와 video queue 분리
- video queue concurrency 제한
- retry와 DLQ 적용
- `ai-engine`을 FastAPI 요청 처리기가 아니라 worker process로 분리

#### 3차: Redis/SSE/진행률 고도화

DB polling 부하나 실시간 UX 개선이 필요할 때 적용한다.

- Redis TTL 캐시
- Redis PubSub 기반 SSE
- polling fallback 유지
- pseudo-progress 메시지 고도화

### G-AIM 기준 권장 흐름

```text
Frontend
  -> POST /api/video/short

Spring Boot WAS
  -> 인증 사용자 확인
  -> jobId 생성
  -> DB에 userId + businessId + jobId + status=pending 저장
  -> ai-engine에 jobId 포함 요청 또는 queue 발행
  -> jobId 반환

ai-engine
  -> jobId를 그대로 사용
  -> AI 생성 실행
  -> 결과 업로드
  -> WAS callback 호출

Spring Boot WAS
  -> DB status/resultUrl/error 업데이트
  -> Frontend polling 응답
```

### 최종 판단

이 문서의 핵심 원칙은 G-AIM에 적합하다.

- `jobId`는 WAS가 생성하고 관리하는 것이 맞다.
- `userId + jobId`는 WAS DB에서 함께 관리해야 한다.
- `ai-engine`은 상태 저장소가 아니라 생성 실행기로 두는 것이 맞다.
- DB가 source of truth이고 Redis는 캐시라는 원칙도 맞다.
- Queue, Redis, SSE는 좋은 방향이지만 현재 단계에서는 순차 적용이 적절하다.

따라서 G-AIM에서는 1차로 반영한 WAS 발급 `jobId`와 callback 중심 구조를 기준으로 Spring Boot DB 상태 관리를 연결하고, 이후 Queue worker와 Redis/SSE를 순차 도입하는 것이 다음 목표가 되어야 한다.
