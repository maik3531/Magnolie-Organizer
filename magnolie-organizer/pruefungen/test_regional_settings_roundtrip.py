"""Native regional preferences retain explicit zones through file round trips."""
import json
from pathlib import Path
import tempfile

import pytest

from modul_laden import quellmodul_laden


@pytest.mark.parametrize("zone", ["UTC", "Etc/UTC", "Europe/Berlin", "system"])
def test_native_regional_zone_survives_write_and_cold_read(monkeypatch, zone):
    with tempfile.TemporaryDirectory(prefix="magnolie-regional-roundtrip-", dir="/tmp/opencode") as root:
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            monkeypatch.setenv(key, root)
        source = Path(__file__).parents[1] / "bin/magnolie-organizer"
        product = quellmodul_laden("owned_regional_zone_" + zone.replace("/", "_"), str(source))
        target = Path(root) / "owned-locale.json"
        assert product.regional_einstellungen_schreiben({"timeZone": zone}, str(target))
        assert json.loads(target.read_text())["timeZone"] == zone
        assert product.regional_einstellungen_lesen(str(target))["timeZone"] == zone
