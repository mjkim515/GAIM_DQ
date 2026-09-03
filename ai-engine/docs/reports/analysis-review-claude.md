# ai-engine 비동기(Celery/Redis) 이미지·영상 생성 — 정밀 분석 및 개선 계획

## Context

`ai-engine`는 FastAPI(API) + Celery worker + Redis(broker/result backend) 구조로 이미지/영상을
비동기 생성하고, 완료/진행/실패를 Spring 백엔드(`/internal/callback/jobs/...`)로 콜백한다.
프런트는 Spring의 상태 API를 polling한다.

목표: (1) Celery worker ↔ Redis ↔ provider 호출 흐름의 정합성, (2) 메모리·자원 관리 문제를
코드 근거와 함께 정리하고, 위험도순 개선안을 제시한다.

> **범위: 분석 리포트 전용 — 코드 변경 없음.** 아래 "권고" 는 실행 계획이 아니라 우선순위별 제안이다.
> **운영 형태: 단일 서버 + `run_*.sh`(run_async_stack.sh / run_all.sh) 기준.** 컨테이너(compose) 관련
> 항목은 "향후 컨테이너화 시" 로만 표기.
> **job 상태 저장소 방향: Spring RDB** (jobId unique). ai-engine 은 콜백 전용 유지.

---

## 현재 흐름

1. `POST /v1/image/jobs` / `POST /v1/video/jobs` → `enqueue_*` → `task.apply_async(queue=...)` → 즉시 `queued` 응답 (WAS 발급 jobId 사용, Celery task id는 노출 안 됨)
2. worker: `generate_*_task`(sync) → `_run_async()`가 `asyncio.run()`으로 async job 실행 (task마다 새 이벤트 루프)
3. job 내부: provider 호출(google-genai / openai / runway) → 결과 bytes → `store_*` 로 로컬 파일 저장 → URL
4. 단계별 `notify_job_progress/completed/failed` → Spring 콜백 (urllib POST, `X-Internal-Token`)
5. 상태 저장: ai-engine `veo_service._JOBS`(프로세스 메모리 dict) + `image._IMAGE_JOB_IDS`(프로세스 메모리 dict),
   Spring `VideoJobStore/ImageJobStore`(`ConcurrentHashMap`). **Redis에 애플리케이션 job 레코드는 없음.**

---

## 🔴 CRITICAL (즉시 조치)

### C0. `ai-engine/.env` 가 실 크레덴셜과 함께 git에 커밋됨
- 커밋 `513d790` 이후 추적됨. `.gitignore`/`.dockerignore` 에 있으나 강제 add 되어 히스토리에 존재.
- 노출된 것: `OPENAI_API_KEY`(sk-proj-...), `GOOGLE_API_KEY`(AIza...),
  `GCP_SERVICE_ACCOUNT_JSON`(전체 private key, `gen-lang-client-0817130673`),
  `RUNWAYML_API_SECRET` ×2, `WAS_INTERNAL_TOKEN=change-this-internal-token`, `SECRET_KEY` 플레이스홀더.
- 조치: 4개 키 전부 **폐기·재발급**, `git filter-repo`(또는 BFG)로 히스토리에서 제거,
  시크릿 매니저/주입식 env로 전환, `.env` 는 예제만 유지.

### C1. (향후 컨테이너화 시 CRITICAL) Docker worker가 잘못된 큐를 구독 → job이 전혀 실행 안 됨
- `docker/Dockerfile.worker:10` CMD 에 `-Q` 없음 → 기본 `celery` 큐만 소비.
- `celery_app.py:25-29` `task_routes` 는 모든 task를 `image-queue`/`video-queue` 로 라우팅.
- 결과: `docker-compose.yml` / `docker-compose.prod.yml` worker는 **아무 job도 처리하지 않음**.
- **현재 단일 서버 운영에는 영향 없음** — `run_worker.sh:27` 이 `-Q image-queue,video-queue` 를 전달하므로 정상.
  compose 배포로 전환하는 순간 터짐.
- 조치: `Dockerfile.worker` CMD 에 `-Q image-queue,video-queue` 추가(또는 큐 분리).

