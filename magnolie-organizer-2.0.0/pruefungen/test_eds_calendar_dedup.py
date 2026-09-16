import importlib.machinery
import importlib.util
import os


PROGRAMM = os.path.join(os.path.dirname(__file__), "..", "bin", "magnolie-organizer")
lader = importlib.machinery.SourceFileLoader("magnolie_eds_calendar_dedup", PROGRAMM)
spec = importlib.util.spec_from_loader("magnolie_eds_calendar_dedup", lader)
m = importlib.util.module_from_spec(spec)
lader.exec_module(m)


class Quelle:
    def get_display_name(self):
        return "Google birthdays"


class Registry:
    def ref_source(self, uid):
        return Quelle() if uid == "google-calendar" else None


class Probe:
    def antwort(self, funktion, nutzlast):
        self.funktion = funktion
        self.nutzlast = nutzlast


def test_calendar_connect_wait_is_shorter_than_outer_timeout(monkeypatch):
    calls = []

    class Source:
        def get_enabled(self): return True

    class LocalRegistry:
        def ref_source(self, _uid): return Source()

    class Connected:
        def is_online(self): return True

    class ECal:
        ClientSourceType = type("ClientSourceType", (), {"EVENTS": 1})
        Client = type("Client", (), {"connect_sync": staticmethod(
            lambda *args: calls.append(args) or Connected())})

    monkeypatch.setitem(m._EDS, "ECal", ECal)
    client = m.eds_kalender_client(LocalRegistry(), "local")

    assert isinstance(client, Connected)
    assert calls[0][2] == 5 and calls[0][2] < m.EDS_OPERATION_TIMEOUT


def sync(monkeypatch, lokale_termine, remote_ics, mutations=None,
         client="google-calendar", tombstones=None, fail_operation="", last_sync=0,
         lokale_jahrestage=None):
    mutations = mutations if mutations is not None else []
    def mutate(operation, value):
        if operation == fail_operation:
            raise RuntimeError("GOA permission denied")
        mutations.append((operation, value))
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", Registry)
    monkeypatch.setattr(m, "eds_kalender_client", lambda registry, uid: client)
    monkeypatch.setattr(m, "eds_events_lesen", lambda _client: [remote_ics] if remote_ics else [])
    monkeypatch.setattr(m, "eds_event_anlegen", lambda _client, text: mutate("create", text))
    monkeypatch.setattr(m, "eds_event_aendern", lambda _client, text: mutate("modify", text))
    monkeypatch.setattr(m, "eds_event_loeschen", lambda _client, uid: mutate("delete", uid))
    probe = Probe()
    m.Fenster._sync_ausfuehren(probe, {
        "wahl": {"kalenderUid": "google-calendar",
                 "kalenderUids": ["google-calendar"]},
        "daten": {"termine": lokale_termine, "kontakte": [],
                  "jahrestage": lokale_jahrestage or [],
                  "geloescht": {"termine": tombstones or [], "kontakte": []},
                  "letzterSync": last_sync,
                  "letzteSyncs": {"kalender": {"google-calendar": last_sync}
                                    if last_sync else {}}}})
    return probe.nutzlast


def test_eds_reader_distinguishes_failure_from_empty_calendar():
    class Client:
        def __init__(self, result):
            self.result = result

        def get_object_list_sync(self, query, cancellable):
            return self.result

    try:
        m.eds_events_lesen(Client((False, [])))
    except RuntimeError:
        pass
    else:
        raise AssertionError("failed EDS tuple must abort synchronization")

    assert m.eds_events_lesen(Client((True, []))) == []


def test_eds_reader_aborts_on_one_unserializable_component():
    class Good:
        def as_ical_string(self):
            return "BEGIN:VEVENT\r\nUID:good\r\nEND:VEVENT\r\n"

    class Broken:
        def get_icalcomponent(self):
            raise RuntimeError("broken component")

    class Client:
        def get_object_list_sync(self, query, cancellable):
            return True, [Good(), Broken()]

    try:
        m.eds_events_lesen(Client())
    except RuntimeError as error:
        assert "broken component" in str(error)
    else:
        raise AssertionError("partial EDS snapshots must be rejected")


