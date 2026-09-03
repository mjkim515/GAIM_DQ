# ai-engine 시스템 분석 리포트 (2026-09-03)

> 범위: **분석 전용, 코드 변경 없음.**
> 대상: `ai-engine` (FastAPI API + Celery worker + Redis broker/result backend).
> 전제: WAS DB가 job 상태의 source of truth, ai-engine은 생성 실행기 + 콜백 전용.
> 운영 형태: 단일 서버 + `run_async_stack.sh` 기준. compose 항목은 "향후 컨테이너화 시"로 표기.
> MVP 목표: 10명 이하 동시 사용자, 이미지/비디오 비동기 생성.

기존 문서(`ai-engine-async-ops-priority-review.md`, `ai-engine-analysis-review_claude.md`)에서
P0/P1 상당수가 "완료"로 표시되어 있어, **현재 코드 기준으로 재검증**하고 아직 살아있는 문제와
새로 발견한 문제를 정리했다.

---

## 0. 한 줄 요약

방향(WAS=source of truth, ai-engine=실행기, Celery+Redis 비동기)은 MVP에 적합하고
P0 설정 보강(worker 분리, time limit, prefetch, media size limit, production validator,
Redis 정책)도 대부분 반영되어 있다.

**다만 "job이 조용히 stuck 되는" 경로가 아직 3개 남아있고, git history 시크릿 노출은 미해결이다.**
10명 이하 동시 사용자 기준에서 실제로 문제가 되는 지점은 다음 4가지다.

1. git history 시크릿 노출 (미해결)
2. 콜백 유실 복구 구멍 — 결과가 1시간 뒤 사라지고, 그 뒤 status API가 "queued"로 오응답
3. worker 크래시 시 재전달분이 job lock에 막혀 재실행도 콜백도 안 됨
4. 비디오 처리량 (concurrency 1)

---

## 1. CRITICAL — 즉시 조치

### 1-1. `.env`가 실제 크레덴셜과 함께 git history에 남아있음 (미해결)

검증 결과:

```
513d790 "Update ai-engine to latest version"  → ai-engine/.env 추가 (실키 포함)
cc8b251 "Stop tracking ai-engine/.env"        → 추적만 중지
```

`513d790` 트리에 실제 값 존재 확인 (마스킹):

```
OPENAI_API_KEY=sk-proj-********
GOOGLE_API_KEY=AIzaSy********
GCP_SERVICE_ACCOUNT_JSON='{"typ********   (private key 전체 포함)
RUNWAYML_API_SECRET=key_a6********          (+ 주석 처리된 key_cd******** 하나 더)
SECRET_KEY / WAS_INTERNAL_TOKEN            (placeholder 값)
```

추적 중지(`cc8b251`)만으로는 해결되지 않는다. history, clone, fork, CI 캐시에 그대로 남는다.
provider key가 살아 있으면 외부 비용 발생 / 권한 오남용으로 이어질 수 있다.

**조치**

- OpenAI / Google API key / GCP 서비스계정 / Runway 시크릿 **4종(사실상 5개) 전부 폐기·재발급**. 최우선.
- `git filter-repo`(또는 BFG)로 history에서 `ai-engine/.env` 제거 → 원격 force push → 팀원 재클론.
- 운영 시크릿은 `.env` 커밋이 아니라 배포 환경변수 / 시크릿 매니저로 주입. repo에는 `.env.example`만.
- `app/config.py:100` production validator는 이미 placeholder 토큰 / eager mode / localhost callback을
  거부한다(양호). 유지.

---

## 2. HIGH — job이 조용히 멈추는 경로

### 2-1. worker 크래시 → 재전달돼도 job lock에 막혀 재실행 안 됨 + 콜백도 없음

`acks_late=True` + `reject_on_worker_lost=True`를 켜서(`app/config.py:67-68`) worker가 OOM/kill 되면
메시지가 다른 worker로 재전달되도록 해놨는데, 재전달된 task가 다음 경로에 막힌다.

- `app/workers/job_locks.py:42-62` — `acquire_job_lock`은 Redis `SET NX EX 900`. 크래시한 worker는
  `finally: release_job_lock`을 못 돌리므로 lock이 **최대 15분간 stale 상태로 생존**한다.
- `app/workers/tasks/image_tasks.py:21-26` / `app/workers/tasks/video_tasks.py:24-29` —
  재전달된 task는 lock 획득 실패 → `on_duplicate()` → `{"status": "duplicate_skipped"}` 반환.
  **콜백 전송 없음. 재생성 없음.**

