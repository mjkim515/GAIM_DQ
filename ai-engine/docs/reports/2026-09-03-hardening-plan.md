# ai-engine 보강 구현 계획 (2026-09-03)

> 범위: **구현 계획 문서. 코드 변경 없음.**
> 근거 리포트: [`ai-engine-system-analysis-2026-09-03.md`](./ai-engine-system-analysis-2026-09-03.md)
> 대상 항목: 리포트의 2-1, 2-2, 2-3, 3-1 + 콜백 백오프.
> 전제: 단일 서버 + `run_async_stack.sh`, WAS DB = source of truth, ai-engine = 실행기 + 콜백 전용.
> 진행 상태: **2026-09-03 현재 1 → 4 → 2 → 3 → 5 순서로 주요 보강 적용 완료.**
> 우선순위 리뷰 반영: [`ai-engine-async-ops-priority-review.md`](./ai-engine-async-ops-priority-review.md)에
> **2026-09-03** 기준으로 동기화 완료.

---

## 진행 상태 업데이트 (2026-09-03)

현재 코드에 반영된 작업 기준으로 전체 테스트는 다음 상태다.

```bash
137 passed in 14.21s
```

완료율은 두 기준으로 본다.

| 기준 | 완료율 | 설명 |
|---|---:|---|
| 합의/적용 범위 기준 | 약 88% | 실제 승인된 구현 방향 기준. 작업 4는 옵션 B(`fallbackUsed`/`warnings`)로 완료 처리 |
| 원문 strict 기준 | 약 78% | 원문 권장안 A, 작업 5의 allowlist/redirect 차단, 문서 갱신 항목까지 포함한 기준 |

### 작업별 상태

| # | 작업 | 현재 상태 | 완료율 | 비고 |
|---|---|---|---:|---|
| 1 | terminal job 상태 Redis 별도 저장 | 완료 | 95% | `job_terminal_status_ttl_seconds=86400`, terminal Redis key, `PENDING -> processing` 반영. 테스트는 fakeredis 대신 fake Redis class 사용 |
| 2 | callback timeout 상향 + exponential backoff | 완료 | 100% | timeout 5s, terminal callback 4 attempts, progress callback 1 attempt, backoff+jitter 반영 |
| 3 | duplicate lock crash/재전달 정합 | 완료 | 90% | Celery `task_id` 기반 동일 task 재전달 허용. 원문 `LockHeld` dataclass는 쓰지 않고 더 작은 분기로 구현 |
| 4 | 이미지 전체 provider 실패 처리 | 옵션 B 완료 | 70% strict / 100% B 기준 | `fallbackUsed`, `warnings`를 image completed callback/result/terminal status에 전달. 옵션 A(`failed` callback 전환)는 미적용 |
| 5 | reference image URL SSRF 방어 | 부분 완료 | 65% | scheme/hostname/private IP/DNS resolve 차단 완료. allowlist 설정, redirect 차단, production 경고는 미적용 |
| 6 | 관련 단위 테스트 + pytest | 완료 | 90% | `tests/test_callbacks.py`, `tests/test_job_status.py`, `tests/test_job_locks.py`, `tests/test_image_references.py` 추가. 전체 green |
| 7 | 비디오 fallback 시간 예산 정책 | 완료 | 90% | long polling timeout은 Runway fallback 없이 실패. Veo unavailable/unsupported/not found 계열 즉시 오류만 Runway fallback |

### 실제 반영 파일

| 영역 | 파일 |
|---|---|
| 설정 | `app/config.py`, `.env.example`, `docker-compose.prod.yml` |
| callback | `app/services/callbacks.py` |
| terminal status | `app/services/job_status.py`, `app/services/video/veo_service.py`, `app/workers/tasks/image_tasks.py` |
| job lock | `app/workers/job_locks.py`, `app/workers/tasks/image_tasks.py`, `app/workers/tasks/video_tasks.py` |
| SSRF | `app/services/image/references.py` |
| 테스트 | `tests/conftest.py`, `tests/test_api.py`, `tests/test_callbacks.py`, `tests/test_job_status.py`, `tests/test_job_locks.py`, `tests/test_image_references.py` |

### 남은 작업

