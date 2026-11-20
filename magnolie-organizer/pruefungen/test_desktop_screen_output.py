"""Controlled KWin registry observations; no compositor or output is started."""

from pathlib import Path
import sys
import unittest

from gi.repository import GLib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from magnolie_desktop_screen_cast import ScreenCastTarget, _target
from magnolie_desktop_screen_output import KWinOutputWitness
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
