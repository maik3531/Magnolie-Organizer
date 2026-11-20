#!/usr/bin/env python3
"""#691 source contracts and a readable merged-manifest audit.

The default tests do not run Gradle, merge Android manifests, or emulate Android.
After a separately authorized build, audit its actual merged manifest with:
  python3 werkzeuge/test_target37_build.py --manifest PATH --target 37
The audit does not establish APK signing, installation, or native acceptance.
"""
from pathlib import Path
import argparse
import copy
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ANDROID = '{http://schemas.android.com/apk/res/android}'
PACKAGE = 'io.gitlab.maik3531.magnolienotes'
PERMISSION = 'android.permission.ACCESS_LOCAL_NETWORK'
MARKER = PACKAGE + '.TARGET37_VALIDATION'
SUFFIX = '-api37-validation'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_manifest(data, target):
    """Check independently observable output invariants, never source intent."""
    require(target in (35, 37), 'Unsupported target for this migration gate')
    require(b'<!DOCTYPE' not in data.upper(), 'DOCTYPE is not allowed')
    root = ET.fromstring(data)
    require(root.tag == 'manifest' and root.get('package') == PACKAGE,
            'Unexpected manifest/package identity')
    sdk = root.findall('uses-sdk')
    require(len(sdk) == 1, 'Expected exactly one merged uses-sdk element')
    require(sdk[0].get(ANDROID + 'minSdkVersion') == '26', 'minSdk must remain 26')
    require(sdk[0].get(ANDROID + 'targetSdkVersion') == str(target), 'Wrong target SDK')
    app = root.findall('application')
    require(len(app) == 1, 'Expected exactly one merged application element')
    require(app[0].get(ANDROID + 'debuggable', 'false') == 'false',
            'Expected a non-debuggable release variant')
    permissions = [item for item in root if item.tag.startswith('uses-permission')
                   and item.get(ANDROID + 'name') == PERMISSION]
    markers = [item for item in app[0].findall('meta-data')
               if item.get(ANDROID + 'name') == MARKER]
    if target == 37:
        require(len(permissions) == 1 and permissions[0].tag == 'uses-permission',
                'Target 37 requires exactly one LAN declaration')
        require(permissions[0].get(ANDROID + 'maxSdkVersion') is None,
                'The LAN declaration must not expire on a newer device')
        require(app[0].get(ANDROID + 'testOnly') == 'true',
                'Candidate must be testOnly')
        require(len(markers) == 1 and markers[0].get(ANDROID + 'value') == 'true',
                'Candidate validation marker is missing')
        require(root.get(ANDROID + 'versionName', '').endswith(SUFFIX),
                'Candidate version suffix is missing')
    else:
        require(not permissions, 'Target 35 must not declare LAN permission')
        require(not markers and app[0].get(ANDROID + 'testOnly', 'false') == 'false',
                'Product must not carry candidate markers')
        require(not root.get(ANDROID + 'versionName', '').endswith(SUFFIX),
                'Product carries the candidate version suffix')


class Target37BuildContracts(unittest.TestCase):
    """Bounded integration checks; not a Kotlin/AGP execution substitute."""
    def setUp(self):
        self.build = (ROOT / 'app/build.gradle.kts').read_text()

    def test_opt_in_is_strict_offline_unsigned_before_key_loading(self):
        declaration = self.build.split('val target37Validierung =', 1)[1].split(
            'val schluesselDatei =', 1)[0]
        self.assertIn('providers.gradleProperty("magnolieTarget37Validation")', declaration)
        self.assertIn('.map { it.toBooleanStrict() }.getOrElse(false)', declaration)
        self.assertIn('check(!target37Validierung || (fdroidBau && gradle.startParameter.isOffline))',
                      declaration)
        self.assertIn('if (!fdroidBau && schluesselDatei.isFile)', self.build)

    def test_target_permission_and_suffix_are_one_explicit_choice(self):
        self.assertIn('targetSdk = if (target37Validierung) 37 else 35', self.build)
        self.assertIn('minSdk = 26', self.build)
        self.assertIn('if (target37Validierung) versionNameSuffix = "-api37-validation"', self.build)
        self.assertIn('val releaseManifest = if (target37Validierung) target37Manifest\n'
                      '            else file("src/release/AndroidManifest.xml")', self.build)
        self.assertIn('extension.sourceSets.getByName("release").manifest.srcFile(releaseManifest)',
                      self.build)

    def test_public_agp_manifest_api_has_no_legacy_getter(self):
        # AndroidSourceFile exposes srcFile(Any), not getSrcFile()/a Kotlin property.
        self.assertNotRegex(self.build, r'\.manifest\.srcFile\b(?!\s*\()')
        self.assertNotIn('.getSrcFile(', self.build)
        self.assertNotRegex(self.build, r'as\s+.*(?:DefaultAndroidSource|com\.android\.build\.gradle)')

    def test_final_dsl_checks_and_variant_filter_are_present(self):
        gates = self.build.split('androidComponents {', 1)[1].split(
            'val pruefeReleaseSigningKonfiguration', 1)[0]
        for contract in ('finalizeDsl { extension ->',
                         'extension.defaultConfig.minSdk == 26',
                         'extension.defaultConfig.targetSdk == if (target37Validierung) 37 else 35',
                         'fdroidBau && release.signingConfig == null && !release.isDebuggable',
                         'extension.sourceSets.getByName("release").manifest.srcFile(releaseManifest)',
                         'check(target37Manifest.isFile)',
                         'release.versionNameSuffix == "-api37-validation"',
                         'beforeVariants(selector().all())',
                         'if (target37Validierung) {\n'
                         '            if (variant.buildType != "release") variant.enable = false',
                         'variant.deviceTests.values.forEach { it.enable = false }'):
            self.assertIn(contract, gates)

    def test_overlay_has_only_the_coordinated_candidate_changes(self):
        main = ET.parse(ROOT / 'app/src/main/AndroidManifest.xml').getroot()
        overlay = ET.parse(ROOT / 'app/src/target37/AndroidManifest.xml').getroot()
        self.assertFalse(any(item.get(ANDROID + 'name') == PERMISSION for item in main))
        self.assertEqual([item.tag for item in overlay], ['uses-permission', 'application'])
        self.assertEqual(overlay[0].attrib, {ANDROID + 'name': PERMISSION})
        self.assertEqual(overlay[1].attrib, {ANDROID + 'testOnly': 'true'})
        self.assertEqual(len(overlay[1]), 1)
        self.assertEqual(overlay[1][0].tag, 'meta-data')
        self.assertEqual(overlay[1][0].attrib,
                         {ANDROID + 'name': MARKER, ANDROID + 'value': 'true'})