| 우선순위 | 항목 | 이유 |
|---|---|---|
| P1 | reference image redirect 차단 | 현재는 요청 전 URL/DNS 검증만 수행. redirect로 내부망 URL로 이동하는 우회 가능성 잔존 |
| P1 | `reference_image_allowed_hosts` 설정 추가 여부 결정 | 운영에서 특정 CDN/storage 도메인만 허용하면 SSRF 방어가 더 강해짐 |
| P1 | 이미지 provider 전체 실패 시 옵션 A로 전환할지 재결정 | 현재는 placeholder 유지 + metadata 전달. 사용자 과금/장애 은폐 정책 관점에서 `failed`가 더 정직할 수 있음 |
| P2 | API/operations 문서 갱신 | `job-terminal:*`, 24h 복구 윈도우, `PENDING -> processing` 의미를 운영 문서에 반영 필요 |
| P2 | Redis 기반 통합 테스트 또는 fakeredis 도입 | 현재 테스트는 fake class/monkeypatch 중심이라 실제 Redis 동작과의 간극이 일부 남음 |

### Open Decisions 현재 상태

| # | 결정 | 현재 결론 |
|---|---|
| 1 | 이미지 전 provider 실패 시 `failed` vs placeholder+warnings | 옵션 B 채택 완료. 옵션 A는 후속 재검토 |
| 2 | `was_callback_timeout_sec` = 5 vs 10 | 5s 채택 완료 |
| 3 | terminal 저장소 TTL: 기존 12h vs 신규 24h | 신규 24h 채택 완료 |
| 4 | SSRF allowlist 강제 vs 사설 IP 차단 | 사설 IP 차단/DNS resolve 차단 완료. allowlist는 미적용 |
| 5 | `/v1/*/status` PENDING 처리 | `processing` 채택 완료 |
| 6 | 비디오 timeout 후 Runway fallback 여부 | timeout after long polling은 fallback하지 않음. Veo unavailable/unsupported/not found 계열 즉시 오류만 fallback |

---

## 0. 이번 작업 범위

| # | 작업 | 리포트 항목 | 위험도 |
|---|---|---|---|
| 1 | terminal job 상태를 Redis에 별도 저장, status API가 Celery result TTL에 비의존 | 2-2 | 낮음 |
| 2 | callback timeout 상향 + exponential backoff | 2-2 | 낮음 |
| 3 | duplicate lock이 crash/재전달 시 조용히 `duplicate_skipped`로 끝나지 않게 정합 | 2-1 | **중간 (설계 주의)** |
| 4 | 이미지 전체 provider 실패 시 `failed` 콜백 또는 `fallbackUsed`/`warnings` 전달 | 2-3 | 낮음 |
| 5 | reference image URL allowlist / 사설 IP 차단 | 3-1 | 낮음 |
| 6 | 관련 단위 테스트 추가 + `pytest` 재실행 | — | — |

### Non-goals (이번에 안 함)

- 비디오 2-provider fallback 시간 예산 재정리 (리포트 2-4) — long polling timeout fallback 차단으로 보완 적용
- 오브젝트 스토리지 전환, cleanup cron 연결 (3-4), 의존성 lock (3-5)
- WAS 측 reconciler 구현 (WAS 담당)
- `_IMAGE_JOB_IDS` / `_JOBS` in-memory 제거 (3-3) — 3번 작업에서 자연스럽게 의존도만 낮아짐

### WAS / frontend 계약 영향

- 없음(파괴적). 이미지 completed 콜백에 **선택 필드 추가**(additive)뿐.
- 내부 `/v1/*/status` 응답은 4-value enum(`queued|processing|completed|failed`) 유지.
- 내부 status API의 PENDING 처리 의미만 조정(아래 1-3) — 해당 API는 이미 `deprecated`.

---

## 1. 작업 1 — terminal 상태 Redis 별도 저장

### 1-1. 문제 재확인

- 콜백 3회 실패 시 생성물 URL의 유일한 사본 = Celery result backend, `celery_result_expires = 3600`(1h).
- 1h 경과 후 `app/services/job_status.py:53-54`: `AsyncResult.state == PENDING` → `/v1/*/status`가
  `queued` 반환 → "2시간 전 끝난 job"과 "방금 접수된 job"을 구분 불가.
- `JOB_STATUS_TTL_SECONDS = 43200`(12h, jobId→taskId 매핑)과 result TTL(1h) 불일치.

### 1-2. 변경

**신규 설정** — `app/config.py`

