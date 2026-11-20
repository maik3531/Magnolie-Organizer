#!/usr/bin/env python3
"""Run production Java route/lifetime rules with synthetic input, no SDK/network."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path('io/gitlab/maik3531/magnolienotes/netz')
SOURCE = ROOT / 'app/src/main/java' / PACKAGE
CASES = ROOT / 'app/src/test/java' / PACKAGE / 'LanRoutenCases.java'


class LanRoutes(unittest.TestCase):
    def compile_run(self, mutation=None):
        with tempfile.TemporaryDirectory(prefix='notes-691-routing-') as folder:
            work = Path(folder)
            files = []
            for name in ('LanRegel.java', 'LanTor.java', 'LanRoutenRegel.java', 'LanZielWache.java'):
                text = (SOURCE / name).read_text()
                if mutation == 'public-bypass' and name == 'LanRoutenRegel.java':
                    text = text.replace('return longest != 0 || direct || !internet;', 'return false;')
                if mutation == 'stale-transfer' and name == 'LanZielWache.java':
                    text = text.replace('gate.aktuell(token)', 'gate.erlaubt()')
                if mutation == 'ignore-route' and name == 'LanRegel.java':
                    text = text.replace('needsLan.test(address)', 'lokal(address)')
                path = work / name
                path.write_text(text)
                files.append(str(path))
            compiler = shutil.which('javac')
            command = [compiler, '--release', '17'] if compiler else [
                'java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17']
            subprocess.run([*command, '-d', str(work), *files, str(CASES)],
                           check=True, capture_output=True, text=True, timeout=30)
            return subprocess.run(['java', '-cp', str(work),
                'io.gitlab.maik3531.magnolienotes.netz.LanRoutenCases'],
                capture_output=True, text=True, timeout=30)

    def test_production_rules(self):
        if not shutil.which('javac'):
            print('Using installed jdk.compiler: source/bytecode 17; Java-17 API surface is not checked.', flush=True)
        result = self.compile_run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_rejects_public_route_bypass(self):
        self.assertNotEqual(self.compile_run('public-bypass').returncode, 0)

    def test_rejects_revoked_transfer_revival(self):
        self.assertNotEqual(self.compile_run('stale-transfer').returncode, 0)

    def test_rejects_ignoring_platform_route(self):
        self.assertNotEqual(self.compile_run('ignore-route').returncode, 0)

    def test_android_adapter_pins_the_watched_network(self):
        # Source contract only: actual Android routing/bindSocket needs a device.
        source = (SOURCE / 'LanFreigabe.kt').read_text()
        watcher = source.split('fun beobachtenZiel(', 1)[1].split('class ZielWache', 1)[0]
        self.assertIn('network?.bindSocket(socket)', watcher)
        self.assertIn('routenLan(adresse, network)', watcher)
        self.assertIn('?: false', watcher)
        self.assertNotIn('lokal(adresse)', watcher)
        self.assertEqual(watcher.count('verbindungsnetz()'), 1)
        route = source.split('private fun routenLan(', 1)[1].split('fun beobachtenZiel(', 1)[0]
        self.assertNotIn('activeNetwork', route)


if __name__ == '__main__':
    unittest.main()
