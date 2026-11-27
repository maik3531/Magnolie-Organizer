"""CSV role groups are preserved without fabricated addresses (part of #566)."""
import copy
import csv
import io
import json
from pathlib import Path

import pytest

from test_startup_read_failure import native


VECTORS = json.loads((Path(__file__).resolve().parents[2] /
                     "contracts/lotus-csv-contact-fields.json").read_text())["cases"]


def rows(values, fields):
    return sorted(tuple(str(value.get(field, "")) for field in fields) +
                  (tuple(sorted(value.get("typen", []))),) for value in values)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda case: case["id"])
def test_csv_contact_roles_and_addresses_survive_vcard(native, vector):
    text = io.StringIO()
    writer = csv.writer(text, delimiter=";", lineterminator="\r\n")
    writer.writerow(vector["headers"])
    writer.writerow(vector["row"])
    raw = text.getvalue().encode("utf-8")
    result = native.import_rohdaten_lesen("lotus", raw, "owned-contacts.csv")
    assert result["uebersprungen"] == 0
    contact, = result["kontakte"]
    assert native.import_rohdaten_lesen("vcf", raw, "owned-contacts.csv")["kontakte"] == [contact]
    for _ in range(3):
        assert (contact["vorname"], contact["nachname"]) == ("Synthetic", "CSV")
        assert rows(contact.get("telefone", []), ("wert",)) == rows(vector["phones"], ("wert",))
        fields = ("strasse", "plz", "ort", "land")
        assert rows(contact.get("anschriften", []), fields) == rows(vector["addresses"], fields)
        if contact.get("anschriften"):
            assert all(contact[field] == contact["anschriften"][0][field] for field in fields[:3])
        before = copy.deepcopy(contact)
        exported = native.vcard_text(contact)
        assert contact == before
        assert exported.count("BEGIN:VCARD") == 1
        contact, = native.import_rohdaten_lesen("vcf", exported.encode("utf-8"), "owned.vcf")["kontakte"]
