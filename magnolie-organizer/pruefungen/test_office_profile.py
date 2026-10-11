import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from magnolie_office_profile import exchange, OOR


def test_selected_office_fields_change_without_replacing_other_settings(tmp_path):
    directory = tmp_path / "user"
    directory.mkdir()
    path = directory / "registrymodifications.xcu"
    path.write_text('''<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<!--keep--><item oor:path="/org.openoffice.UserProfile/Data"><prop oor:name="givenname"><value>Before</value></prop>
<prop oor:name="mail"><value>keep@example.invalid</value></prop></item>
<item oor:path="/org.openoffice.Other"><prop oor:name="setting"><value>unchanged</value></prop></item></oor:items>''')
    initial = exchange(str(path))
    updated = exchange(str(path), {"givenname": "After & more", "street": "Test road 1"}, initial["stamp"])
    assert updated["felder"] == {"givenname": "After & more", "street": "Test road 1", "mail": "keep@example.invalid"}
    assert "<!--keep-->" in path.read_text()
    root = ET.fromstring(path.read_bytes())
    assert next(node for node in root if node.get("{%s}path" % OOR) == "/org.openoffice.Other").find("prop/value").text == "unchanged"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="changed"):
        exchange(str(path), {"givenname": "Stale"}, initial["stamp"])
    assert path.read_bytes() == before


def test_running_office_is_not_overwritten(tmp_path):
    directory = tmp_path / "user"
    directory.mkdir()
    path = directory / "registrymodifications.xcu"
    path.write_text('<oor:items xmlns:oor="http://openoffice.org/2001/registry"/>')
    snapshot = exchange(str(path))
    (tmp_path / ".lock").write_text("running")
    with pytest.raises(ValueError, match="Close LibreOffice"):
        exchange(str(path), {"givenname": "After"}, snapshot["stamp"])
    assert exchange(str(path))["felder"] == {}
