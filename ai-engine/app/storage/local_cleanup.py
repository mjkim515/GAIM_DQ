import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings

LOCAL_STORAGE_GENERATED_DIRS = ("images", "videos")


@dataclass
class LocalStorageCleanupResult:
    dry_run: bool
    base_dir: str
    retention_seconds: int
    scanned_files: int = 0
    deleted_files: int = 0
    delete_candidates: int = 0
    deleted_bytes: int = 0
    removed_empty_dirs: int = 0
    errors: list[str] = field(default_factory=list)


def cleanup_local_storage(
    *,
    base_dir: Path | None = None,
    retention_seconds: int | None = None,
    dry_run: bool = True,
    now: float | None = None,
) -> LocalStorageCleanupResult:
    settings = get_settings()
    raw_base_dir = base_dir or settings.storage_base_dir
    resolved_base_dir = raw_base_dir.resolve()
    retention = retention_seconds if retention_seconds is not None else settings.local_storage_retention_seconds
    cutoff = (now or time.time()) - retention
    result = LocalStorageCleanupResult(
        dry_run=dry_run,
        base_dir=str(resolved_base_dir),
        retention_seconds=retention,
    )

    if retention < 0:
        result.errors.append("retention_seconds must be greater than or equal to 0")
        return result
    if not resolved_base_dir.exists():
        return result
    if not resolved_base_dir.is_dir():
        result.errors.append(f"base_dir is not a directory: {resolved_base_dir}")
        return result

    for dirname in LOCAL_STORAGE_GENERATED_DIRS:
        target_dir = (resolved_base_dir / dirname).resolve()
        if not _is_relative_to(target_dir, resolved_base_dir) or not target_dir.exists():
            continue
        _cleanup_dir(target_dir, resolved_base_dir, cutoff, dry_run, result)

    if not dry_run:
        _remove_empty_dirs(resolved_base_dir, result)
    return result


def _cleanup_dir(
    target_dir: Path,
    base_dir: Path,
    cutoff: float,
    dry_run: bool,
    result: LocalStorageCleanupResult,
) -> None:
    for path in target_dir.rglob("*"):
        resolved_path = path.resolve()
        if not _is_relative_to(resolved_path, base_dir):
            result.errors.append(f"skipped path outside base_dir: {path}")
            continue
        if path.is_symlink() or not path.is_file():
            continue
        result.scanned_files += 1
        try:
            stat = path.stat()
        except OSError as exc:
            result.errors.append(f"stat failed for {path}: {exc}")
            continue
        if stat.st_mtime > cutoff:
            continue

        result.delete_candidates += 1
        result.deleted_bytes += stat.st_size
        if dry_run:
            continue
        try:
            path.unlink()
            result.deleted_files += 1
        except OSError as exc:
            result.errors.append(f"delete failed for {path}: {exc}")


def _remove_empty_dirs(base_dir: Path, result: LocalStorageCleanupResult) -> None:
    for dirname in LOCAL_STORAGE_GENERATED_DIRS:
        target_dir = base_dir / dirname
        if not target_dir.exists():
            continue
        for path in sorted(target_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if not path.is_dir() or path == base_dir:
                continue
            try:
                path.rmdir()
                result.removed_empty_dirs += 1
            except OSError:
                pass


def _is_relative_to(path: Path, base_dir: Path) -> bool:
    try:
        path.relative_to(base_dir)
        return True
    except ValueError:
        return False
