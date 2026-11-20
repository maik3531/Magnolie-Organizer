"""Controlled KWin registry observations; no compositor or output is started."""

from contextlib import ExitStack
from pathlib import Path
import os
import shlex
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from gi.repository import GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_desktop_screen_cast import ScreenCastTarget, _target
from magnolie_desktop_screen_observer import KWinOutputObserver
from magnolie_desktop_screen_output import KWinOutputFeed, KWinOutputWitness
from test_desktop_screen_cast import streams


NAME = 'Virtual-virtual-xdp-kde-magnolie-1'
BUILTIN = {1: 'eDP-1'}


class TestKWinOutputWitness(unittest.TestCase):
    def setUp(self):
        self.registry = object()
        self.audit = KWinOutputWitness(self.registry, BUILTIN)
        self.target = ScreenCastTarget('extend', 53, 80, NAME)

    def observe(self, *outputs):
        return self.audit.observe(self.registry, dict(outputs))

    def test_exact_instance_after_baseline_then_only_its_removal(self):
        self.assertTrue(self.audit.bind(self.target))
        self.assertFalse(self.audit.present(self.target))
        self.assertFalse(self.audit.removal_observed(self.target))
        self.assertTrue(self.observe((1, 'eDP-1'), (2, NAME), (3, 'HDMI-A-1')))
        self.assertTrue(self.audit.present(self.target))
        self.assertTrue(self.observe((1, 'eDP-1'), (2, NAME)))
        self.assertFalse(self.audit.removal_observed(self.target))
        self.assertTrue(self.observe((1, 'eDP-1')))
        self.assertTrue(self.audit.removal_observed(self.target))
        self.assertFalse(self.audit.removal_observed(ScreenCastTarget('extend', 53, 80, NAME)))

    def test_valid_portal_metadata_arrives_after_native_name(self):
        self.assertTrue(self.observe((1, 'eDP-1'), (2, NAME)))
        self.assertTrue(self.audit.bind(self.target))
        self.assertTrue(self.audit.present(self.target))
        self.assertFalse(self.audit.bind(ScreenCastTarget('extend', 8, 81, NAME)))

    def test_no_preexisting_output_or_geometry_fallback(self):
        preexisting = KWinOutputWitness(self.registry, {1: NAME})
        preexisting.observe(self.registry, {2: NAME})
        self.assertFalse(preexisting.bind(self.target))
        for target in (ScreenCastTarget('monitor', 53, 80, NAME), ScreenCastTarget('extend', 53, 80),
                       ScreenCastTarget('extend', 53, 80, 'HDMI-A-1'), ScreenCastTarget('extend', 53, None, NAME)):
            self.assertFalse(self.audit.bind(target))
        self.assertTrue(self.audit.bind(self.target))
        self.assertTrue(self.observe((2, NAME + '-unrelated')))
        self.assertFalse(self.audit.present(self.target))
        self.assertFalse(self.audit.removal_observed(self.target))

    def test_replacement_duplicate_or_registry_loss_never_confirms(self):
        for next_map in ({2: NAME, 3: NAME}, {3: NAME}, {2: 'different-name'}, {0: NAME}):
            with self.subTest(snapshot=next_map):
                audit = KWinOutputWitness(self.registry, BUILTIN)
                self.assertTrue(audit.bind(self.target))
                self.assertTrue(audit.observe(self.registry, {2: NAME}))
                self.assertFalse(audit.observe(self.registry, next_map))
                self.assertFalse(audit.observe(self.registry, {}))
                self.assertFalse(audit.removal_observed(self.target))
        self.audit.bind(self.target)
        self.observe((2, NAME))
        self.assertFalse(self.audit.observe(object(), {}))
        self.assertTrue(self.audit.present(self.target))
        self.audit.retire(self.registry)
        self.assertFalse(self.observe())
        self.assertFalse(self.audit.removal_observed(self.target))

    def test_removed_before_binding_and_reused_global_do_not_become_proof(self):
        self.observe((2, NAME))
        self.observe()
        self.assertFalse(self.audit.bind(self.target))
        self.assertFalse(self.audit.removal_observed(self.target))
        audit = KWinOutputWitness(self.registry, BUILTIN)
        audit.bind(self.target)
        audit.observe(self.registry, {2: NAME})
        audit.observe(self.registry, {})
        self.assertFalse(audit.observe(self.registry, {2: NAME}))
        self.assertFalse(audit.removal_observed(self.target))

    def test_portal_target_only_keeps_typed_bounded_extending_mapping(self):
        def response(mapping, kind):
            return GLib.Variant('a{sv}', {'streams': GLib.Variant('a(ua{sv})', [(53, {
                'source_type': GLib.Variant('u', kind), 'pipewire-serial': GLib.Variant('t', 80),
                'mapping_id': mapping})])})

        good = GLib.Variant('s', NAME)
        self.assertEqual(_target(response(good, 4), 'extend', 6), self.target)
        self.assertIsNone(_target(response(good, 4), 'extend', 4).mapping_id)
        self.assertIsNone(_target(response(good, 1), 'monitor', 6).mapping_id)
        for bad in (GLib.Variant('s', '\n'), GLib.Variant('s', 'x' * 256), GLib.Variant('u', 1)):
            self.assertIsNone(_target(response(bad, 4), 'extend', 6).mapping_id)
        self.assertIsNone(_target(GLib.Variant('a{sv}', streams()), 'extend', 6).mapping_id)

    def test_truncated_observer_line_revokes_an_apparent_removal(self):
        feed = KWinOutputFeed()
        for record in (b'+\t1\teDP-1\n', b'ready\n'):
            self.assertTrue(feed.consume(record))
        self.assertTrue(feed.witness.bind(self.target))
        self.assertTrue(feed.consume(f'+\t2\t{NAME}\n'.encode()))
        self.assertTrue(feed.consume(b'-\t2\n'))
        self.assertTrue(feed.witness.removal_observed(self.target))
        self.assertFalse(feed.consume(b'+\t'))
        self.assertFalse(feed.witness.removal_observed(self.target))
        self.assertFalse(feed.consume(b'ready\n'))

    def test_unfinished_native_name_cannot_certify_a_baseline(self):
        feed = KWinOutputFeed(require_announcement=True)
        self.assertTrue(feed.consume(b'?\t1\n'))
        self.assertTrue(feed.consume(b'+\t1\teDP-1\n'))
        self.assertTrue(feed.consume(b'ready\n'))
        witness = feed.take_for_run()
        self.assertTrue(feed.consume(b'?\t2\n'))
        self.assertFalse(feed.settled)
        with self.assertRaises(PermissionError):
            feed.mark_start()
        self.assertTrue(feed.consume(f'+\t2\t{NAME}\n'.encode()))
        feed.mark_start()
        self.assertFalse(witness.bind(self.target))  # Named later, but before the submitted Start.
        with self.assertRaises(PermissionError):
            feed.mark_start()

    def test_native_name_requires_original_announcement(self):
        for records in ((b'?\t1\n', b'ready\n'), (b'+\t1\teDP-1\n',)):
            with self.subTest(records=records):
                feed = KWinOutputFeed(require_announcement=True)
                for record in records[:-1]:
                    self.assertTrue(feed.consume(record))
                self.assertFalse(feed.consume(records[-1]))
                self.assertIsNone(feed.witness)

    @unittest.skipUnless(os.environ.get('MAGNOLIE_SCREEN_PRIVATE_WAYLAND') == '1',
                         'opt in to a private libwayland socketpair')
    def test_original_output_uses_real_libwayland_registry_and_disconnect_fences_it(self):
        here = Path(__file__).resolve().parent
        with TemporaryDirectory(prefix='magnolie-wayland-test-') as directory:
            def compile_binary(source, lib):
                program = str(Path(directory) / source.stem)
                flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', lib], text=True, timeout=3)
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-o', program, str(source),
                                *shlex.split(flags)], check=True, timeout=15)
                return program

            observer = compile_binary(here.parent / 'bin/magnolie_wayland_output_observer.c', 'wayland-client')
            server = compile_binary(here / 'wayland_output_fixture.c', 'wayland-server')
            left, right = socket.socketpair()
            with left, right, ExitStack() as cleanup:
                def start(binary, endpoint, **streams):
                    fd = endpoint.fileno()
                    process = cleanup.enter_context(subprocess.Popen([binary, str(fd)], pass_fds=(fd,),
                                                                      bufsize=0, **streams))
                    def reap():
                        if process.poll() is None:
                            process.kill()
                        process.wait(3)
                    cleanup.callback(reap)
                    endpoint.close()
                    return process

                fixture = start(server, left, stdin=subprocess.PIPE)
                client = KWinOutputObserver(observer, right)
                self.assertEqual(right.fileno(), -1)

                def wait_for(condition):
                    deadline = monotonic() + 3
                    while monotonic() < deadline:
                        client.tick()
                        if condition():
                            return
                        sleep(.005)
                    self.fail('Wayland observer deadline')

                def stop():
                    client.close()
                    wait_for(lambda: client.drained)

                cleanup.callback(stop)
                wait_for(lambda: client.feed is not None)
                feed = client.feed
                self.assertEqual(set(feed._live.values()), {'eDP-1', 'HDMI-A-1'})
                witness = feed.take_for_run()
                self.assertFalse(feed.mark_start())
                wait_for(feed.mark_start)
                self.assertTrue(witness.bind(self.target))
                fixture.stdin.write(b'+')
                wait_for(lambda: feed.witness.present(self.target))
                fixture.stdin.write(b'o')
                wait_for(lambda: 'HDMI-A-1' not in feed._live.values())
                self.assertTrue(feed.witness.present(self.target))
                self.assertFalse(feed.witness.removal_observed(self.target))
                fixture.stdin.write(b'-')
                wait_for(lambda: feed.witness.removal_observed(self.target))
                fixture.stdin.write(b'q')
                self.assertEqual(fixture.wait(3), 0)
                wait_for(lambda: client.drained)
                self.assertIsNone(client.feed)
                self.assertFalse(feed.witness.removal_observed(self.target))

            stalled, silent_peer = socket.socketpair()
            with stalled, silent_peer:
                client = KWinOutputObserver(observer, stalled)
                try:
                    self.assertIsNone(client.feed)
                    with patch('magnolie_desktop_screen_observer.monotonic', return_value=client._baseline_deadline):
                        client.tick()
                    wait_for(lambda: client.drained)
                    self.assertIsNone(client.feed)
                finally:
                    stop()
