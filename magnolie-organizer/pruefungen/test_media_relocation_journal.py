"""Actual protected preparation store; no product rename or Saved update."""
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
import os
import sqlite3

import pytest

from test_media_relocation_record import ANIMATED, native_fixture
from test_file_desktop_receive import receiving
from test_file_authenticated_desktop import native, bind
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal, RelocationOwnerCheckpoint
from magnolie_media_relocation_owner import ProtectedRelocationOwner, RelocationOwnerIntent
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_media_retention import NativeMediaRetention, saved_book_retention
from magnolie_optional_phone import selected_modules
from magnolie_telefon import strict_json


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


def two_members(root,raw=b'original with local edits'):
    entry,destination,source,target,raw=native_fixture(root,raw)
    second=replace(entry,source='Camera/later.gif',target='Animationen/Camera/later.gif',original_mapping_sha256='2'*64)
    later=source.with_name('later.gif');later.write_bytes(raw);info=later.stat()
    second=replace(second,file=replace(entry.file,file_key=(info.st_dev,info.st_ino)))
    return bind_relocation_selection((entry,second),occupied=()),destination,source,target,raw


@pytest.fixture
def relocation_owner_case(receiving,tmp_path):
    records,destination,source,target,raw=two_members(tmp_path/'relocation')
    authority=receiving[3]._authority
    with NativeMediaRetention(authority.binding.native_directory) as book:
        version=book.saved_book_version()
    records=bind_relocation_selection(tuple(replace(r,book_sha256=version) for r in records),occupied=())
    return authority,records,destination,source,target,raw


@pytest.mark.parametrize('cut',['none','before_attempt_commit','after_attempt_commit'])
def test_first_folder_attempt_is_bound_once_without_creating_a_folder(relocation_owner_case,monkeypatch,cut):
    from magnolie_media_relocation_record import (MissingGifTargetDraft, bind_gif_relocation_folder_plan,
        inspect_relocation_target_parents)
    authority,records,destination,source,target,raw=relocation_owner_case
    target.parent.rmdir();target.parent.parent.rmdir()
    members=tuple(MissingGifTargetDraft(record.operation,record.book_sha256,record.preferences_sha256,
        record.original_mapping_sha256,destination,record.source,record.source_parents,record.target,
        inspect_relocation_target_parents(destination,record.target,lambda:True),record.file) for record in records)
    plan=bind_gif_relocation_folder_plan(members,destination)
    active=True;transactions=0
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        transaction=owner._transaction
        @contextmanager
        def cut_transaction():
            nonlocal active,transactions
            transactions+=1
            with transaction():
                yield
                if transactions==2 and cut=='before_attempt_commit':raise OSError('before attempted folder commit')
            if transactions==2 and cut=='after_attempt_commit':active=False
        monkeypatch.setattr(owner,'_transaction',cut_transaction)
        action=owner._issue_confirmed_action(lambda:active)
        if cut=='before_attempt_commit':
            with pytest.raises(OSError,match='before attempted folder commit'):
                owner._spend_first_folder_attempt(action,journal,plan,destination)
        elif cut=='after_attempt_commit':
            with pytest.raises(TransferError,match='native_guard_changed'):
                owner._spend_first_folder_attempt(action,journal,plan,destination)
        else:
            assert owner._spend_first_folder_attempt(action,journal,plan,destination).selection_sha256==plan.selection_sha256
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        intent=owner.read_folder_intent();assert intent.selection_sha256==plan.selection_sha256
        row=owner._db.execute('SELECT value FROM meta WHERE key=?',(owner._FOLDER_ATTEMPT_KEY,)).fetchone()
        if cut=='before_attempt_commit':assert row is None
        else:
            assert b'Animationen' not in row[0]
            stored=strict_json(owner._protection.unseal(row[0],owner._FOLDER_ATTEMPT_DOMAIN))
            assert stored['intent']==intent.wire() and stored['path']=='Animationen'
            assert stored['parents']==[list(destination.ancestor_keys[0])]
        with pytest.raises(TransferError,match='folder_plan_held'):
            owner._spend_first_folder_attempt(owner._issue_confirmed_action(lambda:True),journal,plan,destination)
        assert not journal.read().records
    assert source.read_bytes()==raw and not target.parent.parent.exists()