| 키 | 기본값 | 설명 |
|---|---|---|
| `job_terminal_status_ttl_seconds` | `86400` (24h) | terminal 상태 Redis 보존 TTL. reconciler 윈도우보다 충분히 길게 |

**`app/services/job_status.py`**

- 신규 키 헬퍼: `_terminal_key(job_type, job_id) -> "gaim:ai-engine:job-terminal:{job_type}:{job_id}"`
- 신규 함수:
  - `record_terminal_status(job_type: str, job_id: str, payload: dict) -> None`
    - `payload`를 JSON 직렬화해 Redis `SET key json EX job_terminal_status_ttl_seconds`.
    - **best-effort**: `try/except` + `logger.warning`. Redis 장애가 job 실패로 번지지 않게.
    - `job_id` 없으면 no-op.
  - `get_terminal_status(job_type: str, job_id: str) -> dict | None`
    - Redis GET → JSON 역직렬화. 실패 시 `None`.
- `celery_result_payload_for_job(job_type, job_id)` 조회 우선순위 변경:
  1. `get_terminal_status(...)` 존재 → `{"jobId": job_id, **payload}` 반환 (Celery 조회 안 함).
  2. 없으면 기존 `AsyncResult` 로직. 단 `state == PENDING` 분기 수정 (1-3).

**terminal 상태 write 지점** (worker 프로세스에서만 호출):

| 파일 | 함수 | 지점 |
|---|---|---|
| `app/workers/tasks/image_tasks.py` | `_run_image_job` | 성공 dict 반환 직전 |
| `app/workers/tasks/image_tasks.py` | `_notify_image_task_failed` | 실패 dict 반환 직전 |
| `app/services/video/veo_service.py` | `_run_live_video_short_generation` | 성공/실패 분기 각각 |
| `app/services/video/veo_service.py` | `_run_live_video_generation` | 성공/실패 분기 각각 |
| `app/services/video/veo_service.py` | `_set_mock_video_status_async` | 반환 직전 |

- payload 형태 = 각 함수가 이미 반환하는 dict와 동일 (`jobId`, `status`, `images`/`videoUrl`,
  `provider`, `modelUsed`, `durationMs`, `error` 등). 별도 스키마 신설 안 함, 그대로 저장.

### 1-3. `/v1/*/status` PENDING 처리

- 현재: `state == PENDING` → `status: queued, progressPct: 0`.
- 변경:
  - `get_remembered_task_id(...)` 매핑 존재 + PENDING → **`processing`** 반환 (terminal 아님, reconciler가 계속 재확인).
  - 매핑 없음 + terminal 없음 → 기존대로 `failed` + `error: "Unknown job_id"` (image) / video도 동일.
- 이유: "완료 후 result 만료" job이 최대 24h 동안은 terminal 저장소에서 정확히 응답됨.
  그 외 PENDING은 "완료로 오해될 수 있는 queued"가 아니라 "아직 진행 중"으로 표현.

### 1-4. 테스트 — `tests/test_job_status.py` (신규)

- `record_terminal_status` 후 `get_terminal_status`가 payload 반환 (fakeredis).
- `celery_result_payload_for_job`가 terminal 저장소를 Celery보다 우선 조회.
- terminal 없음 + taskId 매핑 있음 + `AsyncResult` PENDING → `processing`.
- terminal 없음 + 매핑 없음 → `failed`/`Unknown job_id`.
- Redis 장애(patch로 예외) 시 `record_terminal_status`가 raise 안 함.

---

## 2. 작업 2 — callback timeout / backoff

### 2-1. 변경

**`app/config.py`**

| 키 | 현재 | 변경 |
|---|---|---|
| `was_callback_timeout_sec` | `1.0` | `5.0` |

- 동기화: `.env.example:17`, `docker-compose.prod.yml:9` (`WAS_CALLBACK_TIMEOUT_SEC`).

**`app/services/callbacks.py`**

- 상수:
  - `CALLBACK_MAX_ATTEMPTS = 3` → `4`
  - `CALLBACK_RETRY_DELAY_SEC` 제거, 대신 `CALLBACK_RETRY_BASE_SEC = 0.5`, `CALLBACK_RETRY_MAX_SEC = 8.0`
- `_post_callback`:
  - 재시도 대기 = `min(CALLBACK_RETRY_BASE_SEC * 2 ** (attempt - 1), CALLBACK_RETRY_MAX_SEC) + random.uniform(0, 0.5)`
  - `import random` 추가.