결과: 원래 job은 미완료인데, 재전달분은 "이미 처리 중"으로 판단하고 스킵 → WAS는 terminal 콜백을
영영 못 받고 `processing`에 고착한다. `acks_late`로 얻으려던 복구가 dedup lock 때문에 무력화된다.

**조치 (택1, MVP는 A 권장)**

- **A.** job lock을 "완료 마커"가 아니라 "실행 중 하트비트"로. lock 값에 `task_id`를 넣고, 재전달된
  task가 자기 `task_id`와 다르면 lock을 탈취해서 재실행. 또는 lock TTL을 `soft_time_limit`보다
  약간 큰 단일 값으로 두고 `reject_on_worker_lost` 재전달 시점이 TTL 이후가 되도록 정렬.
- **B.** 크래시 복구를 job lock 대신 WAS reconciler에만 의존한다면, 재전달 task가
  `duplicate_skipped`를 반환할 때 최소한 현재 상태를 다시 콜백하도록.
- lock 획득 실패 경로 계측 로그(현재 `logger.info`만) → 경고 레벨 + 카운터.

### 2-2. 콜백 유실 복구 구멍 — 결과가 1시간 뒤 사라지고, 그 뒤엔 "queued"라고 오응답

- `app/config.py:20` `was_callback_timeout_sec: float = 1.0` — WAS가 completed 콜백 받고 DB write +
  후처리 하기엔 1초는 너무 짧다. `docker-compose.prod.yml:9`, `.env.example:17`도 1.0.
- `app/services/callbacks.py:9-10,93-102` — 재시도 3회, 고정 `sleep(0.5)`, 백오프 없음.
  4xx/5xx도 동일하게 3회 후 포기 → `return False`. 이 실패는 worker result dict의 `callbacks`
  필드에만 남고 아무도 안 본다.
- 콜백이 다 실패하면 생성물 URL의 유일한 사본은 Celery result backend인데
  `app/config.py:64` `celery_result_expires = 3600` (1시간).
- 1시간 지나면 `app/services/job_status.py:53-54` — `AsyncResult.state == "PENDING"` →
  `/v1/video/status`가 `status: queued, progressPct: 0` 반환. 실제로는 2시간 전에 끝난 job인데.
  WAS reconciler가 이걸 믿으면 계속 대기하거나 잘못된 판단을 한다.
- `JOB_STATUS_TTL_SECONDS = 43200`(12h, jobId→taskId 매핑)과 result TTL 1h가 불일치 →
  매핑은 살아있는데 가리키는 result는 없다.

**조치 (MVP에서 싸게 막는 법)**

- `was_callback_timeout_sec` → 5~10초, 재시도에 지수 백오프 + jitter.
- terminal 상태를 콜백 성공 여부와 무관하게 Redis에 명시적으로 1개 키로 기록
  (`gaim:ai-engine:job-terminal:{type}:{jobId}` = `{status, url/images, provider, model, error, durationMs}`,
  TTL 24h). worker가 완료/실패 시 무조건 write. `/v1/{image,video}/status`가 이걸 1순위로 조회.
  Celery result backend에 의존하지 않게 된다.
- `AsyncResult`가 PENDING이면 "queued"가 아니라 "unknown"을 반환. PENDING은 "모름"이지
  "대기중"이 아니다. 지금 로직은 존재하지 않는 job과 완료 후 만료된 job을 구분하지 못한다.
- (WAS 담당) 오래된 `queued/processing` job reconciler — 이미 가이드에 있음, 구현 확인 필요.

### 2-3. 이미지 전체 실패가 "completed"로 보고되고, WAS는 진짜/가짜를 구분 못 함

- `app/services/image/create_service.py:92-94, 116-137` — 모든 provider 실패 시 mock PNG를
  `provider="local"`로 `ImageCreateResponse` 반환.
- `app/workers/tasks/image_tasks.py:45-51` — 그걸 `notify_image_job_completed`로 보냄.
- `app/services/callbacks.py:45-61` — `notify_image_job_completed` 페이로드에
  `fallbackUsed`도 `warnings`도 없다. 비디오용 `notify_job_completed`(같은 파일 20-42줄)는
  둘 다 보내는데 이미지만 빠졌다.

