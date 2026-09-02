# Celery Worker 운영 가이드라인

## 목적

이 문서는 `ai-engine`의 이미지/비디오 비동기 생성 작업을 Celery worker로 운영할 때의 queue 분리,
worker 분리, concurrency 산정, 확장 기준, 장애 대응 기준을 정리한다.

핵심은 다음과 같다.

- 이미지와 비디오 queue는 이미 논리적으로 분리되어 있다.
- 운영상 필요한 것은 image worker process와 video worker process를 분리해서 운영하는 것이다.
- video worker는 `concurrency=1`부터 시작해 provider quota, 비용, 메모리, SLA를 보며 단계적으로 늘린다.

## 현재 queue 구조

현재 Celery task routing은 다음 구조다.

| 작업 | Celery task | Queue |
|---|---|---|
| 이미지 생성 | `app.workers.tasks.image_tasks.generate_image_task` | `image-queue` |
| 비디오 생성 | `app.workers.tasks.video_tasks.generate_video_task` | `video-queue` |
| 숏폼 비디오 생성 | `app.workers.tasks.video_tasks.generate_video_short_task` | `video-queue` |

관련 파일:

- `app/workers/celery_app.py`
- `app/api/v1/image.py`
- `app/services/video/veo_service.py`
- `run_worker.sh`

`run_worker.sh`의 기본값은 다음과 같다. 이 값은 `run_worker.sh`를 직접 실행할 때의 기본값이다.

```bash
CELERY_QUEUES=image-queue,video-queue
CELERY_WORKER_CONCURRENCY=3
```

이 기본값은 단일 worker를 직접 띄워 빠르게 확인할 때는 편하지만, 운영에서는 image worker와 video worker를
분리하는 것이 좋다. `run_async_stack.sh`는 이 원칙에 맞춰 image worker와 video worker를 별도 프로세스로
실행한다.

## worker 분리 운영 원칙

queue 분리와 worker 분리는 다르다.

```text
queue 분리:
  image task는 image-queue로 들어가고 video task는 video-queue로 들어간다.

worker 분리:
  image-queue만 소비하는 worker process와 video-queue만 소비하는 worker process를 따로 띄운다.
```

비디오 생성은 이미지 생성보다 훨씬 오래 걸리고, provider 비용과 메모리 사용량도 크다. 하나의 worker pool이
image/video queue를 동시에 소비하면 긴 video task가 worker slot을 오래 점유해 image task가 밀릴 수 있다.

운영에서는 다음처럼 분리한다.