- `_post_callback(path, payload, *, max_attempts: int | None = None)` 파라미터 추가:
  - `notify_job_progress` → `max_attempts=1` (progress는 best-effort, 지연 누적 방지)
  - `notify_job_completed` / `notify_image_job_completed` / `notify_job_failed` → 기본 `CALLBACK_MAX_ATTEMPTS`
- (선택) `error.HTTPError` 중 4xx(408/429 제외)는 재시도 안 하고 즉시 `False` — WAS가 못 고치는 요청 오류.
  이번엔 스킵 가능, 주석으로만 표기.

### 2-2. 예산 확인

- 최악(terminal 콜백 4회 전부 실패): `~(0.5+1+2) + 4*5s ≈ 23.5s`.
- task 당 terminal 콜백 1회 + progress 2회(각 1 attempt). 총 추가 지연 여유 = `soft_time_limit(660) - video_max_wait(600) = 60s` 안에 들어옴. OK.
- progress를 1 attempt로 낮추는 게 이 예산 확보의 핵심.

### 2-3. 테스트 — `tests/test_callbacks.py` (신규 또는 확장)

- `urllib.request.urlopen` monkeypatch로 N회 실패 후 성공 → 재시도 횟수/성공 확인.
- 전부 실패 → `False` 반환, 예외 전파 안 함.
- 대기 시간이 지수적으로 증가 (`time.sleep` / `asyncio.sleep` patch로 호출 인자 캡처).
- `notify_job_progress`는 1회만 시도.

---

## 3. 작업 3 — duplicate lock crash/재전달 정합

### 3-1. 문제 재확인

- `acks_late=True` + `reject_on_worker_lost=True` (`app/config.py:67-68`): worker 사망 시 메시지 재전달.
- `app/workers/job_locks.py:42-62`: 크래시한 worker는 `finally: release_job_lock` 못 돌림 →
  lock이 `celery_job_lock_ttl=900s` 동안 stale 생존.
- `app/workers/tasks/image_tasks.py:21-26` / `video_tasks.py:24-29`: 재전달분이 lock 획득 실패 →
  `on_duplicate()` → `{"status": "duplicate_skipped"}`, **콜백 없음, 재생성 없음** → WAS job 고착.

### 3-2. 핵심 아이디어 (단순화 버전 — heartbeat / lock 탈취 없음)

**lock 값에 Celery `task_id`를 저장한다.** acks_late 재전달 시 Celery는 **동일 task_id로 재전달**하므로,
lock 보유자 값이 내 `self.request.id`와 같으면 "크래시 후 되돌아온 내 메시지"로 판단하고 그대로 진행한다.
그 외(`holder != task_id`)는 전부 `duplicate_skipped` + WARNING 로그로 종료한다.

의도적으로 **하지 않는 것**:
- 명시적 lock 탈취(`DEL` + `SET`) — `holder == task_id`면 그 lock은 이미 우리 것이므로,
  그냥 진행하고 `finally`의 compare-and-delete가 정리하게 둔다.
- `AsyncResult` state 조회 / `REVOKED` 처리 — 정상 예외는 `finally`에서 lock을 이미 반납하므로
  "FAILURE인데 lock이 남은" 상태는 finally 직전 프로세스 사망이라는 극히 좁은 창뿐이고,
  그 경우도 동일 task_id 재전달로 처리된다. ai-engine에 revoke 호출 코드도 없다.
- terminal 저장소 기반 재콜백 분기 — "완료 후 콜백 유실 → WAS 재요청" 복구 경로는 §1의
  status API(`get_terminal_status`) + WAS reconciler가 담당한다. lock 로직에 중복 구현하지 않는다.

전제 검증 (모두 성립):
- `task_time_limit(720)` < `celery_job_lock_ttl(900)` → 살아있는 task 도중 lock 만료 안 됨.
- worker-lost 재전달은 동일 task_id 보존 (Celery `reject_on_worker_lost` 동작).
- `visibility_timeout(900) ≈ lock_ttl(900)` 경계에서 재전달 시:
  lock이 막 만료됐으면 `SET NX` 성공 → 정상 실행, 아직 있으면 `holder == task_id` → 진행. 둘 다 올바름.

### 3-3. 변경 — `app/workers/job_locks.py`

