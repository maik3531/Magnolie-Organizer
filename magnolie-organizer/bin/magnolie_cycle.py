"""Personal bleeding-marker estimates, never medical inference or stored events.

The 14–60-day bounds and two-day window margin are documented planning rules,
not clinical thresholds. A break starts a new history instead of silently using
older intervals on the other side of missing or ambiguous records (Refs #803).
"""
from datetime import date, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import hashlib
import json
import struct
import math
import re

BLEEDING_TYPES = {'bleeding-light', 'bleeding-medium', 'bleeding-heavy'}


def _object(value):
    return value if isinstance(value, dict) else {}


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('invalid_cycle_date')
    return date.fromisoformat(value)


@lru_cache(maxsize=1)
def _normative_rules():
    # Use the exact rules shipped with the GUI. A present but damaged primary
    # is an error, never a reason to silently select host timezone data.
    root = Path(__file__).resolve().parents[1]
    candidates = (root / 'web/timezones', root / 'share/magnolie-organizer/web/timezones',
                  root.parent / 'port-adapters/timezones', root / 'werkzeuge/timezones')
    source = next((path for path in candidates if path.exists()), None)
    if source is None:
        raise FileNotFoundError('Bound cycle calendar timezone rules are missing')
    hashes = {
        'tzdb-2026egtz.json': '2e6b1c9da8c9b2a98d8b9c9c6addb4b93b6de37a19e76120361eff245cc87e9c',
        'provenance.json': 'b6b926b73620b3ab9ba477195041e52925ee6b12376791e647f70beba6bcc2a0',
        'LICENSE-tzdb.txt': '0613408568889f5739e5ae252b722a2659c02002839ad970a63dc5e9174b27cf',
    }
    payloads = {}
    for name, expected in hashes.items():
        path = source / name
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Bound cycle calendar timezone resource is too large')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError('Bound cycle calendar timezone identity differs')
        payloads[name] = payload
    rules = json.loads(payloads['tzdb-2026egtz.json'])
    manifest = json.loads(payloads['provenance.json'])
    if (rules.get('schema') != 2 or rules.get('tzdbVersion') != '2026egtz'
            or manifest.get('payloadSHA256') != hashes['tzdb-2026egtz.json']
            or manifest.get('payloadBytes') != len(payloads['tzdb-2026egtz.json'])
            or rules.get('sourceArchiveSHA256') != manifest.get('archiveSHA256')):
        raise ValueError('Bound cycle calendar timezone provenance differs')
    return rules


def _tzif(row):
    # Losslessly re-encode the existing schema-2 TZif/POSIX representation.
    # CPython's standard TZif reader evaluates the rules; no second offset or
    # DST calculation, subprocess, temporary file or host tzdb is involved.
    initial, types, history, future = row
    if initial != 0:
        raise ValueError('Unsupported initial normative timezone type')
    names = bytearray()
    name_indexes = {}
    infos = bytearray()
    for offset, dst, abbreviation, _standard, _universal in types:
        if abbreviation not in name_indexes:
            name_indexes[abbreviation] = len(names)
            names.extend(abbreviation.encode('ascii') + b'\0')
        infos.extend(struct.pack('>iBB', offset, dst, name_indexes[abbreviation]))
    def header(count, type_count, name_count, flags):
        return b'TZif2' + bytes(15) + struct.pack('>6I', flags, flags, 0, count, type_count, name_count)
    # The v1 preamble is skipped by v2 readers. The second section carries every
    # transition, all original type flags and the original infinite POSIX tail.
    preamble = header(0, 1, 4, 0) + struct.pack('>iBB', 0, 0, 0) + b'UTC\0'
    times, indexes = history[::2], history[1::2]
    return (preamble + header(len(times), len(types), len(names), len(types))
            + struct.pack('>' + 'q' * len(times), *times) + bytes(indexes) + infos + names
            + bytes(entry[3] for entry in types) + bytes(entry[4] for entry in types)
            + b'\n' + future[6].encode('ascii') + b'\n')


@lru_cache(maxsize=64)
def _normative_zone(identifier):
    rules = _normative_rules()
    if identifier not in rules['zones']:
        raise ValueError('Cycle calendar timezone is unavailable in the bound normative rules')
    row = rules['rules'][rules['zones'][identifier]]
    return ZoneInfo.from_file(BytesIO(_tzif(row)), key=identifier)


def organizer_today(data, now=None):
    """Book-local date from the same bound timezone rules as the GUI."""
    regional = _object(_object(_object(data).get('einstellungen')).get('regional'))
    identifier = regional.get('timeZone')
    if not isinstance(identifier, str) or identifier in ('', 'system'):
        from magnolie_timezone import system_zone
        identifier = system_zone()
    if identifier == 'Z':
        identifier = 'UTC'
    instant = now if now is not None else datetime.now(timezone.utc)
    return instant.astimezone(_normative_zone(identifier)).date().isoformat()


def _recent_intervals(values):
    recent = []
    for value in reversed(values):
        if not 14 <= value <= 60:
            break
        recent.append(value)
        if len(recent) == 12:
            break
    return list(reversed(recent))


def _median(values):
    return math.floor(median(values) + .5) if len(values) >= 2 else None


