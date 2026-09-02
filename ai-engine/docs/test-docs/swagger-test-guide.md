# Swagger 테스트 가이드

## 요약

ai-engine의 Swagger UI는 다음 두 주소로 접속할 수 있습니다.

| 구분 | Swagger URL | Swagger의 Server 값 |
|---|---|---|
| 로컬 또는 SSH 터널 | `http://127.0.0.1:8002/docs` | `http://127.0.0.1:8002` |
| 운영 프록시 | `https://ai.idq.co.kr/gaim/docs` | `https://ai.idq.co.kr/gaim` |

정확한 문서 경로는 `/doc`이 아니라 `/docs`입니다. Swagger 상단의 **Servers** 항목에는 접속 환경에 맞는 주소 하나만 표시되어야 합니다. 다른 주소가 표시된다면 새로고침한 뒤 다시 확인합니다.

이 문서는 다음 두 가지 이미지 생성 흐름을 설명합니다.

- 동기 테스트: `POST /v1/image/provider-generate`의 응답에서 생성 이미지 URL을 즉시 확인
- 비동기 Job 테스트: `POST /v1/image/jobs`로 작업을 등록하고 WAS 상태 API에서 완료 결과 확인

모든 이미지 API 요청에는 ai-engine의 `WAS_INTERNAL_TOKEN`과 일치하는 `X-Internal-Token` 헤더가 필요합니다. 실제 토큰은 문서에 기록하지 말고 서버 관리자에게 전달받아 사용합니다.

## 1. 외부 컴퓨터에서 로컬 Swagger 접속

ai-engine이 실행 중인 서버와 다른 컴퓨터에서 `127.0.0.1:8002` 주소를 사용하려면 먼저 SSH 로컬 포트 포워딩을 연결해야 합니다.

```bash
ssh -L 8002:127.0.0.1:8002 USER@SERVER_HOST
- 외부 컴퓨터 터미널에서: ssh -L 8002:127.0.0.1:8002 dqlab@211.192.116.158
```

- `USER`: ai-engine 서버에 SSH로 접속할 사용자명
- `SERVER_HOST`: ai-engine 서버의 IP 주소 또는 SSH 호스트명
- 앞쪽 `8002`: 현재 컴퓨터에서 사용할 포트
- 뒤쪽 `127.0.0.1:8002`: 원격 서버에서 ai-engine이 수신하는 주소와 포트

SSH 세션을 종료하면 터널도 끊어지므로 테스트하는 동안 해당 터미널을 열어 둡니다. 연결 후 외부 컴퓨터의 브라우저에서 다음 주소를 엽니다.

```text
http://127.0.0.1:8002/docs
```

접속 전에 다음 항목을 확인합니다.

1. 원격 서버에서 ai-engine API가 `127.0.0.1:8002`로 실행 중인지 확인합니다.
2. 외부 컴퓨터에서 `8002` 포트를 이미 사용하는 프로그램이 없는지 확인합니다.
3. `USER@SERVER_HOST`에 대한 SSH 접속 권한과 방화벽 정책을 확인합니다.
4. Swagger 상단의 Server 값이 `http://127.0.0.1:8002`인지 확인합니다.

로컬 `8002` 포트가 이미 사용 중이면 왼쪽 포트만 다른 값으로 바꿀 수 있습니다.

```bash
ssh -L 18002:127.0.0.1:8002 USER@SERVER_HOST
```

이 경우 Swagger 접속 주소는 `http://127.0.0.1:18002/docs`가 됩니다.

## 2. 운영 Swagger 접속

브라우저에서 다음 주소를 엽니다.

```text
https://ai.idq.co.kr/gaim/docs
```

Swagger 상단의 Server 값이 `https://ai.idq.co.kr/gaim`인지 확인합니다. 운영 URL은 `/gaim` prefix를 포함해야 하며, 이를 제외하면 API 호출과 생성 이미지 조회에서 `404 Not Found`가 발생할 수 있습니다.

## 3. Swagger에서 요청 헤더 입력

