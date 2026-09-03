def test_local_storage_cleanup_dry_run_keeps_files(tmp_path):
    import os
    import time

    from app.storage.local_cleanup import cleanup_local_storage

    old_file = tmp_path / "images" / "old.png"
    recent_file = tmp_path / "videos" / "recent.mp4"
    old_file.parent.mkdir(parents=True)
    recent_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")
    now = time.time()
    os.utime(old_file, (now - 10_000, now - 10_000))
    os.utime(recent_file, (now, now))

    result = cleanup_local_storage(
        base_dir=tmp_path,
        retention_seconds=3600,
        dry_run=True,
        now=now,
    )

    assert result.scanned_files == 2
    assert result.delete_candidates == 1
    assert result.deleted_files == 0
    assert old_file.exists()
    assert recent_file.exists()

def test_local_storage_cleanup_deletes_old_files_and_empty_dirs(tmp_path):
    import os
    import time

    from app.storage.local_cleanup import cleanup_local_storage

    old_file = tmp_path / "images" / "nested" / "old.png"
    recent_file = tmp_path / "videos" / "recent.mp4"
    ignored_file = tmp_path / "manual.txt"
    old_file.parent.mkdir(parents=True)
    recent_file.parent.mkdir(parents=True)
    old_file.write_bytes(b"old")
    recent_file.write_bytes(b"recent")
    ignored_file.write_bytes(b"ignored")
    now = time.time()
    os.utime(old_file, (now - 10_000, now - 10_000))
    os.utime(recent_file, (now, now))
    os.utime(ignored_file, (now - 10_000, now - 10_000))

    result = cleanup_local_storage(
        base_dir=tmp_path,
        retention_seconds=3600,
        dry_run=False,
        now=now,
    )

    assert result.scanned_files == 2
    assert result.delete_candidates == 1
    assert result.deleted_files == 1
    assert result.deleted_bytes == 3
    assert result.removed_empty_dirs >= 1
    assert not old_file.exists()
    assert not old_file.parent.exists()
    assert recent_file.exists()
    assert ignored_file.exists()