@pytest.mark.parametrize('fault',['none','late_occupant','after_create_before_result'])
def test_first_planned_folder_is_installed_no_replace_and_bound_to_its_inode(relocation_owner_case,monkeypatch,fault):
    from magnolie_media_relocation_record import (MissingGifTargetDraft, bind_gif_relocation_folder_plan,
        inspect_relocation_target_parents)
    from magnolie_media_trash import _move_no_replace
    from magnolie_photo_destination import media_path_is_excluded
    authority,records,destination,source,target,raw=relocation_owner_case
    folder=target.parent.parent;target.parent.rmdir();folder.rmdir()
    members=tuple(MissingGifTargetDraft(record.operation,record.book_sha256,record.preferences_sha256,
        record.original_mapping_sha256,destination,record.source,record.source_parents,record.target,
        inspect_relocation_target_parents(destination,record.target,lambda:True),record.file) for record in records)
    plan=bind_gif_relocation_folder_plan(members,destination)
    stage=folder.with_name('.magnolie-relocation-dir-'+members[0].operation)
    assert media_path_is_excluded(stage/'anything.gif')
    active=True;name_moves=[];foreign=[]
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        def rename(fd,old,new):
            nonlocal active
            assert stage.exists() and old==stage.name and new==folder.name
            assert owner._db.execute('SELECT 1 FROM meta WHERE key=?',(owner._FOLDER_ATTEMPT_KEY,)).fetchone()==(1,)
            assert not owner._db.in_transaction
            name_moves.append((stage.stat().st_dev,stage.stat().st_ino))
            if fault=='late_occupant':
                folder.mkdir(mode=0o700);foreign.append(folder.stat().st_ino)
            _move_no_replace(fd,old,new)
            if fault=='after_create_before_result':active=False
        monkeypatch.setattr('magnolie_media_trash._move_no_replace',rename)
        issued=owner._issue_confirmed_action(lambda:active)
        if fault=='late_occupant':
            with pytest.raises(FileExistsError):owner._create_first_confirmed_folder(issued,journal,plan,destination)
        elif fault=='after_create_before_result':
            with pytest.raises(TransferError,match='native_guard_changed'):
                owner._create_first_confirmed_folder(issued,journal,plan,destination)
        else:
            intent,identity=owner._create_first_confirmed_folder(issued,journal,plan,destination)
            assert identity==name_moves[0] and intent.selection_sha256==plan.selection_sha256
        assert not journal.read().records
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        result=owner._db.execute('SELECT value FROM meta WHERE key=?',(owner._FOLDER_RESULT_KEY,)).fetchone()
        if fault=='none':
            stored=strict_json(owner._protection.unseal(result[0],owner._FOLDER_RESULT_DOMAIN))
            assert stored['created']==list(name_moves[0]) and stored['attempt']['intent']==owner.read_folder_intent().wire()
        else:assert result is None
        with pytest.raises(TransferError,match='folder_plan_held|confirmation_changed'):
            owner._create_first_confirmed_folder(owner._issue_confirmed_action(lambda:True),journal,plan,destination)
        assert len(name_moves)==1
    assert source.read_bytes()==raw and not target.parent.exists()
    if fault=='late_occupant':assert folder.stat().st_ino==foreign[0] and stage.stat().st_ino==name_moves[0][1]
    else:assert folder.stat().st_ino==name_moves[0][1] and not stage.exists()


@pytest.mark.parametrize('interrupted',[False,True],ids=['shared_chain','replaced_parent'])
def test_planned_child_uses_the_original_parent_result_without_replay(relocation_owner_case,monkeypatch,interrupted):
    from magnolie_media_relocation_record import (MissingGifTargetDraft, bind_gif_relocation_folder_plan,
        inspect_relocation_target_parents)
    authority,records,destination,source,target,raw=relocation_owner_case
    folder=target.parent.parent;target.parent.rmdir();folder.rmdir()
    members=tuple(MissingGifTargetDraft(record.operation,record.book_sha256,record.preferences_sha256,
        record.original_mapping_sha256,destination,record.source,record.source_parents,record.target,
        inspect_relocation_target_parents(destination,record.target,lambda:True),record.file) for record in records)
    plan=bind_gif_relocation_folder_plan(members,destination)
    assert plan.missing_parents()==('Animationen','Animationen/Camera')
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        if interrupted:
            bind=owner._bind_folder_attempt
            def replace_before_child(intent,root,path,parent_keys,ordinal,lease,committed):
                if ordinal==1:
                    folder.rename(folder.with_name('independent-fixture-parent'))
                    folder.mkdir(mode=0o700)
                return bind(intent,root,path,parent_keys,ordinal,lease,committed)
            monkeypatch.setattr(owner,'_bind_folder_attempt',replace_before_child)
            with pytest.raises(TransferError,match='confirmation_changed'):
                owner._create_confirmed_folders(owner._issue_confirmed_action(lambda:True),journal,plan,destination)
            assert not target.parent.exists() and not list(folder.iterdir())
        else:
            intent,created=owner._create_confirmed_folders(owner._issue_confirmed_action(lambda:True),journal,plan,destination)
            assert intent.selection_sha256==plan.selection_sha256 and tuple(path for path,_ in created)==plan.missing_parents()
            assert target.parent.stat().st_ino==created[1][1][1] and not list(target.parent.iterdir())
        assert not journal.read().records
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        first,=owner._db.execute('SELECT value FROM meta WHERE key=?',(owner._FOLDER_RESULT_KEY,)).fetchone()
        child=owner._db.execute('SELECT value FROM meta WHERE key=?',(owner._FOLDER_RESULT_KEY+':1',)).fetchone()
        first_result=strict_json(owner._protection.unseal(first,owner._FOLDER_RESULT_DOMAIN))
        if interrupted:assert child is None
        else:
            result=strict_json(owner._protection.unseal(child[0],owner._FOLDER_RESULT_DOMAIN))
            assert result['attempt']['parents'][-1]==first_result['created']
        with pytest.raises(TransferError,match='folder_plan_held|confirmation_changed'):
            owner._create_confirmed_folders(owner._issue_confirmed_action(lambda:True),journal,plan,destination)
    assert source.read_bytes()==raw and not target.exists()


