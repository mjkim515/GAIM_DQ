# ai-engine 비동기 생성 운영 리스크 및 작업 우선순위

## 목적

`ai-engine`의 Celery worker, Redis, 이미지/비디오 비동기 생성 흐름을 운영 관점에서 다시 점검하고,
MVP 단계와 실제 운영 단계에서 필요한 보강 작업을 우선순위와 난이도 기준으로 정리한다.

이 문서는 분석 및 작업 계획 문서다. 코드 변경은 포함하지 않는다.

## 동기화 업데이트 (2026-09-03)

이 문서는 2026-09-03 기준 [`ai-engine-hardening-plan-2026-09-03.md`](./ai-engine-hardening-plan-2026-09-03.md)의
적용 상태를 반영했다.

반영된 주요 변경은 다음과 같다.

- terminal job 상태를 Celery result backend와 별도로 Redis에 24시간 저장한다.
- 내부 `/v1/*/status`는 terminal Redis를 먼저 조회하고, taskId 매핑이 있는 `PENDING`은 `queued`가 아니라
  `processing`으로 반환한다.
- WAS callback timeout은 5초로 상향하고, terminal callback은 최대 4회, progress callback은 1회만 시도한다.
- worker Redis lock은 Celery `task_id`를 token으로 사용해 동일 task redelivery를 중복 실행으로 오판하지 않는다.
- image fallback 결과는 completed callback/result/terminal status에 `fallbackUsed`, `warnings` metadata를 포함한다.
- reference image remote URL은 scheme, hostname, private/reserved IP, DNS resolve 결과를 검증한다.
- video fallback 정책은 Veo의 즉시 lifecycle/provider 오류에만 Runway fallback을 허용하고, long polling timeout과
  request validation/bad input은 fallback 없이 failed 처리한다.

최신 검증 상태:

```text
137 passed in 14.21s
```

## 분석 범위

- FastAPI job enqueue 흐름
- Celery app 및 worker task
- Redis broker/result backend 사용 방식
- 이미지/비디오 provider 호출 및 fallback
- WAS callback 연동
- local storage 저장 방식
- 메모리 및 자원 관리
- Docker/운영 실행 설정
- 시크릿/환경변수 관리
- 현재 테스트 커버리지

## 현재 구조 요약

```text
WAS
  -> POST /v1/image/jobs 또는 /v1/video/jobs
  -> ai-engine API가 Celery task enqueue
  -> Redis broker
  -> Celery worker
  -> OpenAI / Google Veo / Google image / Runway provider 호출
  -> local storage 저장
  -> WAS callback(progress/completed/failed)
  -> frontend는 WAS 상태 API polling
```

현재 방향성은 맞다. 특히 job 상태의 source of truth를 WAS DB로 두고, ai-engine은 생성 실행과 callback만
담당하는 구조는 운영 경계가 명확하다.

다만 현재 코드는 아직 MVP 수준이다. 실제 운영에서는 시크릿 관리, retry, worker 장애, callback 유실,
대용량 media 처리, storage 영속성, Redis 운영, queue 격리에서 보강이 필요하다.

## 핵심 리스크 요약

| 구분 | 내용 | 영향도 |
|---|---|---|
| 시크릿 히스토리 | `ai-engine/.env`는 현재 추적되지 않지만 과거 git history에 포함된 이력이 있음 | 매우 높음 |
| Celery retry | `max_retries`는 있으나 예외를 잡아 `failed` dict를 반환하므로 실제 retry가 거의 없음 | 높음 |
| Docker worker queue | 현재 run_*.sh 운영에는 영향이 작지만, Docker/Compose worker는 queue 구독 옵션이 없어 compose 전환 시 routed task를 소비하지 못할 수 있음, docker/Dockerfile.worker에 -Q가 없으면 routed queue를 못 소비할 수 있음 | 중간~높음 |
| callback 유실 | terminal callback은 4회 재시도와 terminal Redis 24h 보존으로 완화됐지만, ai-engine 내부 outbox는 아직 없음 | 중간~높음 |
| in-memory 상태 | API/worker 분리 시 `_JOBS`, `_IMAGE_JOB_IDS`는 운영 상태 저장소로 의미가 약함 | 높음 |
| 대용량 media | base64, URL 이미지, video bytes를 전체 메모리에 적재 | 중간~높음 |
| local storage | 운영 scale-out, 재배포, disk full에 취약 | 중간~높음 |
| Celery 운영 설정 | ack, prefetch, time limit, result expiry, max tasks per child 설정 부족 | 높음 |
| Redis 운영 | broker/result backend Redis에 persistence, auth, maxmemory 정책이 명확하지 않음 | 높음 |
| result backend payload | video task result에 request payload가 남아 media base64가 Redis에 저장될 수 있음 | 중간~높음 |
| client lifecycle | OpenAI/Google client를 매 호출 생성하고 명시적으로 close/cache하지 않음 | 중간 |
| 테스트 | mock/eager 중심이라 실제 Redis/Celery 장애를 검증하지 못함 | 중간 |

## 상세 분석

### 1. 시크릿 히스토리 노출 리스크

대상:

- `ai-engine/.env`
- `.gitignore`
- 배포/운영 환경변수 주입 방식

현재 `ai-engine/.env`는 git tracked 파일이 아니다. 다만 git history에는 추가 후 제거된 이력이 있다.
실제 API key 또는 service account key가 해당 커밋에 포함되었다면, 파일 추적을 중단한 것만으로는 해결되지 않는다.

