"""Current APK instructions and the native Windows source projection, without a GUI."""
import gettext
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT.parent / "magnolie-organizer-windows"
sys.path.insert(0, str(ROOT / "werkzeuge"))
from katalog_pruefen import entries
from pot_erzeugen import handbook_data, package_version


def test_versionless_guidance_in_every_catalog():
    pages = {page["id"]: page["inhalt"] for page in handbook_data()["pages"]}
    transfer = pages["android-apk-transfer"]
    install = pages["android-apk-install-update"]
    for language in ["en", *(ROOT / "po/LINGUAS").read_text().split()]:
        if language == "en":
            messages = {transfer: transfer, install: install}
        else:
            messages = entries((ROOT / "po" / (language + ".po")).read_text())
            mo = gettext.translation("magnolie-handbuch", ROOT / "locale", [language])
            for source in (transfer, install):
                assert mo.gettext(source) == messages[source] != source, language
        for source in (transfer, install):
            value = messages[source]
            assert "Magnolie-Notes.apk" in value, language
            assert "Magnolie-Notes-PRUEFSUMMEN.sha256" not in value, language
            assert not re.search(r"Magnolie-Notes-\d+\.\d+\.\d+\.apk", value), language
        value = messages[transfer]
        assert "Magnolie-Notes-latest-PRUEFSUMMEN.sha256" in value, language
        assert "sha256sum Magnolie-Notes.apk" in value, language
        assert "Get-FileHash .\\Magnolie-Notes.apk -Algorithm SHA256" in value, language
        assert "1.0.13" not in value, language


def test_native_windows_projection_only_changes_approved_resource_paths(tmp_path):
    runner = next(shutil.which(name) for name in ("node", "nodejs", "bun") if shutil.which(name))
    version = package_version()
    installer = f"Magnolie-Organizer-Windows-{version}-Setup-x64.exe"
    output = tmp_path / "handbook"
    subprocess.run([runner, str(WINDOWS / "build/PortHandbook.js"), str(ROOT / "web"),
                    version, installer, str(output)], check=True)
    source_files = {path.relative_to(ROOT / "web") for path in (ROOT / "web").rglob("*") if path.is_file()}
    assert source_files == {path.relative_to(output) for path in output.rglob("*") if path.is_file()}
    for relative in source_files:
        expected = (ROOT / "web" / relative).read_bytes()
        if relative == Path("version.json"):
            expected = (json.dumps({"version": version}, separators=(",", ":")) + "\n").encode()
        elif relative == Path("inhalt.js") or relative.parent == Path("i18n") and relative.suffix == ".js":
            text = expected.decode()
            text = re.sub(r"Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64\.exe", installer, text)
            text = re.sub(r"Windows \d+\.\d+\.\d+", "Windows " + version, text)
            for name in ("kaffee-qr.png", "maik-walter.jpg"):
                text = re.sub(r"src=(['\"])" + re.escape(name) + r"\1",
                              lambda match: "src=" + match[1] + "https://handbuchassets.magnolie.invalid/" + name + match[1], text)
            expected = text.encode()
        assert (output / relative).read_bytes() == expected, relative
