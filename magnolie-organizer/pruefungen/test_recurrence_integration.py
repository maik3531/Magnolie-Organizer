"""Real codecs, launcher projection, both rendered calendars and native C# engine."""
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from modul_laden import quellmodul_laden

ROOT = Path(__file__).parents[2]
CONTRACTS = ROOT / 'contracts'
if not (CONTRACTS / 'recurrence-integration.json').is_file():
    CONTRACTS = Path(__file__).parents[1] / 'contracts'
FIXTURES = json.loads((CONTRACTS / 'recurrence-integration.json').read_text())
m = quellmodul_laden('recurrence_integration_launcher', Path(__file__).parents[1] / 'bin/magnolie-organizer')


def native(test, expand=True):
    m._REGIONAL['timeZone'] = test['zone']
    text = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + '\r\n'.join(line for block in test['components'] for line in block) + '\r\nEND:VCALENDAR\r\n'
    data = m.ics_lesen(text, quellen_id='fixture', jahrestage_als_termine=True)
    for index, components in enumerate(test.get('additionalCalendars', [])):
        extra = m.ics_lesen('BEGIN:VCALENDAR\nVERSION:2.0\n' + '\n'.join(line for block in components for line in block) + '\nEND:VCALENDAR', quellen_id='fixture-' + str(index), jahrestage_als_termine=True)
        for field in ('termine', 'aufgaben'):
            data[field].extend(extra[field])
    task = test.get('task', False)
    items = data['aufgaben' if task else 'termine']
    if not expand:
        return [], items
    lower, upper = (datetime.fromisoformat(test[key].replace('Z', '+00:00')) for key in ('lower', 'upper'))
    values = []
    for item in items:
        for value in m._ics_vorkommen(item, lower, upper, aufgabe=task):
            start = datetime.fromisoformat(value['startDatum' if task else 'datum'] + 'T' + (value['startZeit' if task else 'zeit'] or '00:00'))
            end = datetime.fromisoformat(value['faellig' if task else 'endDatum'] + 'T' + (value['faelligZeit' if task else 'endZeit'] or '00:00'))
            if not task and not value['zeit']:
                end += timedelta(days=1)
            values.append(start.isoformat() + '/' + end.isoformat())
    return sorted(values), items


@pytest.mark.parametrize('test', [test for test in FIXTURES if not test.get('expectedError')], ids=lambda test: test['name'])
def test_launcher_codec_and_window_partitions(test):
    values, items = native(test)
    assert values == test['expected']
    lower, upper = (datetime.fromisoformat(test[key].replace('Z', '+00:00')) for key in ('lower', 'upper'))
    parts = []
    while lower <= upper:
        partition = dict(test, lower=lower.isoformat(), upper=min(upper, lower + timedelta(days=2, seconds=-1)).isoformat())
        parts.extend(native(partition)[0])
        lower += timedelta(days=2)
    assert sorted(parts) == values
    task = test.get('task', False)
    for item in items:
        item['erinnern'] = True
        item['id'] = item['uid']
    data = {'aufgaben' if task else 'termine': items, 'einstellungen': {'sicherheit': {'erinnernTrotzKennwort': True}, 'regional': {'timeZone': test['zone']}}}
    snapshot = m.erinnerungsdaten_auswaehlen(data)
    for expected in values:
        start, end = map(datetime.fromisoformat, expected.split('/'))
        now = end if task else start if any(item.get('zeit') for item in items) else start.replace(hour=8)
        due = (m.faellige_aufgaben(snapshot, now) if task else m.faellige_erinnerungen(snapshot, now, {}, vorlauf=0))
        assert due['faellig'], (test['name'], expected)
        if test.get('endAlarm'):
            due = m.faellige_erinnerungen(snapshot, end - timedelta(minutes=30), {}, vorlauf=0)
            assert any('alarm-END-30' in value['id'] for value in due['faellig']), due


def test_task_start_and_end_alarms_keep_independent_recurrence_anchors():
    m._REGIONAL['timeZone'] = 'UTC'
    data = m.ics_lesen('BEGIN:VTODO\nUID:alarm-task\nSUMMARY:Alarms\nDTSTART:20260901T090000Z\nDUE:20260903T170000Z\nRRULE:FREQ=DAILY;COUNT=2\n'
        'BEGIN:VALARM\nACTION:DISPLAY\nTRIGGER:-PT1H\nEND:VALARM\nBEGIN:VALARM\nACTION:DISPLAY\nTRIGGER;RELATED=END:-PT30M\nEND:VALARM\nEND:VTODO')
    for item in data['aufgaben']:
        item['id'] = item['uid']
    data['einstellungen'] = {'sicherheit': {'erinnernTrotzKennwort': True}}
    for candidate in (data, m.erinnerungsdaten_auswaehlen(data)):
        starts = m.faellige_aufgaben(candidate, datetime(2026, 9, 2, 8))
        ends = m.faellige_aufgaben(candidate, datetime(2026, 9, 4, 16, 30))
        assert any('alarm-START-60' in value['id'] and value['datum'] == '2026-09-04' for value in starts['faellig'])
        assert any('alarm-END-30' in value['id'] and value['datum'] == '2026-09-04' for value in ends['faellig'])