### C2. Celery task 시간 제한이 전혀 없음 → task 영구 hang, worker 슬롯 영구 상실
- `celery_app.py:17` conf 에 `task_time_limit`/`task_soft_time_limit` 없음, 워커 CLI 에도 `--time-limit` 없음.
- 유일한 상한은 앱 폴링 루프의 `deadline = monotonic() + video_max_wait_sec`(600s)
  (`veo_service.py:481,569`, `runway_service.py:33`). 이 검사는 **`time.sleep()` 사이에서만** 실행됨.
- google-genai 클라이언트는 HTTP 타임아웃 미설정(B3) → `generate_videos()` / `operations.get()` 가
  멈추면 task 영구 hang. `acks_late=False`(C4) 라 재전달도 없음 → prefork 슬롯 영구 소실,
  재시작마다 반복되면 worker 풀 고갈.
- 조치: `task_soft_time_limit = video_max_wait_sec + 60`, `task_time_limit = soft + 60`.
  google-genai `http_options=types.HttpOptions(timeout=...)` 설정.

### C3. 상태 저장소가 프로세스 로컬 메모리 — API↔worker 경계에서 무의미 + 멱등성 없음
- ai-engine `veo_service.py:32` `_JOBS`/`_JOB_UPDATED_AT`, `image.py:44` `_IMAGE_JOB_IDS` — 모듈 전역 dict.
  - `enqueue_*`(API 프로세스)가 `queued` 를 자기 dict에 기록 → worker(별도 프로세스)가 progress/terminal 기록
    → `GET /v1/video/status/{id}`(API)는 영원히 `queued`, 12h TTL 후 `Unknown job_id`.
    **단일 서버라도 API 프로세스와 worker 프로세스는 별개이므로 그대로 발생.**
  - prefork concurrency 3~5 → worker 프로세스도 여러 개, 각자 별도 `_JOBS`.
  - **worker에는 멱등성 체크가 아예 없음** — 무조건 재생성. `apply_async` 가 `task_id=job_id` 도 설정 안 함.
  - dedup 은 단일 API 프로세스 메모리 한정. **API 재시작 시 dedup 이력 전부 소실** → Spring 이 같은 jobId
    재요청하면 **중복 생성 = provider 비용 2배**, 콜백 경쟁(last-writer-wins).
- Spring `VideoJobStore.java:14`/`ImageJobStore.java:14` 도 `ConcurrentHashMap`:
  재시작 시 상태 전부 소실, **맵이 절대 제거 안 됨(메모리 누수)**.
- 권고(Spring RDB 방향):
  - Spring 에 job 테이블(`job_id` UNIQUE, status/progress/result_url/error/provider/updated_at).
    `VideoJobStore`/`ImageJobStore` 를 이 테이블 기반으로 교체.
  - **Spring 이 ai-engine 호출 전에 RDB 를 확인** — 이미 있는 jobId 면 재호출 안 함(단일 enqueue 보장).
  - ai-engine `_JOBS`/`_IMAGE_JOB_IDS`/`GET /status` 는 제거 또는 "개발용" 명시(진실원본은 Spring).
  - (선택) worker 진입부 멱등 가드는 이미 떠 있는 Redis 로 `SET job:{id}:lock NX EX` 한 줄이면 충분.

### C4. `acks_late` 미설정 → worker 사망 시 task 유실(고아 job), 실패 콜백조차 없음
- 기본 early-ack. worker OOM-kill/재배포 시 이미 ACK된 메시지는 재전달 안 됨 → job 영구 멈춤.
  `except Exception` 실패 콜백 경로도 실행 안 됨 → WAS 는 `processing`/`queued` 무한 대기.
- 조치: `task_acks_late=True` + `task_reject_on_worker_lost=True` (**C3 멱등 락 선행 필수**,
  아니면 재전달 시 중복 유료 생성).

### C5. Redis broker `visibility_timeout` 미설정(기본 3600s) → 장시간 task 중복 실행
- `broker_transport_options` 없음. 영상 task 가 스토리지 지연/폴백/재시도로 1h 초과 시
  Redis 가 **첫 실행이 살아있는데도** 다른 worker 에 재전달 → Veo 2회 동시 생성, `completed` 콜백 2회.
- 조치: `broker_transport_options={'visibility_timeout': task_time_limit + 여유}`.

