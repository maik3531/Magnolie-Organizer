"""#429: native worker cancellation may only narrow actual source ownership."""
from pathlib import Path

import pytest

from test_media_source import source,native,receiving,mappings
from magnolie_file_transfer import TransferError


def plan(h,current):
    return h.source.plan(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256,native_current=current)


def freeze(h,selected,current):
    return h.source.freeze_observed(h.preferences.issue_action(),h.policy,h.association,h.record.protected_record_sha256,
        selected.observation,catalog_version=selected.catalog_version,native_current=current)


@pytest.mark.parametrize('current',[True,lambda:False,lambda:1])
def test_boolean_or_ended_operation_is_not_native_source_authority(source,monkeypatch,current):
    h=source;monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Ended operation opened a source'))
    with pytest.raises(TransferError,match='native_operation_'):plan(h,current)
    assert not h.source._prepared


def test_positive_callback_cannot_replace_independent_native_sending_consent(source,monkeypatch):
    h=source;h.policy=h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Callback replaced native consent'))
    with pytest.raises(TransferError,match='local_consent_required'):plan(h,lambda:True)
    assert not h.source._prepared


def test_stop_during_actual_plain_source_read_prevents_further_copy_and_preserves_partial_intent(source):
    h=source;selected=plan(h,lambda:True);live=[True]
    def boundary(phase):
        if phase=='source_chunk_read':live[0]=False
    h.source._boundary=boundary
    with pytest.raises(TransferError,match='native_operation_ended'):freeze(h,selected,lambda:live[0])
    assert h.target.read_bytes()==b'hello' and not h.source._prepared
    (stage,)=Path(h.authority.binding.native_directory).glob('.magnolie-source-*.part')
    assert {p.name for p in stage.iterdir()}=={'intent.enc','copying.enc'}
    assert h.preferences.read()==h.policy


@pytest.mark.parametrize('failure',['false','exception'])
def test_prepared_role_is_permanently_closed_after_operation_ends_even_if_callback_later_returns_true(source,failure):
    h=source;live=[True];calls=[]
    def current():
        calls.append(True)
        if live[0] is not True and failure=='exception':raise RuntimeError('synthetic native operation ended')
        return live[0]
    selected=plan(h,current);cached=freeze(h,selected,current)
    with h.source.prepared_cache(cached.manifest.source_id) as reader:assert reader.read_chunk(0)==b'hello'
    before={p.name:p.read_bytes() for p in cached.directory.iterdir()}
    prepared=h.source._prepared[cached.manifest.source_id];live[0]=False
    with pytest.raises((TransferError,RuntimeError)):prepared.permission()
    call_count=len(calls);live[0]=True
    with pytest.raises(TransferError,match='native_operation_ended'):prepared.permission()
    assert len(calls)==call_count and before=={p.name:p.read_bytes() for p in cached.directory.iterdir()}
