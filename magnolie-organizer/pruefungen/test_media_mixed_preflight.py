from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from magnolie_file_transfer import NativeTransferBinding, TransferError
from magnolie_media_mixed_preflight import MixedPcPassAdmission, PendingMixedPreflight, create_request, create_ready_result, require_ready_result, TTL_MS
from magnolie_media_sync import change, create


def _scope():
    a, b = str(uuid4()), str(uuid4())
    settings = create(a)
    for field, value in (('enabled', True), ('videos_enabled', True),
                         ('direction', 'pc_to_phone'), ('collection_mode', 'entire_collection')):
        settings = change(settings, a, b, field, value)
    binding = NativeTransferBinding(a,b,'a'*64,'b'*64,'c'*64,'0'*64)
    return a, b, settings, binding


def test_mixed_preflight_accepts_only_the_exact_original_request_and_controls():
    a, b, settings, binding = _scope()
    now = 90_000
    request = create_request(settings, binding, now)
    ready = create_ready_result(request, settings, binding, now+2)
    require_ready_result(ready, request, settings, binding, now+2)
    attempts = [
        (ready, create_request(settings, binding, now), settings, binding, now+2),
        (ready, request, change(settings,a,b,'auto_mode','wifi'), binding, now+2),
        (ready, request, settings, replace(binding, permission_epoch='d'*64), now+2),
        (ready, request, settings, replace(binding, receiver_identity_sha256='d'*64), now+2),
        (ready, request, settings, binding, now+TTL_MS),
        (dict(ready, created_ms=now-1), request, settings, binding, now+2),
        (dict(ready, expires_ms=ready['expires_ms']+1), request, settings, binding, now+2),
        (dict(ready, message_id=request['message_id']), request, settings, binding, now+2),
        (dict(ready, body=dict(ready['body'], photos=True)), request, settings, binding, now+2),
    ]
    for args in attempts:
        with pytest.raises(TransferError, match='media_mixed_preflight_invalid'):
            require_ready_result(*args)
    stale = deepcopy(request)
    stale['body']['binding_sha256'] = '0'*64
    with pytest.raises(TransferError, match='media_mixed_preflight_invalid'):
        create_ready_result(stale, settings, binding, now+2)


def test_mixed_ready_result_has_no_hello_clock_lead_or_deadline_extension():
    _, _, settings, binding = _scope()
    now = 90_000
    request = create_request(settings, binding, now)
    ready = create_ready_result(request, settings, binding, now+250)
    require_ready_result(ready, request, settings, binding, now+250)
    for reply, checked_at in ((ready, now+249),
                              (dict(ready, expires_ms=request['expires_ms']+1), now+250),
                              (ready, request['expires_ms'])):
        with pytest.raises(TransferError, match='media_mixed_preflight_invalid'):
            require_ready_result(reply, request, settings, binding, checked_at)


@pytest.mark.parametrize('field,value', [
    ('enabled',False), ('photos_enabled',False), ('videos_enabled',False),
    ('direction','two_way'), ('direction','phone_to_pc'),
    ('collection_mode','phone_inventory'), ('collection_mode','import_only'),
])
def test_mixed_preflight_is_not_a_fallback_for_other_scopes(field, value):
    a, b, settings, binding = _scope()
    with pytest.raises(TransferError, match='media_mixed_preflight_invalid'):
        create_request(change(settings,a,b,field,value), binding, 90_000)


@pytest.mark.parametrize('withdrawal', ['none', 'monotonic', 'settings-or-control'])
def test_pending_ticket_requires_actual_write_and_can_be_consumed_once(withdrawal):
    _, _, settings, binding = _scope()
    wall, tick, current = [90_000], [100], [True]
    ticket = PendingMixedPreflight(settings, binding, wall=lambda:wall[0],
                                   monotonic_ms=lambda:tick[0], current=lambda:current[0])
    request = ticket.request()
    ready = create_ready_result(request, settings, binding, wall[0])
    with pytest.raises(TransferError): ticket.observe(ready)
    ticket.mark_written()
    with pytest.raises(TransferError): ticket.consume()
    ticket.observe(ready)
    with pytest.raises(TransferError): ticket.observe(ready)
    if withdrawal == 'monotonic':
        tick[0] += TTL_MS
    elif withdrawal != 'none':
        current[0] = False
    if withdrawal == 'none':
        ticket.consume()
    with pytest.raises(TransferError): ticket.consume()


@pytest.mark.parametrize('change', ['expiry', 'withdrawal', 'clock_regression'])
def test_pass_admission_cannot_revive_after_loss(change):
    tick, current = [3], [True]
    owner, wrong = object(), object()
    pass_owner = MixedPcPassAdmission(object(),object(),object(),object(),deadline=6,
                                     clock=lambda:tick[0],current=lambda:current[0])
    with pytest.raises(TransferError):pass_owner.require_worker(owner)
    pass_owner.claim(owner)
    with pytest.raises(TransferError):pass_owner.require_worker(wrong)
    pass_owner.require_worker(owner)
    if change == 'withdrawal':current[0] = False
    else:tick[0] = 6 if change == 'expiry' else 2
    with pytest.raises(TransferError):pass_owner.require_worker(owner)
    tick[0],current[0]=4,True
    with pytest.raises(TransferError):pass_owner.claim(owner)


@pytest.mark.parametrize('mapped_kind', [None, 'images', 'video'])
def test_mixed_admission_pins_both_mapping_domains_before_any_source_work(mapped_kind):
    seen = []
    snapshot = object()
    class MappingReader:
        def candidate_page(self, kind, *, expected, limit):
            assert expected is (snapshot if seen else None) and limit == 1
            seen.append(kind)
            return snapshot, (object(),) if kind == mapped_kind else (), None
    owner = object()
    pass_owner = MixedPcPassAdmission(object(),object(),object(),object(),deadline=6,clock=lambda:3,current=lambda:True)
    pass_owner.claim(owner)
    if mapped_kind:
        with pytest.raises(TransferError,match='mapped_phone_update_unavailable'):
            pass_owner.require_unmapped_sources(owner,MappingReader())
        with pytest.raises(TransferError):pass_owner.require_worker(owner)
    else:
        assert pass_owner.require_unmapped_sources(owner,MappingReader()) is snapshot
    assert seen == (['images'] if mapped_kind == 'images' else ['images','video'])