def test_eds_enumeration_uses_effective_parent_enabled_state(monkeypatch):
    class Source:
        def get_enabled(self): return True
        def get_uid(self): return "calendar"
        def get_display_name(self): return "Calendar"
        def get_parent(self): return ""
    source = Source()
    class EffectiveRegistry:
        def list_sources(self, _extension): return [source]
        def check_enabled(self, _source): return False
    class ES:
        SOURCE_EXTENSION_CALENDAR = "calendar"
        SOURCE_EXTENSION_ADDRESS_BOOK = "book"
    monkeypatch.setitem(m._EDS, "EDataServer", ES)
    monkeypatch.setitem(m._EDS, "buch_ok", False)
    calendars, books = m.eds_quellen(EffectiveRegistry())
    assert calendars == [] and books == []


def test_missing_event_needs_online_state_before_and_after_lookup():
    class Client:
        def __init__(self): self.checks = iter((True, False))
        def is_online(self): return next(self.checks)
        def get_objects_for_uid_sync(self, _uid, _cancellable): return True, []
    try:
        m.eds_event_fehlend_bestaetigt(Client(), "event")
    except RuntimeError as error:
        assert str(error)
    else:
        raise AssertionError("offline cache must not confirm a remote deletion")


def test_yearly_all_day_from_ics_and_eds_is_one_read_only_event(monkeypatch):
    uid = "google-birthday-42@google.com"
    imported = m.ics_lesen(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:%s\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "DTEND;VALUE=DATE:19900518\r\nRRULE:FREQ=YEARLY\r\n"
        "SUMMARY:Alex\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n" % uid,
        quellenname="thunderbird-birthdays.ics")["termine"][0]
    # Some cache readers identify the master by a local row UID while retaining
    # the RFC series UID. EDS returns the authoritative RFC UID.
    imported["uid"] = "thunderbird-row-42"
    imported["icsSerienUid"] = uid
    import_source = imported["icsQuelleId"]

    remote = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
        "UID:%s\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "DTEND;VALUE=DATE:19900518\r\nRRULE:FREQ=YEARLY;BYMONTH=5;BYMONTHDAY=17\r\n"
        "EXDATE;VALUE=DATE:20900517\r\nSUMMARY:Alex\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n" % uid)

    result = sync(monkeypatch, [imported], remote)

    assert len(result["termine"]) == 1
    event = result["termine"][0]
    assert event["uid"] == uid
    assert event["datum"] == "1990-05-17" and event["zeit"] == ""
    assert event["icsReadOnly"] and event["icsReadOnlyGrund"] == "EDS"
    assert set(event["syncQuellen"]) == {
        import_source, "eds:google-calendar"}
    assert event["syncQuellen"][import_source]["id"] == "thunderbird-row-42"
    assert event["syncQuellen"]["eds:google-calendar"]["id"] == uid
    assert "thunderbird-birthdays.ics" in event["icsQuelleName"]
    assert "Google birthdays" in event["icsQuelleName"]
    assert "Google birthdays" in result["bericht"]


def test_same_yearly_all_day_content_with_distinct_uids_stays_separate(monkeypatch):
    imported = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:family-copy\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "RRULE:FREQ=YEARLY\r\nSUMMARY:Alex\r\nEND:VEVENT\r\n",
        quellenname="family.ics")["termine"][0]
    remote = (
        "BEGIN:VEVENT\r\nUID:work-copy\r\nDTSTART;VALUE=DATE:19900517\r\n"
        "RRULE:FREQ=YEARLY\r\nSUMMARY:Alex\r\nEND:VEVENT\r\n")

    result = sync(monkeypatch, [imported], remote)

    assert {event["uid"] for event in result["termine"]} == {
        "family-copy", "work-copy"}


