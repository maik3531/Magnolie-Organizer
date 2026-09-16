"""Exercise the standalone archive command on synthetic files, never rpmbuild."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "werkzeuge/source_selection.py"


def test_standalone_source_archive_allowlist(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("web/index.html", "pruefungen/fixtures/schema.sql", ".private-testing/person.json",
                 "an-claude.md", "--checkpoint=1", "line\nbreak.txt"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SYNTHETIC NON-SECRET INPUT")
    (source / "werkzeuge").mkdir()
    shutil.copyfile(SELECTOR, source / "werkzeuge/source_selection.py")
    listing = tmp_path / "list"
    with listing.open("wb") as output:
        subprocess.run([sys.executable, "-B", str(SELECTOR), str(source)], stdout=output, check=True)
    script = (ROOT / "werkzeuge/rpm_bauen.sh").read_text()
    command = script[script.index("tar --sort=name"):script.index("\n\nsed ")]
    archive = tmp_path / "synthetic.tar.xz"
    env = dict(os.environ, WURZEL=str(source), NAME="synthetic", FASSUNG="9.8.7", EPOCH="1700000000",
               QUELLLISTE=str(listing), ARCHIV=str(archive))
    subprocess.run(["sh", "-eu", "-c", command], env=env, check=True)
    with tarfile.open(archive) as content:
        assert set(content.getnames()) == {"synthetic-9.8.7/" + name for name in (
            "web/index.html", "pruefungen/fixtures/schema.sql", "--checkpoint=1", "line\nbreak.txt",
            "werkzeuge/source_selection.py")}
        assert all(item.isfile() for item in content.getmembers())
        extracted = tmp_path / "standalone-selector.py"
        extracted.write_bytes(content.extractfile("synthetic-9.8.7/werkzeuge/source_selection.py").read())
    result = subprocess.run([sys.executable, "-I", "-B", str(extracted), str(source)], capture_output=True, check=True)
    assert result.stdout == listing.read_bytes()


@pytest.mark.parametrize("name", ["synthetic.token", "synthetic.pem", "build-config.json", "link.txt"])
def test_unsafe_input_aborts_before_emitting_allowlist(tmp_path, name):
    (tmp_path / "safe.txt").write_text("synthetic")
    path = tmp_path / name
    if name == "link.txt":
        path.symlink_to(tmp_path / "safe.txt")
    else:
        path.write_text("SYNTHETIC NON-CREDENTIAL")
    result = subprocess.run([sys.executable, "-B", str(SELECTOR), str(tmp_path)], capture_output=True)
    assert result.returncode != 0 and result.stdout == b""


def test_selector_is_self_contained_and_packaged():
    spec = importlib.util.spec_from_file_location("handbook_source_selection", SELECTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SECRET.search("synthetic.token")
    # The selector has no sibling-project import and is an ordinary source file.
    assert SELECTOR.suffix == ".py" and not module.ARCHIVE.search(SELECTOR.name)
