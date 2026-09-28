"""Read-only system KDE contact cache and D-Bus ownership contracts."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_kde_native import native, kde


def trust(path, device):
    key = kde.ec.generate_private_key(kde.ec.SECP256R1())
    name = kde.x509.Name([kde.x509.NameAttribute(kde.NameOID.COMMON_NAME, device)])
    now = kde.datetime.now(kde.timezone.utc)
    cert = (kde.x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(kde.x509.random_serial_number())
            .not_valid_before(now - kde.timedelta(days=1)).not_valid_after(now + kde.timedelta(days=1))
            .sign(key, kde.hashes.SHA256()))
    pem = cert.public_bytes(kde.serialization.Encoding.PEM).decode('ascii')
    path.write_text('[' + device + ']\ncertificate=' + json.dumps(pem) + '\n', encoding='utf-8')
    return cert.fingerprint(kde.hashes.SHA256()).hex()


@pytest.fixture
def source(tmp_path, monkeypatch):
    config, data = tmp_path / 'config', tmp_path / 'data'
    monkeypatch.setenv('XDG_CONFIG_HOME', str(config))
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    backend, _ = native()
    backend.bus.contacts = True
    device = backend.bus.ids[0]
    trusted = config / 'kdeconnect/trusted_devices'; trusted.parent.mkdir(parents=True)
    fingerprint = trust(trusted, device)
    cache = data / 'kpeoplevcard' / ('kdeconnect-' + device); cache.mkdir(parents=True)
    card = 'BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Synthetic\r\nTEL:+491701234567\r\nEND:VCARD\r\n'
    (cache / '1.vcf').write_bytes(card.encode())
    (cache / '2.vcard').write_bytes(card.replace('Synthetic', 'Legacy').encode())
    return backend, cache, trusted, fingerprint


def test_native_photo_source_reads_its_cache_without_changing_permissions(source):
    backend, cache, trusted, fingerprint = source
    before = {path: path.read_bytes() for path in [trusted, *cache.iterdir()]}
    status = backend.status()
    assert status['contacts_available'] and status['available']
    result = backend.contact_uids(status['contacts_device_id'])
    assert result['fingerprint'] == fingerprint
    assert [item['uid'] for item in result['contacts']] == ['1', '2']
    assert all(type(item['modified_ms']) is int and 0 <= item['modified_ms'] < 2**53 for item in result['contacts'])
    cards = backend.contact_vcards(['1', '2'], status['contacts_device_id'])
    assert cards['fingerprint'] == fingerprint
    assert cards['contacts'][0]['vcard'] == (cache / '1.vcf').read_bytes().decode()
    assert len([call for call in backend.bus.calls if call[3] == 'synchronizeRemoteWithLocal']) == 1
    assert not any(call[3] in ('setPluginEnabled', 'requestPairing', 'StartServiceByName', 'unpair') for call in backend.bus.calls)
    assert all(path.read_bytes() == value for path, value in before.items())
    first_stamp = result['contacts'][0]['modified_ms']
    path = cache / '1.vcf'; st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    assert backend.contact_uids()['contacts'][0]['modified_ms'] > first_stamp


@pytest.mark.parametrize('state', ['unpaired', 'offline', 'plugin', 'missing-certificate', 'wrong-certificate'])
def test_native_contact_source_unavailable_does_not_disable_sms(source, state):
    backend, cache, trusted, _ = source
    device = backend.bus.ids[0]
    if state == 'unpaired': backend.bus.props[device]['isPaired'] = False
    elif state == 'offline': backend.bus.props[device]['isReachable'] = False
    elif state == 'plugin': backend.bus.contacts = False
    elif state == 'missing-certificate': trusted.unlink()
    else: trusted.write_text('[' + device + ']\ncertificate="invalid"\n')
    status = backend.status()
    assert not status['contacts_available']
    if state not in ('unpaired', 'offline'): assert status['available']
    with pytest.raises(Exception): backend.contact_uids(device)
    assert not any(call[3] == 'synchronizeRemoteWithLocal' for call in backend.bus.calls)


@pytest.mark.parametrize('change', ['owner', 'certificate', 'unpaired', 'plugin'])
def test_native_response_cannot_cross_source_changes(source, monkeypatch, change):
    backend, cache, trusted, _ = source
    read = backend._contact_read
    def changed(path, maximum, directory=None):
        result = read(path, maximum, directory)
        if path == '1.vcf':
            if change == 'owner': backend.bus.owner = ':1.11'
            elif change == 'certificate': trust(trusted, backend.bus.ids[0])
            elif change == 'unpaired': backend.bus.props[backend.bus.ids[0]]['isPaired'] = False
            else: backend.bus.contacts = False
        return result
    monkeypatch.setattr(backend, '_contact_read', changed)
    with pytest.raises(kde.ProtocolError): backend.contact_vcards(['1'])


def test_native_cache_bounds_and_untrusted_paths(source, tmp_path):
    backend, cache, _, _ = source
    for uids in ([], ['../outside'], ['a/b'], ['a\\b'], ['1', '1'], ['1'] * 6):
        with pytest.raises(kde.ProtocolError): backend.contact_vcards(uids)
    outside = tmp_path / 'outside'; outside.write_text('private')
    (cache / 'link.vcf').symlink_to(outside)
    with pytest.raises((OSError, kde.ProtocolError)): backend.contact_uids()
    with pytest.raises((OSError, kde.ProtocolError)): backend.contact_vcards(['link'])
    (cache / 'link.vcf').unlink()
    (cache / '1.vcf').write_text('BEGIN:VCARD\nPHOTO:partial')
    with pytest.raises(kde.ProtocolError): backend.contact_vcards(['1'])
    (cache / '1.vcf').write_bytes(b'x' * (kde.MAX_CONTACT_PACKET + 1))
    with pytest.raises(kde.ProtocolError): backend.contact_vcards(['1'])
    with pytest.raises(kde.ProtocolError): backend.contact_uids()


def test_missing_and_ambiguous_cards_are_not_silently_substituted(source):
    backend, cache, _, _ = source
    assert backend.contact_vcards(['absent'])['contacts'] == []
    (cache / '1.vcard').write_bytes((cache / '1.vcf').read_bytes())
    with pytest.raises(kde.ProtocolError): backend.contact_uids()
    with pytest.raises(kde.ProtocolError): backend.contact_vcards(['1'])


def test_multiple_native_devices_require_explicit_selection(source):
    backend, cache, trusted, _ = source
    device = 'b' * 32
    original = trusted.read_text()
    other_pin = trust(trusted, device)
    trusted.write_text(original + trusted.read_text())
    backend.bus.ids.append(device)
    backend.bus.props[device] = dict(backend.bus.props[backend.bus.ids[0]])
    other = cache.parent / ('kdeconnect-' + device); other.mkdir()
    (other / '1.vcf').write_bytes((cache / '1.vcf').read_bytes())
    assert not backend.status()['contacts_available']
    with pytest.raises(kde.ProtocolError): backend.contact_uids()
    assert backend.contact_uids(device)['fingerprint'] == other_pin


def test_native_certificate_must_belong_to_selected_device(source):
    backend, _, trusted, _ = source
    trust(trusted, 'other-device')
    trusted.write_text(trusted.read_text().replace('[other-device]', '[' + backend.bus.ids[0] + ']'))
    assert not backend.status()['contacts_available']
    with pytest.raises(kde.ProtocolError): backend.contact_uids()


def test_native_qsettings_certificate_with_bom_and_unquoted_escaped_pem(source):
    backend, _, trusted, fingerprint = source
    content = trusted.read_text()
    key, encoded = content.split('certificate=', 1)
    trusted.write_text('\ufeff' + key + 'certificate=' + encoded.strip()[1:-1] + '\n')
    assert backend.contact_uids()['fingerprint'] == fingerprint


def test_native_card_batch_stays_within_contact_ipc_budget(source):
    backend, cache, _, _ = source
    card = 'BEGIN:VCARD\nVERSION:3.0\nFN:Fixture\nNOTE:' + 'x' * (kde.MAX_CONTACT_PACKET // 2) + '\nEND:VCARD\n'
    (cache / '1.vcf').write_text(card)
    (cache / '2.vcard').write_text(card)
    with pytest.raises(kde.ProtocolError): backend.contact_vcards(['1', '2'])


def test_cache_directory_and_changing_files_are_rejected(source, monkeypatch):
    backend, cache, _, _ = source
    original_stat = os.fstat
    calls = []
    def changing_stat(fd):
        value = original_stat(fd); calls.append(fd)
        return value if len(calls) == 1 else SimpleNamespace(st_size=value.st_size,
            st_mtime_ns=value.st_mtime_ns+1, st_ctime_ns=value.st_ctime_ns)
    with monkeypatch.context() as scoped:
        scoped.setattr(kde.os, 'fstat', changing_stat)
        with pytest.raises(kde.ProtocolError): backend._contact_read(str(cache / '1.vcf'), kde.MAX_CONTACT_PACKET)
    moved = cache.with_name('moved'); cache.rename(moved); cache.symlink_to(moved, target_is_directory=True)
    with pytest.raises(OSError): backend.contact_vcards(['1'])


def test_native_photo_bridge_uses_bound_cache_without_importing_other_fields(source, monkeypatch):
    from modul_laden import quellmodul_laden
    backend, cache, _, fingerprint = source
    monkeypatch.setitem(__import__('sys').modules, 'gi', None)
    app = quellmodul_laden('native_kde_photo_bridge', Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer')
    monkeypatch.setattr(app, '_kdeconnect_backend', lambda: backend)
    (cache / '1.vcf').write_text('BEGIN:VCARD\nVERSION:3.0\nFN:Do not import\n'
        'TEL:+491701234567\nPHOTO;TYPE=PNG;ENCODING=b:iVBORw0KGgo=\nEND:VCARD\n')
    replies = []
    host = SimpleNamespace(antwort=lambda name, value: replies.append(value))
    app.Fenster._kontakt_fotos_lesen(host, dict(requestId='fixture', device_id=backend.bus.ids[0], uids=['1']))
    assert replies[0]['ok'] and replies[0]['fingerprint'] == fingerprint
    contact = replies[0]['contacts'][0]
    assert contact['foto'].startswith('data:image/png;base64,') and contact['telefone']
    assert not any(key in contact for key in ('vorname', 'anzeigename', 'vcard', 'notiz'))
