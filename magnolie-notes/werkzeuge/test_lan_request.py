#!/usr/bin/env python3
"""Run the actual LAN request state machine with synthetic lifecycle/OS state.

Uses the installed JVM/compiler only. This is neither an Android nor an ActivityResult
test, and it does not run the JUnit wrapper or install/download any tools.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path('java/io/gitlab/maik3531/magnolienotes')


class LanRequestTests(unittest.TestCase):
    def test_executable_request_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='notes-691-lan-request-') as out:
            # Some runtime images have the compiler module but omit the javac
            # executable and ct.sym. That route checks source/bytecode level 17,
            # not the full Java-17 API surface; it never installs a compiler.
            compiler = shutil.which('javac')
            if compiler:
                command = [compiler, '--release', '17']
            else:
                command = ['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17']
                print('Using installed jdk.compiler: source/bytecode 17; Java-17 API surface is not checked.', flush=True)
            subprocess.run([
                *command, '-d', out,
                str(ROOT / 'app/src/main' / PACKAGE / 'netz/LanAnfrage.java'),
                str(ROOT / 'app/src/test' / PACKAGE / 'netz/LanAnfrageCases.java'),
            ], check=True, timeout=30)
            subprocess.run([
                'java', '-cp', out,
                'io.gitlab.maik3531.magnolienotes.netz.LanAnfrageCases',
            ], check=True, timeout=30)

    def test_actual_activity_integration_boundaries(self):
        source = (ROOT / 'app/src/main' / PACKAGE / 'MainActivity.kt').read_text()
        host = source.split('private val lanAnfrage = LanAnfrage()', 1)[1].split('override fun onCreate', 1)[0]
        self.assertIn('"notes-lan-permission", this, ActivityResultContracts.RequestPermission()', host)
        self.assertIn('Lifecycle.State.RESUMED', host)
        self.assertIn('!isFinishing && !isDestroyed', host)
        self.assertIn('Looper.myLooper() == android.os.Looper.getMainLooper()', host)
        callback = host.split(') { _ ->', 1)[1].split('private fun lanSichtbar', 1)[0]
        self.assertIn('lanAnfrage.antwort(lanSichtbar()) { LanFreigabe.erlaubt() }', callback)
        for action in ('BaumDienst.starten', 'TelefonDienst.start', 'beginPairing', 'frageAn', 'launch('):
            self.assertNotIn(action, callback)
        self.assertIn('lanAnfrage.startFehlgeschlagen(entscheidung.ticket)', host)
        self.assertIn('override fun onStop() {\n        lanAnfrage.unterbrechen()', source)
        self.assertIn('override fun onDestroy() {\n        lanAnfrage.close()', source)
        self.assertNotIn('var lanDialogOffen', source)
        self.assertEqual(source.count('lanFreigabe.launch('), 1)
        self.assertNotIn('LAN_DIALOG', source)  # no saved action/grant flag


if __name__ == '__main__':
    unittest.main()