이미지 endpoint를 펼치고 **Try it out**을 누른 다음 `X-Internal-Token` 입력란에 발급받은 내부 토큰(현재 change-this-internal-token)을 입력합니다.

```http
X-Internal-Token: {발급받은 내부 토큰}
Content-Type: application/json
```

토큰이 없으면 `422 Unprocessable Entity`, 토큰이 일치하지 않으면 `401 Unauthorized`가 반환됩니다.

## 4. 동기 이미지 생성 테스트

동기 테스트는 아래 endpoint를 사용합니다.

```http
POST /v1/image/provider-generate
```

이 endpoint는 Swagger 테스트용/비운영 API입니다. provider 호출이 끝날 때까지 기다린 후 최종 이미지 URL을 응답하므로 이미지 생성과 파일 접근을 빠르게 확인할 때 적합합니다.

### Google 예제

```json
{
  "provider": "google",
  "model": "gemini-2.5-flash-image",
  "prompt": "나무가 울창한 호숫가에 위치한 따뜻한 분위기의 카페 광고 이미지",
  "size": "auto",
  "quality": "auto",
  "output_format": "png",
  "background": "auto",
  "style": "vivid",
  "n": 1
}
```

### OpenAI 예제

```json
{
  "provider": "openai",
  "model": "gpt-image-2",
  "prompt": "과일 가게 할인 행사 홍보 이미지를 만들고 이미지 하단에 문구를 선명하게 넣어줘",
  "text_to_render": "오늘 딸기 30% 할인",
  "size": "1024x1024",
  "quality": "low",
  "output_format": "png",
  "background": "auto",
  "style": "vivid",
  "n": 1
}
```

**Execute**를 누른 뒤 `200` 응답에서 다음 필드를 확인합니다.

```json
{
  "images": [
    "http://127.0.0.1:8002/gaim/generated/images/xxxxxxxx.png"
  ],
  "model_used": "gemini-2.5-flash-image",
  "provider": "google"
}
```

- `images`: 생성된 이미지의 공개 URL 목록
- `model_used`: 실제로 사용된 모델
- `provider`: 실제로 사용된 provider

`AI_PROVIDER_MODE=mock` 환경에서도 테스트용 PNG가 저장되고 URL이 반환되며, 실제 AI 생성 결과를 확인하려면 live provider 설정과 API 인증 정보가 필요합니다.

## 5. 비동기 이미지 Job 테스트

비동기 운영 흐름은 아래 endpoint를 사용합니다.

```http
POST /v1/image/jobs
```

이 흐름을 끝까지 확인하려면 API 서버 외에 Redis, Celery image worker, callback을 받을 WAS가 모두 실행 중이어야 합니다. ai-engine의 Swagger에는 이미지 Job 최종 상태 조회 endpoint가 없으므로, 등록 후 최종 결과는 WAS 상태 API에서 확인합니다.

Swagger에서 매 요청마다 새로운 `jobId`를 넣고 실행합니다. 실행 중인 프로세스에서 이미 등록한 `jobId`를 다시 사용하면 새 이미지 작업이 enqueue되지 않습니다.

```json
{
  "jobId": "swagger-image-test-20260825-001",
  "purpose": "홍보",
  "visual_mood": "warm_cozy",
  "channels": ["instagram"],
  "image_prompt": "따뜻한 조명의 카페 테이블 위에 대표 메뉴가 정갈하게 놓인 광고 이미지",
  "n": 1
}
```

정상 등록 응답은 최종 이미지가 아니라 queued 상태입니다.

```json
{
  "jobId": "swagger-image-test-20260825-001",
  "status": "queued",
  "message": "이미지 생성 작업이 큐에 등록되었습니다."
}
```

WAS의 상태 조회 API를 polling합니다.

```http
GET {WAS_BASE_URL}/api/ai/image/async/job/{jobId}
```

예:

```bash
curl "http://127.0.0.1:8080/api/ai/image/async/job/swagger-image-test-20260825-001"
```

`status`가 `completed`가 되면 `images`에 최종 이미지 URL이 들어옵니다.

