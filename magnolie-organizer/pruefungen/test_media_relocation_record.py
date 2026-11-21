"""#429: exact local recovery evidence, never an authorization to rename."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import os
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_acceptance import NativeAcceptedDestination
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import (MediaRelocationRecord, RelocationFileWitness,
    bind_relocation_selection, inspect_relocation_target_parents)


def record():
    return MediaRelocationRecord('1'*32,'a'*64,'b'*64,'c'*64,'d'*64,(1,1),((1,1),(1,2)),((1,1),(1,5),(1,3)),
        'Camera/clip.gif','Animationen/Camera/clip.gif',RelocationFileWitness((1,4),12,'e'*64))


def observations(entry,source,target,**changes):
    return dict(dict(root_key=entry.root_key,source_parents=entry.source_parents,
        target_parents=entry.target_parents,source=source,target=target),**changes)


def native_fixture(root,raw=b'original with local edits'):
    def identity(path):
        info=path.stat();return info.st_dev,info.st_ino
    root.mkdir(mode=0o700,exist_ok=True)
    entry=record();source=root/entry.source;target=root/entry.target
    source.parent.mkdir(mode=0o700)
    target.parent.parent.mkdir(mode=0o700)
    target.parent.mkdir(mode=0o700)
    source.write_bytes(raw)
    entry=replace(entry,root_key=identity(root),source_parents=(identity(root),identity(source.parent)),
        target_parents=(identity(root),identity(target.parent.parent),identity(target.parent)),
        file=RelocationFileWitness(identity(source),len(raw),sha256(raw).hexdigest()))
    return entry,NativeAcceptedDestination.capture(root),source,target,raw


def test_native_observes_exact_exclusive_inode_before_and_after_fixture_rename(tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    assert entry.observe_native(destination,lambda:True)=='at_source'
    source.rename(target)
    assert entry.observe_native(destination,lambda:True)=='at_target'
    assert target.read_bytes()==raw and not source.exists()
    target.write_bytes(b'?'*len(raw)) # Same inode/length is not the same bytes.
    assert entry.observe_native(destination,lambda:True)=='held'


GIF_HEADER=bytes.fromhex('47494638396101000100800000000000ffffff')
GIF_FRAME=bytes.fromhex('21f90400010000002c0000000001000100000202440100')
ANIMATED=GIF_HEADER+2*GIF_FRAME+b';'


def test_native_animation_proof_reads_the_exact_hashed_original(tmp_path):
    entry,destination,source,_,_=native_fixture(tmp_path,ANIMATED)
    assert entry.observe_native(destination,lambda:True,require_animation=True)=='at_source'
    source.write_bytes(GIF_HEADER+GIF_FRAME+GIF_FRAME.replace(b'\x44',b'\x4c')+b';')
    with pytest.raises(TransferError,match='animation_unproven'):
        entry.observe_native(destination,lambda:True,require_animation=True)


@pytest.mark.parametrize('raw',[GIF_HEADER+GIF_FRAME+b';',ANIMATED[:-1],ANIMATED+b'appendix',
    b'not an animation',GIF_HEADER+49*GIF_FRAME+b';',ANIMATED[:6]+b'\xff\xff'+ANIMATED[8:]])
def test_historical_animation_name_or_marker_does_not_replace_actual_frames(tmp_path,raw):
    entry,destination,source,target,_=native_fixture(tmp_path,raw)
    assert entry.observe_native(destination,lambda:True)=='at_source'
    with pytest.raises(TransferError,match='animation_unproven'):
        entry.observe_native(destination,lambda:True,require_animation=True)
    assert source.read_bytes()==raw and not target.exists()


@pytest.mark.parametrize('fault',['foreign_at_target','symlink','hardlink','changed_parent','changed_intermediate','writable_parent','missing_parent','revoked'])
def test_native_observation_never_confuses_unavailable_or_foreign_endpoint_with_absence(tmp_path,fault):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    current=lambda:True
    if fault=='foreign_at_target':target.write_bytes(raw)
    elif fault=='symlink':target.symlink_to(source)
    elif fault=='hardlink':target.hardlink_to(source)
    elif fault=='changed_parent':
        target.parent.rename(target.parent.with_name('original-parent'))
        target.parent.mkdir(mode=0o700)
    elif fault=='changed_intermediate':
        intermediate=target.parent.parent;old=intermediate.with_name('old-intermediate')
        intermediate.rename(old);intermediate.mkdir(mode=0o700)
        (old/target.parent.name).rename(target.parent) # The leaf parent inode is unchanged.
    elif fault=='missing_parent':target.parent.rmdir()
    elif fault=='writable_parent':target.parent.chmod(0o775)
    else:
        # First check succeeds, then withdraw before any endpoint can be credited.
        permitted=iter((True,False))
        current=lambda:next(permitted,False)
    with pytest.raises((OSError,TransferError)):
        entry.observe_native(destination,current)
    assert source.read_bytes()==raw


def test_native_rechecks_previously_absent_endpoint_and_parent_after_hashing(tmp_path,monkeypatch):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    original_read=os.read
    def read_and_replace_parent(fd,count):
        result=original_read(fd,count)
        if result and target.parent.exists():
            target.parent.rename(target.parent.with_name('old-target'))
            target.parent.mkdir(mode=0o700)
        return result
    monkeypatch.setattr(os,'read',read_and_replace_parent)
    with pytest.raises(TransferError,match='parent_changed'):
        entry.observe_native(destination,lambda:True)
    assert source.read_bytes()==raw and not target.exists()


@pytest.mark.parametrize('level',['leaf','album','group'])
def test_target_inventory_holds_case_equivalent_names_at_any_level(tmp_path,level):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    original={'leaf':target,'album':target.parent,'group':target.parent.parent}[level]
    alias=original.with_name(original.name.upper())
    alias.write_bytes(b'unrelated occupant')
    with pytest.raises(TransferError,match='target_alias_collision'):
        entry.observe_native(destination,lambda:True)
    assert source.read_bytes()==raw and alias.read_bytes()==b'unrelated occupant'
    assert not target.exists()


def test_target_inventory_rechecks_a_case_alias_created_during_hash(tmp_path,monkeypatch):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    alias=target.with_name(target.name.upper());original_read=os.read
    def read_then_add_alias(fd,count):
        part=original_read(fd,count)
        if part and not alias.exists():alias.write_bytes(b'concurrent sibling')
        return part
    monkeypatch.setattr(os,'read',read_then_add_alias)
    with pytest.raises(TransferError,match='target_alias_collision'):
        entry.observe_native(destination,lambda:True)
    assert source.read_bytes()==raw and alias.read_bytes()==b'concurrent sibling' and not target.exists()


def test_target_inventory_cap_is_not_a_proof_of_absence(tmp_path,monkeypatch):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    for name in ('other-a','other-b','other-c'):(target.parent/name).touch()
    monkeypatch.setattr('magnolie_media_relocation_record._MAX_DIRECTORY_ENTRIES',2)
    assert len(list(tmp_path.iterdir()))==2
    with pytest.raises(TransferError,match='target_inventory_unproven'):
        entry.observe_native(destination,lambda:True)
    assert source.read_bytes()==raw and not target.exists()


def test_missing_target_parents_report_existing_prefix_without_creating_directories(tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    target.parent.rmdir();target.parent.parent.rmdir()
    all_missing=inspect_relocation_target_parents(destination,entry.target,lambda:True)
    assert all_missing.existing==(entry.root_key,) and all_missing.missing==('Animationen','Camera')
    assert not target.parent.parent.exists()
    target.parent.parent.mkdir(mode=0o700)
    partial=inspect_relocation_target_parents(destination,entry.target,lambda:True)
    assert partial.existing[0]==entry.root_key and len(partial.existing)==2 and partial.missing==('Camera',)
    assert not target.parent.exists() and source.read_bytes()==raw
    target.parent.mkdir(mode=0o700)
    existing=inspect_relocation_target_parents(destination,entry.target,lambda:True)
    assert existing.existing[:2]==partial.existing and len(existing.existing)==3 and not existing.missing
    assert not target.exists() and source.read_bytes()==raw


@pytest.mark.parametrize('fault',['alias','symlink','unsafe_mode','late_parent','withdrawal'])
def test_target_parent_observation_holds_on_uncertainty(tmp_path,fault):
    entry,destination,source,target,raw=native_fixture(tmp_path)
    target.parent.rmdir();group=target.parent.parent;current=lambda:True
    if fault=='alias':(group/'camera').mkdir(mode=0o700)
    elif fault=='symlink':target.parent.symlink_to(source.parent,target_is_directory=True)
    elif fault=='unsafe_mode':
        target.parent.mkdir(mode=0o700);target.parent.chmod(0o775)
    else:
        calls=[]
        def current():
            calls.append(True)
            if fault=='late_parent' and len(calls)==4:target.parent.mkdir(mode=0o700)
            return fault!='withdrawal' or len(calls)<4
    expected={'alias':'target_alias_collision','unsafe_mode':'unsafe_parent','late_parent':'parent_changed',
        'withdrawal':'original_owner_ended'}
    if fault=='symlink':
        original=source.stat()
        with pytest.raises(OSError):inspect_relocation_target_parents(destination,entry.target,current)
        assert target.parent.is_symlink() and target.parent.readlink()==source.parent
        # Path.exists() follows the link and therefore sees the original; no
        # independent destination should appear behind that synthetic alias.
        assert target.samefile(source) and source.stat().st_ino==original.st_ino
        assert tuple(source.parent.iterdir())==(source,)
    else:
        with pytest.raises(TransferError,match=expected[fault]):inspect_relocation_target_parents(destination,entry.target,current)
        assert not target.exists()
    assert source.read_bytes()==raw


def test_strict_roundtrip_and_evidence_is_not_saved_or_authority():
    entry=record()
    assert MediaRelocationRecord.parse(entry.wire())==entry
    assert not entry.grants_write_authority and not entry.is_saved_receipt
    for change in ({'format':True},{'source':'../clip.gif'},{'target':'Animationen/renamed.gif'},
            {'source_parents':[[1,1],[2,1]]},{'target_parents':[[1,1],[1,5],[1,2]]},{'file_key':[1,True]},
            {'phase':'renamed'},{'sha256':'short'},{'remote_ack':True}):
        with pytest.raises(TransferError):MediaRelocationRecord.parse(dict(entry.wire(),**change))


@pytest.mark.parametrize('shape',[('none','none'),('same','same'),('same','foreign'),('foreign','same'),('none','edited')])
def test_absence_duplicate_replacement_or_content_change_is_held(shape):
    entry=record()
    witnesses={'none':None,'same':entry.file,'foreign':replace(entry.file,file_key=(1,8)),
        'edited':replace(entry.file,sha256='f'*64)}
    observed=observations(entry,*(witnesses[name] for name in shape))
    assert entry.observe(**observed)=='held'
    with pytest.raises(TransferError,match='location_unproven'):entry.terminal_candidate('moved',**observed)


@pytest.mark.parametrize('key',['root_key','source_parents','target_parents'])
def test_changed_root_or_parent_holds_even_with_exact_file(key):
    entry=record()
    assert entry.observe(**observations(entry,None,entry.file,**{key:(1,99)}))=='held'


def test_same_edited_inode_is_distinguished_on_both_sides_of_a_fixture_rename(tmp_path):
    def identity(path):
        stat=path.stat();return stat.st_dev,stat.st_ino
    def observe_file(path):
        if not path.exists():return None
        raw=path.read_bytes();return RelocationFileWitness(identity(path),len(raw),sha256(raw).hexdigest())
    entry,_,source,target,raw=native_fixture(tmp_path)
    initial=observations(entry,observe_file(source),observe_file(target))
    assert entry.observe(**initial)=='at_source'
    canceled=entry.terminal_candidate('canceled',**initial)
    assert canceled==replace(entry,phase='canceled') and source.read_bytes()==raw
    with pytest.raises(TransferError):entry.terminal_candidate('moved',**initial)
    # The fixture performs its own isolated rename; the codec never touches a file.
    os.rename(source,target)
    readback=observations(entry,observe_file(source),observe_file(target))
    assert entry.observe(**readback)=='at_target' and target.read_bytes()==raw
    moved=entry.terminal_candidate('moved',**readback)
    assert moved==replace(entry,phase='moved')
    assert MediaRelocationRecord.parse(moved.wire())==moved
    with pytest.raises(TransferError,match='invalid_transition'):moved.terminal_candidate('moved',**readback)
    assert not source.exists()


def second_record(first, **changes):
    defaults=dict(original_mapping_sha256='2'*64, source='Camera/other.gif',target='Animationen/Camera/other.gif',
        file=replace(first.file,file_key=(1,20)))
    return replace(first,**(defaults|changes))


def test_selection_binds_all_members_and_local_bytes_without_using_caller_order_or_hash():
    first=record();second=second_record(first)
    selection=bind_relocation_selection((second,first),occupied=('Camera/stay.gif',))
    assert bind_relocation_selection(selection,occupied=())==selection
    assert {item.selection_sha256 for item in selection}=={selection[0].selection_sha256}
    assert selection[0].selection_sha256 not in (first.selection_sha256,bind_relocation_selection((first,),occupied=())[0].selection_sha256)
    updated=replace(second,file=replace(second.file,sha256='3'*64))
    assert bind_relocation_selection((first,updated),occupied=())[0].selection_sha256!=selection[0].selection_sha256
    assert not any(item.grants_write_authority or item.is_saved_receipt for item in selection)


@pytest.mark.parametrize('occupied',[('animationen/camera/CLIP.gif',),('animationen/CAMERA',)])
def test_selection_never_targets_a_staying_file_or_its_descendant(occupied):
    with pytest.raises(TransferError,match='selection_collision'):
        bind_relocation_selection((record(),),occupied=occupied)


def test_selection_cannot_reuse_another_selected_sources_path_or_inode():
    first=record()
    second=second_record(first,source=first.target,target='Archive/clip.gif',source_parents=first.target_parents,
        target_parents=((1,1),(1,21)))
    with pytest.raises(TransferError,match='selection_collision'):bind_relocation_selection((first,second),occupied=())
    with pytest.raises(TransferError,match='duplicate_original'):
        bind_relocation_selection((first,second_record(first,file=first.file)),occupied=())


@pytest.mark.parametrize('change',[{'operation':'2'*32},{'book_sha256':'2'*64},{'preferences_sha256':'2'*64},{'phase':'moved'}])
def test_selection_cannot_rebind_a_foreign_or_terminal_member(change):
    first=record()
    with pytest.raises(TransferError):bind_relocation_selection((first,second_record(first,**change)),occupied=())
