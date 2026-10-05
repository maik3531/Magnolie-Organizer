"""Strict optional time-tracking v7 contract; transport integration is separate."""
import json
import re
from uuid import uuid4
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo

VERSION = 7
SETTINGS = 'personal_sync.time_settings'
REQUEST = 'personal_sync.time_request'
BATCH = 'personal_sync.time_batch'
KINDS = frozenset((SETTINGS, REQUEST, BATCH))
MAX_BODY = 192 * 1024
MAX_COUNTER = 9007199254740991
MAX_MINUTE = 4223371679
UUID4 = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z')


def _exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('invalid_time_schema')


def _number(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid_time_integer')
    return value


def _text(value, maximum=20000):
    if not isinstance(value, str) or len(value.encode('utf-16-le')) // 2 > maximum:
        raise ValueError('invalid_time_text')
    value.encode('utf-8')
    return value


def _uuid(value):
    if not isinstance(value, str) or not UUID4.fullmatch(value):
        raise ValueError('invalid_time_identity')


def _zone(value):
    value = _text(value, 160)
    if value in {'UTC', 'GMT', 'UT', 'Z'}:
        return timezone.utc
    match = re.fullmatch(r'(?:UTC|GMT|UT)?([+-])([0-9]{2})(?::([0-9]{2}))?', value)
    if match:
        hours, minutes = int(match[2]), int(match[3] or '0')
        if hours > 18 or minutes > 59 or hours == 18 and minutes:
            raise ValueError('invalid_time_zone')
        return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if match[1] == '-' else 1)))
    return ZoneInfo(value)


def validate_settings(body):
    _exact(body, {'format', 'scope', 'enabled', 'revision', 'epoch'})
    _number(body['format'], VERSION, VERSION)
    if body['scope'] != 'time_tracking' or type(body['enabled']) is not bool:
        raise ValueError('invalid_time_consent')
    _number(body['revision'], 1, MAX_COUNTER)
    _uuid(body['epoch'])
    return body


def accept_settings(current, incoming):
    validate_settings(incoming)
    if current is not None:
        validate_settings(current)
        if current == incoming:
            return current
        if incoming['revision'] <= current['revision'] or incoming['epoch'] == current['epoch']:
            raise ValueError('stale_time_consent')
    return incoming


def new_settings(enabled=False, revision=1):
    return validate_settings(dict(format=VERSION, scope='time_tracking', enabled=enabled,
                                  revision=revision, epoch=str(uuid4())))


def request_body(local, remote, trigger='manual'):
    validate_settings(local); validate_settings(remote)
    return validate(REQUEST, dict(format=VERSION, trigger=trigger,
        sender_epoch=local['epoch'], receiver_epoch=remote['epoch'],
        sender_revision=local['revision'], receiver_revision=remote['revision']), True)


