# ai-engine/WAS에서 Celery를 썼을 때의 단점

작성일: 2026-08-18

## 1. 배경

이 프로젝트는 과거에 Celery(`app/workers/celery_app.py`, `app/workers/tasks/video_tasks.py`)를 시도했다가 제거하고, 현재는 RabbitMQ(`aio-pika`) 기반 커스텀 워커로 영상 생성 job을 처리한다. 상세 아키텍처는 [was-ai-engine-rabbitmq-architecture.md](was-ai-engine-rabbitmq-architecture.md)를 참고한다.

이 문서는 "지금 이 시스템에서 Celery를 (다시) 쓴다면 어떤 단점이 있는가"를 정리한다. Celery 자체가 나쁜 도구라는 뜻이 아니라, 이 시스템의 요구사항(Java WAS ↔ Python ai-engine, 세분화된 retry/DLQ 정책, provider operation resume)과 안 맞는다는 의미다.

과거 Celery 설정 근거(git 이력):

```python
# app/workers/celery_app.py (삭제됨)
celery_app = Celery(
    "gaim_ai_engine",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks.video_tasks"],
)
```

```python
# app/workers/tasks/video_tasks.py (삭제됨)
@celery_app.task(bind=True, max_retries=2)
def generate_video_task(self, request_data: dict) -> dict:
    return {
        "status": "completed",
        "request": request_data,
        "note": "Local ai-engine currently uses the synchronous mock video path.",
    }
```

broker/backend로 Redis를 썼고, task 구현은 실제 provider 호출 없이 mock 응답만 반환하는 스텁 수준이었다.

## 2. RabbitMQ와 Celery 비교

RabbitMQ와 Celery는 같은 계층의 도구가 아니다. RabbitMQ는 메시지를 저장하고 전달하는 broker이고, Celery는 Python 함수 실행을 task로 감싸 worker에서 실행하게 해주는 distributed task queue framework다.

| 항목 | RabbitMQ | Celery |
|---|---|---|
| 정체 | 메시지 브로커 | Python 작업 큐 프레임워크 |
| 핵심 역할 | exchange/queue/routing key로 메시지 전달 | task 정의, worker 실행, retry, scheduling |
| 언어 경계 | AMQP 기반이라 Java/Python/Node 등에서 공통 사용 가능 | Python 중심. producer도 Celery 메시지 규약을 알아야 함 |
| 실행 책임 | 메시지를 실행하지 않음. consumer에게 전달만 함 | worker가 task 함수를 직접 실행 |
| 현재 G-AIM에서의 위치 | WAS와 ai-engine worker 사이의 job 전달 채널 | 도입한다면 ai-engine 내부 worker 구현 후보 |

따라서 "RabbitMQ를 쓸 것인가, Celery를 쓸 것인가"는 엄밀히 말하면 직접 대체 관계가 아니다. Celery도 RabbitMQ를 broker로 사용할 수 있다. 다만 현재 G-AIM에서는 Spring Boot WAS가 RabbitMQ에 순수 AMQP 메시지를 발행하고, Python ai-engine worker가 그 메시지를 consume한다. 이 구조에서는 RabbitMQ가 서비스 간 계약이고, Celery는 그 뒤쪽의 Python worker 구현 방식 중 하나일 뿐이다.

현재 책임 경계는 아래처럼 보는 것이 맞다.

```text
WAS
- 사용자 job 상태의 source of truth
- status polling 응답
- 사용자/비즈니스/캠페인 매핑
- 관리자 화면, 상태 이력, 비용/사용량 추적

RabbitMQ
- WAS에서 ai-engine worker로 video job 전달
- retry/DLQ/callback queue 전달

ai-engine worker
- provider 작업 실행
- Veo operationName 추적
- 중복 실행 방지
- worker crash/redelivery 시 resume
- terminal result callback 보장
```

이 전제에서는 Celery를 쓰더라도 WAS가 Celery task를 직접 호출하는 구조는 피해야 한다. Celery를 도입한다면 `Spring WAS -> ai-engine API -> Celery task`처럼 ai-engine 내부 구현으로만 제한하는 편이 낫다. 하지만 그러면 WAS와 ai-engine 사이의 RabbitMQ 기반 경계는 별도로 남거나, 다시 HTTP job API를 설계해야 한다.

## 3. 단점

### 3.1 Java WAS ↔ Python ai-engine 간 언어 불일치

