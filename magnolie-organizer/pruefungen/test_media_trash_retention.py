"""Authenticated local trash times; retention is not a deletion permission."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_trash import ProtectedMediaTrash,NativeMediaRetentionPermit
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings
from test_media_trash import trash,prepare,paths


def test_retention_uses_confirmed_local_trash_time_and_exact_configured_days(trash):
    _,_,_,_,owner=trash;clock=1_800_000_000_000
    owner._wall_clock_ms=lambda:clock
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    assert entry.changed_ms==clock and entry.trashed_ms is None and not entry.expired(7,clock+366*86400000)
    clock+=3600000
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert entry.trashed_ms==clock and payload.read_bytes()==b'hello' and not original.exists()
    for days in (7,30,90,365):
        assert not entry.expired(days,clock+days*86400000-1)
        assert entry.expired(days,clock+days*86400000)
    assert not entry.expired(0,253402300799999)
    assert not entry.expired(7,clock-1)
    assert owner.read()[1][0]==entry


def test_restoration_keeps_original_trash_time_but_is_never_expired(trash):
    _,_,_,_,owner=trash;clock=1_800_000_000_000
    owner._wall_clock_ms=lambda:clock
    snapshot,entry=prepare(trash)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    deleted=entry.trashed_ms
    clock-=86400000 # Clock rollback cannot reset the retained operation time.
    snapshot,entry=owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
    assert entry.state=='restored' and entry.trashed_ms==entry.changed_ms==deleted
    assert not entry.expired(7,253402300799999)


def test_legacy_authenticated_undated_history_is_not_guessed_from_file_dates(trash):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    # Reconstruct only this owned fixture's authentic legacy-v1 payload shape.
    with owner._db:
        for sequence,blob in owner._db.execute('SELECT sequence,payload FROM events').fetchall():
            value=owner._unprotect(blob,'event/'+str(sequence));value.pop('changed_ms')
            owner._db.execute('UPDATE events SET payload=? WHERE sequence=?',(owner._protect(value,'event/'+str(sequence)),sequence))
        entries,total,digest=owner._entries()
        head=dict(revision=total+1,count=len(entries),events=total,events_sha256=digest,pairing_epoch=owner._peer().pairing_epoch)
        owner._db.execute('UPDATE owner SET payload=?',(owner._protect(head,'owner'),))
    owner.close();reopened=ProtectedMediaTrash(fixture[3]._authority)
    try:
        legacy=reopened.read()[1][0]
        assert legacy.trashed_ms is None and legacy.changed_ms is None
        assert not legacy.expired(7,253402300799999) and payload.read_bytes()==b'hello' and not original.exists()
    finally:reopened.close()


def test_invalid_retention_or_clock_never_changes_existing_payload(trash):
    _,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    for days in (True,-1,1,14,'30',None):
        with pytest.raises(TransferError,match='invalid_retention'):entry.expired(days,1_800_000_000_000)
    for now in (True,-1,253402300800000,'now',None):
        with pytest.raises(TransferError,match='invalid_clock'):entry.expired(30,now)
    assert payload.read_bytes()==b'hello' and not original.exists() and owner.read()==(snapshot,(entry,))


def aged(trash):
    owner=trash[4];clock=[1_800_000_000_000];owner._wall_clock_ms=lambda:clock[0]
    snapshot,entry=prepare(trash)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    clock[0]+=7*86400000
    return owner,snapshot,entry,clock


def test_expired_original_bytes_are_released_but_tombstone_and_new_user_file_survive(trash):
    owner,snapshot,entry,_=aged(trash);original,payload=paths(trash,entry)
    original.write_bytes(b'new user file');original.chmod(0o600)
    permit=NativeMediaRetentionPermit(7,lambda:7)
    snapshot,entry=owner.purge_expired(owner.issue_action(),snapshot,entry.operation,permit)
    assert entry.state=='purged' and not payload.exists() and original.read_bytes()==b'new user file'
    marker=original.parent/entry.purge.name/'payload'
    assert marker.stat().st_size==0 and (marker.stat().st_dev,marker.stat().st_ino)==entry.mapping.file_key
    assert owner.read()==(snapshot,(entry,)) and owner._db.execute('SELECT count(*) FROM events').fetchone()==(4,)
    assert not entry.is_counterpart_ack and not entry.grants_write_authority
    with pytest.raises(TransferError):owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)


def test_never_or_not_yet_due_never_prepares_or_releases_bytes(trash,monkeypatch):
    owner,snapshot,entry,clock=aged(trash);original,payload=paths(trash,entry)
    before=set(original.parent.iterdir())
    monkeypatch.setattr('magnolie_media_trash.os.ftruncate',lambda *args:pytest.fail('No expiry consent for byte release'))
    assert owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(0,lambda:0))==(snapshot,entry)
    clock[0]-=1
    assert owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))==(snapshot,entry)
    assert set(original.parent.iterdir())==before and payload.read_bytes()==b'hello'


@pytest.mark.parametrize('phase',['purge_prepared','purge_moved','purge_bytes_released'])
def test_purge_restart_keeps_exact_original_and_finishes_only_witnessed_operation(trash,phase):
    owner,snapshot,entry,clock=aged(trash);original,payload=paths(trash,entry)
    class Interrupted(Exception):pass
    def stop(at):
        if at==phase:raise Interrupted()
    owner._boundary=stop
    with pytest.raises(Interrupted):owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
    owner.close();reopened=ProtectedMediaTrash(trash[0][3]._authority,wall_clock_ms=lambda:clock[0])
    try:
        current,entries=reopened.read();assert entries[0].state=='purge_prepared'
        current,done=reopened.purge_expired(reopened.issue_action(),current,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
        assert done.state=='purged' and not original.exists() and not payload.exists()
        assert (original.parent/done.purge.name/'payload').stat().st_size==0
    finally:reopened.close()


def test_policy_revocation_holds_full_payload_and_old_permit_cannot_revive(trash):
    owner,snapshot,entry,_=aged(trash);original,payload=paths(trash,entry);days=[7]
    permit=NativeMediaRetentionPermit(7,lambda:days[0])
    def revoke(at):
        if at=='before_purge_bytes':days[0]=0
    owner._boundary=revoke
    with pytest.raises(TransferError,match='retention_changed'):owner.purge_expired(owner.issue_action(),snapshot,entry.operation,permit)
    current,entries=owner.read();entry=entries[0];marker=original.parent/entry.purge.name/'payload'
    assert entry.state=='purge_prepared' and marker.read_bytes()==b'hello' and not original.exists()
    owner._boundary=lambda _:None
    assert owner.purge_expired(owner.issue_action(),current,entry.operation,NativeMediaRetentionPermit(0,lambda:0))==(current,entry)
    days[0]=7
    with pytest.raises(TransferError,match='retention_changed'):owner.purge_expired(owner.issue_action(),current,entry.operation,permit)
    current,entry=owner.restore(owner.issue_action(),current,entry.operation,lambda:True)
    assert entry.state=='restored' and original.read_bytes()==b'hello' and not payload.exists()


def test_restore_after_purge_prepare_preempts_old_expiry_without_extra_history_slots(trash):
    owner,snapshot,entry,_=aged(trash);original,payload=paths(trash,entry)
    class Interrupted(Exception):pass
    def stop(at):
        if at=='purge_moved':raise Interrupted()
    owner._boundary=stop
    with pytest.raises(Interrupted):owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
    owner._boundary=lambda _:None;current,_=owner.read()
    current,entry=owner.restore(owner.issue_action(),current,entry.operation,lambda:True)
    assert original.read_bytes()==b'hello' and entry.state=='restored' and not payload.exists()
    assert owner._db.execute('SELECT count(*) FROM events').fetchone()==(4,)
    with pytest.raises(TransferError,match='purge_not_current'):
        owner.purge_expired(owner.issue_action(),current,entry.operation,NativeMediaRetentionPermit(7,lambda:7))


def test_purge_never_releases_a_hardlinked_or_raced_replacement_file(trash,monkeypatch):
    import os
    owner,snapshot,entry,_=aged(trash);original,payload=paths(trash,entry)
    link=original.parent/'explicit-fixture-hardlink';os.link(payload,link)
    monkeypatch.setattr('magnolie_media_trash.os.ftruncate',lambda *args:pytest.fail('Changed data must not be released'))
    with pytest.raises(TransferError,match='original_file_changed'):
        owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
    assert payload.read_bytes()==link.read_bytes()==b'hello' and owner.read()==(snapshot,(entry,))
    link.unlink() # Only this fixture's explicit extra hardlink, never product cleanup.
    def race(at):
        if at=='before_purge_bytes':
            directory=original.parent/('.magnolie-purge-'+entry.operation)
            (directory/'payload').rename(directory/'keep-original')
            (directory/'payload').write_bytes(b'user replacement');(directory/'payload').chmod(0o600)
    owner._boundary=race
    with pytest.raises(TransferError):
        owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
    directory=original.parent/('.magnolie-purge-'+entry.operation)
    assert (directory/'keep-original').read_bytes()==b'hello' and (directory/'payload').read_bytes()==b'user replacement'


def test_wire_retention_and_completed_old_operation_cannot_authorize_purge(trash):
    owner,snapshot,entry,_=aged(trash);original,payload=paths(trash,entry)
    with pytest.raises(TransferError,match='native_retention_required'):
        owner.purge_expired(owner.issue_action(),snapshot,entry.operation,{'days':7,'enabled':True})
    assert payload.read_bytes()==b'hello' and not original.exists()
    snapshot,entry=owner.restore(owner.issue_action(),snapshot,entry.operation,lambda:True)
    with pytest.raises(TransferError,match='purge_not_current'):
        owner.purge_expired(owner.issue_action(),snapshot,entry.operation,NativeMediaRetentionPermit(7,lambda:7))
    assert original.read_bytes()==b'hello' and not payload.exists()
