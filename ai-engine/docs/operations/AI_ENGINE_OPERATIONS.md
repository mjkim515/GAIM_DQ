# G-AIM AI Engine Operations Guide

이 문서는 `ai-engine`을 로컬 개발 환경에서 실행하고, 운영 환경에 배포하기 위한 절차를 정리한다. 현재 AI Engine은 FastAPI API 서버, Redis, Celery worker로 구성된다.

## 1. 구성 요소

| 구성 요소 | 역할 | 기본 포트/주소 |
| --- | --- | --- |
| FastAPI API | 텍스트/이미지/비디오 생성 API 제공 | `http://127.0.0.1:8002` |
| Redis | Celery broker/result backend | `redis://localhost:6379` |
| Celery image worker | 이미지 비동기 작업 처리 | `image-queue` |
| Celery video worker | 비디오 비동기 작업 처리 | `video-queue` |
| Local storage | 생성 결과 파일 저장 및 `/generated` 정적 서빙 | `storage-data` |

주요 실행 스크립트:

- `run_server.sh`: FastAPI 서버 단독 실행
- `run_redis.sh`: Redis 컨테이너 실행 또는 기존 Redis 재사용
- `run_worker.sh`: Celery worker 실행
- `run_async_stack.sh`: Redis, API 서버, image worker, video worker를 함께 실행
- `stop_async_stack.sh`: 비동기 스택 종료

## 2. 사전 준비

운영 또는 개발 서버에 다음 도구가 필요하다.

- Python 3.12
- Docker
- Redis 7 또는 Docker로 실행 가능한 Redis 컨테이너
- 외부 AI provider API key
  - OpenAI: `OPENAI_API_KEY`
  - Google/GCP: `GOOGLE_API_KEY` 또는 service account 설정
  - Runway fallback 사용 시: `RUNWAYML_API_SECRET`

`run_redis.sh`는 Docker를 사용해 Redis 컨테이너를 자동으로 띄운다. 이미 `6379` 포트에서 Redis가 실행 중이면 기존 Redis를 재사용한다.

## 3. venv 생성 및 의존성 설치

저장소 루트에서 `ai-engine` 디렉터리로 이동한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

개발/테스트 의존성이 필요하면 추가로 설치한다.

```bash
pip install -r requirements-dev.txt
```

설치 확인:

```bash
.venv/bin/uvicorn --version
.venv/bin/celery --version
```

## 4. 환경변수 설정

`.env.example`을 복사해 `.env`를 만든다.

```bash
cp .env.example .env
```

최소 로컬 실행에는 기본값을 사용할 수 있다. 실제 AI provider를 호출하려면 아래 값을 운영 환경에 맞게 수정한다.

