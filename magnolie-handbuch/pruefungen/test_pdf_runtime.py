"""Locked build-time dependency preparation must fail closed and retain licenses."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

source = Path(__file__).resolve().parents[1] / "werkzeuge/pdf_runtime.py"
spec = importlib.util.spec_from_file_location("handbook_pdf_runtime", source)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def fixture(tmp_path, entries):
    cache = tmp_path / "cache"
    cache.mkdir()
    wheel = cache / "synthetic-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"schema": 1, "packages": [{"name": "synthetic", "version": "1",
        "filename": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}]}))
    return lock, cache, tmp_path / "runtime"


def test_offline_preparation_records_original_files_and_includes_license(tmp_path, monkeypatch):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1\n"),
        ("synthetic-1.dist-info/licenses/LICENSE", "Synthetic test license\n")])
    monkeypatch.setattr(runtime, "_get", lambda *args: pytest.fail("An offline cached build must not use the network"))
    manifest = runtime.prepare(lock, cache, target, offline=True)
    assert (target / "synthetic/__init__.py").read_text() == "VALUE=1\n"
    assert manifest["packages"][0]["licenses"] == ["synthetic-1.dist-info/licenses/LICENSE"]
    assert manifest["files"]["synthetic/__init__.py"] == hashlib.sha256(b"VALUE=1\n").hexdigest()
    assert json.loads((target / "runtime-manifest.json").read_text()) == manifest


@pytest.mark.parametrize("entry", ["../escape.py", "/escape.py", "synthetic/native.so", "synthetic\\escape.py"])
def test_unsafe_or_native_entries_are_not_extracted(tmp_path, entry):
    lock, cache, target = fixture(tmp_path, [(entry, "bad"), ("synthetic-1.dist-info/LICENSE", "License")])
    with pytest.raises(ValueError, match="Non-pure or unsafe"):
        runtime.prepare(lock, cache, target, offline=True)
    assert not target.exists()
    assert not (tmp_path / "escape.py").exists()


def test_changed_cached_wheel_never_becomes_runtime_code(tmp_path):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1"), ("synthetic-1.dist-info/LICENSE", "License")])
    wheel = next(cache.iterdir())
    wheel.write_bytes(wheel.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="differs from the lock"):
        runtime.prepare(lock, cache, target, offline=True)
    assert not target.exists()


def test_archive_symlink_is_rejected(tmp_path):
    link = zipfile.ZipInfo("synthetic/escape.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    lock, cache, target = fixture(tmp_path, [(link, "../../outside.py"), ("synthetic-1.dist-info/LICENSE", "License")])
    with pytest.raises(ValueError, match="Non-pure or unsafe"):
        runtime.prepare(lock, cache, target, offline=True)
    assert not target.exists()


def test_missing_license_is_not_silently_shipped(tmp_path):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1")])
    with pytest.raises(ValueError, match="no included license"):
        runtime.prepare(lock, cache, target, offline=True)
    assert not target.exists()


def test_existing_destination_is_preserved(tmp_path):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1"), ("synthetic-1.dist-info/LICENSE", "License")])
    target.mkdir()
    original = target / "owned.txt"
    original.write_text("preserve")
    with pytest.raises(ValueError, match="already exists"):
        runtime.prepare(lock, cache, target, offline=True)
    assert original.read_text() == "preserve"


def test_explicit_update_replaces_only_the_verified_generated_tree(tmp_path):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1"), ("synthetic-1.dist-info/LICENSE", "License")])
    before = runtime.prepare(lock, cache, target, offline=True)
    after = runtime.prepare(lock, cache, target, offline=True, update=True)
    assert before == after
    assert (target / "synthetic/__init__.py").read_text() == "VALUE=1"
    assert not list(tmp_path.glob(".pdf-runtime-*"))


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_update_preserves_additional_user_work(tmp_path, kind):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1"), ("synthetic-1.dist-info/LICENSE", "License")])
    runtime.prepare(lock, cache, target, offline=True)
    owned = target / "owned"
    if kind == "file":
        owned.write_text("preserve")
    else:
        owned.mkdir()
    with pytest.raises(ValueError, match="changed or additional"):
        runtime.prepare(lock, cache, target, offline=True, update=True)
    assert owned.exists()


def test_private_builder_umask_does_not_make_root_owned_runtime_unreadable(tmp_path):
    lock, cache, target = fixture(tmp_path, [("synthetic/__init__.py", "VALUE=1"), ("synthetic-1.dist-info/LICENSE", "License")])
    old_umask = os.umask(0o077)
    try:
        runtime.prepare(lock, cache, target, offline=True)
    finally:
        os.umask(old_umask)
    for path in (target, *target.rglob("*")):
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644)
