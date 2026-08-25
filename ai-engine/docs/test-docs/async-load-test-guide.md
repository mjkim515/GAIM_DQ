# 비동기 이미지/비디오 동시성 테스트 가이드

## 목적

동시 사용자 3명 이하 조건에서 이미지/비디오 생성 요청이 HTTP 요청 안에서 오래 대기하지 않고, `jobId` 기반 비동기 흐름으로 처리되는지 확인한다.

테스트는 frontend를 여러 개 띄우지 않고 backend async API를 직접 호출한다.

## 사전 조건

- Docker가 실행 중이어야 한다.
- ai-engine `.venv`와 backend Maven 실행 환경이 준비되어 있어야 한다.
- 실제 provider 호출을 검증하려면 `ai-engine/.env`의 `AI_PROVIDER_MODE=live`와 provider 인증 값이 필요하다.
- 빠른 흐름 검증만 할 때는 `AI_PROVIDER_MODE=mock`으로도 충분하다.

## 환경별 준비

`run_all.sh`는 Redis가 없을 때 Docker로 `redis:7-alpine` 컨테이너를 실행한다. 따라서 Redis를 Docker로 띄울 수 있는 상태여야 한다.

### macOS - Docker Desktop 사용

Docker Desktop을 실행한 뒤 Docker daemon이 준비됐는지 확인한다.

```bash
docker info
```

`docker info`가 실패하면 Docker Desktop 앱을 먼저 실행한다.

### macOS - Colima 사용

Docker Desktop 대신 Colima를 쓰는 경우 Docker daemon을 먼저 띄운다.

```bash
colima start
docker info
```

`colima start` 후에도 `docker info`가 실패하면 Docker context를 확인한다.

```bash
docker context ls
docker context use colima
```

### Linux

Docker daemon이 실행 중인지 확인한다.

```bash
docker info
```

systemd 환경이면 아래처럼 Docker를 시작할 수 있다.

```bash
sudo systemctl start docker
```

현재 사용자가 Docker socket에 접근할 권한이 없으면 `docker ps`에서 permission denied가 발생할 수 있다. 이 경우 Docker group 권한을 설정하거나 관리자 권한으로 실행해야 한다.

### Redis를 직접 실행하는 경우

이미 로컬 Redis가 `6379` 포트에서 실행 중이면 `run_async_stack.sh`와 `run_all.sh`는 기존 Redis를 재사용한다.

```bash
redis-server --port 6379
```

이 경우 Docker/Colima는 Redis 실행 용도로는 필요하지 않다.

## 서버 구동 - ai-engine 담당자용

ai-engine 담당 범위만 실행하려면 `ai-engine` 디렉토리에서 async stack을 실행한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./run_async_stack.sh
```

`run_async_stack.sh`는 아래 프로세스를 실행한다.

```text
Redis
ai-engine API
ai-engine Celery worker
```

frontend와 backend는 실행하지 않는다. 동시성 테스트 스크립트는 backend API를 호출하므로, 실제 end-to-end 테스트를 하려면 WAS 담당자가 backend를 별도로 실행해야 한다.

Redis는 `run_redis.sh`로 실행된다. 이미 `6379` 포트에 Redis가 떠 있으면 기존 Redis를 재사용하고, 없으면 Docker로 `redis:7-alpine` 컨테이너를 실행한다.

Celery worker는 `run_worker.sh`로 실행된다.

기본 worker 설정:

```text
queues: image-queue,video-queue
concurrency: 3
```

ai-engine async stack을 중지하려면 다른 터미널에서 아래 명령을 실행한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./stop_async_stack.sh
```

`stop_async_stack.sh`는 ai-engine API, ai-engine Celery worker, `gaim-ai-engine-redis` Redis 컨테이너를 중지한다. 이미 실행 중인 외부 Redis를 재사용한 경우에는 Docker 컨테이너가 아니므로 Redis를 직접 중지해야 한다.

## 서버 구동 - 전체 로컬 통합 실행

frontend, backend, ai-engine을 한 번에 띄워 로컬 통합 테스트를 하려면 프로젝트 루트에서 전체 스택을 실행한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org
./run_all.sh
```

`run_all.sh`는 아래 프로세스를 함께 실행한다.

```text
Redis
ai-engine API
ai-engine Celery worker
backend
frontend
```

## 동시성 테스트 실행

backend가 실행 중인 상태에서 다른 터미널에서 실행한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./tools/load_async_jobs.py --image-jobs 3 --video-jobs 3 --concurrency 3 --poll
```

위 명령은 다음 작업을 수행한다.

```text
1. POST /api/ai/image/async/generate 를 3개 동시 요청
2. POST /api/ai/video/async/generate 를 3개 동시 요청
3. 각 응답의 jobId 수집
4. GET /api/ai/image/async/job/{jobId} polling
5. GET /api/ai/video/async/job/{jobId} polling
6. completed 또는 failed 도달 시간 출력
```

## 테스트 변형

이미지만 테스트:

```bash
./tools/load_async_jobs.py --image-jobs 3 --video-jobs 0 --concurrency 3 --poll
```

비디오만 테스트:

```bash
./tools/load_async_jobs.py --image-jobs 0 --video-jobs 3 --concurrency 3 --poll
```

queue 대기 확인:

```bash
./tools/load_async_jobs.py --image-jobs 4 --video-jobs 0 --concurrency 4 --poll
```