```json
{
  "jobId": "swagger-image-test-20260825-001",
  "status": "completed",
  "images": [
    "http://127.0.0.1:8002/gaim/generated/images/xxxxxxxx.png"
  ],
  "modelUsed": "gemini-2.5-flash-image",
  "provider": "google",
  "error": null,
  "progressPct": 100
}
```

`failed` 상태이면 `error`를 확인하고 ai-engine API, Celery worker, WAS callback 로그를 함께 확인합니다.

## 6. 생성 이미지 확인

### 응답 URL로 확인

동기 응답 또는 비동기 완료 응답의 `images` 배열에서 파일명을 확인합니다. 생성 이미지는 SSH 터널을 연결한 상태에서 다음 주소를 브라우저 새 탭으로 열어 확인합니다.

```text
http://127.0.0.1:8002/gaim/generated/images/{파일명}
```

Swagger에서 생성한 이미지도 SSH 터널을 연결한 뒤 `127.0.0.1` 주소로 확인합니다.

```text
http://127.0.0.1:8002/gaim/generated/images/{파일명}
```

응답 URL의 host가 다르면 `{파일명}`은 유지하고 위의 `127.0.0.1` 형식으로 바꿔서 확인합니다. 반환 URL은 서버의 `STORAGE_PUBLIC_BASE_URL` 설정으로 만들어집니다.

예를 들어 응답이 다음과 같다면:

```text
http://127.0.0.1:8002/gaim/generated/images/abc123.png
```

SSH 터널로 확인할 때도 `/gaim` prefix를 포함한 다음 주소를 사용합니다.

```text
http://127.0.0.1:8002/gaim/generated/images/abc123.png
```

### 서버 파일시스템에서 확인

로컬 storage backend를 사용하는 경우 생성 파일은 서버의 다음 위치에 저장됩니다.

```text
{STORAGE_BASE_DIR}/images/{파일명}
```

실제 디렉터리는 서버의 `STORAGE_BASE_DIR` 환경변수 값을 기준으로 확인합니다. 기본 실행 구성에서는 저장 디렉터리가 프로젝트 외부 또는 `storage-data`로 지정될 수 있으므로 특정 절대 경로를 가정하지 않습니다.

## 7. 문제 해결

### Swagger 접속 실패

- 로컬 접속이면 SSH 터널 세션이 유지되고 있는지 확인합니다.
- 원격 서버에서 ai-engine이 `8002` 포트를 수신 중인지 확인합니다.
- 로컬 포트 충돌이 있으면 `18002` 등 다른 포트로 터널링합니다.
- 운영 접속이면 URL에 `/gaim/docs`가 포함되어 있는지 확인합니다.

### Execute 결과가 401 또는 422

- `X-Internal-Token`을 입력했는지 확인합니다.
- 입력한 값이 서버의 `WAS_INTERNAL_TOKEN`과 일치하는지 관리자에게 확인합니다.

### 이미지 URL이 404

- SSH 터널이 연결되어 있는지 확인합니다.
- 이미지 주소가 `http://127.0.0.1:8002/gaim/generated/images/{파일명}` 형식인지 확인합니다.
- 운영 도메인의 `https://ai.idq.co.kr/gaim/generated/images/{파일명}` 경로에서는 이미지를 확인할 수 없습니다.
- `STORAGE_PUBLIC_BASE_URL`과 실제 reverse proxy 경로가 일치하는지 확인합니다.
- `{STORAGE_BASE_DIR}/images/{파일명}`에 파일이 실제로 생성되었는지 확인합니다.

### 비동기 Job이 queued에서 진행되지 않음

- Redis와 Celery image worker가 실행 중인지 확인합니다.
- worker가 `image-queue`를 소비하는지 확인합니다.
- ai-engine과 worker가 동일한 broker 설정을 사용하는지 확인합니다.
- callback 대상 `WAS_BASE_URL`과 WAS 상태 저장 기능이 정상인지 확인합니다.

## 8. 영상 참조 이미지 테스트

ai-engine Swagger에서 영상 생성 API를 테스트할 때도 참조 이미지를 넣을 수 있습니다.