@pytest.mark.parametrize('edited',[False,True],ids=['original','edit_after_folder_creation'])
def test_completed_folder_plan_materializes_only_unchanged_original_endpoints(receiving,tmp_path,monkeypatch,edited):
    from magnolie_media_relocation_record import (MissingGifTargetDraft, _materialize_gif_folder_plan,
        bind_gif_relocation_folder_plan, inspect_relocation_target_parents)
    authority=receiving[3]._authority
    records,destination,source,target,raw=two_members(tmp_path/'relocation',ANIMATED)
    target.parent.rmdir();target.parent.parent.rmdir()
    with NativeMediaRetention(authority.binding.native_directory) as book:
        version=book.saved_book_version()
    members=tuple(MissingGifTargetDraft(record.operation,version,record.preferences_sha256,
        record.original_mapping_sha256,destination,record.source,record.source_parents,record.target,
        inspect_relocation_target_parents(destination,record.target,lambda:True),record.file) for record in records)
    plan=bind_gif_relocation_folder_plan(members,destination)
    def materialize(confirmed,root,created,current):
        if edited:source.write_bytes(b'concurrent local edit')
        return _materialize_gif_folder_plan(confirmed,root,created,current)
    monkeypatch.setattr('magnolie_media_relocation_record._materialize_gif_folder_plan',materialize)
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        action=owner._issue_confirmed_action(lambda:True)
        if edited:
            with pytest.raises(TransferError,match='original_file_changed'):
                owner._materialize_confirmed_folder_selection(action,journal,plan,destination)
        else:
            intent,materialized=owner._materialize_confirmed_folder_selection(action,journal,plan,destination)
            assert intent.selection_sha256==plan.selection_sha256 and len(materialized)==2
            folders=(destination.ancestor_keys[0],(target.parent.parent.stat().st_dev,target.parent.parent.stat().st_ino),
                (target.parent.stat().st_dev,target.parent.stat().st_ino))
            assert all(record.target_parents==folders and not record.grants_write_authority for record in materialized)
            assert tuple(record.file for record in materialized)==tuple(member.file for member in members)
        assert not journal.read().records and not list(target.parent.iterdir())
    assert source.read_bytes()==(b'concurrent local edit' if edited else raw)


def test_confirmed_intent_is_independent_of_the_journal_and_survives_reopen(relocation_owner_case):
    authority,records,destination,source,target,raw=relocation_owner_case
    selection=records[0].selection_sha256
    expected=RelocationOwnerIntent.for_selection(records,destination)
    assert RelocationOwnerIntent.parse(expected.wire())==expected
    assert expected.mappings==tuple(sorted(r.original_mapping_sha256 for r in records))
    with closing(ProtectedRelocationOwner(authority)) as owner:
        assert owner.read_intent() is None
        with pytest.raises(TransferError,match='confirmation_changed'):
            owner.record_confirmed_intent(owner._issue_confirmed_action(lambda:True),records,destination,'f'*64)
        assert owner.read_intent() is None
        ticket=owner._issue_confirmed_action(lambda:True)
        assert owner.record_confirmed_intent(ticket,records,destination,selection)==expected
        with pytest.raises(TransferError,match='action_not_current'):
            owner.record_confirmed_intent(ticket,records,destination,selection)
    with closing(ProtectedMediaRelocationJournal(authority)) as absent_journal:
        assert not absent_journal.read().records
    with closing(ProtectedRelocationOwner(authority)) as reopened:
        assert reopened.require_intent(expected)
        with pytest.raises(TransferError,match='owner_already_recorded'):
            reopened.record_confirmed_intent(reopened._issue_confirmed_action(lambda:True),records,destination,selection)
        assert reopened.require_intent(expected)
        blob,=reopened._db.execute('SELECT value FROM meta WHERE key=?',(reopened._INTENT_KEY,)).fetchone()
        assert selection.encode() not in blob and str(source).encode() not in blob
    assert source.read_bytes()==raw and not target.exists()


def test_owner_intent_holds_busy_lane_withdrawn_confirmation_and_stale_book(relocation_owner_case):
    authority,records,destination,source,target,raw=relocation_owner_case
    directory=authority.binding.native_directory
    with closing(ProtectedRelocationOwner(authority)) as owner:
        def confirm(current):
            return owner.record_confirmed_intent(owner._issue_confirmed_action(current),records,destination,records[0].selection_sha256)
        with NativeMediaRetention(directory) as other, other.activity() as lease:
            assert lease is not None
            with pytest.raises(TransferError,match='activity_busy'):confirm(lambda:True)
        with pytest.raises(TransferError,match='native_guard_changed'):confirm(lambda:False)
        assert owner.read_intent() is None
        with saved_book_retention(directory,{'einstellungen':{'papierkorb':{'an':False,'tage':30}}}) as previous:pass
        assert not previous
        with pytest.raises(TransferError,match='original_book_changed'):confirm(lambda:True)
        assert owner.read_intent() is None
    assert source.read_bytes()==raw and not target.exists()