결과: OpenAI + Google 둘 다 죽어도 사용자는 회색 placeholder를 "완성된 이미지"로 받고,
quota/과금은 차감된다. 모니터링에도 SUCCESS로 보여 장애가 은폐된다.

**조치**

- 전 candidate 실패 시 이미지도 `failed` 콜백으로 분기 (placeholder는 명시적 opt-in 플래그일 때만).
- 최소한 `notify_image_job_completed`에 `fallbackUsed`, `warnings` 추가해서 WAS가 판단할 수 있게.

### 2-4. 비디오 fallback 시간 예산 정책 정리 (보완됨)

기존 구조는 google 후보 폴링 최대 `VIDEO_MAX_WAIT_SEC=600` 후 실패해도 Runway 후보 폴링을 또 최대 600초
시도할 수 있어, `celery_task_soft_time_limit=660`, `hard=720` 예산과 맞지 않았다.

현재 보완 방향은 비디오를 "항상 2-provider 순차 생성"으로 보지 않고, Google/Veo lifecycle 대응용 fallback으로
제한하는 것이다.

```
Google Veo 시도
  ├─ 성공 → completed
  ├─ unsupported / retired / not found / provider unavailable 즉시 오류 → Runway fallback
  ├─ timeout after long polling → failed
  └─ request validation / bad input → failed
```

`ProviderTimeoutError`/`TimeoutError`는 Runway fallback 없이 실패 처리하고, provider unavailable / request rejected
계열은 Runway fallback을 허용한다. 이렇게 하면 긴 Google polling 이후 Runway가 soft limit에 잘리는 경로를 막을 수 있다.

---

## 3. MEDIUM

### 3-1. SSRF — 레퍼런스 이미지 URL 무제한 fetch

`app/services/image/references.py:64` — 스토리지 URL이 아니면 임의 `image_url`을 worker에서
`urlopen`. host allowlist / 사설 IP 차단 / redirect 제한 없음. 크기·타임아웃만 제한된다.
레퍼런스 URL은 프론트 입력이 WAS 거쳐 들어온다 → `169.254.169.254`(클라우드 메타데이터),
내부 서비스 probing 가능. 내부 토큰 인증이 유일한 방어막.

**조치**: scheme/host allowlist(스토리지 도메인만), 사설/링크로컬 IP 차단, redirect 비허용,
Content-Type 검증.

### 3-2. Google genai 클라이언트 매 호출 재생성

`app/services/image/google_service.py:123-157` — 이미지 1건마다, 비디오는 후보마다 새
`genai.Client`. vertex_ai 모드는 `json.loads` + `Credentials.from_service_account_info` +
OAuth 토큰 교환을 매번. `lru_cache` 없음. OpenAI 클라이언트는 이제 `finally: close()` 처리됨(양호).

- 관련: `app/workers/celery_app.py`에 `worker_max_tasks_per_child` / `worker_max_memory_per_child`
  없음 → 장수 prefork 자식의 느린 누수 미방어.

**조치**: Google 클라이언트/자격증명 `lru_cache(key=auth_mode+location)`, `--max-tasks-per-child=50` 추가.

### 3-3. API 프로세스의 in-memory 상태가 오해를 부름

`app/api/v1/image.py:46` `_IMAGE_JOB_IDS`, `app/services/video/veo_service.py:37` `_JOBS`.
API 프로세스는 job을 실행하지 않으므로 `_JOBS`는 항상 "queued"에 머문다.
`enqueue_video_short_generation`이 `_get_job_status`로 중복 체크하는 건 API 재시작 시 사라지는
가짜 멱등성이다. 내부 status API는 이미 `deprecated=True`로 마킹되어 방향은 맞지만,
멱등성은 WAS `jobId UNIQUE` + worker Redis lock 두 개로만 보장된다는 걸 명확히 해야 한다.

**조치**: `_JOBS` 기반 중복 체크 제거 또는 Redis로 이전.

### 3-4. 로컬 스토리지 정리 스케줄 미연결

`app/storage/local_cleanup.py` + `tools/cleanup_local_storage.py`는 존재하지만 cron/timer로
호출되는 곳이 없다. 720p 8초 MP4가 수십 MB씩 무기한 누적 → disk full → write 실패 → job 실패.
`run_async_stack.sh`에도 sweeper가 없다.

**조치**: cron 1줄 또는 systemd timer로 `cleanup_local_storage.py --delete` 일 1회.
디스크 용량 상한/알림도.

### 3-5. 의존성 핀 없음

