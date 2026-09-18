"""Windowed RFC 5545 calendar recurrence, without optional dependencies.

The source RRULE/EXRULE remains authoritative. Invalid rules raise ValueError.
Windows are inclusive. Generated nonexistent local times are removed before
BYSETPOS and COUNT; ambiguous times use the first occurrence (fold=0).

Uncounted rules seek directly. COUNT uses exact, shared prefix checkpoints;
only floating/fixed-offset/all-day rules may extrapolate calendar cycles.
RecurrenceLimitError is never a successful, truncated result. A retryable prefix
limit retains progress; retry the same Rule/query in a background worker. Output or
single-period limits require a smaller window/rule, not a blind retry.
"""

import calendar
import math
import re
import bisect
import threading
import struct
from pathlib import Path
from collections import OrderedDict
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, TZPATH

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
MAX_PERIODS = 146097
MAX_CANDIDATES = 2000000
MAX_OCCURRENCES = 100000
MAX_ORDINAL = datetime.max.toordinal()
UNITS = {"SECONDLY": 1, "MINUTELY": 60, "HOURLY": 3600,
         "DAILY": 86400, "WEEKLY": 604800}


class RecurrenceLimitError(RuntimeError):
    """An exact answer exceeded its work budget; no partial result was returned."""

    def __init__(self, message, *, resource="work", retryable=False, resume_period=0):
        super().__init__(message)
        self.resource = resource
        self.retryable = retryable
        self.resume_period = resume_period


class _Budget:
    def __init__(self):
        self.periods = self.candidates = 0
        self.prefix_progress = False
        self.resume_period = 0

    def charge(self, candidates=0, periods=0):
        self.periods += periods
        self.candidates += candidates
        if self.periods > MAX_PERIODS or self.candidates > MAX_CANDIDATES:
            raise RecurrenceLimitError("Calendar recurrence work limit exceeded.",
                                       retryable=self.prefix_progress, resume_period=self.resume_period)

    def prefix_advanced(self, cursor):
        self.prefix_progress = True
        self.resume_period = max(self.resume_period, cursor)


class _Prefix:
    def __init__(self):
        self.lock = threading.RLock()
        self.cursor = self.total = 0
        self.stride = 128
        self.indices = [0]
        self.totals = [0]
        self.partials = OrderedDict()

    def remember(self, cursor, total):
        self.cursor, self.total = cursor, total
        if cursor - self.indices[-1] >= self.stride:
            self.indices.append(cursor)
            self.totals.append(total)
        if len(self.indices) > 4096:
            self.indices = self.indices[::2]
            self.totals = self.totals[::2]
            self.stride *= 2

    def checkpoint_query(self, target, cursor, total):
        self.partials[target] = (cursor, total)
        self.partials.move_to_end(target)
        if len(self.partials) > 32:
            self.partials.popitem(last=False)


@lru_cache(maxsize=32)
def _prefix_state(text, wall, zone, all_day):
    # Zone objects, not zone names: replacing tzdata/ZoneInfo must not reuse an
    # answer computed with a different transition history.
    return _Prefix()


def _instant(value):
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value


def _exists(value):
    if value.tzinfo is None or isinstance(value.tzinfo, timezone):
        return True
    try:
        return value.astimezone(timezone.utc).astimezone(value.tzinfo).replace(tzinfo=None) == value.replace(tzinfo=None)
    except OverflowError:
        # datetime's representable instant domain is narrower at years 1/9999
        # for nonzero offsets. Do not fabricate an occurrence at another date.
        raise ValueError("Calendar instant is outside the supported date range.") from None


def date_time(value, params, default_zone, *, zone_resolver=None):
    """Parse a wire stamp; a calendar-scoped resolver may supply VTIMEZONE tzinfo."""
    value = str(value).strip()
    is_date = params.get("VALUE", "").upper() == "DATE" or bool(re.fullmatch(r"\d{8}", value))
    form = "%Y%m%d" if is_date else "%Y%m%dT%H%M%S" if len(value.rstrip("Z")) == 15 else "%Y%m%dT%H%M"
    result = datetime.strptime(value.rstrip("Z"), form)
    zone = (default_zone if is_date else timezone.utc if value.endswith("Z") else
            (zone_resolver or ZoneInfo)(params["TZID"]) if params.get("TZID") else default_zone)
    return result.replace(tzinfo=zone), is_date


def duration_end(start, value, is_date=False):
    match = re.fullmatch(r"\+?P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)", value)
    if not match or not any(part is not None for part in match.groups()):
        raise ValueError("invalid calendar duration")
    weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if is_date and any((hours, minutes, seconds)):
        raise ValueError("date duration requires days or weeks")
    # RFC nominal days first, exact hours/minutes/seconds second (DST matters).
    end = start + timedelta(days=weeks * 7 + days)
    exact = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return (end.astimezone(timezone.utc) + exact).astimezone(start.tzinfo) if start.tzinfo else end + exact


def properties(lines):
    result, depth = [], 0
    for line in lines or []:
        if not isinstance(line, str):
            continue
        # The first unquoted colon ends the property header; values may contain colons.
        match = re.match(r'^((?:[^:\"]|\"[^\"]*\")*):(.*)$', line)
        if not match:
            continue
        header = re.split(r';(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)', match[1])
        name, value = header[0].upper(), match[2]
        if name in ('BEGIN', 'END'):
            if value.upper() not in ('VEVENT', 'VTODO'):
                depth = max(0, depth + (1 if name == 'BEGIN' else -1))
        elif not depth:
            result.append((name, dict((key.upper(), val.strip('"')) for key, val in
                                     (part.split('=', 1) for part in header[1:] if '=' in part)), value))
    return result