def test_google_birthday_stays_calendar_event_during_eds_sync(monkeypatch):
    remote = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Familie\r\n"
        "BEGIN:VEVENT\r\nUID:bettina-google\r\n"
        "DTSTART;VALUE=DATE:19900826\r\nDTEND;VALUE=DATE:19900827\r\n"
        "RRULE:FREQ=YEARLY;BYMONTH=8;BYMONTHDAY=26\r\n"
        "SUMMARY:Bettina Jarosch Geburtstag\r\nCATEGORIES:Birthday\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n")

    result = sync(monkeypatch, [], remote)

    assert result["jahrestage"] == []
    assert len(result["termine"]) == 1
    event = result["termine"][0]
    assert event["uid"] == "bettina-google"
    assert event["datum"] == "1990-08-26"
    assert event["wiederholung"]["art"] == "yearly"
    assert event["syncKalenderUid"] == "google-calendar"
    assert "eds:google-calendar" in event["syncQuellen"]


def test_eds_imports_two_and_three_week_intervals(monkeypatch):
    remote = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:eds-14\r\nDTSTART:20260907T090000\r\n"
        "DTEND:20260907T100000\r\nRRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO\r\n"
        "SUMMARY:14 days\r\n"
        "END:VEVENT\r\nBEGIN:VEVENT\r\nUID:eds-21\r\n"
        "DTSTART:20260908T090000\r\nDTEND:20260908T100000\r\n"
        "RRULE:FREQ=WEEKLY;INTERVAL=3;BYDAY=TU\r\n"
        "SUMMARY:21 days\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")

    result = sync(monkeypatch, [], remote)

    intervals = {event["uid"]: event["wiederholung"]["intervall"]
                 for event in result["termine"]}
    assert intervals == {"eds-14": 2, "eds-21": 3}


def test_unassigned_local_import_is_not_uploaded_to_selected_google_calendar(monkeypatch):
    local = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:local-only\r\nDTSTART:20260826T100000\r\n"
        "SUMMARY:Local import\r\nEND:VEVENT\r\n",
        quellenname="Thunderbird")["termine"][0]
    mutations = []
    remote = (
        "BEGIN:VEVENT\r\nUID:remote-only\r\nDTSTART:20260827T100000\r\n"
        "SUMMARY:Remote event\r\nEND:VEVENT\r\n")

    result = sync(monkeypatch, [local], remote, mutations)

    assert {event["uid"] for event in result["termine"]} == {
        "local-only", "remote-only"}
    assert not [entry for entry in mutations if entry[0] == "create"]
    local_result = next(event for event in result["termine"]
                        if event["uid"] == "local-only")
    assert not local_result.get("syncKalenderUid")


def test_remote_deletion_requires_independent_eds_confirmation(monkeypatch):
    class Client:
        def get_objects_for_uid_sync(self, uid, cancellable):
            return True, [object()]

    local = {"uid": "still-there", "datum": "2026-08-26", "zeit": "10:00",
             "titel": "Keep", "geaendert": 10, "sync": True,
             "syncKalenderUid": "google-calendar"}
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", Registry)
    monkeypatch.setattr(m, "eds_kalender_client", lambda registry, uid: Client())
    monkeypatch.setattr(m, "eds_events_lesen", lambda client: [])
    probe = Probe()

    try:
        m.Fenster._sync_ausfuehren(probe, {
            "wahl": {"kalenderUid": "google-calendar",
                     "kalenderUids": ["google-calendar"]},
            "daten": {"termine": [local], "kontakte": [], "jahrestage": [],
                      "geloescht": {"termine": [], "kontakte": []},
                      "letzterSync": 100,
                      "letzteSyncs": {"kalender": {"google-calendar": 100}}}})
    except RuntimeError as error:
        assert str(error)
    else:
        raise AssertionError("an incomplete EDS list must not delete local events")


def test_local_cache_copies_of_same_birthday_are_merged_by_series_uid():
    payload = {"termine": [], "jahrestage": [
        {"uid": "birthday-series", "icsSerienUid": "birthday-series",
         "name": "Gottfried *65", "datum": "1965-08-05", "typ": "birthday",
         "icsQuelleName": "Evolution: google-cache", "icsQuelleId": "evolution:cache"},
        {"uid": "birthday-series-magnolie-instanz-1",
         "icsSerienUid": "birthday-series", "name": "Gottfried *65",
         "datum": "2026-08-05", "typ": "birthday",
         "icsQuelleName": "Thunderbird: Familie", "icsQuelleId": "thunderbird:family"},
    ]}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert len(payload["jahrestage"]) == 1
    event = payload["jahrestage"][0]
    assert event["datum"] == "1965-08-05"
    assert "Evolution: google-cache" in event["icsQuelleName"]
    assert "Thunderbird: Familie" in event["icsQuelleName"]