현재 활성 API인 `POST /v1/video/jobs`는 `multipart/form-data` 파일 업로드가 아니라 JSON body를 받습니다. 따라서 Swagger에서 이미지 파일 선택 버튼은 나오지 않습니다. 이미지는 아래 둘 중 하나로 전달합니다.

- `bytesBase64Encoded`: 이미지 파일을 base64 문자열로 변환해서 전달
- `gcsUri`: provider가 접근 가능한 이미지 URI 전달

frontend도 로컬 파일을 browser에서 base64로 읽어 `bytesBase64Encoded`로 전달합니다.

### Swagger 접속

```text
http://127.0.0.1:8002/docs
```

테스트 대상 endpoint:

```http
POST /v1/video/jobs
X-Internal-Token: {발급받은 내부 토큰}
Content-Type: application/json
```

### base64 만들기

터미널에서 이미지 파일을 base64 문자열로 변환합니다.

```bash
base64 -i /path/to/image.png | tr -d '\n'
```

출력된 긴 문자열을 JSON의 `BASE64_IMAGE_BYTES` 자리에 붙입니다.

주의:

- `bytesBase64Encoded`에는 `data:image/png;base64,` prefix를 붙이지 않습니다.
- `mimeType`은 `image/png` 또는 `image/jpeg`만 사용합니다.
- 너무 큰 이미지는 Swagger 입력/요청 처리에 부담이 될 수 있으므로 테스트용 이미지는 작게 줄여 사용합니다.

### Image to Video 테스트

시작 프레임 1장을 사용해 영상을 생성합니다.

```json
{
  "jobId": "swagger-image-test-1",
  "prompt": "이 이미지를 시작 프레임으로 자연스럽게 움직이는 숏폼 광고 생성. Cheerful Korean female narrator says: \"사랑스런 감자밭 카페에 오세요.\" Soft acoustic background music and gentle cafe ambience.",
  "model": "fast",
  "platform": "instagram_reels",
  "task": "imageToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_IMAGE_BYTES",
      "mimeType": "image/png"
    }
  },
  "advanced": {
    "generateAudio": true
  },
  "metadata": {
    "source": "swagger-image-to-video-test"
  }
}
```

마지막 프레임도 함께 지정하려면 `lastFrame`을 추가합니다.

```json
{
  "jobId": "swagger-image-frame-test-1",
  "prompt": "첫 프레임에서 마지막 프레임으로 자연스럽게 이어지는 짧은 광고 영상 생성. Soft acoustic background music.",
  "model": "fast",
  "platform": "instagram_reels",
  "task": "imageToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 4,
  "input": {
    "image": {
      "bytesBase64Encoded": "BASE64_START_FRAME_BYTES",
      "mimeType": "image/png"
    },
    "lastFrame": {
      "bytesBase64Encoded": "BASE64_END_FRAME_BYTES",
      "mimeType": "image/png"
    }
  },
  "advanced": {
    "generateAudio": true
  }
}
```

`lastFrame`은 선택입니다. `lastFrame`은 `input.image`가 있을 때만 보낼 수 있습니다.

### Reference to Video 테스트

레퍼런스 이미지 1~3장을 사용해 영상을 생성합니다.

`referenceToVideo`는 Veo reference image 조합 안정성을 위해 `model=standard`, `durationSeconds=8` 사용을 권장합니다. frontend는 스타일 레퍼런스 선택 시 이 값을 자동 보정하며, ai-engine도 방어적으로 standard/8초로 정규화합니다.

```json
{
  "jobId": "swagger-reference-test-1",
  "prompt": "레퍼런스 이미지를 참고해서 제품 중심 숏폼 광고 생성. Cheerful Korean female narrator says: \"사랑스런 감자밭 카페에 오세요.\" Soft acoustic background music.",
  "model": "standard",
  "platform": "instagram_reels",
  "task": "referenceToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "input": {
    "referenceImages": [
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_BYTES",
        "mimeType": "image/png"
      }
    ]
  },
  "advanced": {
    "generateAudio": true
  },
  "metadata": {
    "source": "swagger-reference-to-video-test"
  }
}
```