def test_owner_intent_fails_closed_after_row_loss(relocation_owner_case):
    authority,records,destination,source,target,raw=relocation_owner_case
    with closing(ProtectedRelocationOwner(authority)) as owner:
        expected=owner.record_confirmed_intent(owner._issue_confirmed_action(lambda:True),records,destination,records[0].selection_sha256)
        with closing(sqlite3.connect(owner._path)) as db, db:
            db.execute('DELETE FROM meta WHERE key=?',(owner._INTENT_KEY,))
        with pytest.raises(TransferError,match='original_owner_changed'):owner.require_intent(expected)
        with pytest.raises(TransferError,match='owner_held'):owner.read_intent()
    with closing(ProtectedRelocationOwner(authority)) as reopened:
        with pytest.raises(TransferError,match='original_owner_changed'):reopened.require_intent(expected)
    assert source.read_bytes()==raw and not target.exists()


def test_preparation_is_bound_to_original_owner_checkpoint_before_restart(relocation_owner_case):
    authority,records,destination,source,target,raw=relocation_owner_case
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        intent,witness=owner.prepare_original(owner._issue_confirmed_action(lambda:True),journal,records,destination,
            records[0].selection_sha256)
        prepared=journal.read()
        assert witness==RelocationOwnerCheckpoint.from_snapshot(prepared,destination)
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        def current():return owner.require_checkpoint(intent)==witness
        assert [v.state for v in journal.inspect_original_recovery(owner.require_checkpoint(intent),destination,
            require_original=current)]==['prepared_at_source','prepared_at_source']
        # The newer journal head must not adopt itself into the outer store.
        journal.record_terminal(journal.issue_action(),prepared,0,'canceled',destination,require_original=lambda:True)
        assert owner.require_checkpoint(intent)==witness
        with pytest.raises(TransferError,match='original_journal_changed'):
            journal.inspect_original_recovery(witness,destination,require_original=current)
    assert source.read_bytes()==raw and not target.exists()


def test_journal_committed_without_outer_checkpoint_cannot_be_adopted(relocation_owner_case,monkeypatch):
    authority,records,destination,source,target,raw=relocation_owner_case
    active=True
    intent=RelocationOwnerIntent.for_selection(records,destination)
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        original=journal.prepare
        def interrupt(*args,**kwargs):
            nonlocal active
            result=original(*args,**kwargs);active=False;return result
        monkeypatch.setattr(journal,'prepare',interrupt)
        with pytest.raises(TransferError,match='native_guard_changed'):
            owner.prepare_original(owner._issue_confirmed_action(lambda:active),journal,records,destination,intent.selection_sha256)
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        assert owner.require_intent(intent) and journal.read().records==records
        with pytest.raises(TransferError,match='original_checkpoint_required'):owner.require_checkpoint(intent)
        with pytest.raises(TransferError,match='original_checkpoint_required'):
            owner.inspect_bound_recovery(journal,destination,require_original=lambda:True)
        with pytest.raises(TransferError,match='owner_already_recorded'):
            owner.prepare_original(owner._issue_confirmed_action(lambda:True),journal,records,destination,intent.selection_sha256)
    assert source.read_bytes()==raw and not target.exists()


