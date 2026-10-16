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


def test_checked_native_regional_write_uses_file_state_cas_and_real_zone_validation(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="magnolie-regional-cas-", dir="/tmp/opencode") as root:
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            monkeypatch.setenv(key, root)
        source = Path(__file__).parents[1] / "bin/magnolie-organizer"
        product = quellmodul_laden("owned_regional_cas", str(source))
        path = str(Path(root) / "owned-locale.json")
        assert product.regional_einstellungen_schreiben({"language": "en", "timeZone": "UTC", "homeCountry": "US"}, path)
        initial = product.regional_einstellungen_geprueft_lesen(path)
        desired = dict(initial, hourCycle="h12", formatLocale="en_GB")
        actual = product.regional_einstellungen_geprueft_schreiben(desired, initial, path)
        assert actual["hourCycle"] == "h12" and actual["formatLocale"] == "en-GB" and actual["homeCountry"] == "US"
        saved = Path(path).read_bytes()
        with pytest.raises(ValueError, match="regional_conflict"):
            product.regional_einstellungen_geprueft_schreiben(desired, initial, path)
        assert Path(path).read_bytes() == saved
        for patch in ({"timeZone": "Mars/Olympus"}, {"homeCountry": "ZZ"}, {"language": "not-a-catalog"}):
            with pytest.raises(ValueError, match="invalid_regional_settings"):
                product.regional_einstellungen_geprueft_schreiben(dict(actual, **patch), actual, path)
            assert Path(path).read_bytes() == saved
        partial = dict(actual, hourCycle="h23")
        del partial["homeCountry"]
        assert product.regional_einstellungen_geprueft_schreiben(partial, actual, path)["homeCountry"] == "US"


def test_verified_native_regional_read_does_not_claim_corrupt_file_is_valid(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="magnolie-regional-invalid-", dir="/tmp/opencode") as root:
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            monkeypatch.setenv(key, root)
        source = Path(__file__).parents[1] / "bin/magnolie-organizer"
        product = quellmodul_laden("owned_regional_invalid", str(source))
        target = Path(root) / "owned-locale.json"
        assert product.regional_einstellungen_geprueft_lesen(str(target))["timeZone"] == "system"
        target.write_text("{broken")
        with pytest.raises(ValueError):
            product.regional_einstellungen_geprueft_lesen(str(target))
