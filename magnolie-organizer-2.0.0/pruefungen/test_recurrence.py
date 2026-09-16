"""Dependency-free RFC recurrence, DST, seeking and resource-limit regressions."""

import sys
import io
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "bin"))
import magnolie_recurrence as recurrence
from magnolie_recurrence import Rule, RecurrenceLimitError


@pytest.fixture(autouse=True)
def clear_prefix_cache():
    recurrence._prefix_state.cache_clear()


def stamps(values):
    return [value.strftime("%Y-%m-%dT%H:%M:%S") for value in values]


@pytest.mark.parametrize("frequency,interval,expected", [
    ("SECONDLY", 20, ["09:00:00", "09:00:20", "09:00:40"]),
    ("MINUTELY", 7, ["09:00:00", "09:07:00", "09:14:00"]),
    ("HOURLY", 3, ["09:00:00", "12:00:00", "15:00:00"]),
    ("DAILY", 2, ["2026-09-01", "2026-09-03", "2026-09-05"]),
    ("WEEKLY", 2, ["2026-09-01", "2026-09-15", "2026-09-29"]),
    ("MONTHLY", 2, ["2026-09-01", "2026-11-01", "2027-01-01"]),
    ("YEARLY", 2, ["2026-09-01", "2028-09-01", "2030-09-01"]),
])
def test_all_seven_frequencies(frequency, interval, expected):
    start = datetime(2026, 9, 1, 9)
    rule = Rule(f"FREQ={frequency};INTERVAL={interval};COUNT=3", start)
    result = rule.between(start, datetime(2031, 1, 1))
    assert [value.strftime("%H:%M:%S" if frequency in ("SECONDLY", "MINUTELY", "HOURLY") else "%Y-%m-%d") for value in result] == expected


@pytest.mark.parametrize("zone,start,expected", [
    ("Europe/Berlin", "2026-03-27T02:30:00", ["2026-03-27", "2026-03-28", "2026-03-30", "2026-03-31"]),
    ("Australia/Lord_Howe", "2026-10-02T02:15:00", ["2026-10-02", "2026-10-03", "2026-10-05", "2026-10-06"]),
    ("Pacific/Apia", "2011-12-28T09:00:00", ["2011-12-28", "2011-12-29", "2011-12-31", "2012-01-01"]),
    ("America/Sao_Paulo", "2018-11-03T00:30:00", ["2018-11-03", "2018-11-05", "2018-11-06", "2018-11-07"]),
])
def test_count_window_invariance_across_gap_and_date_line(zone, start, expected):
    start = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(zone))
    text = "FREQ=DAILY;COUNT=4"
    whole = Rule(text, start).between(start, start + timedelta(days=8))
    assert [value.strftime("%Y-%m-%d") for value in whole] == expected
    for offset in (3, 1, 5, 0, 2, 4):
        lower, upper = start + timedelta(days=offset), start + timedelta(days=8)
        assert Rule(text, start).between(lower, upper) == [value for value in whole if value >= lower]


@pytest.mark.parametrize("start", [datetime(1998, 1, 5, 9), datetime(2021, 3, 1, 9)])
@pytest.mark.parametrize("text", ["FREQ=WEEKLY;INTERVAL=2;COUNT=2000;BYDAY=MO,WE",
                                  "FREQ=MONTHLY;INTERVAL=2;COUNT=900;BYDAY=2MO,-1FR"])
def test_forum_anchors_count_and_partition_invariance(start, text):
    start = start.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    upper = datetime(2026, 10, 1, tzinfo=start.tzinfo)
    whole = Rule(text, start).between(start, upper)
    lower = datetime(2026, 9, 1, tzinfo=start.tzinfo)
    result = Rule(text, start).between(lower, upper)
    assert result and result == [value for value in whole if value >= lower]
    parts = [value for offset in range(30) for value in Rule(text, start).between(
        lower + timedelta(days=offset), lower + timedelta(days=offset + 1, microseconds=-1))]
    assert parts == [value for value in result if value < upper]


