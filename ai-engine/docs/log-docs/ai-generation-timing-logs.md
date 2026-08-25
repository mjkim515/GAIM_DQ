# AI 생성 시간 로그

## 목적

AI Engine은 텍스트, 이미지, 비디오 생성에 걸린 시간을 측정해서 로그로 남길 수 있다.
이 로그는 운영 중 생성 지연 확인, provider/model별 응답 시간 비교, 이미지 fallback 원인 분석에 사용한다.

생성 시간 로그는 기본적으로 꺼져 있다.
아래 옵션을 켠 경우에만 생성 시간을 측정하고 로그를 남긴다.

```env
AI_GENERATION_TIMING_LOG_ENABLED=true
```

기본값은 다음과 같다.

```env
AI_GENERATION_TIMING_LOG_ENABLED=false
AI_GENERATION_TIMING_LOG_FILE=
```

## 설정 옵션

### AI_GENERATION_TIMING_LOG_ENABLED

생성 시간 측정과 로그 출력을 켜고 끄는 옵션이다.

| 값 | 동작 |
| --- | --- |
| `false` | 생성 시간 측정 안 함, 로그 안 남김 |
| `true` | 생성 시간 측정 후 로그 남김 |

### AI_GENERATION_TIMING_LOG_FILE

생성 시간 로그를 파일로 남길지 결정하는 옵션이다.
`AI_GENERATION_TIMING_LOG_ENABLED=true`일 때만 의미가 있다.

| 값 | 동작 |
| --- | --- |
| 빈 값 | stdout/stderr로 출력 |
| 파일 경로 | 해당 파일에 로그 기록 |
| `true` | 기본 파일 경로 `logs/ai-generation-timing.log`에 기록 |
| `false`, `0`, `none`, `null`, `off` | stdout/stderr로 출력 |

예시:

```env
# 생성 시간 로그 비활성화
AI_GENERATION_TIMING_LOG_ENABLED=false
AI_GENERATION_TIMING_LOG_FILE=

# 생성 시간 로그 활성화, stdout/stderr 출력
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=

# 생성 시간 로그 활성화, 지정 파일에 기록
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=logs/ai-generation-timing.log

# Docker/compose 권장 파일 경로
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=/app/logs/ai-generation-timing.log

# 생성 시간 로그 활성화, 기본 파일 경로에 기록
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=true
```

## 현재 구현 위치

공통 로그 함수:

```text
ai-engine/app/core/logging.py
```

주요 함수:

```python
log_ai_generation_timing(...)
is_ai_generation_timing_enabled()
```

사용 logger 이름:

```text
app.ai_generation_timing
```

파일 로그를 사용하는 경우 `RotatingFileHandler`를 사용한다.

| 항목 | 값 |
| --- | --- |
| 기본 파일 경로 | `logs/ai-generation-timing.log` |
| 파일 회전 기준 | 10 MB |
| 백업 파일 개수 | 5개 |

상대 경로를 지정하면 ai-engine 프로세스의 현재 작업 디렉터리를 기준으로 파일이 생성된다.
필요한 디렉터리는 자동으로 생성된다.

## 실행 방식별 로그 위치

`AI_GENERATION_TIMING_LOG_FILE`이 비어 있으면 로그는 stdout/stderr로 출력된다.
파일 경로를 지정하면 해당 파일에 기록된다.

| 실행 방식 | `AI_GENERATION_TIMING_LOG_FILE`이 빈 값일 때 | 파일 경로를 지정했을 때 |
| --- | --- | --- |
| 로컬 `uvicorn` | ai-engine을 실행한 터미널 | 지정한 파일 경로 |
| `run_server.sh` | 스크립트를 실행한 터미널 | 지정한 파일 경로 |
| Docker container | 컨테이너 stdout/stderr, `docker logs`에서 확인 | `/app/logs/ai-generation-timing.log` 권장. 유지하려면 `/app/logs` volume mount 필요 |
| docker-compose | 서비스 로그, `docker compose logs`에서 확인 | `./logs:/app/logs` mount 기준으로 host의 `ai-engine/logs/ai-generation-timing.log`에서 확인 |
| systemd | `journalctl`에서 확인 | 지정한 파일 경로. 서비스 사용자 권한 필요 |
| Kubernetes | `kubectl logs` 또는 클러스터 로그 수집기 | Pod 내부 파일. 유지하려면 persistent volume 필요 |
| Cloud runtime | 플랫폼 stdout/stderr 로그 수집기 | 런타임별로 다르며 파일 보존이 보장되지 않을 수 있음 |

컨테이너/Kubernetes/Cloud Run 같은 환경에서는 보통 파일보다 stdout/stderr 수집이 운영하기 쉽다.
단일 VM이나 로컬 운영에서는 파일 로그가 유용할 수 있다.

Docker/compose에서 파일 로그를 사용할 때는 생성 산출물/상태 저장소인 `/app/storage-data`와 로그 경로를 분리한다.
권장 경로는 다음과 같다.

```env
AI_GENERATION_TIMING_LOG_FILE=/app/logs/ai-generation-timing.log
```

compose에서는 `/app/logs`를 host 디렉터리에 mount한다.

```yaml
volumes:
  - ./logs:/app/logs
```

## 공통 로그 필드

로그 메시지는 `ai_generation_timing` 이벤트 이름 뒤에 key-value 형태로 출력된다.

공통 필드:

| 필드 | 의미 |
| --- | --- |
| `content_type` | `text`, `image`, `video` 중 하나 |
| `operation` | 측정한 작업 이름 |
| `provider` | `openai`, `google`, `local` 등 provider 이름 |
| `model` | 실제 사용한 model 이름 |
| `duration_ms` | 소요 시간, 밀리초 단위 |
| `status` | `success` 또는 `failed` |

콘텐츠별 추가 필드:

| 필드 | 사용 대상 | 의미 |
| --- | --- | --- |
| `tokens_used` | text | provider 또는 mock이 반환한 token 수 |
| `fallback_used` | image | 최종 이미지 결과가 fallback을 사용했는지 여부 |
| `attempted_count` | image | 시도한 이미지 candidate 개수 |
| `rank` | image | 이미지 라우팅 candidate 순위 |
| `job_id` | video | 비디오 job id |
| `video_url` | video | 비디오 생성 성공 시 결과 URL |

예시:

```text
ai_generation_timing content_type=image operation=create_image provider=google model=imagen-4.0-generate-001 duration_ms=8421 fallback_used=True attempted_count=2 status=success
```

## 이미지 생성 시간 측정

구현 파일:

```text
ai-engine/app/services/image/create_service.py
```

측정 지점:

| 함수 | operation | 의미 |
| --- | --- | --- |
| `create_image()` | `create_image` | 이미지 생성 전체 시간. 라우팅, validation, provider fallback, placeholder 응답 포함 |
| `_execute_candidate()` | `candidate_generate` 또는 `candidate_edit` | provider/model candidate 1개의 실행 시간 |

이미지는 `/v1/image/generate` 기준으로 다음 두 종류의 시간을 볼 수 있다.

1. 사용자 입장에서 이미지 생성 1회에 걸린 전체 시간
2. provider/model candidate별 API 호출 시간과 실패 시간

OpenAI/Google provider 함수 내부에는 별도 타이밍 로그를 넣지 않았다.
`_execute_candidate()`와 거의 같은 시간이 중복으로 찍히는 것을 피하기 위해서다.

## 텍스트 생성 시간 측정

구현 파일:

```text
ai-engine/app/services/text/openai_service.py
```

측정 지점:

| 함수 | operation | 의미 |
| --- | --- | --- |
| `_generate_openai_text()` | `generate_text` | mock/live OpenAI 텍스트 생성 시간 |

커버되는 API:

| API | 측정 여부 |
| --- | --- |
| `/v1/text/generate` | 측정 |
| `/v1/text/brand` | 측정 |
| `/v1/text/marketing` | 측정 |
| `/v1/text/refine` | 측정 |

## 비디오 생성 시간 측정

구현 파일:

```text
ai-engine/app/services/video/veo_service.py
```

측정 지점:

| 함수 | operation | 의미 |
| --- | --- | --- |
| `enqueue_video_generation()` mock 경로 | `enqueue_video_generation` | 요청 시작부터 mock 실패 상태 설정까지 걸린 시간 |
| `enqueue_video_short_generation()` mock 경로 | `enqueue_video_short_generation` | 요청 시작부터 mock 실패 상태 설정까지 걸린 시간 |
| `_run_live_video_generation()` | `generate_video` | live 비디오 생성 background job 전체 시간 |
| `_run_live_video_short_generation()` | `generate_video_short` | live 숏폼 비디오 생성 background job 전체 시간 |

비디오는 live mode에서 비동기 job으로 처리된다.
HTTP 응답은 job 시작만 의미하므로, 실제 생성 시간은 background task 내부에서 측정한다.
측정 범위는 provider 호출, polling, 파일 저장, 완료/실패 처리까지 포함한다.

## 로컬 활성화 방법

터미널에서 바로 켜려면:

```bash
AI_GENERATION_TIMING_LOG_ENABLED=true ai-engine/.venv/bin/uvicorn app.main:app --app-dir ai-engine --reload
```

파일 로그까지 켜려면:

```bash
AI_GENERATION_TIMING_LOG_ENABLED=true AI_GENERATION_TIMING_LOG_FILE=logs/ai-generation-timing.log ai-engine/.venv/bin/uvicorn app.main:app --app-dir ai-engine --reload
```

Docker/compose에서는 다음 경로를 권장한다.

```env
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=/app/logs/ai-generation-timing.log
```

또는 `ai-engine/.env`에 추가한다.

```env
AI_GENERATION_TIMING_LOG_ENABLED=true
AI_GENERATION_TIMING_LOG_FILE=logs/ai-generation-timing.log
```

설정을 바꾼 뒤에는 ai-engine 프로세스를 재시작해야 한다.

## 검증 명령

생성 시간 로그 관련 테스트만 실행:

```bash
ai-engine/.venv/bin/python -m pytest ai-engine/tests/test_api.py -k "timing"
```

API 테스트 전체 실행:

```bash
ai-engine/.venv/bin/python -m pytest ai-engine/tests/test_api.py
```

## 운영 메모

- 생성 시간 로그는 완료/실패 중심으로 남긴다.
- polling 루프마다 로그를 남기지 않으므로 로그량은 비교적 작다.
- 파일 로그는 동기 파일 I/O이지만, 현재 로그 빈도에서는 AI 생성 시간에 비해 오버헤드가 작다.
- 네트워크 파일시스템이나 매우 높은 트래픽에서는 파일 로그보다 stdout/stderr 수집이 더 안전하다.
- 컨테이너에서 파일 로그를 남기려면 volume mount와 log rotation 정책을 함께 확인해야 한다.