Celery는 Python 전용 프로토콜이다. 지금 구조는 WAS(Spring Boot)가 순수 AMQP를 Spring AMQP(`RabbitTemplate`)로 직접 발행하고, ai-engine이 `aio-pika`로 그냥 consume하는 방식이라 언어에 무관하게 동작한다.

Celery를 쓰려면 WAS가 Celery 프로토콜(메시지 포맷, 헤더 규약)에 맞춰 발행하거나 별도 브릿지를 둬야 한다. 결국 WAS는 raw AMQP를 다뤄야 하는 상황이 되므로, ai-engine 쪽만 Celery로 감싸는 것은 이득이 크지 않다.

### 3.2 Redis라는 추가 인프라 의존성

과거 설정은 broker/backend 모두 Redis였다. WAS가 이미 RabbitMQ를 메시징 채널로 쓰는 상황에서 Celery를 되살리려면:

- Redis를 새 인프라 의존성으로 추가하거나
- Celery를 RabbitMQ 위에 broker로 얹어야 한다(가능은 하지만 Celery의 result backend 관례는 여전히 Redis/DB 쪽에 최적화돼 있다).

어느 쪽이든 지금 구조(WAS와 ai-engine이 같은 RabbitMQ 하나만 공유)보다 인프라가 늘어난다.

단, 여기서 말하는 Redis 의존성과 ai-engine의 파일 기반 `operation_store`/`result_store`를 Redis로 바꾸는 것은 별개의 판단이다. 후자는 Celery 도입이 아니라 worker resume/idempotency를 위한 내부 저장소 개선이다. WAS가 관리하는 job 상태, 관리자 화면, 비용 추적과도 책임이 다르다.

```text
WAS DB/상태 저장소
- 사용자에게 보여줄 job status
- 이력, 감사, 비용, 권한

ai-engine Redis
- video:operation:{jobId}
- video:result:{jobId}
- video:operation-lock:{jobId}
- operationName, requestFingerprint, terminal result replay cache
```

이 Redis는 WAS가 직접 참조하지 않아도 된다. WAS와 맞춰야 할 것은 기존 RabbitMQ message schema, `jobId`, callback payload 계약뿐이다.

### 3.3 세분화된 retry/DLQ 토폴로지를 표현하기 어려움

현재 구조는 실패 종류별로 서로 다른 큐/TTL/재시도 횟수를 쓴다.

| 실패 종류 | 큐 | 재시도 횟수 | 지연 |
|---|---|---:|---:|
| 일반 provider/storage 오류 | `video.generate.retry` | 3회 | 30초 |
| Veo timeout | `video.generate.retry.timeout` | 1회 | 5분 |
| operation start claim 충돌 | `video.generate.retry.starting` | 2회 | 150초 |
| WAS callback 전송 실패 | `video.callback.retry` | 5회 | 15초 |

Celery의 `self.retry(countdown=...)`/`max_retries`는 task 단위 재시도 정책이라, "이 실패는 A 큐로, 저 실패는 B 큐로, 각각 다른 TTL로" 같은 큐 레벨 라우팅을 표현하려면 결국 raw AMQP 기능을 다시 다뤄야 한다. Celery의 추상화가 도움이 되기보다 오히려 우회해야 할 장애물이 된다.

### 3.4 provider operation resume/멱등성 문제는 Celery가 대신 해주지 않음

이 시스템에서 가장 어려운 부분은 큐 라이브러리와 무관하다.

- `operation_store`: `job_id` + request fingerprint + Veo `operationName`을 원자적으로 기록해, 타임아웃 재시도 시 `generate_videos()`를 다시 부르지 않고 기존 operation polling을 재개한다.
- `result_store`: terminal 결과를 기록해, 메시지가 재전달돼도 provider를 재호출하지 않고 저장된 결과로 callback만 재발행한다.

Celery의 기본 재시도는 task를 처음부터 다시 실행하는 것이므로, provider 쪽에서 이미 진행 중인 장시간 작업을 이어받는(resume) 능력이 없다. 이 방어 로직은 Celery를 쓰든 안 쓰든 직접 구현해야 하므로, Celery 도입이 가장 어려운 작업량을 줄여주지 않는다.