```bash
# 이미지 전용 worker
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh

# 비디오 전용 worker
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

로컬에서 image/video worker를 동시에 띄울 때는 Celery inspect 결과가 섞이지 않도록 worker name을 구분한다.
`run_async_stack.sh`는 기본적으로 다음 이름을 사용한다.

```bash
CELERY_IMAGE_WORKER_NAME=ai-image-worker@%h
CELERY_VIDEO_WORKER_NAME=ai-video-worker@%h
```

## video worker를 1개로 시작하는 이유

`video worker 1개 + concurrency=1`은 처리량을 크게 늘리는 설정이 아니다. 이 설정의 목적은 격리와 backpressure다.

효과:

- 비디오 작업이 이미지 작업의 worker slot을 빼앗지 않는다.
- provider 비용 폭주를 막는다.
- Google Veo/Runway rate limit에 천천히 접근한다.
- worker OOM 또는 hang의 장애 범위를 줄인다.
- 운영 초기에 queue 대기시간과 평균 생성 시간을 측정할 수 있다.

한계:

- 동시에 처리되는 비디오 job은 1개다.
- 나머지 비디오 job은 `video-queue`에 쌓인다.
- 동시 사용자 요청은 받을 수 있지만, 실제 비디오 생성은 순차 처리된다.

따라서 MVP는 `concurrency=1`로 시작하고, 베타부터 video worker 수를 늘려 실제 처리량을 키운다.

## 동시 요청과 동시 생성의 차이

Celery 기반 비동기 구조에서는 사용자가 동시에 많은 요청을 보내도 API는 job을 Redis queue에 넣고 바로
`queued`를 반환할 수 있다.

다만 실제 생성 동시성은 worker 수와 concurrency가 결정한다.

```text
동시 이미지 처리 수 = image worker 수 × image concurrency
동시 비디오 처리 수 = video worker 수 × video concurrency
```

예시:

| 구성 | 실제 동시 처리 수 |
|---|---:|
| image worker 1개, concurrency 3 | 이미지 3개 |
| image worker 2개, concurrency 3 | 이미지 6개 |
| video worker 1개, concurrency 1 | 비디오 1개 |
| video worker 3개, concurrency 1 | 비디오 3개 |
| video worker 2개, concurrency 2 | 비디오 4개 |

비디오는 worker 하나에 `concurrency=2` 이상을 주는 것보다, 여러 worker process/container를 두고 각각
`concurrency=1`로 운영하는 편이 더 안전하다. worker 하나가 OOM 또는 hang 상태가 되어도 다른 worker에 미치는
영향이 작다.

## 처리량 산정

대기시간은 대략 다음 공식으로 추정한다.

```text
평균 대기시간 ≈ 큐에 쌓인 job 수 ÷ 동시 처리 수 × 평균 생성 시간
```

비디오 평균 생성 시간이 4분이라고 가정하면:

| video 동시 처리 수 | 시간당 처리량 | 20개 job 대기 시 마지막 완료 |
|---:|---:|---:|
| 1개 | 약 15개/시간 | 약 80분 |
| 2개 | 약 30개/시간 | 약 40분 |
| 4개 | 약 60개/시간 | 약 20분 |
| 8개 | 약 120개/시간 | 약 10분 |

이미지 평균 생성 시간이 20~40초라면:

| image 동시 처리 수 | 평균 20초 기준 | 평균 40초 기준 |
|---:|---:|---:|
| 3개 | 약 540개/시간 | 약 270개/시간 |
| 6개 | 약 1080개/시간 | 약 540개/시간 |
| 10개 | 약 1800개/시간 | 약 900개/시간 |

이 수치는 provider rate limit, 저장소 성능, callback 처리량, 네트워크 상태를 제외한 단순 계산이다. 실제 운영에서는
측정값으로 보정해야 한다.

## 권장 운영 프로파일

### MVP

목표:

- 기능 검증
- queue/callback 흐름 검증
- provider 비용 통제
- 장애 범위 최소화

권장:

```text
image worker: 1개, concurrency=2~3
video worker: 1개, concurrency=1
```

예시:

```bash
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

### 소규모 베타

목표:

- 동시 사용자 요청을 받아 queue 대기시간을 측정
- video 처리량 2~3개 동시 생성까지 검증
- provider quota와 비용 추적

권장:

```text
image worker: 1~2개, 각 concurrency=3
video worker: 2~3개, 각 concurrency=1
```

예시:

```bash
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh

CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

### 운영 초기

목표:

- 평균 대기시간 SLA 관리
- provider limit 내에서 안정적 확장
- worker 장애 격리

권장:

```text
image 동시 처리: 6~10
video 동시 처리: 3~5
```

예시:

```text
image worker 2개 × concurrency 3 = image 동시 처리 6개
video worker 3개 × concurrency 1 = video 동시 처리 3개
```

### 확장 단계

목표:

- queue depth와 SLA 기준 autoscaling
- provider quota 증설
- object storage 전환
- Redis/RabbitMQ 등 broker 운영 안정화

권장:

- video worker는 먼저 개수를 늘리고, 개별 worker concurrency는 1을 유지한다.
- provider quota와 비용 예산이 확인된 뒤에만 video concurrency를 2 이상으로 올린다.
- video 동시 처리 5개 이상부터는 memory, storage, callback 처리량을 함께 본다.

## worker 확장 상한

worker는 기술적으로 여러 개 띄울 수 있다. 하지만 실제 상한은 다음 요소가 결정한다.

- Google Veo / Runway API quota
- provider rate limit
- provider 비용 예산
- worker memory
- video bytes 저장 방식
- Redis memory
- Redis broker 안정성
- local storage 또는 object storage 처리량
- WAS callback 처리량
- 사용자가 허용 가능한 대기시간 SLA

운영 판단 기준:

```text
worker를 늘려도 되는 경우:
  queue depth가 계속 증가하고,
  provider rate limit이 여유 있고,
  worker memory가 안정적이며,
  callback success rate가 높고,
  storage write latency가 안정적일 때

