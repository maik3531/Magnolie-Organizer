"""Offline lifecycle regressions: fake processes/clocks, never an SDK executable."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('session', Path(__file__).resolve().parents[1] / 'tools/emulator-session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class EmulatorBootDiagnosticTests(unittest.TestCase):
    def test_boot_failure_categories_are_fixed_and_do_not_emit_host_or_record_values(self):
        output = session.emulator_boot_failure_signature(
            'ERROR | Cannot launch multiple emulators with the same AVD /private/profile\n'
            'FATAL: private document title\nGPU backend failed /private/password\n'
            'Address already in use 5580\nCould not access KVM: Permission denied')
        self.assertEqual(output['categories'], ['address_in_use','backend_failure','emulator_fatal','kvm_permission_denied','same_avd_running'])
        self.assertTrue(output['recognized'])
        self.assertNotIn('private', json.dumps(output))
        self.assertEqual(session.emulator_boot_failure_signature('private document text'), {'categories':[], 'recognized':False})

    def test_kvm_signatures_distinguish_only_specific_errors(self):
        signatures = {
            'Could not access KVM: Permission denied': 'kvm_permission_denied',
            '/dev/kvm is not found': 'kvm_unavailable',
            'KVM: Device or resource busy': 'kvm_busy',
            'x86_64 emulation currently requires hardware acceleration': 'hardware_accel_required',
        }
        for message, category in signatures.items():
            self.assertEqual(session.emulator_boot_failure_signature(message)['categories'],[category])
        self.assertFalse(session.emulator_boot_failure_signature('KVM initialized; acceleration available')['recognized'])

    def test_kvm_facts_are_numeric_or_boolean_and_missing_is_explicit(self):
        with patch.object(session.os, 'stat', side_effect=FileNotFoundError):
            facts = session.kvm_access_facts()
        self.assertFalse(facts['exists']); self.assertFalse(facts['readable']); self.assertFalse(facts['writable'])
        device = os.stat_result((0o20660,0,0,0,12,34,0,0,0,0))
        with patch.object(session.os, 'stat', return_value=device), patch.object(session.os,'access',side_effect=[True,False]):
            facts = session.kvm_access_facts()
        self.assertTrue(facts['character']); self.assertEqual(facts['uid'],12); self.assertEqual(facts['gid'],34)
        self.assertEqual(facts['mode'],0o660); self.assertTrue(facts['readable']); self.assertFalse(facts['writable'])
        self.assertTrue(all(type(value) in (int,bool) for value in facts.values()))

    def test_preboot_exit_keeps_original_failure_and_reads_only_bounded_tail(self):
        with tempfile.NamedTemporaryFile(mode='w+') as log:
            log.write('PANIC: out-of-bound prefix\n'+'x'*70000+'\nAddress already in use\nprivate record')
            owner = unittest.mock.Mock()
            child = unittest.mock.Mock(pid=123, returncode=7)
            self.assertEqual(session.record_preboot_exit(owner,child,log),7)
            event = owner.record.call_args
            self.assertEqual(event.args, ('emulator-preboot-exit',))
            self.assertEqual(event.kwargs['actualExit'],7)
            self.assertEqual(event.kwargs['technical']['categories'],['address_in_use'])
            self.assertNotIn('private',json.dumps(event.kwargs))
            child.returncode=0
            self.assertEqual(session.record_preboot_exit(owner,child,log),1)


class PortAvailabilityTests(unittest.TestCase):
    def test_active_listener_rejected_even_with_address_reuse(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
            server.listen()
            with self.assertRaisesRegex(RuntimeError, f'port {port} unavailable: errno=98'):
                session.require_available_port(port)

    def test_closed_own_connection_time_wait_does_not_block_fresh_owner(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
            server.listen()
            with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
                accepted, _ = server.accept()
                accepted.close()  # Server side actively closes, retaining TIME_WAIT.
                self.assertEqual(client.recv(1), b'')
        with socket.socket() as original_probe:
            with self.assertRaises(OSError) as error:
                original_probe.bind(('127.0.0.1', port))
            self.assertEqual(error.exception.errno, 98)
        session.require_available_port(port)


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
    def test_sdk_override_reaches_build_and_emulator_paths(self):
        self.assertEqual(session.sdk_root({'ANDROID_HOME':'/workspace/android-sdk'}), Path('/workspace/android-sdk'))
        self.assertEqual(session.sdk_root({'ANDROID_SDK_ROOT':'/workspace/android-sdk'}), Path('/workspace/android-sdk'))
        with self.assertRaisesRegex(ValueError, 'same SDK'):
            session.sdk_root({'ANDROID_HOME':'/workspace/one','ANDROID_SDK_ROOT':'/workspace/two'})

    def test_online_mode_preserves_bounded_serial_gradle_options(self):
        spec = importlib.util.spec_from_file_location('offline_checks', session.ROOT / 'tools/offline-checks.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        default = gate.gradle_command([':app:testDebugUnitTest'], rerun=True)
        online = gate.gradle_command([':app:testDebugUnitTest'], online=True, rerun=True)
        self.assertIn('--offline', default)
        self.assertEqual([arg for arg in default if arg != '--offline'], online)
        self.assertIn('--no-daemon', online)
        self.assertIn('--max-workers=1', online)
        self.assertIn('--rerun-tasks', online)

    def test_api_default_and_explicit_supported_images(self):
        self.assertEqual(session.parser().parse_args(['prepare']).api,34)
        self.assertEqual(session.parser().parse_args(['run','--api','35']).api,35)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            session.parser().parse_args(['run','--api','36'])

    def test_image_selection_is_closed_and_package_is_fixed(self):
        self.assertEqual(session.parser().parse_args(['prepare']).image, 'google_apis')
        self.assertEqual(session.system_image(34, 'default'), 'system-images;android-34;default;x86_64')
        self.assertEqual(session.system_image(34, 'google_apis'), 'system-images;android-34;google_apis;x86_64')
        for invalid in ('../default', '/tmp/image', 'google_apis_playstore', 'default;x86'):
            with self.assertRaises(ValueError): session.system_image(34, invalid)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                session.parser().parse_args(['prepare', '--image', invalid])

    def test_wrong_prepared_image_rejected_before_spawning_sdk(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)/'state.json'
            state.write_text(json.dumps({'requestedApi':34, 'image':'google_apis'}))
            opts = session.parser().parse_args(['run', '--image', 'default', '--state', str(state)])
            with patch.object(session, 'idle'), patch.object(session.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(RuntimeError, 'Prepared image identifier differs'):
                    session.run_session(session.Owner(), opts)
                spawn.assert_not_called()

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
        with patch.object(session, 'adb', side_effect=results) as adb, patch.object(session, 'prepare_test_process'):
            for name in ('basics', 'saf'):
                session.run_test(owner, {}, name, 12)
            self.assertEqual([call.args[-1] for call in adb.call_args_list], [12, 12])
            for name in ('unknown', 'basics,saf', '*'):
                with self.assertRaises(ValueError):
                    session.run_test(owner, {}, name, 12)

    def test_cold_stage_stop_is_scoped_verified_and_preserves_data(self):
        package=session.BETA_PACKAGE
        before='PID NAME\n42 '+package+'\n43 '+package+':service\n88 io.gitlab.maik3531.magnolienotes\n'
        empty='PID NAME\n88 io.gitlab.maik3531.magnolienotes\n'
        clock=Clock()
        with patch.object(session.time,'monotonic',clock.time), patch.object(session.time,'sleep',clock.sleep), \
             patch.object(session,'adb',side_effect=[before,'',before,empty]) as adb:
            owner=session.Owner(runtime=20)
            session.prepare_test_process(owner,{},'restart')
        commands=[call.args[2] for call in adb.call_args_list]
        self.assertEqual(commands,[['shell','ps','-A','-o','PID,NAME'],
                                  ['shell','am','force-stop',package],
                                  ['shell','ps','-A','-o','PID,NAME'],['shell','ps','-A','-o','PID,NAME']])
        self.assertEqual(owner.state['events'][-1]['targetPidsAfter'],[])
        self.assertTrue(all(0 < call.args[3] <= 5 for call in adb.call_args_list))
        self.assertNotIn('pm',str(commands))
        self.assertNotIn('clear',str(commands))
        self.assertNotIn('rm',str(commands))

    def test_cold_stage_wait_is_bounded_by_owner_deadline(self):
        clock=Clock()
        def output(owner,state,args,timeout):
            return '' if args[1:3]==['am','force-stop'] else 'PID NAME\n42 '+session.BETA_PACKAGE+'\n'
        with patch.object(session.time,'monotonic',clock.time), patch.object(session.time,'sleep',clock.sleep), \
             patch.object(session,'adb',side_effect=output):
            owner=session.Owner(runtime=1)
            with self.assertRaises(session.Deadline): session.prepare_test_process(owner,{},'layout')
        self.assertLessEqual(clock.now,1.1)
        self.assertNotEqual(owner.state.get('phase'),'stage-process-stopped')

    def test_cold_stage_read_errors_are_not_absent_processes(self):
        for output in ('', 'Permission denied', 'PID NAME\ninvalid row', 'error: device offline'):
            with patch.object(session,'adb',return_value=output) as adb:
                with self.assertRaises(RuntimeError): session.prepare_test_process(session.Owner(),{},'layout')
                self.assertEqual(adb.call_count,1)
        with patch.object(session,'adb',side_effect=['PID NAME\n','Security exception']) as adb:
            with self.assertRaises(RuntimeError): session.prepare_test_process(session.Owner(),{},'layout')
            self.assertEqual(adb.call_count,2)
        with patch.object(session,'adb',side_effect=subprocess.CalledProcessError(1,['ps'])):
            with self.assertRaises(subprocess.CalledProcessError): session.prepare_test_process(session.Owner(),{},'layout')

    def test_cold_start_applies_only_to_ui_stages_not_alarm_or_reboot_stages(self):
        def proof(owner,state,args,timeout):
            stage=args[args.index('stage')+1]
            return 'INSTRUMENTATION_RESULT: stream='+json.dumps(dict(stage=stage,passed=True))+'\nINSTRUMENTATION_CODE: -1'
        with patch.object(session,'prepare_test_process') as prepare, patch.object(session,'adb',side_effect=proof):
            for stage in session.STAGES: session.run_test(session.Owner(),{},stage,12)
        self.assertEqual([call.args[2] for call in prepare.call_args_list],
                         ['basics','restart','layout','time','navigation','calendar-files'])

    def test_native_suites_execute_through_owner_stage_contract(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        def proof(owner, state, args, timeout):
            stage = args[args.index('stage')+1]
            return 'INSTRUMENTATION_RESULT: stream='+json.dumps(dict(stage=stage, passed=True, sourceHash='current'))+'\nINSTRUMENTATION_CODE: -1'
        with patch.object(session, 'prepare_test_process'), patch.object(session, 'adb', side_effect=proof):
            for stages in native.SUITES.values():
                for stage in stages:
                    owner = session.Owner()
                    session.run_test(owner, {'expectedSourceHash':'current'}, stage, 120)
                    self.assertEqual(owner.state['phase'], 'test-passed')

    def test_timeout_preserves_partial_tempfile_output_and_original_exception(self):
        for failure in (session.Deadline('original deadline'), session.Stopped('original stop')):
            owner=session.Owner(); child=object(); item={'identity': {'pid': 42}}
            def spawn(args,label,**kwargs):
                owner.children.append((child,item))
                kwargs['stdout'].write('INSTRUMENTATION_STATUS: stream=PHASE navigation-fixture-start\n')
                kwargs['stdout'].flush()
                return child
            with patch.object(owner,'spawn',side_effect=spawn), patch.object(owner,'wait',side_effect=failure), \
                 patch.object(owner,'stop_child') as cleanup:
                with self.assertRaises(type(failure)) as raised: owner.command(['synthetic'],timeout=1)
            self.assertIs(raised.exception,failure)
            self.assertIn('PHASE navigation-fixture-start',failure.output)
            cleanup.assert_called_once_with(child,item)

    def test_instrument_timeout_prints_bounded_partial_output_without_passing(self):
        failure=session.Deadline('original deadline')
        failure.output='x'*20000+'\nINSTRUMENTATION_STATUS: stream=PHASE trusted-tab-switch-1\n'
        owner=session.Owner(); captured=io.StringIO()
        with patch.object(session,'prepare_test_process'), patch.object(session,'adb',side_effect=failure), \
             contextlib.redirect_stdout(captured):
            with self.assertRaises(session.Deadline) as raised: session.run_test(owner,{},'layout',12)
        self.assertIs(raised.exception,failure)
        self.assertIn('trusted-tab-switch-1',captured.getvalue())
        self.assertLess(len(captured.getvalue()),16500)
        self.assertNotEqual(owner.state.get('phase'),'test-passed')

    def test_instrument_exit_zero_without_success_is_failure(self):
        with patch.object(session, 'adb', return_value='INSTRUMENTATION_FAILED'), patch.object(session, 'prepare_test_process'):
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
        with patch.object(session, 'adb', return_value=output), patch.object(session, 'prepare_test_process'):
            with self.assertRaisesRegex(RuntimeError, 'different source snapshot'):
                session.run_test(session.Owner(), {'expectedSourceHash': 'new'}, 'basics', 120)

    def test_startup_milestones_only_allow_fixed_numeric_telemetry(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        line = '11-08 12:00:00.000 111 222 D MagnolieStartup: event=VAULT_OPEN_END pid=111 generation=1 elapsedRealtimeMs=123 sinceCreateMs=12'
        output = native.startup_milestones(line+'\n'+line+' private record\n'+line.replace('VAULT_OPEN_END','PRIVATE_VALUE'))
        self.assertEqual(output, line.split('MagnolieStartup: ')[1])
        self.assertLessEqual(len(native.startup_milestones((line+'\n')*100)), 6000)
        self.assertLessEqual(len(native.startup_milestones((line+'\n')*100).splitlines()), 48)

    def test_native_failure_output_retains_technical_stack_and_is_bounded(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        log = ('11-08 12:00:00.000 111 222 E AndroidRuntime: FATAL EXCEPTION: main\n'
               '11-08 12:00:00.001 111 222 E AndroidRuntime: at package.Class.method(Class.kt:42)\n'
               '11-08 12:00:00.002 111 222 I TabletNativeTest: synthetic document text\n'
               '11-08 12:00:00.003 111 222 W ActivityManager: unrelated warning')
        output = native.technical_failure_log(log)
        self.assertIn('FATAL EXCEPTION', output)
        self.assertIn('Class.kt:42', output)
        self.assertNotIn('synthetic document text', output)
        self.assertNotIn('unrelated warning', output)
        progress = native.technical_failure_log('11-08 12:00:00.000 111 222 I TabletNativeTest: PHASE navigation-fixture-ready\n11-08 12:00:00.001 111 222 I TabletNativeTest: PHASE trusted-tab-switch-7')
        self.assertIn('navigation-fixture-ready',progress)
        self.assertIn('trusted-tab-switch-7',progress)
        self.assertLessEqual(len(native.technical_failure_log(log*500)), 16000)
        self.assertLessEqual(len(native.technical_failure_log(log*500).splitlines()), 160)
        exit_info = 'process=synthetic.package reason=4 (CRASH) status=0 importance=100 pss=123 rss=456 description=private text'
        signature = native.exit_info_signature(exit_info)
        self.assertIn('reason=4 (CRASH)', signature)
        self.assertIn('rss=456', signature)
        self.assertNotIn('process=', signature)
        self.assertNotIn('private text', signature)
        self.assertLessEqual(len(native.exit_info_signature(exit_info*500)), 3000)
        correlated = native.exit_info_signature('timestamp=2026-11-08 12:26:10.123 pid=5432 reason=12 (DEPENDENCY DIED) description=private')
        self.assertIn('timestamp=2026-11-08 12:26:10.123', correlated)
        self.assertIn('pid=5432', correlated)
        self.assertIn('reason=12 (DEPENDENCY DIED)', correlated)
        self.assertNotIn('private', correlated)

    def test_system_dependency_diagnostics_are_scoped_and_do_not_return_records(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        package=session.BETA_PACKAGE
        log=('11-08 12:00:00.000 100 200 I ActivityManager: Killing 3086:'+package+'/u0a12: depends on provider com.android.webview\n'
             '11-08 12:00:00.001 100 200 I ActivityManager: Killing 4000:unrelated.notes/u0a15: cached\n'
             '11-08 12:00:00.002 100 200 I ActivityManager: Killing 4001:'+package+'.test/u0a16: cached\n'
             '11-08 12:00:00.003 100 200 I ActivityManager: '+package+' private record text\n'
             '11-08 12:00:00.004 100 200 I WebViewUpdateService: Current WebView package changed: com.android.webview')
        summary=native.system_dependency_log(log)
        self.assertIn('Killing 3086:',summary)
        self.assertIn('WebView package changed',summary)
        self.assertNotIn('unrelated.notes',summary)
        self.assertNotIn(package+'.test',summary)
        self.assertNotIn('private record text',summary)
        self.assertLessEqual(len(native.system_dependency_log(log*500)),8000)
        state='Current WebView package (name, version): (com.android.webview, 113.0)\nNumber of relros started: 2\nNumber of relros finished: 1\nWebView package dirty: true\nprivate document title: unrelated'
        readiness=native.provider_readiness(state)
        self.assertIn('relros finished: 1',readiness)
        self.assertIn('package dirty: true',readiness)
        self.assertNotIn('private document',readiness)
        descriptions=('timestamp=2026-11-08 12:00:00.000 pid=3086 reason=12 (DEPENDENCY DIED)\n'
                      'description=depends on provider com.android.webview/.Provider in dying proc com.android.webview private words\n'
                      'timestamp=2026-11-08 11:59:00.000 reason=4 (CRASH)\ndescription=private record com.private.document')
        result=native.dependency_exit_descriptions(descriptions)
        self.assertIn('com.android.webview/.Provider',result)
        self.assertNotIn('private words',result)
        self.assertNotIn('com.private.document',result)
        self.assertLessEqual(len(native.dependency_exit_descriptions(descriptions*500)),2000)

    def test_gms_lifecycle_signature_excludes_all_free_text_and_unrelated_processes(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
        output=('ACTIVITY MANAGER PROCESS EXIT INFO\nApplicationExitInfo #0:\n'
                'timestamp=2026-11-08 14:10:17.800 pid=123 realUid=1000\n'
                'process=com.google.android.gms.persistent reason=1 (EXIT_SELF) status=0\n'
                'description=unrelated@example.test token=not-for-output\n'
                'ApplicationExitInfo #1:\ntimestamp=2026-11-08 14:00:00.000 pid=999\n'
                'process=com.google.android.gms.other reason=4 (CRASH) status=9\n')
        data=json.loads(native.gms_exit_signature(output))
        self.assertTrue(data['available'])
        self.assertEqual(data['records'],[dict(timestamp='2026-11-08 14:10:17.800',pid=123,reason=1,status=0)])
        self.assertNotIn('unrelated@example.test',native.gms_exit_signature(output))
        self.assertNotIn('not-for-output',native.gms_exit_signature(output))
        self.assertNotIn('realUid',native.gms_exit_signature(output))
        self.assertLessEqual(len(native.gms_exit_signature(output*500)),2000)
        self.assertFalse(json.loads(native.gms_exit_signature('Permission denied'))['available'])
        process=json.loads(native.gms_process_signature('PID NAME\n123 com.google.android.gms.persistent\n999 unrelated.app\n124 com.google.android.gms.persistent.extra'))
        self.assertEqual(process['pids'],[123])
        self.assertFalse(json.loads(native.gms_process_signature('error: offline'))['available'])

    def test_next_suite_requires_main_before_process_or_lock(self):
        spec = importlib.util.spec_from_file_location('native_checks', session.ROOT / 'tools/native-checks.py')
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        with patch.object(native.session.subprocess, 'Popen') as process, patch.object(native.session, 'locks') as locks:
            for suite in ('ui', 'services'):
                with self.assertRaises(SystemExit):
                    native.main(['--suite', suite])
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