문제:

- 과거 커밋, remote, fork, clone, CI cache에 시크릿이 남을 수 있다.
- provider key가 살아 있으면 외부 비용 발생 또는 권한 오남용으로 이어질 수 있다.
- `SECRET_KEY`, `WAS_INTERNAL_TOKEN` 기본값이 production에 남으면 내부 API 보호가 약해진다.

보강 방향:

- 노출된 적 있는 OpenAI, Google, GCP service account, Runway key는 폐기 후 재발급한다.
- git history에서 `.env`를 제거한다.
- 운영 시크릿은 `.env` 커밋이 아니라 secret manager 또는 배포 환경변수로 주입한다.
- production 부팅 시 placeholder secret/token/localhost callback URL을 거부하는 설정 validator를 둔다.

### 2. Celery retry가 실질적으로 동작하지 않음

대상:

- `app/workers/tasks/image_tasks.py`
- `app/workers/tasks/video_tasks.py`
- `app/core/exceptions.py`

`@celery_app.task(bind=True, max_retries=2)`가 선언되어 있지만 task 내부에서 대부분의 예외를 잡아
`{"status": "failed"}` 형태로 반환한다. Celery 입장에서는 task가 실패한 것이 아니라 성공적으로 종료된 것이다.

문제:

- provider timeout, rate limit, 일시적 connection error가 즉시 최종 실패가 될 수 있다.
- `ProviderRateLimitError.retryable = True` 같은 정보가 실제 Celery retry 정책에 연결되어 있지 않다.
- `max_retries=2`가 설정되어 있어도 운영자는 retry가 된다고 오해할 수 있다.

보강 방향:

- validation/auth/request 오류는 retry하지 않는다.
- timeout/rate limit/connection/service unavailable/storage transient 오류만 `self.retry(...)`로 재시도한다.
- 최종 retry 소진 후에만 `failed` callback을 전송한다.
- retry 횟수, countdown, backoff, jitter를 Celery 설정 또는 task별 정책으로 명시한다.

### 3. Docker worker가 routed queue를 소비하지 못할 수 있음

대상:

- `docker/Dockerfile.worker`
- `app/workers/celery_app.py`
- `run_worker.sh`

`celery_app.py`는 image task를 `image-queue`, video task를 `video-queue`로 라우팅한다. 로컬 `run_worker.sh`는
`-Q image-queue,video-queue`를 붙이지만 Docker worker CMD에는 queue 지정이 없다.

문제:

- Docker/compose 기반으로 실행하면 worker가 기본 `celery` queue만 바라볼 가능성이 있다.
- 이 경우 API는 queued 응답을 반환하지만 task가 처리되지 않는다.

보강 방향:

- Docker worker CMD에 `-Q ${CELERY_QUEUES:-image-queue,video-queue}` 추가.
- 가능하면 image worker와 video worker를 별도 서비스로 분리한다.

### 4. callback 유실 복구 경로가 부족함

대상:

- `app/services/callbacks.py`
- `app/workers/tasks/image_tasks.py`
- `app/workers/tasks/video_tasks.py`

callback은 2026-09-03 보강 후 terminal callback 최대 4회, progress callback 1회로 동작한다. terminal 결과는
별도 Redis key에 24시간 저장되므로 Celery result backend TTL만으로 복구 가능성이 사라지는 문제는 완화됐다.
다만 ai-engine 내부 outbox/retry task는 아직 없고, WAS가 terminal callback을 받지 못하면 frontend 상태 보정은
WAS reconciler 또는 내부 status API 재조회에 의존한다.

보강 방향:

- callback timeout을 운영 기준으로 상향한다. (2026-09-03 반영)
- 고정 sleep 대신 exponential backoff + jitter를 적용한다. (2026-09-03 반영)
- terminal 결과를 Celery result backend와 별도 Redis key로 보존한다. (2026-09-03 반영)
- terminal callback 실패는 별도 outbox/retry task로 넘긴다.
- WAS에는 오래된 queued/processing job을 보정하는 reconciler를 둔다.
- WAS callback handler는 같은 `jobId`에 대해 idempotent해야 한다.

### 5. in-memory idempotency/status 한계

대상:

- `app/api/v1/image.py`
- `app/services/video/veo_service.py`

이미지 job 중복 방지는 API 프로세스의 `_IMAGE_JOB_IDS` dict에 의존한다. 비디오 상태도 `_JOBS` dict에 저장된다.
API와 worker가 별도 프로세스가 되면 이 메모리 상태는 공유되지 않는다.

문제:

- API 재시작 시 dedup 이력이 사라진다.
- multi-worker, multi-replica 환경에서 중복 실행을 막지 못한다.
- ai-engine 내부 `/v1/video/status/{job_id}`는 운영 source of truth가 될 수 없다.

보강 방향:

- WAS DB의 `jobId UNIQUE` 제약이 1차 멱등성 기준이어야 한다.
- ai-engine은 worker 진입 시 Redis `SET job:{jobId}:lock NX EX ...` 정도의 보조 lock만 둔다.
- ai-engine 내부 status API는 개발/레거시용으로만 유지하거나 제거한다.

### 6. 대용량 media 메모리 적재

대상:

- `app/services/image/references.py`
- `app/services/video/veo_service.py`
- `app/services/video/runway_service.py`
- `app/services/image/openai_service.py`
- `app/services/image/google_service.py`