- `acquire_job_lock(job_id, job_type, task_id: str | None)`:
  - lock 값(`token`) = `task_id or uuid4().hex`.
  - `SET key value NX EX celery_job_lock_ttl`.
  - 획득 성공 → `JobLock(key, token=value, client)`.
  - 획득 실패 → `client.get(key)`로 보유자 값 읽어 신규 반환형 `LockHeld(holder=holder_value)` (frozen dataclass).
    - `None`(경합 중 사라짐)이면 1회 재시도 후 그래도 실패면 `LockHeld(holder=None)`.
- `release_job_lock(lock)`:
  - 현재도 `current_token == lock.token`일 때만 삭제 (compare-and-delete). 유지.
- `run_with_job_lock(*, job_id, job_type, task_id, on_duplicate, run)`:
  - `lock is False` (비활성/`job_id` 없음) → `run()`.
  - `lock is JobLock` → `run()`, `finally release_job_lock(lock)`.
  - `lock is LockHeld`:
    1. `lock.holder == task_id` (내 메시지의 재전달) → `run()`,
       `finally`에서 `release_job_lock` (token = 내 task_id라 compare-and-delete 일치).
       `logger.warning("job lock held by own redelivered task; proceeding job_id=%s", job_id)`.
    2. 그 외 → `on_duplicate()` 반환 + **`logger.warning`** (조용한 skip 방지).
- `celery_job_lock_ttl` 기본값(900) 유지. `.env.example` 주석에 "동시 중복 방지용, crash 복구는
  task_id 재전달 감지로 별도 처리" 명시.

### 3-4. 변경 — task 진입부

**`app/workers/tasks/image_tasks.py` / `video_tasks.py`**

- `generate_image_task(self, request_data)` 등은 `bind=True`이므로 `self.request.id` 사용 가능.
- `run_with_job_lock(...)` 호출에 `task_id=self.request.id` 전달.
- `_duplicate_result` / `_duplicate_result` 반환 경로에 `logger.warning` 추가 (조용한 skip 방지).
- `on_recovered` 콜백 없음 (단순화 버전).

### 3-5. 상호작용 점검표

| 시나리오 | 기대 동작 |
|---|---|
| 동일 jobId 2건 거의 동시 enqueue (서로 다른 task_id) | 1건 실행, 2건째 `duplicate_skipped` (WARNING 로그) |
| worker가 job 중간에 `kill -9` | 메시지 재전달 → 동일 task_id → `holder == task_id` → 재실행 → terminal 콜백 도달 |
| job 완료 후 terminal 콜백 유실 | WAS reconciler가 `GET /v1/*/status` 조회 → §1 terminal 저장소 hit → WAS DB 보정 (lock 로직 무관) |
| 정상 장시간 비디오(5분) 중 동일 jobId 재enqueue (다른 task_id) | `holder != task_id` → `duplicate_skipped` (정상) |
| 재전달 시점에 lock TTL이 막 만료됨 | `SET NX` 성공 → 정상 실행 |

### 3-6. 테스트 — `tests/test_job_locks.py` (신규)

- fakeredis 필요. `CELERY_JOB_LOCK_ENABLED=true` per-test 오버라이드.
- `acquire_job_lock` NX 동작, lock 값이 전달한 `task_id`인지.
- `run_with_job_lock`: 최초 호출 → `run` 실행 + 종료 후 lock 해제.
- lock 선점된 상태(다른 task_id) → `on_duplicate` 호출, `run` 미호출.
- lock 선점된 상태(동일 task_id) → `run` 호출, 종료 후 lock 해제.
- `CELERY_JOB_LOCK_ENABLED=false` → lock 경로 미진입, `run` 항상 호출.
- Redis 장애(patch로 예외) → `acquire_job_lock`이 `False` 반환하고 `run` 진행 (현행 동작 유지).
- `release_job_lock`가 값 불일치 시 삭제 안 함.

---

## 4. 작업 4 — 이미지 전체 provider 실패 처리

### 4-1. 문제 재확인

- `app/services/image/create_service.py:92-137`: 전 provider 실패 시 mock PNG를 `provider="local"`로
  `ImageCreateResponse` 반환.
- `app/workers/tasks/image_tasks.py:45-51`: 그대로 `notify_image_job_completed` → completed 콜백.
- `app/services/callbacks.py:45-61`: `notify_image_job_completed`에 `fallbackUsed`/`warnings` 없음
  (video `notify_job_completed`는 있음).

