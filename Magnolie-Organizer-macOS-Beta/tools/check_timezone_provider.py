#!/usr/bin/env python3
"""Actual Swift vs proleptic Python civil math and independent zic/ZoneInfo.
No finite test vectors are runtime timezone data. No source/env fallback in Core.
"""
import argparse
import calendar
from datetime import datetime, timedelta
import hashlib
import json
import os
import selectors
import signal
import sys
from pathlib import Path
import subprocess
import tempfile
import time

BETA = Path(__file__).resolve().parents[1]
ROOT = BETA.parent
DATA = ROOT / 'port-adapters/timezones'

def cleanup_group(process):
    # Every caller starts a fresh session: this group contains only this owned
    # invocation and its compiler/oracle descendants, never unrelated processes.
    def send(sig):
        try:
            os.killpg(process.pid, sig)
            return True
        except ProcessLookupError:
            return False
    probe_denied, group_exit_observed = False, False
    if send(signal.SIGTERM):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            process.poll()  # Reap the direct child even if descendants remain.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                group_exit_observed = True
                break
            except PermissionError:
                # Darwin may deny a zero-signal liveness probe during group
                # teardown. Do not mistake that for exit; reach bounded KILL.
                probe_denied = True
            time.sleep(.02)
        else:
            send(signal.SIGKILL)
            # The direct child may already be reaped while its worker is still
            # handling the signal. Give the owned group a bounded exit window.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                process.poll()
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    group_exit_observed = True
                    break
                except PermissionError:
                    probe_denied = True
                time.sleep(.02)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        process.wait(timeout=2)
    if probe_denied and not group_exit_observed:
        print('Owned group cleanup: direct child reaped, but descendant-group exit remains unverified because Darwin denied liveness probes.', file=sys.stderr, flush=True)


def run_owned(command, *, timeout, cwd=None, capture=False):
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True,
                               stdout=subprocess.PIPE if capture else None, text=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, output=output)
        return output
    finally:
        original_failure = sys.exc_info()[0] is not None
        try:
            cleanup_group(process)
        except Exception as cleanup_error:
            if not original_failure:
                raise
            print('Owned process-group cleanup also failed: ' + str(cleanup_error), file=sys.stderr, flush=True)
        finally:
            if process.stdout:
                process.stdout.close()


def civil_reference(worker, payload, manifest):
    process = subprocess.Popen([str(worker), str(payload), str(manifest)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    batch, checked = [], 0
    epoch = datetime(1970, 1, 1)
    def flush():
        nonlocal checked
        if not batch:
            return
        process.stdin.write(json.dumps(batch, separators=(',', ':')) + '\n'); process.stdin.flush()
        if not selector.select(timeout=20):
            raise TimeoutError('Swift civil oracle batch exceeded20seconds')
        reply = json.loads(process.stdout.readline())
        assert reply.get('checked') == len(batch) and not reply.get('failures') and 'error' not in reply, reply
        checked += len(batch); batch.clear()
    def add(date):
        batch.append(['c', [date.year, date.month, date.day, date.hour, date.minute, date.second, date.microsecond // 1000],
                      (date - epoch) // timedelta(milliseconds=1), (date.weekday() + 1) % 7])
        if len(batch) == 1000:
            flush()
    try:
        for day in range(146097):
            add(datetime(1400, 1, 1) + timedelta(days=day, hours=12, minutes=34, seconds=56, milliseconds=789))
        for year in [1, 99, 100, 400, 1582, 1600, 1900, 2000, 2400, 9999]:
            for month in range(1, 13):
                for day in [1, calendar.monthrange(year, month)[1]]:
                    add(datetime(year, month, day, 23, 59, 59, 999000))
        flush(); process.stdin.close()
        assert process.wait(timeout=20) == 0
        print(json.dumps({'provider': 'actual Swift integer civil engine', 'reference': 'Python datetime/calendar proleptic Gregorian', 'checks': checked}), flush=True)
    finally:
        selector.close()
        cleanup_group(process)
        for stream in [process.stdin, process.stdout]:
            stream.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--swift', required=True)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--definitions', action='store_true', help='Also validate actual emitted unlimited VTIMEZONE with published Python and zic')
    parser.add_argument('--worker', type=Path, help='Use an already built exact Swift worker')
    args = parser.parse_args()
    payload, manifest = DATA / 'tzdb-2026egtz.json', DATA / 'provenance.json'
    snapshots = {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in [payload, manifest, args.archive]}
    with tempfile.TemporaryDirectory(prefix='mac-swift-timezone-') as scratch:
        if args.worker:
            worker = args.worker.resolve()
        else:
            run_owned([args.swift, 'build', '--product', 'TimezoneReferenceWorker', '--scratch-path', scratch, '--jobs', '2'], cwd=BETA, timeout=300)
            binary = run_owned([args.swift, 'build', '--show-bin-path', '--scratch-path', scratch], cwd=BETA, timeout=300, capture=True).strip()
            worker = Path(binary) / 'TimezoneReferenceWorker'
        civil_reference(worker, payload, manifest)
        run_owned(['python3', str(DATA / 'check-independent.py'), str(args.archive), '--worker-command',
                        json.dumps([str(worker), str(payload), str(manifest)]), '--engine-label', 'actual Swift normative schema2 provider',
                        '--worker-input', str(worker), '--worker-input', str(manifest)], timeout=300)
        if args.definitions:
            emitted = BETA / 'tools/check_timezone_definitions.py'
            command = ['python3', str(emitted), '--serve', '--worker', str(worker)]
            # One owned session covers checker -> Python server -> Swift emitter.
            run_owned(['python3', str(DATA / 'check-independent.py'), str(args.archive), '--worker-command', json.dumps(command),
                       '--engine-label', 'actual Swift unlimited VTIMEZONE via published v2.0.30 Python CalendarZone',
                       '--worker-input', str(worker), '--worker-input', str(emitted)], timeout=300)
    assert snapshots == {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in snapshots}, 'Reference assets changed during validation'

if __name__ == '__main__':
    main()