현재 reference image URL, base64 image, video input base64, Runway output, provider video bytes가 대부분 전체 메모리에
올라온다.

문제:

- 큰 base64 payload가 worker 메모리를 급격히 올릴 수 있다.
- 외부 URL 다운로드에 content length/content type 제한이 없다.
- 여러 video job이 동시에 실행되면 OOM 가능성이 커진다.

보강 방향:

- API request body size 제한.
- base64 encoded 길이와 decoded byte 크기 제한.
- reference image URL allowlist 또는 signed URL 정책.
- content-type, content-length 검증.
- video는 가능하면 provider output URI/GCS 기반으로 처리한다.
- worker process memory limit과 `worker_max_tasks_per_child`를 설정한다.

### 7. local storage 운영 한계

대상:

- `app/storage/factory.py`
- `app/storage/local.py`
- `app/services/image/storage.py`
- `app/services/video/storage.py`

현재 `STORAGE_BACKEND=local`만 구현되어 있다. `gcs_bucket_name` 설정은 있지만 GCS/S3 adapter는 없다.

문제:

- 컨테이너 재배포나 서버 교체 시 파일 유지가 어렵다.
- scale-out 시 인스턴스별 파일 경로가 달라질 수 있다.
- 파일 TTL cleanup이 없어 disk full 리스크가 있다.

보강 방향:

- MVP는 local storage + 공유 볼륨 + cleanup으로 시작 가능.
- 실제 운영은 GCS/S3/R2 adapter를 구현한다.
- public URL 또는 signed URL 정책을 명확히 한다.
- 오래된 생성물 보존 기간과 sweeper를 둔다.

### 8. Celery 운영 설정 부족

대상:

- `app/workers/celery_app.py`
- `run_worker.sh`
- `docker/Dockerfile.worker`
- `docker-compose.yml`
- `docker-compose.prod.yml`

현재 Celery 설정은 serializer, timezone, route 정도만 있다. 긴 video task에는 부족하다.

보강 방향:

- `worker_prefetch_multiplier=1`
- `task_acks_late=True`
- `task_reject_on_worker_lost=True`
- `task_soft_time_limit`
- `task_time_limit`
- `result_expires`
- `worker_max_tasks_per_child`
- Redis broker `visibility_timeout`
- image/video worker 분리

### 9. Redis broker/result backend 운영 설정 부족

대상:

- `run_redis.sh`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `app/workers/celery_app.py`

Redis는 Celery broker와 result backend로 쓰인다. 현재 로컬/compose 설정은 빠르게 띄우는 데 초점이 있고,
운영용 persistence, auth, maxmemory, eviction 정책은 명확하지 않다.

문제:

- Redis 컨테이너가 재생성되면 아직 실행 전인 queued task가 사라질 수 있다.
- maxmemory 정책이 없으면 메모리 한계에서 신규 job enqueue가 실패할 수 있다.
- result backend와 broker를 같은 Redis에 오래 보관하면 메모리 압박이 커진다.
- 로컬 Redis 포트가 그대로 노출되면 같은 host의 다른 프로세스가 broker/result를 볼 수 있다.

보강 방향:

- 운영 Redis는 managed Redis 또는 별도 broker Redis를 사용한다.
- 로컬/단일 서버라도 named volume, appendonly, requirepass/ACL, maxmemory 정책을 문서화한다.
- broker와 result backend DB를 분리하고 result TTL을 짧게 둔다.
- callback만 source of truth로 쓴다면 `task_ignore_result=True` 또는 최소 `result_expires`를 검토한다.

### 10. Celery result backend에 request payload가 과도하게 남을 수 있음

대상:

- `app/workers/tasks/video_tasks.py`
- `app/workers/celery_app.py`

video task는 result dict에 `request_data`를 다시 넣는다. `imageToVideo` 또는 `referenceToVideo` 요청에서
`bytesBase64Encoded`를 사용하면 입력 이미지 base64가 Celery result backend에도 저장될 수 있다.

문제:

- Redis DB1 메모리 사용량이 커진다.
- media payload가 broker message와 result backend 양쪽에 남는다.
- 민감한 입력 metadata가 불필요하게 오래 보관될 수 있다.

보강 방향:

- result에 원본 request 전체를 남기지 않는다.
- 필요한 경우 `jobId`, provider, model, duration, callback success 여부만 남긴다.
- `result_expires`를 짧게 설정하거나 `task_ignore_result=True`를 적용한다.
- media 입력은 base64 inline보다 object storage URI 중심으로 넘긴다.

### 11. provider HTTP/client lifecycle 관리 부족

대상:

- `app/services/image/openai_service.py`
- `app/services/text/openai_service.py`
- `app/services/image/google_service.py`
- `app/services/video/veo_service.py`

OpenAI/Google client가 요청마다 생성된다. 명시적인 close 또는 cache lifecycle이 없다. 또한 Google video generation과
operation polling은 SDK call 자체의 HTTP timeout보다 앱 레벨 polling deadline에 더 많이 의존한다.

문제:

- 장수 worker process에서 socket/file descriptor 누수 가능성이 있다.
- 매 호출 client/credential/token 생성 비용이 누적된다.
- SDK 호출 자체가 멈추면 앱 레벨 deadline까지 도달하지 못할 수 있다.

보강 방향:

- provider client 또는 credential을 안전한 범위에서 cache한다.
- OpenAI client는 timeout과 close lifecycle을 명확히 둔다.
- Google genai client 생성 시 HTTP timeout 설정 가능 여부를 확인해 반영한다.
- worker process 재활용(`worker_max_tasks_per_child`)으로 장수 process 누수를 완화한다.

### 12. eager mode foot-gun

대상:

- `app/workers/celery_app.py`
- `tests/conftest.py`
- 운영 env

`CELERY_TASK_ALWAYS_EAGER=true`가 production에 잘못 들어가면 `apply_async`가 실제 queue 등록이 아니라 API 요청
처리 중 동기 실행으로 바뀔 수 있다.

문제:

- `/v1/image/jobs`, `/v1/video/jobs`가 즉시 queued를 반환하지 못한다.
- 긴 video 생성이 FastAPI request handler를 점유한다.
- 운영 장애가 테스트와 비슷하게 보이지 않아 원인 파악이 늦어진다.

보강 방향:

- `APP_ENV != "test"`에서 eager mode를 금지하거나 startup validation으로 막는다.
- `.env.example`과 운영 문서에 test-only 옵션임을 명시한다.

### 13. 설정 문서 불일치

대상:

- `.env.example`
- `app/config.py`

`.env.example` 주석은 `GOOGLE_AUTH_MODE=api_key | service_account`라고 설명하지만 실제 config는
`api_key | vertex_ai`만 허용한다.

보강 방향:

- `.env.example` 주석을 실제 config와 맞춘다.
- 또는 config에서 `service_account` alias를 허용하고 내부적으로 `vertex_ai`로 normalize한다.

## MVP 기준 운영 리스크

MVP에서 허용 가능한 것:

- Redis broker 기반 Celery 운영
- local storage 사용
- WAS DB를 source of truth로 두는 callback 중심 상태 관리
- provider fallback을 단순하게 유지
- mock/eager 테스트와 소수 live smoke test 병행

MVP에서 최소 보강해야 하는 것:

- `.env` 히스토리 노출 여부 확인 및 키 폐기/재발급
- Docker worker queue 구독 수정
- image/video queue worker 분리 또는 최소한 queue 명시
- video worker concurrency 낮게 설정
- callback 실패 로그와 알림
- WAS stuck job reconciler
- request media size 제한
- Celery time limit/prefetch 설정
- Redis result TTL 또는 result payload 축소

MVP에서 타협 가능한 것:

- RabbitMQ 전환은 당장 필수는 아니다.
- 완전한 object storage 전환은 트래픽이 작으면 2차로 미룰 수 있다.
- 상세 progress는 provider 실제 progress가 아니라 synthetic progress로 시작해도 된다.

## 실제 운영 기준 리스크

실제 운영에서 반드시 필요한 것:

- 시크릿 매니저 또는 배포 환경변수 기반 secret 주입
- WAS DB 기반 job lifecycle 영속화
- callback 재시도/outbox/reconciler
- object storage 기반 결과 저장
- provider별 quota/rate limit/circuit breaker
- Celery worker ack/retry/time-limit 설정
- worker queue 분리 및 autoscaling 기준
- Redis managed 운영 또는 broker 분리
- Redis persistence/auth/maxmemory 정책
- queue depth, task latency, failure rate, callback success rate 모니터링
- worker kill/OOM/redeploy 시나리오 테스트

scale-out 시 깨지는 지점:

- API process memory dict 기반 idempotency
- ai-engine 내부 video status API
- local disk result URL
- 단일 worker가 image/video queue를 함께 소비하는 구조
- callback 실패를 worker result에만 남기는 구조

## 난이도 기준

| 난이도 | 의미 |
|---|---|
| S | 0.5일 이내, 단일 파일 또는 설정 수정 중심 |
| M | 1~2일, 코드와 테스트 일부 추가 필요 |
| L | 3~5일, 여러 모듈과 통합 테스트 필요 |
| XL | 1주 이상, 인프라/백엔드/운영 정책 연동 필요 |

## 작업 리스트 및 우선순위

### 진행률 요약

2026-09-03 기준 적용 상태:

| 구분 | 완료 | 부분 완료 | 대기/외부 연동 대기 | 비고 |
|---|---:|---:|---:|---|
| P0 운영 전 필수 | 7건 | 0건 | 2건 | worker queue 구독/분리, 핵심 Celery 설정, production validator, media size limit은 적용됨 |
| P1 안정화 필수 | 10건 | 3건 | 0건 | ack/lost 재처리, Redis lock/redelivery, terminal Redis, callback backoff, result payload 축소, local storage cleanup, Redis 최소 정책, 실제 Redis/Celery smoke까지 적용 |
| P2 확장 및 운영 고도화 | 0건 | 0건 | 7건 | 실제 운영 확장 과제는 미적용 |

상태 기준:

- 완료: 코드 또는 문서 적용이 끝났고 기본 검증까지 완료된 항목
- 부분 완료: 일부 적용됐지만 운영적으로 의미 있는 잔여 작업이 있는 항목
- 대기: 아직 적용하지 않은 항목
- 외부 연동 대기: WAS, provider, 운영 인프라 쪽 확인 또는 별도 구현이 필요한 항목

### P0. 운영 전 필수