현재 이 정보는 ai-engine의 파일 저장소에 있다. 단일 host/shared volume 전제에서는 동작하지만, worker를 여러 host에 분산하면 같은 `jobId`의 operation/result 상태를 공유하지 못한다. 이 부분은 Celery 여부와 무관하게 Redis 같은 공유 저장소로 바꾸는 것이 더 직접적인 개선이다.

### 3.5 운영 부담 증가

Celery worker는 별도의 프로세스 관리(prefork/eventlet/gevent 등 concurrency 모델 선택), 보통 함께 쓰는 Flower 같은 모니터링, task 시그니처 변경 시 버전 호환성까지 추가로 관리해야 한다.

지금 구조는 asyncio 프로세스 하나가 `video.generate`/`video.callback` 두 큐를 함께 consume하는 단일 모델이라, 튜닝 지점이 `asyncio.Semaphore`(동시성)와 thread pool 크기 정도로 단순하다.

### 3.6 Celery로 대체되는 부분과 남는 부분이 섞임

Celery를 도입하면 현재 custom worker 중 일부는 줄일 수 있다.

```text
대체 가능:
- aio-pika consume loop
- 직접 message ack/nack 처리
- 일부 retry scheduling
- worker process 실행 방식

계속 필요:
- Veo provider 호출
- operationName 저장과 polling resume
- requestFingerprint 검증
- terminal result replay
- WAS callback payload 계약
- 사용자 job 상태 source of truth
```

즉 Celery는 worker 실행 프레임워크를 대체할 수 있지만, video generation 도메인 로직이나 운영 상태 모델을 대체하지 않는다.

### 3.7 callback queue는 분리되어 있지만 worker 프로세스는 아직 분리되어 있지 않음

현재 구조는 `video.generate`와 `video.callback` 큐를 분리해 두었다. 이 점은 좋다. 다만 같은 ai-engine worker 프로세스가 두 큐를 모두 consume한다.

```text
현재:
ai-engine-worker
  -> video.generate consume
  -> video.callback consume

운영 분리안:
ai-engine-video-worker
  -> video.generate consume

ai-engine-callback-worker
  -> video.callback consume
```

영상 생성 worker는 provider quota, CPU/RAM, 장시간 polling 기준으로 scale해야 하고 callback worker는 WAS HTTP I/O 기준으로 scale해야 한다. Celery를 도입하지 않더라도 이 분리는 별도 개선 과제로 볼 수 있다.

## 4. Celery가 유리한 경우 (참고)

공정하게 보면 Celery가 나은 상황도 있다.

- task chain/group/chord 같은 워크플로 조합이 필요할 때
- Flower 등 기성 모니터링 도구를 바로 쓰고 싶을 때
- 실패 종류별 세분화된 큐 라우팅이 필요 없는, 범용적인 백그라운드 job 처리일 때
- producer와 worker가 모두 Python이고, 서비스 간 계약을 Celery task protocol로 통일해도 될 때

이런 조건이면 Celery가 코드량을 줄여준다. 하지만 이 프로젝트처럼 언어가 다른 producer(WAS)와 ai-engine이 하나의 RabbitMQ를 공유하고, 실패 종류별 재시도 정책과 provider operation resume이 필요한 시스템에는 맞지 않는다.

## 5. 결론

지금의 RabbitMQ(`aio-pika`) 기반 커스텀 워커 구조를 유지하는 것이 맞다. Celery로 되돌아가면 인프라(Redis)가 늘고, WAS와의 언어 불일치 문제가 남고, 세분화된 retry/DLQ 정책을 다시 raw AMQP로 구현해야 해서 실질적인 이득이 없다.

우선순위는 Celery 도입보다 아래 개선이 먼저다.

1. WAS job status는 WAS 담당 저장소(DB/Redis 등)로 영속화한다.
2. ai-engine의 `operation_store`/`result_store`는 파일에서 Redis로 바꿔 worker resume/idempotency를 multi-worker/multi-host에서도 보장한다.
3. RabbitMQ는 data volume, 계정, queue depth/DLQ monitoring을 운영 기준으로 정리한다.
4. callback queue는 이미 분리되어 있으므로, 다음 단계에서는 callback consumer 프로세스도 video generation worker와 분리한다.

Celery는 이 개선을 끝낸 뒤에도 custom worker 실행/재시도 코드가 계속 부담이 될 때 다시 검토하는 것이 맞다. 그때도 WAS가 Celery를 직접 호출하는 구조가 아니라 ai-engine 내부 구현으로 제한해야 한다.
