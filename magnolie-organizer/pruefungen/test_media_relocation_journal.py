"""Actual protected preparation store; no product rename or Saved update."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from test_media_relocation_record import native_fixture
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native, bind
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_optional_phone import selected_modules


def test_protected_selection_reopens_after_fixture_rename_without_restarting_or_updating_mapping(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    authority=receiving[3]._authority
    directory=tmp_path/'relocation'
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        initial=journal.read();assert not initial.records and not initial.associated
        assert sorted(directory.iterdir())==[directory/'Animationen',directory/'Camera']
        with pytest.raises(TransferError,match='confirmation_changed'):
            journal.prepare(journal.issue_action(),initial,selection,'f'*64,destination,require_original=lambda:True)
        assert journal.read()==initial
        saved=journal.prepare(journal.issue_action(),initial,selection,version,destination,require_original=lambda:True)
        assert saved.associated and saved.records==selection and saved.version!=initial.version
        assert source.read_bytes()==raw and not target.exists()
        assert selection[0].target.encode() not in (Path(journal._native_directory())/journal._name/'prefs.sqlite').read_bytes()
        with pytest.raises(TransferError,match='original_journal_changed'):
            journal.prepare(journal.issue_action(),initial,selection,version,destination,require_original=lambda:True)
        assert journal.read()==saved
    source.rename(target) # Isolated recovery fixture, not a product move.
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        assert reopened.require_prepared(saved.version,version)==saved
        with pytest.raises(TransferError,match='original_journal_changed'):
            reopened.require_prepared(saved.version,'f'*64)
        assert reopened.read().records[0].observe_native(destination,lambda:True)=='at_target'
        assert reopened.read()==saved and target.read_bytes()==raw and not source.exists()


def two_members(root):
    entry,destination,source,target,raw=native_fixture(root)
    second=replace(entry,source='Camera/later.gif',target='Animationen/Camera/later.gif',original_mapping_sha256='2'*64)
    later=source.with_name('later.gif');later.write_bytes(raw);info=later.stat()
    second=replace(second,file=replace(entry.file,file_key=(info.st_dev,info.st_ino)))
    return bind_relocation_selection((entry,second),occupied=()),destination,source,target,raw


def test_foreign_occupant_or_withdrawal_never_prepares_partial_journal(receiving,tmp_path):
    selection,destination,source,target,raw=two_members(tmp_path/'relocation');version=selection[0].selection_sha256
    occupied=target.with_name('later.gif');occupied.write_bytes(b'foreign')
    with closing(ProtectedMediaRelocationJournal(receiving[3]._authority)) as journal:
        initial=journal.read()
        with pytest.raises(TransferError,match='original_file_changed'):
            journal.prepare(journal.issue_action(),initial,selection,version,destination,require_original=lambda:True)
        assert journal.read()==initial and occupied.read_bytes()==b'foreign'
        with pytest.raises(TransferError,match='original_owner_ended'):
            journal.prepare(journal.issue_action(),initial,selection,version,destination,require_original=lambda:False)
        assert journal.read()==initial
    assert source.read_bytes()==source.with_name('later.gif').read_bytes()==raw and not target.exists()


def test_withdrawn_after_first_protected_member_write_rolls_back_the_whole_selection(receiving,tmp_path,monkeypatch):
    selection,destination,source,target,raw=two_members(tmp_path/'relocation')
    authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        protect=journal._protect;observed=[]
        def cut(payload,label):
            data=protect(payload,label)
            if label=='member/0':observed.append(label)
            return data
        monkeypatch.setattr(journal,'_protect',cut)
        with pytest.raises(TransferError,match='original_owner_ended'):
            journal.prepare(journal.issue_action(),journal.read(),selection,selection[0].selection_sha256,
                destination,require_original=lambda:not observed)
        assert observed==['member/0']
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        snapshot=reopened.read()
        assert snapshot.associated and not snapshot.records
    assert source.read_bytes()==source.with_name('later.gif').read_bytes()==raw and not target.exists()


def test_missing_operation_member_is_not_an_empty_journal_on_reopen(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=())
    authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        saved=journal.prepare(journal.issue_action(),journal.read(),selection,selection[0].selection_sha256,
            destination,require_original=lambda:True)
        database=journal._native_directory()+'/'+journal._name+'/prefs.sqlite'
        assert saved.records==selection
    with closing(sqlite3.connect(database)) as db, db:db.execute('DELETE FROM selection')
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        with pytest.raises(TransferError,match='original_journal_changed'):reopened.read()
    assert source.read_bytes()==raw and not target.exists()


def test_exact_checkpoint_holds_if_the_whole_journal_is_missing(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=());revision=selection[0].selection_sha256
    authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        snapshot=journal.prepare(journal.issue_action(),journal.read(),selection,revision,
            destination,require_original=lambda:True)
        journal_dir=Path(journal._native_directory())/journal._name
    preserved=journal_dir.with_name('preserved-fixture-journal');journal_dir.rename(preserved)
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        with pytest.raises(TransferError,match='original_journal_changed'):
            reopened.require_prepared(snapshot.version,revision)
    assert not journal_dir.exists() and preserved.is_dir()
    assert source.read_bytes()==raw and not target.exists()


def test_relocation_modules_follow_the_existing_optional_photo_composition():
    modules={'magnolie_media_relocation_record.py','magnolie_media_relocation_journal.py'}
    assert not selected_modules(modules,dict(photo_sync=False,phone_camera=True))
    assert selected_modules(modules,dict(photo_sync=True,phone_camera=False))==modules