### 4-2. 결정 필요 (Open Decision #1)

- **옵션 A (권장)**: async job 경로에서 전 provider 실패 시 placeholder 반환 안 하고 `failed` 콜백.
- **옵션 B**: placeholder 유지하되 `notify_image_job_completed`에 `fallbackUsed=True`, `warnings` 추가.

두 옵션 모두 **job task 경로에서만** 분기하고, 동기 테스트 API(`/v1/image/provider-generate`,
`/v1/image/intent`)의 placeholder 동작은 건드리지 않음.

### 4-3. 변경 (옵션 A 기준)

**`app/workers/tasks/image_tasks.py` `_run_image_job`**

- `result = await create_image(image_request)` 후:
  - `if result.provider == "local":` (placeholder 판정)
    - `public_error = "모든 이미지 생성 provider가 실패했습니다."` (또는 `JOB_FAILURE_MESSAGES` 재사용)
    - `record_terminal_status("image", job_id, {...status: failed...})`
    - `await notify_job_failed(job_id, public_error, duration_ms)`
    - return failed dict
  - else 기존 completed 경로.
- `create_image` / `create_service.py`는 **변경 없음** (판정만 task에서).

### 4-3b. 변경 (옵션 B 기준, A 미채택 시)

- `app/services/callbacks.py` `notify_image_job_completed(..., fallback_used: bool | None = None, warnings: list[str] | None = None)` — 파라미터/payload 추가 (additive).
- `_run_image_job`에서 `result.routing.fallback_used`, `result.routing.warnings` 전달.
  - 단, 현재 task가 받는 `ImageCreateResponse.routing` 접근 가능 여부 확인 필요
    (`create_image` 반환형에 `routing` 포함됨 — OK).

### 4-4. 테스트 — `tests/test_image_jobs.py` (확장)

- 두 provider 모두 실패하도록 patch (`generate_openai_images`/`generate_google_images` raise) →
  - 옵션 A: `notify_job_failed` 호출, completed 콜백 없음, terminal 저장소에 `failed`.
  - 옵션 B: completed 콜백에 `fallbackUsed=True` + `warnings` 비어있지 않음.
- 정상 1개 provider 성공 → 기존대로 completed.

---

## 5. 작업 5 — reference image URL allowlist / 사설 IP 차단

### 5-1. 문제 재확인

- `app/services/image/references.py:64`: 스토리지 URL 아니면 임의 `image_url`을 worker에서 `urlopen`.
  host allowlist / 사설 IP 차단 / redirect 제한 없음. 크기·타임아웃만 제한.

### 5-2. 신규 설정 — `app/config.py`

| 키 | 기본값 | 설명 |
|---|---|---|
| `reference_image_allowed_hosts` | `[]` | 비어있으면 "공인 IP면 허용". 값이 있으면 해당 host만 허용 |
| `reference_image_block_private_ips` | `True` | 사설/loopback/link-local/reserved IP 차단 |

- production validator(`app/config.py:100`)에 경고성 체크 추가 검토:
  live 모드 + `reference_image_allowed_hosts` 비어있음 → 경고 로그(차단은 안 함).

### 5-3. 변경 — `app/services/image/references.py`

- 신규 헬퍼 `_assert_url_fetch_allowed(image_url: str) -> None`:
  1. `urlparse` → scheme이 `http`/`https` 아니면 `ProviderError`.
  2. hostname 없으면 `ProviderError`.
  3. `reference_image_allowed_hosts` 비어있지 않으면 hostname이 목록에 없을 때 `ProviderError`.
  4. `socket.getaddrinfo(hostname, port)` → 모든 결과 IP에 대해:
     `ipaddress.ip_address(ip)`가 `is_private / is_loopback / is_link_local / is_reserved / is_multicast`
     중 하나면 (`reference_image_block_private_ips=True`일 때) `ProviderError`.
     DNS 실패 → `ProviderError`.
- `_load_from_url`의 `urlopen` 직전에 `_assert_url_fetch_allowed(image_url)` 호출.
- **redirect 차단**: `urllib.request.build_opener`에 redirect를 막는 핸들러 사용
  (`HTTPRedirectHandler.redirect_request`가 `None` 반환하도록 서브클래스) → `opener.open(...)`.
  기존 `urlopen(...)` → `opener.open(...)`로 교체.