```env
APP_ENV=production
APP_PORT=8002
SECRET_KEY=replace-with-random-secret
ALLOWED_ORIGINS=["https://your-frontend.example.com"]

WAS_BASE_URL=https://your-was.example.com
WAS_INTERNAL_TOKEN=replace-with-shared-internal-token
WAS_CALLBACK_TIMEOUT_SEC=1.0

AI_PROVIDER_MODE=live
OPENAI_API_KEY=replace-with-openai-key
OPENAI_PROVIDER_TIMEOUT_SEC=60
GOOGLE_API_KEY=replace-with-google-key
GOOGLE_PROVIDER_TIMEOUT_MS=60000
RUNWAYML_API_SECRET=replace-with-runway-key
RUNWAY_REQUEST_TIMEOUT_SEC=30
RUNWAY_DOWNLOAD_TIMEOUT_SEC=60

STORAGE_BACKEND=local
STORAGE_BASE_DIR=storage-data
STORAGE_PUBLIC_BASE_URL=https://your-ai-engine.example.com/generated
LOCAL_STORAGE_RETENTION_SECONDS=604800
MAX_IMAGE_REFERENCE_BYTES=10485760
MAX_VIDEO_INPUT_IMAGE_BYTES=10485760
REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC=20

REDIS_URL=redis://redis-host:6379/0
CELERY_BROKER_URL=redis://redis-host:6379/0
CELERY_RESULT_BACKEND=redis://redis-host:6379/1
# Docker Compose 내부 Redis를 사용할 때는 localhost 대신 redis service hostname을 쓴다.
DOCKER_REDIS_URL=redis://redis:6379/0
DOCKER_CELERY_BROKER_URL=redis://redis:6379/0
DOCKER_CELERY_RESULT_BACKEND=redis://redis:6379/1
REDIS_APPENDONLY=yes
REDIS_MAXMEMORY=512mb
REDIS_MAXMEMORY_POLICY=noeviction
# Redis auth 사용 시 URL-safe password를 쓰고 Redis URL을 redis://:password@host:6379/db 형식으로 맞춘다.
REDIS_REQUIREPASS=
CELERY_TASK_ALWAYS_EAGER=false
CELERY_WORKER_CONCURRENCY=3
CELERY_IMAGE_WORKER_CONCURRENCY=5
CELERY_VIDEO_WORKER_CONCURRENCY=1
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_TASK_SOFT_TIME_LIMIT=660
CELERY_TASK_TIME_LIMIT=720
CELERY_RESULT_EXPIRES=3600
CELERY_BROKER_VISIBILITY_TIMEOUT=900
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP=true
CELERY_TASK_ACKS_LATE=true
CELERY_TASK_REJECT_ON_WORKER_LOST=true
CELERY_TASK_ACKS_ON_FAILURE_OR_TIMEOUT=true
CELERY_TASK_RETRY_ENABLED=false
CELERY_TASK_RETRY_COUNTDOWN=15
CELERY_JOB_LOCK_TTL=900
CELERY_JOB_LOCK_ENABLED=true
```

주의 사항:

- `AI_PROVIDER_MODE=mock`이면 외부 AI provider를 호출하지 않는 mock 모드로 동작한다.
- MVP 기본값은 `CELERY_TASK_RETRY_ENABLED=false`다. provider fallback은 같은 task 안에서 수행하지만, Celery
  task-level retry는 하지 않는다. 중복 provider 호출과 callback 순서 혼선을 감수하고 provider 일시 장애 자동 복구를
  우선할 때만 true로 켠다.
- 운영에서는 `SECRET_KEY`, `WAS_INTERNAL_TOKEN`, provider API key를 placeholder로 두면 안 된다.
- `ALLOWED_ORIGINS`는 실제 frontend origin만 허용한다.
- `STORAGE_PUBLIC_BASE_URL`은 WAS 또는 frontend가 접근 가능한 공개 URL이어야 한다.

### Secret 히스토리 대응

`.env` 파일은 현재 git ignore 대상이어야 하며, 운영 서버에서는 가능하면 `.env` 파일 대신 배포 환경변수 또는
secret manager로 주입한다.

다음 명령으로 `.env` 추적/히스토리 상태를 확인한다.

```bash
git ls-files ai-engine/.env
git log --name-status -- ai-engine/.env
git check-ignore -v ai-engine/.env
```

`git log -- ai-engine/.env`에 과거 커밋이 나오면 파일을 삭제했더라도 secret이 history에 남아 있을 수 있다.
과거 `.env`에 실제 provider credential이 들어간 적이 있으면 최소한 아래 항목은 폐기/재발급한다.

- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`
- `GCP_SERVICE_ACCOUNT_JSON`
- `RUNWAYML_API_SECRET`
- `WAS_INTERNAL_TOKEN`
- Redis password를 사용했다면 `REDIS_REQUIREPASS`

이미 원격 저장소에 push된 커밋이면 history purge는 팀 전체 clone/rebase에 영향을 준다. 이 경우 먼저 credential
폐기/재발급을 완료하고, 원격 공유 범위와 배포 이력을 확인한 뒤 history purge 여부를 결정한다.

### Resource TTL 요약

메모리와 디스크 사용량을 제한하는 TTL 설정은 기능별 섹션에 나뉘어 있다.

| 설정 | 기본값 | 대상 |
|---|---:|---|
| `CELERY_RESULT_EXPIRES` | `3600` | Redis result backend 보관 시간 |
| `JOB_STATUS_TTL_SECONDS` | `43200` | `jobId -> Celery taskId` fallback mapping 보관 시간 |
| `CELERY_JOB_LOCK_TTL` | `900` | 중복 실행 방지 Redis lock 보관 시간 |
| `LOCAL_STORAGE_RETENTION_SECONDS` | `604800` | 로컬 생성 파일 보관 시간 |

앞의 세 값은 API/worker 재시작 후 자동 적용된다. `LOCAL_STORAGE_RETENTION_SECONDS`는 cleanup script가 참조하는
값이므로 실제 삭제를 하려면 `tools/cleanup_local_storage.py --delete`를 직접 실행하거나 cron에 등록해야 한다.
- Redis DB `0`은 broker, Redis DB `1`은 result backend로 사용한다.
- MVP Redis 최소 정책은 AOF on, `maxmemory` 설정, `maxmemory-policy noeviction`이다.
- Redis auth를 켜면 `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` 모두 같은 password를 포함해야 한다.
- provider timeout은 `OPENAI_PROVIDER_TIMEOUT_SEC`, `GOOGLE_PROVIDER_TIMEOUT_MS`,
  `RUNWAY_REQUEST_TIMEOUT_SEC`, `RUNWAY_DOWNLOAD_TIMEOUT_SEC`, `REFERENCE_IMAGE_DOWNLOAD_TIMEOUT_SEC`로 제어한다.
- video 작업 limit은 `VIDEO_MAX_WAIT_SEC < CELERY_TASK_SOFT_TIME_LIMIT < CELERY_TASK_TIME_LIMIT < CELERY_BROKER_VISIBILITY_TIMEOUT`
  순서를 지켜야 한다. 이 관계가 깨지면 앱 설정 로딩 단계에서 실패한다.

## 5. 로컬 API 서버 단독 실행

API 서버만 실행하려면 다음을 사용한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./run_server.sh
```

기본값:

- `HOST=127.0.0.1`
- `PORT=8002`
- `APP_MODULE=app.main:app`
- `UVICORN_BIN=.venv/bin/uvicorn`

포트나 host를 바꾸려면 환경변수를 함께 넘긴다.

```bash
HOST=0.0.0.0 PORT=8002 ./run_server.sh
```

`run_server.sh`는 같은 포트에서 이미 실행 중인 프로세스가 있으면 먼저 종료한 뒤 서버를 시작한다.

## 6. 비동기 전체 스택 실행

이미지/비디오 작업은 Celery worker와 Redis가 필요하다. 로컬에서 전체 스택을 실행하려면 다음을 사용한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./run_async_stack.sh
```

이 스크립트는 다음 순서로 실행된다.

1. `run_redis.sh`로 Redis 준비
2. `run_server.sh`로 FastAPI 서버 실행
3. `run_worker.sh`로 image 전용 Celery worker 실행
4. `run_worker.sh`로 video 전용 Celery worker 실행

기본값:

```bash
HOST=127.0.0.1
PORT=8002
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CELERY_IMAGE_QUEUES=image-queue
CELERY_VIDEO_QUEUES=video-queue
CELERY_IMAGE_WORKER_CONCURRENCY=3
CELERY_VIDEO_WORKER_CONCURRENCY=1
CELERY_IMAGE_WORKER_NAME=ai-image-worker@%h
CELERY_VIDEO_WORKER_NAME=ai-video-worker@%h
```

운영과 유사하게 외부 접속을 허용하려면 다음처럼 실행한다.

```bash
HOST=0.0.0.0 PORT=8002 CELERY_IMAGE_WORKER_CONCURRENCY=3 CELERY_VIDEO_WORKER_CONCURRENCY=1 ./run_async_stack.sh
```

종료:

```bash
./stop_async_stack.sh
```

또는 `run_async_stack.sh` 실행 터미널에서 `Ctrl+C`를 입력한다.

실제 Redis/Celery 통합 smoke test:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine

# Redis, worker ping, image/video queue 구독만 확인
./tools/integration_async_stack_smoke.py --skip-jobs

# mock mode에서는 실제 image/video task enqueue, consume, result payload까지 확인
# 실행 전 .env에서 AI_PROVIDER_MODE=mock로 설정하고 async stack을 재시작한다.
./tools/integration_async_stack_smoke.py

# live mode에서 provider 호출까지 포함해 확인. provider 비용이 발생할 수 있음
./tools/integration_async_stack_smoke.py --enqueue-provider-jobs
```

