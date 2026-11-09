"""Real existing-key AEAD/SQLite/root descriptors; no product picker or SEND."""
from dataclasses import replace
from pathlib import Path
import os
import fcntl
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_media_source_roots import ProtectedMediaCollectionRoots, NativeMediaCollectionRootsWitness
from magnolie_file_transfer import TransferError
from magnolie_photo_preferences import ProtectedPhotoPreferences
from test_file_authenticated_desktop import native, bind


@pytest.fixture
def roots(native,tmp_path):
    service,peer,_=native;channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    clock=[100];store=ProtectedMediaCollectionRoots(authority,monotonic_ms=lambda:clock[0])
    path=tmp_path/'selected';path.mkdir(mode=0o700);(path/'one.jpg').write_bytes(b'actual original')
    selected=NativeCollectionRoot(path,lambda:True)
    try:yield service,authority,store,selected,clock
    finally:selected.close();store.close();authority.close()


def add(fixture,kind='images',expected=None):
    _,_,store,selected,_=fixture
    return store.add(store.issue_action(),expected or store.read(),selected,kind)


def cipher(store):return store._db.execute('SELECT payload FROM policy').fetchone()[0]


def test_passive_absence_then_native_selection_reopen_and_independent_phone_preferences(roots):
    service,authority,store,selected,_=roots
    directory=Path(service.store.root);before=set(directory.iterdir())
    absent=store.read();assert absent.roots==() and set(directory.iterdir())==before
    saved=add(roots);record=saved.roots[0]
    assert not saved.grants_send_authority and not record.grants_send_authority
    assert record.directory==selected._directory and record.key==selected.key and record.birthtime==selected.birthtime
    assert record.mount_id==selected.mount_id and record.pairing_epoch==authority.current_peer().pairing_epoch
    assert store.add(store.issue_action(),saved,selected,'images')==saved
    assert selected._directory.path.encode() not in cipher(store)
    assert b'actual original'==(Path(selected._directory.path)/'one.jpg').read_bytes()
    prefs=ProtectedPhotoPreferences(authority)
    try:
        assert prefs.read().policy is None
        assert not (directory/prefs._name).exists()
    finally:prefs.close()
    store.close();reopened=ProtectedMediaCollectionRoots(authority)
    try:
        assert reopened.read()==saved
        with reopened.open_root(record,lambda:True) as source:
            member=source.inventory().members[0]
            with source.open_member(member) as reader:assert reader.read_exact(0,15)==b'actual original'
        assert authority.current_peer() is not None
    finally:reopened.close()


def test_actions_cas_and_append_only_images_videos_keep_original_record(roots):
    _,_,store,selected,clock=roots
    absent=store.read();action=store.issue_action();saved=store.add(action,absent,selected,'images')
    for supplied,expected in [(action,saved),(store.issue_action(),absent),({'approved':True},saved)]:
        with pytest.raises(TransferError):store.add(supplied,expected,selected,'videos')
    expired=store.issue_action();clock[0]+=60001
    with pytest.raises(TransferError):store.add(expired,saved,selected,'videos')
    final=add(roots,'videos');assert final.roots[0]==saved.roots[0] and len(final.roots)==2
    assert len({r.id for r in final.roots})==2 and final.revision==saved.revision+1


def test_changed_native_generation_and_replaced_path_do_not_rebind_or_modify_history(roots):
    _,_,store,selected,_=roots;saved=add(roots);blob=cipher(store)
    record=saved.roots[0]
    with pytest.raises(TransferError):store.open_root(replace(record,birthtime=(record.birthtime[0]+1,record.birthtime[1])),lambda:True)
    path=Path(selected._directory.path);path.rename(path.with_name('old'));path.mkdir(mode=0o700)
    with NativeCollectionRoot(path,lambda:True) as replacement:
        with pytest.raises(TransferError):store.add(store.issue_action(),saved,replacement,'images')
    assert cipher(store)==blob and store.read()==saved
    with pytest.raises(TransferError):store.open_root(record,lambda:True)


def test_member_reader_is_retired_after_catalog_owner_close(roots):
    _,_,store,_,_=roots;saved=add(roots)
    with store.open_root(saved.roots[0],lambda:True) as source:
        with source.open_member(source.inventory().members[0]) as reader:
            store.close()
            with pytest.raises(TransferError):reader.read_exact(0,1)