class MergedManifestAuditTests(unittest.TestCase):
    """Synthetic positive/negative outputs exercise the actual audit function."""
    def specimen(self, target):
        root = ET.Element('manifest', {'package': PACKAGE,
            ANDROID + 'versionName': '1.0.21' + (SUFFIX if target == 37 else '')})
        ET.SubElement(root, 'uses-sdk', {ANDROID + 'minSdkVersion': '26',
                                        ANDROID + 'targetSdkVersion': str(target)})
        app = ET.SubElement(root, 'application')
        if target == 37:
            ET.SubElement(root, 'uses-permission', {ANDROID + 'name': PERMISSION})
            app.set(ANDROID + 'testOnly', 'true')
            ET.SubElement(app, 'meta-data', {ANDROID + 'name': MARKER, ANDROID + 'value': 'true'})
        return root

    def reject(self, root, target):
        with self.assertRaises(ValueError):
            audit_manifest(ET.tostring(root), target)

    def test_product_and_candidate_outputs(self):
        for target in (35, 37):
            audit_manifest(ET.tostring(self.specimen(target)), target)

    def test_sdk_identity_and_debug_mismatches_fail(self):
        for target in (35, 37):
            for kind in ('package', 'min', 'target', 'debug', 'duplicate_sdk', 'duplicate_app'):
                with self.subTest(target=target, mutation=kind):
                    root = self.specimen(target)
                    if kind == 'package': root.set('package', PACKAGE + '.other')
                    if kind == 'min': root.find('uses-sdk').set(ANDROID + 'minSdkVersion', '27')
                    if kind == 'target': root.find('uses-sdk').set(ANDROID + 'targetSdkVersion', '36')
                    if kind == 'debug': root.find('application').set(ANDROID + 'debuggable', 'true')
                    if kind == 'duplicate_sdk': root.append(copy.deepcopy(root.find('uses-sdk')))
                    if kind == 'duplicate_app': root.append(copy.deepcopy(root.find('application')))
                    self.reject(root, target)

    def test_candidate_requires_permission_and_private_markers(self):
        for kind in ('permission', 'maxsdk', 'duplicate_permission', 'testOnly', 'marker', 'suffix'):
            with self.subTest(mutation=kind):
                root = self.specimen(37)
                if kind == 'permission': root.remove(root.find('uses-permission'))
                if kind == 'maxsdk': root.find('uses-permission').set(ANDROID + 'maxSdkVersion', '37')
                if kind == 'duplicate_permission': root.append(copy.deepcopy(root.find('uses-permission')))
                if kind == 'testOnly': root.find('application').attrib.clear()
                if kind == 'marker': root.find('application').remove(root.find('application/meta-data'))
                if kind == 'suffix': root.set(ANDROID + 'versionName', '1.0.21')
                self.reject(root, 37)

    def test_product_rejects_candidate_leaks(self):
        for kind in ('permission', 'marker', 'testOnly', 'suffix'):
            with self.subTest(mutation=kind):
                root = self.specimen(35)
                if kind == 'permission': ET.SubElement(root, 'uses-permission', {ANDROID + 'name': PERMISSION})
                if kind == 'marker': ET.SubElement(root.find('application'), 'meta-data', {ANDROID + 'name': MARKER})
                if kind == 'testOnly': root.find('application').set(ANDROID + 'testOnly', 'true')
                if kind == 'suffix': root.set(ANDROID + 'versionName', '1.0.21' + SUFFIX)
                self.reject(root, 35)


if __name__ == '__main__':
    if '--manifest' in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--manifest', type=Path, required=True)
        parser.add_argument('--target', type=int, choices=(35, 37), required=True)
        args = parser.parse_args()
        try:
            audit_manifest(args.manifest.read_bytes(), args.target)
        except (ValueError, ET.ParseError, OSError) as error:
            parser.exit(1, f'FAIL: {error}\n')
        print(f'PASS: readable merged manifest target {args.target}; not APK/native acceptance')
    else:
        unittest.main()
