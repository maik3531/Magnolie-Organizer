"""Owned native tray-settings and autostart-entry readback fixtures."""
from pathlib import Path
import tempfile

import pytest

from modul_laden import quellmodul_laden


def test_actual_tray_config_and_autostart_registration_readback(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="magnolie-tray-state-", dir="/tmp/opencode") as root:
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            monkeypatch.setenv(key, root)
        source = Path(__file__).parents[1] / "bin/magnolie-organizer"
        product = quellmodul_laden("owned_native_tray_state", str(source))
        config = Path(root) / "owned-tray.json"
        assert product.tray_einstellungen_schreiben({"autostart": True, "oeffnen": "centered"}, str(config))["ok"]
        actual = product.tray_einstellungen_geprueft_lesen(str(config))
        assert actual["aktiv"] and actual["startMinimiert"] and actual["autostart"] and actual["oeffnen"] == "centered"
        entry = Path(root) / "owned-tray.desktop"
        assert product.tray_autostart_einrichten(True, str(entry))["ok"]
        assert product.tray_autostart_registriert(str(entry))
        entry.write_text(entry.read_text().replace("Hidden=false", "Hidden=true"))
        assert not product.tray_autostart_registriert(str(entry))
        assert product.tray_autostart_einrichten(False, str(entry))["ok"]
        assert not entry.exists() and not product.tray_autostart_registriert(str(entry))
        config.write_text("{broken")
        with pytest.raises(ValueError):
            product.tray_einstellungen_geprueft_lesen(str(config))
