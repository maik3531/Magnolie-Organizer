"""Native background-state reads keep OS registration changes explicit."""
from pathlib import Path
import tempfile

from modul_laden import quellmodul_laden


def test_mcp_background_read_does_not_reconcile_autostart_but_legacy_ui_still_does(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="magnolie-background-read-", dir="/tmp/opencode") as root:
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
            monkeypatch.setenv(key, root)
        source = Path(__file__).parents[1] / "bin/magnolie-organizer"
        product = quellmodul_laden("owned_background_read", str(source))
        settings = product.background_settings_read()
        settings.update(enabled=True, autostart=True)
        product.background_settings_write(settings, update_autostart=False)
        target = Path(product.background_autostart_path())
        assert target.is_relative_to(Path(root)) and not target.exists()
        readonly = product.hintergrund_einstellungen_lesen(reconcile_autostart=False)
        assert readonly["enabled"] and readonly["autostart"] and not readonly["running"]
        assert not target.exists()
        legacy = product.hintergrund_einstellungen_lesen()
        assert legacy["enabled"] and target.is_file()
