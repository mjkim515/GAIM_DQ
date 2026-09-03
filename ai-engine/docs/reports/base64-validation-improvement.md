# Base64 입력 검증 개선 사항

## 배경

Spring Boot에서 `bytesBase64Encoded` 또는 `b64_json`에 실제 이미지 bytes를 Base64로 인코딩한 값이 아니라 `"BASE64_REFERENCE_IMAGE_BYTES"` 같은 예시 문자열을 그대로 전달하면 Python의 `base64.b64decode()`가 실패한다.

대표 에러:

```text
Invalid base64-encoded string: number of data characters (25) cannot be 1 more than a multiple of 4
```

이 문자열은 실제 이미지 데이터가 아니며, Base64 디코딩 대상이 될 수 없다.

## Spring Boot 요청 작성 기준

`bytesBase64Encoded`에는 순수 Base64 문자열만 넣어야 한다. `data:image/png;base64,` prefix나 placeholder 문자열을 넣지 않는다.

```java
byte[] imageBytes = Files.readAllBytes(Path.of("reference.png"));
String base64Image = Base64.getEncoder().encodeToString(imageBytes);

AiVideoShortMediaInputRequest referenceImage = new AiVideoShortMediaInputRequest(
        null,
        base64Image,
        "image/png"
);
```

## ai-engine 방어 개선

잘못된 Base64 입력이 provider 호출 단계에서 500 계열 오류로 터지지 않도록, ai-engine의 디코딩 경계에서 검증한다.

적용 지점:

- `app/services/base64_utils.py`: 공통 Base64 디코딩 및 검증 유틸
- `app/services/image/references.py`: 이미지 생성/편집 `reference_images[].b64_json` 디코딩
- `app/services/image/create_service.py`: 이미지 생성 요청의 Base64 참조 이미지 사전 검증
- `app/services/video/veo_service.py`: 영상 생성 `bytesBase64Encoded` 사전 검증 및 provider 전달 전 디코딩

처리 내용:

- 값이 비어 있으면 `RequestValidationError`
- `data:*;base64,` prefix가 붙어 있으면 payload 부분만 사용
- Base64 길이와 문자셋을 검증
- 디코딩 결과가 empty bytes이면 `RequestValidationError`

기대 응답:

```json
{
  "code": "REQUEST_VALIDATION_ERROR",
  "message": "input.referenceImages[0].bytesBase64Encoded must be valid base64-encoded bytes"
}
```

HTTP status는 `400 Bad Request`이다.