| ID | 작업 | 대상 | 난이도 | 상태 | 완료율 | 적용 및 잔여 내용 | 이유 | 검증 방법 |
|---|---|---|---|---|---:|---|---|---|
| P0-0 | `.env` 히스토리 노출 대응 | git history, provider keys, secret 운영 방식 | M~L | 외부 조치 대기 | 40% | 2026-09-02 확인 결과 현재 `ai-engine/.env`는 git 추적 대상이 아니고 `.gitignore`에 포함되어 있다. 다만 git history에는 2026-08-28 `ai-engine/.env` 추가 커밋과 2026-08-31 추적 중지 커밋이 남아 있다. 마스킹 스캔 기준 `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GCP_SERVICE_ACCOUNT_JSON`, `RUNWAYML_API_SECRET` 항목이 과거 커밋에 존재했으므로 해당 credential은 폐기/재발급 대상으로 본다. git history purge 여부는 원격 공유 상태 확인 후 결정해야 한다 | 삭제된 파일도 과거 커밋에 남으면 실제 비용/권한 리스크가 있음 | provider key 폐기/재발급 확인, 필요 시 history purge 후 `git log -- ai-engine/.env`가 비어 있는지 확인 |
| P0-1 | Docker worker queue 구독 수정 | `docker/Dockerfile.worker`, `docker-compose.yml` | S | 완료 | 100% | `Dockerfile.worker`에 `CELERY_QUEUES` 기반 `-Q` 옵션과 `CELERY_WORKER_NAME` 기반 `-n` 옵션을 추가했다. dev/prod compose는 worker별 queue를 명시한다 | routed task가 실행되지 않는 치명적 문제 방지 | `docker compose config`와 image/video job 실제 consume 확인 |
| P0-2 | image/video worker 분리 실행 옵션 정리 | `run_worker.sh`, `docker-compose.yml`, 운영 문서 | S~M | 완료 | 100% | 로컬 `run_async_stack.sh`와 dev/prod Docker Compose 모두 image worker와 video worker를 별도 프로세스/service로 실행하도록 적용했다. image worker는 `image-queue`, video worker는 `video-queue`만 구독한다. 기본 동시성은 image 5, video 1이며 `CELERY_IMAGE_WORKER_CONCURRENCY`, `CELERY_VIDEO_WORKER_CONCURRENCY`로 조정한다 | 긴 video job이 image job을 막는 현상 완화 | image worker와 video worker 각각 queue consume 확인 |
| P0-3 | Celery time limit 설정 | `app/workers/celery_app.py` | S | 완료 | 100% | `app/config.py`에 soft/hard time limit 설정을 추가하고 Celery app에 반영. 기본값 soft 660초, hard 720초 | provider hang으로 worker 슬롯이 영구 점유되는 문제 방지 | 의도적 timeout task로 soft/hard limit 동작 확인 |
| P0-4 | prefetch 제한 | `app/workers/celery_app.py` | S | 완료 | 100% | `worker_prefetch_multiplier=1` 설정값을 추가하고 Celery app에 반영 | 긴 task에서 head-of-line blocking 완화 | queue에 video 여러 건 넣고 예약 개수 확인 |
| P0-5 | WAS callback idempotency 및 terminal 상태 규칙 확인 | WAS callback handler, API 연동 문서 | M | 가이드 완료 / WAS 구현 대기 | 70% | image/video Spring Boot 연동 가이드에 WAS 담당자 필수 체크리스트와 terminal 충돌 정책표를 추가했다. `jobId` unique 제약, callback transaction, row lock 또는 optimistic locking, progress/terminal idempotency, terminal 이후 progress 무시, unknown `jobId` 정책을 필수로 명시했다. ai-engine 단독으로 WAS 실제 구현 여부는 확정할 수 없으므로 WAS callback handler 구현/테스트 확인은 남아 있다 | 중복 callback/늦은 progress로 상태 역전 방지 | completed 이후 progress 무시, completed 이후 failed 무시, failed 이후 completed 보정, 중복 terminal callback 테스트 |
| P0-6 | media size 상한 추가 | schemas/service validation | M | 완료 | 100% | `MAX_IMAGE_REFERENCE_BYTES`, `MAX_VIDEO_INPUT_IMAGE_BYTES` 설정 추가. 이미지 reference base64/local URL/HTTP URL과 숏폼 비디오 입력 이미지를 provider 호출 전 byte 기준으로 제한 | base64/URL 대용량 입력으로 OOM 방지 | 제한 초과 base64/URL 요청이 400으로 거절되는지 확인 |
| P0-7 | production 설정 validator 추가 | `app/config.py`, app startup | M | 완료 | 100% | production에서 placeholder secret/token, eager mode, localhost callback, live provider key 누락을 막는 validator 추가 | placeholder secret/eager mode/localhost callback의 운영 반입 방지 | production env에서 placeholder 설정 시 부팅 실패 확인 |
| P0-8 | `.env.example` `GOOGLE_AUTH_MODE` 불일치 수정 | `.env.example`, 필요 시 `config.py` | S | 완료 | 100% | `.env.example` 주석을 실제 config와 맞게 `api_key | vertex_ai`로 수정 | 운영 설정 오류 방지 | `GOOGLE_AUTH_MODE` 값별 설정 로딩 테스트 |

### P1. 안정화 필수

