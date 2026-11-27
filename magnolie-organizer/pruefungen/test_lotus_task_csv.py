"""Check Lotus task status and priority through CSV import and VTODO roundtrip."""
import json
from pathlib import Path

import pytest

from modul_laden import quellmodul_laden


SOURCE = Path(__file__).resolve().parents[1]
MARKER = "contracts/lotus-task-csv-vectors.json"
contract = SOURCE.parent / MARKER
if not contract.is_file():
    contract = SOURCE / MARKER
VECTORS = json.loads(contract.read_text(encoding="utf-8"))
native = quellmodul_laden("magnolie_lotus_task_csv", SOURCE / "bin/magnolie-organizer")


@pytest.mark.parametrize("vector", VECTORS, ids=lambda vector: vector["header"])
def test_lotus_task_csv(vector):
    rows = vector["rows"]
    csv = "\r\n".join([vector["header"], *(row["csv"] for row in rows), ""])
    imported = native.lotus_csv_lesen(csv.encode("utf-8-sig"))
    assert imported["uebersprungen"] == 0
    tasks = imported["aufgaben"]
    expected = [(row["csv"].split(";")[0], "2026-05-31", row["done"], row["priority"]) for row in rows]

    def task_fields(items):
        return [(item["titel"], item["faellig"], item["erledigt"], item["prio"]) for item in items]

    assert task_fields(tasks) == expected
    exported = native.ics_schreiben_aufgaben(tasks)
    assert exported.count("BEGIN:VTODO") == len(rows)
    assert task_fields(native.ics_lesen(exported)["aufgaben"]) == expected