@pytest.mark.parametrize("count", [2050, 2100, 2150])
def test_count_does_not_repeat_timezone_history_after_400_years(count):
    start = datetime(1600, 1, 1, tzinfo=ZoneInfo("Europe/Berlin"))
    text = f"FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=27,28,29,30,31;BYHOUR=2;BYMINUTE=30;COUNT={count}"
    lower, upper = datetime(2021, 3, 1, tzinfo=start.tzinfo), datetime(2060, 1, 1, tzinfo=start.tzinfo)
    whole = Rule(text, start).between(start, upper)
    recurrence._prefix_state.cache_clear()
    assert Rule(text, start).between(lower, upper) == [value for value in whole if value >= lower]


def test_bysetpos_uses_valid_source_times_before_count():
    start = datetime(2026, 3, 28, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    text = "FREQ=DAILY;BYHOUR=2,3;BYSETPOS=1;COUNT=3"
    expected = ["2026-03-28T02:30:00", "2026-03-29T03:30:00", "2026-03-30T02:30:00"]
    rule = Rule(text, start)
    assert stamps(rule.between(start, start + timedelta(days=5))) == expected
    assert stamps(Rule(text, start).between(start + timedelta(days=2), start + timedelta(days=5))) == expected[2:]


def test_all_day_dates_are_not_removed_by_timezone_history():
    start = datetime(2011, 12, 28, tzinfo=ZoneInfo("Pacific/Apia"))
    rule = Rule("FREQ=DAILY;COUNT=4;BYHOUR=2;BYMINUTE=30;BYSECOND=15", start, all_day=True)
    assert stamps(rule.between(start, start + timedelta(days=7))) == [
        "2011-12-28T00:00:00", "2011-12-29T00:00:00", "2011-12-30T00:00:00", "2011-12-31T00:00:00"]


def test_ambiguous_times_are_once_and_bounds_compare_instants():
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 10, 25, 1, 30, tzinfo=zone)
    rule = Rule("FREQ=HOURLY;COUNT=4", start)
    result = rule.between(start, start + timedelta(hours=5))
    assert [value.hour for value in result] == [1, 2, 3, 4]
    assert all(value.fold == 0 for value in result)
    lower = datetime(2026, 10, 25, 2, 15, tzinfo=zone, fold=1)
    assert [value.hour for value in rule.between(lower, start + timedelta(hours=5))] == [3, 4]
    assert rule.between(datetime(2026, 10, 25, 2, 40, tzinfo=zone), lower) == []


def test_window_ending_in_second_fold_keeps_late_first_fold_minutes():
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2026, 10, 25, 1, 30, tzinfo=zone)
    text = "FREQ=MINUTELY;COUNT=200"
    lower = datetime(2026, 10, 25, 2, 45, tzinfo=zone)
    upper = datetime(2026, 10, 25, 2, 15, tzinfo=zone, fold=1)
    result = Rule(text, start).between(lower, upper)
    assert [value.minute for value in result] == list(range(45, 60))
    whole = Rule(text, start).between(start, upper)
    assert result == [value for value in whole if value.astimezone(timezone.utc) >= lower.astimezone(timezone.utc)]


@pytest.mark.parametrize("text,expected", [
    ("FREQ=MINUTELY;INTERVAL=7;BYSECOND=0,30;COUNT=3", ["09:07:00", "09:07:30", "09:14:00"]),
    ("FREQ=HOURLY;BYMINUTE=15,45;BYSECOND=0,30;BYSETPOS=2,-1;COUNT=3", ["09:15:30", "09:45:30", "10:15:30"]),
    ("FREQ=SECONDLY;INTERVAL=13;BYSECOND=6,19,32,45,58;COUNT=3", ["09:01:06", "09:01:19", "09:01:32"]),
])
def test_subdaily_expansion_limiting_and_first_period_clipping(text, expected):
    start = datetime(2026, 9, 1, 9, 0, 40)
    assert [value.strftime("%H:%M:%S") for value in Rule(text, start).between(start, start + timedelta(days=2))] == expected