`requirements.txt` 전부 `>=`. lock 파일 없음. `.venv`가 이미 celery 5.6 / redis 8.1로
드리프트됐다고 기존 문서에 기록됨. `pip-compile`로 `requirements.lock` 생성 또는 `==` 핀.

### 3-6. compose 파일이 지뢰 상태 (향후 컨테이너화 시)

- `docker-compose.prod.yml:22-24` — api와 worker가 `storage-data`를 공유 볼륨 없이 각자 로컬로
  씀 → worker가 만든 파일을 api가 못 서빙 → `resultUrl` 404.
- prod compose에 redis 서비스 없음 (`REDIS_URL` 기본 `redis://redis-host:6379` → 연결 실패 크래시루프).
- `app/config.py:49` `storage_public_base_url` 기본값 `http://localhost:8000/generated` —
  포트 틀림(앱은 8002), prefix 없음(`/gaim`). env 오버라이드 없으면 깨진 URL.
- worker 컨테이너 root 실행, healthcheck 없음, `restart: unless-stopped`가 크래시루프 은폐,
  `mem_limit` 없음.

### 3-7. 단일 uvicorn이 API + `/generated` 정적 서빙 겸함

`app/main.py:71`, `run_server.sh:32` (`--workers` 없음). 수십 MB 비디오 다운로드가 API 요청과
CPU/커넥션 경쟁. 10명 기준 아마 OK지만, 비디오 여러 개 동시 다운로드 시 status polling 지연 가능.
nginx/정적 분리 또는 오브젝트 스토리지로.

---

## 4. 처리량 / 용량 (10명 동시 사용자 관점)

| 항목 | 현재 | 평가 |
|---|---|---|
| 이미지 worker | concurrency 5 (`run_async_stack.sh:51`, `.env.example:137`) | 10명 동시 요청 → 5 실행 / 5 큐. 이미지 생성 ~10-30초. 마지막 사용자 ~1분 대기. **OK** |
| 비디오 worker | concurrency **1** (`.env.example:138`) | 10명 동시 비디오 → 직렬 처리. 건당 2-3분(+ 폴링 최대 600초). 10번째 사용자 20-30분+ 대기 → 프론트 polling 타임아웃 초과 가능. **병목** |
| Redis | `maxmemory 512mb`, `noeviction` | broker+result 겸용. `noeviction`이라 한계 도달 시 신규 enqueue 거부. result payload는 축소됨(`video_tasks`에서 request 제거 확인). 10명 기준 512mb 충분하나 모니터링 필요 |
| 메모리 | 비디오 bytes 전체 RAM 상주, worker mem limit 없음 | 비디오 concurrency 1이라 ~1개 × 수십MB. OK. 단 `max-memory-per-child` 없음 |

**조치**: 비디오 concurrency를 2로 올리고 RAM 모니터링. 또는 프론트에 "대기열 N번째, 예상 X분"
노출 + polling 타임아웃을 넉넉히. 비디오가 주 유스케이스면 concurrency 2~3 + `--max-memory-per-child`.

---

## 5. LOW / 정리

- `app/services/video/veo_service.py:635-639` `_is_operation_done` — `done` 속성 없으면 미완으로
  간주 → SDK 객체 형태 변하면 deadline까지 hang.
- `app/workers/tasks/video_tasks.py:83-85` `_notify_video_task_failed` — `job_id` 없으면 콜백 자체
  스킵(스키마상 `min_length=1`이라 실현 가능성 낮음).
- `app/services/image/google_service.py:189-192` `_store_image_sync_bridge` — 이미지 1장마다
  `asyncio.run()`. 중첩 루프, 낭비. 배치로.
- `enqueue_*`가 `async def`인데 blocking `.apply_async()` 직접 호출 — 이벤트 루프 짧게 블록.
  `await asyncio.to_thread(...)`로.
- `app/main.py:61-67` CORS `allow_credentials=True` + `*` methods/headers — 전 라우트가 내부 토큰
  인증이고 프론트가 직접 안 부르므로 무해하나, 죽은 설정이라 오해 소지. 제거하거나 주석.
- `CELERY_TASK_RETRY_ENABLED=false` 기본값 — transient provider 5xx = 즉시 사용자 노출 실패/placeholder.
  MVP 트레이드오프로 OK지만, 비디오(placeholder 불가)는 retry on 검토.

---

## 6. 권장 적용 순서 (MVP)

