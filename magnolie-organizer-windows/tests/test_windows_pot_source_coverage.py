"""Windows-only extraction gates; no translated runtime catalogs required."""

import importlib.util
import json
import gettext
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phone_audio_question_extraction_and_german_native_catalog(tmp_path):
    """The real question/outcome literals must survive native catalog compilation.

    No GUI, consent, download, UAC or driver code is executed by this test.
    Other translated languages and native GUI acceptance remain separate work.
    """
    source = (ROOT / "PhoneCameraAudioSetupUi.cs").read_text(encoding="utf-8")
    keys = {json.loads(literal) for literal in re.findall(
        r'\bT\(("(?:\\.|[^"\\])*")\)', source)}
    assert len(keys) == 10
    pot = tmp_path / "windows.pot"
    subprocess.run(["python3", str(ROOT / "werkzeuge/pot_erzeugen.py"),
                    "--output", str(pot)], check=True)
    extracted = subprocess.check_output(
        ["msgattrib", "--no-wrap", str(pot)], text=True, encoding="utf-8")
    for key in keys:
        assert "msgid " + json.dumps(key, ensure_ascii=False) + "\n" in extracted
    native = tmp_path / "native.json"
    subprocess.run(["python3", str(ROOT / "werkzeuge/po_zu_native.py"),
                    str(native), "de", str(ROOT / "app/po/de.po")], check=True)
    catalog = json.loads(native.read_text(encoding="utf-8"))["locales"]["de"]
    mo = tmp_path / "de.mo"
    subprocess.run(["msgfmt", "--check", "--check-format", "-o", str(mo),
                    str(ROOT / "app/po/de.po")], check=True)
    with mo.open("rb") as file:
        compiled = gettext.GNUTranslations(file)
    for key in keys:
        assert catalog[key] and catalog[key] != key
        assert compiled.gettext(key) == catalog[key]
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