`./tools/integration_async_stack_smoke.py`는 `CELERY_TASK_ALWAYS_EAGER=false`인 실제 Redis/Celery worker 환경에서
실행한다. mock full smoke를 할 때는 `.env`에서 `AI_PROVIDER_MODE=mock`로 변경한 뒤 `run_async_stack.sh`를
재시작한다. `AI_PROVIDER_MODE=mock`이면 기본 실행에서 image/video provider job까지 enqueue한다.
명령 앞에만 `AI_PROVIDER_MODE=mock`을 붙이면 이미 떠 있는 worker에는 반영되지 않는다. 이 상태에서 provider job을
넣으면 worker의 기존 mode로 실행될 수 있으므로 smoke script는 `.env`가 mock이 아니면 mock provider job enqueue를
차단한다.
`AI_PROVIDER_MODE=live`이면 기본 실행에서 provider job은 `skipped`로 표시하고 Redis, worker, active queue,
duplicate lock만 확인한다. 의도적으로 live provider 호출까지 검증할 때만 `--enqueue-provider-jobs`를 사용한다.
기존 `--allow-live-mode`는 `--enqueue-provider-jobs`의 alias로 유지한다.

성공 조건:

- Redis `ping` 성공
- 가능한 환경에서는 Redis `appendonly`, `maxmemory`, `maxmemory-policy` 확인
- Celery worker `ping` 성공
- `active_queues`에 `image-queue`, `video-queue` 둘 다 존재
- mock mode 또는 `--enqueue-provider-jobs` 실행 시 image job이 `completed`로 끝남
- mock mode 또는 `--enqueue-provider-jobs` 실행 시 video short job이 terminal 상태로 끝남
- worker-level Redis lock 중복 작업이 `duplicate_skipped`로 끝남
- video result payload에 원본 `request`가 남지 않음

## 7. Redis와 worker 개별 실행

Redis만 실행:

```bash
./run_redis.sh
```

`run_redis.sh`가 새 Redis 컨테이너를 만들 때 적용하는 MVP 기본 정책:

```bash
REDIS_APPENDONLY=yes
REDIS_MAXMEMORY=512mb
REDIS_MAXMEMORY_POLICY=noeviction
REDIS_DATA_VOLUME=gaim-ai-engine-redis-data
```

기본값은 Docker named volume이다. macOS/Colima 환경에서는 bind mount의 권한 처리 때문에 Redis 컨테이너가
`chown: .: Permission denied`로 바로 종료될 수 있으므로, 로컬 MVP 운영은 named volume을 우선 사용한다.
서버의 특정 디렉터리를 직접 마운트해야 할 때만 `REDIS_DATA_DIR=/path/to/redis-data`를 명시한다.

Redis password를 켤 때는 URL-safe password를 만들고 `.env`에 아래 값을 함께 맞춘 뒤 `run_async_stack.sh`를
재시작한다. base64 password는 `/`, `+`, `=` 문자가 들어갈 수 있어 Redis URL에서 URL-encoding이 필요하다.
MVP에서는 hex password를 권장한다.

```bash
openssl rand -hex 32
```

