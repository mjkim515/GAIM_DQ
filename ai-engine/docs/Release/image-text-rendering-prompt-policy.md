# 이미지 텍스트 렌더링 프롬프트 정책

## 배경

현재 서비스에서는 GPT Image 2만 한국어 텍스트 렌더링을 안정적으로 처리할 수 있는 이미지 생성 모델로 본다. 다른 이미지 생성 모델도 시각 품질은 좋을 수 있지만, 이미지 안에 한국어가 들어가면 오탈자, 왜곡, 의미 없는 유사 한글 글리프가 생성될 수 있다.

이 문제는 `text_to_render` 또는 `text_rendering`이 없는 요청에서도 발생할 수 있다. 사용자 프롬프트가 매장 이벤트, 행사, 메뉴, 포스터, 라벨, 패키지, 매장 입구 장면처럼 텍스트가 자연스럽게 등장할 수 있는 상황을 묘사하면, 일부 모델이 임의로 간판이나 배너 문구를 만들어 넣기 때문이다.

문제를 재현할 수 있는 테스트 프롬프트:

```text
봄맞이 이벤트가 열리는 매장 앞에서 사람들이 즐겁게 입장하는 모습, 밝은 햇살, 활기찬 분위기, 자연스러운 실사
```

비-GPT Image 2 모델에서는 위 요청에 명시적인 텍스트 입력이 없어도 이미지 안의 간판, 배너, 포스터 등에 `봄마잣이 축제` 같은 깨진 한국어가 생성될 수 있다.

## 라우팅 정책

### 텍스트 입력이 있는 경우

아래 필드 중 하나라도 있으면 텍스트 렌더링 요청으로 처리한다.

- `text_to_render`
- `text_rendering`

이 경우 이미지 생성은 `gpt-image-2`를 1순위로 라우팅한다. 프롬프트에는 사용자가 요청한 문구를 정확히 렌더링하라는 지시를 포함한다.

### 텍스트 입력이 없는 경우

`text_to_render`와 `text_rendering`이 모두 없으면 텍스트 없는 이미지 생성 요청으로 처리한다. 이 경우 Nano Banana 같은 비-GPT Image 2 모델을 사용할 수 있다.

목표는 이미지에 텍스트를 강제로 넣는 것이 아니다. 모델이 장면 맥락상 표시 요소를 임의로 만들 경우, 깨진 한국어 대신 짧은 영어만 사용하도록 제어하는 것이다.

## 프롬프트 정책

### GPT Image 2 + 텍스트 입력 있음

텍스트 입력이 있으면 아래와 같은 한국어 렌더링 지시를 포함한다.

```text
다음 문구를 이미지 안에 정확히 렌더링하세요: {text_to_render}.
```

`text_rendering`이 제공되면 언어, 배치, 폰트 힌트, 색상 힌트도 함께 반영한다.

### 비-GPT Image 2 + 텍스트 입력 없음

기존처럼 한국어로 “텍스트를 넣지 마세요”라는 금지 지시를 길게 넣지 않는다. 그런 방식은 `텍스트`, `한글`, `간판`, `로고`, `포스터`, `라벨`, `메뉴판` 같은 위험 단어를 프롬프트에 노출하고, 일부 이미지 모델이 이 단어를 시각 요소로 다시 끌어올 수 있기 때문이다.

대신 아래 영어 표시 정책을 추가한다.

```text
[Visible writing policy]
If visible words, signage, labels, menus, posters, banners, stickers, packaging text, or UI-like marks naturally appear in the scene, render them only as short, common English words. Korean writing must not appear. Avoid pseudo-Korean or unreadable Korean-like glyphs.
```

이 정책의 의미는 다음과 같다.

- 모델이 장면 안에 표지판, 메뉴, 포스터, 배너, 라벨, 패키지 텍스트 등을 자연스럽게 만들 수는 있다.
- 단, 그런 표시 요소가 생긴다면 짧고 일반적인 영어 단어만 사용해야 한다.
- 한국어는 이미지 안에 나타나면 안 된다.
- 깨진 한글처럼 보이는 유사 한글 글리프도 피해야 한다.

이 방식은 표시 요소를 완전히 금지하는 것보다 현실적이다. 매장, 행사, 거리, 상품 장면에서는 모델이 간판이나 포스터를 자연스럽게 만들 수 있기 때문에, 이를 전부 막으려 하기보다 한국어 깨짐을 피하도록 영어로 유도한다.

## 구현 위치

주요 구현 파일:

- `ai-engine/app/services/image/model_router.py`

관련 함수:

- `build_image_routing_plan()`
- `_build_text_free_image_prompt()`
- `_text_free_visible_writing_policy()`
- `apply_text_free_provider_policy()`
- `apply_text_free_reference_provider_policy()`
- `_build_prompt()` - intent 기반 레거시 경로

직접 provider 호출 API에도 같은 정책을 적용한다.

관련 파일:

- `ai-engine/app/api/v1/image.py`

관련 엔드포인트:

- `/v1/image/provider-generate`
- `/v1/image/provider-generate-with-reference`

## 테스트 가이드

아래 프롬프트로 문제와 완화 동작을 확인할 수 있다.

```text
봄맞이 이벤트가 열리는 매장 앞에서 사람들이 즐겁게 입장하는 모습, 밝은 햇살, 활기찬 분위기, 자연스러운 실사
```

`text_to_render`와 `text_rendering`이 없는 경우 기대되는 provider prompt 동작:

- 선택 모델은 `gemini-2.5-flash-image`일 수 있다.
- 프롬프트에 `[Visible writing policy]`가 포함된다.
- 프롬프트에 `Korean writing must not appear`가 포함된다.
- 프롬프트에 `[텍스트 처리]`는 포함되지 않는다.
- 프롬프트에 한국어 정확 렌더링 지시는 포함되지 않는다.

기대되는 이미지 동작:

- 자연스러운 매장 입구 장면을 우선한다.
- 모델이 표지판, 포스터, 메뉴, 라벨 같은 표시 요소를 추가한다면 짧은 영어로 표현한다.
- 깨진 한국어 또는 유사 한글 글리프는 피한다.

`text_to_render` 또는 `text_rendering`이 있는 경우 기대 동작:

- `gpt-image-2`로 라우팅한다.
- 사용자가 입력한 한국어 문구를 정확히 렌더링하도록 지시한다.
- 요청된 한국어 문구를 영어로 바꾸지 않는다.