- 스토리지 fast-path(`image_url.startswith(public_base)` / localhost 매칭) 로직은 유지.
- 한계 명시(주석): getaddrinfo 검사와 실제 연결 사이 DNS rebinding TOCTOU 존재. MVP 허용,
  강화 시 resolved IP 고정 연결 필요.

### 5-4. 테스트 — `tests/test_references.py` (신규)

- `image_url` = `http://169.254.169.254/latest/meta-data/` → `ProviderError` (getaddrinfo mock 불필요, IP 리터럴).
- `http://127.0.0.1:8002/...` (스토리지 아닌 경로) → `ProviderError`.
- `ftp://...` / scheme 없음 → `ProviderError`.
- `reference_image_allowed_hosts=["cdn.example.com"]` + 다른 host → `ProviderError`.
- 공인 host + 200 응답 mock → bytes 반환.
- redirect 응답 mock → 따라가지 않고 오류.
- 스토리지 public URL → 로컬 파일 경로로 읽음 (기존 동작 회귀 없음).

---

## 6. 설정 변경 요약

| 파일 | 키 | 현재 | 변경 후 |
|---|---|---|---|
| `app/config.py` | `was_callback_timeout_sec` | `1.0` | `5.0` |
| `app/config.py` | `job_terminal_status_ttl_seconds` | (없음) | `86400` |
| `app/config.py` | `reference_image_allowed_hosts` | (없음) | `[]` |
| `app/config.py` | `reference_image_block_private_ips` | (없음) | `True` |
| `.env.example` | `WAS_CALLBACK_TIMEOUT_SEC` | `1.0` | `5.0` |
| `.env.example` | (신규 3키 주석 추가) | — | — |
| `docker-compose.prod.yml` | `WAS_CALLBACK_TIMEOUT_SEC` | `1.0` | `5.0` |

- `celery_job_lock_ttl` 은 **변경 없음** (900 유지). 주석만 갱신.
- `celery_result_expires` 는 **변경 없음** (1h 유지) — terminal 저장소가 복구 소스이므로 굳이 안 늘림.

---

## 7. 테스트 인프라

### 7-1. `tests/conftest.py` 이슈

- 현재 전역: `AI_PROVIDER_MODE=mock`, `CELERY_TASK_ALWAYS_EAGER=true`, `CELERY_JOB_LOCK_ENABLED=false`.
- 작업 1·3 테스트는 Redis 접근 필요.

### 7-2. 계획

- `requirements-dev.txt`에 `fakeredis` 추가.
- 신규 fixture (`tests/conftest.py` 또는 `tests/conftest_redis.py`):
  - `fake_redis` — `fakeredis.FakeStrictRedis` 인스턴스.
  - `patch_redis` — `app.workers.job_locks.Redis.from_url` 와 `app.services.job_status.Redis.from_url`
    를 `fake_redis` 반환하도록 monkeypatch.
  - `job_lock_enabled` — `get_settings` 캐시 클리어 + `CELERY_JOB_LOCK_ENABLED=true` env 오버라이드.
- 작업 1 status API 테스트용으로 `celery.result.AsyncResult` state 를 patch (terminal 저장소 우선순위 검증).
  작업 3 lock 테스트는 `AsyncResult` 조회를 하지 않으므로 mock 불필요.

### 7-3. 실행

```bash
cd ai-engine
.venv/bin/python -m pytest -q
```

- 기준선: 현재 문서상 `106 passed`. 신규 테스트 추가 후 전체 green 확인.
- 각 PR 머지 전 전체 `pytest` 1회.

---

## 8. PR 분리 및 순서

| PR | 포함 | 의존 | 근거 |
|---|---|---|---|
| **PR-A** | 작업 1 (terminal 저장) + 작업 2 (콜백 백오프) + 작업 4 (이미지 실패) | 없음 | 저위험, 즉시 가치. 작업 3의 전제(terminal 저장소) 제공 |
| **PR-B** | 작업 3 (lock crash/재전달 정합 — 단순화 버전) | 없음 (PR-A와 병렬 가능) | 설계 주의 필요, 리뷰 집중. terminal 저장소 의존 없음 |
| **PR-C** | 작업 5 (SSRF) | 없음 (PR-A와 병렬 가능) | 독립적 하드닝 |