def _pause_context(data, today):
    """Respect only an explicit, valid diary pause; never infer a cause."""
    empty = {'paused': False, 'pauseReason': None, 'pauseStart': None,
             'pauseUntil': None, 'resumedOn': None, 'restartFrom': None}
    calendar = _object(_object(data.get('einstellungen')).get('kalender'))
    pause = _object(_object(calendar.get('zyklusErinnerungen')).get('pause'))
    reason = pause.get('reason')
    if not isinstance(reason, str) or reason not in ('pregnancy', 'breastfeeding', 'medication', 'menopause', 'other'):
        return empty
    try:
        start = _day(pause.get('startedOn'))
        until = _day(pause['until']) if pause.get('until') is not None else None
    except (TypeError, ValueError):
        return empty
    if (until is not None and until < start) or today < start:
        return empty
    try:
        resumed = _day(pause.get('resumedOn'))
        if resumed < start or resumed > today:
            resumed = None
    except (TypeError, ValueError):
        resumed = None
    try:
        restart = resumed if resumed is not None else until + timedelta(days=1) if until is not None else None
    except OverflowError:
        restart = None
    return {'paused': resumed is None and (until is None or today <= until), 'pauseReason': reason,
            'pauseStart': start.isoformat(), 'pauseUntil': until.isoformat() if until is not None else None,
            'resumedOn': resumed.isoformat() if resumed is not None else None,
            'restartFrom': restart.isoformat() if restart is not None else None}


def estimate_cycle(data, as_of=None):
    """Derive one next-start estimate as of an explicit ISO date, or book-local today."""
    data = _object(data)
    today = _day(organizer_today(data) if as_of is None else as_of)
    pause = _pause_context(data, today)
    markers = data.get('zyklusmarker') if isinstance(data.get('zyklusmarker'), list) else []
    ids = {entry['id'] for entry in markers if isinstance(entry, dict)
           and isinstance(entry.get('id'), str) and entry['id']
           and isinstance(entry.get('art'), str) and entry['art'] in BLEEDING_TYPES}
    dates, future = set(), set()
    marks = data.get('tagmarken') if isinstance(data.get('tagmarken'), list) else []
    for mark in marks:
        if not isinstance(mark, dict) or not isinstance(mark.get('zyklusIds'), list):
            continue
        if not any(isinstance(value, str) and value in ids for value in mark['zyklusIds']):
            continue
        try:
            day = _day(mark.get('datum'))
        except (ValueError, TypeError):
            continue
        if pause['pauseReason'] is not None and (pause['restartFrom'] is None or day.isoformat() < pause['restartFrom']):
            continue
        (future if day > today else dates).add(day)

    starts = []
    previous = None
    run = recorded_run = 0
    for day in sorted(dates):
        gap = (day - previous).days if previous is not None else None
        if gap is None or gap > 3:
            starts.append(day)
            run = recorded_run = 1
        else:
            run = run + 1 if gap == 1 else 1
            recorded_run = max(recorded_run, run)
        previous = day
    intervals = [(b - a).days for a, b in zip(starts, starts[1:])]
    used = _recent_intervals(intervals)
    length = _median(used)
    baseline = _median(_recent_intervals(intervals[:-1]))
    excluded = sum(not 14 <= value <= 60 for value in intervals)
    reason = 'gap' if excluded else 'restart' if pause['pauseReason'] is not None else 'insufficient'
    predicted = window_start = window_end = None
    overdue = 0
    if length is not None:
        try:
            prediction = starts[-1] + timedelta(days=length)
            lower = starts[-1] + timedelta(days=max(1, min(used) - 2))
            upper = starts[-1] + timedelta(days=max(used) + 2)
            if previous >= lower:
                reason = 'ongoing'
            else:
                reason = 'ready'
                predicted, window_start, window_end = (value.isoformat() for value in (prediction, lower, upper))
                overdue = max(0, (today - upper).days)
        except OverflowError:
            reason = 'range'
    stale_after = max(120, 2 * (max(used) + 2 if used else 60))
    stale = bool(starts) and (today - starts[-1]).days > stale_after
    if pause['paused']:
        reason = 'paused'
    return {'asOf': today.isoformat(), 'starts': [day.isoformat() for day in starts], 'intervals': intervals,
            'length': length, 'predicted': predicted, 'baseline': baseline,
            'latest': intervals[-1] if intervals else None, 'usedIntervals': used,
            'excludedIntervals': excluded, 'futureIgnored': len(future),
            'lastBleeding': previous.isoformat() if previous else None,
            'recordedRun': recorded_run, 'windowStart': window_start, 'windowEnd': window_end,
            'overdueDays': overdue, 'stale': stale, 'reason': reason, **pause}


def cycle_reminders(data, translate=lambda text: text, as_of=None):
    _ = translate
    settings = _object(_object(_object(data).get('einstellungen')).get('kalender'))
    options = _object(settings.get('zyklusErinnerungen'))
    if settings.get('zykluskalenderAn') is not True or not (options.get('prognose') is True or options.get('abweichung') is True):
        return []
    stats = estimate_cycle(data, as_of)
    if stats['paused']:
        return []
    result = []
    if options.get('prognose') is True and stats['predicted'] and not stats['stale']:
        lead = options.get('vorlauf', 1)
        lead = lead if type(lead) is int and 0 <= lead <= 30 else 1
        result.append({'id': 'cycle-estimate:' + stats['starts'][-1] + ':' + stats['predicted'],
            'datum': stats['predicted'], 'zeit': '08:00',
            'titel': _('Estimated next period'), 'standardErinnerung': False,
            'individuelleErinnerungTage': lead})
    threshold = options.get('abweichungTage', 7)
    threshold = threshold if type(threshold) is int and 1 <= threshold <= 30 else 7
    if options.get('abweichung') is True and stats['baseline'] is not None and abs(stats['latest'] - stats['baseline']) >= threshold:
        result.append({'id': 'cycle-deviation:' + stats['starts'][-1] + ':' + str(stats['latest']),
            'datum': stats['starts'][-1], 'zeit': '08:00',
            'titel': _('Cycle interval changed'), 'standardErinnerung': False,
            'individuelleErinnerungTage': 0})
    return result