| ID | 작업 | 대상 | 난이도 | 상태 | 완료율 | 적용 및 잔여 내용 | 이유 | 검증 방법 |
|---|---|---|---|---|---:|---|---|---|
| P1-1 | Celery retry 정책 실제 연결 | `image_tasks.py`, `video_tasks.py`, `provider_errors.py`, image/video provider fallback | M~L | 완료 | 100% | 반영일: 2026-09-03. MVP 기본값은 `CELERY_TASK_RETRY_ENABLED=false`로 Celery task-level provider retry를 비활성화했다. provider fallback은 같은 task 안에서만 수행한다. auth/config/validation 오류는 즉시 실패한다. `CELERY_TASK_RETRY_ENABLED=true`로 opt-in하면 retryable provider 오류에 한해 `self.retry()`가 동작한다. 이미지는 모든 외부 provider 후보가 retryable 오류로 실패한 경우에만 retry 대상으로 올리고, retryable/non-retryable 실패가 섞이면 placeholder fallback을 유지하되 `fallbackUsed`, `warnings` metadata를 callback/result/terminal status에 남긴다. 비디오는 Veo 성공 시 completed, Veo unsupported/retired/not found/provider unavailable 계열 즉시 오류 시 Runway fallback, long polling timeout과 request validation/bad input은 fallback 없이 failed 처리한다. 실패 유형별 fallback/retry/failed 정책표를 운영 가이드와 API 가이드에 갱신했다 | MVP 중복 provider 호출/비용/callback 순서 리스크 완화. 필요 시 transient provider 장애 회복을 opt-in으로 사용 | 기본 retry off, opt-in retry on, 혼합 실패 fallback, video timeout no-fallback 테스트 |
| P1-2 | `acks_late` 및 worker lost 재처리 설정 | `celery_app.py` | M | 완료 | 100% | `task_acks_late`, `task_reject_on_worker_lost`, `task_acks_on_failure_or_timeout` 설정을 추가하고 Celery app에 반영 | worker kill 시 task 유실 방지 | worker kill 후 task 재전달 확인 |
| P1-3 | Redis broker `visibility_timeout` 설정 | `celery_app.py` | S | 완료 | 100% | `CELERY_BROKER_VISIBILITY_TIMEOUT` 설정을 추가하고 기본값 900초로 Celery app에 반영 | 장시간 task 중복 재전달 방지 | visibility timeout보다 짧은 task/긴 task 시나리오 확인 |
| P1-4 | callback outbox 또는 callback retry task 추가 | `callbacks.py`, worker task, Spring Boot callback service | L | 대체 경로 적용 | 75% | 반영일: 2026-09-03. ai-engine 내부 outbox/retry task는 미적용. 대신 callback timeout을 5초로 상향하고 terminal callback은 최대 4회 exponential backoff+jitter로 재시도한다. progress callback은 지연 누적을 막기 위해 1회만 시도한다. terminal callback 실패 후에도 결과는 terminal Redis에 24시간 보존된다. Spring Boot callback endpoint가 idempotent DB update를 수행하도록 image/video 연동 가이드에 service 구현 기준을 추가했다. terminal 이후 progress 무시, terminal callback 중복 upsert, 상태 역전 방지, unknown `jobId` 처리 정책을 문서화했다 | terminal callback 유실/중복에 따른 상태 불일치 완화 | callback 실패/재시도/backoff 테스트, progress 1회 시도 테스트, WAS callback endpoint 중복/역순/unknown job 테스트 |
| P1-5 | WAS stuck job reconciler | WAS scheduled job, ai-engine status fallback API | L | 부분 완료 | 80% | 반영일: 2026-09-03. WAS DB repository 구현은 WAS 담당 영역으로 두고, image/video Spring Boot 가이드에 stuck job reconciler 기준을 추가했다. ai-engine은 `jobId -> Celery taskId`를 Redis에 저장하고, terminal job 상태를 `gaim:ai-engine:job-terminal:{job_type}:{job_id}` Redis key에 24시간 저장한다. image/video status API는 terminal Redis를 Celery result backend보다 먼저 조회한다. terminal 없음 + taskId 매핑 있음 + Celery `PENDING`이면 `queued`가 아니라 `processing`을 반환한다. 실제 Spring Boot scheduled job 구현은 남음 | callback 유실/worker 장애 후 상태 보정 | 오래된 `queued`/`processing` job이 ai-engine status API 조회 후 completed/failed로 보정되는지 확인 |
| P1-6 | worker-level Redis lock 추가 | worker task 진입부 | M | 완료 | 100% | 반영일: 2026-09-03. `app/workers/job_locks.py`를 추가하고 image/video task 진입부에 `jobId` 기반 Redis lock 적용. lock token은 Celery `task_id`를 우선 사용한다. 같은 `task_id`로 redelivery된 task는 lock TTL을 갱신하고 재진입을 허용한다. 다른 task가 같은 `jobId`로 진입하면 provider 호출 없이 `duplicate_skipped` 반환 | 같은 jobId 중복 실행 방지와 worker crash/redelivery 정합성 확보 | 동일 jobId 중복 enqueue 후 provider 1회 호출 확인, 같은 task_id redelivery 재진입 테스트 |
| P1-7 | local storage cleanup/sweeper 추가 | storage module 또는 운영 스크립트 | M | 완료 | 100% | `app/storage/local_cleanup.py`와 `tools/cleanup_local_storage.py` 추가. 기본 dry-run, `--delete` 명시 시 오래된 `images/`, `videos/` 파일 삭제 | disk full 방지 | TTL 지난 파일 삭제 dry-run/실행 검증 |
| P1-8 | 실제 Redis+Celery 통합 테스트 추가 | tests/integration 또는 scripts | M | 완료 | 100% | `tools/integration_async_stack_smoke.py` 추가. Redis ping, worker ping, active queue, duplicate lock을 live/mock 공통으로 확인한다. mock full smoke에서 image job `completed`, video short mock failure, duplicate lock `duplicate_skipped`를 확인했다. mock full smoke 전에는 `.env`에서 `AI_PROVIDER_MODE=mock`로 변경하고 async stack을 재시작해야 한다. smoke 명령에만 `AI_PROVIDER_MODE=mock`을 붙이는 오용은 provider job enqueue 전에 실패하도록 차단했다. live mode provider 호출은 `--enqueue-provider-jobs`로 비용 발생 가능성을 명시하고 실행한다 | eager/mock 테스트 한계 보완 | Redis/worker 별도 실행 후 job lifecycle 확인 |
| P1-9 | result backend payload 축소 및 TTL 설정 | `video_tasks.py`, `celery_app.py`, `job_status.py` | M | 완료 | 100% | 반영일: 2026-09-03. `result_expires=3600` 적용 완료. video task result에서 원본 `request` payload 저장을 제거하고 테스트로 고정했다. callback 유실 복구에 필요한 terminal 결과는 Celery result backend TTL에 의존하지 않도록 별도 Redis key에 24시간 저장한다 | base64 media가 Redis result에 오래 남는 문제 방지와 result TTL 만료 후 terminal 상태 복구 | result에 media가 없는지, TTL 만료되는지, terminal Redis가 Celery result보다 우선 조회되는지 확인 |
| P1-10 | Redis persistence/auth/maxmemory 정책 정리 | `run_redis.sh`, compose, 운영 문서 | M | 완료 | 100% | `run_redis.sh`와 dev compose에 AOF, `maxmemory`, `noeviction`, named volume 설정을 추가했다. `run_async_stack.sh`는 `.env` 로드 후 Redis readiness를 기다린 다음 API/worker를 시작한다. `REDIS_REQUIREPASS`와 password 포함 Redis URL 형식을 문서화했고, URL-safe hex password를 권장한다. macOS/Colima bind mount 권한 문제를 피하도록 기본 Redis 저장소를 Docker named volume으로 조정했다. 2026-09-01 실제 smoke에서 Redis auth 연결, `appendonly=yes`, `maxmemory=536870912`, `maxmemory-policy=noeviction`, image/video queue 구독, duplicate lock을 확인했다 | queue 유실, memory full, 무인증 접근 리스크 완화 | `./run_async_stack.sh` 후 `./tools/integration_async_stack_smoke.py` 실행 |
| P1-11 | provider client timeout/lifecycle 정리 | OpenAI/Google/Runway service modules | M~L | 완료 | 100% | 반영일: 2026-09-03. `OPENAI_PROVIDER_TIMEOUT_SEC`, `GOOGLE_PROVIDER_TIMEOUT_MS`, `RUNWAY_REQUEST_TIMEOUT_SEC`, `RUNWAY_DOWNLOAD_TIMEOUT_SEC`, `REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC` 설정을 추가했다. OpenAI async client는 요청별 생성 후 `close()`하고, Google genai client는 `HttpOptions(timeout=...)`로 생성한다. Runway task 생성/조회와 output download timeout도 설정화했다. `VIDEO_MAX_WAIT_SEC < CELERY_TASK_SOFT_TIME_LIMIT < CELERY_TASK_TIME_LIMIT < CELERY_BROKER_VISIBILITY_TIMEOUT` 관계를 settings validator와 테스트로 고정했다. video long polling timeout은 Runway fallback 없이 failed 처리하도록 정책을 명확히 했다 | SDK hang, fd/socket 누수, client 생성 비용 완화. fallback으로 soft time limit 예산을 초과하는 문제 방지 | timeout 설정 전달 단위 테스트, Celery limit 정렬 테스트, video timeout no-fallback 테스트 |
| P1-12 | eager mode 운영 방지 | `celery_app.py`, `config.py`, docs | S | 완료 | 100% | production에서 `CELERY_TASK_ALWAYS_EAGER=true`면 settings validator에서 부팅 실패 | 운영에서 queue 우회 동기 실행 방지 | `APP_ENV=production CELERY_TASK_ALWAYS_EAGER=true` 부팅 실패 확인 |
| P1-13 | reference image URL SSRF guard | `app/services/image/references.py`, config/docs | M | 부분 완료 | 65% | 반영일: 2026-09-03. remote reference image URL은 `http`/`https` scheme과 hostname을 요구하고, literal IP 및 DNS resolve 결과가 private/loopback/link-local/multicast/reserved/unspecified 대역이면 거절한다. storage public URL fast path는 유지한다. redirect 이후 최종 URL 재검증, 운영 allowlist, production 경고는 남아 있다 | 내부망 metadata endpoint, Redis, local service로의 SSRF 시도 차단 | private IP/literal IP/internal DNS 차단 테스트, public DNS 허용 테스트, redirect 우회 테스트 추가 필요 |