def test_birthday_dedup_never_changes_month_and_day():
    payload = {"termine": [], "jahrestage": [
        {"uid": "mia", "name": "Mia", "datum": "1990-08-12"},
        {"uid": "mia", "name": "Mia", "datum": "1985-03-04"},
    ]}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert [item["datum"] for item in payload["jahrestage"]] == [
        "1990-08-12", "1985-03-04"]


def test_appointment_and_anniversary_collections_are_never_cross_deduplicated():
    master = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:geb1\r\nDTSTART;VALUE=DATE:19900812\r\n"
        "RRULE:FREQ=YEARLY\r\nEXDATE;VALUE=DATE:20260812\r\n"
        "SUMMARY:Mia\r\nEND:VEVENT\r\n")["termine"][0]
    payload = {"termine": [master], "jahrestage": [
        {"uid": "geb1", "icsSerienUid": "geb1", "name": "Mia",
         "datum": "1990-08-12"}]}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert payload["termine"] == [master]
    assert len(payload["jahrestage"]) == 1


def test_sync_ignores_non_semantic_rrule_form():
    base = {"uid": "monat", "datum": "2026-08-11", "titel": "Monatsserie",
            "geaendert": 10, "wiederholung": {"art": "monthly", "bis": "",
            "ordinal": 2, "wochentag": "TU"}}
    remote = dict(base, wiederholung=dict(base["wiederholung"], rruleForm="byday"))

    assert m._sync_inhalt_hash(base, m.TERMIN_FELDER) == \
        m._sync_inhalt_hash(remote, m.TERMIN_FELDER)
    merged, creates, updates, deletes, counts = m.sync_merge(
        [dict(base, sync=True)], {"monat": remote}, [], 10, m.TERMIN_FELDER)
    assert len(merged) == 1 and not creates and not updates and not deletes
    assert counts["konflikte"] == 0


def test_local_appointment_and_anniversary_with_same_uid_appear_only_once():
    appointment = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:same-google-event\r\n"
        "DTSTART;VALUE=DATE:19650805\r\nRRULE:FREQ=YEARLY\r\n"
        "SUMMARY:Gottfried\r\nEND:VEVENT\r\n",
        quellenname="Thunderbird")["termine"][0]
    payload = {"termine": [appointment], "jahrestage": [
        {"uid": "same-google-event", "icsSerienUid": "same-google-event",
         "name": "Gottfried Geburtstag", "datum": "1965-08-05",
         "typ": "birthday", "icsQuelleName": "Evolution"}
    ]}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert len(payload["termine"]) == 1
    assert len(payload["jahrestage"]) == 1


def test_local_birthdays_with_distinct_external_uids_remain_separate():
    payload = {"termine": [], "jahrestage": [
        {"uid": "family-copy", "name": "Alex", "datum": "1990-05-17",
         "typ": "birthday"},
        {"uid": "work-copy", "name": "Alex", "datum": "1985-05-17",
         "typ": "birthday"},
    ]}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert [(item["uid"], item["datum"]) for item in payload["jahrestage"]] == [
        ("family-copy", "1990-05-17"), ("work-copy", "1985-05-17")]


def test_local_appointments_with_same_title_and_time_remain_separate():
    payload = {"termine": [
        {"uid": "first", "datum": "2026-08-17", "zeit": "09:00",
         "endZeit": "10:00", "titel": "Besprechung", "ort": "Büro"},
        {"uid": "second", "datum": "2026-08-17", "zeit": "09:00",
         "endZeit": "11:00", "titel": "Besprechung", "ort": "Praxis"},
    ], "jahrestage": []}

    m._lokale_kalender_dubletten_bereinigen(payload)

    assert [(item["uid"], item["ort"]) for item in payload["termine"]] == [
        ("first", "Büro"), ("second", "Praxis")]


