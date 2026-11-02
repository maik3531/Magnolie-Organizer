"""Bounded before/candidate upload pair, never writer or save authority."""
import base64
import copy
import hashlib
import json

import pytest
import magnolie_content_scope as scope
from magnolie_personal_actor_projection import NativeHistoricalPrepareProjection, MAX_BYTES, CHUNK_BYTES
from magnolie_personal_actor_restore_candidate import NativeHistoricalRestoreCandidateProof
from test_personal_actor_producer import native
from test_personal_actor_restore_candidate import gui_candidates


def receiver(fixture, candidate_text=None, candidate_data=None):
    snapshot = native(fixture['book'])[2]
    candidate = candidate_data if candidate_data is not None else (fixture['candidate_text'] if candidate_text is None else candidate_text).encode('utf-8')
    state = {'owner': True, 'source': 'a' * 64, 'saved': snapshot.saved_book, 'now': 1.0}
    value = NativeHistoricalPrepareProjection(snapshot.saved_book, snapshot.content_sha256, len(snapshot.text.encode()), hashlib.sha256(candidate).hexdigest(), len(candidate), state['source'],
        current_owner=lambda: state['owner'], current_source=lambda: state['source'], current_saved_book=lambda: state['saved'], clock=lambda: state['now'])
    return value, state, snapshot, candidate


def upload(value, channel, payload):
    for offset in range(0, len(payload), CHUNK_BYTES):
        raw = payload[offset:offset + CHUNK_BYTES]
        assert value.append(value.token, channel, offset, base64.b64encode(raw).decode()) == offset + len(raw)


def wiped(value):
    assert value.closed and value._before.closed and not value._candidate and not value._before._buffer


def test_actual_gui_before_and_exact_candidate_bytes_are_distinct_consumed_native_inputs(gui_candidates):
    for fixture in gui_candidates:
        text = '\n ' + fixture['candidate_text'] + '\n'  # Actual payload bytes, not a caller's canonical after hash.
        value, state, before, raw = receiver(fixture, text)
        upload(value, 'candidate', raw); upload(value, 'book', before.text.encode())
        snapshot, candidate = value.finish(value.token); wiped(value)
        assert snapshot.saved_book == before.saved_book and snapshot.book() == fixture['book'] and candidate == text
        manifest = scope.create(fixture['members']['notes'], fixture['members']['tasks'])
        proof = NativeHistoricalRestoreCandidateProof.prepare(fixture['peer'], fixture['run'], fixture['format'], [fixture['target']], [fixture['choice']], candidate,
            current_owner=lambda: state['owner'], current_source=lambda: state['source'], current_snapshot=lambda: snapshot,
            current_scope=lambda: manifest)
        assert proof.after_sha256 == hashlib.sha256(raw).hexdigest()
        assert 'Protected' not in repr(value) and 'data:' not in repr(value)
        with pytest.raises(PermissionError): value.finish(value.token)
        with pytest.raises(PermissionError): value.append(value.token, 'candidate', 0, 'e30=')


@pytest.mark.parametrize('fault', ['candidate-byte', 'before-byte', 'missing-candidate', 'offset', 'channel', 'owner', 'source', 'save', 'ttl', 'utf8'])
def test_projection_failure_closes_both_buffers_without_minting_a_restore_or_write(gui_candidates, fault):
    invalid = b'\xff' + gui_candidates[0]['candidate_text'].encode()[1:] if fault == 'utf8' else None
    value, state, before, raw = receiver(gui_candidates[0], candidate_data=invalid)
    if fault == 'candidate-byte': raw = b' ' + raw[1:]
    book = before.text.encode()
    if fault == 'before-byte': book = b' ' + book[1:]
    if fault not in ('offset', 'channel'):
        upload(value, 'book', book)
        if fault != 'missing-candidate': upload(value, 'candidate', raw)
    if fault == 'owner': state['owner'] = False
    if fault == 'source': state['source'] = 'b' * 64
    if fault == 'save': state['saved'] = dict(state['saved'], sequence=state['saved']['sequence'] + 1)
    if fault == 'ttl': state['now'] = 31.0
    with pytest.raises((PermissionError, ValueError, UnicodeError)):
        if fault == 'offset': value.append(value.token, 'candidate', 1, 'e30=')
        elif fault == 'channel': value.append(value.token, 'ordinary-data', 0, 'e30=')
        else: value.finish(value.token)
    wiped(value)


def test_foreign_and_nested_book_tokens_cannot_consume_or_abort_the_historical_pair(gui_candidates):
    value, state, before, raw = receiver(gui_candidates[0])
    upload(value, 'book', before.text.encode())
    counts = copy.deepcopy(value.received_bytes)
    for token in ('f' * 64, value._before.token):
        with pytest.raises(PermissionError): value.append(token, 'candidate', 0, 'e30=')
        with pytest.raises(PermissionError): value.finish(token)
        assert value.received_bytes == counts and not value.closed and not value._before.closed
    upload(value, 'candidate', raw); value.finish(value.token); wiped(value)


def test_candidate_transport_hash_alone_does_not_validate_its_json_or_exact_book_delta(gui_candidates):
    fixture = gui_candidates[0]
    changed = json.loads(fixture['candidate_text']); changed['einstellungen']['unrelated_change'] = True
    for text in ('{"book_persisted":true}', json.dumps(changed), fixture['candidate_text'][:-1] + ',"personalSync":{}}'):
        value, state, before, raw = receiver(fixture, text)
        upload(value, 'book', before.text.encode()); upload(value, 'candidate', raw)
        snapshot, candidate = value.finish(value.token); wiped(value)
        manifest = scope.create(fixture['members']['notes'], fixture['members']['tasks'])
        with pytest.raises((PermissionError, ValueError), match='candidate_delta_changed|duplicate_key'):
            NativeHistoricalRestoreCandidateProof.prepare(fixture['peer'], fixture['run'], fixture['format'], [fixture['target']], [fixture['choice']], candidate,
                current_owner=lambda: state['owner'], current_source=lambda: state['source'], current_snapshot=lambda: snapshot,
                current_scope=lambda: manifest)


@pytest.mark.parametrize('size', [True, 0, MAX_BYTES + 1])
def test_each_upload_side_is_bounded_before_allocating_a_buffer(gui_candidates, size):
    before = native(gui_candidates[0]['book'])[2]
    with pytest.raises(ValueError):
        NativeHistoricalPrepareProjection(before.saved_book, before.content_sha256, 2, 'a' * 64, size, 'b' * 64,
            current_owner=lambda: True, current_source=lambda: 'b' * 64, current_saved_book=lambda: before.saved_book)
