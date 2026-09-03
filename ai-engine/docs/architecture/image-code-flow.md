# 이미지 생성 코드 실행 흐름

> Version: v1.1

## 전체 흐름

```text
backend WAS -> POST /v1/image/jobs
-> app/api/v1/image.py
-> enqueue_image_job_endpoint()
-> generate_image_task.apply_async(...)
-> worker executes create_image()
-> build_image_routing_plan()
-> provider 후보 순차 실행
-> 이미지 저장
-> backend WAS callback(progress/completed/failed)
-> frontend polls backend WAS GET /api/ai/image/async/job/{jobId}
```

## 1. API 엔드포인트

파일:

```text
app/api/v1/image.py
```

핵심 코드:

```python
@router.post("/jobs", response_model=ImageJobResponse)
async def enqueue_image_job_endpoint(request: ImageJobRequest) -> ImageJobResponse:
    generate_image_task.apply_async(
        args=[request.model_dump(by_alias=True)],
        queue="image-queue",
    )
    return ImageJobResponse(
        jobId=request.job_id,
        status="queued",
        message="이미지 생성 작업이 큐에 등록되었습니다.",
    )
```

운영 라우트 이름은 `/v1/image/jobs`로 통일했습니다. 이 API는 최종 이미지를 동기 반환하지 않고, worker queue 등록 후 `ImageJobResponse`를 즉시 반환합니다.

`POST /v1/image/generate` 동기 라우트는 비활성/주석 처리되어 Swagger에 노출되지 않습니다.

## 2. 요청 스키마

파일:

```text
app/schemas/image.py
```

주요 필드:

- `jobId`: backend WAS가 발급한 작업 ID
- `purpose`
- `visual_mood`: 기본 `bright`. frontend에서는 `비주얼 무드 (선택)`으로 표시
- `channels`
- `image_prompt`
- `reference_images`
- `text_to_render`
- `text_rendering`
- `n`

`text_rendering.text`가 있고 `text_to_render`가 없으면 `text_to_render`로 자동 복사됩니다.

`ImageJobRequest`는 기존 이미지 생성 입력인 `ImageRequest`를 확장하고 `jobId`를 필수로 추가합니다. worker는 이 payload를 받아 provider 라우팅과 이미지 생성을 실행합니다.

## 3. 비동기 worker 실행

파일:

```text
app/workers/tasks/image_tasks.py
```

함수:

```python
generate_image_task
```

동작:

1. queue payload에서 `ImageJobRequest`를 복원합니다.
2. backend WAS에 progress callback을 전송합니다.
3. `create_image()`를 호출해 provider routing/generation을 실행합니다.
4. 성공하면 생성 이미지 URL, provider, model, warning 정보를 completed callback으로 전송합니다.
5. 실패하면 error 정보를 failed callback으로 전송합니다.

frontend는 ai-engine을 직접 polling하지 않습니다. frontend는 backend WAS의 `GET /api/ai/image/async/job/{jobId}`를 polling하고, backend WAS는 ai-engine callback으로 받은 상태를 반환합니다.

## 4. 라우팅 후보 생성

파일:

```text
app/services/image/model_router.py
```

함수:

```python
build_image_routing_plan(request)
```

역할:

1. primary channel 결정
2. 최종 provider prompt 생성
3. Google용 aspect ratio 결정
4. OpenAI용 pixel size 결정
5. `visual_mood`를 OpenAI style 파생값으로 변환
6. 모델 후보 목록 생성
7. 후보별 `ProviderImageRequest` 생성

## 5. 후보 선택 기준

후보 선택 함수:

```python
_select_image_candidates(request, google_size, openai_size)
```

우선순위:

1. 텍스트 + 참조 이미지
2. 텍스트만 있음
3. 참조 이미지만 있음
4. 브랜드/고품질 요청
5. 일반 홍보/이벤트 요청

## 6. 최종 프롬프트 생성

함수:

```python
_build_final_image_prompt(request, primary_channel)
```

포함되는 정보:

- 사용자 이미지 요청
- 목적
- 비주얼 무드
- 선택 채널
- primary channel별 구성 지시
- 참조 이미지 사용 여부
- 텍스트 렌더링 지시

`visual_mood`는 `VISUAL_MOOD_HINTS`를 통해 사람이 읽을 수 있는 이미지 프롬프트 힌트로 변환됩니다.