def test_unbound_local_anniversary_is_uploaded_once(monkeypatch):
    class WritableClient:
        def is_readonly(self): return False

    mutations = []
    result = sync(monkeypatch, [], "", mutations, client=WritableClient(),
                  lokale_jahrestage=[{"uid": "birthday-local", "name": "Alex",
                      "datum": "--05-17", "typ": "birthday"}])

    creates = [value for operation, value in mutations if operation == "create"]
    assert len(creates) == 1
    assert "UID:birthday-local" in creates[0]
    assert "X-MAGNOLIE-DATE:--05-17" in creates[0]
    assert len(result["jahrestage"]) == 1
    assert set(result["jahrestage"][0]["syncQuellen"]) == {"eds:google-calendar"}


def test_successful_remote_deletion_keeps_recent_tombstone(monkeypatch):
    now = 1_800_000_000_000
    monkeypatch.setattr(m, "jetzt_ms", lambda: now)
    mutations = []
    remote = m.vevent_text({
        "uid": "deleted-event", "datum": "2026-08-25", "titel": "Gelöscht",
        "geaendert": now - 10_000})
    tombstone = {"uid": "deleted-event", "zeit": now - 1_000,
                 "syncKalenderUid": "google-calendar"}

    result = sync(monkeypatch, [], remote, mutations, tombstones=[tombstone])

    assert mutations == [("delete", "deleted-event")]
    assert result["geloescht"]["termine"] == [tombstone]


def test_eds_modify_failure_keeps_cursor_and_exposes_diagnostic(monkeypatch):
    remote = {"uid": "meeting", "datum": "2026-09-01", "zeit": "10:00",
              "titel": "Remote", "geaendert": 100}
    remote_ics = m.vevent_text(remote)
    remote_time = m.ics_lesen(remote_ics)["termine"][0]["geaendert"]
    local = dict(remote, titel="Local", geaendert=remote_time + 100_000, sync=True,
                 syncKalenderUid="google-calendar")

    result = sync(monkeypatch, [local], remote_ics,
                  fail_operation="modify", last_sync=100)

    assert result["ok"] is False
    assert "Google birthdays" in result["fehler"]
    assert "GOA permission denied" in result["fehler"]
    assert result["letzterSync"] == 100
    assert result["letzteSyncs"]["kalender"]["google-calendar"] == 100
    assert result["termine"][0]["sync"] is False


def test_tombstone_grace_period_deduplicates_and_expires_only_old_valid_marks():
    now = 1_800_000_000_000
    fresh = now - m.GRABSTEIN_SCHONFRIST_MS + 1
    old = now - m.GRABSTEIN_SCHONFRIST_MS
    result = m.grabsteine_behalten([
        {"uid": "fresh", "zeit": fresh}, {"uid": "fresh", "zeit": fresh - 1},
        {"uid": "old", "zeit": old}, {"uid": "damaged", "zeit": "?"},
    ], now)

    assert {item["uid"] for item in result} == {"fresh", "damaged"}


def test_contact_tombstones_survive_success_and_keep_failed_remote_deletions():
    now = 1_800_000_000_000
    result = m.kontakt_grabsteine_nach_loeschung([
        {"uid": "already-absent", "zeit": now - 1_000},
        {"uid": "deleted", "zeit": now - 2_000},
        {"uid": "failed", "zeit": now - 3_000},
    ], ["deleted", "failed"], {"deleted"}, now)

    assert {item["uid"] for item in result} == {
        "already-absent", "deleted", "failed"}
    assert next(item for item in result if item["uid"] == "failed")["zeit"] == now - 3_000