### C6. 완료 콜백 유실이 조용하고 복구 불가 — `was_callback_timeout_sec` 기본 1.0초
- `config.py:20` `was_callback_timeout_sec: float = 1.0`. `callbacks.py:93` 재시도 3회 × 고정 0.5s(백오프 없음).
  `HTTPError`(4xx/5xx)도 동일하게 3회 후 포기.
- 최종 실패 시 `logger.warning` + `return False`. 반환 dict `{"callbacks":{"completed":false}}` 를 아무도 안 봄.
  → **생성물은 디스크에 저장됐지만 WAS 는 `resultUrl` 을 영구히 모름** → job 고착 → 프런트 무한 polling.
  재조정(reconciliation)/DLQ/replay 없음.
- 권고: 타임아웃 10s 로 상향, 지수 백오프.
  ai-engine 이 terminal 결과(`resultUrl`/`error`)를 콜백 성공 여부와 무관하게 **Celery result backend 에는
  이미 남기고 있으므로**, Spring 이 일정 시간(예: 90s) 이상 `processing` 인 job 을 스캔해
  `GET /v1/video/status` 대신 **ai-engine 이 결과를 Spring RDB 에 직접 재기록하는 outbox 재시도**
  또는 Spring 이 ai-engine 결과를 되묻는 재조정 스케줄러 도입.

---

## 🟠 흐름 정합성 (High/Medium)

### F1. `max_retries=2` 는 죽은 설정 — 사실상 재시도 없음
- `image_tasks.py:15`, `video_tasks.py:18,30` `@task(bind=True, max_retries=2)` 이나
  모든 예외를 내부에서 잡아 dict 반환 → Celery 는 항상 SUCCESS. `self.retry()` / `autoretry_for` 없음.
- 일시적 provider 5xx/timeout 이 곧바로 영구 실패(video short candidate fallback 만 일부 완화).
- `app/core/exceptions.py` 의 `retryable` 속성은 아무 데서도 안 쓰임.
- 조치: `autoretry_for` + `retry_backoff` + `retry_jitter` 로 실제 재시도 배선, 또는 오해 소지 파라미터 제거.

### F2. 이미지 실패가 "성공"으로 보고됨
- `create_service.py:80,102-123` — 모든 provider 실패 시 로컬 mock PNG 를 `provider="local"`,
  `fallback_used=True`, `status="completed"` 로 반환 → WAS 에 placeholder URL 로 `completed` 콜백.
  Flower/모니터링에도 SUCCESS 로 보임. 실패가 은폐됨.
- 조치: 전 candidate 실패 시 `failed` 콜백 + task 실패로 분기(placeholder 는 옵션 플래그로만).

### F3. 긴 폴링이 prefork 슬롯을 통째로 점유 + 큐 격리 없음 + prefetch=4
- `run_worker.sh:9` 한 worker 가 `image-queue,video-queue` 모두 소비.
- 영상 job 은 생성 완료까지(최대 10분) 슬롯 1개 점유. concurrency 3~5 에서 영상 버스트가 이미지 job 굶김.
- `worker_prefetch_multiplier` 기본 4 → 분 단위 task 에 부적합(슬롯당 4개 예약, head-of-line 블로킹).
- 조치: `video` worker(저 concurrency, 긴 limit) / `image` worker(고 concurrency, 짧은 limit) 분리.
  `worker_prefetch_multiplier=1`.

### F4. Result backend 비대화(아무도 안 읽음) + 브로커에 대용량 페이로드
- `task_track_started=True`, `result_expires` 미설정(기본 24h).
- `video_tasks.py:24,38` `result["request"] = request_data` — `imageToVideo`/`referenceToVideo` 의
  `bytesBase64Encoded`(입력 이미지 base64 전체, 최대 3장)가 결과에 포함 → Redis DB1 에 24h 저장, 미사용.
- 같은 base64 가 `apply_async(args=[...])` 로 **브로커 메시지**에도 인라인.
- 조치: `task_ignore_result=True`(콜백만 쓰면) 또는 `result_expires=3600`.
  `result["request"]` 에서 media 제거. 입력 이미지는 GCS URI/참조로 전달(base64 인라인 지양).

### F5. `task_always_eager` foot-gun
- `celery_app.py:23` 가 config 에 연결됨. 실환경에서 true 가 되면(`tests/conftest.py:14` 는 강제 true)
  `apply_async` 가 10분 생성을 **FastAPI 요청 핸들러 안에서 동기 실행** → 비동기 설계 붕괴.