### P2. 확장 및 운영 고도화

| ID | 작업 | 대상 | 난이도 | 상태 | 완료율 | 적용 및 잔여 내용 | 이유 | 검증 방법 |
|---|---|---|---|---|---:|---|---|---|
| P2-1 | GCS/S3/R2 storage adapter 구현 | `app/storage/*` | L | 대기 | 0% | object storage adapter 미적용 | scale-out 및 재배포 안정성 | API/worker 다른 인스턴스에서 동일 URL 접근 확인 |
| P2-2 | provider output URI 기반 video 저장 흐름 지원 | `veo_service.py`, storage adapter | L | 대기 | 0% | provider URI를 직접 저장소로 옮기는 흐름 미적용 | video bytes 전체 메모리 적재 감소 | provider URI 반환 케이스 처리 테스트 |
| P2-3 | provider별 rate limit/circuit breaker | provider service layer | L | 대기 | 0% | provider별 rate limit/circuit breaker 미적용 | quota 초과와 장애 확산 방지 | provider mock 429/5xx 연속 발생 시 차단 확인 |
| P2-4 | 운영 metric/logging 확장 | logging/monitoring config | M~L | 대기 | 0% | queue depth, duration, callback 성공률 등 운영 metric 미적용 | 장애 원인 분석과 용량 계획 | queue depth, duration, callback success metric 확인 |
| P2-5 | DLQ 또는 failed job replay 절차 | Celery/Redis/WAS 운영 도구 | L | 대기 | 0% | failed job replay 절차와 도구 미적용 | 장애 후 수동 복구 가능성 확보 | failed job replay runbook 테스트 |
| P2-6 | live smoke test 자동화 | `tools/`, test docs | M | 대기 | 0% | 비용 제한 live smoke 자동화 미적용 | provider 회귀 조기 탐지 | 비용 제한을 둔 live smoke command 실행 |
| P2-7 | Redis/RabbitMQ broker 전환 검토 | infra/docs/config | XL | 대기 | 0% | Redis 유지/대체 broker 전환 검토 미수행 | 트래픽 증가 시 delivery semantics 강화 | Redis와 대체 broker 운영 비교 리포트 |