`CELERY_WORKER_CONCURRENCY=3`이면 4번째 작업은 worker 여유가 생길 때까지 queue에 머무는지 확인한다.

## 참고: job 수, 요청 concurrency, worker concurrency 차이

테스트 명령의 `--image-jobs`, `--video-jobs`, `--concurrency`와 ai-engine의 `CELERY_WORKER_CONCURRENCY`는 서로 다른 의미다.

| 설정 | 의미 |
|---|---|
| `--image-jobs 3` | 이미지 job을 총 3개 생성 |
| `--video-jobs 3` | 비디오 job을 총 3개 생성 |
| `--concurrency 3` | 테스트 스크립트가 backend에 job 생성 요청을 최대 3개 동시에 보냄 |
| `CELERY_WORKER_CONCURRENCY=3` | ai-engine worker가 provider 생성 task를 최대 3개 동시에 실행 |

예를 들어 아래 명령은 총 6개 job을 만들되, backend로 보내는 생성 요청은 최대 3개씩 병렬로 보낸다.

```bash
./tools/load_async_jobs.py --image-jobs 3 --video-jobs 3 --concurrency 3 --poll
```

흐름:

```text
총 job 수: 6개
- image job 3개
- video job 3개

동시 enqueue 요청 수: 최대 3개
```

반면 실제 provider 호출 동시성은 `CELERY_WORKER_CONCURRENCY`가 결정한다.

예:

```text
요청 10개
CELERY_WORKER_CONCURRENCY=3
```

흐름:

```text
1. backend가 10개 요청을 거의 동시에 받음
2. ai-engine이 Redis queue에 task 10개를 넣음
3. Celery worker가 최대 3개 task만 동시에 실행
4. provider 호출도 최대 3개만 동시에 나감
5. 실행 중인 task 하나가 끝나면 queue에서 다음 task 하나를 꺼내 실행
```

즉 정확히 "3개가 모두 끝난 뒤 다음 3개"가 아니라, **3개 실행 슬롯을 유지하면서 하나 끝날 때마다 다음 하나를 채우는 방식**이다.

예:

```text
처음:
실행 중: 1, 2, 3
대기 중: 4, 5, 6, 7, 8, 9, 10

2번 완료:
실행 중: 1, 3, 4
대기 중: 5, 6, 7, 8, 9, 10

1번 완료:
실행 중: 3, 4, 5
대기 중: 6, 7, 8, 9, 10
```

따라서 10명 동시 요청 상황을 테스트하더라도 `CELERY_WORKER_CONCURRENCY=3`이면 provider에는 최대 3개 정도만 동시에 나간다. 이 설정이 Google/OpenAI 429를 줄이는 핵심이다.

## 확인 포인트

### 1. queued 응답이 빠르게 오는지

예:

```text
IMAGE 1 queued in 120ms jobId=...
IMAGE 2 queued in 98ms jobId=...
VIDEO 1 queued in 130ms jobId=...
```

`queued` 응답이 빠르게 오면 생성 작업이 HTTP 요청 안에서 끝까지 실행되지 않는다는 뜻이다.

### 2. status polling이 진행 상태를 받는지

예:

```text
IMAGE 1 status=processing progress=5 jobId=...
IMAGE 1 status=processing progress=90 jobId=...
IMAGE 1 completed in 8400ms result=[...]
```

비디오 mock 모드에서는 재생 가능한 MP4가 생성되지 않으므로 실패가 정상일 수 있다.

예:

```text
VIDEO 1 failed in 300ms error=Mock video generation does not create playable MP4...
```

### 3. worker 로그에서 병렬 처리 여부 확인

`run_all.sh` 출력의 `[ai-worker]` 로그에서 task 시작 시간이 겹치는지 확인한다.

동시 사용자 3명 이하 MVP에서는 동시에 최대 3개 worker task가 실행되는 것을 기대한다.

## 주요 옵션

```bash
./tools/load_async_jobs.py --help
```

옵션:

```text
--base-url       backend base URL. 기본값: http://127.0.0.1:8080
--image-jobs     생성할 이미지 job 수
--video-jobs     생성할 비디오 job 수
--concurrency    동시에 요청할 enqueue request 수
--poll           terminal status까지 polling
--poll-interval  polling 간격 초
--max-wait       최대 polling 대기 초
--timeout        HTTP 요청 timeout 초
```

## 성공 기준

- 모든 생성 요청이 빠르게 `queued` 응답을 반환한다.
- backend status API에서 `queued`, `processing`, `completed` 또는 `failed` 상태를 조회할 수 있다.
- ai-engine worker가 Redis queue에서 task를 consume한다.
- 이미지 완료 시 callback payload의 `images`, `provider`, `modelUsed`가 backend 상태에 반영된다.
- 비디오 완료 시 callback payload의 `resultUrl`이 backend 상태에 반영된다.
- worker concurrency가 3을 넘지 않는다.

## 주의 사항

- `AI_PROVIDER_MODE=live`는 실제 provider 비용과 rate limit 영향을 받는다.
- video live 생성은 오래 걸릴 수 있으므로 `--max-wait`를 늘려야 할 수 있다.
- backend의 현재 `ImageJobStore`, `VideoJobStore`는 메모리 store다. 서버 재시작 시 상태가 사라진다.
- 운영에서는 WAS DB가 job 상태의 source of truth가 되어야 한다.
