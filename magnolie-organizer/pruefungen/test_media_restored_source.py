"""Fresh source READ from actual completed native new-inode restore lineage."""
from hashlib import sha256
import os
import types

import pytest

from test_media_source import source
from test_photo_mappings import mappings
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native
from test_media_source_backup import open_backup
from magnolie_media_backups import NativeMediaBackupLocations,NativeMediaBackupRestoreOwner
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_media_retention import NativeMediaRetention
from magnolie_file_transfer import TransferError
from magnolie_telefon import canonical


@pytest.fixture
def restored(source,tmp_path):
    h=source;scope=sha256(canonical(dict(subject=h.preferences._subject,media_type='images'))).hexdigest()
    directory=h.authority.binding.native_directory
    with open_backup(h) as backup:version=backup.save_from_mappings(h.mappings,h.association,h.record.protected_record_sha256)
    destination=tmp_path/'new-restore-destination';destination.mkdir(mode=0o700);target=NativeAcceptedDestination.capture(destination)
    owner=NativeMediaBackupRestoreOwner(directory,scope,lambda:True)
    try:
        with NativeMediaBackupLocations(directory,scope,lambda:True) as locations:
            locations.choose(locations.issue_action(),locations.read(),h.record.destination,None)
            result=owner.restore(owner.issue_action(),locations,h.record.destination,locations.source_id(h.record.destination),version,target)
        candidate=owner.source_candidate(result.operation)
        yield types.SimpleNamespace(h=h,owner=owner,result=result,candidate=candidate,path=destination/result.name,
            scope=scope,version=version,target=target,directory=directory)
    finally:owner.close()


def inspect(r,*,owner=None,operation=None,record=None):
    h=r.h
    return h.source.inspect_restored(h.preferences.issue_action(),h.policy,owner or r.owner,operation or r.result.operation,
        record or r.candidate.protected_record_sha256)


def test_completed_native_restoration_reads_new_owned_inode_and_later_edits_without_patching_original_saved_mapping(restored):
    r=restored;h=r.h;assert r.candidate.file_key!=h.record.file_key
    assert r.candidate.original_mapping==h.record and not r.candidate.grants_read_authority and not r.candidate.is_saved_receipt
    h.target.unlink();raw=b'fresh explicitly selected edited restored bytes';r.path.write_bytes(raw)
    observed=inspect(r)
    assert observed.file_key==r.candidate.file_key and observed.sha256==sha256(raw).hexdigest() and observed.size==len(raw)
    assert observed.original_reference==h.record.phone_original_reference() and r.owner.history()[0].original_mapping==h.record
    assert not observed.grants_read_authority and not observed.is_saved_receipt and not h.preferences.local_grant(True).grants.send_files
    assert r.path.read_bytes()==raw and not h.target.exists()


@pytest.mark.parametrize('change',['replacement','symlink','hardlink'])
def test_restored_source_uses_exact_new_native_inode_single_link_and_no_follow_not_only_saved_name(restored,change):
    r=restored;held=r.path.with_name('held-original-restore-fixture')
    if change=='hardlink':os.link(r.path,held)
    else:
        r.path.rename(held)
        if change=='replacement':r.path.write_bytes(b'hello')
        else:r.path.symlink_to(held)
    with pytest.raises((TransferError,OSError)):inspect(r)
    assert held.read_bytes()==b'hello' and r.path.read_bytes()==b'hello'


@pytest.mark.parametrize('change',['stale_record','foreign_scope','metadata_only'])
def test_restore_metadata_stale_selection_or_foreign_native_phone_scope_never_grants_source_read(restored,change,monkeypatch):
    r=restored;other=None
    monkeypatch.setattr(r.h.source,'_file',lambda *args:pytest.fail('Invalid restore proof reached file READ'))
    try:
        if change=='foreign_scope':
            other=NativeMediaBackupRestoreOwner(r.directory,'f'*64,lambda:True)
            with pytest.raises(TransferError,match='original_peer_scope_required'):inspect(r,owner=other)
        elif change=='metadata_only':
            with pytest.raises(TransferError,match='original_peer_scope_required'):inspect(r,owner=r.candidate)
        else:
            with pytest.raises(TransferError,match='source_selection_changed'):inspect(r,record='f'*64)
    finally:
        if other is not None:other.close()


def test_completed_restore_still_requires_current_positive_source_consent_and_current_saved_book(restored,monkeypatch):
    r=restored;h=r.h
    h.preferences.configure_sending(h.preferences.issue_action(),h.policy,photos=False,videos=False)
    monkeypatch.setattr(h.source,'_file',lambda *args:pytest.fail('Restore history bypassed native consent'))
    with pytest.raises(TransferError,match='local_consent_required'):inspect(r)
    assert r.path.read_bytes()==b'hello'


def test_book_pause_denies_completed_restore_source_before_read_without_changing_journal_or_file(restored,monkeypatch):
    r=restored;before=r.owner.history()
    with NativeMediaRetention(r.directory) as retention:retention.pause()
    monkeypatch.setattr(r.h.source,'_file',lambda *args:pytest.fail('Restore history bypassed saved book'))
    with pytest.raises(TransferError,match='saved_book_required'):inspect(r)
    assert r.owner.history()==before and r.path.read_bytes()==b'hello'


def test_prepared_restoration_never_becomes_a_source_candidate_even_under_current_positive_consent(restored):
    r=restored;h=r.h
    def stop(phase):
        if phase=='prepared':raise RuntimeError('explicit prepared-only restore')
    with NativeMediaBackupLocations(r.directory,r.scope,lambda:True) as locations:
        with NativeMediaBackupRestoreOwner(r.directory,r.scope,lambda:True,boundary=stop) as pending:
            with pytest.raises(RuntimeError,match='prepared-only'):
                pending.restore(pending.issue_action(),locations,h.record.destination,locations.source_id(h.record.destination),r.version,r.target)
            unfinished=next(item for item in pending.history() if item.state=='prepared')
            with pytest.raises(TransferError,match='completed_history_required'):pending.source_candidate(unfinished.operation)
            with pytest.raises(TransferError,match='completed_history_required'):
                inspect(r,owner=pending,operation=unfinished.operation,record='f'*64)
    assert r.path.read_bytes()==b'hello'
