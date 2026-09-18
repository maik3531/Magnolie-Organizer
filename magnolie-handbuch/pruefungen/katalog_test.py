"""Source extraction, installed-prefix CLI and locale regressions.

Fixtures live in pytest's temporary directory, never in the web payload.
"""
import ast
import gettext
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
from katalog_pruefen import entries
from pot_erzeugen import handbook_data, handbook_messages, package_version


def test_effective_sources_are_in_template():
    template = entries((ROOT / "po/magnolie-handbuch.pot").read_text())
    assert set(handbook_messages()) <= template.keys()
    data = handbook_data()
    assert "starting-for-the-first-time" not in data["variants"]
    assert "platform-security-matrix" not in data["variants"]
    assert "appearance-sound-and-anniversaries" not in data["variants"]
    assert len(data["variants"]) == 15


def test_all_catalogs_cover_the_effective_source():
    template = entries((ROOT / "po/magnolie-handbuch.pot").read_text())
    problems = []
    for language in (ROOT / "po/LINGUAS").read_text().split():
        actual = entries((ROOT / "po" / (language + ".po")).read_text())
        assert actual.keys() == template.keys(), language
        missing = [key for key in template if not actual[key].strip()]
        if missing:
            problems.append(language + ": " + str(len(missing)) + " untranslated: " +
                            "; ".join(key[:95] for key in missing))
    assert not problems, "\n".join(problems)


def test_manual_setup_and_security_translations():
    data = handbook_data()
    for language in (ROOT / "po/LINGUAS").read_text().split():
        translation = gettext.translation("magnolie-handbuch", localedir=str(ROOT / "locale"), languages=[language])
        catalog = entries((ROOT / "po" / (language + ".po")).read_text())
        for page_id in ("first-run-assistant", "first-run-saved-intentions", "technical-update-trust", "starting-for-the-first-time"):
            page = next(page for page in data["pages"] if page["id"] == page_id)
            source = page["inhaltAnhang"]["en"] if page.get("inhaltAnhangErsetzt") else page["inhalt"]
            value = translation.gettext(source)
            assert value and value != source, (language, page_id)
            assert catalog[source] == value
            original = ET.fromstring("<div>" + source + "</div>")
            rendered = ET.fromstring("<div>" + value + "</div>")
            assert Counter(node.tag for node in original.iter()) == Counter(node.tag for node in rendered.iter())
            assert sorted(node.attrib.get("data-page") for node in original.iter() if "data-page" in node.attrib) == \
                sorted(node.attrib.get("data-page") for node in rendered.iter() if "data-page" in node.attrib)
            for token in ("Ed25519", "SHA-256", "Authenticode", "wttr.in", "Windows", "Linux", "APK", "Android", "LibreOffice", "KDE Connect", "Magnolie Notes"):
                assert value.count(token) == source.count(token), (language, page_id, token)


def test_chinese_posix_language(monkeypatch):
    source = ROOT / "bin/magnolie-handbuch"
    tree = ast.parse(source.read_text())
    selected = [node for node in tree.body if
                isinstance(node, ast.FunctionDef) and node.name in ("normalisiere_sprache", "web_sprache", "lade_uebersetzung") or
                isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
                    ("UNTERSTUETZTE_SPRACHEN", "TEXT_DOMAIN") for target in node.targets)]
    import locale
    namespace = dict(os=os, locale=locale, gettext=gettext, __file__=str(source), SPRACH_OVERRIDE=None)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    for code in ("zh_CN.UTF-8", "zh-CN.UTF-8@modifier", "zh_CN", "zh", "zh-SG"):
        monkeypatch.setenv("LANGUAGE", code)
        assert namespace["web_sprache"]() == "zh_CN"
    monkeypatch.setenv("LANGUAGE", "zh_CN.UTF-8")
    assert namespace["lade_uebersetzung"]().gettext("Contents") != "Contents"


def test_installed_pot_in_nonstandard_prefix(tmp_path):
    prefix = tmp_path / "installation"
    share = prefix / "share/magnolie-handbuch"
    (share / "web").mkdir(parents=True)
    (share / "werkzeuge").mkdir()
    (prefix / "bin").mkdir()
    private = prefix / "lib/magnolie-handbuch"
    private.mkdir(parents=True)
    for name in ("version.json", "handbuch.js", "i18n-markers.js"):
        shutil.copyfile(ROOT / "web" / name, share / "web" / name)
    launcher = prefix / "bin/magnolie-handbuch"
    shutil.copyfile(ROOT / "bin/magnolie-handbuch", launcher)
    shutil.copyfile(ROOT / "bin/magnolie_asset.py", private / "magnolie_asset.py")
    generator = share / "werkzeuge/pot_erzeugen.py"
    shutil.copyfile(ROOT / "werkzeuge/pot_erzeugen.py", generator)
    assert package_version(str(share)) == "2.0.18"
    assert not (share / "debian").exists()
    output = tmp_path / "installed.pot"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=str(tmp_path))
    result = subprocess.run([sys.executable, str(launcher), "--language", "en", "--pot-template", str(output)],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert "POT template written to:" in result.stdout
    assert entries(output.read_text()) == entries((ROOT / "po/magnolie-handbuch.pot").read_text())


def test_temporary_pot_does_not_rewrite_source_markers(tmp_path):
    marker = ROOT / "web/i18n-markers.js"
    before = (marker.read_bytes(), marker.stat().st_mtime_ns)
    output = tmp_path / "source.pot"
    subprocess.run([sys.executable, str(ROOT / "werkzeuge/pot_erzeugen.py"), "--output", str(output)], check=True)
    assert (marker.read_bytes(), marker.stat().st_mtime_ns) == before
    assert entries(output.read_text()) == entries((ROOT / "po/magnolie-handbuch.pot").read_text())


def test_download_metadata_is_version_independent():
    metadata = json.loads((ROOT / "web/mobile-downloads.json").read_text())
    assert "version" not in metadata["notes"]
    assert metadata["notes"]["url"].endswith("/Magnolie-Notes.apk")


def test_version_metadata_is_in_both_package_layouts():
    assert "web/version.json" in (ROOT / "debian/install").read_text()
    assert "web/version.json" in (ROOT / "rpm/magnolie-handbuch.spec").read_text()


def test_english_override_is_complete_only_for_unchanged_german_pages():
    data = handbook_data()
    pages = [page for page in data["pages"] if page["id"] in
             {"support-with-a-coffee", "about-maik-walter"}]
    expected = {page[key] for page in pages for key in ("kapitel", "titel", "inhalt")}
    po = ROOT / "po/english/protected.po"
    catalog = entries(po.read_text())
    assert set(catalog) == expected
    assert all(catalog[key].strip() and catalog[key] != key for key in expected)
    js = (ROOT / "web/i18n/en.js").read_text()
    assert json.loads(js.split(",", 1)[1].rsplit(");", 1)[0])["messages"] == catalog
    subprocess.run(["msgfmt", "--check", "--check-format", "-o", os.devnull, str(po)], check=True)
    for package in ("debian/rules", "rpm/magnolie-handbuch.spec"):
        assert "po/english/protected.po web/i18n/en.js" in (ROOT / package).read_text()