worker를 늘리면 안 되는 경우:
  provider 429/5xx가 증가하거나,
  worker RSS가 계속 증가하거나,
  Redis memory가 빠르게 증가하거나,
  callback 실패가 발생하거나,
  storage disk usage가 임계치에 가까울 때
```

## Celery 설정 가이드

긴 video task를 운영하려면 기본 Celery 설정만으로는 부족하다.

권장 설정:

```python
celery_app.conf.update(
    worker_prefetch_multiplier=1,
    task_soft_time_limit=660,
    task_time_limit=720,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 900,
    },
)
```

현재 코드에서는 아래 환경변수로 조절한다.

| 환경변수 | 기본값 | 의미 |
|---|---:|---|
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | worker slot이 미리 예약하는 task 수 |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `660` | soft timeout 초 |
| `CELERY_TASK_TIME_LIMIT` | `720` | hard timeout 초 |
| `CELERY_RESULT_EXPIRES` | `3600` | result backend TTL 초 |
| `CELERY_BROKER_VISIBILITY_TIMEOUT` | `900` | Redis broker 재전달 visibility timeout 초 |
| `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP` | `true` | worker 시작 시 broker 재연결 시도 |
| `CELERY_TASK_ACKS_LATE` | `true` | task 완료 후 ack 처리 |
| `CELERY_TASK_REJECT_ON_WORKER_LOST` | `true` | worker process 유실 시 broker 재전달 허용 |
| `CELERY_TASK_ACKS_ON_FAILURE_OR_TIMEOUT` | `true` | 최종 실패/timeout task의 무한 재전달 방지 |
| `CELERY_TASK_RETRY_ENABLED` | `false` | Celery task-level provider retry 사용 여부. MVP 기본값은 비활성화 |
| `CELERY_TASK_RETRY_COUNTDOWN` | `15` | `CELERY_TASK_RETRY_ENABLED=true`일 때 retryable provider 오류 재시도 대기 초 |
| `CELERY_JOB_LOCK_TTL` | `900` | worker-level `jobId` Redis lock TTL 초 |
| `CELERY_JOB_LOCK_ENABLED` | `true` | worker-level Redis lock 사용 여부 |

`acks_late`와 `task_reject_on_worker_lost`는 worker kill 시 task 유실을 줄이는 데 필요하다. 현재 worker 진입부에는
`jobId` 기반 Redis lock이 있어 같은 작업이 동시에 중복 실행되는 것을 한 번 더 막는다.
video 작업은 `VIDEO_MAX_WAIT_SEC < CELERY_TASK_SOFT_TIME_LIMIT < CELERY_TASK_TIME_LIMIT < CELERY_BROKER_VISIBILITY_TIMEOUT`
순서가 지켜져야 한다. 이 관계가 깨지면 설정 로딩 단계에서 실패하도록 막는다.

## Provider Timeout 기준

provider 호출은 worker slot을 오래 점유할 수 있으므로 SDK/HTTP timeout을 명시한다.

| 환경변수 | 기본값 | 의미 |
|---|---:|---|
| `OPENAI_PROVIDER_TIMEOUT_SEC` | `60` | OpenAI text/image client request timeout 초 |
| `GOOGLE_PROVIDER_TIMEOUT_MS` | `60000` | Google genai client HTTP timeout ms |
| `RUNWAY_REQUEST_TIMEOUT_SEC` | `30` | Runway task 생성/조회 HTTP timeout 초 |
| `RUNWAY_DOWNLOAD_TIMEOUT_SEC` | `60` | Runway output 다운로드 timeout 초 |
| `REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC` | `20` | 외부 reference image 다운로드 timeout 초 |

OpenAI async client는 요청마다 생성하고 사용 후 close한다. 전역 singleton으로 공유하지 않는 이유는 API 서버와
Celery worker의 event loop 수명이 다르고, 테스트와 worker 재시작 시 credential/env 변경 가능성이 있기 때문이다.
Google sync client는 SDK `HttpOptions`에 timeout을 넣어 생성한다.

## Provider 실패 처리 정책

provider 장애를 실제로 완전히 재현하기는 어렵다. 운영 코드는 provider SDK/HTTP layer에서 전달된 예외 타입을
기준으로 fallback, Celery retry, 즉시 실패를 결정한다.

| 실패 유형 | 이미지 provider fallback | 비디오 provider fallback | Celery retry | 이유 |
|---|---:|---:|---:|---|
| 요청 validation 오류 | 아니오 | 아니오 | 아니오 | 같은 요청을 반복해도 성공하지 않음 |
| provider auth/config 오류 | 아니오 | 아니오 | 아니오 | 설정 오류를 fallback으로 숨기지 않음 |
| rate limit | 예 | 예 | 기본 아니오, opt-in 시 fallback 모두 retryable 실패이면 예 | 일시 장애 가능성이 높음 |
| timeout | 예 | 예 | 기본 아니오, opt-in 시 fallback 모두 retryable 실패이면 예 | worker slot 회수와 중복 provider 호출 위험을 함께 관리해야 함 |
| connection 오류 | 예 | 예 | 기본 아니오, opt-in 시 fallback 모두 retryable 실패이면 예 | 네트워크 일시 장애 가능성 |
| provider 5xx/service unavailable | 예 | 예 | 기본 아니오, opt-in 시 fallback 모두 retryable 실패이면 예 | provider 일시 장애 가능성 |
| provider request rejected | 후보별 fallback 가능 | 후보별 fallback 가능 | 아니오 | 모델/요청 호환성 문제일 수 있어 후보 전환까지만 시도 |
| 알 수 없는 예외 | sanitized warning 후 fallback | sanitized warning 후 fallback | 아니오 | 원인을 숨기지 않도록 warning만 남김 |

MVP 기본값은 `CELERY_TASK_RETRY_ENABLED=false`다. 이 경우 task-level Celery retry를 하지 않고, 같은 task 안에서
provider fallback만 시도한다. 이미지 provider가 모두 실패하면 local placeholder까지 fallback하고, 비디오 provider가
모두 실패하면 최종 실패 callback을 보낸다. 이 기본값은 provider 비용 중복, 긴 영상 작업의 중복 실행, callback 순서
혼선을 줄이기 위한 선택이다.

`CELERY_TASK_RETRY_ENABLED=true`로 켜면 retryable provider 오류가 Celery retry 대상이 된다. 이미지는 모든 외부
provider 후보가 timeout/rate limit/connection/service unavailable 같은 retryable 오류로 실패한 경우에만 local
placeholder 대신 retryable 오류를 worker로 올린다. retryable 오류와 non-retryable provider 오류가 섞이면 retry하지
않고 fallback 결과를 사용한다. provider auth/config 오류는 fallback 없이 즉시 실패한다.

비디오는 Google/Veo 실패 후 Runway fallback을 시도할 수 있다. `CELERY_TASK_RETRY_ENABLED=true`인 경우에는
Google/Veo가 timeout/rate limit/connection 오류로 실패했고 Runway가 auth/config 오류로 실패한 상황에서도 앞선
retryable 오류를 보존해 Celery retry 대상으로 유지한다. 기본값인 false에서는 마지막 실패를 기준으로 실패 callback을
보낸다.

## Redis MVP 최소 정책

Redis는 Celery broker와 result backend로 쓰이므로 MVP에서도 아래 설정은 적용한다.

| 항목 | 권장값 | 이유 |
|---|---|---|
| `REDIS_APPENDONLY` | `yes` | Redis/container 재시작 시 queue 유실 범위 축소 |
| `REDIS_MAXMEMORY` | `512mb` 이상 | result backend와 queue 누적으로 인한 메모리 폭주 방지 |
| `REDIS_MAXMEMORY_POLICY` | `noeviction` | 임의 eviction으로 task/result가 사라지는 상황 방지 |
| `REDIS_REQUIREPASS` | 운영/공유 네트워크에서 설정 | 무인증 Redis 접근 방지 |

Redis auth를 켜면 `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` 모두
`redis://:password@host:6379/db` 형식으로 맞춘다.

