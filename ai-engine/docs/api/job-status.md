# Backend - ai-engine Job Status 연동 가이드

> 목적: backend 개발자가 `ai-engine` 비동기 job status 연동 방식을 선택하고 구현할 수 있도록 기준을 정리한다.

## 결론

`callback push`와 `backend polling`은 둘 다 가능한 구조입니다. 중요한 차이는 **backend가 job status를 어디에, 얼마나 안정적으로 저장하느냐**입니다.

```text
backend 인메모리 + ai-engine callback push
=> 운영 안정성 낮음

backend DB + ai-engine callback push
=> 충분히 운영 가능

backend DB + backend polling
=> 이것도 가능하지만 항상 더 안정적인 것은 아님

backend DB + ai-engine callback push + reconciliation polling
=> 권장 운영 구조
```

권장안은 **callback push를 기본 상태 반영 경로로 사용하고, callback 유실 복구를 위해 backend reconciliation polling을 보조 경로로 두는 방식**입니다.

```text
기본 상태 반영:
ai-engine -> backend callback push

장애 복구:
backend scheduled reconciler -> ai-engine status polling

frontend 조회:
frontend -> backend status API -> backend DB
```

## 현재 GAIM 연동 방향

운영 기준 source of truth는 backend WAS DB입니다.

frontend는 `ai-engine`을 직접 호출하지 않고 backend API만 호출합니다.

```http
POST /api/ai/image/async/generate
GET  /api/ai/image/async/job/{jobId}

POST /api/ai/video/async/generate
GET  /api/ai/video/async/job/{jobId}
```

backend는 `jobId`를 생성하고 DB에 저장한 뒤 `ai-engine` 내부 API로 job을 등록합니다.

```http
POST /v1/image/jobs
POST /v1/video/jobs
```

`ai-engine`은 작업 진행률과 최종 결과를 backend callback API로 전달합니다.

```http
POST /internal/callback/jobs/{jobId}/progress
POST /internal/callback/jobs/{jobId}
```

## 방식 A: backend DB + ai-engine callback push

이 방식은 `ai-engine`이 상태 변화를 backend에 알려주는 구조입니다.

```text
Frontend
  -> Backend 생성 요청

Backend
  -> jobId 생성
  -> DB INSERT status=queued
  -> ai-engine /v1/image/jobs or /v1/video/jobs 호출

ai-engine
  -> queue 등록
  -> worker 실행
  -> progress callback
  -> completed/failed callback

Backend
  -> callback 수신
  -> DB status 업데이트

Frontend
  -> Backend status API polling
  -> Backend DB 상태 반환
```

장점:

- 상태 변화가 있을 때만 backend에 전달되므로 backend -> ai-engine polling 부하가 적습니다.
- 사용자가 화면을 닫아도 backend DB에 완료/실패 상태를 기록할 수 있습니다.
- completed callback 시점에 결과 저장, 콘텐츠 row 연결, 알림 발송, usage 반영 같은 후처리를 backend에서 한 번에 처리하기 좋습니다.
- job 수가 많아져도 주기적 polling보다 불필요한 트래픽이 적습니다.

주의점:

- callback 수신 endpoint가 반드시 필요합니다.
- callback은 네트워크 장애, backend 재시작, timeout 때문에 유실될 수 있습니다.
- 같은 callback이 중복 도착할 수 있습니다.
- progress callback과 completed callback의 도착 순서가 뒤바뀔 수 있습니다.

따라서 callback push 방식은 아래 조건을 만족해야 운영 가능합니다.

- status를 DB에 저장
- `jobId` 기준 idempotent 처리
- `X-Internal-Token` 검증
- terminal status 이후 progress 무시
- 상태 역전 방어
- callback 유실 복구용 reconciliation polling 제공

## 방식 B: backend DB + backend polling

이 방식은 backend가 `ai-engine`에 status를 직접 물어보는 구조입니다.

```text
Frontend
  -> Backend 생성 요청

Backend
  -> jobId 생성
  -> DB INSERT status=queued
  -> ai-engine /v1/image/jobs or /v1/video/jobs 호출

ai-engine
  -> queue 등록
  -> worker 실행
  -> ai-engine 내부 status 저장

Frontend
  -> Backend status API polling

Backend
  -> ai-engine status API 조회
  -> DB 업데이트
  -> Frontend 응답
```

장점:

- callback endpoint를 별도로 열지 않아도 됩니다.
- backend가 원할 때 상태를 조회하므로 callback 유실 문제는 줄어듭니다.
- 장애 후 backend가 `jobId`만 알고 있으면 ai-engine에 다시 조회해 상태를 복구할 수 있습니다.