@pytest.mark.parametrize("week_start", ["MO", "SU", "FR"])
def test_yearly_week_numbers_are_window_invariant_at_year_boundary(week_start):
    start = datetime(2021, 3, 1, 9)
    text = f"FREQ=YEARLY;BYWEEKNO=1,-1;BYDAY=MO,SU;WKST={week_start};COUNT=40"
    end = datetime(2027, 1, 5)
    whole = Rule(text, start).between(start, end)
    for lower in (datetime(2024, 12, 25), datetime(2025, 1, 1), datetime(2026, 1, 1)):
        assert Rule(text, start).between(lower, end) == [value for value in whole if value >= lower]


def test_exrule_uses_same_counted_rule_evaluator():
    start = datetime(2026, 9, 1, 9)
    upper = datetime(2026, 9, 10)
    included = Rule("FREQ=DAILY;COUNT=7", start).between(start, upper)
    excluded = set(Rule("FREQ=DAILY;INTERVAL=2;COUNT=2", start).between(start, upper))
    assert [value.day for value in included if value not in excluded] == [2, 4, 5, 6, 7]


@pytest.mark.parametrize("text", [
    "", "FREQ=", "FREQ=DAILY;", "FREQ=DAILY;FREQ=WEEKLY", "FREQ=DAILY;COUNT=2;UNTIL=20260101",
    "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-1", "FREQ=DAILY;INTERVAL=2147483648",
    "FREQ=DAILY;COUNT=2147483648", "FREQ=DAILY;INTERVAL=9999999999999999999999999999999",
    "FREQ=DAILY;COUNT=1.0", "FREQ=DAILY;COUNT= 1", "FREQ=DAILY;BYMONTH=0",
    "FREQ=YEARLY;BYMONTH=13", "FREQ=YEARLY;BYYEARDAY=0", "FREQ=YEARLY;BYWEEKNO=54",
    "FREQ=DAILY;BYHOUR=24", "FREQ=DAILY;BYMINUTE=60", "FREQ=DAILY;BYSECOND=60",
    "FREQ=DAILY;BYDAY=1MO", "FREQ=YEARLY;BYDAY=54MO", "FREQ=MONTHLY;BYDAY=0MO",
    "FREQ=WEEKLY;BYMONTHDAY=1", "FREQ=DAILY;BYYEARDAY=1", "FREQ=MONTHLY;BYWEEKNO=1",
    "FREQ=YEARLY;BYWEEKNO=1;BYDAY=1MO", "FREQ=DAILY;BYSETPOS=1", "FREQ=DAILY;BYHOUR=",
    "FREQ=DAILY;BYHOUR=1,", "FREQ=YEARLY;BYEASTER=1", "FREQ=MONTHLY;BYDAY=+MO",
])
def test_invalid_rules_fail_closed(text):
    with pytest.raises(ValueError):
        Rule(text, datetime(2021, 3, 1, 9))


