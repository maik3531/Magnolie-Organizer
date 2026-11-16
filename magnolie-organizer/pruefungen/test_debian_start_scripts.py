"""#685: manifest and actual payload checks must cover the real entry point."""
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "web_startskripte_pruefen", ROOT / "werkzeuge/web_startskripte_pruefen.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_debian_manifest_contains_every_real_start_script():
    assert checker.pruefen(ROOT / "web", ROOT / "debian/install") > 0


def test_actual_payload_requires_every_script(tmp_path):
    (tmp_path / "index.html").write_text('<script src="appearance.js"></script>')
    with pytest.raises(FileNotFoundError):
        checker.pruefen(tmp_path)
    (tmp_path / "appearance.js").write_text("// synthetic packaged script")
    assert checker.pruefen(tmp_path) == 1


def test_missing_manifest_entry_is_rejected(tmp_path):
    manifest = tmp_path / "install"
    manifest.write_text("web/index.html usr/share/magnolie-organizer/web\n")
    with pytest.raises(ValueError, match="missing from Debian manifest"):
        checker.pruefen(ROOT / "web", manifest)


@pytest.mark.parametrize("name", ("../private.js", "https://example.invalid/a.js",
                                 "/outside.js", "%61.js", "a.js?query", "a.js#fragment"))
def test_nonlocal_or_ambiguous_script_rejected(tmp_path, name):
    (tmp_path / "index.html").write_text('<script src="' + name + '"></script>')
    with pytest.raises(ValueError, match="Invalid entry-point"):
        checker.pruefen(tmp_path)


def test_payload_symlink_escape_rejected(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<script src="outside.js"></script>')
    outside = tmp_path / "outside.js"
    outside.write_text("// not in payload root")
    (web / "outside.js").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes package web root"):
        checker.pruefen(web)


def test_generated_active_catalog_requires_packaged_backing_file(tmp_path):
    (tmp_path / "index.html").write_text('<script src="i18n-active.js"></script>')
    with pytest.raises(FileNotFoundError):
        checker.pruefen(tmp_path)
    (tmp_path / "i18n-en.js").write_text("// backing catalog")
    assert checker.pruefen(tmp_path) == 1