권장 순서:

1. WAS DB에서 `jobId` unique 보장.
2. worker 진입부에 Redis lock 또는 equivalent guard 추가.
3. `task_acks_late=True` 적용.
4. `task_reject_on_worker_lost=True` 적용.
5. worker kill 재전달 테스트.

주의:

- `worker_prefetch_multiplier=1`은 긴 task에서 예약만 많이 잡아두는 문제를 줄인다.
- `task_time_limit`은 provider SDK hang으로 worker slot이 영구 점유되는 것을 막는다.
- `visibility_timeout`은 Redis broker가 너무 빨리 task를 재전달하지 않도록 task 최대 실행 시간보다 길게 둔다.
- `result_expires`는 Redis result backend 메모리 증가를 제한한다.

## 실행 예시

### 로컬 개발 기본 실행

```bash
./run_async_stack.sh
```

이 명령은 Redis, FastAPI API, image worker, video worker를 함께 실행한다.

기본값:

```bash
CELERY_IMAGE_QUEUES=image-queue
CELERY_VIDEO_QUEUES=video-queue
CELERY_IMAGE_WORKER_CONCURRENCY=3
CELERY_VIDEO_WORKER_CONCURRENCY=1
```

즉 로컬 전체 스택 기본 실행도 image/video worker가 분리된다.