- 조치: 비-테스트 환경에서 eager 금지하는 가드 / 문서화.

### F6. `_set_mock_video_status` 의 `asyncio.create_task()` 버그
- `veo_service.py:93` — 동기 함수에서 호출 → 루프 없으면 `RuntimeError`, 있어도 await 안 된 fire-and-forget.
  mock 경로 한정이나 잠재 버그.

### F7. 기타
- `_notify_video_task_failed` 는 `job_id` 없으면 콜백 자체를 안 보냄(`video_tasks.py:65`) — 침묵 블랙홀.
- `enqueue_*` 가 `async def` 인데 blocking `.apply_async()` 직접 호출 → 이벤트 루프 잠깐 블록.
- 진행률 콜백은 best-effort, 재전달 시 순서 보장 없음(늦게 끝난 stale worker 가 최신 완료 뒤에 POST 가능).
- `_is_operation_done` 는 `done` 속성 없으면 "미완"으로 간주 → SDK 객체 형태 이상 시 deadline 에만 의존.

---

## 🟠 메모리 · 자원 관리 (High/Medium)

### M1. (High) 디스크 무한 증가 — 정리 로직 전무
- `storage/local.py:18` `target.write_bytes(data)` 로 `storage-data/images|videos/{uuid}.ext` 영구 저장.
  `app/main.py:71` 이 `/generated` 로 공개 서빙.
- 콜백/업로드 후 삭제·TTL sweeper·크론·용량 상한 **전부 없음**. `tempfile`/`/tmp` 미사용.
- 720p 최대 8s MP4(수십 MB)가 공유 볼륨에 영구 누적. `storage_backend` 은 `local` 만 지원,
  `google-cloud-storage` 미설치(GCS 경로 없음).
- 조치: 보존 TTL + sweeper(또는 콜백 성공 후 삭제), prod 는 GCS 전환(`gcs_bucket_name` 설정은 존재).

### M2. (High) worker OOM 구성 — 자식 재활용/메모리 상한/컨테이너 제한 전부 없음
- prefork, concurrency 5(dev compose), `--max-tasks-per-child` / `--max-memory-per-child` 없음,
  compose `mem_limit`/`cpus`/`deploy.resources` 없음(그리고 `docker compose` 는 `deploy.resources` 무시).
- 영상 바이트 전체가 RAM 상주: `veo_service.py:230,608` `video_bytes`,
  `runway_service.py:125 response.read()` (스트리밍 없음), `storage/local.py:18 write_bytes` — 일시적 2~3벌.
  concurrency × N MB × 누수(M4) → OOM-kill → task 유실(C4).
- 조치: `--max-tasks-per-child=50` + `--max-memory-per-child=<KB>`, 컨테이너 `mem_limit`,
  `peak ≈ concurrency × max_video_MB × 3` 로 concurrency 산정.

### M3. (High) Redis 에 `maxmemory`/eviction/persistence 설정 없음
- `run_redis.sh:31`, `docker-compose.yml:37` — 포트만 노출, `--maxmemory`/`--maxmemory-policy`/볼륨/AOF 없음.
- broker + result backend 겸용. 기본 `noeviction` → 메모리 한계 시 **쓰기 거부(신규 job 거부)**.
- 볼륨 없음 → 컨테이너 재생성 시 **큐에 있던 미시작 job 전부 소실**(RDB 는 ephemeral `/data` 에 씀).
- 조치: broker DB 는 `appendonly yes` + named volume + `maxmemory-policy noeviction`,
  result 를 별도 인스턴스/DB 로 두고 `allkeys-lru` + 짧은 TTL, 또는 result backend 제거(F4).
- Redis 포트가 인증 없이 호스트에 노출(`requirepass`/ACL/`bind` 없음) → `requirepass` 최소 적용.

### M4. (Medium) HTTP/SDK 클라이언트 매 호출 재생성, 절대 close 안 함
- `openai_service.py:59,95`, `text/openai_service.py:69` — `AsyncOpenAI(...)` 요청마다 생성,
  `close()`/`async with` 없음. task 의 일회용 이벤트 루프에서 생성되어 httpx async 정리가 안 돌아감
  → 장수 prefork 자식에서 이미지/텍스트 job 마다 소켓/fd 누수.
