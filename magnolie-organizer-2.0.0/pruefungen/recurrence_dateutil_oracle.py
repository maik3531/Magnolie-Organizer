"""Explicit developer oracle; see requirements-recurrence-oracle.txt.

Not auto-collected by pytest or package builds. --golden-digests prints test-only
reference digests; it never rewrites fixtures or derives expectations from Rule.
"""

import itertools
import json
import random
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

try:
    import dateutil
    from dateutil import rrule
except ImportError as error:
    raise ImportError("Explicit oracle requires pruefungen/requirements-recurrence-oracle.txt; no check was skipped") from error
sys.path.insert(0, str(Path(__file__).parents[1] / "bin"))
from magnolie_recurrence import Rule

MATRIX = json.loads((Path(__file__).parent / "fixtures" / "recurrence-rfc-oracle.json").read_text())
CASES = list(itertools.product(MATRIX["anchors"], MATRIX["rules"], MATRIX["endings"]))


def weekyear_oracle(text, start, upper):
    """dateutil date/time selectors, grouped into the Windows week-year periods."""
    fields = dict(part.split("=") for part in text.split(";"))
    weekday = ("MO", "TU", "WE", "TH", "FR", "SA", "SU").index(fields.get("WKST", "MO"))
    daily = {name: value for name, value in fields.items()
             if name not in ("FREQ", "INTERVAL", "COUNT", "UNTIL", "BYWEEKNO", "BYSETPOS")}
    for name, value in (("BYHOUR", start.hour), ("BYMINUTE", start.minute), ("BYSECOND", start.second)):
        daily.setdefault(name, str(value))
    daily_text = "FREQ=DAILY;" + ";".join(name + "=" + value for name, value in daily.items())
    expected = []
    for year in range(start.year, upper.year + 2, int(fields.get("INTERVAL", "1"))):
        fourth, next_fourth = datetime(year, 1, 4), datetime(year + 1, 1, 4)
        first_week = fourth - timedelta(days=(fourth.weekday() - weekday) % 7)
        next_year = next_fourth - timedelta(days=(next_fourth.weekday() - weekday) % 7)
        weeks = (next_year - first_week).days // 7
        candidates = set()
        for number in map(int, fields["BYWEEKNO"].split(",")):
            number = number if number > 0 else weeks + number + 1
            if not 1 <= number <= weeks:
                continue
            week = first_week + timedelta(weeks=number - 1)
            candidates.update(rrule.rrulestr(daily_text, dtstart=week).between(
                week, week + timedelta(days=7, microseconds=-1), inc=True))
        candidates = sorted(candidates)
        if "BYSETPOS" in fields:
            candidates = sorted({candidates[position - 1 if position > 0 else position]
                                 for position in map(int, fields["BYSETPOS"].split(",")) if abs(position) <= len(candidates)})
        expected.extend(value for value in candidates if value >= start)
    if "COUNT" in fields:
        expected = expected[:int(fields["COUNT"])]
    return [value for value in expected if value <= upper]


@pytest.mark.parametrize("anchor,text,ending", CASES)
def test_windows_448_case_oracle_matrix(anchor, text, ending):
    start, lower, upper = map(datetime.fromisoformat, (anchor, MATRIX["lower"], MATRIX["upper"]))
    expected = rrule.rrulestr(text + ending, dtstart=start).between(lower, upper, inc=True)
    assert Rule(text + ending, start).between(lower, upper) == expected


