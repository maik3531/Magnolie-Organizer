"""Positive regressions for the independently reviewed native scheduling paths."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from modul_laden import quellmodul_laden

m = quellmodul_laden('native_recurrence_regressions', Path(__file__).parents[1] / 'bin/magnolie-organizer')


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setitem(m._REGIONAL, 'timeZone', 'UTC')


def imported(lines, task=False):
    kind = 'VTODO' if task else 'VEVENT'
    data = m.ics_lesen('BEGIN:' + kind + '\nUID:fixture\nSUMMARY:Fixture\n' + lines + '\nEND:' + kind)
    for item in data['aufgaben' if task else 'termine']:
        item['id'] = item['uid']
    return data


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("task", [False, True])
@pytest.mark.parametrize("mode", ["absolute", "series-outside-window", "relative-start", "relative-end"])
def test_ics_display_trigger_time_and_replay(mode, task, background):
    trigger = {
        "absolute": "TRIGGER;VALUE=DATE-TIME:20261127T103017Z",
        "series-outside-window": "TRIGGER;VALUE=DATE-TIME:20261127T103017Z",
        "relative-start": "TRIGGER:-PT2H",
        "relative-end": "TRIGGER;RELATED=END:-PT3H",
    }[mode]
    day = "20260801" if mode == "series-outside-window" else (
        "20261127" if mode.startswith("relative") else "20261129")
    recurrence = "\nRRULE:FREQ=DAILY;COUNT=4" if mode == "series-outside-window" else ""
    data = imported(f"DTSTART:{day}T123017Z\nDURATION:PT1H{recurrence}\n"
                    f"BEGIN:VALARM\nACTION:DISPLAY\n{trigger}\nEND:VALARM", task=task)
    data["einstellungen"] = {"sicherheit": {"erinnernTrotzKennwort": True}}
    if background:
        data = m.erinnerungsdaten_auswaehlen(data)

    def run(when, state=None):
        if task:
            return m.faellige_aufgaben(data, when, {"faellig": [], "verpasst": [],
                                                    "zustand": state or {"gemeldet": {}}})
        return m.faellige_erinnerungen(data, when, state or {}, vorlauf=0)

    now = datetime(2026, 11, 27, 10, 30, 17, tzinfo=timezone.utc)
    early = run(now - timedelta(seconds=1))
    assert not early["faellig"] and not early["verpasst"]
    due = run(now)
    assert len(due["faellig"]) == 1 and not due.get("recurrenceErrors")
    restored = json.loads(json.dumps(due["zustand"]))
    again = run(now + timedelta(minutes=1), restored)
    assert not again["faellig"] and not again["verpasst"]
    if not task:
        assert m.naechster_weckzeitpunkt(data, now - timedelta(seconds=1), vorlauf=0) == now.replace(tzinfo=None)


@pytest.mark.parametrize("task", [False, True])
def test_absolute_alarm_identity_survives_projection_and_zone_change(task, monkeypatch):
    start = datetime(2026, 10, 25, 0, 15, 7, tzinfo=timezone.utc)
    end = start.replace(second=41)
    alarms = "".join(
        "\nBEGIN:VALARM\nACTION:DISPLAY\nTRIGGER;VALUE=DATE-TIME:" +
        instant.strftime("%Y%m%dT%H%M%SZ") + "\nEND:VALARM"
        for instant in (start, start, end))
    data = imported("DTSTART:20261201T100000Z\nDURATION:PT1H" + alarms, task=task)
    data["einstellungen"] = {"sicherheit": {"erinnernTrotzKennwort": True}}
    monkeypatch.setitem(m._REGIONAL, "timeZone", "Europe/Berlin")
    projected = m.erinnerungsdaten_auswaehlen(data)

    def run(source, now, state=None):
        if task:
            return m.faellige_aufgaben(source, now, {"faellig": [], "verpasst": [],
                                                      "zustand": state or {"gemeldet": {}}})
        return m.faellige_erinnerungen(source, now, state or {}, vorlauf=0)

    first = run(projected, start)
    assert len(first["faellig"]) == 1
    monkeypatch.setitem(m._REGIONAL, "timeZone", "UTC")
    second = run(data, end, first["zustand"])
    assert len(second["faellig"]) == 1
    assert second["faellig"][0]["id"] != first["faellig"][0]["id"]


@pytest.mark.parametrize("task,kind", [
    (False, "cancelled"), (False, "confidential"), (False, "invalid"), (False, "email"),
    (True, "cancelled"), (True, "completed"), (True, "confidential"), (True, "invalid"), (True, "email"),
])
def test_absolute_alarm_respects_exclusions(task, kind):
    status = {"cancelled": "\nSTATUS:CANCELLED", "completed": "\nSTATUS:COMPLETED"}.get(kind, "")
    trigger = "20261127T103017" + ("" if kind == "invalid" else "Z")
    action = "EMAIL" if kind == "email" else "DISPLAY"
    data = imported(f"DTSTART:20261129T120000Z\nDURATION:PT1H{status}\n"
                    f"BEGIN:VALARM\nACTION:{action}\nTRIGGER;VALUE=DATE-TIME:{trigger}\nEND:VALARM", task=task)
    data["einstellungen"] = {"sicherheit": {"erinnernTrotzKennwort": True}}
    if kind == "confidential":
        data["aufgaben" if task else "termine"][0]["vertraulich"] = True
    selected = m.erinnerungsdaten_auswaehlen(data)
    now = datetime(2026, 11, 27, 10, 30, 17, tzinfo=timezone.utc)
    for source in (selected,) if kind == "confidential" else (data, selected):
        result = m.faellige_aufgaben(source, now) if task else m.faellige_erinnerungen(source, now, {}, vorlauf=0)
        assert not result["faellig"] and not result["verpasst"]


def test_absolute_alarm_on_undated_task_schedules_a_wakeup():
    data = imported("BEGIN:VALARM\nACTION:DISPLAY\nTRIGGER;VALUE=DATE-TIME:20261127T103017Z\nEND:VALARM",
                    task=True)
    now = datetime(2026, 11, 27, 10, 30, 17, tzinfo=timezone.utc)
    assert len(m.faellige_aufgaben(data, now)["faellig"]) == 1
    assert m.naechster_weckzeitpunkt(data, now - timedelta(seconds=1), als_instant=True) == now
    data["einstellungen"] = {"erinnerung": {"aufgaben": False}}
    assert m.naechster_weckzeitpunkt(data, now - timedelta(seconds=1), als_instant=True) is None


@pytest.mark.parametrize("task", [False, True])
def test_absolute_alarm_upgrades_legacy_minute_without_consuming_new_seconds(task):
    alarms = "\n".join(
        f"BEGIN:VALARM\nACTION:DISPLAY\nTRIGGER;VALUE=DATE-TIME:20261127T1030{second}Z\nEND:VALARM"
        for second in ("00", "17"))
    data = imported("DTSTART:20261129T123000Z\nDURATION:PT1H\n" + alarms, task=task)
    old_key = ("af-fixture@2026-11-29T12:30:00+00:00-2026-11-29-1330-alarm-START-2026-11-27 10:30" if task
               else "fixture@202611291230:v2:alarm-absolut-202611271030")
    state = {"gemeldet": {old_key: "2026-11-27 10:30"}}
    now = datetime(2026, 11, 27, 10, 30, 17, tzinfo=timezone.utc)
    result = (m.faellige_aufgaben(data, now, {"faellig": [], "verpasst": [], "zustand": state}) if task
              else m.faellige_erinnerungen(data, now, state, vorlauf=0))
    assert len(result["faellig"]) == 1
    assert "10:30:17+00:00" in result["faellig"][0]["id"]
    assert any("10:30:00+00:00" in key for key in result["zustand"]["gemeldet"])


def test_fold_and_gap_reminder_instants(monkeypatch):
    monkeypatch.setitem(m._REGIONAL, 'timeZone', 'Europe/Berlin')
    data = imported('DTSTART:20261025T013000Z\nRRULE:FREQ=DAILY;COUNT=2')
    first = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
    second = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
    early = m.faellige_erinnerungen(data, first, {}, vorlauf=0)
    assert not early['faellig'] and not early['verpasst']
    due = m.faellige_erinnerungen(data, second, early['zustand'], vorlauf=0)
    assert len(due['faellig']) == 1
    assert not m.faellige_erinnerungen(data, second, due['zustand'], vorlauf=0)['faellig']
    projected = m._ics_vorkommen(data['termine'][0], first, second)[0]
    assert projected['icsStartUtc'] == int(second.timestamp() * 1000)
    assert projected['zeit'] == '02:30' and not projected['icsAllDay']
    old_mark = m._termin_meldungen(projected, projected['id'], m._termin_zeitpunkt(projected), 0)[0][0]
    assert due['faellig'][0]['id'] == old_mark
    both = imported('DTSTART:20261025T003000Z\nRDATE:20261025T013000Z')
    early = m.faellige_erinnerungen(both, first, {}, vorlauf=0)
    late = m.faellige_erinnerungen(both, second, early['zustand'], vorlauf=0)
    assert len(early['faellig']) == len(late['faellig']) == 1
    assert early['faellig'][0]['id'] != late['faellig'][0]['id']
    gap = imported('DTSTART;TZID=Europe/Berlin:20260329T033000\nRRULE:FREQ=DAILY;COUNT=2')
    assert len(m.faellige_erinnerungen(gap, datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc), {}, vorlauf=60)['faellig']) == 1
    assert m.naechster_weckzeitpunkt(gap, datetime(2026, 3, 28, 23, tzinfo=timezone.utc), vorlauf=60) == datetime(2026, 3, 29, 1, 30)


def test_task_fold_and_second_precision(monkeypatch):
    monkeypatch.setitem(m._REGIONAL, 'timeZone', 'Europe/Berlin')
    data = imported('DTSTART:20261025T012900Z\nDUE:20261025T013030Z\nRRULE:FREQ=DAILY;COUNT=2', task=True)
    data['aufgaben'][0]['erinnern'] = True
    assert not m.faellige_aufgaben(data, datetime(2026, 10, 25, 0, 30, 30, tzinfo=timezone.utc))['faellig']
    result = m.faellige_aufgaben(data, datetime(2026, 10, 25, 1, 30, 30, tzinfo=timezone.utc))
    assert len(result['faellig']) == 1 and result['faellig'][0]['zeit'] == '02:30:30'


@pytest.mark.parametrize('task', [False, True])
def test_old_period_is_excluded(task):
    item = {'icsRoundtrip': ['DTSTART:20210101T090000Z', 'DURATION:PT1H',
        'RDATE;VALUE=PERIOD:20260801T090000Z/PT960H', 'EXRULE:FREQ=DAILY']}
    assert m._ics_vorkommen(item, datetime(2026, 9, 8), datetime(2026, 9, 9), aufgabe=task, ueberlappung=True) == []


@pytest.mark.parametrize('task', [False, True])
@pytest.mark.parametrize('rule', ['FREQ=SECONDLY', 'FREQ=INVALID', 'FREQ=DAILY;INTERVAL=broken'])
def test_failed_series_isolated_without_success_status(task, rule):
    data = imported('DTSTART:20260901T090000Z\nDURATION:PT1S\nRRULE:' + rule, task=task)
    field = 'aufgaben' if task else 'termine'
    data[field][0]['erinnern'] = True
    healthy = {'id': 'healthy', 'titel': 'Healthy', 'erinnern': True,
        'faellig': '2026-09-08', 'faelligZeit': '09:00', 'datum': '2026-09-08', 'zeit': '09:00'}
    data[field].append(healthy)
    result = m.faellige_aufgaben(data, datetime(2026, 9, 8, 9)) if task else m.faellige_erinnerungen(data, datetime(2026, 9, 8, 9), {}, vorlauf=0)
    assert any(value['titel'] == 'Healthy' for value in result['faellig'])
    assert len(result['recurrenceErrors']) == 1
    assert not result['recurrenceErrors'][0]['retryable']
    assert all('fixture' not in key for key in result['zustand']['gemeldet'])


def test_prefix_progress_survives_scheduler_retry(monkeypatch):
    import magnolie_recurrence as recurrence
    recurrence._prefix_state.cache_clear()
    monkeypatch.setattr(recurrence, 'MAX_PERIODS', 100)
    data = imported('DTSTART;TZID=Europe/Berlin:20210101T090000\nDURATION:PT1S\nRRULE:FREQ=DAILY;COUNT=3000')
    result = m.faellige_erinnerungen(data, datetime(2022, 1, 1, 8), {}, vorlauf=0)
    assert result['recurrenceErrors'][0]['retryable']
    for _ in range(8):
        result = m.faellige_erinnerungen(data, datetime(2022, 1, 1, 8), {}, vorlauf=0)
        if not result['recurrenceErrors']:
            break
    assert not result['recurrenceErrors'] and result['faellig']


def test_task_thirty_day_alarm():
    data = imported('DTSTART:20261008T090000Z\nDUE:20261008T170000Z\nRRULE:FREQ=YEARLY\nBEGIN:VALARM\nACTION:DISPLAY\nTRIGGER:-P30D\nEND:VALARM', task=True)
    assert len(m.faellige_aufgaben(data, datetime(2026, 9, 8, 9))['faellig']) == 1


def test_runtime_delivers_and_persists_healthy_without_all_success(monkeypatch):
    data = imported('DTSTART:20260901T090000Z\nDURATION:PT1S\nRRULE:FREQ=SECONDLY')
    data['termine'].append({'id': 'healthy', 'titel': 'Healthy', 'datum': '2026-09-08', 'zeit': '09:00'})
    data['einstellungen'] = {'erinnerung': {'an': True, 'vorlauf': 0}}
    delivered, saved = [], []
    monkeypatch.setattr(m, 'wecker_lebt', lambda: False)
    monkeypatch.setattr(m, 'sitzungsumgebung_uebernehmen', lambda: None)
    monkeypatch.setattr(m, 'daten_lesen_gepuffert', lambda: data)
    monkeypatch.setattr(m, 'erinnerung_zustand_lesen', lambda: {})
    monkeypatch.setattr(m, 'erinnerung_zustand_schreiben', lambda value: saved.append(value) or True)
    monkeypatch.setattr(m, 'wecker_notiz', lambda value: None)
    monkeypatch.setattr(m, 'ton_abspielen', lambda **kwargs: None)
    monkeypatch.setattr(m, 'melden', lambda *args: delivered.append(args) or 'system')
    result = m.erinnerungslauf(datetime(2026, 9, 8, 9))
    assert result['gemeldet'] == len(delivered) == 1
    assert result['fehler'] and len(result['recurrenceErrors']) == 1
    assert len(saved) == 1 and len(saved[0]['gemeldet']) == 1


@pytest.mark.parametrize('kind, date, occurrence', [('monthly', '2021-01-15', '2026-09-15'), ('yearly', '2021-09-15', '2027-09-15')])
def test_native_interval_match_seek_and_export(kind, date, occurrence):
    item = {'datum': date, 'zeit': '09:00', 'wiederholung': {'art': kind, 'intervall': 2}}
    target = datetime.fromisoformat(occurrence)
    assert m.wiederholung_trifft(item, target)
    assert m._naechster_serientag(item, target, target) == target
    assert 'RRULE:FREQ=' + kind.upper() + ';INTERVAL=2' in m.ics_schreiben_termine([item])


def test_cancellation_without_start_is_identity_not_appointment():
    data = m.ics_lesen('BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Regression//EN\nMETHOD:CANCEL\nBEGIN:VEVENT\nUID:cancel\nDTSTAMP:20260908T000000Z\nSEQUENCE:1\nORGANIZER:mailto:test@example.invalid\nATTENDEE:mailto:attendee@example.invalid\nRECURRENCE-ID:20260908T090000Z\nSTATUS:CANCELLED\nEND:VEVENT\nEND:VCALENDAR')
    assert data['uebersprungen'] == 0 and len(data['termine']) == 1
    assert data['termine'][0]['icsSerienUid'] == 'cancel'
    assert m._ics_vorkommen(data['termine'][0], datetime(2026, 9, 8), datetime(2026, 9, 9)) == []


@pytest.mark.parametrize('lag', [7, 30])
@pytest.mark.parametrize('related,hour', [('START', 9), ('END', 10)])
@pytest.mark.parametrize('task', [False, True])
def test_after_event_alarm_is_delivered_once(lag, related, hour, task):
    from datetime import timedelta
    data = imported('DTSTART:20260901T090000Z\nDURATION:PT1H\nBEGIN:VALARM\n'
                    'ACTION:DISPLAY\nTRIGGER;RELATED=' + related + ':P' + str(lag) + 'D\nEND:VALARM', task=task)
    now = datetime(2026, 9, 1, hour, tzinfo=timezone.utc) + timedelta(days=lag)
    def run(when, state=None):
        return (m.faellige_aufgaben(data, when, {'faellig': [], 'verpasst': [],
                'zustand': state or {'gemeldet': {}}}) if task else
                m.faellige_erinnerungen(data, when, state or {}, vorlauf=0))
    result = run(now)
    assert len(result['faellig']) == 1 and not result.get('recurrenceErrors')
    again = run(now + timedelta(minutes=1), result['zustand'])
    assert not again['faellig'] and not again['verpasst']
    missed = run(now + timedelta(days=1))
    assert len(missed['verpasst']) == 1
    if not task:
        assert m.naechster_weckzeitpunkt(data, now - timedelta(hours=1), vorlauf=0) == now.replace(tzinfo=None)


@pytest.mark.parametrize('bad_first', [False, True])
def test_bad_recurrence_does_not_remove_healthy_wake_time(bad_first):
    data = imported('DTSTART:20210101T090000Z\nRRULE:FREQ=INVALID')
    healthy = {'id': 'healthy', 'titel': 'Healthy', 'datum': '2026-09-11', 'zeit': '09:00'}
    data['termine'].insert(1 if bad_first else 0, healthy)
    errors = []
    assert m.naechster_weckzeitpunkt(data, datetime(2026, 9, 10, 12),
                                    vorlauf=15, fehler=errors) == datetime(2026, 9, 11, 8, 45)
    assert len(errors) == 1 and errors[0]['id'] == 'fixture'
