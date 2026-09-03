# ai-engine System Overview

`ai-engine`은 G-AIM의 AI 생성 실행기다. Spring Boot WAS 뒤에서 동작하며, 텍스트, 이미지, 영상 생성 요청을 provider별 실행 정책에 따라 처리한다.

## Runtime Components

- FastAPI API server — Spring Boot WAS가 호출하는 내부 API를 제공한다.
- Redis — Celery broker/result backend와 job 상태 보조 저장소로 사용한다.
- Celery workers — 이미지/영상 생성처럼 오래 걸리는 작업을 비동기로 실행한다.
- Provider clients — OpenAI, Google/Veo, Runway 등 외부 생성 provider를 호출한다.
- Spring Boot WAS callback — ai-engine이 progress/completed/failed 상태를 WAS로 전달한다.

## Responsibility Boundary

Spring Boot WAS가 사용자 인증, 권한, job 상태의 source of truth를 담당한다. ai-engine은 생성 실행, provider 라우팅, 진행률 콜백, 완료/실패 콜백을 담당한다.

```text
frontend
  -> Spring Boot WAS
  -> ai-engine FastAPI
  -> Redis / Celery worker
  -> external AI provider
  -> Spring Boot WAS callback
  -> frontend polling
```

## Request Model

텍스트 생성은 짧은 동기 API로 처리한다. 이미지와 영상 생성은 WAS가 `jobId`를 발급한 뒤 ai-engine job API로 전달하고, ai-engine worker가 작업 상태를 callback으로 반환하는 비동기 구조를 기본으로 한다.

## Key Design Rules

- WAS DB를 job 상태의 최종 기준으로 둔다.
- ai-engine은 사용자 세션이나 권한 판단을 직접 소유하지 않는다.
- provider/model 선택은 ai-engine 내부 정책으로 캡슐화한다.
- 이미지와 영상 생성은 HTTP 요청 안에서 긴 provider polling을 직접 대기하지 않는다.
- 생성 결과, 실패 사유, fallback 여부는 WAS가 사용자에게 설명할 수 있는 형태로 전달한다.

## Related Docs

- [`async-multiuser.md`](./async-multiuser.md)
- [`image-routing-policy.md`](./image-routing-policy.md)
- [`image-code-flow.md`](./image-code-flow.md)
- [`../reports/2026-09-03-system-analysis.md`](../reports/2026-09-03-system-analysis.md)
- [`../presentations/pdf/AI Engine Architecture.pdf`](../presentations/pdf/AI%20Engine%20Architecture.pdf)
