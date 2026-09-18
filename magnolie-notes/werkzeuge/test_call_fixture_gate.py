"""Only our Python child processes; no Android, profile, device, or network."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('call_fixture_gate', Path(__file__).with_name('call_fixture_gate.py'))
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


class SupervisorTest(unittest.TestCase):
    def run_child(self, source, wall=1):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='call-wrapper-test-') as temporary:
            return gate.monitor([sys.executable, '-c', source], temporary, Path(temporary), wall=wall, interval=0.2)

    def test_stdin_has_eof_and_success_requires_actual_exit(self):
        result = self.run_child('import sys; assert sys.stdin.read() == ""; print("BUILD SUCCESSFUL")')
        self.assertTrue(result['clean_exit'])
        self.assertEqual([], result['remaining_owned'])

    def test_success_log_cannot_mask_hanging_process(self):
        result = self.run_child('import time; print("BUILD SUCCESSFUL", flush=True); time.sleep(30)', wall=0.4)
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['clean_exit'])
        self.assertEqual([], result['remaining_owned'])

    def test_detached_orphan_is_killed_and_reaped_not_reported_as_pass(self):
        result = self.run_child('''import os, time, signal
pid = os.fork()
if pid == 0:
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
else:
    time.sleep(0.1)
''')
        self.assertTrue(result['forced_cleanup'])
        self.assertFalse(result['clean_exit'])
        self.assertEqual([], result['remaining_owned'])

    def test_nonzero_exit_is_preserved(self):
        result = self.run_child('raise SystemExit(7)')
        self.assertEqual(7, result['exit_code'])
        self.assertFalse(result['clean_exit'])

    def test_systemd_success_requires_fresh_passed_worker_record(self):
        for mode in ('missing', 'stale', 'failed', 'unclean', 'valid'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(dir='/tmp/opencode') as temporary:
                output = Path(temporary)
                record = output / 'gate-result.json'
                if mode == 'stale':
                    record.write_text(json.dumps({'passed': True, 'clean_exit': True}))
                    os.utime(record, (0, 0))
                def completed(*args, **kwargs):
                    if mode not in ('missing', 'stale'):
                        record.write_text(json.dumps({'passed': mode != 'failed', 'clean_exit': mode != 'unclean'}))
                    return gate.subprocess.CompletedProcess(args[0], 0)
                with patch.object(sys, 'argv', ['call_fixture_gate.py', '--output', temporary]), \
                        patch.object(gate.subprocess, 'run', side_effect=completed):
                    self.assertEqual(0 if mode == 'valid' else 1, gate.main())

    def test_outer_preserves_nonzero_systemd_exit(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temporary, \
                patch.object(sys, 'argv', ['call_fixture_gate.py', '--output', temporary]), \
                patch.object(gate.subprocess, 'run', return_value=gate.subprocess.CompletedProcess([], 17)):
            self.assertEqual(17, gate.main())


if __name__ == '__main__': unittest.main()
