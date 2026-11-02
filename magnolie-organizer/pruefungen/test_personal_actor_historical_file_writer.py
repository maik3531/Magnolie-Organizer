"""Actual native AES/atomic store + controller, not GTK/IPC/physical phone E2E."""
import hashlib
import importlib.machinery
import importlib.util
import json
import queue
import threading
from types import MethodType, SimpleNamespace
from pathlib import Path

import pytest
import magnolie_personal_actor as actor
from magnolie_personal_actor_store import NativeProducerBookSnapshot
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_historical_prepare import prepared, durable_queue
from test_personal_actor_transport import frame


def native_store(tmp_path, monkeypatch):
    for key in ('HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR'):
        directory = tmp_path / key; directory.mkdir(parents=True)
        monkeypatch.setenv(key, str(directory))
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/nonexistent-historical-writer-test')
    source = Path(__file__).resolve().parents[1] / 'bin/magnolie-organizer'
    loader = importlib.machinery.SourceFileLoader('historical_writer_native', str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module


@pytest.mark.parametrize('fault', ['none', 'failure', 'payload', 'after-write'])
def test_historical_native_writer_encrypts_once_then_only_exact_peer_receipt_completes(tmp_path, monkeypatch, gui_candidates, fault):
    native = native_store(tmp_path, monkeypatch)
    fixtures = gui_candidates if fault == 'none' else gui_candidates[:1]
    for index, fixture in enumerate(fixtures):
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path / str(index), monkeypatch, fixture)
        admission = service.personal_actor_admissions[handle.actor_id]
        manifest = service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope'])
        claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        before_text = json.dumps(book, ensure_ascii=False); password = 'synthetic-only-historical-file'
        envelope, dek, dek_id, wrapper = native.daten_huelle_anlegen(before_text, password)
        path = tmp_path / str(index) / 'encrypted-book.json'
        native.atomar_text_schreiben(str(path), envelope)
        before_bytes, before_saved, queue = path.read_bytes(), read(), durable_queue(service)
        writes = []
        def writer(payload):
            writes.append(payload)
            if fault == 'failure':
                raise OSError('Synthetic pre-write failure')
            stored = native.daten_verschluesseln(payload, password, dek, dek_id, wrapper)
            native.atomar_text_schreiben(str(path), stored)
            if fault == 'after-write':
                raise OSError('Synthetic failure after atomic file replacement')
            owner.record_saved('native-producer-fixture', True, hashlib.sha256(payload.encode()).hexdigest())
            data = json.loads(payload); saved = read()
            fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            service.native_actor_producer_book = lambda: NativeProducerBookSnapshot.capture(read, lambda: data,
                lambda: (saved['book_source'], saved['sequence'], fingerprint))
        if fault == 'after-write':
            with pytest.raises(OSError):
                service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
            after_bytes = path.read_bytes()
            assert native.daten_entschluesseln(path.read_text(), password) == text
            with pytest.raises(PermissionError):
                service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
            with pytest.raises(PermissionError):
                service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
            status = service.personal_actor_status(registry, handle)
            assert len(writes) == 1 and status['phase'] == 'cancelled' and status['historical_book_persisted'] is False
            assert path.read_bytes() == after_bytes and read() == before_saved and durable_queue(service) == queue and not channel.sent
            continue
        if fault != 'none':
            with pytest.raises(OSError if fault == 'failure' else PermissionError):
                service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text + (' ' if fault == 'payload' else ''), writer)
            assert len(writes) == (1 if fault == 'failure' else 0) and path.read_bytes() == before_bytes and read() == before_saved
            assert durable_queue(service) == queue and not channel.sent
            continue
        result = service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
        assert result['historical_book_persisted'] is False
        assert native.ist_verschluesselt(path.read_text()) and native.daten_entschluesseln(path.read_text(), password) == text
        assert read()['sequence'] == before_saved['sequence'] + 1
        with pytest.raises(PermissionError):
            service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
        after_bytes = path.read_bytes()
        confirmed = service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
        assert confirmed['historical_book_persisted'] is True and confirmed['phone_data_persisted'] is False
        service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
        assert len(writes) == 1 and path.read_bytes() == after_bytes
        service.advance_personal_actor_completion(registry, handle)
        decision = channel.sent.pop(); assert not channel.sent
        assert actor.unwrap(decision['body'])[0] == 'personal_sync.deletion_decision'
        service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, decision['message_id'])))
        done = service.personal_actor_status(registry, handle)
        assert done['phase'] == 'completed' and done['phone_persisted'] is True and done['phone_data_persisted'] is False
        assert path.read_bytes() == after_bytes and service.current_content_scope(peer['device_id'], peer['static_public'], admission['scope']) == manifest
        with pytest.raises(PermissionError): registry.require_current(handle)


