"""Native-generated OR6 values, deleted storage and hostile ccSTR boundaries."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "bin"))
from magnolie_or6 import read_or6, _rtf
from modul_laden import quellmodul_laden

CONTRACT = json.loads((Path(__file__).parents[2] / "contracts/or6-native-fixtures.json").read_text())


def native_fixture(name="known-values.or6"):
    item = CONTRACT["files"][name]
    data = gzip.decompress(base64.b64decode(item["gzip_base64"], validate=True))
    assert len(data) == item["bytes"] and hashlib.sha256(data).hexdigest() == item["sha256"]
    return data


def rotate(data, left):
    output = bytearray(data)
    for offset in range(0, len(output), 2):
        word = struct.unpack_from("<H", output, offset)[0]
        word = ((word << 1) | (word >> 15)) if left else ((word >> 1) | (word << 15))
        struct.pack_into("<H", output, offset, word & 65535)
    return output


def blocks(decoded):
    offset = 0
    while offset < len(decoded):
        tag, address, size = struct.unpack_from("<III", decoded, offset)
        assert offset == address and size >= 12
        yield offset, tag, size
        offset += size


def test_native_or6_known_values_and_live_deletion():
    result = read_or6(native_fixture())
    for kind, collection in (("contact", "kontakte"), ("appointment", "termine"), ("task", "aufgaben"), ("note", "notizen")):
        assert len(result[collection]) == 1
        for key, value in CONTRACT["expected"][kind].items():
            assert result[collection][0][key] == value
        assert result[collection][0]["uid"].startswith("or6:")
    assert result["uebersprungen"] == 0
    empty = read_or6(native_fixture("empty.or6"))
    assert all(not empty[key] for key in ("kontakte", "termine", "aufgaben", "notizen"))
    assert empty["uebersprungen"] == 0
    deleted = read_or6(native_fixture("deleted-values.or6"))
    assert not deleted["kontakte"]
    for collection in ("termine", "aufgaben", "notizen"):
        assert deleted[collection] == result[collection]
    assert "Recurrences" in result["bericht"] and "attachments" in result["bericht"]


def test_selected_application_catalog_translates_report_and_read_error():
    def selected(message):
        return "Selected catalog: " + message
    assert read_or6(native_fixture(), selected)["bericht"].startswith("Selected catalog: OR6")
    with pytest.raises(ValueError, match="Selected catalog: The content is unreadable"):
        read_or6(b"invalid", selected)


@pytest.mark.parametrize("corruption", ("truncated", "signature", "zero_size", "self", "field_pointer", "duplicate_field", "schema_cycle", "wrong_parent", "rtf"))
def test_corrupt_or6_fails_before_returning_any_records(corruption):
    raw = native_fixture()
    if corruption == "truncated":
        broken = raw[:-4]
    elif corruption == "signature":
        broken = b"NOPE" + raw[4:]
    else:
        data = rotate(raw, True)
        chain = list(blocks(data))
        contact = next(offset for offset, tag, size in chain if tag == 0x400 and struct.unpack_from("<I", data, offset+0x28)[0] == 34)
        if corruption == "zero_size":
            struct.pack_into("<I", data, 8, 0)
        elif corruption == "self":
            struct.pack_into("<I", data, contact+4, contact+4)
        elif corruption == "field_pointer":
            struct.pack_into("<I", data, contact+0x34+8+4, 0xffffffff)
        elif corruption == "duplicate_field":
            data[contact+0x34+8:contact+0x34+10] = data[contact+0x34:contact+0x34+2]
        elif corruption == "wrong_parent":
            struct.pack_into("<I", data, contact+0x18, 0xffffffff)
        elif corruption == "schema_cycle":
            field = next(offset for offset, tag, size in chain if tag == 0xfffffffd)
            struct.pack_into("<I", data, field+0x20, field)
        else:
            note = next(offset for offset, tag, size in chain if tag == 0x510)
            size = next(size for offset, tag, size in chain if offset == note)
            end = data.rfind(b"}", note, note+size)
            assert end >= note
            data[end] = 32
        broken = bytes(rotate(data, False))
    with pytest.raises(ValueError):
        read_or6(broken)


def test_rtf_does_not_include_objects_and_handles_unicode_without_rendering():
    assert _rtf(b"{\\rtf1\\ansi\\ansicpg1252{\\fonttbl{\\f0 Hidden font;}}{\\*\\objdata Hidden object}Visible\\par \\u228?\\'f6\\'fc\\'df}") == "Visible\näöüß"
    with pytest.raises(ValueError):
        _rtf(b"{\\rtf1" + b"{" * 65 + b"}" * 66)


def test_unsupported_series_do_not_claim_preserved_ics_originals():
    data = rotate(native_fixture(), True)
    appointment = next(offset for offset, tag, size in blocks(data) if tag == 0x100)
    count = struct.unpack_from("<I", data, appointment+0x28)[0]
    for index in range(count):
        offset = appointment + 0x34 + index*8
        if struct.unpack_from("<H", data, offset)[0] == 15:
            struct.pack_into("<HHI", data, offset, 10, 2, 1)
            break
    else:
        raise AssertionError("Native appointment busy field missing")
    result = read_or6(bytes(rotate(data, False)))
    assert not result["termine"] and result["uebersprungen"] == 1
    assert result["wiederholend"] == 0


def test_actual_linux_dispatch_zip_and_source_bound_mcp_preview(tmp_path):
    product = quellmodul_laden("or6_import_product", str(Path(__file__).parents[1] / "bin/magnolie-organizer"))
    raw = native_fixture()
    assert product.import_rohdaten_lesen("lotus", raw, "owned.or6")["kontakte"][0]["nachname"] == "Müller"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as writer:
        writer.writestr("owned.or6", raw)
    assert len(product.import_rohdaten_lesen("lotus", archive.getvalue(), "owned.zip")["notizen"]) == 1

    class Window:
        _gesperrt = False
        def __init__(self): self.replies = []
        def _datei_oeffnen(self, *args): raise AssertionError("MCP opened file dialog")
        def antwort(self, callback, payload): self.replies.append((callback, payload))

    path = tmp_path / "owned.or6"
    path.write_bytes(raw)
    window = Window()
    def inspect(**extras):
        product.Fenster.bei_import(window, {"requestId": "owned-or6", "art": "lotus", "pfad": str(path), **extras})
        callback, payload = window.replies.pop()
        assert callback == "App.importErgebnis" and payload["requestId"] == "owned-or6"
        return payload
    original = inspect()
    assert original["ok"] and len(original["kontakte"]) == len(original["notizen"]) == 1
    assert original["sha256"] == hashlib.sha256(raw).hexdigest()
    assert inspect(expectedRevision=original["revision"])["ok"]
    path.write_bytes(raw + b"\0\0\0\0")
    assert inspect(expectedRevision=original["revision"])["code"] == "conflict"
    assert path.read_bytes() == raw + b"\0\0\0\0"