```env
REDIS_REQUIREPASS=your-hex-password
REDIS_URL=redis://:your-hex-password@127.0.0.1:6379/0
CELERY_BROKER_URL=redis://:your-hex-password@127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://:your-hex-password@127.0.0.1:6379/1
```

`run_async_stack.sh`는 `.env`를 읽고 `run_redis.sh` 실행 후 Redis `PING`이 성공할 때까지 기다린 다음
API와 worker를 시작한다.

이미 만들어진 `gaim-ai-engine-redis` 컨테이너는 `run_redis.sh`가 재사용하므로 Redis 설정 변경이 자동 반영되지
않는다. AOF, maxmemory, password 정책을 바꿨다면 기존 컨테이너를 중지/삭제한 뒤 다시 만든다.

```bash
docker stop gaim-ai-engine-redis
docker rm gaim-ai-engine-redis
./run_redis.sh
```

Celery worker만 실행:

```bash
CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
```

`run_worker.sh`의 worker 기본 큐:

```bash
CELERY_QUEUES=image-queue,video-queue
```

운영에서는 image worker와 video worker를 분리해서 실행한다.

```bash
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
CELERY_QUEUES=video-queue CELERY_WORKER_CONCURRENCY=1 ./run_worker.sh
```

## 8. Docker Compose 실행

개발용 compose:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
docker compose up --build
```

개발용 compose는 다음 서비스를 함께 실행한다.

- `api`
- `image-worker`
- `video-worker`
- `redis`

개발용 compose의 worker는 기본적으로 분리되어 있다.

```text
image-worker: image-queue 전용, 기본 concurrency 5
video-worker: video-queue 전용, 기본 concurrency 1
```

운영용 compose:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

운영용 compose는 `api`, `image-worker`, `video-worker`에 `restart: unless-stopped`를 설정한다. 단, 현재
`docker-compose.prod.yml`에는 Redis 서비스가 포함되어 있지 않으므로 운영 환경에서는 별도 Redis를 준비하고
서버 환경변수의 Redis URL을 해당 주소로 설정해야 한다. 서버에서 `.env` 파일을 두지 않는 경우에도
`docker-compose.prod.yml`은 shell/export된 환경변수를 컨테이너 환경변수로 전달한다.

운영 로그 확인:

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f image-worker
docker compose -f docker-compose.prod.yml logs -f video-worker
```

운영 종료:

```bash
docker compose -f docker-compose.prod.yml down
```

## 9. 실행 확인

헬스체크:

```bash
curl http://127.0.0.1:8002/health
```

정상 응답 예:

```json
{
  "status": "ok",
  "env": "development",
  "storage_backend": "local",
  "ai_provider_mode": "mock"
}
```

API 문서:

- Swagger: `http://127.0.0.1:8002/docs`
- ReDoc: `http://127.0.0.1:8002/redoc`

정적 파일 서빙:

- 생성 결과는 `STORAGE_BASE_DIR`에 저장된다.
- 공개 URL은 `STORAGE_PUBLIC_BASE_URL` 기준으로 만들어진다.
- FastAPI는 `/generated` 경로로 `STORAGE_BASE_DIR`을 서빙한다.

local storage cleanup:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine

# 삭제 후보만 확인
./tools/cleanup_local_storage.py

# 실제 삭제
./tools/cleanup_local_storage.py --delete