- `google_service.py:123 _build_google_client` — 매 호출(영상 폴백은 candidate 마다) 새 `genai.Client`,
  vertex 모드는 `json.loads(service_account_json)` + `Credentials.from_service_account_info` +
  **OAuth 토큰 교환을 매 생성마다** 수행. `lru_cache` 없음.
- 조치: `lru_cache` 로 클라이언트/자격증명 캐시(key=auth_mode+location), 또는 명시적 lifecycle.

### M5. (Medium) `response.read()` / base64 decode 크기 상한 없음 + SSRF
- `references.py:51 urlopen(image_url).read()`, `references.py:23 b64decode`,
  `runway_service.py:125`, `veo_service.py:541 _to_google_image` b64 decode — 무제한 할당.
- `references.py:30 _load_from_url` 는 스토리지 URL 판별 실패 후 **임의 `image_url` 을 worker 에서 urlopen**
  (내부망) — 내부 토큰 인증만이 방어.
- 조치: scheme/host 허용목록, 사설 IP 차단, `Content-Length`/누적 바이트 상한.

### M6. (Medium) split-brain job state / lazy GC — C3 와 동일 근인. `_cleanup_expired_jobs` 는 매 get/set O(n) 스캔이며 저트래픽 시 축소 안 됨.

### M7. (Low) 계층마다 `asyncio.run()` per-call
- tasks `_run_async` → `asyncio.run(...)` (task마다 새 루프),
  `google_service.py:188 _store_image_sync_bridge` 는 **이미지 1장마다** `asyncio.run(store_image(...))`.
  동작하나 낭비 + 취소/타임아웃 전파 불가 + 중첩 `asyncio.run` 취약.

### M8. 이미지 라이브러리 미사용(PIL/cv2/moviepy 없음) — decompression bomb 노출은 없으나 로컬 검증(치수/포맷)도 없음.

---

## 🟡 운영 인프라 (Medium)

### 현재(단일 서버 + run_*.sh)에 해당
- `run_redis.sh:31` Redis 컨테이너가 `--maxmemory`/영속 볼륨/`requirepass` 없이 기동, 포트 6379 호스트 노출 →
  M3 참고. 호스트 다른 프로세스가 브로커·결과 전부 열람 가능.
- **단일 uvicorn 프로세스**(`run_server.sh:32`, `--workers` 없음). 같은 프로세스가 `/generated` 정적 서빙 겸함
  → 영상 다운로드가 API 요청과 CPU/커넥션 경쟁.
- concurrency 값이 코드 3 / `.env` 5 / 스크립트 3 로 불일치 → 실제 적용값 혼동.
- `run_all.sh:12` 가 `AI_ENGINE_INTERNAL_TOKEN=change-this-internal-token` 을 하드코딩.
- `Settings` 에 기본 시크릿/localhost URL 을 비-dev 에서 거부하는 validator 없음.
- 의존성 전부 `>=`, lock 파일 없음 → `.venv` 이미 celery 5.6 / redis 8.1 등으로 드리프트. py3.12 vs 3.13.

### 향후 컨테이너화(compose) 시 추가로 터지는 것
- `docker-compose.prod.yml` 에 redis 서비스 없음 + `.env` broker 가 `localhost` → 연결 실패 크래시루프.
- 공유 `storage-data` 볼륨 없음 → worker 저장 영상을 api 컨테이너가 못 서빙 → `resultUrl` 404.
- `storage_public_base_url="http://localhost:8000/generated"` — 포트도 틀림(api 8002).
- healthcheck 없음, `restart: unless-stopped` 가 크래시루프 은폐. 컨테이너 root 실행.

---

## 권고 (우선순위순, 구현은 별도 승인)

### P0 — 정합성 / 데이터 유실 / 비용 / 보안
1. **C0**: 크레덴셜 4종(OpenAI/Google/GCP SA/Runway) 폐기·재발급, `.env` 히스토리 purge, 주입식 시크릿 전환.
2. **C3**: Spring 에 job 테이블(`job_id` UNIQUE) 도입, `*JobStore` 를 RDB 기반으로 교체.
   Spring 이 ai-engine 호출 전 RDB 확인 → 단일 enqueue. ai-engine 의 `_JOBS`/`_IMAGE_JOB_IDS`/`GET /status`
   는 "개발용" 격하. (선택) worker 멱등 가드는 Redis `SET NX` 한 줄.