```python
VISUAL_MOOD_HINTS = {
    "bright": "깨끗하고 밝은 하이키 조명, 선명한 색감",
    "warm_cozy": "따뜻한 색감, 골든아워 조명, 편안하고 초대하는 분위기",
    "moody": "분위기 있는 저조도 조명, 깊이 있는 색감",
    "clean_minimal": "미니멀한 구성, 넉넉한 여백, 중립적인 색감",
    "premium": "고급스러운 질감, 정제된 구도, 세련된 시각 연출",
    "vibrant": "높은 채도, 활기찬 분위기, 강한 색 대비",
}
```

최종 프롬프트에는 다음 형태로 삽입됩니다.

```text
[시각 무드]
깨끗하고 밝은 하이키 조명, 선명한 색감
```

OpenAI 후보 요청에는 `_to_openai_style()` 결과가 `ProviderImageRequest.style`로 들어갑니다.

```python
bright, vibrant -> vivid
warm_cozy, moody, clean_minimal, premium -> natural
```

텍스트가 있으면 다음 형태의 지시가 추가됩니다.

```text
다음 문구를 이미지 안에 정확히 렌더링하세요: ...
```

## 7. 후보 실행

파일:

```text
app/services/image/create_service.py
```

함수:

```python
create_image(request)
```

동작:

1. 후보 목록을 순서대로 실행
2. 성공하면 `ImageCreateResponse`를 worker에 반환
3. provider 오류는 `warnings`에 기록
4. 다음 후보로 fallback
5. 모든 provider 실패 시 local placeholder 반환
6. worker가 `ImageCreateResponse` 내용을 backend WAS callback payload로 변환

`create_image()`는 더 이상 운영 HTTP 요청에 직접 최종 응답을 반환하지 않습니다. 운영 흐름에서는 worker 내부 실행 함수로 사용됩니다.

## 8. Provider 분기

`candidate.operation == "edit"`이면 참조 이미지 기반 edit 경로를 사용합니다.

```python
if candidate.operation == "edit":
    edit_request = image_request_to_reference_request(request)
    return await _execute_edit(candidate, edit_request)
```

그 외 generate 후보는 provider에 따라 분기합니다.

```python
if candidate.provider == "google":
    return await generate_google_images(request)
if candidate.provider == "openai":
    return await generate_openai_images(request)
```

## 9. Google 호출

파일:

```text
app/services/image/google_service.py
```

Imagen 계열:

```text
client.models.generate_images()
```

Nano Banana 계열:

```text
client.models.generate_content()
```

참조 이미지 기반 Nano Banana:

```text
edit_google_images()
-> _edit_nano_banana_images_sync()
```

## 10. OpenAI 호출

파일:

```text
app/services/image/openai_service.py
```

생성:

```python
client.images.generate(...)
```

편집:

```python
client.images.edit(...)
```

`gpt-image-2` 편집 요청에는 `input_fidelity`를 전달하지 않습니다.

## 11. 저장

파일:

```text
app/services/image/storage.py
app/storage/local.py
```

생성된 이미지는 `STORAGE_BASE_DIR/images/{uuid}.png`에 저장되고, completed callback/status payload의 `images`에는 `STORAGE_PUBLIC_BASE_URL` 기준 URL이 포함됩니다.

## 12. 응답과 상태 전달

`POST /v1/image/jobs`의 즉시 응답:

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "queued",
  "message": "이미지 생성 작업이 큐에 등록되었습니다."
}
```

완료 후 backend WAS가 frontend에 반환하는 상태 payload에는 다음 정보가 포함됩니다.

```json
{
  "jobId": "f3325b10-bfcc-4ef3-814e-b1fcd47338fd",
  "status": "completed",
  "images": ["http://127.0.0.1:8000/generated/images/{uuid}.png"],
  "provider": "google",
  "modelUsed": "gemini-2.5-flash-image",
  "error": null,
  "progressPct": 100
}
```

## 13. 테스트용 provider 직접 호출

아래 API는 provider 동작을 직접 확인하기 위한 테스트용/비운영 경로입니다.

- `POST /v1/image/provider-generate`
- `POST /v1/image/provider-generate-with-reference`
- `POST /v1/image/intent` (deprecated)

운영 연동과 frontend/backend 정식 흐름은 항상 `POST /v1/image/jobs`를 기준으로 합니다.
