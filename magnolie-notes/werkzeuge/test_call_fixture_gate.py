"""Only our Python child processes; no Android, profile, device, or network."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('call_fixture_gate', Path(__file__).with_name('call_fixture_gate.py'))
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


class WrapperSelectionTest(unittest.TestCase):
    def fixture(self, root):
        properties = root / 'gradle-wrapper.properties'
        properties.write_text('''distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-9.6.0-bin.zip
distributionSha256Sum=''' + 'a' * 64 + '''
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
''')
        cache = root / '.gradle/wrapper/dists/gradle-9.6.0-bin/42k10rwplmzkhuboz9kdazi7s'
        executable = cache / 'gradle-9.6.0/bin/gradle'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 0\n'); executable.chmod(0o700)
        (cache / 'gradle-9.6.0-bin.zip.ok').touch()
        return properties, cache, executable

    def test_exact_wrapper_cache_not_old_or_first_directory(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); properties, cache, executable = self.fixture(root)
            old = root / '.gradle/wrapper/dists/gradle-8.13-bin/5xuhj0ry160q40clulazy9h7d/gradle-8.13/bin'
            old.mkdir(parents=True); (old / 'gradle').write_text('old')
            (cache.parent / 'unrelated-cache-key').mkdir()
            self.assertEqual(executable, gate.cached_gradle(root, properties))

    def test_missing_configured_cache_never_falls_back(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); properties, cache, executable = self.fixture(root)
            executable.unlink()
            old = root / '.gradle/wrapper/dists/gradle-8.13-bin/5xuhj0ry160q40clulazy9h7d/gradle-8.13/bin'
            old.mkdir(parents=True); (old / 'gradle').write_text('old')
            with self.assertRaises(RuntimeError): gate.cached_gradle(root, properties)

    def test_incomplete_wrapper_install_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); properties, cache, _ = self.fixture(root)
            (cache / 'gradle-9.6.0-bin.zip.ok').unlink()
            with self.assertRaises(RuntimeError): gate.cached_gradle(root, properties)

    def test_ambiguous_distribution_roots_are_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); properties, cache, _ = self.fixture(root)
            (cache / 'gradle-8.13').mkdir()
            with self.assertRaises(RuntimeError): gate.cached_gradle(root, properties)

    def test_symlinked_executable_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); properties, _, executable = self.fixture(root)
            other = root / 'other-gradle'; other.write_text('old')
            executable.unlink(); executable.symlink_to(other)
            with self.assertRaises(RuntimeError): gate.cached_gradle(root, properties)

    def test_unbound_or_unsupported_wrapper_config_is_rejected(self):
        replacements = [
            ('distributionSha256Sum=' + 'a' * 64, 'distributionSha256Sum=invalid'),
            ('https\\://services.gradle.org', 'http\\://services.gradle.org'),
            ('distributionPath=wrapper/dists', 'distributionPath=../elsewhere'),
            ('zipStoreBase=GRADLE_USER_HOME', 'zipStoreBase=PROJECT'),
            ('distributionBase=GRADLE_USER_HOME', 'distributionBase=GRADLE_USER_HOME\ndistributionBase=PROJECT'),
        ]
        for before, after in replacements:
            with self.subTest(after=after), tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
                root = Path(directory); properties, _, _ = self.fixture(root)
                properties.write_text(properties.read_text().replace(before, after))
                with self.assertRaises(RuntimeError): gate.cached_gradle(root, properties)

    def test_selection_and_compiler_inputs_are_source_bound(self):
        paths = gate.source_hashes()
        for name in ('gradle/wrapper/gradle-wrapper.properties', 'gradle/wrapper/gradle-wrapper.jar',
                     'build.gradle.kts', 'gradle/libs.versions.toml', 'gradle/verification-metadata.xml',
                     'app/gradle.lockfile', 'settings-gradle.lockfile'):
            self.assertIn(name, paths)


class ReadonlyProjectTest(unittest.TestCase):
    def test_project_metadata_is_writable_but_canonical_files_stay_readonly(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root = Path(directory); source = root / 'canonical'; output = root / 'output'
            (source / 'app/src').mkdir(parents=True)
            for name in ('project-root', 'app-root'): (output / name).mkdir(parents=True)
            contents = {'settings.gradle.kts': 'canonical settings', 'app/build.gradle.kts': 'canonical app',
                        'app/src/fixture.kt': 'canonical Kotlin'}
            for name, text in contents.items(): (source / name).write_text(text)
            code = '''import os,sys
from pathlib import Path
source=Path(sys.argv[1])
assert os.access(source,os.W_OK) and os.access(source/'app',os.W_OK)
for name in ['settings.gradle.kts','app/build.gradle.kts','app/src/fixture.kt']:
    try: (source/name).write_text('forbidden')
    except OSError: pass
    else: raise AssertionError('Canonical input became writable: '+name)
(source/'generated-metadata').write_text('temporary')
(source/'app/generated-metadata').write_text('temporary')
'''
            command = ['bwrap', '--die-with-parent', '--unshare-net', '--ro-bind', '/', '/',
                       '--tmpfs', '/tmp', '--bind', str(root), str(root), *gate.project_mounts(output, source),
                       sys.executable, '-B', '-c', code, str(source)]
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
            self.assertEqual(0, completed.returncode, completed.stderr)
            for name, text in contents.items(): self.assertEqual(text, (source / name).read_text())
            self.assertFalse((source / 'generated-metadata').exists())
            self.assertFalse((source / 'app/generated-metadata').exists())
            self.assertEqual('temporary', (output / 'project-root/generated-metadata').read_text())
            self.assertEqual('temporary', (output / 'app-root/generated-metadata').read_text())

    def test_shared_test_contract_is_source_bound(self):
        self.assertIn('../contracts/contact-original-return-hash-v1-vectors.json', gate.source_hashes())


class SupervisorTest(unittest.TestCase):
    def test_selected_jdk_reaches_the_isolated_worker(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as temporary:
            def completed(command, **kwargs):
                self.assertIn('--setenv=JAVA_HOME=/fixture/jdk-21', command)
                (Path(temporary) / 'gate-result.json').write_text(json.dumps({'passed': True, 'clean_exit': True}))
                return gate.subprocess.CompletedProcess(command, 0)
            with patch.dict(os.environ, {'JAVA_HOME': '/fixture/jdk-21'}), \
                    patch.object(sys, 'argv', ['call_fixture_gate.py', '--output', temporary]), \
                    patch.object(gate.subprocess, 'run', side_effect=completed):
                self.assertEqual(0, gate.main())

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