@pytest.mark.parametrize("frequency", ["SECONDLY", "MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY", "YEARLY"])
def test_seeded_selector_combinations_and_partition_queries(frequency):
    rng = random.Random(20260907)
    for _ in range(20):
        start = datetime(2024, 2, rng.randrange(1, 29), rng.randrange(24), rng.randrange(60), rng.randrange(60))
        if frequency == "WEEKLY":
            # Windows applies BYSETPOS to a full WKST period. dateutil clips the
            # first week's date set at DTSTART instead. Align this oracle's
            # first week; the unaligned Windows convention has a golden test.
            start -= timedelta(days=start.weekday())
        selectors = {"FREQ": frequency, "INTERVAL": str(rng.choice((1, 2, 3, 7)))}
        for name, values in (("BYHOUR", ["0,9,17,23", "9,10"]), ("BYMINUTE", ["0,15,30,45", "1,2,3"]),
                             ("BYSECOND", ["0,20,40", "10,30"]), ("BYDAY", ["MO,WE,FR", "SA,SU"])):
            if rng.randrange(2):
                selectors[name] = rng.choice(values)
        if frequency == "YEARLY":
            selectors.update(rng.choice(({"BYMONTH": "2,9", "BYMONTHDAY": "1,-1"},
                                         {"BYYEARDAY": "1,60,-1"}, {"BYWEEKNO": "1,20,-1"}, {})))
        elif frequency == "MONTHLY" and rng.randrange(2):
            selectors["BYDAY"] = rng.choice(("1MO,-1FR", "5TH", "-2TU"))
        if any(name.startswith("BY") for name in selectors) and rng.randrange(2):
            selectors["BYSETPOS"] = rng.choice(("1", "-1", "1,-1", "2,-2"))
        selectors["COUNT"] = str(rng.choice((3, 10, 40)))
        text = ";".join(name + "=" + value for name, value in selectors.items())
        span = {"SECONDLY": 2, "MINUTELY": 3, "HOURLY": 7, "DAILY": 60,
                "WEEKLY": 180, "MONTHLY": 800, "YEARLY": 1800}[frequency]
        upper = start + timedelta(days=span)
        # dateutil ignores UNTIL when BYSETPOS can never select a candidate.
        # Prove those empty subdaily sets by cardinality, rather than hanging
        # the reference generator or skipping the product assertion.
        maximum = (1 if frequency == "SECONDLY" else len(selectors.get("BYSECOND", "0").split(",")))
        if frequency == "HOURLY":
            maximum *= len(selectors.get("BYMINUTE", "0").split(","))
        empty = frequency in ("SECONDLY", "MINUTELY", "HOURLY") and "BYSETPOS" in selectors and all(
            abs(int(position)) > maximum for position in selectors["BYSETPOS"].split(","))
        oracle_text = text.rsplit(";COUNT=", 1)[0] + ";UNTIL=" + upper.strftime("%Y%m%dT%H%M%S")
        try:
            expected = ([] if empty else weekyear_oracle(text, start, upper) if "BYWEEKNO" in selectors else
                        list(itertools.islice(rrule.rrulestr(oracle_text, dtstart=start), int(selectors["COUNT"]))))
        except ValueError as error:
            assert str(error) == "Invalid rrule byxxx generates an empty set."
            expected = []
        actual = Rule(text, start).between(start, upper)
        assert actual == expected, text
        lower = start + timedelta(days=span // 2)
        assert Rule(text, start).between(lower, upper) == [value for value in expected if value >= lower], text


@pytest.mark.parametrize("wkst", ["MO", "SU", "FR"])
@pytest.mark.parametrize("weeknos", ["1", "-1", "1,-1", "20", "53"])
@pytest.mark.parametrize("interval", [1, 2, 3])
def test_week_number_year_boundary_oracle(wkst, weeknos, interval):
    start, upper = datetime(2021, 3, 1, 9), datetime(2035, 1, 10)
    text = f"FREQ=YEARLY;INTERVAL={interval};BYWEEKNO={weeknos};BYDAY=MO,SU;WKST={wkst};COUNT=80"
    # Windows groups YEARLY/BYWEEKNO by week-year, not dateutil's calendar-year
    # partition. Use dateutil's daily expansion inside each selected week.
    # This also avoids dateutil 2.9's spurious week-53 hit on 2022-01-02.
    expected = weekyear_oracle(text, start, upper)
    assert Rule(text, start).between(start, upper) == expected
    lower = datetime(2026, 12, 28)
    assert Rule(text, start).between(lower, upper) == [value for value in expected if value >= lower]


@pytest.mark.parametrize("zone,start,text,count", [
    ("Europe/Berlin", "2026-03-28T23:30:00", "FREQ=HOURLY", 8),
    ("Europe/Berlin", "2026-03-29T01:45:00", "FREQ=MINUTELY;INTERVAL=15", 20),
    ("Europe/Berlin", "2026-03-29T01:59:30", "FREQ=SECONDLY;INTERVAL=30", 8),
    ("Australia/Lord_Howe", "2026-10-04T01:59:30", "FREQ=SECONDLY;INTERVAL=30", 8),
    ("Pacific/Apia", "2011-12-29T23:30:00", "FREQ=HOURLY", 6),
])
def test_subdaily_count_oracle_filters_source_gaps_before_count(zone, start, text, count):
    wall = datetime.fromisoformat(start)
    zone = ZoneInfo(zone)
    first, upper = wall.replace(tzinfo=zone), (wall + timedelta(days=3)).replace(tzinfo=zone)
    source = rrule.rrulestr(text + ";UNTIL=" + upper.strftime("%Y%m%dT%H%M%S"), dtstart=wall)
    expected = []
    for value in source:
        aware = value.replace(tzinfo=zone)
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == value:
            expected.append(aware)
            if len(expected) == count:
                break
    complete = text + f";COUNT={count}"
    assert Rule(complete, first).between(first, upper) == expected
    for lower in reversed(expected):
        assert Rule(complete, first).between(lower, upper) == [value for value in expected if value >= lower]


if __name__ == "__main__":
    if sys.argv[1:] != ["--golden-digests"]:
        raise SystemExit("Use pytest on this file, or --golden-digests for reviewed fixture maintenance")
    if dateutil.__version__ != "2.9.0.post0":
        raise SystemExit("Golden maintenance requires the pinned python-dateutil 2.9.0.post0")
    lower, upper = map(datetime.fromisoformat, (MATRIX["lower"], MATRIX["upper"]))
    digests = []
    for text in MATRIX["rules"]:
        group = []
        for anchor, ending in itertools.product(MATRIX["anchors"], MATRIX["endings"]):
            values = rrule.rrulestr(text + ending, dtstart=datetime.fromisoformat(anchor)).between(lower, upper, inc=True)
            group.append([anchor, text + ending, MATRIX["lower"], MATRIX["upper"], [value.isoformat() for value in values]])
        digests.append(hashlib.sha256(json.dumps(group, separators=(",", ":")).encode("ascii")).hexdigest())
    print(json.dumps(digests, indent=2))