def test_actual_linux_save_worker_supplies_its_own_fresh_saved_content_witness_to_historical_confirm(tmp_path, monkeypatch, gui_candidates):
    native = native_store(tmp_path, monkeypatch)
    for index, fixture in enumerate(gui_candidates):
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = prepared(tmp_path / str(index), monkeypatch, fixture)
        path = tmp_path / str(index) / 'actual-worker-book.json'
        monkeypatch.setattr(native, 'daten_datei', lambda: str(path))
        password = 'synthetic-only-actual-worker'
        envelope, dek, dek_id, wrapper = native.daten_huelle_anlegen(json.dumps(book), password)
        native.speichere_text(envelope)
        initial = service.native_actor_producer_book()
        responses = []
        probe = SimpleNamespace(_kennwort=password, _daten_dek=dek, _daten_dek_kennung=dek_id, _daten_umschlag=wrapper,
            _aktuelle_daten=book, _daten_sperre=threading.RLock(), _speicher_auftraege=queue.Queue(), _gesperrt=False, _ladefehler='',
            _notes_actor_book_owner=owner, _notes_actor_saved_data=(initial.book_source, initial.sequence, initial.content_sha256),
            _telefon_actor_buchbindung=lambda: ('native-producer-fixture', True), _journal_snapshot=lambda reason: None,
            antwort=lambda callback, value: responses.append((callback, value)))
        for name in ('_vielleicht_verschluesseln', '_telefon_actor_buchnachweis', '_telefon_actor_producer_buch'):
            setattr(probe, name, MethodType(getattr(native.Fenster, name), probe))
        service.native_actor_saved_book = probe._telefon_actor_buchnachweis
        service.native_actor_producer_book = probe._telefon_actor_producer_buch
        claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text)
        before = probe._telefon_actor_buchnachweis()
        def writer(payload):
            # Invoke the ACTUAL serial native save worker with a bounded queue,
            # not a replacement record_saved callback or fabricated SaveACK.
            probe._speicher_auftraege.put((1, payload)); probe._speicher_auftraege.put(None)
            native.Fenster._speicher_lauf(probe)
            saved_responses = [value for callback, value in responses if callback == 'App.gespeichert']
            assert len(saved_responses) == 1 and saved_responses[0]['ok'] is True
        with probe._daten_sperre:
            service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
            fresh = probe._telefon_actor_buchnachweis()
            assert fresh['sequence'] == before['sequence'] + 1 and fresh['sha256'] == hashlib.sha256(text.encode()).hexdigest()
            assert native.daten_entschluesseln(path.read_text(), password) == text and probe._aktuelle_daten == json.loads(text)
            actual_bytes = path.read_bytes()
            result = service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'])
            assert result['historical_book_persisted'] is True and result['phone_data_persisted'] is False
        service.advance_personal_actor_completion(registry, handle)
        decision = channel.sent.pop(); assert not channel.sent
        service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, decision['message_id'])))
        assert service.personal_actor_status(registry, handle)['phase'] == 'completed'
        assert path.read_bytes() == actual_bytes and len([value for callback, value in responses if callback == 'App.gespeichert']) == 1