| 순위 | 항목 | 참조 |
|---|---|---|
| 1 | 시크릿 4종 폐기·재발급 + history purge | 1-1 |
| 2 | terminal 상태 Redis 명시 기록 + status API가 PENDING을 "queued"로 안 하기 | 2-2 |
| 3 | job lock ↔ acks_late 재전달 정합 (worker 크래시 시 job 유실 방지) | 2-1 |
| 4 | 이미지 전체 실패 → failed 콜백 + `notify_image_job_completed`에 warnings/fallbackUsed | 2-3 |
| 5 | `was_callback_timeout_sec` 5-10초 + 지수 백오프 | 2-2 |
| 6 | 비디오 fallback 시간 예산 정리 또는 단일 provider화 | 2-4 |
| 7 | 스토리지 cleanup cron 연결 | 3-4 |
| 8 | SSRF allowlist, Google 클라이언트 캐시 + `max-tasks-per-child` | 3-1, 3-2 |
| 9 | 비디오 concurrency 2 + 용량 모니터링 | 4 |
| 10 | 의존성 lock, compose 파일 정리 | 3-5, 3-6 |

---

## 7. 검증 방법 (조치 구현 시)

1. **로컬 스택**: `ai-engine/run_async_stack.sh` (redis + api + image worker + video worker).
2. **이미지 job**(mock): `POST /v1/image/jobs` → WAS mock callback endpoint가 progress/completed 수신.
3. **비디오 job**(live): `POST /v1/video/jobs` → progress 5→90→100 콜백, `resultUrl` 접근 가능.
4. **재전달**: 비디오 job 진행 중 video worker `kill -9` → 다른 worker 재수행 + 중복 생성 없음 +
   최종 terminal 콜백 도달 확인.
5. **콜백 장애**: WAS mock 정지 후 job 완료 → 1시간 이상 경과 후 `/v1/video/status`가
   "queued"가 아니라 완료 상태를 반환하는지 확인.
6. **타임아웃**: provider 지연 mock → `task_time_limit`에 걸려 슬롯 회수 + failed 콜백.
7. **이미지 전체 실패**: 두 provider 모두 실패 mock → `failed` 콜백 (placeholder completed 아님).
8. **SSRF**: `reference_images[].image_url`에 `http://169.254.169.254/...` → 400 거절 확인.
9. **디스크**: cleanup cron 동작 후 retention 초과 파일 제거 확인.
10. **자원**: 동시 비디오 job N개 → worker RSS, `redis-cli INFO memory` 추이 확인.

---

## 8. 이미 반영되어 확인된 항목 (재검증 결과 양호)

- image/video worker 분리 실행 (`run_async_stack.sh`, dev/prod compose) — 반영됨
- Celery `task_soft_time_limit` / `task_time_limit` / `worker_prefetch_multiplier=1` — 반영됨 (`app/config.py:60-63`)
- `task_acks_late` / `task_reject_on_worker_lost` / `task_acks_on_failure_or_timeout` — 반영됨 (단 2-1 참조)
- `broker_transport_options.visibility_timeout=900` — 반영됨 (`app/workers/celery_app.py:33-35`)
- media size limit (`MAX_IMAGE_REFERENCE_BYTES`, `MAX_VIDEO_INPUT_IMAGE_BYTES`) + `decode_limited_base64` — 반영됨
- production settings validator (placeholder secret / eager / localhost callback 거부) — 반영됨 (`app/config.py:100-135`)
- `VIDEO_MAX_WAIT_SEC < soft < hard < visibility_timeout` 순서 validator — 반영됨 (`app/config.py:102-107`)
- Redis `appendonly` / `maxmemory` / `noeviction` / named volume / `requirepass` 옵션 — 반영됨 (`run_redis.sh`)
- Celery result payload 축소 (video task result에서 원본 request 제거) + `result_expires=3600` — 반영됨 (단 2-2 참조)
- OpenAI async client `finally: close()` + provider timeout 설정화 — 반영됨 (`app/services/image/openai_service.py:73-75`)
- Google genai client `HttpOptions(timeout=...)` — 반영됨 (`app/services/image/google_service.py:127`)
- 로컬 스토리지 cleanup 로직 + 도구 — 구현됨 (단 스케줄 미연결, 3-4 참조)
- jobId → Celery taskId Redis 매핑 + status API fallback 조회 — 구현됨 (단 result TTL 1h 한계, 2-2 참조)