@pytest.mark.parametrize('cut',[None,'attempt','outcome','withdraw_after_attempt'])
def test_original_selection_pins_attempt_before_rename_and_outcome_after_sync(receiving,tmp_path,monkeypatch,cut):
    from magnolie_media_trash import _move_no_replace
    authority=receiving[3]._authority
    records,destination,source,target,raw=two_members(tmp_path/'relocation',ANIMATED)
    with NativeMediaRetention(authority.binding.native_directory) as book:
        version=book.saved_book_version()
    records=bind_relocation_selection(tuple(replace(r,book_sha256=version) for r in records),occupied=())
    intent=RelocationOwnerIntent.for_selection(records,destination)
    moves=[];expected=[];withdrawn=[]
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        advance=owner._advance_checkpoint
        def checkpoint(active,before,after,live):
            assert active==intent and owner.require_checkpoint(intent)==before
            step='attempt' if len(expected)%2==0 else 'outcome'
            if step==cut:raise OSError('fixture cut after journal '+step)
            advance(active,before,after,live);expected.append(after)
            if cut=='withdraw_after_attempt' and step=='attempt':withdrawn.append(True)
        def rename(*args,**kwargs):
            assert len(expected)==2*len(moves)+1 and owner.require_checkpoint(intent)==expected[-1]
            moves.append(True);return _move_no_replace(*args,**kwargs)
        monkeypatch.setattr(owner,'_advance_checkpoint',checkpoint)
        monkeypatch.setattr('magnolie_media_trash._move_no_replace',rename)
        action=owner._issue_confirmed_action(lambda:not withdrawn)
        if cut is None:
            assert owner._move_original_animation_selection(action,journal,records,destination,intent.selection_sha256)==(intent,expected[-1])
        elif cut=='withdraw_after_attempt':
            with pytest.raises(TransferError,match='native_guard_changed'):
                owner._move_original_animation_selection(action,journal,records,destination,intent.selection_sha256)
        else:
            with pytest.raises(OSError,match='fixture cut after journal '+cut):
                owner._move_original_animation_selection(action,journal,records,destination,intent.selection_sha256)
    with closing(ProtectedRelocationOwner(authority)) as owner, closing(ProtectedMediaRelocationJournal(authority)) as journal:
        before=journal.read();witness=owner.require_checkpoint(intent)
        def inspect():return owner.inspect_bound_recovery(journal,destination,require_original=lambda:True)
        with pytest.raises(TransferError,match='original_destination_required'):
            owner.inspect_bound_recovery(journal,type(destination).capture(target.parent),require_original=lambda:True)
        with pytest.raises(TransferError,match='original_owner_required'):
            owner.inspect_bound_recovery(journal,destination,require_original=lambda:False)
        if cut is None:
            assert [v.state for v in inspect()]==['moved','moved'] and len(moves)==2
            assert all((tmp_path/'relocation'/r.target).read_bytes()==raw for r in records)
        else:
            assert before.attempts==(0,) and len(before.outcomes)==(cut=='outcome')
            assert len(moves)==(cut=='outcome')
            if cut=='withdraw_after_attempt':
                assert [v.state for v in inspect()]==['held_spent_at_source','prepared_at_source']
            else:
                with pytest.raises(TransferError,match='original_journal_changed'):inspect()
        with pytest.raises(TransferError,match='owner_already_recorded'):
            owner._move_original_animation_selection(owner._issue_confirmed_action(lambda:True),journal,records,destination,intent.selection_sha256)
        assert journal.read()==before and owner.require_checkpoint(intent)==witness
    assert source.exists()==(cut in ('attempt','withdraw_after_attempt'))
    assert target.exists()==(cut in (None,'outcome'))


@pytest.mark.parametrize('cut',['before_commit','after_commit'])
def test_confirmation_cut_cannot_return_move_authority_or_bootstrap_journal(relocation_owner_case,monkeypatch,cut):
    authority,records,destination,source,target,raw=relocation_owner_case
    intent=RelocationOwnerIntent.for_selection(records,destination)
    active=True
    with closing(ProtectedRelocationOwner(authority)) as owner:
        if cut=='before_commit':
            seal=owner._protection.seal
            def interrupted_seal(*args):
                nonlocal active
                value=seal(*args);active=False;return value
            monkeypatch.setattr(owner._protection,'seal',interrupted_seal)
        else:
            original=owner._transaction
            @contextmanager
            def interrupted_transaction():
                nonlocal active
                with original():yield
                active=False
            monkeypatch.setattr(owner,'_transaction',interrupted_transaction)
        with pytest.raises(TransferError,match='native_guard_changed'):
            owner.record_confirmed_intent(owner._issue_confirmed_action(lambda:active),records,destination,intent.selection_sha256)
    with closing(ProtectedRelocationOwner(authority)) as reopened:
        if cut=='before_commit':assert reopened.read_intent() is None
        else:assert reopened.require_intent(intent)
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        assert not journal.read().records
    assert source.read_bytes()==raw and not target.exists()


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
        with pytest.raises(TransferError,match='original_anchor_required'):
            reopened.require_prepared(snapshot.version,revision)
    assert not journal_dir.exists() and preserved.is_dir()
    assert source.read_bytes()==raw and not target.exists()