class CalendarZone(tzinfo):
    """An embedded transition history, independent of the host's TZID database."""

    def __init__(self, lines):
        self.key = next(value for name, _, value in properties(lines[1:-1]) if name == 'TZID')
        self.observances = []
        for block in re.findall(r'(?ims)^BEGIN:(STANDARD|DAYLIGHT)\n(.*?)^END:\1\s*$', '\n'.join(lines)):
            props = properties(block[1].splitlines())
            def get(name):
                values = [value for key, _, value in props if key == name]
                if len(values) != 1:
                    raise ValueError('Missing or duplicate timezone ' + name + '.')
                return values[0]
            def offset(text):
                m = re.fullmatch(r'([+-])(\d{2})(\d{2})(\d{2})?', text)
                if not m or int(m[2]) > 23 or int(m[3]) > 59 or int(m[4] or 0) > 59:
                    raise ValueError('Invalid timezone offset.')
                return timedelta(seconds=(1 if m[1] == '+' else -1) * (int(m[2]) * 3600 + int(m[3]) * 60 + int(m[4] or 0)))
            start = date_time(get('DTSTART'), {}, None)[0]
            before, after = offset(get('TZOFFSETFROM')), offset(get('TZOFFSETTO'))
            rules, dates = [], {start}
            for name, params, value in props:
                if name == 'RRULE':
                    # Observance UNTIL is UTC; the transition DTSTART is local
                    # under TZOFFSETFROM, not under the zone being constructed.
                    value = re.sub(r'UNTIL=(\d{8}T\d{6}Z)', lambda m: 'UNTIL=' +
                        (date_time(m[1], {}, None)[0].replace(tzinfo=None) + before).strftime('%Y%m%dT%H%M%S'), value.upper())
                    rules.append(Rule(value, start))
                elif name == 'RDATE':
                    dates.update(date_time(v, params, None)[0] for v in value.split(','))
            self.observances.append((start, before, after, rules, dates))
        if not self.observances:
            raise ValueError('Missing timezone observance.')
        self.offsets = sorted({v for o in self.observances for v in o[1:3]}, reverse=True)
        self.initial = min(self.observances, key=lambda o: o[0] - o[1])[1]
        self.lock = threading.RLock()
        self.through = 0
        self.transitions = []
        self.instants = []

    def _ensure(self, year):
        with self.lock:
            if year <= self.through:
                return
            through = min(9999, year + 4)
            upper = datetime(through, 12, 31, 23, 59, 59)
            transitions = {}
            for start, before, after, rules, dates in self.observances:
                values = set(dates)
                for rule in rules:
                    values.update(rule.between(start, upper))
                for value in values:
                    at = value - before
                    if at in transitions and transitions[at] != (before, after):
                        raise ValueError('Conflicting timezone transitions.')
                    transitions[at] = (before, after)
                    if len(transitions) > MAX_OCCURRENCES:
                        raise RecurrenceLimitError('Timezone transition limit exceeded.', resource='timezone')
            self.transitions = sorted((at, *offsets) for at, offsets in transitions.items())
            self.instants = [v[0] for v in self.transitions]
            self.through = through

    def _offset_at(self, utc):
        self._ensure(utc.year)
        i = bisect.bisect_right(self.instants, utc) - 1
        return self.transitions[i][2] if i >= 0 else self.initial

    def utcoffset(self, value):
        if value is None:
            return None
        wall = value.replace(tzinfo=None)
        valid = [offset for offset in self.offsets if self._offset_at(wall - offset) == offset]
        if valid:
            return valid[-1 if value.fold else 0]
        for at, before, after in self.transitions:
            if after > before and at + before <= wall < at + after:
                return after if value.fold else before
        raise ValueError('Unresolved timezone wall time.')

    def fromutc(self, value):
        utc = value.replace(tzinfo=None)
        offset = self._offset_at(utc)
        i = bisect.bisect_right(self.instants, utc) - 1
        fold = i >= 0 and self.transitions[i][1] > offset and utc < self.transitions[i][0] + self.transitions[i][1] - offset
        return (utc + offset).replace(tzinfo=self, fold=int(fold))

    def dst(self, value):
        return timedelta(0)

    def tzname(self, value):
        return self.key


@lru_cache(maxsize=32)
def _calendar_zones(blocks):
    result = {}
    for block in blocks:
        key = next(value for name, _, value in properties(block[1:-1]) if name == 'TZID')
        if key in result:
            raise ValueError('Duplicate calendar timezone.')
        result[key] = block
    return result


@lru_cache(maxsize=32)
def _calendar_zone(block):
    return CalendarZone(block)


def calendar_zones(blocks):
    zones = _calendar_zones(tuple(tuple(block) for block in blocks or []))
    return lambda name: _calendar_zone(zones[name]) if name in zones else ZoneInfo(name)


