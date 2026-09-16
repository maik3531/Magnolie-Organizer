"""Windows-only extraction gates; no translated runtime catalogs required."""

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
    text = subprocess.check_output(["msgattrib", "--no-wrap", str(output)], text=True)
    for name in ("FirstRunSetupForm.cs", "FirstRunSetupPhoneServices.cs", "NextcloudMailbox.cs"):
        source = (ROOT / name).read_text(encoding="utf-8")
        literals = module.deferred_literals(name, source)
        assert literals, name
        for literal in literals:
            assert "msgid " + json.dumps(json.loads(literal), ensure_ascii=False) in text
    for identifier in ("nextcloud", "generic-dav", "bluetooth", "select"):
        assert 'msgid "' + identifier + '"\n' not in text