여러 장을 넣는 예:

```json
{
  "jobId": "swagger-reference-multi-test-1",
  "prompt": "여러 레퍼런스 이미지를 참고해서 매장과 제품 분위기를 살린 숏폼 광고 생성. Soft acoustic background music.",
  "model": "standard",
  "platform": "instagram_reels",
  "task": "referenceToVideo",
  "aspectRatio": "9:16",
  "durationSeconds": 8,
  "input": {
    "referenceImages": [
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_1",
        "mimeType": "image/png"
      },
      {
        "bytesBase64Encoded": "BASE64_REFERENCE_IMAGE_2",
        "mimeType": "image/jpeg"
      }
    ]
  },
  "advanced": {
    "generateAudio": true
  }
}
```

규칙:

- `referenceImages`는 1~3장입니다.
- `referenceImages`는 `image` 또는 `lastFrame`과 같이 보낼 수 없습니다.
- `referenceToVideo`는 `input.referenceImages`가 반드시 필요합니다.

### gcsUri 방식

스키마상 `gcsUri`도 사용할 수 있습니다.

```json
{
  "input": {
    "image": {
      "gcsUri": "gs://gaim-generated-assets/video-shorts/start-frame.png",
      "mimeType": "image/png"
    }
  }
}
```

주의:

- Google/Veo 경로에서는 GCS URI를 사용할 수 있습니다.
- Runway fallback은 `gs://` URI를 직접 읽을 수 없습니다.
- Runway 직접 테스트 또는 Runway fallback까지 고려하면 `bytesBase64Encoded` 또는 공개 접근 가능한 `https://` 이미지 URL을 사용합니다.

### 결과 확인

요청이 성공하면 즉시 queued 응답이 옵니다.

```json
{
  "jobId": "swagger-reference-test-1",
  "status": "queued",
  "message": "숏폼 영상 생성이 시작되었습니다. task=referenceToVideo"
}
```

상태 확인:

```http
GET /v1/video/status/{jobId}
X-Internal-Token: {발급받은 내부 토큰}
```

WAS 경유 상태 확인:

```http
GET /api/ai/video/async/job/{jobId}
```

완료 응답에서 실제 사용 모델을 확인합니다.

```json
{
  "provider": "google",
  "modelUsed": "veo-3.1-generate-001",
  "fallbackUsed": false,
  "warnings": []
}
```

Runway fallback이면 아래처럼 보일 수 있습니다.

```json
{
  "provider": "runway",
  "modelUsed": "gen4_turbo",
  "fallbackUsed": true,
  "warnings": [
    "Rank 1 google/veo-3.1-fast-generate-001 failed: provider request failed"
  ]
}
```

Runway fallback 결과는 현재 별도 오디오 합성 없이 무음으로 취급합니다.

### 자주 발생하는 오류

#### 422 Validation Error

주요 원인:

- `task=imageToVideo`인데 `input.image`가 없음
- `task=referenceToVideo`인데 `input.referenceImages`가 없음
- `task=textToVideo`인데 `input.image` 또는 `referenceImages`를 보냄
- `referenceImages`와 `image` 또는 `lastFrame`을 같이 보냄
- `gcsUri`와 `bytesBase64Encoded`를 동시에 보냄
- `mimeType`이 `image/png`, `image/jpeg`가 아님

#### base64 decode 실패

주요 원인:

- `data:image/png;base64,` prefix를 붙임
- 줄바꿈이 포함됨
- 복사 중 문자열 일부가 잘림

base64는 아래처럼 줄바꿈 없이 만듭니다.

```bash
base64 -i /path/to/image.png | tr -d '\n'
```

#### Runway fallback으로 생성됨

`fallbackUsed=true`이면 Google/Veo 후보가 실패하고 Runway로 넘어간 것입니다. `warnings`에서 Google/Veo 실패 이유를 먼저 확인합니다.

오디오가 필요한 테스트라면 `provider=google`, `modelUsed=veo-3.1-*`, `fallbackUsed=false`인지 확인합니다.