@pytest.mark.parametrize('missing',['policy','owner','anchor','database','directory'])
def test_missing_catalog_parts_are_preserved_hold_and_never_reinitialized(roots,missing):
    service,authority,store,selected,_=roots;add(roots)
    parent=Path(service.store.root);folder=parent/store._name;anchor=parent/store._anchor
    if missing in ('policy','owner'):
        store._db.execute('DELETE FROM '+missing);store._db.commit()
    else:
        source={'anchor':anchor,'database':folder/'prefs.sqlite','directory':folder}[missing]
        source.rename(source.with_name(source.name+'.retained'))
    # Reopen with the same actual authenticated authority, not a fake key/store.
    store.close();fresh=ProtectedMediaCollectionRoots(authority)
    try:
        before=set(parent.iterdir())
        with pytest.raises((TransferError,OSError)):fresh.read()
        with pytest.raises((TransferError,OSError)):fresh.add(fresh.issue_action(),replace_saved_absent(fresh),selected,'images')
        assert set(parent.iterdir())==before
    finally:fresh.close()


def replace_saved_absent(store):
    from magnolie_media_source_roots import NativeMediaCollectionRootsSnapshot
    return NativeMediaCollectionRootsSnapshot(store._absent,1,())


def test_authenticated_malformed_root_and_membership_mismatch_are_not_repaired(roots):
    _,_,store,_,_=roots;saved=add(roots);original=cipher(store)
    head=store._db.execute('SELECT payload FROM owner').fetchone()[0]
    for mutate in [lambda value:value['roots'][0].update(mount_id=True),
                   lambda value:value['roots'][0].update(birthtime=[0,1_000_000_000]),
                   lambda value:value['roots'].append(dict(value['roots'][0])),
                   lambda value:value.update(roots=[])]:
        body=store._unprotect(original,'roots');mutate(body);blob=store._protect(body,'roots')
        from hashlib import sha256
        owner=store._protect(dict(revision=saved.revision,roots_sha256=sha256(blob).hexdigest()),'owner')
        store._db.execute('UPDATE policy SET payload=?',(blob,));store._db.execute('UPDATE owner SET payload=?',(owner,));store._db.commit()
        try:
            with pytest.raises(TransferError):store.read()
        finally:
            store._db.execute('UPDATE policy SET payload=?',(original,));store._db.execute('UPDATE owner SET payload=?',(head,));store._db.commit()
    assert store.read()==saved


def test_native_revocation_and_catalog_capacity_never_discard_selection(roots,monkeypatch):
    _,authority,store,selected,_=roots;saved=add(roots);blob=cipher(store)
    monkeypatch.setattr(store,'MAX_ROOTS',1)
    with pytest.raises(TransferError):store.add(store.issue_action(),saved,selected,'videos')
    assert cipher(store)==blob and store.read()==saved
    authority.revoke()
    with pytest.raises(TransferError):store.read()


