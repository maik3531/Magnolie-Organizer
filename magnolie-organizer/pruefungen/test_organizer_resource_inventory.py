"""#684: the real entry point must be served by both fixed native transports."""
from html.parser import HTMLParser
from pathlib import Path
import sys

import pytest

from modul_laden import quellmodul_laden


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SCRIPTS = ("contact-group-aliases.js", "appearance.js", "normative-timezones.js")
TOKEN = "a" * 48


@pytest.fixture
def native(monkeypatch, tmp_path):
    for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                 "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        target = tmp_path / name
        target.mkdir(mode=0o700)
        monkeypatch.setenv(name, str(target))
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent-resource-test-bus")
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/nonexistent-resource-test-system-bus")
    monkeypatch.setitem(sys.modules, "gi", None)
    monkeypatch.syspath_prepend(str(ROOT / "bin"))
    return quellmodul_laden("magnolie_resource_inventory", ROOT / "bin/magnolie-organizer")


def resolve(native, transport, name, web=WEB):
    if transport == "native":
        return native.organizer_ressource("magnolie-organizer://app/" + name, str(web), "en")
    return native.organizer_http_ressource("/" + TOKEN + "/" + name, TOKEN, str(web), "en")


class EntryScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.sources.append(attrs["src"])


@pytest.mark.parametrize("transport", ("native", "http"))
def test_real_entry_point_scripts_are_all_reachable(native, transport):
    parser = EntryScripts()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    assert parser.sources
    missing = [name for name in parser.sources if resolve(native, transport, name) is None]
    assert not missing, (transport, missing)
    for name in parser.sources:
        path, mime = resolve(native, transport, name)
        expected = WEB / ("i18n-en.js" if name == "i18n-active.js" else name)
        assert Path(path) == expected.resolve()
        assert mime == "application/javascript"


@pytest.mark.parametrize("transport", ("native", "http"))
@pytest.mark.parametrize("name", SCRIPTS)
def test_required_script_paths_remain_exact_and_fixed(native, transport, name, tmp_path):
    assert resolve(native, transport, name) == (str((WEB / name).resolve()), "application/javascript")
    for invalid in (name + "?v=1", name + "#fragment", "../" + name,
                    "%" + format(ord(name[0]), "02x") + name[1:], "/" + name,
                    name.replace(".js", ".js/extra")):
        assert resolve(native, transport, invalid) is None
    unknown = tmp_path / "private-test.js"
    unknown.write_text("not an approved entry point", encoding="utf-8")
    assert resolve(native, transport, unknown.name, tmp_path) is None


@pytest.mark.parametrize("transport", ("native", "http"))
@pytest.mark.parametrize("name", SCRIPTS)
def test_missing_or_escaped_script_is_not_served(native, transport, name, tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    assert resolve(native, transport, name, root) is None
    outside = tmp_path / "outside.js"
    outside.write_text("outside the approved root", encoding="utf-8")
    (root / name).symlink_to(outside)
    assert resolve(native, transport, name, root) is None


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_admission_does_not_expand_origin_or_capability(native, name):
    for authority in ("elsewhere", "user@app", "app:443"):
        assert native.organizer_ressource("magnolie-organizer://" + authority + "/" + name, str(WEB)) is None
    assert native.organizer_http_ressource("/" + "b" * 48 + "/" + name, TOKEN, str(WEB)) is None
    assert native.organizer_http_ressource("/" + TOKEN + "extra/" + name, TOKEN, str(WEB)) is None