### 로컬에서 worker 분리 실행

터미널 1:

```bash
./run_redis.sh
```

터미널 2:

```bash
./run_server.sh
```

터미널 3:

```bash
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
```

터미널 4:

```bash
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

### 비디오 worker 여러 개 실행

동시 비디오 처리 수를 3개로 올리려면 video worker를 3개 띄운다.

```bash
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

### Docker/Compose 주의사항

Docker worker도 queue를 명시해야 한다.

```bash
celery -A app.workers.celery_app.celery_app worker \
  --loglevel=info \
  --concurrency=${CELERY_WORKER_CONCURRENCY:-3} \
  -Q ${CELERY_QUEUES:-image-queue,video-queue} \
  -n ${CELERY_WORKER_NAME:-ai-worker@%h}
```

dev/prod compose에서는 service를 분리한다.

```yaml
image-worker:
  environment:
    CELERY_QUEUES: image-queue
    CELERY_WORKER_CONCURRENCY: ${CELERY_IMAGE_WORKER_CONCURRENCY:-5}
    CELERY_WORKER_NAME: ai-image-worker@%h

video-worker:
  environment:
    CELERY_QUEUES: video-queue
    CELERY_WORKER_CONCURRENCY: ${CELERY_VIDEO_WORKER_CONCURRENCY:-1}
    CELERY_WORKER_NAME: ai-video-worker@%h
```

Compose에서 Redis auth를 켠 경우에는 컨테이너 내부 hostname을 써야 하므로 아래처럼 `redis` host를 사용한다.

```env
REDIS_REQUIREPASS=your-hex-password
DOCKER_REDIS_URL=redis://:your-hex-password@redis:6379/0
DOCKER_CELERY_BROKER_URL=redis://:your-hex-password@redis:6379/0
DOCKER_CELERY_RESULT_BACKEND=redis://:your-hex-password@redis:6379/1
```

## 모니터링 지표

필수 지표:

- `image-queue` depth
- `video-queue` depth
- active task count
- reserved task count
- image task duration p50/p95
- video task duration p50/p95
- provider별 success/failure count
- provider별 rate limit count
- callback success/failure count
- callback latency
- worker RSS memory
- worker restart count
- Redis memory usage
- Redis connected clients
- storage disk usage 또는 object storage write latency

운영 알림 기준 예시:

| 지표 | 알림 기준 예시 |
|---|---|
| `video-queue` depth | 10분 이상 지속 증가 |
| video task p95 | SLA의 1.5배 초과 |
| provider 429 | 5분 동안 연속 발생 |
| callback failure | terminal callback 1건 이상 실패 |
| worker RSS | 제한의 80% 초과 |
| Redis memory | maxmemory의 80% 초과 |
| local storage disk | 80% 초과 |

local storage disk가 증가하는 경우:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine

# 삭제 후보 확인
./tools/cleanup_local_storage.py

# 실제 삭제
./tools/cleanup_local_storage.py --delete
```

`LOCAL_STORAGE_RETENTION_SECONDS` 기본값은 604800초, 즉 7일이다. cleanup은 `images/`, `videos/` 하위의
오래된 생성 파일만 대상으로 하며, `--delete`를 주지 않으면 파일을 삭제하지 않는다.

운영에서는 먼저 dry-run과 1회 수동 삭제를 확인한 뒤 cron에 등록한다.

```bash
cd /path/to/ai-engine
mkdir -p logs

# 삭제 후보 확인
./tools/cleanup_local_storage.py > logs/storage-cleanup.dry-run.log 2>&1

# 실제 삭제 1회 수동 검증
./tools/cleanup_local_storage.py --delete >> logs/storage-cleanup.log 2>&1
```

crontab 예시:

```cron
# 매일 03:00에 LOCAL_STORAGE_RETENTION_SECONDS보다 오래된 생성 파일 삭제
0 3 * * * cd /path/to/ai-engine && ./tools/cleanup_local_storage.py --delete >> logs/storage-cleanup.log 2>&1
```

주의:

- `/path/to/ai-engine`은 실제 배포 경로로 바꾼다.
- cron 실행 계정이 `STORAGE_BASE_DIR/images`, `STORAGE_BASE_DIR/videos` 파일을 삭제할 권한을 가져야 한다.
- GCS/S3/R2 전환 후에는 object storage lifecycle rule을 별도로 설정한다.

worker 배포 또는 재시작 후 smoke test:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine

# Redis와 active queue만 확인
./tools/integration_async_stack_smoke.py --skip-jobs

# mock mode에서는 실제 task lifecycle까지 확인
# 실행 전 .env에서 AI_PROVIDER_MODE=mock로 설정하고 async stack을 재시작한다.
./tools/integration_async_stack_smoke.py

# live mode에서 provider 호출까지 포함해 확인. provider 비용이 발생할 수 있음
./tools/integration_async_stack_smoke.py --enqueue-provider-jobs
```

이 smoke test는 `active_queues`에 `image-queue`, `video-queue`가 모두 있는지 확인한다. 둘 중 하나가 빠지면 해당
worker가 뜨지 않았거나 잘못된 queue를 구독하는 상태다. `AI_PROVIDER_MODE=live` 기본 실행에서는 provider job을
`skipped`로 표시하고 Redis, worker, active queue, duplicate lock만 확인한다. mock full smoke를 할 때는 `.env`의
`AI_PROVIDER_MODE=mock` 설정이 worker process에 반영되도록 async stack을 재시작해야 한다. 명령 앞에만
`AI_PROVIDER_MODE=mock`을 붙이면 이미 실행 중인 worker에는 반영되지 않으므로, smoke script는 `.env`가 mock이
아닌 상태의 mock provider job enqueue를 차단한다.

## 장애 대응

### video queue가 계속 쌓이는 경우

확인:

- provider rate limit 발생 여부
- video worker active task 수
- worker hang 여부
- callback 실패로 stuck job이 아닌지
- 평균 생성 시간이 증가했는지

대응:

- provider quota가 여유 있으면 video worker를 1개씩 추가한다.
- quota가 부족하면 frontend/WAS에서 대기시간 안내 또는 생성 제한을 둔다.
- worker hang이면 time limit 설정과 worker 재시작 정책을 확인한다.

### image job이 느려지는 경우

확인:

- image worker가 video queue까지 소비하고 있지 않은지
- image worker concurrency가 너무 낮은지
- provider 429/5xx가 증가했는지
- Redis queue depth가 증가하는지

대응:

- image worker를 video worker와 분리한다.
- image concurrency를 2~3에서 시작해 단계적으로 늘린다.
- provider rate limit이 발생하면 concurrency를 낮춘다.

### worker가 hang 되는 경우

확인:

- provider SDK call timeout 설정
- provider timeout 설정이 현재 `.env`/운영 환경에 반영됐는지 확인
- `task_time_limit`
- `task_soft_time_limit`
- worker RSS/fd 증가

대응:

- time limit을 적용한다.
- worker를 재시작한다.
- `worker_max_tasks_per_child`를 설정한다.
- OpenAI client close, Google `HttpOptions`, Runway HTTP timeout 설정을 확인한다.

### worker가 OOM으로 죽는 경우

확인:

- video 동시 처리 수
- base64 media 입력 크기
- Runway/Veo output bytes 크기
- local storage write 중 메모리 피크

대응:

- video worker concurrency를 1로 낮춘다.
- worker 수를 줄인다.
- `MAX_IMAGE_REFERENCE_BYTES`, `MAX_VIDEO_INPUT_IMAGE_BYTES`로 media size limit을 적용한다.
- `worker_max_tasks_per_child`, `worker_max_memory_per_child`를 적용한다.
- object storage URI 기반 흐름으로 전환한다.

### callback 실패가 발생하는 경우

확인:

- `WAS_BASE_URL`
- `WAS_INTERNAL_TOKEN`
- WAS callback endpoint 상태
- callback timeout
- reverse proxy/firewall

대응:

- terminal callback 실패는 알림을 발생시킨다.
- callback retry/backoff를 늘린다.
- outbox 또는 WAS reconciler로 최종 상태를 복구한다.
- WAS callback handler를 idempotent하게 유지한다.

### Redis 장애가 발생하는 경우

확인:

- Redis process/container 상태
- Redis memory
- Redis persistence 설정
- broker/result backend URL
- worker broker reconnect 로그

대응:

- Redis를 복구한다.
- queued job 유실 가능성을 WAS DB 기준으로 확인한다.
- stuck job을 reconciler로 재시도 또는 실패 처리한다.
- 운영에서는 managed Redis 또는 broker 전용 Redis를 검토한다.

### provider rate limit이 발생하는 경우

확인:

- provider별 429 count
- 현재 동시 생성 수
- retry 폭증 여부
- fallback provider까지 연쇄 실패하는지

대응:

- worker 수 또는 concurrency를 낮춘다.
- retry backoff와 jitter를 적용한다.
- 사용자/사업장별 quota를 WAS에서 제한한다.
- provider quota 증설 전까지 video queue 처리량 목표를 낮춘다.

## 검증 시나리오

MVP 검증:

- image worker 1개, video worker 1개로 분리 실행
- image job 3개, video job 1개 enqueue
- image job이 video job과 무관하게 완료되는지 확인
- video job progress/completed callback이 WAS에 반영되는지 확인

베타 검증:

- video worker 2~3개로 확장
- 비디오 10~20개를 동시에 enqueue
- queue 대기시간, 평균 생성 시간, provider 429 여부 확인
- worker RSS와 Redis memory 확인

장애 검증:

- worker kill 후 task 재전달 여부 확인
- callback endpoint 중단 후 복구 여부 확인
- Redis 재시작 시 queued job 유실 여부 확인
- 대용량 base64 입력 거절 확인
- provider timeout mock 후 worker slot 회수 확인

## 최종 권장안

MVP:

```text
image worker: 1개, concurrency=2~3
video worker: 1개, concurrency=1
```

소규모 베타:

```text
image worker: 1~2개, 각 concurrency=3
video worker: 2~3개, 각 concurrency=1
```

운영 초기:

```text
image 동시 처리: 6~10
video 동시 처리: 3~5
```

비디오 동시 처리 수는 provider quota와 비용 예산을 확인하면서 한 번에 크게 올리지 말고 1개씩 늘린다.
사용자 동시 요청 수는 queue가 흡수할 수 있지만, 실제 완료 시간은 video 동시 처리 수와 평균 생성 시간에 의해
결정된다.
