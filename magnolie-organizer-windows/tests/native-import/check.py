#!/usr/bin/env python3
"""#660: run the existing native-import entry point on bounded synthetic inputs."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dotnet', required=True)
    parser.add_argument('--assembly', required=True, type=Path)
    args = parser.parse_args()
    assembly = args.assembly.resolve(strict=True)
    checks = 0

    def run(request):
        result = subprocess.run([args.dotnet, str(assembly)], input=json.dumps(request),
                                text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr[-2000:]
        # JSON-only stdout also proves that the referenced CoreTests Main was
        # not executed as a side effect of loading the actual codec assembly.
        return json.loads(result.stdout)

    for index, zone in enumerate(['Africa/Casablanca', 'Asia/Almaty', 'Synthetic/Embedded']):
        wire = 'DTSTART;TZID=' + zone + ':20260115T123017'
        definition = ('BEGIN:VTIMEZONE\r\nTZID:Synthetic/Embedded\r\nBEGIN:STANDARD\r\n'
                      'DTSTART:19700101T000000\r\nTZOFFSETFROM:+005328\r\n'
                      'TZOFFSETTO:+005328\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n') if index == 2 else ''
        uid = 'synthetic-import-660-' + str(index)
        text = ('BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + definition + 'BEGIN:VEVENT\r\nUID:' + uid +
                '\r\nSUMMARY:Synthetic import fixture\r\n' + wire + '\r\nDURATION:PT1M\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')
        parsed = run(dict(operation='parse', art='ics', text=text))
        assert parsed['FehlerhafteTermine'] == 0 and len(parsed['Termine']) == 1
        item = parsed['Termine'][0]
        assert item['uid'] == uid and wire in item['icsRoundtrip']
        exported = run(dict(operation='export', art='ics-termine', data=parsed['Termine']))
        assert exported['Skipped'] == 0 and wire in exported['Text']
        again = run(dict(operation='parse', art='ics', text=exported['Text']))['Termine'][0]
        for field in ['uid', 'titel', 'datum', 'zeit', 'endDatum', 'endZeit', 'icsAnzeigeZeitzone']:
            assert again[field] == item[field], (zone, field)
        checks += 1

    card = ('BEGIN:VCARD\r\nVERSION:3.0\r\nUID:synthetic-contact-660\r\n'
            'N:Fixture;Synthetic;;;\r\nFN:Synthetic Fixture\r\nEMAIL;TYPE=WORK:Mixed@Example.org\r\nEND:VCARD\r\n')
    contacts = run(dict(operation='parse', art='vcf', file='synthetic.vcf', text=card))['Kontakte']
    assert len(contacts) == 1 and contacts[0]['uid'] == 'synthetic-contact-660'
    vcard = run(dict(operation='vcf', data=contacts))
    assert vcard['Skipped'] == 0
    again = run(dict(operation='parse', art='vcf', file='synthetic.vcf', text=vcard['Text']))['Kontakte']
    assert again[0]['uid'] == contacts[0]['uid']
    checks += 1

    assert run(dict(operation='parse', art='unknown', text='synthetic')) == {'error': 'InvalidDataException'}
    checks += 1
    with tempfile.TemporaryDirectory(prefix='magnolie-native-import-660-') as folder:
        fixture = dict(synthetic=True, uid='synthetic-store-660', notizen=[])
        result = run(dict(operation='persist', file=str(Path(folder) / 'synthetic.json'), data=fixture))
        assert result == fixture
        checks += 1
    print(json.dumps(dict(nativeImportProbeChecks=checks, actualReferencedCodecs=True,
                          coreTestMainExecuted=False, installedAcceptance=False)))


if __name__ == '__main__':
    main()
