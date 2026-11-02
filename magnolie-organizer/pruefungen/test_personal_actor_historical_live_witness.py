"""Operation-local plaintext projections must not escape into native save guards."""
import copy
import gc
import hashlib
import json
import weakref

import pytest
import magnolie_personal_actor as actor
from magnolie_personal_actor_completion import NativeBookProofPending
from magnolie_personal_actor_store import NativeProducerBookSnapshot, NativeSavedBookContentWitness
from test_personal_actor_restore_candidate import gui_candidates
from test_personal_actor_historical_prepare import prepared, durable_queue
from test_personal_actor_historical_file_writer import native_store
from test_personal_actor_transport import frame


def projected_setup(tmp_path, monkeypatch, fixture):
    values = prepared(tmp_path, monkeypatch, fixture)
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = values
    gui_book = [copy.deepcopy(book)]; captured = []
    def producer_factory():
        def produce():
            saved = read()
            content = hashlib.sha256(json.dumps(gui_book[0], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            snapshot = NativeProducerBookSnapshot.capture(read, lambda: gui_book[0], lambda: (saved['book_source'], saved['sequence'], content))
            captured.append(weakref.ref(snapshot))
            return snapshot
        return produce
    initial = producer_factory()()
    metadata = {'witness': NativeSavedBookContentWitness.from_snapshot(initial), 'purpose': 'prepare', 'token': None}
    del initial
    service.native_actor_producer_book = None
    service.native_actor_saved_book = None
    def witness(operation, token):
        if metadata['purpose'] == 'prepare' and operation in ('begin', 'save'):
            if metadata['token'] is None: metadata['token'] = token
        elif (metadata['purpose'], operation) not in (('prewrite', 'save'), ('confirm', 'confirm')):
            return None
        return metadata['witness'] if token == metadata['token'] else None
    def live_saved():
        if metadata['purpose'] not in ('confirm', 'terminal'):
            raise NativeBookProofPending('No live native terminal proof in this operation')
        return metadata['witness'].saved_book
    operation_provider = producer_factory(); provider_ref = weakref.ref(operation_provider)
    claim = service.prepare_personal_actor_historical_restore_save(registry, handle, view['revision'], choices, text,
        native_book_source=service.native_actor_book_source, native_saved_book=read, native_producer_book=operation_provider,
        native_book_witness=witness, native_completion_saved_book=live_saved)
    del operation_provider; gc.collect()
    assert provider_ref() is None and all(reference() is None for reference in captured), 'Prepare retained the consumed native plaintext projection/provider'
    assert service.native_actor_producer_book is None and service.native_actor_saved_book is None
    metadata['purpose'] = None
    return values, claim, metadata, gui_book, producer_factory, captured


def test_metadata_only_native_witness_supports_actual_encrypted_save_and_fresh_terminal_without_retaining_books(tmp_path, monkeypatch, gui_candidates):
    native = native_store(tmp_path, monkeypatch)
    for index, fixture in enumerate(gui_candidates[:2]):
        values, claim, metadata, gui_book, factory, captured = projected_setup(tmp_path / str(index), monkeypatch, fixture)
        service, peer, channel, book, owner, read, registry, handle, view, choices, text = values
        with pytest.raises(PermissionError): service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
        assert registry.status(handle)['phase'] == 'completion'
        path = tmp_path / str(index) / 'actual-encrypted-witness.json'; password = 'synthetic-only-live-witness'
        initial, dek, dek_id, wrapper = native.daten_huelle_anlegen(json.dumps(book), password)
        native.atomar_text_schreiben(str(path), initial)
        metadata['purpose'] = 'prewrite'
        def writer(payload):
            native.atomar_text_schreiben(str(path), native.daten_verschluesseln(payload, password, dek, dek_id, wrapper))
            owner.record_saved('native-producer-fixture', True, hashlib.sha256(payload.encode()).hexdigest())
            gui_book[0] = json.loads(payload)
        service.write_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text, writer)
        actual_bytes = path.read_bytes()
        assert native.daten_entschluesseln(path.read_text(), password) == text
        metadata['purpose'] = 'confirm'
        metadata['witness'] = NativeSavedBookContentWitness.from_snapshot(factory()())
        operation_provider = factory(); provider_ref = weakref.ref(operation_provider)
        result = service.confirm_personal_actor_historical_restore_save(registry, handle, claim['claim_token'],
            native_producer_book=operation_provider, native_saved_book=read)
        del operation_provider; gc.collect()
        assert provider_ref() is None and all(reference() is None for reference in captured), 'Confirm retained the consumed after-book projection/provider'
        assert result['historical_book_persisted'] is True and result['phone_data_persisted'] is False
        metadata['purpose'] = None
        with pytest.raises(PermissionError, match='not_ready'): registry.read_completion_controls(handle)
        assert registry.status(handle)['phase'] == 'completion'
        metadata['purpose'] = 'terminal'
        service.advance_personal_actor_completion(registry, handle)
        decision = channel.sent.pop(); assert not channel.sent
        assert actor.unwrap(decision['body'])[0] == 'personal_sync.deletion_decision'
        service._payload(peer, channel, frame(actor.ACK_KIND, actor.ack(handle.actor_id, decision['message_id'])))
        assert service.personal_actor_status(registry, handle)['phase'] == 'completed'
        assert path.read_bytes() == actual_bytes and service.native_actor_producer_book is None and service.native_actor_saved_book is None


@pytest.mark.parametrize('fault', ['no-probe', 'json-impostor', 'content', 'save-bytes', 'source'])
def test_live_metadata_witness_cannot_replace_current_owner_content_or_original_source(tmp_path, monkeypatch, gui_candidates, fault):
    values, claim, metadata, gui_book, factory, captured = projected_setup(tmp_path, monkeypatch, gui_candidates[0])
    service, peer, channel, book, owner, read, registry, handle, view, choices, text = values
    before, queued = read(), durable_queue(service)
    metadata['purpose'] = None if fault == 'no-probe' else 'prewrite'
    observed = metadata['witness']
    if fault == 'json-impostor': metadata['witness'] = observed.saved_book
    if fault == 'content': metadata['witness'] = NativeSavedBookContentWitness(observed.book_source, observed.sequence, observed.saved_sha256, 'f' * 64)
    if fault == 'save-bytes': metadata['witness'] = NativeSavedBookContentWitness(observed.book_source, observed.sequence, 'f' * 64, observed.content_sha256)
    if fault == 'source': service.native_actor_book_source = lambda: '0' * 64
    with pytest.raises(PermissionError): service.check_personal_actor_historical_restore_save(registry, handle, claim['claim_token'], text)
    assert registry.status(handle)['phase'] == ('completion' if fault == 'no-probe' else 'cancelled')
    assert read() == before and durable_queue(service) == queued and not channel.sent and gui_book[0] == book
    with pytest.raises(PermissionError): registry.require_current(handle)
