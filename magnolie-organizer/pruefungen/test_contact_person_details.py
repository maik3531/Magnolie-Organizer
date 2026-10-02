"""Emergency-contact details survive exchange without importing local references (#78)."""
import json
from test_startup_read_failure import native


def person():
    return {"name": "Elena Care", "vorname": "Elena", "nachname": "Care", "telefon": "0123", "status": "Son",
            "kontaktId": "local-card", "firma": "Care company", "notiz": "First line\nSecond line", "geburtstag": "--07-06",
            "telefone": [{"wert": "0123", "typen": ["HOME"]}, {"wert": "0456", "typen": ["CELL"]}],
            "emailEintraege": [{"wert": "care@example.test", "typen": ["WORK"]}],
            "anschriften": [{"strasse": "Care 7", "plz": "12345", "ort": "Example", "region": "Region",
                             "land": "Deutschland", "postfach": "42", "zusatz": "Floor 2", "typen": ["WORK"]}]}


def test_rich_person_is_not_shadowed_by_legacy_first_person_fields(native):
    p = person()
    record = {"kontaktpersonen": [p], "kontaktpersonName": p["name"], "kontaktpersonTelefon": p["telefon"], "kontaktpersonStatus": p["status"]}
    actual = native._kontaktpersonen_liste(record)
    assert len(actual) == 1
    assert actual[0]["kontaktId"] == "local-card"
    assert actual[0]["anschriften"][0]["zusatz"] == "Floor 2"
    assert actual[0]["notiz"] == p["notiz"]
    assert len(actual[0]["telefone"]) == 2


def test_vcard_keeps_full_manual_person_but_not_local_card_reference(native):
    p = person()
    exported = native.vcf_schreiben([{"vorname": "Parent", "uid": "parent", "kontaktpersonen": [p]}])
    assert "local-card" not in exported
    restored = native.vcf_lesen(exported)["kontakte"][0]["kontaktpersonen"]
    assert len(restored) == 1
    actual = restored[0]
    assert "kontaktId" not in actual
    for key in ("name", "vorname", "nachname", "telefon", "status", "firma", "notiz", "geburtstag"):
        assert actual[key] == p[key]
    assert actual["anschriften"][0]["postfach"] == "42"
    assert actual["emailEintraege"][0]["wert"] == "care@example.test"
    assert {n["wert"] for n in actual["telefone"]} == {"0123", "0456"}


def test_external_vcard_cannot_bind_an_existing_local_card(native):
    text = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Parent\r\nX-MAGNOLIE-NOTFALLKONTAKT:" + native._vcard_escape(json.dumps(person())) + "\r\nEND:VCARD\r\n"
    restored = native.vcf_lesen(text)["kontakte"][0]["kontaktpersonen"][0]
    assert "kontaktId" not in restored
    assert restored["firma"] == "Care company"


def test_provider_echo_ignores_local_reference_and_retains_it_without_duplicates(native):
    p = native._kontaktpersonen_liste({"kontaktpersonen": [person()]})[0]
    remote = {k: v for k, v in p.items() if k != "kontaktId"}
    linked = {"kontaktpersonen": [p]}
    copied = {"kontaktpersonen": [remote]}
    assert native._sync_inhalt_hash(linked, ["kontaktpersonen"]) == native._sync_inhalt_hash(copied, ["kontaktpersonen"])
    assert native._kontaktpersonen_vereinigen(linked, copied) == [p]
    assert native._kontaktpersonen_vereinigen(copied, linked) == [p]
