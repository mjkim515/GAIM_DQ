#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_DIR.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

sys.path.insert(0, str(ROOT))

from app.storage.local_cleanup import cleanup_local_storage


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean old generated local image/video files.")
    parser.add_argument("--base-dir", type=Path, default=None, help="Local storage base directory")
    parser.add_argument("--retention-seconds", type=int, default=None, help="Keep files newer than this many seconds")
    parser.add_argument("--delete", action="store_true", help="Delete files. Omit for dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = cleanup_local_storage(
        base_dir=args.base_dir,
        retention_seconds=args.retention_seconds,
        dry_run=not args.delete,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