@pytest.mark.parametrize('test', [test for test in FIXTURES if test.get('expectedError')], ids=lambda test: test['name'])
def test_launcher_rejects_invalid_recurrence_without_discarding_source(test):
    from magnolie_recurrence import RecurrenceLimitError
    with pytest.raises((ValueError, KeyError, RecurrenceLimitError)):
        native(test)
    assert native(test, expand=False)[1]


def test_second_precision_reminder_identity_and_next_wakeup():
    test = next(test for test in FIXTURES if test['name'] == 'minutely-selector')
    _, items = native(test)
    due = m.faellige_erinnerungen({'termine': items}, datetime(2026, 9, 7, 9, 7), {}, vorlauf=0)
    keys = [value['id'] for value in due['faellig'] + due['verpasst']]
    assert len(set(keys)) == len(keys) == 3
    assert m.naechster_weckzeitpunkt({'termine': items}, datetime(2026, 9, 7, 9, 0, 1), vorlauf=0) == datetime(2026, 9, 7, 9, 0, 30)


def test_nonrecurring_task_due_remains_editable():
    task = m.ics_lesen('BEGIN:VTODO\nUID:due-task\nSUMMARY:Due\nDUE;VALUE=DATE:20260101\nEND:VTODO')['aufgaben'][0]
    task['faellig'] = '2026-12-24'
    exported = m.ics_schreiben_aufgaben([task])
    assert 'DUE;VALUE=DATE:20261224' in exported and '20260101' not in exported


def check_cross_language(fixtures):
    dotnet = os.environ.get('DOTNET') or shutil.which('dotnet') or '/tmp/opencode/dotnet-8.0.408/dotnet'
    project = ROOT / 'magnolie-organizer-windows/tests/CoreTests.csproj'
    assert project.is_file(), 'Explicit four-engine suite requires the complete canonical repository and restored .NET test dependencies'
    with tempfile.TemporaryDirectory(prefix='f13-recurrence-', dir='/tmp/opencode') as output:
        built = subprocess.run([dotnet, 'build', str(project), '--no-restore', '--nologo', '-v:q', '-p:OutputPath=' + output + '/bin/',
            '-p:IntermediateOutputPath=' + output + '/obj/'], capture_output=True, text=True)
        assert built.returncode == 0, built.stdout + built.stderr
        probe = subprocess.run([dotnet, output + '/bin/CoreTests.dll', '--recurrence-json'], input=json.dumps(fixtures), capture_output=True, text=True)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    windows = json.loads(probe.stdout)
    payload = []
    for test, result in zip(fixtures, windows):
        if test.get('expectedError'):
            from magnolie_recurrence import RecurrenceLimitError
            with pytest.raises((ValueError, KeyError, RecurrenceLimitError)):
                native(test)
            _, items = native(test, expand=False)
            assert items and result['error']
            payload.extend([dict(test, items=items), dict(test, items=result['items'])])
            continue
        linux, items = native(test)
        assert result['values'] == linux == test['expected'], test['name']
        # Exercise both native parser models through normalization and both web UIs.
        payload.extend([dict(test, items=items), dict(test, items=result['items'])])
        if test.get('roundtrip'):
            exported = m.ics_schreiben_aufgaben(items) if test.get('task') else m.ics_schreiben_termine(items)
            for text in (exported, result['exported']):
                parsed = m.ics_lesen(text, quellen_id='fixture', jahrestage_als_termine=True)
                payload.append(dict(test, items=parsed['aufgaben' if test.get('task') else 'termine']))
            payload.append(dict(test, items=result['roundtripItems']))
    node = os.environ.get('NODE') or shutil.which('node') or shutil.which('nodejs')
    command = [node] if node else ['flatpak', 'run', '--filesystem=' + str(ROOT), '--command=node', 'org.flatpak.Builder']
    web = subprocess.run(command + [str(ROOT / 'magnolie-organizer-windows/tests/recurrence-integration.js')], input=json.dumps(payload), capture_output=True, text=True)
    assert web.returncode == 0, web.stdout + web.stderr
    assert len(json.loads(web.stdout)) == 2