@pytest.mark.parametrize("frequency", ["SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
def test_huge_valid_intervals_and_date_boundaries_do_not_overflow(frequency):
    start = datetime(9999, 12, 30, 9)
    assert Rule(f"FREQ={frequency};INTERVAL=2147483647;COUNT=2", start).between(start, datetime.max) == [start]
    first = datetime(1, 1, 1)
    assert Rule(f"FREQ={frequency};INTERVAL=2147483647;COUNT=1;WKST=SU", first).between(first, first) == [first]


def test_uncounted_and_simple_fixed_count_seek_without_history():
    for first in (datetime(1998, 1, 5, 9), datetime(2021, 3, 1, 9)):
        for zone in (None, timezone.utc):
            start = first.replace(tzinfo=zone)
            lower, upper = datetime(2026, 9, 7, 9, tzinfo=zone), datetime(2026, 9, 7, 9, 0, 3, tzinfo=zone)
            for ending in ("", ";COUNT=2147483647"):
                rule = Rule("FREQ=SECONDLY" + ending, start)
                with mock.patch.object(rule, "_dates", wraps=rule._dates) as dates:
                    assert len(rule.between(lower, upper)) == 4
                    assert dates.call_count == 4


@pytest.mark.parametrize('frequency', [*recurrence.UNITS, 'MONTHLY', 'YEARLY'])
@pytest.mark.parametrize('ending', ['', ';COUNT=1', ';COUNT=2', ';UNTIL=99991231T235959'])
@pytest.mark.parametrize('zone', [None, timezone.utc])
def test_seek_at_domain_end_preserves_results_and_terminates(frequency, ending, zone):
    start = datetime(9999, 12, 31, 23, 59, 59, tzinfo=zone)
    rule = Rule('FREQ=' + frequency + ending, start)
    seek = {}
    upper = datetime.max.replace(tzinfo=zone)
    assert rule.between(start, upper, seek=seek) == [start]
    assert seek == {'next': None}
    assert Rule('FREQ=' + frequency + ';BYMONTH=2', start).between(start, upper, seek=seek) == []
    assert seek == {'next': None}


@pytest.mark.parametrize('frequency', [*recurrence.UNITS, 'MONTHLY', 'YEARLY'])
def test_seek_in_last_period_advances_without_overflow(frequency):
    start = datetime(9999, 12, 31, 23, 59, 58)
    rule = Rule('FREQ=' + frequency + ';INTERVAL=2147483647', start)
    seek = {}
    assert rule.between(start, start, seek=seek) == [start]
    assert seek['next'] == start + timedelta(microseconds=1)
    assert rule.between(seek['next'], datetime.max, seek=seek) == []
    assert seek['next'] is None


def test_seek_keeps_errors_and_budget_failures(monkeypatch):
    start = datetime(9999, 12, 31, 23, 59, 58)
    with pytest.raises(ValueError):
        Rule('FREQ=INVALID', start).between(start, datetime.max, seek={})
    monkeypatch.setattr(recurrence, 'MAX_PERIODS', 1)
    seek = {}
    with pytest.raises(RecurrenceLimitError) as error:
        Rule('FREQ=SECONDLY', start).between(start, datetime.max, seek=seek)
    assert error.value.resource == 'work' and not error.value.retryable
    assert seek['next'] is None


def test_count_prefix_is_shared_and_incremental_in_real_source_zone():
    start = datetime(1998, 1, 5, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    text = "FREQ=DAILY;COUNT=20000"
    lower, upper = datetime(2026, 9, 1, tzinfo=start.tzinfo), datetime(2026, 9, 3, tzinfo=start.tzinfo)
    first = Rule(text, start).between(lower, upper)
    fresh = Rule(text, start)
    with mock.patch.object(fresh, "_dates", wraps=fresh._dates) as dates:
        assert fresh.between(lower, upper) == first
        assert dates.call_count <= 5
    next_rule = Rule(text, start)
    with mock.patch.object(next_rule, "_dates", wraps=next_rule._dates) as dates:
        assert next_rule.between(lower + timedelta(days=1), upper + timedelta(days=1))
        assert dates.call_count <= 6


def test_bounded_prefix_retry_preserves_progress_without_partial_results(monkeypatch):
    start = datetime(2026, 1, 1, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    text = "FREQ=DAILY;COUNT=200"
    lower, upper = start + timedelta(days=150), start + timedelta(days=153)
    expected = Rule(text, start).between(start, upper)
    recurrence._prefix_state.cache_clear()
    monkeypatch.setattr(recurrence, "MAX_PERIODS", 32)
    cursors = []
    for _ in range(6):
        try:
            result = Rule(text, start).between(lower, upper)
            break
        except RecurrenceLimitError as error:
            assert error.retryable
            cursors.append(error.resume_period)
    else:
        pytest.fail("bounded prefix never completed")
    assert cursors == sorted(set(cursors)) and cursors[-1] > cursors[0]
    assert result == [value for value in expected if value >= lower]


def test_active_prefix_worker_survives_shared_cache_eviction(monkeypatch):
    start = datetime(2026, 1, 1, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    rule = Rule("FREQ=DAILY;COUNT=200", start)
    lower, upper = start + timedelta(days=100), start + timedelta(days=103)
    expected = Rule(rule.text, start).between(start, upper)
    recurrence._prefix_state.cache_clear()
    monkeypatch.setattr(recurrence, "MAX_PERIODS", 32)
    previous = 0
    for attempt in range(5):
        try:
            result = rule.between(lower, upper)
            break
        except RecurrenceLimitError as error:
            assert error.retryable and error.resume_period > previous
            previous = error.resume_period
            for index in range(40):
                recurrence._prefix_state(f"other-{attempt}-{index}", start.replace(tzinfo=None), start.tzinfo, False)
    else:
        pytest.fail("cache eviction lost the active worker's progress")
    assert result == [value for value in expected if value >= lower]


def test_cycle_prefix_budget_retry_reuses_completed_cycle(monkeypatch):
    start = datetime(2026, 1, 1)
    rule = Rule("FREQ=HOURLY;BYMINUTE=0;COUNT=10000", start)
    lower, upper = start + timedelta(hours=100), start + timedelta(hours=103)
    monkeypatch.setattr(recurrence, "MAX_PERIODS", 24)
    with pytest.raises(RecurrenceLimitError) as error:
        rule.between(lower, upper)
    assert error.value.retryable
    assert rule.between(lower, upper) == [lower + timedelta(hours=index) for index in range(4)]


def test_backward_prefix_queries_make_bounded_retry_progress(monkeypatch):
    start = datetime(2000, 1, 1, tzinfo=ZoneInfo("Europe/Berlin"))
    text = "FREQ=YEARLY;BYMONTHDAY=1;COUNT=10000"
    rule = Rule(text, start)
    assert rule.between(datetime(2200, 1, 1), datetime(2201, 1, 1))
    lower, upper = datetime(2040, 1, 1), datetime(2041, 1, 1)
    monkeypatch.setattr(recurrence, "MAX_CANDIDATES", 128)
    cursors = []
    for _ in range(12):
        try:
            result = rule.between(lower, upper)
            break
        except RecurrenceLimitError as error:
            assert error.retryable
            cursors.append(error.resume_period)
    else:
        pytest.fail("backward prefix query repeatedly lost its checkpoint")
    assert cursors and cursors == sorted(set(cursors))
    assert len(result) == 13 and result[0].year == 2040 and result[-1].year == 2041


def test_large_output_and_period_limits_never_return_partial_lists(monkeypatch):
    monkeypatch.setattr(recurrence, "MAX_OCCURRENCES", 10)
    start = datetime(2026, 1, 1)
    with pytest.raises(RecurrenceLimitError) as error:
        Rule("FREQ=SECONDLY", start).between(start, start + timedelta(minutes=1))
    assert not error.value.retryable
    with pytest.raises(RecurrenceLimitError) as error:
        Rule("FREQ=YEARLY;BYDAY=MO;BYSETPOS=-1", start).between(start, start + timedelta(days=366))
    assert not error.value.retryable


def test_float_bounds_do_not_use_process_timezone():
    start = datetime(2026, 9, 1, 9)
    assert Rule("FREQ=DAILY;COUNT=1", start).between(start, start) == [start]
    with pytest.raises(ValueError):
        Rule("FREQ=DAILY", start).between(start.replace(tzinfo=timezone.utc), start.replace(tzinfo=timezone.utc))


def test_windows_full_first_week_bysetpos_convention():
    start = datetime(2024, 2, 27, 16, 32, 40)
    text = "FREQ=WEEKLY;INTERVAL=3;BYSECOND=10,30;BYDAY=MO,WE,FR;BYSETPOS=2,-2;COUNT=3"
    result = Rule(text, start).between(start, start + timedelta(days=60))
    assert stamps(result) == ["2024-03-01T16:32:10", "2024-03-18T16:32:30", "2024-03-22T16:32:10"]
    assert Rule(text, start).between(datetime(2024, 3, 1), datetime(2024, 4, 1)) == result


def test_windows_week_year_spill_and_interval_convention():
    start = datetime(2014, 1, 1, 9)
    text = "FREQ=YEARLY;INTERVAL=2;BYWEEKNO=1;BYDAY=MO;COUNT=3"
    assert stamps(Rule(text, start).between(start, datetime(2020, 1, 10))) == [
        "2016-01-04T09:00:00", "2018-01-01T09:00:00", "2019-12-30T09:00:00"]
    assert stamps(Rule(text, start).between(datetime(2019, 12, 28), datetime(2020, 1, 2))) == ["2019-12-30T09:00:00"]
    assert Rule("FREQ=YEARLY;BYWEEKNO=53;BYDAY=SU", datetime(2021, 3, 1)).between(
        datetime(2022, 1, 1), datetime(2022, 1, 3)) == []


def test_calendar_scoped_timezone_resolver_is_used_without_global_registration():
    local = timezone(timedelta(hours=5, minutes=45))
    resolver = mock.Mock(return_value=local)
    value, all_day = recurrence.date_time("20260907T090000", {"TZID": "calendar-private"}, timezone.utc, zone_resolver=resolver)
    resolver.assert_called_once_with("calendar-private")
    assert value.tzinfo is local and not all_day
    assert Rule("FREQ=DAILY;COUNT=2", value).between(value, value + timedelta(days=2)) == [value, value + timedelta(days=1)]


def test_cached_prefixes_do_not_alias_changed_timezone_rules_with_same_name():
    def zone(transitions):
        header = b"TZif\0" + bytes(15) + struct.pack(">6l", 0, 0, 0, len(transitions), 2, 8)
        table = b"".join(struct.pack(">l", int(stamp.timestamp())) for stamp, _ in transitions)
        types = bytes(index for _, index in transitions)
        info = struct.pack(">lBB", 0, 0, 0) + struct.pack(">lBB", 3600, 1, 4)
        return ZoneInfo.from_file(io.BytesIO(header + table + types + info + b"STD\0DST\0"), key="test/same-name")

    old = zone([(datetime(2026, 3, 29, 1, tzinfo=timezone.utc), 1),
                (datetime(2026, 10, 25, 1, tzinfo=timezone.utc), 0)])
    new = zone([])
    start = datetime(2026, 3, 27, 1, 30)
    text = "FREQ=DAILY;COUNT=4"
    lower, upper = datetime(2026, 3, 30), datetime(2026, 4, 2)
    assert [value.day for value in Rule(text, start.replace(tzinfo=old)).between(lower, upper)] == [30, 31]
    assert [value.day for value in Rule(text, start.replace(tzinfo=new)).between(lower, upper)] == [30]
    assert recurrence._prefix_state.cache_info().currsize == 2


def test_zero_padding_does_not_turn_valid_small_integer_into_overflow():
    start = datetime(2026, 9, 1)
    text = "FREQ=DAILY;INTERVAL=" + "0" * 1000 + "2;COUNT=2"
    assert Rule(text, start).between(start, start + timedelta(days=4)) == [start, start + timedelta(days=2)]


def test_impossible_subdaily_positions_do_not_scan_history_or_window():
    start = datetime(1998, 1, 5)
    for frequency in ("SECONDLY", "MINUTELY", "HOURLY"):
        rule = Rule(f"FREQ={frequency};BYDAY=MO,WE,FR;BYSETPOS=2,-2;COUNT=100", start)
        with mock.patch.object(rule, "_dates", side_effect=AssertionError("impossible set scanned")):
            assert rule.between(datetime(2026, 9, 1), datetime.max) == []


def test_fixed_zone_calendar_cycles_keep_leap_skips_and_first_period_clipping():
    start = datetime(1600, 2, 29, 9, tzinfo=timezone.utc)
    lower, upper = datetime(2400, 1, 1, tzinfo=timezone.utc), datetime(2405, 1, 1, tzinfo=timezone.utc)
    assert Rule("FREQ=YEARLY;COUNT=194", start).between(lower, upper) == []
    assert stamps(Rule("FREQ=YEARLY;COUNT=195", start).between(lower, upper)) == ["2400-02-29T09:00:00"]
    start = datetime(1600, 1, 15, 9)
    text = "FREQ=MONTHLY;BYDAY=2MO;COUNT=9600"
    assert stamps(Rule(text, start).between(datetime(2400, 1, 1), datetime(2400, 3, 1))) == ["2400-01-10T09:00:00"]


def test_until_is_inclusive_in_source_time_and_utc():
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
    rule = Rule("FREQ=HOURLY;UNTIL=20261101T063000Z", start)
    assert [value.hour for value in rule.between(start, start + timedelta(hours=5))] == [0, 1]
    start = datetime(2026, 9, 1)
    assert Rule("FREQ=DAILY;UNTIL=20260903", start).between(start, datetime(2026, 9, 10)) == [
        start, start + timedelta(days=1), start + timedelta(days=2)]