# 보관 기간을 직접 지정
./tools/cleanup_local_storage.py --retention-seconds 604800 --delete
```

기본 보관 기간은 `LOCAL_STORAGE_RETENTION_SECONDS=604800`으로 7일이다. cleanup 대상은
`STORAGE_BASE_DIR/images`, `STORAGE_BASE_DIR/videos` 하위 파일이며, 기본 실행은 dry-run이다.
실제 삭제는 `--delete`를 명시했을 때만 수행한다.

운영 등록 순서:

1. `STORAGE_BASE_DIR`이 실제 생성 파일 경로를 가리키는지 확인한다.
2. dry-run으로 삭제 후보를 먼저 확인한다.
3. `--delete`로 1회 수동 실행해 로그와 삭제 결과를 확인한다.
4. cron에 등록한다.

```bash
mkdir -p logs
./tools/cleanup_local_storage.py > logs/storage-cleanup.dry-run.log 2>&1
./tools/cleanup_local_storage.py --delete >> logs/storage-cleanup.log 2>&1
```

crontab 예시:

```cron
# 매일 03:00에 LOCAL_STORAGE_RETENTION_SECONDS보다 오래된 생성 파일 삭제
0 3 * * * cd /path/to/ai-engine && ./tools/cleanup_local_storage.py --delete >> logs/storage-cleanup.log 2>&1
```

운영 주의사항:

- cron의 `/path/to/ai-engine`은 실제 배포 경로로 바꾼다.
- cron 프로세스가 `STORAGE_BASE_DIR` 파일을 삭제할 권한이 있어야 한다.
- 삭제 주기는 보관 기간보다 짧게 둔다. 예를 들어 7일 보관이면 하루 1회 실행이면 충분하다.
- GCS/S3/R2 같은 object storage로 전환하면 이 스크립트는 local storage에만 적용된다. object storage lifecycle
  rule을 별도로 설정해야 한다.

media input size limit:

- `MAX_IMAGE_REFERENCE_BYTES`: 이미지 생성/편집 reference 이미지의 최대 byte 수
- `MAX_VIDEO_INPUT_IMAGE_BYTES`: 숏폼 비디오 생성에 쓰는 시작 프레임, 마지막 프레임, reference 이미지의 최대 byte 수

MVP에서는 서버가 할당받은 local storage를 사용하므로 base64 입력, local reference URL, HTTP reference URL을
provider 호출 전에 byte 기준으로 제한한다. 나중에 GCS 등 object storage로 전환하면 `gcsUri` 입력은 실제 bytes를
직접 읽지 않으므로, 업로드 단계의 object size 제한이나 metadata 검증을 별도로 적용해야 한다.

## 10. WAS 연동 체크리스트

Spring Boot backend와 연동할 때 다음 값을 맞춘다.

AI Engine `.env`:

```env
WAS_BASE_URL=http://localhost:8080
WAS_INTERNAL_TOKEN=change-this-internal-token
```

Backend 설정:

- AI Engine base URL이 `http://localhost:8002` 또는 운영 AI Engine URL을 가리키는지 확인한다.
- AI Engine과 backend가 같은 `WAS_INTERNAL_TOKEN`을 사용하는지 확인한다.
- 이미지/비디오 비동기 작업 callback URL이 backend에서 수신 가능한지 확인한다.

로컬 통합 실행 순서:

1. Redis 실행
2. AI Engine API 실행
3. AI Engine worker 실행
4. Backend 실행
5. Frontend 실행

간단히는 다음 명령으로 1-3번을 함께 실행한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./run_async_stack.sh
```

## 11. 운영 배포 체크리스트

배포 전 확인:

- `.env`가 운영 값으로 설정되어 있다.
- `APP_ENV=production`이다.
- `AI_PROVIDER_MODE=live`가 필요한 환경에서 설정되어 있다.
- provider API key가 placeholder가 아니다.
- `SECRET_KEY`가 충분히 랜덤한 값이다.
- `WAS_INTERNAL_TOKEN`이 backend와 동일하다.
- `ALLOWED_ORIGINS`에 실제 frontend origin만 포함되어 있다.
- Redis가 운영 환경에서 접근 가능하다.
- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`가 Redis 주소를 가리킨다.
- `STORAGE_BASE_DIR`가 컨테이너/서버 재시작 후에도 유지되는 경로다.
- `STORAGE_PUBLIC_BASE_URL`이 외부에서 접근 가능한 URL이다.
- API 서버 `/health`가 정상 응답한다.
- worker 로그에 queue consume 오류가 없다.
- 방화벽 또는 reverse proxy에서 `8002` 또는 운영 API 포트가 열려 있다.

