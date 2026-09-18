"""Offline lifecycle regressions: fake processes/clocks, never an SDK executable."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('session', Path(__file__).resolve().parents[1] / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class Clock:
    now = 0.0
    def time(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Process:
    def __init__(self, clock, exit=None, stubborn=False):
        self.pid = 7654321
        self.returncode = exit
        self.clock = clock
        self.waits = []
        self.stubborn = stubborn
        self.signals = []
        self.reaped = False

    def poll(self):
        if self.returncode is not None:
            self.reaped = True
        return self.returncode

    def wait(self, timeout=None):
        assert timeout is not None and timeout > 0, 'Unbounded wait regression'
        self.waits.append(timeout)
        if self.returncode is None:
            self.clock.sleep(timeout)
            raise subprocess.TimeoutExpired('fake', timeout)
        self.reaped = True
        return self.returncode

    def send(self, expected, sig):
        assert expected == {'pid': self.pid, 'start': 'owned'}
        self.signals.append(sig)
        if not self.stubborn or sig == signal.SIGKILL:
            self.returncode = -sig
        return True


class LifecycleTest(unittest.TestCase):
    def test_api_default_and_explicit_supported_images(self):
        self.assertEqual(session.parser().parse_args(['prepare']).api,34)
        self.assertEqual(session.parser().parse_args(['run','--api','35']).api,35)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            session.parser().parse_args(['run','--api','36'])

    def test_wrong_prepared_api_rejected_before_spawning_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state.json'
            state.write_text(json.dumps({'requestedApi':34}))
            opts=session.parser().parse_args(['run','--api','35','--state',str(state)])
            with patch.object(session,'idle'), patch.object(session.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError,'Prepared image API differs'):
                    session.run_session(session.Owner(),opts)
                spawn.assert_not_called()

    def setUp(self):
        self.clock = Clock()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(session.time, 'monotonic', self.clock.time))
        self.stack.enter_context(patch.object(session.time, 'sleep', self.clock.sleep))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def owner_child(self, **kwargs):
        owner = session.Owner()
        child = Process(self.clock, **kwargs)
        with patch.object(session.subprocess, 'Popen', return_value=child), patch.object(session, 'identity', return_value={'pid': child.pid, 'start': 'owned'}):
            owner.spawn(['fake-only'], 'emulator')
        return owner, child

    def test_default_deadline_and_progress(self):
        owner, child = self.owner_child()
        with self.assertRaises(session.Deadline):
            owner.wait(child, 999999)
        self.assertEqual(self.clock.now, 1200)
        times = [event['elapsed'] for event in owner.state['events']]
        self.assertTrue(all(b-a <= 60 for a, b in zip(times, times[1:])))
        self.assertIn('elapsed=30.0s', self.output.getvalue())
        with patch.object(session, 'exact_signal', side_effect=child.send):
            owner.close()
        self.assertTrue(child.reaped)

    def test_natural_failure_records_actual_exit(self):
        owner, child = self.owner_child(exit=17)
        self.assertEqual(owner.wait(child, 10), 17)
        with patch.object(session, 'exact_signal') as send:
            owner.close()
            send.assert_not_called()
        self.assertEqual(owner.state['children'][0]['exit'], 17)
        self.assertTrue(child.reaped)

    def test_term_then_kill_has_two_finite_waits(self):
        owner, child = self.owner_child(stubborn=True)
        with patch.object(session, 'exact_signal', side_effect=child.send):
            owner.close()
        self.assertEqual(child.signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertTrue(child.reaped)
        self.assertEqual(owner.state['children'][0]['exit'], -signal.SIGKILL)
        self.assertLessEqual(self.clock.now, 10)

    def test_zombie_is_waited_not_signalled(self):
        owner, child = self.owner_child(exit=0)
        with patch.object(session, 'exact_signal') as send:
            owner.close()
            send.assert_not_called()
        self.assertTrue(child.reaped)

    def test_sigterm_and_sigint_restore_handlers_and_reap(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            owner, child = self.owner_child()
            original = signal.getsignal(sig)
            with owner.signals(), patch.object(session, 'exact_signal', side_effect=child.send):
                signal.getsignal(sig)(sig, None)
                with self.assertRaises(session.Stopped):
                    owner.wait(child, 100)
                owner.close()
            self.assertEqual(signal.getsignal(sig), original)
            self.assertTrue(child.reaped)

    def test_signal_during_spawn_still_registers_child(self):
        owner = session.Owner()
        child = Process(self.clock)
        def spawning(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return child
        with owner.signals(), patch.object(session.subprocess, 'Popen', side_effect=spawning), patch.object(session, 'identity', return_value={'pid': child.pid, 'start': 'owned'}):
            owner.spawn(['fake'], 'child')
            with patch.object(session, 'exact_signal', side_effect=child.send):
                owner.close()
        self.assertTrue(child.reaped)

    def test_boot_timeout_is_three_minutes(self):
        self.assertEqual(session.parser().parse_args(['run']).boot_timeout, 180)
        owner, child = self.owner_child()
        with self.assertRaises(session.Deadline):
            owner.wait(child, session.BOOT)
        self.assertEqual(self.clock.now, 180)

    def test_two_cpu_limit_prefers_physical_cores_within_allowed_set(self):
        def topology(path, *args, **kwargs):
            return '0' if path.name == 'physical_package_id' else str(int(path.parent.parent.name[3:]) // 2)
        for allowed, expected in [({0,1,2,3}, [0,2]), ({1,3}, [1,3]), ({0,1}, [0,1]), ({3}, [3])]:
            with patch.object(session.os, 'sched_getaffinity', return_value=allowed), \
                    patch.object(session.os, 'sched_setaffinity') as pin, \
                    patch.object(session.Path, 'read_text', autospec=True, side_effect=topology):
                self.assertEqual(session.pin_two_cpus(), expected)
                pin.assert_called_once_with(0, expected)

    def test_each_instrument_test_is_bounded_and_single_selected(self):
        owner = session.Owner()
        results = ['INSTRUMENTATION_RESULT: stream='+json.dumps(dict(stage=name, passed=True))+'\nINSTRUMENTATION_CODE: -1' for name in ('basics', 'saf')]
        with patch.object(session, 'adb', side_effect=results) as adb:
            for name in ('basics', 'saf'):
                session.run_test(owner, {}, name, 12)
            self.assertEqual([call.args[-1] for call in adb.call_args_list], [12, 12])
            for name in ('unknown', 'basics,saf', '*'):
                with self.assertRaises(ValueError):
                    session.run_test(owner, {}, name, 12)

    def test_instrument_exit_zero_without_success_is_failure(self):
        with patch.object(session, 'adb', return_value='INSTRUMENTATION_FAILED'):
            with self.assertRaises(RuntimeError):
                session.run_test(session.Owner(), {}, 'basics', 12)

    def test_pid_reuse_fence_uses_pidfd(self):
        with patch.object(session.os, 'pidfd_open', return_value=88), patch.object(session.os, 'close') as close, patch.object(session, 'identity', return_value={'pid': 42, 'start': 'different'}), patch.object(session.signal, 'pidfd_send_signal') as send:
            self.assertFalse(session.exact_signal({'pid': 42, 'start': 'old'}, signal.SIGKILL))
            send.assert_not_called()
            close.assert_called_once_with(88)

    def test_server_not_created_by_owner_cannot_be_used(self):
        with patch.object(session, 'owns_adb_socket', return_value=False), patch.object(session.Owner, 'command') as command:
            with self.assertRaises(RuntimeError):
                session.adb(session.Owner(), {'adbPort': 5039}, ['get-state'])
            command.assert_not_called()

    def test_adb_server_management_and_transport_override_rejected(self):
        with patch.object(session, 'owns_adb_socket', return_value=True), patch.object(session.Owner, 'command') as command:
            for args in (['kill-server'], ['start-server'], ['-P', '5037', 'shell']):
                with self.assertRaises(RuntimeError):
                    session.adb(session.Owner(), {'adbPort': 5039}, args)
            command.assert_not_called()

    def test_main_permission_required_before_any_process_or_lock(self):
        with patch.object(session.subprocess, 'Popen') as process, patch.object(session, 'locks') as locks:
            with self.assertRaises(SystemExit):
                session.main(['run'])
            process.assert_not_called()
            locks.assert_not_called()

    def test_bad_deadline_values_rejected(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.assertRaises(Exception):
                session.positive(value)
        for args in (['run', '--progress', '61'], ['run', '--runtime', '1201'], ['run', '--boot-timeout', '181'],
                     ['run', '--main-slot-granted', '--test-timeout', '121']):
            with self.assertRaises(SystemExit):
                session.main(args)

    def test_native_proof_must_match_installed_candidate(self):
        output = 'INSTRUMENTATION_RESULT: stream='+json.dumps(dict(stage='basics', passed=True,
            sourceHash='old'))+'\nINSTRUMENTATION_CODE: -1'
        with patch.object(session, 'adb', return_value=output):
            with self.assertRaisesRegex(RuntimeError, 'different source snapshot'):
                session.run_test(session.Owner(), {'expectedSourceHash': 'new'}, 'basics', 120)

    def test_next_suite_requires_main_before_process_or_lock(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        with patch.object(native.session.subprocess, 'Popen') as process, patch.object(native.session, 'locks') as locks:
            with self.assertRaises(SystemExit):
                native.main(['--suite', 'ui'])
            process.assert_not_called()
            locks.assert_not_called()

    def test_next_suite_rejects_stale_source_and_tampered_apks(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp, patch.object(native, 'ROOT', Path(temp)):
            artifacts = Path(temp) / 'artifacts'
            artifacts.mkdir()
            for name in ('app.apk', 'test.apk'):
                (artifacts / name).write_bytes(b'private fake APK')
            digest = native.hashlib.sha256(b'private fake APK').hexdigest()
            candidate = dict(stale=False, signing='debug only', sourceHash='current',
                applicationId='io.gitlab.maik3531.magnolieorganizer.tablet.beta',
                instrumentationTestOnly=True, apkAssetsVerified=True,
                name='app.apk', testApk='test.apk', sha256=digest, testApkSha256=digest)
            self.assertEqual(len(native.candidate_files(candidate, {'sourceHash': 'current'})), 2)
            for change in ({'stale': True}, {'sourceHash': 'old'}, {'name': '../app.apk'}):
                with self.assertRaises(RuntimeError):
                    native.candidate_files(dict(candidate, **change), {'sourceHash': 'current'})
            (artifacts / 'test.apk').write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                native.candidate_files(candidate, {'sourceHash': 'current'})

    def test_failure_stops_other_owned_children(self):
        owner, first = self.owner_child()
        second = Process(self.clock, exit=3)
        second.pid += 1
        owner.children.append((second, dict(identity={'pid': second.pid}, pid=second.pid, exit=None)))
        with patch.object(session, 'exact_signal', side_effect=first.send):
            owner.close()
        self.assertTrue(first.reaped and second.reaped)

    def test_lock_conflict_never_starts_process_and_releases_partial_locks(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp:
            a, b = Path(temp) / 'a.lock', Path(temp) / 'b.lock'
            with session.locks([b]), patch.object(session.subprocess, 'Popen') as process:
                with self.assertRaises(RuntimeError):
                    with session.locks([a, b]):
                        process(['never'])
                process.assert_not_called()
                with session.locks([a]):
                    pass
            inode = b.stat().st_ino
            with session.locks([a, b]):
                pass
            self.assertEqual(b.stat().st_ino, inode)

    def test_both_existing_vm_locks_and_heavy_lock_are_required(self):
        opts = session.parser().parse_args(['run', '--vm-root', '/root-vm', '--session-root', '/session-vm'])
        self.assertEqual(set(session.lock_paths(opts)), {Path('/root-vm/sole-vm.lock'), Path('/session-vm/sole-vm.lock'),
            Path('/tmp/opencode/android-build.lock'), Path('/tmp/opencode/native-layout.lock'),
            Path('/tmp/opencode/magnolie-global-heavy.lock')})

    def test_raw_qemu_and_gradle_rejected(self):
        for line in ('12 qemu-system-x86 /usr/bin/qemu-system-x86_64 -m 2048', '15 java java GradleDaemon'):
            owner = session.Owner()
            with patch.object(owner, 'command', side_effect=['', '', line]):
                with self.assertRaises(RuntimeError):
                    session.idle(owner)

    def test_legacy_stale_state_cannot_stop_anything(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp:
            path = Path(temp) / 'state.json'
            path.write_text(json.dumps(dict(ownerPid=1160425, emulatorPid=1160584)))
            with patch.object(session, 'exact_signal') as send:
                with self.assertRaises(RuntimeError):
                    session.live_state(path)
                send.assert_not_called()

    def test_failed_state_write_cannot_skip_wait_and_reap(self):
        owner, child = self.owner_child(stubborn=True)
        owner.state_path = Path('/nonexistent/session.json')
        with patch.object(session.tempfile, 'NamedTemporaryFile', side_effect=OSError('disk full')), patch.object(session, 'exact_signal', side_effect=child.send), contextlib.redirect_stderr(io.StringIO()):
            owner.close()
        self.assertTrue(child.reaped)
        self.assertEqual(owner.state['children'][0]['exit'], -signal.SIGKILL)

    def test_main_timeout_reaps_emulator_and_server_before_releasing_locks(self):
        events=[]
        processes=[]
        def spawn(*args, **kwargs):
            child=Process(self.clock, stubborn=True)
            child.pid += len(processes)
            processes.append(child)
            return child
        def send(expected,sig):
            child=next(p for p in processes if p.pid==expected['pid'])
            return child.send(expected,sig)
        def run(owner,opts):
            owner.spawn(['fake-adb'], 'adb5039')
            child=owner.spawn(['fake-emulator'], 'emulator')
            return owner.wait(child,99999)
        @contextlib.contextmanager
        def locks(_):
            events.append('locked')
            yield
            self.assertTrue(all(p.reaped for p in processes))
            events.append('released-after-reap')
        with patch.object(session,'locks',locks), patch.object(session,'run_session',run), patch.object(session.subprocess,'Popen',spawn), patch.object(session,'identity',side_effect=lambda pid:dict(pid=pid,start='owned')), patch.object(session,'exact_signal',send):
            self.assertEqual(session.main(['run','--main-slot-granted','--runtime','1']),124)
        self.assertEqual(events,['locked','released-after-reap'])
        self.assertEqual(len(processes),2)

    def test_missing_coordination_root_fails_without_starting_child(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temp, patch.object(session.subprocess,'Popen') as process:
            with self.assertRaises(FileNotFoundError):
                with session.locks([Path(temp)/'missing-root/sole-vm.lock']):
                    process(['never'])
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
