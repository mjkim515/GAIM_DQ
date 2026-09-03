# Veo 3.1 오디오 설정 가이드

## 요약

Veo 3.1에서 오디오는 별도 오디오 파일을 업로드해서 합성하는 방식이 아니라, `generateAudio` 파라미터를 켜고 프롬프트 안에 오디오 연출을 명확히 작성하는 방식으로 제어한다.

현재 G-AIM 숏폼 생성 화면의 `BGM/효과음 생성` 토글은 이 구조와 맞다. 다만 BGM 분위기, 효과음, 앰비언스, 대사 여부 같은 세부 옵션은 별도 API 파라미터가 아니라 최종 Veo 프롬프트에 문장으로 포함해야 한다.

## API 파라미터

Veo 3 계열에서 오디오 생성은 `generateAudio` boolean으로 제어한다.

```json
{
  "parameters": {
    "durationSeconds": 8,
    "aspectRatio": "9:16",
    "resolution": "720p",
    "generateAudio": true
  }
}
```

값의 의미는 다음과 같다.

- `true`: 영상과 함께 오디오를 생성한다.
- `false`: 무음 영상으로 생성한다.

공식 문서 기준으로 `generateAudio`는 Veo 3 모델에서 `true` 또는 `false`를 받는 오디오 생성 옵션이다. BGM 장르, 볼륨, 효과음 강도, 보이스오버 음색 같은 세부 파라미터는 제공되지 않는다.

참고: [Veo on Vertex AI video generation API](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/veo-video-generation?hl=en)

## 오디오를 인식시키는 방식

Veo가 오디오 의도를 잘 인식하게 하려면 오디오 지시문을 프롬프트 안에서 별도 문장으로 분리한다.

권장 구조:

```text
Visual: A close-up vertical video of a fresh strawberry cake being placed on a cafe table, warm natural light, slow camera push-in.

Audio: Soft upbeat acoustic pop music in the background. Gentle cafe ambience, quiet plate sound as the cake touches the table. No dialogue.
```

오디오 지시문에는 다음 요소를 명확히 넣는 것이 좋다.

- BGM: 음악 장르, 분위기, 속도
- Sound effects: 장면 안에서 발생하는 개별 효과음
- Ambient noise: 장소감을 주는 배경 소리
- Dialogue 또는 voiceover: 사람이 말하는 문장, 톤, 화자
- Exclusion: 원하지 않는 오디오, 예를 들어 `No dialogue`, `No voiceover`

공식 프롬프트 가이드도 오디오 설명을 별도 문장으로 작성하는 방식을 권장한다.

참고: [Veo video generation prompt guide](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide?hl=en)

## 예시

### BGM과 효과음만 있는 숏폼

```text
Visual: A vertical short-form ad showing a barista pouring latte art in a cozy cafe, warm morning sunlight, smooth slow camera push-in.

Audio: Soft upbeat acoustic background music. Gentle espresso machine hiss, light cup clink, and quiet cafe ambience. No dialogue or voiceover.
```

### 매장 분위기를 살리는 앰비언스

```text
Visual: A vertical video of fresh bread coming out of the oven in a small local bakery, warm golden lighting, close-up shot.

Audio: Warm and cozy background music. Subtle bakery ambience, oven door sound, soft tray movement, and faint morning street noise outside. No dialogue.
```

### 내레이션 포함

```text
Visual: A cheerful bakery owner presents a fresh croissant to the camera in a bright local bakery.

Audio: Light morning cafe ambience with soft background music. A friendly voiceover says: Freshly baked croissants are ready this morning.
```

### 인물 대사 포함

```text
Visual: A medium shot of a cafe owner smiling behind the counter and handing a drink to a customer.

Audio: Gentle cafe ambience and soft background music. The cafe owner says: Your iced latte is ready.
```

## 대사 작성 규칙

대사나 내레이션을 넣을 때는 따옴표를 피하고 `says:` 또는 `voiceover says:` 뒤에 바로 문장을 쓴다.

권장:

```text
The owner says: Freshly baked croissants are ready this morning.
```

비권장:

```text
The owner says: "Freshly baked croissants are ready this morning."
```

따옴표를 쓰면 모델이 대사를 영상 안의 텍스트처럼 렌더링하려고 할 수 있다.

참고: [Best practices for Veo on Vertex AI](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/best-practice)

## G-AIM 적용 방향

현재 프론트엔드에서는 `Shortform.jsx`가 `generateAudio` boolean을 payload의 `advanced.generateAudio`로 전달한다.

현재 가능한 설정:

- `generateAudio: true`: BGM/효과음 생성
- `generateAudio: false`: 무음 영상 생성

세부 오디오 옵션을 추가하려면 UI에서 선택한 값을 최종 프롬프트에 합쳐 보내는 방식이 가장 현실적이다.

예시 UI 옵션:

- 오디오 없음
- 자동 BGM
- BGM + 효과음
- 매장 앰비언스
- 보이스오버 포함

전송 전 변환 예시:

```text
Audio: Bright, friendly background music suitable for a short social media ad. Add subtle cafe ambience and gentle product handling sound effects. No dialogue or voiceover.
```

이 방식은 현재 백엔드 스키마를 크게 바꾸지 않고도 적용할 수 있다. 프론트엔드에서 사용자의 선택을 `audioPrompt` 문자열로 만들고, 영상 생성 요청 직전에 기존 프롬프트 뒤에 붙이면 된다.

## 구현 시 권장 정책

1. 사용자가 오디오를 끄면 `generateAudio: false`만 보낸다.
2. 사용자가 오디오를 켜면 `generateAudio: true`를 보낸다.
3. 오디오 세부 설정은 영어 문장으로 변환해 최종 프롬프트에 붙인다.
4. 대사나 내레이션이 없는 기본값에는 `No dialogue or voiceover.`를 명시한다.
5. 한국어 UI를 유지하되, Veo로 보내는 최종 프롬프트의 오디오 지시문은 영어로 만드는 것을 권장한다.

## 현재 코드 기준 매핑

프론트엔드:

- `frontend/src/screens/contentCreation/Shortform.jsx`
- `generateAudio` 상태가 `advanced.generateAudio`로 전달된다.

백엔드:

- `ai-engine/app/schemas/video.py`
- `VideoShortAdvancedOverrides.generate_audio`가 `generateAudio` alias로 정의되어 있다.

Veo 요청 생성:

- `ai-engine/app/services/video/veo_service.py`
- `_build_video_short_generate_kwargs()`에서 `generateAudio=false`일 때만 `generate_audio=false`가 `GenerateVideosConfig`로 전달된다.
- `generateAudio=true` 또는 생략 시에는 `generate_audio` 필드를 provider config에 넣지 않고 Veo 3.1 모델 기본 오디오 동작에 맡긴다.

## 핵심 결론

Veo 3.1에서 오디오를 넣으려면 `generateAudio: true`를 켜고, 프롬프트에 오디오 연출을 명확히 작성해야 한다. ai-engine은 이 경우 `generate_audio=true`를 명시하지 않고 모델 기본 오디오 생성에 맡긴다. 구조화된 오디오 설정 파라미터는 없으므로, G-AIM에서 세부 오디오 옵션을 만들려면 UI 선택값을 프롬프트 문장으로 변환하는 방식이 가장 적합하다.