def test_remote_calendar_update_replaces_complete_scheduling_metadata():
    local = {"uid": "metadata", "datum": "2026-09-01", "zeit": "10:00", "titel": "Old",
             "geaendert": 1000, "sync": True, "icsTimezones": [["TZID:Old"]],
             "icsRangeOverrides": [["SUMMARY:Old override"]], "ort": "Old room"}
    remote = {"uid": "metadata", "datum": "2026-09-01", "zeit": "10:00", "titel": "Updated",
              "geaendert": 3000, "icsTimezones": [["TZID:New"]],
              "icsAnzeigeZeitzone": "UTC", "icsRoundtrip": ["LOCATION:New room"]}
    merged, creates, updates, deletes, _counts = m.sync_merge(
        [local], {"metadata": remote}, [], 2000, m.TERMIN_FELDER)
    assert not creates and not updates and not deletes
    assert merged[0]["icsTimezones"] == remote["icsTimezones"]
    assert merged[0]["icsAnzeigeZeitzone"] == "UTC"
    assert "icsRangeOverrides" not in merged[0] and "ort" not in merged[0]
    changed_zone = dict(remote, icsTimezones=[["TZID:Changed"]])
    assert m._sync_inhalt_hash(remote, m.TERMIN_FELDER) != m._sync_inhalt_hash(changed_zone, m.TERMIN_FELDER)
    assert m._sync_inhalt_format(m.TERMIN_FELDER) != m._sync_inhalt_format(m.AUFGABE_FELDER)


def test_complex_duplicate_retains_combined_source_label():
    first = {"uid": "same", "datum": "2026-09-01", "titel": "Same", "icsQuelleId": "a", "icsQuelleName": "A"}
    second = dict(first, icsQuelleId="b", icsQuelleName="B", icsKomplex=True)
    result = m._lokale_kalender_dubletten_bereinigen({"termine": [first, second]})
    assert len(result["termine"]) == 1
    assert result["termine"][0]["icsQuelleName"] == "A + B"
    assert set(result["termine"][0]["syncQuellen"]) == {"a", "b"}


def test_local_duplicate_cleanup_does_not_discard_different_details():
    first = {"uid": "same", "datum": "2026-09-01", "titel": "Same",
             "icsQuelleId": "a", "icsQuelleName": "A", "notiz": "Source A"}
    second = dict(first, icsQuelleId="b", icsQuelleName="B", notiz="Source B", icsKomplex=True)
    result = m._lokale_kalender_dubletten_bereinigen({"termine": [first, second]})
    assert [item["notiz"] for item in result["termine"]] == ["Source A", "Source B"]
    compatible = dict(second)
    compatible.pop("notiz")
    result = m._lokale_kalender_dubletten_bereinigen({"termine": [dict(first), compatible]})
    assert len(result["termine"]) == 1 and result["termine"][0]["notiz"] == "Source A"


def test_equal_timestamp_conflict_preserves_both_versions_and_converges():
    local = {"uid": "meeting", "datum": "2026-09-01", "zeit": "10:00",
             "titel": "Local title", "geaendert": 1000, "sync": True}
    remote = {"uid": "meeting", "datum": "2026-09-01", "zeit": "10:00",
              "titel": "Remote title", "geaendert": 1000}

    merged, creates, updates, deletes, counts = m.sync_merge(
        [local], {"meeting": remote}, [], 0, m.TERMIN_FELDER)

    assert not creates and not updates and not deletes
    assert counts["konflikte"] == 1
    assert merged[0]["titel"] == "Remote title"
    assert merged[0]["syncKonflikte"][0]["lokal"]["titel"] == "Local title"
    assert merged[0]["syncKonflikte"][0]["remote"]["titel"] == "Remote title"
    assert m._("%d synchronization conflict") % 1 in m._sync_satz(
        "Appointments", counts, 0)

    again, creates, updates, deletes, counts = m.sync_merge(
        merged, {"meeting": remote}, [], 1000, m.TERMIN_FELDER)
    assert len(again) == 1 and len(again[0]["syncKonflikte"]) == 1
    assert not creates and not updates and not deletes and counts["konflikte"] == 0