## 추천 적용 순서

1. Docker worker queue 구독을 먼저 고친다.
2. `.env` 히스토리 노출 여부를 처리하고 production 설정 validator를 넣는다.
3. worker를 image/video로 분리하고 video concurrency를 낮춘다.
4. Celery `time_limit`, `soft_time_limit`, `prefetch_multiplier=1`을 넣는다.
5. request media size 제한을 추가한다.
6. retryable error에만 Celery retry를 연결한다. (적용 완료)
7. `acks_late`, worker lost 재처리, Redis lock/redelivery 정합성을 함께 적용한다. (적용 완료)
8. terminal Redis 보존, callback backoff, WAS reconciler 계약을 정리한다. (ai-engine 적용 완료, WAS 구현 대기)
9. result backend payload/TTL과 Redis 운영 정책을 정리한다. (적용 완료)
10. reference image URL SSRF guard를 넣고 allowlist/redirect 정책을 후속으로 결정한다. (부분 완료)
11. local storage cleanup을 넣는다. (적용 완료)
12. object storage adapter를 구현한다.
13. 운영 metric, live smoke, 부하 테스트를 자동화한다.

## 검증 체크리스트

### 단위 테스트

- image/video request validation
- media size 초과 거절
- provider error classification
- retryable/non-retryable 분기
- callback payload 생성

### 로컬 통합 테스트

- Redis 실행
- FastAPI API 실행
- image worker 실행
- video worker 실행
- `/v1/image/jobs` enqueue 후 worker consume 확인
- `/v1/video/jobs` enqueue 후 worker consume 확인
- WAS callback mock endpoint로 progress/completed/failed 수신 확인

### 장애 테스트

- Redis 중단 후 enqueue 실패 처리
- worker kill 후 task 재전달 확인
- provider timeout mock 후 retry 확인
- callback endpoint 500/timeout 후 재전송 확인
- 동일 `jobId` 중복 요청 후 provider 1회 호출 확인
- 대용량 base64 payload 거절 확인
- storage write 실패 후 failed callback 확인
- worker 반복 작업 후 RSS/fd 증가 추이 확인
- Redis 재시작 후 queued task 유실 여부 확인
- Celery result backend에 media base64가 남지 않는지 확인

## 현재 테스트 상태

현재 `ai-engine` 테스트는 통과한다.

```text
137 passed in 14.21s
```

단, 테스트 환경은 `AI_PROVIDER_MODE=mock`, `CELERY_TASK_ALWAYS_EAGER=true` 중심이다. 따라서 실제 Redis broker,
별도 Celery worker 프로세스, worker kill, ack/retry, callback 유실은 별도 통합/장애 테스트가 필요하다.

## 결론

MVP는 현재 구조를 유지하되 시크릿 히스토리 대응과 WAS callback idempotency 확인은 별도로 완료해야 한다.
worker queue 구독, worker 분리, Celery time limit, media size 제한, Redis/job lock/redelivery, terminal Redis,
callback timeout/backoff, local cleanup은 코드 기준으로 적용됐다. WAS stuck job 보정은 ai-engine fallback status
API와 연동 가이드까지 적용됐고, 실제 WAS scheduled reconciler 구현은 WAS 담당 영역으로 남아 있다.

실제 운영에서는 local storage와 in-memory 상태에 기대지 않고, WAS DB + object storage + callback recovery +
명확한 Celery delivery 설정으로 전환해야 한다. 우선순위는 안정성에 직접 영향을 주는 P0/P1부터 적용하는 것이 맞다.
