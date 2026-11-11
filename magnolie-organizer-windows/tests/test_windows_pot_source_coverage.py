"""Windows-only extraction gates; no translated runtime catalogs required."""

import importlib.util
import json
import gettext
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phone_audio_question_extraction_and_all_native_catalogs(tmp_path):
    """The real question/outcome literals must survive native catalog compilation.

    No GUI, consent, download, UAC or driver code is executed by this test.
    Native GUI acceptance and independent linguistic review are separate work.
    """
    source = (ROOT / "PhoneCameraAudioSetupUi.cs").read_text(encoding="utf-8")
    keys = {json.loads(literal) for literal in re.findall(
        r'\bT\(("(?:\\.|[^"\\])*")\)', source)}
    assert len(keys) == 11
    pot = tmp_path / "windows.pot"
    subprocess.run(["python3", str(ROOT / "werkzeuge/pot_erzeugen.py"),
                    "--output", str(pot)], check=True)
    extracted = subprocess.check_output(
        ["msgattrib", "--no-wrap", str(pot)], text=True, encoding="utf-8")
    for key in keys:
        assert "msgid " + json.dumps(key, ensure_ascii=False) + "\n" in extracted
    native = tmp_path / "native.json"
    locales_source = (ROOT / "NativeLocalization.cs").read_text(encoding="utf-8")
    locale_list = re.search(r'SupportedLocales\s*=\s*\[(.*?)\];', locales_source, re.S)
    assert locale_list
    locales = re.findall(r'"([^"]+)"', locale_list[1])
    assert len(locales) == len(set(locales)) == 19
    arguments = [item for locale in locales
                 for item in (locale, str(ROOT / "app/po" / (locale + ".po")))]
    subprocess.run(["python3", str(ROOT / "werkzeuge/po_zu_native.py"),
                    str(native), *arguments], check=True)
    catalogs = json.loads(native.read_text(encoding="utf-8"))["locales"]
    shipped = json.loads((ROOT / "app/native-i18n.json").read_text(encoding="utf-8"))["locales"]
    assert set(catalogs) == set(locales)
    for locale in locales:
        catalog = catalogs[locale]
        mo = tmp_path / (locale + ".mo")
        subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo),
                        str(ROOT / "app/po" / (locale + ".po"))], check=True)
        with mo.open("rb") as file:
            compiled = gettext.GNUTranslations(file)
        for key in keys:
            assert catalog[key] and catalog[key] != key, (locale, key)
            assert compiled.gettext(key) == catalog[key], (locale, key)
            assert shipped[locale][key] == catalog[key], ("runtime", locale, key)
            assert "VB-CABLE" not in key or "VB-CABLE" in catalog[key], locale
            assert "VB-Audio" not in key or "VB-Audio" in catalog[key], locale
            assert "www.vb-cable.com" not in key or "www.vb-cable.com" in catalog[key], locale
        # Placeholder/markup corruption must not hide license origins or turn
        # non-readiness into an English fallback. Human wording review remains
        # distinct from compilation/coverage and is not claimed by this test.
    catalog = catalogs["de"]
    # Safety/legal disclosures are part of the localized question, not just
    # extraction markers or an English fallback in an otherwise German UI.
    for key, fragments in (
        ("VB-CABLE is selected separately in OBS or another application. This setup prevents it from becoming the Windows default audio device, including manual default selection.",
         ("OBS", "Windows", "manuelle", "Standardgerät")),
        ("VB-CABLE is donationware by VB-Audio: www.vb-cable.com. Donations are welcome; professional deployments may require purchased licences.",
         ("VB-Audio", "www.vb-cable.com", "Donationware", "Lizenzen")),
    ):
        assert all(fragment in catalog[key] for fragment in fragments)


def test_phone_handshake_timeout_uses_existing_gettext_key():
    source = (ROOT / "TelefonCoordinator.cs").read_text(encoding="utf-8")
    assert 'throw new TimeoutException(T("Phone connection cancelled or timed out."))' in source
    assert '"Der Telefon-Handshake hat nicht rechtzeitig geantwortet."' not in source


def test_setup_deferred_literals_are_catalogued(tmp_path):
    spec = importlib.util.spec_from_file_location("windows_pot", ROOT / "werkzeuge/pot_erzeugen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / "windows.pot"
    module.run(["--output", str(output)])
    first = output.read_bytes()
    module.run(["--output", str(output)])
    assert output.read_bytes() == first
    # msgattrib normalizes wrapping for exact key checks without compiling translations.
    text = subprocess.check_output(["msgattrib", "--no-wrap", str(output)], text=True, encoding="utf-8")
    # Native media labels live in the existing gettext marker file, not only
    # direct _ calls. Package regeneration must retain them as well.
    for label in ("A native media operation is still running.", "Photos",
                  "Synchronize videos", "Media recycle bin"):
        assert "msgid " + json.dumps(label) + "\n" in text
    for name in ("FirstRunSetupForm.cs", "FirstRunSetupPhoneServices.cs", "NextcloudMailbox.cs"):
        source = (ROOT / name).read_text(encoding="utf-8")
        literals = module.deferred_literals(name, source)
        assert literals, name
        for literal in literals:
            assert "msgid " + json.dumps(json.loads(literal), ensure_ascii=False) in text
    for identifier in ("nextcloud", "generic-dav", "bluetooth", "select"):
        assert 'msgid "' + identifier + '"\n' not in text