def test_missing_last_modified_and_sequence_are_used_without_losing_conflict():
    parsed = m.ics_lesen(
        "BEGIN:VEVENT\r\nUID:no-clock\r\nSEQUENCE:4\r\nDTSTAMP:20260901T100000Z\r\n"
        "DTSTART:20260902T100000\r\nSUMMARY:Remote\r\nEND:VEVENT\r\n"
    )["termine"][0]
    assert parsed["icsSequence"] == 4 and parsed["icsAenderungszeitFehlt"]
    assert "SEQUENCE:4\r\n" in m.vevent_text(parsed)

    local = dict(parsed, titel="Local", geaendert=parsed["geaendert"] + 50,
                 icsSequence=4, sync=True)
    merged, _creates, updates, _deletes, counts = m.sync_merge(
        [local], {"no-clock": parsed}, [], local["geaendert"], m.TERMIN_FELDER)
    assert merged[0]["titel"] == "Remote" and not updates
    assert merged[0]["syncKonflikte"][0]["lokal"]["titel"] == "Local"
    assert counts["konflikte"] == 1

    locally_changed = dict(parsed, titel="Local after sync",
                           geaendert=parsed["geaendert"] + 50, sync=True)
    merged, _creates, updates, _deletes, counts = m.sync_merge(
        [locally_changed], {"no-clock": parsed}, [], parsed["geaendert"],
        m.TERMIN_FELDER)
    assert updates == merged and merged[0]["titel"] == "Local after sync"
    assert merged[0]["syncKonflikte"][0]["remote"]["titel"] == "Remote"
    assert counts["konflikte"] == 1

    higher = dict(parsed, titel="Sequence wins", icsSequence=5,
                  geaendert=parsed["geaendert"] - 50)
    merged, _creates, updates, _deletes, counts = m.sync_merge(
        [dict(parsed, titel="Old sequence", sync=True)],
        {"no-clock": higher}, [], 0, m.TERMIN_FELDER)
    assert merged[0]["titel"] == "Sequence wins" and not updates
    assert counts["konflikte"] == 0

    local_newer = dict(parsed, titel="Local later",
                       geaendert=parsed["geaendert"] + 2000, sync=True)
    remote_older = dict(parsed, icsAenderungszeitFehlt=False)
    merged, _creates, updates, _deletes, _counts = m.sync_merge(
        [local_newer], {"no-clock": remote_older}, [], 0, m.TERMIN_FELDER)
    assert updates == merged and merged[0]["icsSequence"] == 5
    assert "SEQUENCE:5\r\n" in m.vevent_text(merged[0])


def test_eds_import_matching_uses_external_identifier_index(monkeypatch):
    size = 120
    local = []
    remote = []
    for index in range(size):
        uid = "indexed-%d" % index
        text = ("BEGIN:VEVENT\r\nUID:%s\r\nDTSTART:20260902T100000\r\n"
                "SUMMARY:Indexed %d\r\nEND:VEVENT\r\n" % (uid, index))
        local.append(m.ics_lesen(text, quellenname="import.ics")["termine"][0])
        remote.append(text)

    calls = 0
    original = m._termin_eds_ics_identisch

    def counted(left, right):
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr(m, "_termin_eds_ics_identisch", counted)
    monkeypatch.setattr(m, "eds_laden", lambda: True)
    monkeypatch.setattr(m, "eds_registry", Registry)
    monkeypatch.setattr(m, "eds_kalender_client", lambda registry, uid: "google-calendar")
    monkeypatch.setattr(m, "eds_events_lesen", lambda _client: remote)
    monkeypatch.setattr(m, "eds_event_anlegen", lambda *_args: None)
    monkeypatch.setattr(m, "eds_event_aendern", lambda *_args: None)
    monkeypatch.setattr(m, "eds_event_loeschen", lambda *_args: None)
    probe = Probe()
    m.Fenster._sync_ausfuehren(probe, {
        "wahl": {"kalenderUid": "google-calendar",
                 "kalenderUids": ["google-calendar"]},
        "daten": {"termine": local, "kontakte": [], "jahrestage": [],
                  "geloescht": {"termine": [], "kontakte": []},
                  "letzterSync": 0, "letzteSyncs": {"kalender": {}}}})

    assert len(probe.nutzlast["termine"]) == size
    assert calls <= size * 2