3. **C2+C4+C5**: `celery_app.py` 에 `task_soft_time_limit`/`task_time_limit`,
   `task_acks_late=True`(2번 선행), `task_reject_on_worker_lost=True`,
   `worker_prefetch_multiplier=1`, `broker_transport_options={'visibility_timeout': ...}`,
   `broker_connection_retry_on_startup=True`.
4. **B3**: 모든 외부 HTTP 타임아웃 — google-genai `http_options`, OpenAI `timeout=`,
   `was_callback_timeout_sec` 기본 10s + 지수 백오프.
5. **C6**: terminal 결과가 Spring 에 반드시 도달하도록 — ai-engine outbox 재시도 또는
   Spring 재조정 스케줄러(오래된 `processing` job 재확인).
6. **F2**: 이미지 전 candidate 실패 시 `failed` 로 분기(placeholder 는 옵션).

### P1 — 자원 관리
7. **F3**: `video`/`image` worker 를 별도 프로세스로 분리(`run_worker.sh` 를 큐별로, concurrency·time-limit 분리).
8. **M2**: `run_worker.sh` 에 `--max-tasks-per-child=50` + `--max-memory-per-child=<KB>`.
9. **M3**: `run_redis.sh` 에 `--maxmemory`/`--maxmemory-policy`/`--requirepass`,
   result backend 축소(F4: `result_expires=3600` 또는 `task_ignore_result=True`,
   `video_tasks` 결과에서 `request` media 제거).
10. **M4**: `_build_google_client` / `AsyncOpenAI` 를 `lru_cache` 로 재사용.
11. **M1**: 생성물 보존 TTL + sweeper(또는 콜백 성공 후 삭제).

### P1 — 운영(단일 서버)
12. concurrency 값 단일화(코드/`.env`/스크립트), `run_all.sh` 하드코딩 토큰 제거.
13. `Settings` validator: 비-dev 부팅 시 기본 `secret_key`/`was_internal_token`/localhost URL 거부.
14. API `uvicorn --workers N` 또는 gunicorn, `/generated` 서빙 분리(nginx 등).
15. 의존성 상한 핀 + lock 파일, Python 버전 통일.

### P1 — 향후 컨테이너화 시
16. **C1**: `Dockerfile.worker` CMD 에 `-Q image-queue,video-queue`.
17. `docker-compose.prod.yml`: redis 서비스 + 공유 볼륨(또는 GCS) + `storage_public_base_url` 실 URL +
    healthcheck + 비-root `USER`.

### P2 — 하드닝
18. **M5**: `response.read()` 크기 상한, `_load_from_url` SSRF 허용목록/사설 IP 차단.
19. **M7**: 저장 직후 `del video_bytes`, 가능한 경로는 디스크 스트리밍.
20. **F1/F5/F6/F7**: `autoretry_for`+backoff 실제 재시도, eager 가드, `create_task` 버그 수정,
    jobId 없을 때 처리, `_is_operation_done` 견고화.

---

## (권고 구현 시) 검증 방법

1. **로컬 스택**: `ai-engine/run_async_stack.sh` (redis+api+worker).
2. **이미지 job**(mock): `POST /v1/image/jobs` → Spring 상태 API 가 queued→processing→completed 로 전이.
3. **영상 job**(live): `POST /v1/video/jobs` → progress 5→90→100 콜백, `resultUrl` 접근 가능.
4. **재전달**: 영상 job 진행 중 worker `kill -9` → 다른 worker 재수행 + **중복 생성 없음** 확인.
5. **콜백 장애**: Spring 정지 후 job 완료 → Spring 복구 후 재조정으로 최종 상태(`resultUrl`) 채워짐.
6. **타임아웃**: provider 지연 목 → `task_time_limit` 에 걸려 슬롯 회수.
7. **자원**: 동시 영상 job N개 → worker RSS, `redis-cli INFO memory`, `--max-memory-per-child` 재기동 확인.
8. **디스크**: sweeper 동작 후 오래된 파일 제거 확인.

## 결정 사항 (사용자 확인 완료)

- 운영: 단일 서버 + `run_*.sh`. 컨테이너 이슈는 참고용.
- job 상태 영속화: **Spring RDB**.
- 이번 범위: **분석 리포트만** (코드 변경 없음).