@lru_cache(maxsize=32)
def timezone_definition(tzid):
    """Export TZif history and its POSIX future, not a finite DST snapshot."""
    ZoneInfo(tzid)  # Validate the key before using it as a relative resource path.
    path = next((Path(root) / tzid for root in TZPATH if (Path(root) / tzid).is_file()), None)
    if path:
        data = path.read_bytes()
    else:
        from importlib.resources import files
        data = files('tzdata.zoneinfo').joinpath(*tzid.split('/')).read_bytes()
    def header(at, size):
        if data[at:at + 4] != b'TZif':
            raise ValueError('Invalid TZif data.')
        counts = struct.unpack('>6I', data[at + 20:at + 44])
        gmt, std, leap, times, types, chars = counts
        return counts, at + 44 + times * (size + 1) + types * 6 + chars + leap * (size + 4) + std + gmt
    counts, end = header(0, 4)
    at, size = 44, 4
    if data[4:5] in (b'2', b'3', b'4'):
        at, size = end + 44, 8
        counts, end = header(end, 8)
    _, _, _, count, type_count, char_count = counts
    times = struct.unpack('>' + ('q' if size == 8 else 'i') * count, data[at:at + count * size])
    at += count * size
    indices = data[at:at + count]
    at += count
    types = [struct.unpack('>iBB', data[pos:pos + 6]) for pos in range(at, at + type_count * 6, 6)]
    at += type_count * 6
    names = data[at:at + char_count]
    def name(info):
        return names[info[2]:].split(b'\0', 1)[0].decode('ascii')
    def offset(seconds):
        sign = '+' if seconds >= 0 else '-'
        h, remainder = divmod(abs(seconds), 3600)
        m, s = divmod(remainder, 60)
        return '%s%02d%02d%s' % (sign, h, m, '%02d' % s if s else '')
    groups = {}
    previous = types[0]
    last = datetime(1, 1, 1)
    for seconds, index in zip(times, indices):
        current = types[index]
        try:
            instant = datetime(1970, 1, 1) + timedelta(seconds=seconds)
            wall = instant + timedelta(seconds=previous[0])
        except OverflowError:
            previous = current
            continue
        if current[0] != previous[0]:
            groups.setdefault((current[1], previous[0], current[0], name(current)), []).append(wall)
        previous, last = current, instant
    footer = data[end:].strip(b'\n').decode('ascii') if size == 8 else ''
    token = r'(?:<[^>]+>|[A-Za-z]{3,})'
    number = r'[+-]?\d{1,3}(?::\d{1,2}(?::\d{1,2})?)?'
    match = re.fullmatch('(' + token + ')(' + number + ')(' + token + ')?(' + number + ')?(?:,([^,]+),([^,]+))?', footer)
    def seconds(text):
        sign = -1 if text.startswith('-') else 1
        parts = list(map(int, text.lstrip('+-').split(':')))
        return sign * sum(value * unit for value, unit in zip(parts, (3600, 60, 1)))
    future = []
    if match and match[3] and match[5] and match[6]:
        standard = -seconds(match[2]); daylight = -seconds(match[4]) if match[4] else standard + 3600
        for kind, rule, before, after, label in ((1, match[5], standard, daylight, match[3]), (0, match[6], daylight, standard, match[1])):
            part, _, clock = rule.partition('/')
            clock_seconds = seconds(clock or '2')
            month_rule = re.fullmatch(r'M(\d{1,2})\.(\d)\.(\d)', part)
            dates = []
            for year in range(max(1, last.year - 1), 10000):
                if month_rule:
                    month, week, weekday = map(int, month_rule.groups())
                    first = datetime(year, month, 1)
                    day = 1 + (weekday - (first.weekday() + 1) % 7) % 7 + (week - 1) * 7
                    if day > calendar.monthrange(year, month)[1]:
                        day -= 7
                    wall = first.replace(day=day)
                else:
                    julian = part.startswith('J')
                    n = int(part[1:] if julian else part)
                    wall = datetime(year, 1, 1) + timedelta(days=n - 1 + (calendar.isleap(year) and n >= 60) if julian else n)
                try:
                    wall += timedelta(seconds=clock_seconds)
                    instant = wall - timedelta(seconds=before)
                except OverflowError:
                    continue
                if instant <= last:
                    continue
                dates.append(wall)
                if month_rule and 0 <= clock_seconds < 86400:
                    break
            if dates:
                rrule = ('FREQ=YEARLY;BYMONTH=%d;BYDAY=%d%s' % (month, -1 if week == 5 else week, ('SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA')[weekday])
                         if month_rule and 0 <= clock_seconds < 86400 else '')
                future.append((kind, before, after, label.strip('<>'), dates, rrule))
    elif footer and not match:
        raise ValueError('Invalid TZif future rule.')
    if not groups and not future:
        groups[(0, previous[0], previous[0], name(previous))] = [datetime(1970, 1, 1)]
    lines = ['BEGIN:VTIMEZONE', 'TZID:' + tzid]
    for kind, before, after, label, dates, rule in [(*key, dates, '') for key, dates in groups.items()] + future:
        component = 'DAYLIGHT' if kind else 'STANDARD'
        lines.extend(['BEGIN:' + component, 'DTSTART:' + dates[0].strftime('%Y%m%dT%H%M%S'),
                      'TZOFFSETFROM:' + offset(before), 'TZOFFSETTO:' + offset(after), 'TZNAME:' + label])
        if len(dates) > 1:
            lines.append('RDATE:' + ','.join(value.strftime('%Y%m%dT%H%M%S') for value in dates[1:]))
        if rule:
            lines.append('RRULE:' + rule)
        lines.append('END:' + component)
    return tuple(lines + ['END:VTIMEZONE'])


