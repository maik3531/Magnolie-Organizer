"""Current feature closure, archive contracts and read-only preflight regressions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "werkzeuge"))
import notes_candidate
import package_preflight
import release_sources
from runtime_pruefen import package_modules


def test_all_four_explicit_runtime_lists_match_current_source():
    actual = {path.name for path in (ROOT / 'bin').glob('*.py')}
    assert actual
    for kind, installed in package_modules(ROOT).items():
        assert installed == actual, kind


def test_json_and_markdown_contracts_are_copied_without_changing_goldens(tmp_path):
    shared = tmp_path / 'contracts'
    shared.mkdir()
    (shared / 'vectors.json').write_text('{"immutableGolden":true}')
    (shared / 'lifecycle.md').write_text('# Public protocol lifecycle')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in shared.iterdir()}
    source = tmp_path / 'standalone'
    source.mkdir()
    release_sources.sync_contracts(source)
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source / 'contracts').iterdir()} == hashes
    (shared / 'unexpected.sh').write_text('# not a contract')
    with pytest.raises(ValueError, match='contracts'):
        release_sources.sync_contracts(source)


def test_new_feature_harnesses_are_source_not_product_payload():
    spec = importlib.util.spec_from_file_location('packaging_background_runner', ROOT / 'pruefungen/run_background_reliability.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    selected = {str(relative) for relative, _ in release_sources.source_files(ROOT / 'pruefungen')}
    for name in runner.DEFAULT_TESTS + ['background_cross_platform.py', 'letter_cross_platform.py',
            'pot_cross_platform.py', 'receipt-native/cross_receipt.py', 'receipt-native/ReceiptProbe.csproj',
            'phone_setup_daemon_host.py', 'phone_invitation_host.py', 'phone_bluetooth_host.py',
            'letter-layout/LetterProbe.csproj', 'letter-layout/Program.cs', 'letter-layout/web.js']:
        assert name in selected
    for file in ('debian/install', 'rpm/magnolie-organizer.spec', 'flatpak/io.gitlab.maik3531.MagnolieOrganizer.json'):
        text = (ROOT / file).read_text()
        assert 'install -m 0644 pruefungen/' not in text and 'contracts/ /app/' not in text


def test_private_metadata_probe_never_opens_secret_content(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.keystore'
    path.write_text('SYNTHETIC NON-CREDENTIAL')
    def forbidden(*_args, **_kwargs):
        pytest.fail('metadata probe read secret contents')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    assert package_preflight.metadata(path)['regular']
    assert not package_preflight.metadata(tmp_path / 'missing')['exists']


def test_sdk_discovery_requires_real_platform_tools(tmp_path):
    (tmp_path / 'platform-tools').mkdir()
    (tmp_path / 'platform-tools/adb').write_text('synthetic executable placeholder')
    assert package_preflight.android_sdk(tmp_path) == tmp_path


def test_apk_audit_rejects_validation_and_secret_payload_without_keys(tmp_path, monkeypatch):
    apk = tmp_path / 'synthetic.apk'
    certificate = 'a' * 64
    def output(args, **_kwargs):
        if args[1:3] == ['dump', 'badging']:
            return "package: name='io.gitlab.maik3531.magnolienotes' versionCode='14' versionName='1.0.14'\n"
        if args[1:3] == ['dump', 'xmltree']:
            return 'E: manifest\n'
        return 'Signer #1 certificate SHA-256 digest: ' + certificate + '\n'
    monkeypatch.setattr(notes_candidate.subprocess, 'check_output', output)
    for name in ('assets/synthetic.token', 'fixtures/test.json', 'validation/probe.txt', '../outside'):
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr(name, b'SYNTHETIC NON-CREDENTIAL')
        with pytest.raises(ValueError):
            notes_candidate.audit(apk, '1.0.14', 14, 'synthetic-aapt', 'synthetic-apksigner', certificate)
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('AndroidManifest.xml', b'SYNTHETIC MANIFEST')
        archive.writestr('classes.dex', b'dex\n035\0' + bytes(104))
    notes_candidate.audit(apk, '1.0.14', 14, 'synthetic-aapt', 'synthetic-apksigner', certificate)
    with pytest.raises(ValueError, match='version'):
        notes_candidate.audit(apk, '1.0.13', 13, 'synthetic-aapt', 'synthetic-apksigner', certificate)
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('assets/innocent.txt', b'-----BEGIN PRIVATE KEY-----\nSYNTHETIC NON-KEY\n')
    with pytest.raises(ValueError, match='Plaintext'):
        notes_candidate.audit(apk, '1.0.14', 14, 'synthetic-aapt', 'synthetic-apksigner', certificate)


def test_plaintext_marker_is_rejected_in_source_and_binary_payload(tmp_path):
    (tmp_path / 'innocent.txt').write_bytes(b'-----BEGIN PRIVATE KEY-----\nSYNTHETIC NON-KEY\n')
    with pytest.raises(ValueError, match='Private material'):
        list(release_sources.source_files(tmp_path))
    with pytest.raises(ValueError, match='Private key'):
        release_sources.audit_binary(tmp_path)


def dex_fixture(name):
    data = bytearray(180 + len(name))
    data[:8] = b'dex\n035\0'
    for offset, value in ((60, 112), (68, 116), (96, 1), (100, 120), (112, 152), (116, 0), (120, 0)):
        struct.pack_into('<I', data, offset, value)
    data[152] = len(name)
    data[153:153 + len(name)] = name
    return bytes(data)


def test_dex_class_definitions_are_not_confused_with_reflection_strings():
    name = b'Lio/gitlab/maik3531/magnolienotes/ValidationHooks;'
    assert list(notes_candidate.dex_classes(dex_fixture(name))) == [name.decode()]


@pytest.mark.parametrize('damage', ['application-id', 'debuggable', 'test-only', 'certificate', 'validation-class'])
def test_production_apk_cross_metadata_is_fail_closed(tmp_path, monkeypatch, damage):
    apk = tmp_path / 'synthetic.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('classes.dex', dex_fixture(b'Lio/gitlab/maik3531/magnolienotes/' +
            (b'ValidationHooks;' if damage == 'validation-class' else b'MagnolieApp;')))
    certificate = 'a' * 64
    def output(args, **_kwargs):
        if args[1:3] == ['dump', 'badging']:
            app = 'io.gitlab.maik3531.magnolienotes' + ('.validation' if damage == 'application-id' else '')
            return f"package: name='{app}' versionCode='14' versionName='1.0.14'\n" + ('application-debuggable' if damage == 'debuggable' else '')
        if args[1:3] == ['dump', 'xmltree']:
            return 'A: android:testOnly(0x01010272)=(type 0x12)0xffffffff' if damage == 'test-only' else 'E: manifest'
        return 'Signer #1 certificate SHA-256 digest: ' + ('b' * 64 if damage == 'certificate' else certificate) + '\n'
    monkeypatch.setattr(notes_candidate.subprocess, 'check_output', output)
    with pytest.raises(ValueError):
        notes_candidate.audit(apk, '1.0.14', 14, 'synthetic-aapt', 'synthetic-apksigner', certificate)
