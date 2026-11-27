"""Real CSV byte dispatcher: decode BOM text before detecting binary NULs (#817)."""
import codecs
import io
from pathlib import Path
import zipfile

import pytest

from modul_laden import quellmodul_laden


SOURCE = Path(__file__).resolve().parents[1] / "bin/magnolie-organizer"
native = quellmodul_laden("magnolie_csv_unicode_import", SOURCE)
EVENT_CSV = 'ANFANGSDATUMZEIT,BESCHREIBUNG\r\n"27.11.2026 09:30","Prüfung 👩‍💻"\r\n'
CONTACT_CSV = 'Vorname,Nachname,E-Mail\r\nZoë,Müller,zoe@example.test\r\n'


def encoded(text, encoding):
    if encoding == "utf-16-le":
        return codecs.BOM_UTF16_LE + text.encode(encoding)
    if encoding == "utf-16-be":
        return codecs.BOM_UTF16_BE + text.encode(encoding)
    return text.encode(encoding)


def archive(raw):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as value:
        value.writestr("selected/import.csv", raw)
    return output.getvalue()


@pytest.mark.parametrize("encoding", ("utf-8-sig", "utf-16-le", "utf-16-be"))
@pytest.mark.parametrize("kind", ("lotus", "vcf"))
@pytest.mark.parametrize("in_zip", (False, True))
@pytest.mark.parametrize("source,field,key,expected", (
    (EVENT_CSV, "termine", "titel", "Prüfung 👩‍💻"),
    (CONTACT_CSV, "kontakte", "nachname", "Müller"),
))
def test_unicode_csv_through_actual_dispatcher(encoding, kind, in_zip, source, field, key, expected):
    raw = encoded(source, encoding)
    result = native.import_rohdaten_lesen(kind, archive(raw) if in_zip else raw,
                                        "selected.zip" if in_zip else "selected.csv")
    assert len(result[field]) == 1
    assert result[field][0][key] == expected
    assert result["uebersprungen"] == 0
    if field == "termine":
        assert result[field][0]["datum"] == "2026-11-27"
        assert result[field][0]["zeit"] == "09:30"


@pytest.mark.parametrize("encoding", ("utf-8-sig", "utf-16-le", "utf-16-be"))
def test_decoded_null_remains_rejected(encoding):
    with pytest.raises(ValueError, match="CSV"):
        native.import_rohdaten_lesen("lotus", encoded(EVENT_CSV.replace("Prüfung", "Prü\0fung"), encoding), "selected.csv")


@pytest.mark.parametrize("raw", (b"SQLite format 3\0" + b"x" * 50, b"\xff\xfeA", b"\xfe\xff\0", b"\xff\xfe\x00\xd8"))
def test_binary_and_damaged_utf16_remain_rejected(raw):
    with pytest.raises(ValueError, match="CSV"):
        native.import_rohdaten_lesen("lotus", raw, "selected.csv")


def test_legacy_single_byte_and_bytearray_still_import():
    source = EVENT_CSV.replace(" 👩‍💻", "")
    result = native.lotus_csv_lesen(bytearray(source.encode("cp1252")))
    assert result["termine"][0]["titel"] == "Prüfung"