def expand_calendar(item, lower, upper, zone, *, task=False, additions=True, overlap=False, with_properties=False, seek=None):
    """Source recurrence set. Return (start, exclusive end, DATE, original identity).

    None is reserved for entries without source scheduling data. Errors and work
    limits propagate, never masquerading as an empty set or a native one-off.
    """
    props = properties(item.get('icsRoundtrip'))
    if seek is not None:
        seek['next'] = None
    if not any(name in ('DTSTART', 'RRULE', 'RDATE', 'EXRULE', 'RECURRENCE-ID', 'STATUS') for name, _, _ in props):
        return None
    resolver = calendar_zones(item.get('icsTimezones'))
    def get(name, source=props):
        return next(((value, params) for key, params, value in source if key == name), ('', {}))
    if item.get('icsStatus', '').upper() == 'CANCELLED' or get('STATUS')[0].upper() == 'CANCELLED':
        return []
    if get('RECURRENCE-ID')[1].get('RANGE', 'THISANDFUTURE').upper() != 'THISANDFUTURE':
        raise ValueError('Unsupported recurrence range.')
    def parse(value, params):
        return date_time(value, params, zone, zone_resolver=resolver)
    value, params = get('DTSTART')
    if value:
        start, all_day = parse(value, params)
    else:
        date = item.get('startDatum' if task else 'datum') or (item.get('faellig') if task else '')
        time = item.get('startZeit' if task else 'zeit') or (item.get('faelligZeit') if task else '')
        start = datetime.fromisoformat(date + 'T' + (time or '00:00')).replace(tzinfo=zone)
        all_day = not time
    # DATE identity is civil, including dates skipped by a dateline change.
    if all_day:
        start = start.replace(tzinfo=None)
        lower, upper = lower.replace(tzinfo=None), upper.replace(tzinfo=None)
    else:
        lower = lower.replace(tzinfo=zone) if lower.tzinfo is None else lower
        upper = upper.replace(tzinfo=zone) if upper.tzinfo is None else upper
    def key(value):
        return value.replace(tzinfo=None) if all_day else _instant(value)
    def end_info(source, anchor, default=None):
        value, params = get('DUE' if task else 'DTEND', source)
        specification = get('DURATION', source)[0]
        if value:
            end = parse(value, params)[0]
            span = key(end) - key(anchor)
            specification = ''
        elif specification:
            span = key(duration_end(anchor, specification, all_day)) - key(anchor)
        elif default is not None:
            return default
        else:
            date = item.get('faellig' if task else 'endDatum') or anchor.strftime('%Y-%m-%d')
            time = item.get('faelligZeit' if task else 'endZeit') or anchor.strftime('%H:%M:%S')
            end = datetime.fromisoformat(date + 'T' + time).replace(tzinfo=anchor.tzinfo)
            span = max(timedelta(0), key(end) - key(anchor)) + (timedelta(days=1) if all_day and not task else timedelta(0))
        if span < timedelta(0):
            raise ValueError('Invalid calendar end.')
        return span, specification
    duration = end_info(props, start)
    ranges = []
    for lines in item.get('icsRangeOverrides') or []:
        definition = properties(lines)
        value, params = get('RECURRENCE-ID', definition)
        if params.get('RANGE', '').upper() != 'THISANDFUTURE':
            raise ValueError('Unsupported recurrence range.')
        original = parse(value, params)[0]
        value, params = get('DTSTART', definition)
        replacement = parse(value, params)[0] if value else original
        shift = (replacement.astimezone(start.tzinfo).replace(tzinfo=None) - original.astimezone(start.tzinfo).replace(tzinfo=None)
                 if not all_day else replacement.replace(tzinfo=None) - original.replace(tzinfo=None))
        ranges.append((key(original), shift, end_info(definition, replacement, duration), get('STATUS', definition)[0].upper() == 'CANCELLED', definition))
    ranges.sort(key=lambda value: value[0])
    previous = duration
    for index, r in enumerate(ranges):
        if not any(name in ('DUE' if task else 'DTEND', 'DURATION') for name, _, _ in r[4]):
            ranges[index] = r = (r[0], r[1], previous, r[3], r[4])
        previous = r[2]
    padding = max([timedelta(0)] + [abs(value[1]) + timedelta(days=2) for value in ranges])
    durations = [duration] + [value[2] for value in ranges]
    lookback = max(info[0] for info in durations) if overlap else timedelta(0)
    if overlap and not all_day and any(re.search('[WD]', info[1]) for info in durations):
        lookback += timedelta(days=2)
    lo, hi = lower - padding - lookback, upper + padding
    values = {}
    def future(value):
        if seek is None or value is None:
            return
        value = value if all_day else value.astimezone(zone)
        value = (value - padding).replace(tzinfo=None)
        if seek['next'] is None or value < seek['next']:
            seek['next'] = value
    def finish_at(value, info):
        return duration_end(value, info[1], all_day) if info[1] else value + info[0] if all_day else (_instant(value) + info[0]).astimezone(value.tzinfo)
    def add(value, info=duration):
        if all_day:
            value = value.replace(tzinfo=None)
        if key(value) > key(hi):
            future(value)
        if (key(lo) <= key(value) or overlap and key(finish_at(value, info)) >= key(lower)) and key(value) <= key(hi):
            values[key(value)] = (value, info)
            if len(values) > MAX_OCCURRENCES:
                raise RecurrenceLimitError('Calendar recurrence output limit exceeded.', resource='output')
    add(start)
    if not get('RECURRENCE-ID')[0]:
        for name, _, text in props:
            if name == 'RRULE':
                rule_seek = {} if seek is not None else None
                for value in Rule(text, start, all_day=all_day).between(lo, hi, seek=rule_seek):
                    add(value)
                if rule_seek is not None:
                    future(rule_seek.get('next'))
    raw_dates = set()
    if additions:
        for name, params, text in props:
            if name != 'RDATE':
                continue
            for part in text.split(','):
                period = part.split('/', 1)
                value = parse(period[0], params)[0]
                info = duration
                if len(period) == 2:
                    end = duration_end(value, period[1], all_day) if period[1].startswith(('P', '+P')) else parse(period[1], params)[0]
                    info = (key(end) - key(value), period[1] if period[1].startswith(('P', '+P')) else '')
                    if info[0] <= timedelta(0):
                        raise ValueError('Invalid recurrence period.')
                add(value, info)
                raw_dates.add(value.astimezone(zone).strftime('%Y-%m-%d'))
        for extra in item.get('icsZusatzTermine') or []:
            if extra.get('datum') not in raw_dates:
                add(datetime.fromisoformat(extra['datum'] + 'T' + (extra.get('zeit') or start.strftime('%H:%M:%S'))).replace(tzinfo=zone))
        for date in item.get('icsZusatzDaten') or []:
            if date not in raw_dates and not any(extra.get('datum') == date for extra in item.get('icsZusatzTermine') or []):
                add(datetime.fromisoformat(date + 'T' + start.strftime('%H:%M:%S')).replace(tzinfo=zone))
    precise = set()
    for name, params, text in props:
        if name == 'EXRULE':
            rule = Rule(text, start, all_day=all_day)
            # Overlapping PERIODs may start before the ordinary duration lookback.
            for identity, (value, _) in list(values.items()):
                if identity < key(lo) and rule.between(value, value):
                    values.pop(identity, None)
            for value in rule.between(lo, hi):
                values.pop(key(value), None)
        if name != 'EXDATE':
            continue
        for part in text.split(','):
            excluded, date_only = parse(part, params)
            if not date_only:
                precise.add(excluded.astimezone(zone).strftime('%Y-%m-%d'))
                values.pop(key(excluded), None)
            else:
                values = {k: v for k, v in values.items() if v[0].date() != excluded.date()}
    raw_precise = set(precise)
    for extra in item.get('icsAusnahmeTermine') or []:
        if extra.get('datum') not in raw_precise:
            values.pop(key(datetime.fromisoformat(extra['datum'] + 'T' + extra['zeit']).replace(tzinfo=zone)), None)
            precise.add(extra['datum'])
    result = []
    for identity, (value, info) in sorted(values.items()):
        local = value if all_day else value.astimezone(zone)
        date = local.strftime('%Y-%m-%d')
        if date in (item.get('icsAusnahmen') or []) and date not in precise:
            continue
        active = next((r for r in reversed(ranges) if r[0] <= identity), None)
        if active:
            if active[3]:
                continue
            value = (value if all_day else value.astimezone(start.tzinfo)) + active[1]
            info = active[2]
        finish = finish_at(value, info)
        if key(value) > key(upper) or (key(finish) < key(lower) if overlap else key(value) < key(lower)):
            continue
        occurrence = (value if all_day else value.astimezone(zone), finish if all_day else finish.astimezone(zone), all_day, identity)
        if with_properties:
            inherited = {}
            for r in ranges:
                if r[0] <= identity:
                    for name, params, text in r[4]:
                        if name not in ('DTSTART', 'DTEND', 'DUE', 'DURATION', 'RECURRENCE-ID', 'RRULE', 'RDATE', 'EXDATE', 'EXRULE', 'UID', 'DTSTAMP', 'SEQUENCE', 'LAST-MODIFIED'):
                            inherited[name] = (params, text)
            occurrence += (inherited,)
        result.append(occurrence)
    return sorted(result, key=lambda value: key(value[0]))