- 각 PR에 해당 테스트 포함.
- PR 본문 끝에 `🤖 Generated with [Claude Code](https://claude.com/claude-code)` (요청 시 PR 생성).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

### 문서 갱신 (각 PR에 포함)

- `docs/api/job-status.md` — status API의 terminal 저장소 기반 복구,
  PENDING → processing 의미, 24h 복구 윈도우 명시.
- `docs/operations/AI_ENGINE_OPERATIONS.md` — 신규 Redis 키(`job-terminal:*`), 신규 설정.
- `docs/reports/async-ops-priority-review.md` — P0-5/P1-4/P1-6 진행률 갱신.

---

## 9. 롤아웃 / 검증 시나리오

`ai-engine/run_async_stack.sh` (redis + api + image worker + video worker) 기준:

1. **정상 이미지 job** (mock): `POST /v1/image/jobs` → completed 콜백 + `job-terminal:image:{id}` 키 존재.
2. **정상 비디오 job** (live): progress 5→90→100, `resultUrl` 접근 가능, terminal 키 존재.
3. **콜백 유실 복구**: WAS mock 정지 → job 완료 → 1h 초과 대기 → `GET /v1/video/status/{id}` 가
   `completed` + `videoUrl` 반환 (Celery result는 만료됐어도).
4. **worker 크래시**: 비디오 job 진행 중 video worker `kill -9` →
   재전달 task가 동일 task_id → `holder == task_id` 로 진행 → 재실행 → 최종 terminal 콜백 도달.
5. **동일 jobId 중복 enqueue (다른 task_id, 완료 전)**: 2건째 `duplicate_skipped` + WARNING 로그, provider 재호출 0회.
6. **이미지 전 provider 실패**: 두 provider raise mock → `failed` 콜백 (옵션 A) / `fallbackUsed` 콜백 (옵션 B).
7. **SSRF**: `reference_images[].image_url = http://169.254.169.254/...` → 400.
8. **콜백 backoff**: WAS mock이 3회 503 후 200 → 재시도 간격이 증가하며 최종 성공.

---

## 10. Open Decisions (착수 전 확정 필요)

| # | 결정 | 기본 제안 |
|---|---|---|
| 1 | 이미지 전 provider 실패 시 `failed` (옵션 A) vs placeholder+warnings (옵션 B) | **A** (정직한 실패 + 재시도) |
| 2 | `was_callback_timeout_sec` = 5 vs 10 | **5**, progress 콜백은 1 attempt |
| 3 | terminal 저장소 TTL: 기존 `job_status_ttl_seconds`(12h) 재사용 vs 신규 24h | **신규 24h** |
| 4 | SSRF allowlist를 production 필수로 강제 vs 사설 IP 차단만 항상 | **사설 IP 차단 항상 + allowlist 선택(경고만)** |
| 5 | `/v1/*/status` PENDING(매핑 존재) → `processing` vs `queued` 유지 | **`processing`** |

---

## 11. 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| 작업 3 lock 로직 회귀로 정상 job이 스킵되거나 중복 실행 | 단순화로 분기 2개뿐(holder==me / else). 3-5 점검표를 테스트로 고정, PR-B 단독 리뷰 |
| `self.request.id` 가 eager 모드에서 `None` | eager(test)에서는 `celery_job_lock_enabled=false`라 lock 경로 미진입. 신규 테스트는 fakeredis + 명시적 task_id 주입 |
| API 재시작(in-memory dedup 소실) + WAS가 완료 jobId 재-POST + lock TTL(900s) 만료, 3조건 동시 → provider 2회 호출 | 잔여 리스크로 수용. WAS `jobId UNIQUE` + reconciler-not-repost 설계가 1차 방어. 현행 대비 악화 아님 |
| terminal 저장소 write 실패가 job 실패로 전파 | `record_terminal_status`는 best-effort try/except |
| 콜백 backoff로 task 시간 증가 → soft_time_limit 초과 | progress 1 attempt + 예산 계산(2-2)으로 60s 여유 내 유지 |
| fakeredis와 실제 redis 동작 차이 | lock은 `SET NX EX` / `GET` / `DEL`만 사용 — fakeredis 지원 범위 |
| DNS rebinding TOCTOU (작업 5) | MVP 허용, 주석 명시. 강화는 별도 |
