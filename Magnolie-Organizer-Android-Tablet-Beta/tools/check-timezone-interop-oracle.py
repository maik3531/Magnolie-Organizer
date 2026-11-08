#!/usr/bin/env python3
"""Check external native-audit clocks against published 2.0.30 and pinned IANA data.

Download tzdata2026e.tar.gz from the official IANA release URL, then pass its path.
This is a test-only zic build, never a production database or a sampled rule model.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
import zoneinfo

ROOT = Path(__file__).resolve().parents[2]
SHA256 = 'b26882805f26aac59d5b222978e6580484b834ccdc98be89df2f05a6dc53a652'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('iana_archive', type=Path)
parser.add_argument('--write', action='store_true')
args = parser.parse_args()
assert hashlib.sha256(args.iana_archive.read_bytes()).hexdigest() == SHA256
source = subprocess.check_output(['git', 'show', 'v2.0.30:magnolie-organizer/bin/magnolie_recurrence.py'], cwd=ROOT)
with tempfile.TemporaryDirectory(prefix='magnolie-tz-oracle-') as temporary:
    work = Path(temporary)
    sources = ['africa', 'asia', 'australasia', 'europe', 'northamerica', 'southamerica', 'etcetera', 'backward']
    with tarfile.open(args.iana_archive) as archive:
        assert archive.extractfile('version').read().decode().strip() == '2026e'
        for name in sources:
            (work / name).write_bytes(archive.extractfile(name).read())
    output = work / 'zoneinfo'
    subprocess.run(['zic', '-b', 'fat', '-d', str(output), *[str(work / name) for name in sources]], check=True)
    zoneinfo.reset_tzpath([str(output)]); zoneinfo.ZoneInfo.clear_cache()
    module_path = work / 'published_recurrence.py'; module_path.write_bytes(source)
    spec = importlib.util.spec_from_file_location('published_recurrence', module_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    clocks = []
    for name in ['Europe/Berlin', 'America/New_York', 'Australia/Sydney', 'Australia/Lord_Howe', 'Pacific/Chatham', 'Africa/Casablanca', 'Africa/Cairo', 'America/Mexico_City', 'Asia/Almaty']:
        for year in [2026, 2400]:
            for month in [1, 7]:
                wall = datetime(year, month, 15, 12, 30)
                definition = module.timezone_definition(name)
                if isinstance(definition, str): definition = definition.splitlines()
                offset = module.CalendarZone(definition).utcoffset(wall)
                assert offset == wall.replace(tzinfo=zoneinfo.ZoneInfo(name)).utcoffset()
                epoch = int((wall-offset).replace(tzinfo=timezone.utc).timestamp()*1000)
                clocks.append(dict(identifier=name, wall=wall.isoformat(timespec='minutes'), epochMs=epoch, offsetSeconds=int(offset.total_seconds())))
    # A current post-change clock distinguishes today's reminder impact from year2400.
    wall = datetime(2026, 10, 15, 12, 30); name = 'Africa/Casablanca'
    offset = module.CalendarZone(module.timezone_definition(name)).utcoffset(wall)
    assert offset == wall.replace(tzinfo=zoneinfo.ZoneInfo(name)).utcoffset()
    clocks.append(dict(identifier=name, wall=wall.isoformat(timespec='minutes'),
                       epochMs=int((wall-offset).replace(tzinfo=timezone.utc).timestamp()*1000), offsetSeconds=int(offset.total_seconds())))
    fixture = dict(schema=1, publishedVersion='2.0.30', publishedRecurrenceSHA256=hashlib.sha256(source).hexdigest(),
                   ianaVersion='2026e', ianaURL='https://data.iana.org/time-zones/releases/tzdata2026e.tar.gz',
                   ianaSHA256=SHA256, expectedBundledTZDBVersion='2026egtz', clocks=clocks)
    expected = json.dumps(fixture, indent=2)+'\n'
    target = ROOT / 'port-adapters/tests/timezone-interop-oracle.json'
    if args.write: target.write_text(expected)
    else: assert target.read_text() == expected, 'External civil-time oracle differs'
    print('Published Python 2.0.30 + independent zic/ZoneInfo, official IANA2026e: 37 clocks PASS')
    print('oracleSHA256='+hashlib.sha256(expected.encode()).hexdigest())
