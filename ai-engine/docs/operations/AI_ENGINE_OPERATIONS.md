# G-AIM AI Engine Operations Guide

이 문서는 `ai-engine`을 로컬 개발 환경에서 실행하고, 운영 환경에 배포하기 위한 절차를 정리한다. 현재 AI Engine은 FastAPI API 서버, Redis, Celery worker로 구성된다.

## 1. 구성 요소

| 구성 요소 | 역할 | 기본 포트/주소 |
| --- | --- | --- |
| FastAPI API | 텍스트/이미지/비디오 생성 API 제공 | `http://127.0.0.1:8000` |
| Redis | Celery broker/result backend | `redis://localhost:6379` |
| Celery worker | 이미지/비디오 비동기 작업 처리 | `image-queue`, `video-queue` |
| Local storage | 생성 결과 파일 저장 및 `/generated` 정적 서빙 | `storage-data` |

주요 실행 스크립트:

- `run_server.sh`: FastAPI 서버 단독 실행
- `run_redis.sh`: Redis 컨테이너 실행 또는 기존 Redis 재사용
- `run_worker.sh`: Celery worker 실행
- `run_async_stack.sh`: Redis, API 서버, worker를 함께 실행
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
APP_PORT=8000
SECRET_KEY=replace-with-random-secret
ALLOWED_ORIGINS=["https://your-frontend.example.com"]

WAS_BASE_URL=https://your-was.example.com
WAS_INTERNAL_TOKEN=replace-with-shared-internal-token
WAS_CALLBACK_TIMEOUT_SEC=1.0

AI_PROVIDER_MODE=live
OPENAI_API_KEY=replace-with-openai-key
GOOGLE_API_KEY=replace-with-google-key
RUNWAYML_API_SECRET=replace-with-runway-key

STORAGE_BACKEND=local
STORAGE_BASE_DIR=storage-data
STORAGE_PUBLIC_BASE_URL=https://your-ai-engine.example.com/generated

REDIS_URL=redis://redis-host:6379/0
CELERY_BROKER_URL=redis://redis-host:6379/0
CELERY_RESULT_BACKEND=redis://redis-host:6379/1
CELERY_TASK_ALWAYS_EAGER=false
CELERY_WORKER_CONCURRENCY=3
```

주의 사항:

- `AI_PROVIDER_MODE=mock`이면 외부 AI provider를 호출하지 않는 mock 모드로 동작한다.
- 운영에서는 `SECRET_KEY`, `WAS_INTERNAL_TOKEN`, provider API key를 placeholder로 두면 안 된다.
- `ALLOWED_ORIGINS`는 실제 frontend origin만 허용한다.
- `STORAGE_PUBLIC_BASE_URL`은 WAS 또는 frontend가 접근 가능한 공개 URL이어야 한다.
- Redis DB `0`은 broker, Redis DB `1`은 result backend로 사용한다.

## 5. 로컬 API 서버 단독 실행

API 서버만 실행하려면 다음을 사용한다.

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
./run_server.sh
```

기본값:

- `HOST=127.0.0.1`
- `PORT=8000`
- `APP_MODULE=app.main:app`
- `UVICORN_BIN=.venv/bin/uvicorn`

포트나 host를 바꾸려면 환경변수를 함께 넘긴다.

```bash
HOST=0.0.0.0 PORT=8000 ./run_server.sh
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
3. `run_worker.sh`로 Celery worker 실행

기본값:

```bash
HOST=127.0.0.1
PORT=8000
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
CELERY_WORKER_CONCURRENCY=3
```

운영과 유사하게 외부 접속을 허용하려면 다음처럼 실행한다.

```bash
HOST=0.0.0.0 PORT=8000 CELERY_WORKER_CONCURRENCY=3 ./run_async_stack.sh
```

종료:

```bash
./stop_async_stack.sh
```

또는 `run_async_stack.sh` 실행 터미널에서 `Ctrl+C`를 입력한다.

## 7. Redis와 worker 개별 실행

Redis만 실행:

```bash
./run_redis.sh
```

Celery worker만 실행:

```bash
CELERY_WORKER_CONCURRENCY=3 ./run_worker.sh
```

worker 기본 큐:

```bash
CELERY_QUEUES=image-queue,video-queue
```

특정 큐만 처리하려면 다음처럼 실행한다.

```bash
CELERY_QUEUES=image-queue CELERY_WORKER_CONCURRENCY=2 ./run_worker.sh
```

## 8. Docker Compose 실행

개발용 compose:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
docker compose up --build
```

개발용 compose는 다음 서비스를 함께 실행한다.

- `api`
- `worker`
- `redis`

운영용 compose:

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

운영용 compose는 `api`와 `worker`에 `restart: unless-stopped`를 설정한다. 단, 현재 `docker-compose.prod.yml`에는 Redis 서비스가 포함되어 있지 않으므로 운영 환경에서는 별도 Redis를 준비하고 `.env`의 Redis URL을 해당 주소로 설정해야 한다.

운영 로그 확인:

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker
```

운영 종료:

```bash
docker compose -f docker-compose.prod.yml down
```

## 9. 실행 확인

헬스체크:

```bash
curl http://127.0.0.1:8000/health
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

- Swagger: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

정적 파일 서빙:

- 생성 결과는 `STORAGE_BASE_DIR`에 저장된다.
- 공개 URL은 `STORAGE_PUBLIC_BASE_URL` 기준으로 만들어진다.
- FastAPI는 `/generated` 경로로 `STORAGE_BASE_DIR`을 서빙한다.

## 10. WAS 연동 체크리스트

Spring Boot backend와 연동할 때 다음 값을 맞춘다.

AI Engine `.env`:

```env
WAS_BASE_URL=http://localhost:8080
WAS_INTERNAL_TOKEN=change-this-internal-token
```

Backend 설정:

- AI Engine base URL이 `http://localhost:8000` 또는 운영 AI Engine URL을 가리키는지 확인한다.
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
- 방화벽 또는 reverse proxy에서 `8000` 또는 운영 API 포트가 열려 있다.

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

### API 포트 충돌

`run_server.sh`와 `stop_async_stack.sh`는 `PORT`에 해당하는 listener를 종료한다. 수동 확인:

```bash
lsof -iTCP:8000 -sTCP:LISTEN
```

다른 포트를 사용하려면:

```bash
PORT=8001 ./run_server.sh
```

### worker가 작업을 처리하지 않음

확인 항목:

- API와 worker가 같은 `CELERY_BROKER_URL`을 사용하는가
- worker가 `image-queue,video-queue`를 구독하는가
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
curl http://127.0.0.1:8000/health
```

운영 Docker:

```bash
cd /Users/mjkim/project/G-AIM/GAIM_Org/ai-engine
cp .env.example .env
# Edit .env with production values.
docker compose -f docker-compose.prod.yml up --build -d
curl http://127.0.0.1:8000/health
```
