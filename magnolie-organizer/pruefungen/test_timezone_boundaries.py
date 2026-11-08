"""#436: embedded historical anchors must not overflow for modern events."""
from datetime import datetime, timedelta, timezone

import pytest

from test_recurrence_timezones import m
from magnolie_recurrence import CalendarZone


def definition(stamp='00010101T000000', before='+0100', after=None):
    return ['BEGIN:VTIMEZONE', 'TZID:External/Initial', 'BEGIN:STANDARD',
            'DTSTART:' + stamp, 'TZOFFSETFROM:' + before, 'TZOFFSETTO:' + (after or before),
            'END:STANDARD', 'END:VTIMEZONE']


def boundary_fixtures():
    """Same actual codec/Web probe contract used by recurrence integration."""
    fixtures = []
    cases = [(stamp, offset, None, seconds) for stamp in ('00010101T000000', '99991231T235959')
             for offset, seconds in (('+0100', 3600), ('-0100', -3600), ('+005328', 3208), ('-005328', -3208))]
    cases += [('00010101T000000', '+0100', '+0200', 7200), ('99991231T235959', '-0100', '-0200', -3600)]
    for index, (stamp, before, after, seconds) in enumerate(cases):
        start = datetime(2026, 3, 28, 10) - timedelta(seconds=seconds)
        fixtures.append(dict(name='boundary-' + str(index), zone='UTC', lower='2026-03-28T00:00:00Z', upper='2026-03-29T00:00:00Z',
            components=[definition(stamp, before, after), ['BEGIN:VEVENT', 'UID:boundary-' + str(index), 'SUMMARY:Boundary fixture',
                'DTSTART;TZID=External/Initial:20260328T100000', 'DTEND;TZID=External/Initial:20260328T110000', 'END:VEVENT']],
            expected=[start.isoformat() + '/' + (start + timedelta(hours=1)).isoformat()], roundtrip=True))
    return fixtures


def test_historical_constant_anchor_resolves_modern_event():
    zone = CalendarZone(definition())
    assert datetime(2026, 3, 28, 10, tzinfo=zone).utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize('stamp', ['00010101T000000', '99991231T235959'])
@pytest.mark.parametrize('offset,seconds', [('+0100', 3600), ('-0100', -3600), ('+005328', 3208), ('-005328', -3208)])
def test_boundary_constant_anchors_preserve_exact_offsets(stamp, offset, seconds):
    zone = CalendarZone(definition(stamp, offset))
    utc = datetime(2026, 3, 28, 9, tzinfo=timezone.utc)
    local = utc.astimezone(zone)
    assert local.replace(tzinfo=None) == utc.replace(tzinfo=None) + timedelta(seconds=seconds)
    assert local.utcoffset() == timedelta(seconds=seconds)
    assert local.astimezone(timezone.utc) == utc
    # Query both extreme years; the transition itself can be outside UTC's
    # datetime domain, but lookup must retain its exact before/after semantics.
    assert datetime(1, 1, 2, 12, tzinfo=zone).utcoffset() == timedelta(seconds=seconds)
    assert datetime(9999, 12, 30, 12, tzinfo=zone).utcoffset() == timedelta(seconds=seconds)


@pytest.mark.parametrize('stamp,before,after,expected', [
    ('00010101T000000', '+0100', '+0200', 7200),
    ('99991231T235959', '-0100', '-0200', -3600)])
def test_genuine_outside_range_transition_is_not_moved_or_clamped(stamp, before, after, expected):
    zone = CalendarZone(definition(stamp, before, after))
    assert datetime(2026, 3, 28, 12, tzinfo=zone).utcoffset() == timedelta(seconds=expected)


@pytest.mark.parametrize('stamp,offset,until', [
    ('99990101T000000', '+0100', '99991231T235959Z'),
    ('00010101T000000', '-0100', '00010101T000000Z')])
def test_unrepresentable_local_until_is_clear_format_error(stamp, offset, until):
    lines = definition(stamp, offset)
    lines.insert(-2, 'RRULE:FREQ=YEARLY;UNTIL=' + until)
    with pytest.raises(ValueError, match='Timezone UNTIL.*date range'):
        CalendarZone(lines)


def test_year_one_until_keeps_four_digit_year():
    lines = definition()
    lines.insert(-2, 'RRULE:FREQ=YEARLY;UNTIL=00010101T000000Z')
    zone = CalendarZone(lines)
    assert datetime(2026, 3, 28, 12, tzinfo=zone).utcoffset() == timedelta(hours=1)


def test_outside_range_result_is_format_error_not_fabricated_date():
    zone = CalendarZone(definition())
    with pytest.raises(ValueError, match='outside the supported date range'):
        datetime.max.replace(tzinfo=timezone.utc).astimezone(zone)


def test_unbounded_observance_rule_terminates_at_year_9999():
    lines = definition('99980101T000000', '-0100')
    lines.insert(-2, 'RRULE:FREQ=YEARLY')
    assert datetime(9999, 12, 30, 12, tzinfo=CalendarZone(lines)).utcoffset() == -timedelta(hours=1)


def test_real_codec_retains_source_and_exact_modern_event_instant():
    m._REGIONAL['timeZone'] = 'UTC'
    text = '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', *definition(),
        'BEGIN:VEVENT', 'UID:synthetic-boundary-event', 'SUMMARY:Synthetic boundary event',
        'DTSTART;TZID=External/Initial:20260328T100000', 'DTEND;TZID=External/Initial:20260328T110000',
        'END:VEVENT', 'END:VCALENDAR', ''])
    items = m.ics_lesen(text)['termine']
    assert len(items) == 1
    values = m._ics_vorkommen(items[0], datetime(2026, 3, 28), datetime(2026, 3, 29))
    assert len(values) == 1 and values[0]['zeit'] == '09:00' and values[0]['endZeit'] == '10:00'
    exported = m.ics_schreiben_termine(items)
    assert 'DTSTART:00010101T000000' in exported and 'TZID:External/Initial' in exported
    assert 'DTSTART;TZID=External/Initial:20260328T100000' in exported
    reopened = m.ics_lesen(exported)['termine']
    assert len(reopened) == 1
    again = m._ics_vorkommen(reopened[0], datetime(2026, 3, 28), datetime(2026, 3, 29))
    fields = ('uid', 'titel', 'datum', 'zeit', 'endDatum', 'endZeit')
    assert [[value.get(key) for key in fields] for value in again] == [[value.get(key) for key in fields] for value in values]