def batches(local, remote, entries, calendar=None, trigger='manual', from_organizer=True):
    """Prepare every bounded packet before enqueueing any of a snapshot."""
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError('invalid_time_snapshot')
    for entry in entries:
        validate_record(entry, allow_deletion=from_organizer is True)
    if len({entry['id'] for entry in entries}) != len(entries):
        raise ValueError('duplicate_time_identity')
    base = request_body(local, remote, trigger)
    packet = dict(base, entries=[])
    if calendar is not None:
        if not from_organizer:
            raise ValueError('calendar_requires_organizer_source')
        packet['calendar'] = validate_calendar(calendar)
    validate(BATCH, packet, from_organizer)
    result = []
    for entry in entries:
        candidate = dict(packet, entries=packet['entries'] + [entry])
        size = len(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'))
        if len(candidate['entries']) > 32 or size > MAX_BODY:
            if packet['entries'] or 'calendar' in packet:
                result.append(packet)
            packet = dict(base, entries=[entry])
            validate(BATCH, packet, from_organizer)
        else:
            packet = candidate
    if packet['entries'] or 'calendar' in packet or not result:
        result.append(packet)
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def validate_record(record, allow_deletion=False):
    fields = {'id', 'startMinute', 'endMinute', 'pauseMinute', 'pauseMinutes', 'zone',
              'type', 'note', 'modifiedMs', 'deleted', 'clock'}
    if isinstance(record, dict) and 'pausePlan' in record:
        fields.add('pausePlan')
    _exact(record, fields)
    _uuid(record['id'])
    start = _number(record['startMinute'], 0, MAX_MINUTE)
    pauses = _number(record['pauseMinutes'], 0, MAX_MINUTE - start)
    _number(record['modifiedMs'], 0, 253402300799999)
    end, pause = record['endMinute'], record['pauseMinute']
    if end is not None:
        _number(end, start, MAX_MINUTE)
        if pauses > end - start:
            raise ValueError('invalid_time_pause')
    if pause is not None:
        _number(pause, start, MAX_MINUTE)
        if end is not None or pauses > pause - start:
            raise ValueError('invalid_time_pause')
    if type(record['deleted']) is not bool or record['deleted'] and allow_deletion is not True:
        raise ValueError('local_removal_is_not_remote_deletion')
    if record['deleted'] and (start != 0 or end != 0 or pause is not None or pauses != 0 or
            record['zone'] != 'UTC' or record['type'] or record['note'] or record.get('pausePlan') is not None):
        raise ValueError('time_tombstone_must_omit_contents')
    _zone(record['zone'])
    _text(record['type'], 120); _text(record['note'])
    clock = record['clock']
    if not isinstance(clock, dict) or not 1 <= len(clock) <= 32:
        raise ValueError('invalid_time_clock')
    for actor, counter in clock.items():
        _uuid(actor); _number(counter, 1, MAX_COUNTER)
    validate_pause_plan(record)
    return record


def validate_pause_plan(record):
    plan = record.get('pausePlan')
    if plan is None:
        return
    if record['endMinute'] is not None or record['deleted']:
        raise ValueError('pause_plan_requires_open_record')
    _exact(plan, {'fixed', 'manual', 'replaced', 'fixedEnds', 'baseMinutes'})
    _number(plan['baseMinutes'], 0, MAX_MINUTE - record['startMinute'])
    fixed, manual, replaced, ends = (plan[key] for key in ('fixed', 'manual', 'replaced', 'fixedEnds'))
    if not isinstance(fixed, list) or len(fixed) > 16 or not isinstance(manual, list) or len(manual) > 10000:
        raise ValueError('invalid_time_pause_intervals')
    for item in fixed:
        _exact(item, {'start', 'end'})
        _number(item['start'], 0, 1439); _number(item['end'], 0, 1439)
        if item['start'] == item['end']:
            raise ValueError('empty_time_pause_window')
    previous = record['startMinute']
    for item in manual:
        _exact(item, {'start', 'end'})
        start = _number(item['start'], previous, MAX_MINUTE)
        previous = _number(item['end'], start, MAX_MINUTE)
        if record['pauseMinute'] is not None and previous > record['pauseMinute']:
            raise ValueError('overlapping_time_pause_intervals')
    if not isinstance(replaced, list) or len(replaced) > 60000:
        raise ValueError('invalid_time_pause_replacements')
    for value in replaced:
        _number(value, 0, MAX_MINUTE)
    if replaced != sorted(set(replaced)):
        raise ValueError('noncanonical_time_pause_replacements')
    if not isinstance(ends, dict) or len(ends) > 60000:
        raise ValueError('invalid_fixed_pause_endings')
    for key, value in ends.items():
        if not isinstance(key, str) or not re.fullmatch(r'0|[1-9][0-9]*', key):
            raise ValueError('invalid_fixed_pause_identity')
        start = _number(int(key), 0, MAX_MINUTE)
        _number(value, start, MAX_MINUTE)


def validate_calendar(value):
    _exact(value, {'enabled', 'country', 'regions', 'holidays'})
    if type(value['enabled']) is not bool:
        raise ValueError('invalid_time_calendar')
    country = _text(value['country'], 2)
    if not (not value['enabled'] and not country) and not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('invalid_time_country')

    def regions(items):
        if not isinstance(items, list) or len(items) > 64 or any(not _text(item, 64) for item in items):
            raise ValueError('invalid_time_regions')

    regions(value['regions'])
    holidays = value['holidays']
    if not isinstance(holidays, list) or len(holidays) > 2048:
        raise ValueError('invalid_time_holidays')
    for holiday in holidays:
        _exact(holiday, {'date', 'name', 'country', 'nationwide', 'regions'})
        if date.fromisoformat(_text(holiday['date'], 10)).isoformat() != holiday['date']:
            raise ValueError('invalid_time_date')
        if not _text(holiday['name'], 160) or not re.fullmatch('[A-Z]{2}', _text(holiday['country'], 2)) or type(holiday['nationwide']) is not bool:
            raise ValueError('invalid_time_holiday')
        regions(holiday['regions'])
    return value


def validate(kind, body, from_organizer):
    if len(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')) > MAX_BODY:
        raise ValueError('time_message_too_large')
    if kind == SETTINGS:
        return validate_settings(body)
    fields = {'format', 'sender_epoch', 'receiver_epoch', 'sender_revision', 'receiver_revision', 'trigger'}
    if kind == BATCH:
        fields |= {'entries'}
        if isinstance(body, dict) and 'calendar' in body:
            fields.add('calendar')
    elif kind != REQUEST:
        raise ValueError('unknown_time_message')
    _exact(body, fields)
    _number(body['format'], VERSION, VERSION)
    if body['trigger'] not in ('manual', 'auto_wifi'):
        raise ValueError('invalid_time_trigger')
    for key in ('sender_epoch', 'receiver_epoch'): _uuid(body[key])
    for key in ('sender_revision', 'receiver_revision'): _number(body[key], 1, MAX_COUNTER)
    if kind == BATCH:
        records = body['entries']
        if not isinstance(records, list) or len(records) > 32:
            raise ValueError('invalid_time_batch')
        for record in records: validate_record(record, allow_deletion=from_organizer is True)
        if len({record['id'] for record in records}) != len(records):
            raise ValueError('duplicate_time_identity')
        if 'calendar' in body:
            if not from_organizer: raise ValueError('calendar_requires_organizer_source')
            validate_calendar(body['calendar'])
    return body


def allowed(body, local, remote, local_own, remote_own, fresh_controls, local_versions, remote_versions):
    if fresh_controls is not True or local_own is not True or remote_own is not True or not any(type(v) is int and v == VERSION for v in local_versions) or not any(type(v) is int and v == VERSION for v in remote_versions) or local is None or remote is None:
        return False
    try:
        validate_settings(local); validate_settings(remote)
        for key in ('sender_revision', 'receiver_revision'): _number(body[key], 1, MAX_COUNTER)
        for key in ('sender_epoch', 'receiver_epoch'): _uuid(body[key])
        return local['enabled'] and remote['enabled'] and body['sender_epoch'] == remote['epoch'] and body['receiver_epoch'] == local['epoch'] and body['sender_revision'] == remote['revision'] and body['receiver_revision'] == local['revision']
    except (ValueError, KeyError, TypeError):
        return False