class Rule:
    """One RRULE or EXRULE value and its source DTSTART.

    ``all_day=True`` keeps DATE recurrences independent of timezone gaps and
    ignores BYHOUR/BYMINUTE/BYSECOND as RFC 5545 requires. Naive query bounds are
    source wall times, not operating-system local times. A floating DTSTART
    requires floating bounds; aware results retain their source tzinfo.

    Like CalendarRecurrence.cs, weekly BYSETPOS uses the complete WKST period,
    including the first period. YEARLY/BYWEEKNO selects complete week-years;
    selected weeks may extend into the preceding/following calendar year.
    """

    def __init__(self, text, start, *, all_day=False):
        if not isinstance(text, str) or len(text) > 65536 or not isinstance(start, datetime):
            raise ValueError("invalid recurrence rule/start")
        pairs = [part.split("=", 1) for part in text.upper().split(";")]
        if any(len(pair) != 2 or not pair[1] for pair in pairs) or len(dict(pairs)) != len(pairs):
            raise ValueError("invalid recurrence rule")
        self.values = dict(pairs)
        allowed = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "WKST", "BYDAY", "BYMONTH",
                   "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYSETPOS", "BYHOUR", "BYMINUTE", "BYSECOND"}
        if set(self.values) - allowed:
            raise ValueError("unsupported recurrence rule part")
        self.text = ";".join(key + "=" + value for key, value in sorted(self.values.items()))
        self.start = start.replace(microsecond=0, fold=0)
        self.all_day = bool(all_day)
        if self.all_day:
            self.start = self.start.replace(hour=0, minute=0, second=0)
        self.wall = self.start.replace(tzinfo=None)
        self.freq = self.values.get("FREQ")
        if self.freq not in (*UNITS, "MONTHLY", "YEARLY"):
            raise ValueError("unsupported recurrence frequency")
        self.subdaily = self.freq in ("HOURLY", "MINUTELY", "SECONDLY")
        if self.all_day and self.subdaily:
            raise ValueError("subdaily recurrence requires DATE-TIME DTSTART")
        self.interval = self._integer(self.values.get("INTERVAL", "1"), 1, 2147483647)
        self.count = self._integer(self.values["COUNT"], 1, 2147483647) if "COUNT" in self.values else None
        if self.count is not None and "UNTIL" in self.values:
            raise ValueError("COUNT and UNTIL are mutually exclusive")
        self.until = date_time(self.values["UNTIL"], {}, start.tzinfo)[0] if "UNTIL" in self.values else None
        if self.until and len(self.values["UNTIL"]) == 8:
            self.until = self.until.replace(hour=23, minute=59, second=59)
        if self.until and start.tzinfo is None and self.until.tzinfo is not None:
            raise ValueError("floating DTSTART requires floating UNTIL")
        self.week_start = WEEKDAYS.index(self.values.get("WKST", "MO"))
        self.months = self._numbers("BYMONTH", 1, 12)
        self.monthdays = self._numbers("BYMONTHDAY", -31, 31)
        self.yeardays = self._numbers("BYYEARDAY", -366, 366)
        self.weeknos = self._numbers("BYWEEKNO", -53, 53)
        self.positions = self._numbers("BYSETPOS", -366, 366)
        self.hours = self._numbers("BYHOUR", 0, 23, zero=True)
        self.minutes = self._numbers("BYMINUTE", 0, 59, zero=True)
        self.seconds = self._numbers("BYSECOND", 0, 59, zero=True)
        self.weekdays = []
        for part in self.values.get("BYDAY", "").split(",") if "BYDAY" in self.values else []:
            match = re.fullmatch(r"([+-]?[0-9]{1,2})?(MO|TU|WE|TH|FR|SA|SU)", part)
            if not match:
                raise ValueError("invalid BYDAY")
            ordinal = self._integer(match[1], -53, 53) if match[1] else 0
            if match[1] and (not ordinal or self.freq not in ("MONTHLY", "YEARLY") or self.weeknos):
                raise ValueError("invalid ordinal BYDAY")
            value = (ordinal, WEEKDAYS.index(match[2]))
            if value not in self.weekdays:
                self.weekdays.append(value)
        if (self.weeknos and self.freq != "YEARLY" or
                self.yeardays and self.freq in ("DAILY", "WEEKLY", "MONTHLY") or
                self.monthdays and self.freq == "WEEKLY" or
                self.positions and not any(key.startswith("BY") and key != "BYSETPOS" for key in self.values)):
            raise ValueError("invalid recurrence selector combination")
        self.day_selected = bool(self.weekdays or self.monthdays or self.yeardays or self.weeknos)
        if self.all_day:
            self.hours = self.minutes = self.seconds = ()
        self.anchor_day = self.wall.toordinal()
        if self.freq == "WEEKLY":
            self.anchor_day -= (self.wall.weekday() - self.week_start) % 7
        self.anchor_second = (self.anchor_day - 1) * 86400
        if self.subdaily:
            seconds = self.wall.hour * 3600 + self.wall.minute * 60 + self.wall.second
            unit = UNITS[self.freq]
            self.anchor_second += seconds // unit * unit
        self.repeatable = self.all_day or start.tzinfo is None or isinstance(start.tzinfo, timezone)
        maximum_times = ((1 if self.subdaily else len(self.hours) or 1) *
                         (1 if self.freq in ("MINUTELY", "SECONDLY") else len(self.minutes) or 1) *
                         (1 if self.freq == "SECONDLY" else len(self.seconds) or 1))
        maximum_days = {"WEEKLY": 7, "MONTHLY": 31, "YEARLY": 371 if self.weeknos else 366}.get(self.freq, 1)
        self.empty_positions = bool(self.positions) and all(abs(pos) > maximum_days * maximum_times for pos in self.positions)

    @staticmethod
    def _integer(value, minimum, maximum):
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            raise ValueError("invalid recurrence integer")
        digits = value.lstrip("+-").lstrip("0") or "0"
        if len(digits) > 10:
            raise ValueError("recurrence integer out of range")
        number = int(("-" if value.startswith("-") else "") + digits)
        if not minimum <= number <= maximum:
            raise ValueError("recurrence integer out of range")
        return number

    def _numbers(self, name, minimum, maximum, zero=False):
        if name not in self.values:
            return ()
        values = tuple(sorted({self._integer(value, minimum, maximum) for value in self.values[name].split(",")}))
        if not zero and 0 in values:
            raise ValueError("invalid " + name)
        return values

    def _week_one(self, year):
        # Ordinals permit the adjacent week-year at the civil date boundaries.
        if not 1 <= year <= 9999:
            base = 2000 + year % 400
            return self._week_one(base) + (year - base) // 400 * 146097
        fourth = datetime(year, 1, 4)
        return fourth.toordinal() - (fourth.weekday() - self.week_start) % 7

    def _matches_date(self, day, period_year=None):
        if self.months and day.month not in self.months:
            return False
        last = calendar.monthrange(day.year, day.month)[1]
        if self.monthdays and day.day not in self.monthdays and day.day - last - 1 not in self.monthdays:
            return False
        position = day.toordinal() - datetime(day.year, 1, 1).toordinal() + 1
        year_length = 365 + calendar.isleap(day.year)
        if self.yeardays and position not in self.yeardays and position - year_length - 1 not in self.yeardays:
            return False
        if self.weeknos:
            year = period_year if period_year is not None else day.year
            ordinal = day.toordinal()
            week = (ordinal - self._week_one(year)) // 7 + 1
            total = (self._week_one(year + 1) - self._week_one(year)) // 7
            if week not in self.weeknos and week - total - 1 not in self.weeknos:
                return False
        if self.weekdays:
            if self.freq == "YEARLY" and not self.months:
                before, after = position - 1, year_length - position
            else:
                before, after = day.day - 1, last - day.day
            if not any(day.weekday() == weekday and (not ordinal or
                (before // 7 + 1 == ordinal if ordinal > 0 else -(after // 7 + 1) == ordinal))
                       for ordinal, weekday in self.weekdays):
                return False
        elif self.freq == "WEEKLY" and day.weekday() != self.wall.weekday():
            return False
        if self.freq in ("MONTHLY", "YEARLY") and not self.day_selected and day.day != self.wall.day:
            return False
        return not (self.freq == "YEARLY" and not self.day_selected and not self.months and day.month != self.wall.month)

    def _period(self, index):
        if self.freq in UNITS:
            seconds = self.anchor_second + index * self.interval * UNITS[self.freq]
            ordinal, seconds = divmod(seconds, 86400)
            if ordinal + 1 > MAX_ORDINAL:
                return None
            return datetime.fromordinal(max(1, ordinal + 1)) + timedelta(seconds=seconds)
        if self.freq == "MONTHLY":
            year, month = divmod(self.wall.year * 12 + self.wall.month - 1 + index * self.interval, 12)
            month += 1
        else:
            year, month = self.wall.year + index * self.interval, 1
        return datetime(year, month, 1) if year <= 9999 else None

    def _index(self, value, ceil=False):
        if self.freq == "YEARLY":
            distance = value.year - self.wall.year
            step = self.interval
        elif self.freq == "MONTHLY":
            distance = (value.year - self.wall.year) * 12 + value.month - self.wall.month
            step = self.interval
        else:
            distance = (value.toordinal() - 1) * 86400 + value.hour * 3600 + value.minute * 60 + value.second - self.anchor_second
            step = self.interval * UNITS[self.freq]
        return max(0, (distance + (step - 1 if ceil else 0)) // step)

    def _indices(self, first, last, budget):
        index = first
        while index <= last:
            budget.charge(periods=1)
            period = self._period(index)
            if period is None:
                return
            if self.subdaily:
                jump = None
                try:
                    if not self._matches_date(period):
                        jump = period.replace(hour=0, minute=0, second=0) + timedelta(days=1)
                    elif self.hours and period.hour not in self.hours:
                        jump = period.replace(minute=0, second=0) + timedelta(hours=1)
                    elif self.freq in ("MINUTELY", "SECONDLY") and self.minutes and period.minute not in self.minutes:
                        jump = period.replace(second=0) + timedelta(minutes=1)
                    elif self.freq == "SECONDLY" and self.seconds and period.second not in self.seconds:
                        next_second = next((second for second in self.seconds if second > period.second), 60 + self.seconds[0])
                        jump = period + timedelta(seconds=next_second - period.second)
                except OverflowError:
                    return
                if jump is not None:
                    index = max(index + 1, self._index(jump, ceil=True))
                    continue
            yield index
            index += 1

    def _dates(self, index, budget=None):
        budget = budget or _Budget()
        period = self._period(index)
        if period is None:
            return []
        if self.freq == "WEEKLY":
            first = self.anchor_day + index * self.interval * 7
            days = [datetime.fromordinal(day) for day in range(max(1, first), min(MAX_ORDINAL + 1, first + 7))]
        elif self.freq == "YEARLY" and self.weeknos:
            days = [datetime.fromordinal(day) for day in range(
                max(1, self._week_one(period.year)), min(MAX_ORDINAL + 1, self._week_one(period.year + 1)))]
        elif self.freq in ("MONTHLY", "YEARLY"):
            months = [period.month] if self.freq == "MONTHLY" else self.months or (
                range(1, 13) if self.day_selected else [self.wall.month])
            days = []
            for month in months:
                last = calendar.monthrange(period.year, month)[1]
                selected = ({value if value > 0 else last + value + 1 for value in self.monthdays}
                            if self.monthdays else range(1, last + 1) if self.day_selected else [self.wall.day])
                days.extend(datetime(period.year, month, day) for day in sorted(selected) if 1 <= day <= last)
        else:
            days = [period.replace(hour=0, minute=0, second=0)]
        hours = (period.hour,) if self.subdaily else self.hours or (self.wall.hour,)
        minutes = (period.minute,) if self.freq in ("MINUTELY", "SECONDLY") else self.minutes or (self.wall.minute,)
        seconds = (period.second,) if self.freq == "SECONDLY" else self.seconds or (self.wall.second,)
        if (self.subdaily and self.hours and period.hour not in self.hours or
                self.freq in ("MINUTELY", "SECONDLY") and self.minutes and period.minute not in self.minutes or
                self.freq == "SECONDLY" and self.seconds and period.second not in self.seconds):
            return []
        result = []
        for day in days:
            budget.charge(candidates=1)
            if not self._matches_date(day, period.year):
                continue
            budget.charge(candidates=len(hours) * len(minutes) * len(seconds))
            for hour in hours:
                for minute in minutes:
                    for second in seconds:
                        value = day.replace(hour=hour, minute=minute, second=second, tzinfo=self.start.tzinfo)
                        if self.all_day or _exists(value):
                            result.append(value)
                            if len(result) > MAX_OCCURRENCES:
                                raise RecurrenceLimitError("Calendar recurrence period is too large.", resource="period")
        if self.positions:
            result = sorted({result[pos - 1 if pos > 0 else pos] for pos in self.positions if abs(pos) <= len(result)})
        return result

    def _prefix(self, index, clipped, budget):
        if not hasattr(self, "_prefix_cache"):
            try:
                self._prefix_cache = _prefix_state(self.text, self.wall, self.start.tzinfo, self.all_day)
            except TypeError:
                # An unhashable custom tzinfo gets private, exact checkpoints.
                self._prefix_cache = _Prefix()
        # Active workers retain their checkpoint even if other documents evict
        # this entry from the bounded, cross-instance cache.
        state = self._prefix_cache
        with state.lock:
            if index >= state.cursor:
                cursor, total = state.cursor, state.total
            else:
                checkpoint = bisect.bisect_right(state.indices, index) - 1
                cursor, total = state.indices[checkpoint], state.totals[checkpoint]
            partial = state.partials.get(index)
            if partial is not None and partial[0] > cursor:
                cursor, total = partial
            initial = cursor
            try:
                if self.count is not None and total - clipped >= self.count:
                    return total
                for period in self._indices(cursor, index - 1, budget):
                    total += len(self._dates(period, budget))
                    cursor = period + 1
                    budget.prefix_advanced(cursor)
                    if cursor > state.cursor:
                        state.remember(cursor, total)
                    if self.count is not None and total - clipped >= self.count:
                        return total
                if index > state.cursor:
                    state.remember(index, total)
                state.checkpoint_query(index, index, total)
                return total
            except RecurrenceLimitError as error:
                state.checkpoint_query(index, cursor, total)
                if cursor > initial and error.resource == "work":
                    error.retryable = True
                    error.resume_period = cursor
                raise

    def _count_before(self, index, budget):
        if not index:
            return 0
        if self.repeatable and self.freq in UNITS and not any(name.startswith("BY") for name in self.values):
            return index
        if not hasattr(self, "_clipped"):
            self._clipped = sum(value.replace(tzinfo=None) < self.wall for value in self._dates(0, budget))
        clipped = self._clipped
        cycle = {"DAILY": 146097, "WEEKLY": 20871, "MONTHLY": 4800, "YEARLY": 400}.get(self.freq)
        if self.subdaily:
            days = 146097 if any(name in self.values for name in ("BYMONTH", "BYMONTHDAY", "BYYEARDAY", "BYWEEKNO")) else 7 if self.weekdays else 1
            cycle = days * 86400 // UNITS[self.freq]
        cycle //= math.gcd(self.interval, cycle)
        if self.repeatable and index >= cycle:
            total = self._prefix(cycle, clipped, budget)
            if total - clipped >= self.count:
                return self.count
            full, remainder = divmod(index, cycle)
            if full * total - clipped >= self.count:
                return self.count
            return full * total + self._prefix(remainder, clipped, budget) - clipped
        return self._prefix(index, clipped, budget) - clipped

    def between(self, lower, upper, *, seek=None):
        if seek is not None:
            seek['next'] = None
        def bound(value):
            if not isinstance(value, datetime):
                raise ValueError("recurrence bounds must be datetimes")
            if self.all_day:
                return value.replace(tzinfo=self.start.tzinfo)
            if self.start.tzinfo is None:
                if value.tzinfo is not None:
                    raise ValueError("floating DTSTART requires floating bounds")
                return value
            return value.replace(tzinfo=self.start.tzinfo) if value.tzinfo is None else value.astimezone(self.start.tzinfo)

        lower, upper = bound(lower), bound(upper)
        if self.empty_positions:
            return []
        instant_of = (lambda value: value.replace(tzinfo=None)) if self.all_day else _instant
        low_instant, high_instant = instant_of(lower), instant_of(upper)
        if self.until is not None:
            high_instant = min(high_instant, instant_of(self.until))
        if low_instant > high_instant or high_instant < instant_of(self.start):
            return []
        if self.all_day:
            upper = high_instant.replace(tzinfo=self.start.tzinfo)
        elif self.start.tzinfo is not None:
            upper = high_instant.astimezone(self.start.tzinfo)
        else:
            upper = high_instant
        # An upper bound in the second fold also includes the end of the first
        # fold, even though those wall values can be later than both bounds.
        low_wall, high_wall = lower.replace(tzinfo=None), upper.replace(tzinfo=None)
        if not self.all_day and upper.tzinfo is not None and upper.fold:
            repeated = upper.replace(fold=0).utcoffset() - upper.utcoffset()
            if repeated > timedelta(0):
                high_wall = min(datetime.max - repeated, high_wall) + repeated
        first = self._index(min(low_wall, upper.replace(tzinfo=None)))
        last = self._index(max(low_wall, high_wall))
        if self.freq == "YEARLY" and self.weeknos:
            first, last = max(0, first - 1), last + 1
        budget = _Budget()
        used = self._count_before(first, budget) if self.count is not None else 0
        result = []
        if self.count is not None and used >= self.count:
            return result
        for index in self._indices(first, last, budget):
            for value in self._dates(index, budget):
                if value.replace(tzinfo=None) < self.wall:
                    continue
                instant = instant_of(value)
                if instant > high_instant:
                    continue
                used += 1
                if self.count is not None and used > self.count:
                    return result
                if low_instant <= instant:
                    result.append(value)
                    if len(result) > MAX_OCCURRENCES:
                        raise RecurrenceLimitError("Calendar recurrence window is too large.", resource="window")
        if seek is not None and (self.count is None or used < self.count) and (self.until is None or high_instant < instant_of(self.until)):
            index = self._index(high_wall)
            period = self._period(index)
            if self.freq in UNITS:
                span = timedelta(seconds=UNITS[self.freq])
            elif self.freq == 'MONTHLY':
                span = timedelta(days=calendar.monthrange(period.year, period.month)[1])
            else:
                span = timedelta(days=365 + calendar.isleap(period.year))
            next_period = self._period(index + 1)
            # Compare distances without constructing a period end in year 10000.
            if high_wall - period < span:
                if upper.replace(tzinfo=None) < datetime.max:
                    seek['next'] = upper + timedelta(microseconds=1)
            elif next_period is not None:
                seek['next'] = next_period.replace(tzinfo=self.start.tzinfo)
        return result
