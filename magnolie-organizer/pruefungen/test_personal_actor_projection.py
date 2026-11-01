"""Operation-local projection receiver gates; no daemon cache or IPC adapter yet."""
import base64
import hashlib
import json
import pytest

from magnolie_personal_actor_projection import NativeBookProjection, CHUNK_BYTES
from test_personal_actor_producer import fixture, native


def transfer_fixture():
    book, _ = fixture(33); book['notizen'][0]['text'] = 'Grüße 🌸' * 9000
    owner, read, snapshot = native(book)
    state = {'owner': True, 'source': 'a' * 64, 'clock': 0}
    receiver = NativeBookProjection(snapshot.saved_book, snapshot.content_sha256, len(snapshot.text.encode()), state['source'],
        current_owner=lambda: state['owner'], current_source=lambda: state['source'], current_saved_book=read, clock=lambda: state['clock'])
    return receiver, state, owner, read, snapshot


def upload(receiver, text):
    raw = text.encode()
    for offset in range(0, len(raw), CHUNK_BYTES):
        assert receiver.append(receiver.token, offset, base64.b64encode(raw[offset:offset + CHUNK_BYTES]).decode()) == min(len(raw), offset + CHUNK_BYTES)


def test_native_projection_chunks_finish_exact_snapshot_and_erase_transport_buffer():
    receiver, state, owner, read, snapshot = transfer_fixture()
    upload(receiver, snapshot.text)
    result = receiver.finish(receiver.token)
    assert result == snapshot and result.book() == snapshot.book()
    assert receiver.closed and receiver.received_bytes == 0
    assert 'Grüße' not in repr(receiver) and receiver.token not in repr(receiver)
    with pytest.raises(PermissionError): receiver.finish(receiver.token)


@pytest.mark.parametrize('gate', ['owner', 'source', 'writer', 'deadline'])
def test_changed_native_gates_fail_closed_and_wipe_partial_input(gate):
    receiver, state, owner, read, snapshot = transfer_fixture()
    receiver.append(receiver.token, 0, base64.b64encode(snapshot.text.encode()[:CHUNK_BYTES]).decode())
    if gate == 'owner': state['owner'] = False
    if gate == 'source': state['source'] = 'b' * 64
    if gate == 'writer': owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
    if gate == 'deadline': state['clock'] = 30
    with pytest.raises(PermissionError): receiver.finish(receiver.token)
    assert receiver.closed and receiver.received_bytes == 0


def test_foreign_token_cannot_abort_or_edit_the_legitimate_projection():
    receiver, state, owner, read, snapshot = transfer_fixture()
    first = base64.b64encode(snapshot.text.encode()[:CHUNK_BYTES]).decode()
    for method in (lambda: receiver.append('f' * 64, 0, first), lambda: receiver.finish('f' * 64)):
        with pytest.raises(PermissionError): method()
        assert not receiver.closed and receiver.received_bytes == 0
    upload(receiver, snapshot.text)
    assert receiver.finish(receiver.token) == snapshot


@pytest.mark.parametrize('gate', ['boolean-offset', 'wrong-offset', 'bad-base64', 'empty', 'oversize', 'overflow', 'incomplete', 'wrong-digest'])
def test_projection_input_is_strict_bounded_and_never_partially_reused(gate):
    receiver, state, owner, read, snapshot = transfer_fixture()
    if gate in ('incomplete', 'wrong-digest'):
        if gate == 'wrong-digest': upload(receiver, snapshot.text[:-1] + ' ')
        with pytest.raises(ValueError): receiver.finish(receiver.token)
    else:
        offset = True if gate == 'boolean-offset' else 1 if gate == 'wrong-offset' else 0
        raw = '!' if gate == 'bad-base64' else '' if gate == 'empty' else base64.b64encode(b'x' * (CHUNK_BYTES + 1 if gate == 'oversize' else 1)).decode()
        if gate == 'overflow':
            upload(receiver, snapshot.text); offset = receiver.received_bytes
        with pytest.raises(ValueError): receiver.append(receiver.token, offset, raw)
    assert receiver.closed and receiver.received_bytes == 0


@pytest.mark.parametrize('text', ['[]', '{"a":1,"a":2}', '{"invalid":NaN}', '{"not":"canonical", "spacing":1}'])
def test_matching_bytehash_does_not_authorize_noncanonical_or_nonbook_content(text):
    _, _, _, read, _ = transfer_fixture()
    receiver = NativeBookProjection(read(), hashlib.sha256(text.encode()).hexdigest(), len(text), 'a' * 64,
        current_owner=lambda: True, current_source=lambda: 'a' * 64, current_saved_book=read)
    upload(receiver, text)
    with pytest.raises(ValueError): receiver.finish(receiver.token)
    assert receiver.closed and receiver.received_bytes == 0


def test_writer_change_after_append_or_finish_validation_is_rechecked():
    for finish in (False, True):
        receiver, state, owner, read, snapshot = transfer_fixture()
        if finish: upload(receiver, snapshot.text)
        calls = [0]
        def changed():
            calls[0] += 1
            if calls[0] == 2: owner.record_saved('native-producer-fixture', True, snapshot.saved_sha256)
            return read()
        receiver._current_saved = changed
        with pytest.raises(PermissionError):
            if finish: receiver.finish(receiver.token)
            else: receiver.append(receiver.token, 0, base64.b64encode(snapshot.text.encode()[:CHUNK_BYTES]).decode())
        assert receiver.closed and receiver.received_bytes == 0