def test_copied_cipher_anchor_cannot_replace_original_native_anchor_after_reopen(roots):
    service,authority,store,_,_=roots;saved=add(roots)
    anchor=Path(service.store.root)/store._anchor
    blob=anchor.read_bytes();anchor.rename(anchor.with_name(anchor.name+'.original'))
    fd=os.open(anchor,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:out.write(blob)
    store.close();fresh=ProtectedMediaCollectionRoots(authority)
    try:
        with pytest.raises(TransferError):fresh.read()
        assert anchor.read_bytes()==blob
    finally:fresh.close()


def test_actual_native_lock_busy_and_stale_second_owner_preserve_both_selections(roots):
    _,authority,store,selected,_=roots;saved=add(roots)
    other=ProtectedMediaCollectionRoots(authority)
    try:
        observed=other.read();assert observed==saved
        fcntl.flock(store._lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            with pytest.raises(TransferError,match='busy'):other.read()
        finally:fcntl.flock(store._lock_fd,fcntl.LOCK_UN)
        final=add(roots,'videos')
        with pytest.raises(TransferError,match='cas_conflict'):other.add(other.issue_action(),observed,selected,'images')
        assert other.read()==final and final.roots[0]==saved.roots[0]
    finally:other.close()


def test_pairing_epoch_change_preserves_old_selection_but_does_not_confer_open_or_rebind(roots):
    import magnolie_telefon as phone
    service,_,store,selected,_=roots;saved=add(roots)
    peer=service.store.peers[0];peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([8])*32)
    service.store.save_peers();channel,binding=bind(service,peer)
    authority=service.open_native_file_authority(peer['device_id'],peer['static_public'],channel,binding.generation)
    fresh=ProtectedMediaCollectionRoots(authority)
    try:
        assert fresh.read()==saved
        with pytest.raises(TransferError):fresh.open_root(saved.roots[0],lambda:True)
        with pytest.raises(TransferError):fresh.add(fresh.issue_action(),saved,selected,'images')
        assert fresh.read()==saved
    finally:fresh.close();authority.close()


def test_explicit_private_storage_or_broad_ancestor_selection_cannot_enter_catalog(roots):
    service,_,store,_,_=roots
    private=Path(service.store.root)
    for path in [private,private.parent]:
        # The actual native directory permissions must meet source prerequisites.
        with NativeCollectionRoot(path,lambda:True) as source:
            with pytest.raises(TransferError,match='private_storage_excluded'):
                store.add(store.issue_action(),store.read(),source,'images')
    assert store.read().roots==() and not (private/store._name).exists()


def test_same_native_root_at_changed_path_is_not_silently_reassociated(roots):
    _,_,store,selected,_=roots;saved=add(roots);blob=cipher(store)
    original=Path(selected._directory.path);moved=original.with_name('moved-selection');original.rename(moved)
    with NativeCollectionRoot(moved,lambda:True) as fresh:
        assert fresh.key==selected.key and fresh.birthtime==selected.birthtime
        with pytest.raises(TransferError,match='reassociation_required'):
            store.add(store.issue_action(),saved,fresh,'images')
    assert cipher(store)==blob and store.read()==saved


def test_authentication_failure_is_not_an_absent_root_catalog(roots):
    from cryptography.exceptions import InvalidTag
    _,_,store,_,_=roots;saved=add(roots);original=cipher(store)
    damaged=original[:-1]+bytes([original[-1]^1])
    store._db.execute('UPDATE policy SET payload=?',(damaged,));store._db.commit()
    with pytest.raises(InvalidTag):store.read()
    assert cipher(store)==damaged


@pytest.mark.parametrize('part',['prefs.lock','prefs.sqlite'])
def test_copied_native_store_entry_does_not_adopt_old_protected_selection(roots,part):
    service,authority,store,_,_=roots;add(roots)
    path=Path(service.store.root)/store._name/part
    store.close();raw=path.read_bytes();path.rename(path.with_name(part+'.retained'))
    # Keep the retained original outside the strict catalog directory so that
    # the intended inode-binding check, not unknown-entry rejection, is tested.
    path.with_name(part+'.retained').rename(path.parent.parent/(part+'.retained'))
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as out:out.write(raw)
    fresh=ProtectedMediaCollectionRoots(authority)
    try:
        with pytest.raises(TransferError):fresh.read()
        assert path.read_bytes()==raw
    finally:fresh.close()


def test_original_witness_survives_append_but_never_creates_absent_storage(roots):
    _,authority,store,_,_=roots
    with pytest.raises(TransferError):store.witness()
    saved=add(roots);witness=store.witness()
    assert not witness.grants_send_authority and NativeMediaCollectionRootsWitness.parse(witness.wire())==witness
    final=add(roots,'videos');assert store.witness()==witness
    bound=ProtectedMediaCollectionRoots(authority,original=witness)
    try:assert bound.read()==final and bound.witness()==witness
    finally:bound.close()


def test_supplied_original_witness_prevents_combined_catalog_and_anchor_reset(roots):
    service,authority,store,selected,_=roots;add(roots);witness=store.witness()
    store.close();parent=Path(service.store.root)
    for name in [store._name,store._anchor]:
        path=parent/name;path.rename(path.with_name(name+'.retained'))
    bound=ProtectedMediaCollectionRoots(authority,original=witness)
    try:
        before=set(parent.iterdir())
        with pytest.raises(TransferError):bound.read()
        with pytest.raises(TransferError):bound.add(bound.issue_action(),replace_saved_absent(bound),selected,'images')
        assert set(parent.iterdir())==before
    finally:bound.close()


def test_supplied_wrong_original_witness_never_adopts_existing_catalog(roots):
    _,authority,store,_,_=roots;saved=add(roots);witness=store.witness()
    for wrong in [replace(witness,anchor_sha256='f'*64),replace(witness,database_key=(witness.database_key[0],witness.database_key[1]+1))]:
        bound=ProtectedMediaCollectionRoots(authority,original=wrong)
        try:
            with pytest.raises(TransferError):bound.read()
            assert store.read()==saved
        finally:bound.close()
    with pytest.raises(TransferError):ProtectedMediaCollectionRoots(authority,original=replace(witness,scope='f'*64))
    for value in [dict(witness.wire(),format=True),dict(witness.wire(),anchor_key=[0,0]),dict(witness.wire(),unknown=True)]:
        with pytest.raises(TransferError):NativeMediaCollectionRootsWitness.parse(value)
