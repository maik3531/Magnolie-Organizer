#!/usr/bin/env python3
"""Actual Swift unlimited VTIMEZONE -> canonical Python CalendarZone -> zic oracle.
No OS zone resolver participates on the emitted-calendar side of this comparison.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import hashlib
import types
import time
from collections import OrderedDict
from pathlib import Path
import subprocess
import sys
from check_timezone_provider import BETA, DATA, run_owned


def rule_cache_key(rule, lower, upper):
    def freeze(value):
        if value is None or type(value) in (str, bool, int):
            return (type(value).__name__, value)
        if type(value) is datetime and value.tzinfo is None:
            return ('datetime', value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond, value.fold)
        if type(value) in (list, tuple):
            return (type(value).__name__, tuple(freeze(item) for item in value))
        if type(value) is dict and all(type(key) is str for key in value):
            return ('dict', tuple((key, freeze(item)) for key, item in sorted(value.items())))
        raise TypeError('Unrecognized mutable/opaque rule state; bypass cache')
    try:
        # Include every instance field, including all mutable derived selectors.
        # Only our installed method wrapper is excluded; the pinned original
        # method does not inspect that wrapper as recurrence input.
        return (freeze({key: value for key, value in vars(rule).items() if key != 'between'}), freeze(lower), freeze(upper))
    except TypeError:
        return None


def serve(worker):
    # The Actions reference step precedes the later freeze step. Load the exact
    # published, hash-pinned pure module rather than whichever worktree is present.
    source = run_owned(['git', 'show', '067c38934b539943d8e1720abafd8a80b401d797:magnolie-organizer/bin/magnolie_recurrence.py'],
                       cwd=BETA.parent, timeout=20, capture=True)
    if hashlib.sha256(source.encode()).hexdigest() != '86269e77f87d0bc671733151053378077acc7eda417adce47f1395e7357ed6fe':
        raise RuntimeError('Published recurrence oracle hash mismatch')
    recurrence = types.ModuleType('published_magnolie_recurrence')
    recurrence.__file__ = 'published-v2.0.30/magnolie_recurrence.py'
    sys.modules[recurrence.__name__] = recurrence
    exec(compile(source, recurrence.__file__, 'exec'), recurrence.__dict__)
    process = subprocess.Popen([str(worker), str(DATA / 'tzdb-2026egtz.json'), str(DATA / 'provenance.json'), '--definitions'],
                               stdout=subprocess.PIPE, text=True)
    zones, expansions = {}, OrderedDict()
    started = time.monotonic()
    counters = {'ruleCacheHits': 0, 'ruleEvaluations': 0}
    def memoize(rule):
        original = rule.between
        def between(lower, upper, *, seek=None):
            # Exact complete instance state and bounds identify a result.
            # Every definition/Rule is still parsed by the original published
            # implementation; only immutable completed results share.
            if seek is not None or rule.start.tzinfo is not None:
                return original(lower, upper, seek=seek)
            key = rule_cache_key(rule, lower, upper)
            if key is None:
                return original(lower, upper)
            if key in expansions:
                counters['ruleCacheHits'] += 1
                expansions.move_to_end(key)
                return list(expansions[key])
            counters['ruleEvaluations'] += 1
            result = original(lower, upper)
            # Short/empty early-year bounds are cheap and must not evict the
            # expensive far-future expansions shared by equivalent rules.
            if 1000 <= len(result) <= 20_000:
                expansions[key] = tuple(result)
                while len(expansions) > 128:
                    expansions.popitem(last=False)
            return result
        rule.between = between
    try:
        for line in process.stdout:
            if len(line.encode()) > 8 * 1024 * 1024 or len(zones) >= 597:
                raise ValueError('Swift definition output exceeded bounds')
            item = json.loads(line)
            if item['identifier'] in zones:
                raise ValueError('Duplicate Swift definition')
            lines = item['lines']
            zone = recurrence.CalendarZone(lines)
            if zone.key != item['identifier']:
                raise ValueError('Published parser changed the original emitted TZID')
            for _, _, _, rules, _ in zone.observances:
                for rule in rules:
                    memoize(rule)
            zones[item['identifier']] = zone
        if process.wait(timeout=20) != 0 or len(zones) != 597:
            raise ValueError('Swift definition registry incomplete')
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=2)
        process.stdout.close()
    print(json.dumps({'phase': 'emitted-definition-parse', 'namedDefinitions': len(zones), 'seconds': time.monotonic() - started}), file=sys.stderr, flush=True)
    epoch, utc = datetime(1970, 1, 1), timezone.utc
    def stamp(date):
        return (date - epoch) // timedelta(milliseconds=1)
    for line in sys.stdin:
        rows = json.loads(line); failures = []
        for row in rows:
            try:
                kind, identifier = row[:2]
                zone = zones[identifier]
                if kind == 'o':
                    instant = epoch + timedelta(milliseconds=row[2])
                    wall = zone.fromutc(instant.replace(tzinfo=zone))
                    offset = zone._offset_at(instant)
                    assert int(offset.total_seconds()) == row[3], 'Emitted offset differs from zic'
                    assert [wall.year, wall.month, wall.day, wall.hour, wall.minute, wall.second, wall.microsecond // 1000] == row[4], 'Emitted wall differs from zic'
                elif kind == 'w':
                    wall = datetime(*row[2][:6], microsecond=row[2][6] * 1000)
                    valid = sorted({stamp(wall - offset) for offset in zone.offsets if zone._offset_at(wall - offset) == offset})
                    assert valid == row[3], 'Emitted fold/gap differs from zic'
                    if not valid:
                        assert stamp(wall - zone.utcoffset(wall.replace(tzinfo=zone, fold=0))) == row[4], 'Emitted gap-forward differs from zic'
                else:
                    raise ValueError('Unknown oracle operation')
            except Exception as error:
                failures.append({'identifier': row[1], 'sample': row, 'error': str(error)})
        print(json.dumps({'checked': len(rows), 'failures': failures}, separators=(',', ':')), flush=True)
    print(json.dumps({'phase': 'emitted-definition-complete', **counters, 'retainedExpansions': len(expansions), 'seconds': time.monotonic() - started}), file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    if args.serve:
        serve(args.worker)
        return
    if args.archive is None:
        parser.error('--archive is required')
    command = [sys.executable, str(Path(__file__).resolve()), '--serve', '--worker', str(args.worker.resolve())]
    run_owned([sys.executable, str(DATA / 'check-independent.py'), str(args.archive), '--worker-command', json.dumps(command),
               '--engine-label', 'actual Swift unlimited VTIMEZONE via published Python CalendarZone',
               '--worker-input', str(args.worker), '--worker-input', str(Path(__file__).resolve())], timeout=300)

if __name__ == '__main__':
    main()