권장 운영 프로세스:

1. `.env` 업데이트
2. Redis 연결 확인
3. Docker image build
4. API와 worker 배포
5. `/health` 확인
6. `/docs` 또는 smoke API로 API schema 확인
7. 이미지/비디오 비동기 작업 1건 생성
8. worker 처리 로그 및 WAS callback 수신 확인

## 12. 장애 대응

### uvicorn executable not found

증상:

```text
uvicorn executable not found: .../.venv/bin/uvicorn
Create the virtualenv and install requirements first.
```

조치:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### celery executable not found

증상:

```text
celery executable not found: .../.venv/bin/celery
```

조치:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Redis 연결 실패

확인:

```bash
lsof -iTCP:6379 -sTCP:LISTEN
docker ps
```

조치:

```bash
./run_redis.sh
```

운영 환경에서는 `.env`의 Redis 주소가 실제 Redis host를 가리키는지 확인한다.

Redis 직접 중지:

`run_redis.sh`로 띄운 기본 Docker Redis는 컨테이너 이름이 `gaim-ai-engine-redis`다.

```bash
docker stop gaim-ai-engine-redis
```

다시 시작:

```bash
docker start gaim-ai-engine-redis
```

컨테이너까지 삭제:

```bash
docker rm gaim-ai-engine-redis
```

실행 중인 Redis 컨테이너 확인:

```bash
docker ps | grep redis
```

로컬에 직접 설치된 Redis가 `6379` 포트에서 실행 중이면 먼저 PID를 확인한다.

```bash
lsof -iTCP:6379 -sTCP:LISTEN
```

`redis-cli`가 있으면 정상 종료를 시도한다.

```bash
redis-cli shutdown
```

macOS Homebrew 서비스로 실행 중이면 다음 명령을 사용한다.

```bash
brew services stop redis
brew services stop redis@7
```

위 방법으로 종료되지 않으면 `lsof`로 확인한 PID를 종료한다.

```bash
kill <PID>
```

강제 종료는 마지막 수단으로만 사용한다.

```bash
kill -9 <PID>
```

### API 포트 충돌

`run_server.sh`와 `stop_async_stack.sh`는 `PORT`에 해당하는 listener를 종료한다. 수동 확인:

```bash
lsof -iTCP:8002 -sTCP:LISTEN
```

다른 포트를 사용하려면:

```bash
PORT=8001 ./run_server.sh
```

### worker가 작업을 처리하지 않음

확인 항목:

- API와 worker가 같은 `CELERY_BROKER_URL`을 사용하는가
- image worker가 `image-queue`를 구독하고 video worker가 `video-queue`를 구독하는가
- Redis가 접근 가능한가
- worker 로그에 provider API key 오류가 없는가

worker 재시작:

```bash
./stop_async_stack.sh
./run_async_stack.sh
```

### provider API key 오류

확인 항목:

- `AI_PROVIDER_MODE=live`인지 확인
- `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `RUNWAYML_API_SECRET`이 실제 값인지 확인
- Google Vertex AI 또는 service account 모드 사용 시 `GOOGLE_AUTH_MODE`, `GCP_PROJECT_ID`, `GCP_SERVICE_ACCOUNT_JSON` 설정 확인

### 생성 파일 URL 접근 불가

확인 항목:

- `STORAGE_BASE_DIR`에 파일이 생성되었는가
- API 서버가 `/generated`를 서빙하는가
- `STORAGE_PUBLIC_BASE_URL`이 실제 외부 URL과 일치하는가
- reverse proxy가 `/generated` 경로를 AI Engine으로 라우팅하는가

## 13. 빠른 실행 요약

로컬 mock 모드:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run_async_stack.sh
curl http://127.0.0.1:8002/health
```

운영 Docker:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
cp .env.example .env
# Edit .env with production values.
docker compose -f docker-compose.prod.yml up --build -d
curl http://127.0.0.1:8002/health
```