def test_restart_inspection_needs_the_external_checkpoint_and_classifies_the_whole_selection(receiving,tmp_path):
    selection,destination,source,target,raw=two_members(tmp_path/'relocation')
    authority=receiving[3]._authority
    with NativeMediaRetention(authority.binding.native_directory) as book:
        selection=bind_relocation_selection(tuple(replace(r,book_sha256=book.saved_book_version()) for r in selection),occupied=())
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,selection[0].selection_sha256,
            destination,require_original=lambda:True)
        checkpoint=journal.record_terminal(journal.issue_action(),prepared,1,'canceled',destination,require_original=lambda:True)
        old_witness=RelocationOwnerCheckpoint.from_snapshot(prepared,destination)
        witness=RelocationOwnerCheckpoint.from_snapshot(checkpoint,destination)
        for malformed in (dict(witness.wire(),format=True),dict(witness.wire(),path=str(source)),
                dict(witness.wire(),prepared_version=None),{k:v for k,v in witness.wire().items() if k!='book_sha256'}):
            with pytest.raises(TransferError,match='invalid_owner_checkpoint'):
                RelocationOwnerCheckpoint.parse(malformed)
        directory=Path(journal._native_directory())
        store=directory/journal._name;anchor=directory/journal._anchor.name
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        def inspect(expected=RelocationOwnerCheckpoint.parse(witness.wire()),current=lambda:True):
            return reopened.inspect_original_recovery(expected,destination,require_original=current)
        with pytest.raises(TransferError,match='original_journal_changed'):inspect(old_witness)
        for field in ('selection_sha256','destination_sha256','prepared_version','outcome_version'):
            with pytest.raises(TransferError,match='original_journal_changed'):inspect(replace(witness,**{field:'f'*64}))
        with pytest.raises(TransferError,match='original_checkpoint_required'):inspect(checkpoint)
        with pytest.raises(TransferError,match='original_owner_ended'):inspect(current=lambda:False)
        observed=inspect()
        assert [(v.ordinal,v.state) for v in observed]==[(0,'prepared_at_source'),(1,'canceled')]
        assert not any(v.grants_write_authority for v in observed)
        with NativeMediaRetention(authority.binding.native_directory) as book:
            with book.activity(exclusive=True) as own:
                assert own is not None
                with pytest.raises(TransferError,match='activity_busy'):inspect()
        source.rename(target) # Unspent displacement is not a moved outcome.
        assert [v.state for v in inspect()]==['held','canceled']
        assert reopened.read()==checkpoint
    store.rename(store.with_name('preserved-journal'))
    anchor.rename(anchor.with_suffix('.preserved'))
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        assert not reopened.read().records
        with pytest.raises(TransferError,match='original_journal_changed'):
            reopened.inspect_original_recovery(witness,destination,require_original=lambda:True)
    assert not store.exists() and not anchor.exists() and target.read_bytes()==raw and not source.exists()


def test_terminal_commit_keeps_the_original_preparation_and_rejects_replay(receiving,tmp_path):
    selection,destination,source,target,raw=two_members(tmp_path/'relocation')
    version=selection[0].selection_sha256;authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        with pytest.raises(TransferError,match='original_location_unproven'):
            journal.record_terminal(journal.issue_action(),prepared,0,'moved',destination,require_original=lambda:True)
        assert journal.read()==prepared
        source.rename(target)  # Simulate a process returning after the separately journaled rename.
        moved=journal.record_terminal(journal.issue_action(),prepared,0,'moved',destination,require_original=lambda:True)
        assert moved.version==prepared.version and moved.outcome_version!=prepared.outcome_version and moved.records==selection
        assert moved.outcomes==((0,replace(selection[0],phase='moved')),)
        with pytest.raises(TransferError,match='original_journal_changed'):
            journal.record_terminal(journal.issue_action(),prepared,1,'canceled',destination,require_original=lambda:True)
        with pytest.raises(TransferError,match='already_recorded'):
            journal.record_terminal(journal.issue_action(),moved,0,'moved',destination,require_original=lambda:True)
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        fresh=reopened.require_prepared(prepared.version,version)
        assert fresh==moved
        done=reopened.record_terminal(reopened.issue_action(),fresh,1,'canceled',destination,require_original=lambda:True)
        database=Path(reopened._native_directory())/reopened._name/'prefs.sqlite'
    assert done.outcomes==moved.outcomes+((1,replace(selection[1],phase='canceled')),)
    assert target.read_bytes()==source.with_name('later.gif').read_bytes()==raw and not source.exists()
    with closing(sqlite3.connect(database)) as db, db:db.execute('DELETE FROM outcomes WHERE ordinal=0')
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        with pytest.raises(TransferError,match='original_journal_changed'):reopened.read()


@pytest.mark.parametrize('fault',['database_rollback','before_database_commit','missing_anchor','truncated_anchor'])
def test_anchor_holds_a_changed_or_interrupted_independent_checkpoint(receiving,tmp_path,monkeypatch,fault):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=());revision=selection[0].selection_sha256
    authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        snapshot=journal.prepare(journal.issue_action(),journal.read(),selection,revision,
            destination,require_original=lambda:True)
        root=Path(journal._native_directory())
        db=root/journal._name/'prefs.sqlite';anchor=root/journal._anchor.name
        prepared_db=db.read_bytes();prepared_anchor=anchor.read_bytes()
        if fault in ('database_rollback','before_database_commit'):
            source.rename(target)
            if fault=='database_rollback':
                journal.record_terminal(journal.issue_action(),snapshot,0,'moved',destination,require_original=lambda:True)
            else:
                append=journal._anchor.append;advanced=[]
                def interrupted(*args):
                    append(*args);advanced.append(True)
                monkeypatch.setattr(journal._anchor,'append',interrupted)
                with pytest.raises(TransferError,match='original_owner_ended'):
                    journal.record_terminal(journal.issue_action(),snapshot,0,'moved',destination,require_original=lambda:not advanced)
                assert advanced and db.read_bytes()==prepared_db
            assert anchor.read_bytes().startswith(prepared_anchor) and anchor.read_bytes()!=prepared_anchor
    if fault=='database_rollback':db.write_bytes(prepared_db) # Keep the original database inode.
    elif fault=='missing_anchor':anchor.rename(anchor.with_suffix('.preserved'))
    elif fault=='truncated_anchor':anchor.write_bytes(prepared_anchor[:-1])
    expected={'missing_anchor':'original_anchor_required','truncated_anchor':'original_anchor_incomplete'}.get(fault,'anchor_journal_mismatch')
    with closing(ProtectedMediaRelocationJournal(authority)) as reopened:
        with pytest.raises(TransferError,match=expected):reopened.require_prepared(snapshot.version,revision)
    if fault in ('missing_anchor','truncated_anchor'):assert source.read_bytes()==raw and not target.exists()
    else:assert target.read_bytes()==raw and not source.exists()


