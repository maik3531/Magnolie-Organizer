#!/usr/bin/env python3
"""Feed canonical calendar records to Swift, then parse its exports with the actual desktop codec."""
import argparse
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from project_ui import BETA, LINUX


def canonical():
    # The source module explicitly supports codec use without GTK. Import it,
    # including its shared recurrence implementation, rather than cloning it.
    loader = importlib.machinery.SourceFileLoader('mac_calendar_canonical', str(LINUX / 'bin/magnolie-organizer'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def cases(module):
    all_day = {'uid': 'monthly-ordinal', 'titel': 'Zweiter Donnerstag', 'datum': '2024-01-11', 'zeit': '',
               'wiederholung': {'art': 'monthly', 'bis': '', 'ordinal': 2, 'wochentag': 'TH'}}
    monthly = {'uid': 'monthly-setpos', 'titel': 'Letzter Freitag', 'datum': '2026-01-30', 'zeit': '09:15',
               'endDatum': '2026-01-31', 'endZeit': '10:45', 'icsAnzeigeZeitzone': 'UTC',
               'wiederholung': {'art': 'monthly', 'bis': '2027-01-31', 'ordinal': -1, 'wochentag': 'FR', 'rruleForm': 'bysetpos'}}
    custom = {'uid': 'custom-days', 'titel': 'Zusatztermine', 'datum': '2026-03-27', 'zeit': '',
              'wiederholung': {'art': 'custom', 'bis': '', 'daten': ['2026-03-29', '2026-04-02']}, 'icsAusnahmen': ['2026-03-29']}
    task = {'uid': 'task-parent', 'titel': 'Task ü', 'startDatum': '2026-03-28', 'startZeit': '10:00',
            'faellig': '2026-03-29', 'faelligZeit': '10:00', 'icsAnzeigeZeitzone': 'UTC', 'prio': 1,
            'notiz': 'Line 1\nLine 2, semicolon;', 'erledigt': True, 'erinnern': True, 'individuelleErinnerungTage': 2, 'reihenfolge': 3}
    child = {'uid': 'task-child', 'titel': 'Child', 'faellig': '2026-04-01', 'prio': 3, 'elternUid': 'task-parent', 'reihenfolge': 4}
    anniversaries = [{'uid': 'birthday-leap', 'name': 'Leap Birthday', 'datum': '1980-02-29', 'typ': 'birthday', 'notiz': 'Public synthetic'},
                     {'uid': 'yearless', 'name': 'No year', 'datum': '--02-29', 'typ': 'wedding-anniversary'}]
    result = [dict(name='ordinal', kind='ics-termine', records=[all_day]),
              dict(name='setpos', kind='ics-termine', records=[monthly]),
              dict(name='custom-exdate', kind='ics-termine', records=[custom]),
              dict(name='tasks', kind='ics-aufgaben', records=[task, child]),
              dict(name='anniversaries', kind='ics-jahrestage', records=anniversaries)]
    for name in ['golden-komplex', 'caldav-series-resource']:
        source = (LINUX / 'pruefungen/fixtures' / (name + '.ics')).read_text()
        records = module.ics_lesen(source)['termine']
        result.append(dict(name=name, kind='ics-termine', records=records, source=source))
    # A recurrence with a source-local time across the spring DST change.
    source = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:dst-berlin\r\n'
              'DTSTART;TZID=Europe/Berlin:20260328T100000\r\nDTEND;TZID=Europe/Berlin:20260328T110000\r\n'
              'RRULE:FREQ=DAILY;COUNT=4\r\nRDATE;TZID=Europe/Berlin:20260402T100000\r\n'
              'EXDATE;TZID=Europe/Berlin:20260330T100000\r\nSUMMARY:DST calendar\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
    result.append(dict(name='dst-series', kind='ics-termine', records=module.ics_lesen(source)['termine'], source=source))
    # These UTF8 identities were independently checked against published2.0.30
    # and Kotlin; no Swift canonical-equivalence assumption supplies expected data.
    for fixture in sorted((BETA / 'tests/fixtures/opaque-ics').glob('*.ics')):
        source = fixture.read_text()
        result.append(dict(name='opaque-' + fixture.stem, kind='ics-termine', records=module.ics_lesen(source)['termine'], source=source))
    for fixture in sorted((BETA.parent / 'port-adapters/tests/fixtures/source-vtimezone-case').glob('*.ics')):
        source = fixture.read_text()
        result.append(dict(name='source-vtz-case-' + fixture.stem, kind='ics-termine', records=module.ics_lesen(source)['termine'], source=source))
    for identifier in ['@utc', '@magnolie-utc-instant', 'UTC', 'Factory']:
        source = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTIMEZONE\r\nTZID:' + identifier +
                  '\r\nBEGIN:STANDARD\r\nDTSTART:19700101T000000\r\nTZOFFSETFROM:+0300\r\nTZOFFSETTO:+0300\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n'
                  'BEGIN:VEVENT\r\nUID:source-zone\r\nDTSTART;TZID=' + identifier + ':20260115T120000\r\nSUMMARY:Source authority\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
        name = {'@utc': 'at-utc', '@magnolie-utc-instant': 'private-marker', 'UTC': 'utc', 'Factory': 'factory'}[identifier]
        result.append(dict(name='source-zone-' + name, kind='ics-termine', records=module.ics_lesen(source)['termine'], source=source))
    source = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + ''.join(
        'BEGIN:VEVENT\r\nUID:civil-' + day + '\r\nDTSTART:' + day + 'T120000Z\r\nSUMMARY:Gregorian civil\r\nEND:VEVENT\r\n'
        for day in ['00010615', '00990615', '15821004', '15821005', '15821010', '15821011', '24000229', '99990615']) + 'END:VCALENDAR\r\n')
    result.append(dict(name='proleptic-civil', kind='ics-termine', records=module.ics_lesen(source)['termine'], source=source))
    writers = {'ics-termine': module.ics_schreiben_termine, 'ics-aufgaben': module.ics_schreiben_aufgaben, 'ics-jahrestage': module.ics_schreiben_jahrestage}
    groups = {'ics-termine': 'termine', 'ics-aufgaben': 'aufgaben', 'ics-jahrestage': 'jahrestage'}
    for case in result:
        # Compare semantic fields against the desktop writer+parser, not against
        # our own serializer's interpretation. Generated stamps are not input.
        case['expected'] = module.ics_lesen(writers[case['kind']](case['records']))[groups[case['kind']]]
        case['importSource'] = case.get('source') or writers[case['kind']](case['records'])
        parsed = module.ics_lesen(case['importSource'])
        case['importExpected'] = {group: parsed[group] for group in ['termine', 'aufgaben', 'jahrestage']}
    return result


def stable(record):
    # Local routing, change stamps and source-observation caches are not ICS
    # content. Everything else, including raw properties, is checked below.
    ignored = {'geaendert', 'icsSequence', 'icsAenderungszeitFehlt', 'icsQuelleId', 'icsQuelleName', 'icsTimezones', 'icsRoundtrip', 'icsAnzeigeZeitzone'}
    return {key: value for key, value in record.items() if key not in ignored}


def validate(module, fixtures, output):
    groups = {'ics-termine': 'termine', 'ics-aufgaben': 'aufgaben', 'ics-jahrestage': 'jahrestage'}
    temporal = {'DTSTART', 'DTEND', 'DUE', 'DURATION', 'RRULE', 'RDATE', 'EXDATE', 'EXRULE', 'RECURRENCE-ID'}
    for case in fixtures:
        file = output / (case['name'] + '.ics')
        if not file.is_file():
            raise AssertionError('Native export missing: ' + case['name'])
        serialized = file.read_text()
        actual = module.ics_lesen(serialized)[groups[case['kind']]]
        if [stable(value) for value in actual] != [stable(value) for value in case['expected']]:
            raise AssertionError('Canonical semantic roundtrip differs: ' + case['name'] + '\n' + json.dumps(
                {'expected': [stable(x) for x in case['expected']], 'actual': [stable(x) for x in actual]}, ensure_ascii=True))
        if case['name'] == 'dst-series':
            lower = datetime(2026, 3, 27, tzinfo=timezone.utc)
            upper = datetime(2026, 4, 4, tzinfo=timezone.utc)
            original = module.ics_lesen(case['source'])['termine']
            def occurrences(records):
                return sorted((item['icsOccurrence'], item['icsStartUtc'], item['icsEndUtc'])
                              for record in records for item in module._ics_vorkommen(record, lower, upper))
            expected_occurrences, actual_occurrences = occurrences(original), occurrences(actual)
            if expected_occurrences != actual_occurrences or len(actual_occurrences) != 4:
                raise AssertionError('DST/RRULE/RDATE/EXDATE occurrence instants changed')
            starts = [datetime.fromtimestamp(item[1] / 1000, timezone.utc).isoformat() for item in actual_occurrences]
            if starts != ['2026-03-28T09:00:00+00:00', '2026-03-29T08:00:00+00:00',
                          '2026-03-31T08:00:00+00:00', '2026-04-02T08:00:00+00:00']:
                raise AssertionError('Spring DST/calendar exception fixture no longer proves its intended instants')
        if case.get('source'):
            source_lines = module._entfalte(case['source']) if hasattr(module, '_entfalte') else case['source'].replace('\r\n ', '').splitlines()
            exported_lines = serialized.replace('\n ', '').splitlines()
            for record in case['records']:
                for block in record.get('icsTimezones', []):
                    if '\n'.join(block) not in '\n'.join(exported_lines):
                        raise AssertionError('Source VTIMEZONE changed: ' + case['name'])
            # Preserve all original component properties, including parameterized
            # unknown extensions and nested alarms. Calendar headers are generated.
            depth, component_lines = 0, []
            for line in source_lines:
                name, _, value = line.partition(':')
                if line.startswith(('BEGIN:VEVENT', 'BEGIN:VTODO')):
                    depth = 1; continue
                if line.startswith(('END:VEVENT', 'END:VTODO')):
                    depth = 0; continue
                if depth and name.split(';', 1)[0] not in {'DTSTAMP'}:
                    component_lines.append(line)
            for line in component_lines:
                # UID/summary etc may be regenerated only when semantically equal;
                # temporal clocks/recurrence and unknown parameters remain exact.
                base = line.split(':', 1)[0].split(';', 1)[0]
                if base in temporal or base.startswith('X-') or base in {'BEGIN', 'END', 'ACTION', 'TRIGGER', 'ATTENDEE', 'ATTACH'}:
                    if line not in exported_lines:
                        raise AssertionError('Source property was lost: ' + case['name'] + ': ' + line)
        print('Canonical Swift export roundtrip: ' + case['name'], flush=True)


def validate_imports(module, fixtures, output):
    for case in fixtures:
        file = output / (case['name'] + '-imported.json')
        if not file.is_file():
            raise AssertionError('Native import output missing: ' + case['name'])
        imported = json.loads(file.read_text())
        for group in ['termine', 'aufgaben', 'jahrestage']:
            expected, actual = case['importExpected'][group], imported[group]
            if [stable(record) for record in actual] != [stable(record) for record in expected]:
                raise AssertionError('Native import differs from canonical parser: ' + case['name'] + '/' + group + '\n' + json.dumps(
                    {'expected': [stable(x) for x in expected], 'actual': [stable(x) for x in actual]}, ensure_ascii=True))
            if actual:
                reexport = output / (case['name'] + '-reimport-' + group + '.ics')
                reread = module.ics_lesen(reexport.read_text())[group]
                if [stable(record) for record in reread] != [stable(record) for record in expected]:
                    raise AssertionError('Native import/reexport canonical roundtrip differs: ' + case['name'] + '/' + group)
            for source_record, native_record in zip(expected, actual):
                # Extra retained source parameters are allowed; every property
                # the published parser retained must still be present exactly.
                native_raw = native_record.get('icsRoundtrip', [])
                for line in source_record.get('icsRoundtrip', []):
                    if line not in native_raw:
                        raise AssertionError('Native import lost raw property: ' + case['name'] + ': ' + line)
                if source_record.get('icsTimezones') != native_record.get('icsTimezones'):
                    raise AssertionError('Native import changed source VTIMEZONE blocks: ' + case['name'])
        if not imported.get('icsImportMetadata', {}).get('sourceSHA256'):
            raise AssertionError('Native import has no source binding')
        print('Canonical native import/reexport roundtrip: ' + case['name'], flush=True)


def validate_resource_patch(module, output):
    before = module.ics_lesen((output / 'patch-before.ics').read_text())
    after = module.ics_lesen((output / 'patch-after.ics').read_text())
    expected = module.ics_lesen((output / 'patch-expected.ics').read_text())
    for group in ['termine', 'aufgaben', 'jahrestage']:
        if [stable(x) for x in after[group]] != [stable(x) for x in expected[group]]:
            raise AssertionError('Resource patch differs from independently parsed expected calendar: ' + group)
    if len(before['termine']) != len(after['termine']) or len(before['aufgaben']) != len(after['aufgaben']):
        raise AssertionError('Resource patch lost sibling records')
    if [x['titel'] for x in after['termine']] != ['Changed', 'Original']:
        raise AssertionError('Resource patch did not selectively edit its target')
    print('Published parser resource-patch sibling/recurrence/task oracle passed', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--swift')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='mac-calendar-contract-') as temp:
        root = Path(temp)
        # Importing the GUI module must never pick up a personal profile/cache.
        for name in ['XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME']:
            os.environ[name] = str(root / name)
        os.environ['TZ'] = 'UTC'
        module = canonical()
        fixtures = cases(module)
        fixture = root / 'records.json'; fixture.write_text(json.dumps(fixtures) + '\n')
        print('Canonical calendar vectors prepared: ' + str(len(fixtures)), flush=True)
        if args.swift:
            output = root / 'exported'; output.mkdir()
            env = dict(os.environ, MACOS_BETA_CALENDAR_FIXTURES=str(fixture), MACOS_BETA_CALENDAR_OUTPUT=str(output))
            subprocess.run([args.swift, 'test', '--scratch-path', str(root / 'swift-build'), '--jobs', '2'], cwd=BETA, env=env, check=True, timeout=300)
            validate(module, fixtures, output)
            validate_imports(module, fixtures, output)
            validate_resource_patch(module, output)
        else:
            print('Swift calendar export NOT executed; pass --swift for native/portable validation.', flush=True)


if __name__ == '__main__':
    main()
