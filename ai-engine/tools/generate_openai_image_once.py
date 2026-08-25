from __future__ import annotations

import base64
import os
from datetime import datetime
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
OUTPUT_DIR = ROOT.parent / "storage-data"
PROMPT = "신선한 과일을 판매하는 상점이미지를 만들어봐"
SIZE = "1024x1024"
MODELS = ["gpt-image-2", "gpt-image-1.5", "gpt-image-1"]


def load_openai_key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()

    raise RuntimeError("OPENAI_API_KEY is not set")


def main() -> None:
    api_key = load_openai_key()
    client = OpenAI(api_key=api_key)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for model in MODELS:
        try:
            response = client.images.generate(
                model=model,
                prompt=PROMPT,
                size=SIZE,
                quality="low",
                n=1,
            )
            image_b64 = response.data[0].b64_json
            if not image_b64:
                raise RuntimeError(f"{model} returned no b64_json image data")
            image_bytes = base64.b64decode(image_b64)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = OUTPUT_DIR / f"fresh-fruit-store-{timestamp}.png"
            output_path.write_bytes(image_bytes)
            print(f"model={model}")
            print(f"size={SIZE}")
            print(f"path={output_path}")
            print(f"bytes={len(image_bytes)}")
            return
        except Exception as exc:
            last_error = exc
            print(f"model={model} failed: {exc}")

    raise RuntimeError("All GPT Image generation attempts failed") from last_error


if __name__ == "__main__":
    main()