def test_terminal_parent_sync_failure_keeps_the_original_outcome_pending(receiving,tmp_path,monkeypatch):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    authority=receiving[3]._authority
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        source.rename(target)
        fsync=os.fsync;parents=[]
        def fail_sync(fd):
            value=os.fstat(fd);key=value.st_dev,value.st_ino
            if key in (entry.source_parents[-1],entry.target_parents[-1]):
                parents.append(key)
                if key==entry.target_parents[-1]:raise OSError('fixture sync failure')
            return fsync(fd)
        with monkeypatch.context() as patch:
            patch.setattr(os,'fsync',fail_sync)
            with pytest.raises(OSError,match='fixture sync failure'):
                journal.record_terminal(journal.issue_action(),prepared,0,'moved',destination,require_original=lambda:True)
        assert parents==[entry.source_parents[-1],entry.target_parents[-1]]
        assert journal.require_prepared(prepared.version,version)==prepared
    assert target.read_bytes()==raw and not source.exists()


def test_terminal_target_replaced_during_directory_sync_is_not_credited(receiving,tmp_path,monkeypatch):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation')
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    with closing(ProtectedMediaRelocationJournal(receiving[3]._authority)) as journal:
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        source.rename(target)
        previous=target.with_name('preserved.gif');sync=os.fsync
        def replace_target(fd):
            sync(fd)
            info=os.fstat(fd)
            if (info.st_dev,info.st_ino)==entry.target_parents[-1]:
                target.rename(previous);target.write_bytes(raw)
        monkeypatch.setattr(os,'fsync',replace_target)
        with pytest.raises(TransferError,match='original_file_changed'):
            journal.record_terminal(journal.issue_action(),prepared,0,'moved',destination,require_original=lambda:True)
        assert journal.require_prepared(prepared.version,version)==prepared
    assert target.stat().st_ino!=entry.file.file_key[1] and previous.stat().st_ino==entry.file.file_key[1]
    assert target.read_bytes()==previous.read_bytes()==raw and not source.exists()


def test_relocation_modules_follow_the_existing_optional_photo_composition():
    modules={'magnolie_media_relocation_record.py','magnolie_media_relocation_journal.py','magnolie_media_relocation_anchor.py',
        'magnolie_media_relocation_owner.py'}
    assert not selected_modules(modules,dict(photo_sync=False,phone_camera=True))
    assert selected_modules(modules,dict(photo_sync=True,phone_camera=False))==modules