주의점:

- backend -> ai-engine 조회 트래픽이 계속 발생합니다.
- 많은 job이 동시에 실행되면 polling interval, timeout, rate limit 정책이 필요합니다.
- ai-engine도 job status를 안정적으로 저장해야 합니다.
- ai-engine status 저장소가 메모리라면 ai-engine 재시작 시 상태가 사라질 수 있습니다.
- frontend polling이 곧 backend -> ai-engine polling으로 증폭될 수 있습니다.

따라서 backend polling 방식도 아래 조건이 필요합니다.

- ai-engine의 durable status 저장소
- backend polling interval/backoff
- timeout과 max polling window
- ai-engine 장애 시 backend DB 상태 처리 정책
- completed/failed 이후 polling 종료

## 비교표

| 항목 | callback push | backend polling |
|---|---|---|
| 기본 방향 | ai-engine이 backend에 상태 push | backend가 ai-engine 상태 조회 |
| frontend 조회 | backend DB 조회 | backend DB 또는 ai-engine 조회 결과 |
| backend DB 필요성 | 강함 | 강함 |
| callback endpoint | 필요 | 불필요 |
| ai-engine status 조회 API | 복구용으로 권장 | 필수 |
| 트래픽 | 상태 변화 시에만 발생 | polling 주기마다 발생 |
| callback 유실 위험 | 있음 | 낮음 |
| 중복 처리 | 필요 | 상대적으로 적음 |
| 대량 job 처리 | 유리 | polling 부하 관리 필요 |
| 구현 단순성 | callback 처리 규칙 필요 | polling/backoff 규칙 필요 |
| 운영 권장도 | DB + 복구 polling 있으면 권장 | 가능하지만 기본 경로로만 쓰면 부하 고려 필요 |

## 왜 callback-only는 부족한가

callback push 자체는 문제가 아닙니다. 문제는 **callback이 반드시 도착한다고 가정하는 것**입니다.

예시:

```text
ai-engine worker 작업 완료
-> backend로 completed callback 전송
-> 순간적으로 backend 장애 또는 timeout
-> callback 실패
-> ai-engine 작업은 완료됨
-> backend DB는 processing에 멈춤
```

이 문제를 막으려면 callback 실패를 완전히 제거하려 하기보다, stuck job을 나중에 복구할 수 있는 경로를 둬야 합니다.

권장 복구 방식:

```text
backend scheduled reconciler
  -> DB에서 오래 queued/processing 상태인 job 조회
  -> ai-engine status API 조회
  -> completed/failed면 DB 보정
  -> 아직 진행 중이면 lastCheckedAt만 갱신
```

## 권장 운영 구조

최종 권장 구조는 아래와 같습니다.

```text
1. Backend가 jobId를 생성한다.
2. Backend가 DB에 job row를 생성한다.
3. Backend가 ai-engine /v1/image/jobs 또는 /v1/video/jobs를 호출한다.
4. ai-engine은 queued를 즉시 반환한다.
5. ai-engine worker가 provider 실행과 storage 저장을 처리한다.
6. ai-engine은 progress/completed/failed callback을 backend에 보낸다.
7. Backend는 callback을 검증하고 DB 상태를 업데이트한다.
8. Frontend는 backend status API만 polling한다.
9. Backend reconciler는 오래 멈춘 job을 ai-engine status API로 보정한다.
```

이 구조에서는 backend DB가 운영 source of truth입니다. `ai-engine`은 작업 실행자이며, callback과 reconciliation status API를 통해 backend DB를 최신화합니다.

## Status enum

현재 GAIM 연동 status 값은 아래 4개로 통일합니다.

```text
queued
processing
completed
failed
```

의미:

| status | 의미 | terminal |
|---|---|---:|
| `queued` | job 요청 접수 또는 queue 등록 | 아니오 |
| `processing` | provider 실행 또는 storage 저장 중 | 아니오 |
| `completed` | 생성 성공, 결과 URL 사용 가능 | 예 |
| `failed` | 생성 실패, error 확인 필요 | 예 |

## Callback payload 계약

Progress callback:

```http
POST /internal/callback/jobs/{jobId}/progress
X-Internal-Token: {WAS_INTERNAL_TOKEN}
Content-Type: application/json
```

```json
{
  "progress": 5
}
```

Image completed callback:

```http
POST /internal/callback/jobs/{jobId}
X-Internal-Token: {WAS_INTERNAL_TOKEN}
Content-Type: application/json
```

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

Video completed callback:

```json
{
  "status": "completed",
  "resultUrl": "http://127.0.0.1:8002/gaim/generated/videos/c2814445-0491-432a-ad99-268a6b3e7440.mp4",
  "durationMs": 12345,
  "provider": "google",
  "modelUsed": "veo-3.1-fast-generate-001",
  "fallbackUsed": false,
  "warnings": []
}
```

Failed callback:

```json
{
  "status": "failed",
  "error": "provider request failed",
  "durationMs": 12345
}
```

## Backend 구현 체크리스트

- frontend 요청은 backend API에서만 받습니다.
- backend가 `jobId`를 생성합니다.
- backend DB에 job row를 생성합니다.
- userId, businessId, campaignId, request payload, status, progressPct를 저장합니다.
- ai-engine 호출 전 사용자 권한과 quota를 검증합니다.
- ai-engine 호출 시 `X-Internal-Token`을 포함합니다.
- callback 수신 endpoint를 internal route로 둡니다.
- callback 수신 시 `X-Internal-Token`을 검증합니다.
- `jobId`로 DB row를 조회합니다.
- progress callback은 terminal status가 아닐 때만 반영합니다.
- completed callback은 result URL과 provider 정보를 저장합니다.
- failed callback은 error를 저장합니다.
- callback 처리는 idempotent해야 합니다.
- 오래 stuck된 job을 복구하는 scheduled reconciler를 둡니다.

## 상태 전이 규칙

| 현재 status | 수신 이벤트 | 다음 status | 처리 |
|---|---|---|---|
| 없음 | 생성 요청 | `queued` 또는 `pending` | DB row 생성 |
| `queued` | ai-engine queued 응답 | `queued` | queue 등록 확인 |
| `queued` | progress callback | `processing` | progressPct 저장 |
| `processing` | progress callback | `processing` | progressPct 갱신 |
| `queued` 또는 `processing` | completed callback | `completed` | result 저장, progressPct=100 |
| `queued` 또는 `processing` | failed callback | `failed` | error 저장, progressPct=100 |
| `completed` | progress callback | `completed` | 무시 |
| `failed` | progress callback | `failed` | 무시 |
| `completed` 또는 `failed` | completed/failed callback 재수신 | 유지 | idempotent 처리 |

`processing` 이후 `queued`로 되돌리는 상태 역전은 허용하지 않습니다.

## Reconciliation polling

callback push를 기본 경로로 쓰더라도, 운영 안정성을 위해 backend에 보정 polling을 둡니다.

대상:

```sql
status IN ('queued', 'processing')
AND updated_at < now() - interval 'N minutes'
```

권장 동작:

1. 오래된 진행 중 job을 일정 개수 조회합니다.
2. ai-engine status API로 현재 상태를 확인합니다.
3. ai-engine이 `completed`면 backend DB를 completed로 보정합니다.
4. ai-engine이 `failed`면 backend DB를 failed로 보정합니다.
5. ai-engine도 모르면 retry count를 올리거나 timeout 정책에 따라 failed 처리합니다.

주의:

- 모든 job을 매번 polling하지 않습니다.
- stuck job만 대상으로 합니다.
- batch size와 interval을 제한합니다.
- ai-engine 장애 시 backend status API가 느려지지 않도록 scheduled worker에서 처리합니다.

## Backend 개발자에게 전달할 가이드 문구

```text
GAIM의 운영 구조는 backend DB를 job status의 source of truth로 둡니다.

기본 상태 업데이트는 ai-engine callback push로 처리합니다.
ai-engine은 /internal/callback/jobs/{jobId}/progress 와
/internal/callback/jobs/{jobId} 로 progress/completed/failed를 전달합니다.

backend는 callback endpoint에서 X-Internal-Token을 검증하고,
jobId로 DB row를 찾아 status, progressPct, resultUrl/images, error,
provider, modelUsed, fallbackUsed, warnings를 업데이트하면 됩니다.

callback은 중복되거나 순서가 늦게 도착할 수 있으므로 idempotent하게 처리해야 합니다.
completed/failed 이후 들어오는 progress callback은 무시합니다.

callback 유실에 대비해 오래 queued/processing 상태인 job은
backend scheduled reconciler가 ai-engine status API로 확인해 DB를 보정하는
fallback polling을 두는 것을 권장합니다.
```

## 관련 문서

- [Spring Boot 이미지 생성 연동 가이드](./springboot-image-generate-guide-v1.1.md)
- [Spring Boot 비디오 생성 연동 가이드](./springboot-video-generate-guide-v1.1.md)
- [이미지 생성 API 가이드](./image-generate-guide-v1.1.md)
- [숏폼 영상 생성 API 가이드](./video-generate-guide-v1.1.md)
