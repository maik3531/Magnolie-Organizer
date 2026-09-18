import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("graphics", Path(__file__).parents[1] / "werkzeuge/appimage_graphics.py")
graphics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graphics)


class GraphicsTests(unittest.TestCase):
    def test_private_helpers_do_not_depend_on_usr_bin_sandbox_mount(self):
        sys.path.insert(0, str(Path(__file__).parents[1] / 'werkzeuge'))
        try:
            import appimage_runtime as runtime
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / 'usr/bin').mkdir(parents=True)
            (app / 'usr/lib/webkit2gtk-4.1').mkdir(parents=True)
            for name in ('bwrap', 'xdg-dbus-proxy'):
                (app / 'usr/bin' / name).write_bytes(name.encode())
                (app / 'usr/bin' / name).chmod(0o755)
            data = b'/proc/self/cwd//./usr/lib/webkit2gtk-4.1\0/usr/bin/bwrap\0/usr/bin/xdg-dbus-proxy\0'
            library = app / 'usr/lib/libwebkit2gtk-4.1.so.0'
            library.write_bytes(data)
            locations = []
            def started(command, env):
                private = Path(env['LD_LIBRARY_PATH'].split(':')[0])
                locations.append(private)
                self.assertFalse((private / 'p').is_symlink())
                self.assertFalse((private / 'b').is_symlink())
                self.assertEqual((private / 'p').read_bytes(), b'xdg-dbus-proxy')
                self.assertEqual(len((private / library.name).read_bytes()), len(data))
                self.assertIn(str(app / 'usr/share'), env['LD_LIBRARY_PATH'])
                self.assertEqual(env['WEBKIT_FORCE_SANDBOX'], '1')
                from unittest.mock import Mock
                return Mock(wait=lambda: 0)
            with patch.object(runtime, 'select', return_value=''), \
                    patch.object(runtime, 'sandbox_helper', side_effect=lambda env, bundled: bundled), \
                    patch.object(runtime.os, 'environ', {'LD_LIBRARY_PATH':str(app / 'usr/lib')}), \
                    patch.object(runtime.subprocess, 'Popen', side_effect=started):
                self.assertEqual(runtime.launch(app, ['probe.py']), 0)
            self.assertEqual(library.read_bytes(), data)
            self.assertTrue(locations)
            self.assertTrue(all(not path.exists() for path in locations))

    def test_apparmor_uses_verified_system_helper_or_fails_closed(self):
        sys.path.insert(0, str(Path(__file__).parents[1] / 'werkzeuge'))
        try:
            import appimage_runtime as runtime
        finally:
            sys.path.pop(0)
        bundled = Path('/tmp/123456/b')
        env = {'LD_LIBRARY_PATH': '/bundle/lib', 'LD_PRELOAD': '/host/graphics.so'}
        with patch.object(runtime.Path, 'exists', return_value=True), \
                patch.object(runtime.Path, 'read_text', return_value='1\n'), \
                patch.object(runtime.subprocess, 'run') as run:
            self.assertEqual(runtime.sandbox_helper(env, bundled), Path('/usr/bin/bwrap'))
            self.assertEqual(run.call_args.kwargs['env'], env)
            self.assertIn('--unshare-user', run.call_args.args[0])
            run.side_effect = subprocess.CalledProcessError(1, 'bwrap')
            with self.assertRaisesRegex(RuntimeError, 'AppArmor-approved'):
                runtime.sandbox_helper(env, bundled)
        with patch.object(runtime.Path, 'exists', return_value=False), \
                patch.object(runtime.subprocess, 'run') as run:
            self.assertEqual(runtime.sandbox_helper(env, bundled), bundled)
            run.assert_not_called()

    def test_runtime_relocation(self):
        sys.path.insert(0, str(Path(__file__).parents[1] / 'werkzeuge'))
        try:
            from appimage_runtime import launch, relocate
        finally:
            sys.path.pop(0)
        original = b'ELF/usr/bin/bwrap\0rest'
        result = relocate(original, '/usr/bin/bwrap', '/tmp/123456/b')
        self.assertEqual(len(result), len(original))
        self.assertIn(b'/tmp/123456/b\0', result)
        self.assertTrue(result.endswith(b'rest'))
        with self.assertRaises(RuntimeError):
            relocate(original, '/usr/bin/bwrap', '/far/too/long/runtime/bwrap')
        with self.assertRaises(RuntimeError):
            relocate(b'unknown', '/usr/bin/bwrap', '/tmp/123456/b')
        app = Path('/test.AppDir')
        for flag in ('--help', '--hilfe', '-h', '--version', '-V'):
            with patch('appimage_runtime.os.execv', side_effect=SystemExit(0)) as execute, \
                    patch('appimage_runtime.select') as select:
                with self.assertRaises(SystemExit):
                    launch(app, [str(app / 'usr/bin/magnolie-organizer'), flag])
                select.assert_not_called()
                self.assertEqual(execute.call_args.args[0], str(app / 'usr/bin/python3'))

    def test_loader_output(self):
        self.assertEqual(graphics.loader_paths("\tlibstdc++.so.6 => /lib64/libstdc++.so.6 (0x123)\n"),
                         {"libstdc++.so.6": "/lib64/libstdc++.so.6"})
        with self.assertRaises(RuntimeError):
            graphics.loader_paths("libLLVM.so => not found")

    def test_baseline_and_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            (app / "usr/lib").mkdir(parents=True)
            for name in ("libstdc++.so.6", "libgcc_s.so.1", "libxml2.so.2", "libgtk-3.so.0"):
                (app / "usr/lib" / name).touch()
            cache = "libEGL_mesa.so.0 (libc6,x86-64) => /host/libEGL_mesa.so.0\n"
            closure = "\n".join(f"{name} => /host/{name} (0x123)" for name in
                                 ("libstdc++.so.6", "libgcc_s.so.1", "libxml2.so.2", "libc.so.6"))
            success = subprocess.CompletedProcess([], 0, "", "")
            failure = subprocess.CompletedProcess([], 1, "", "GLIBCXX_3.4.32 not found")
            with patch.object(graphics.subprocess, "check_output", return_value=cache), \
                    patch.object(graphics.subprocess, "run", return_value=success) as run:
                self.assertEqual(graphics.select(app), "")
                self.assertEqual(run.call_count, 1)
            with patch.object(graphics.subprocess, "check_output", side_effect=[cache, closure]) as load, \
                    patch.object(graphics.subprocess, "run", side_effect=[failure, success]) as run:
                selected = graphics.select(app)
                self.assertIn("/host/libstdc++.so.6", selected)
                self.assertIn("/host/libgcc_s.so.1", selected)
                self.assertIn("/host/libxml2.so.2", selected)
                self.assertNotIn("libc.so", selected)
                self.assertNotIn("libgtk", selected)
                self.assertEqual(run.call_args.kwargs["env"]["LD_PRELOAD"], selected)
                self.assertNotIn("LD_LIBRARY_PATH", load.call_args.kwargs["env"])
            with patch.object(graphics.subprocess, "check_output", side_effect=[cache, closure]), \
                    patch.object(graphics.subprocess, "run", return_value=failure):
                with self.assertRaisesRegex(RuntimeError, "No compatible"):
                    graphics.select(app)


if __name__ == "__main__":
    unittest.main()