def test_native_animation_rename_preserves_inode_bytes_mode_and_mtime(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation',ANIMATED)
    authority=receiving[3]._authority;original=source.stat()
    with NativeMediaRetention(authority.binding.native_directory) as book:
        entry=replace(entry,book_sha256=book.saved_book_version())
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        expected=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        moved=journal.move_prepared_animation(journal.issue_action(),expected,0,destination,require_original=lambda:True)
        assert moved.attempts==(0,) and moved.outcomes==((0,replace(selection[0],phase='moved')),)
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        assert journal.require_prepared(expected.version,version)==moved
        observed,=journal.inspect_original_recovery(RelocationOwnerCheckpoint.from_snapshot(moved,destination),
            destination,require_original=lambda:True)
        assert observed.state=='moved' and not observed.grants_write_authority
        with pytest.raises(TransferError,match='already_recorded'):
            journal.move_prepared_animation(journal.issue_action(),moved,0,destination,require_original=lambda:True)
    current=target.stat()
    assert (current.st_dev,current.st_ino,current.st_mode,current.st_mtime_ns)==(original.st_dev,original.st_ino,original.st_mode,original.st_mtime_ns)
    assert target.read_bytes()==raw and not source.exists()


def test_native_move_does_not_spend_attempt_when_case_alias_already_occupies_target(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation',ANIMATED)
    authority=receiving[3]._authority
    with NativeMediaRetention(authority.binding.native_directory) as book:
        entry=replace(entry,book_sha256=book.saved_book_version())
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        prepared=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        alias=target.with_name(target.name.upper());alias.write_bytes(b'existing unrelated file')
        with pytest.raises(TransferError,match='target_alias_collision'):
            journal.move_prepared_animation(journal.issue_action(),prepared,0,destination,require_original=lambda:True)
        assert journal.read()==prepared and not prepared.attempts and not prepared.outcomes
    assert source.read_bytes()==raw and alias.read_bytes()==b'existing unrelated file' and not target.exists()


@pytest.mark.parametrize('fault',['late_collision','late_case_alias','revoked_after_spend','interrupted_after_rename'])
def test_spent_native_attempt_cannot_replay_after_failure_or_revocation(receiving,tmp_path,monkeypatch,fault):
    from magnolie_media_trash import _move_no_replace
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation',ANIMATED)
    authority=receiving[3]._authority
    with NativeMediaRetention(authority.binding.native_directory) as book:
        entry=replace(entry,book_sha256=book.saved_book_version())
    selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
    moves=[];withdrawn=[];checkpoints=[];alias=target.with_name(target.name.upper())
    def wrapped(*args,**kw):
        moves.append(True)
        if fault=='late_collision':target.write_bytes(b'foreign target')
        _move_no_replace(*args,**kw)
        if fault=='late_case_alias':alias.write_bytes(b'late unrelated file')
        if fault=='interrupted_after_rename':raise OSError('fixture interruption after atomic rename')
    with closing(ProtectedMediaRelocationJournal(authority)) as journal, monkeypatch.context() as patch:
        expected=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
        patch.setattr('magnolie_media_trash._move_no_replace',wrapped)
        append=journal._append_member
        def spend(*args):
            result=append(*args);checkpoints.append(RelocationOwnerCheckpoint.from_snapshot(result,destination))
            if fault=='revoked_after_spend':withdrawn.append(True)
            return result
        patch.setattr(journal,'_append_member',spend)
        error=TransferError if fault in ('revoked_after_spend','late_case_alias') else OSError
        with pytest.raises(error):
            journal.move_prepared_animation(journal.issue_action(),expected,0,destination,require_original=lambda:not withdrawn)
    with closing(ProtectedMediaRelocationJournal(authority)) as journal:
        checkpoint,=checkpoints # Captured before the interruption, not adopted on restart.
        held=journal.require_prepared(expected.version,version)
        assert RelocationOwnerCheckpoint.from_snapshot(held,destination)==checkpoint and held.attempts==(0,) and not held.outcomes
        observed,=journal.inspect_original_recovery(checkpoint,destination,require_original=lambda:True)
        assert observed.state=={'late_collision':'held','late_case_alias':'held','revoked_after_spend':'held_spent_at_source',
            'interrupted_after_rename':'held_spent_at_target'}[fault]
        assert not observed.grants_write_authority and journal.read()==held
        with pytest.raises(TransferError,match='attempt_already_spent'):
            journal.move_prepared_animation(journal.issue_action(),held,0,destination,require_original=lambda:True)
        if fault=='interrupted_after_rename':
            evidence=journal.record_terminal(journal.issue_action(),held,0,'moved',destination,require_original=lambda:True)
            assert evidence.outcomes==((0,replace(selection[0],phase='moved')),)
    assert len(moves)==(0 if fault=='revoked_after_spend' else 1)
    if fault in ('interrupted_after_rename','late_case_alias'):assert target.read_bytes()==raw and not source.exists()
    else:assert source.read_bytes()==raw
    if fault=='late_collision':assert target.read_bytes()==b'foreign target'
    if fault=='late_case_alias':assert alias.read_bytes()==b'late unrelated file'
    if fault=='revoked_after_spend':assert not target.exists()


def test_native_move_requires_original_saved_book_and_exclusive_media_lane(receiving,tmp_path):
    entry,destination,source,target,raw=native_fixture(tmp_path/'relocation',ANIMATED)
    authority=receiving[3]._authority;directory=authority.binding.native_directory
    with NativeMediaRetention(directory) as book:
        entry=replace(entry,book_sha256=book.saved_book_version())
        selection=bind_relocation_selection((entry,),occupied=());version=selection[0].selection_sha256
        with closing(ProtectedMediaRelocationJournal(authority)) as journal:
            prepared=journal.prepare(journal.issue_action(),journal.read(),selection,version,destination,require_original=lambda:True)
            with book.activity() as copy:
                assert copy is not None
                with pytest.raises(TransferError,match='media_activity_busy'):
                    journal.move_prepared_animation(journal.issue_action(),prepared,0,destination,require_original=lambda:True)
            with saved_book_retention(directory,{'einstellungen':{'papierkorb':{'an':True,'tage':0}}}) as saved:pass
            assert not saved
            with pytest.raises(TransferError,match='original_book_changed'):
                journal.inspect_original_recovery(RelocationOwnerCheckpoint.from_snapshot(prepared,destination),
                    destination,require_original=lambda:True)
            with pytest.raises(TransferError,match='original_book_changed'):
                journal.move_prepared_animation(journal.issue_action(),prepared,0,destination,require_original=lambda:True)
            assert journal.require_prepared(prepared.version,version)==prepared
    assert source.read_bytes()==raw and not target.exists()
