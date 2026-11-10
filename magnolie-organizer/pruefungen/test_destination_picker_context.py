"""#499: actual native picker/Unix IPC/protected preference lifetime, no GTK install."""
import pytest
from types import SimpleNamespace
import time
import threading
import json
import os
import sqlite3
from pathlib import Path
from test_file_authenticated_desktop import bind
from test_file_desktop_receive import negotiate
from test_file_video_authority import ack_all
from test_media_source_pc import pc, source, mappings
from test_media_source_connection import composition, agree

from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving
from test_video_destination_ui import prepare_choice, native_picker, saved_book_inputs
from magnolie_photo_destination_choice import NativeDestinationFolderChoice
from magnolie_media_source_choice import native_folder_witness
from magnolie_media_source_collection import NativeCollectionRoot
from magnolie_file_transfer import TransferError
from magnolie_media_retention import NativeMediaRetention
import magnolie_hintergrund as background


@pytest.mark.parametrize('photos', [False, True])
def test_original_picker_cannot_apply_returned_path_after_protected_intent_changes(receiving, tmp_path, monkeypatch, photos):
    prepare_choice(receiving, monkeypatch)
    connection = receiving[3]
    session = connection.desktop_session()
    if photos:
        session._local_enabled(False)
    before = connection._preferences.read()
    target = tmp_path / ('Late-Photo-Choice' if photos else 'Late-Video-Choice')
    target.mkdir(mode=0o700)
    changed = []

    def change_original_intent_while_dialog_open(window):
        preferences = connection._preferences
        changed.append(preferences.configure_sending(preferences.issue_action(), preferences.read(), photos=True, videos=False))
        return str(target)

    with native_picker(receiving, tmp_path, change_original_intent_while_dialog_open, photos=photos) as (_, invoke, calls, answers):
        invoke()
        assert session.join(20)
        assert len(calls) == 1 and len(changed) == 1
        after = connection._preferences.read()
        original_destination = before.policy.destination if photos else (before.policy.videos.destination if before.policy.videos is not None else None)
        current_destination = after.policy.destination if photos else (after.policy.videos.destination if after.policy.videos is not None else None)
        assert current_destination == original_destination, 'Late native callback adopted a path into a different protected intent'
        assert after.policy.sending.photos is True, 'Independent newly saved SEND choice must not be rolled back'
        assert answers[-1][1]['ok'] is False
    assert not list(target.iterdir())


@pytest.mark.parametrize('change', ['missing_hash', 'forged_hash', 'missing_witness', 'forged_witness', 'paused', 'stale_file'])
def test_prepare_requires_actual_saved_plaintext_hash_and_original_book_file(receiving, tmp_path, change):
    service, _, _, connection = receiving[:4]
    connection.desktop_session()._local_enabled(False)
    before=connection._preferences.read()
    inputs=saved_book_inputs(connection)
    if change=='missing_hash':inputs['book_version']=None
    elif change=='forged_hash':inputs['book_version']='0'*64
    elif change=='missing_witness':inputs['book_witness']=None
    elif change=='forged_witness':inputs['book_witness'][1]+=1
    elif change=='paused':
        with NativeMediaRetention(service.store.root) as book:book.pause()
    elif change=='stale_file':
        (tmp_path/'daten.json').write_text('{"changed":true}')
    with pytest.raises(TransferError):
        connection.native_destination_choice('prepare',kind='images',**inputs)
    assert connection._native_destination_choice is None
    assert connection._preferences.read()==before


@pytest.mark.parametrize('phase', ['prepare','commit','cancel'])
def test_ipc_book_inputs_are_required_only_for_prepare(phase):
    fields=dict(peer_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',fingerprint='AAAA-BBBB-CCCC-DDDD',
        destination_action=phase,media_type='images',selection=None if phase=='prepare' else 'a'*64,
        path='/native/path' if phase=='commit' else None,witness={} if phase=='commit' else None,
        book_version='b'*64 if phase=='prepare' else None,book_witness=[1]*9 if phase=='prepare' else None)
    background._request_shape('phone_photo_sync_destination_choice',fields)
    if phase=='prepare':fields['book_witness']=None
    else:fields['book_version']='b'*64
    with pytest.raises(background.IPCError):background._request_shape('phone_photo_sync_destination_choice',fields)


@pytest.mark.parametrize('photos',[False,True])
def test_cancel_during_native_preference_preparation_retires_original_commit(receiving,tmp_path,monkeypatch,photos):
    prepare_choice(receiving,monkeypatch)
    connection=receiving[3]
    if photos:connection.desktop_session()._local_enabled(False)
    before=connection._preferences.read()
    target=tmp_path/'Cancelled-Original-Write';target.mkdir(mode=0o700)
    original=connection._preferences._protect;owners=[]
    def protect(value,purpose):
        result=original(value,purpose)
        if purpose=='policy' and not owners:
            owner=connection._native_destination_choice;owners.append(owner)
            assert owner._committing
            connection.native_destination_choice('cancel',kind=owner.kind,selection=owner.selection)
            assert owner.closed.is_set() and owner.book_fd is None and owner.meta_fd is None
            assert connection._native_destination_choice is owner,'Committing slot must stay held until IO drains'
        return result
    monkeypatch.setattr(connection._preferences,'_protect',protect)
    with native_picker(receiving,tmp_path,str(target),photos=photos) as (_,invoke,_,answers):
        invoke();assert owners and answers[-1][1]['ok'] is False
    assert connection._native_destination_choice is None
    assert connection._preferences.read()==before and not list(target.iterdir())


def test_destination_lease_expiry_releases_only_original_owned_descriptors(receiving):
    connection=receiving[3]
    connection.desktop_session()._local_enabled(False)
    inputs=saved_book_inputs(connection)
    first=connection.native_destination_choice('prepare',kind='images',**inputs)
    original=connection._native_destination_choice
    original.issued-=61
    second=connection.native_destination_choice('prepare',kind='images',**inputs)
    current=connection._native_destination_choice
    assert original.closed.is_set() and original.book_fd is None and original.meta_fd is None
    assert second['selection']!=first['selection']
    with pytest.raises(TransferError):connection.native_destination_choice('cancel',kind='images',selection=first['selection'])
    assert connection._native_destination_choice is current and not current.closed.is_set()
    connection.native_destination_choice('cancel',kind='images',selection=second['selection'])
    assert current.closed.is_set() and current.book_fd is None and current.meta_fd is None


def test_native_preference_denial_callback_is_sticky_after_owner_returns(receiving):
    preferences=receiving[3]._preferences;live=[True]
    action=preferences.issue_action(_native_current=lambda:live[0]);action.consume(preferences)
    live[0]=False
    with pytest.raises(TransferError):action.validate(preferences)
    live[0]=True
    with pytest.raises(TransferError):action.validate(preferences)


def test_source_picker_can_retire_expired_destination_but_not_a_live_original_lease(pc,native):
    from test_media_source_choice import prepare
    with composition(pc,native[0]) as h:
        agree(h,native[0])
        connection=h.connection
        inputs=saved_book_inputs(connection)
        page=connection.native_destination_choice('prepare',kind='images',**inputs)
        owner=connection._native_destination_choice
        with pytest.raises(TransferError):prepare(h)
        assert connection._native_destination_choice is owner and not owner.closed.is_set()
        owner.issued-=61
        selection=prepare(h)
        assert owner.closed.is_set() and owner.book_fd is None and owner.meta_fd is None
        assert connection._native_destination_choice is None
        connection.native_collection_choice('cancel',kind='images',selection=selection['selection'])


@pytest.mark.parametrize('photos', [False, True])
@pytest.mark.parametrize('change', ['book', 'save_pause', 'saved_ack', 'proxy', 'expiry', 'control'])
def test_native_dialog_context_change_rejects_late_path_and_releases_original_lease(receiving, tmp_path, monkeypatch, photos, change):
    prepare_choice(receiving, monkeypatch)
    service, peer, channel, connection = receiving[:4]
    if photos: connection.desktop_session()._local_enabled(False)
    before = connection._preferences.read()
    target = tmp_path / 'Late-Native-Path'; target.mkdir(mode=0o700)
    owners = []; now = [time.monotonic()]
    def selected(window):
        owners.append(connection._native_destination_choice)
        assert owners[-1] is not None
        if change == 'book':
            (tmp_path / 'daten.json').write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":7}}}')
        elif change == 'save_pause':
            with NativeMediaRetention(service.store.root) as saved: saved.pause()
        elif change == 'saved_ack': window._telefon_actor_buchnachweis = lambda: None
        elif change == 'proxy': window._telefon = background.PhoneServiceProxy(window._telefon.path)
        elif change == 'expiry': now[0] += 61
        elif change == 'control':
            from test_file_desktop_receive import negotiate
            negotiate(service, peer, channel, connection, receive_enabled=not photos)
        return str(target)
    with native_picker(receiving, tmp_path, selected, photos=photos, clock=SimpleNamespace(monotonic=lambda: now[0])) as (_, invoke, calls, answers):
        invoke()
        assert len(calls) == 1 and answers[-1][1]['ok'] is False
    assert connection._preferences.read() == before and not list(target.iterdir())
    assert owners[0].closed.is_set() and owners[0].book_fd is None
    assert connection._native_destination_choice is None


@pytest.mark.parametrize('photos', [False, True])
def test_native_original_book_is_rechecked_at_actual_preference_write_boundary(receiving, tmp_path, monkeypatch, photos):
    prepare_choice(receiving, monkeypatch)
    connection = receiving[3]
    if photos: connection.desktop_session()._local_enabled(False)
    before = connection._preferences.read()
    target = tmp_path / 'Before-Native-Write'; target.mkdir(mode=0o700)
    original = connection._preferences._protect
    hit = []
    def protect(value, purpose):
        encrypted = original(value, purpose)
        if purpose == 'policy' and not hit:
            hit.append(True)
            (tmp_path / 'daten.json').write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":30}}}')
        return encrypted
    monkeypatch.setattr(connection._preferences, '_protect', protect)
    with native_picker(receiving, tmp_path, str(target), photos=photos) as (_, invoke, _, answers):
        invoke()
        assert hit and answers[-1][1]['ok'] is False
    assert connection._preferences.read() == before and not list(target.iterdir())


@pytest.mark.parametrize('photos', [False, True])
@pytest.mark.parametrize('change', ['wrong_witness', 'recreated'])
def test_context_owner_never_reopens_a_substituted_selected_directory(receiving, tmp_path, monkeypatch, photos, change):
    prepare_choice(receiving, monkeypatch)
    connection = receiving[3]
    if photos: connection.desktop_session()._local_enabled(False)
    before = connection._preferences.read()
    owner = NativeDestinationFolderChoice(connection, 'images' if photos else 'video', **saved_book_inputs(connection))
    target = tmp_path / 'Original-Native-Directory'; target.mkdir(mode=0o700)
    try:
        with NativeCollectionRoot(str(target), lambda: True) as held:
            witness = native_folder_witness(held)
            if change == 'wrong_witness': witness = {'approved': True}
            else:
                target.rename(tmp_path / 'Keep-Original-Directory')
                target.mkdir(mode=0o700)
            with pytest.raises(TransferError): owner.commit(str(target), witness)
    finally: owner.close()
    assert connection._preferences.read() == before and not list(target.iterdir())


@pytest.mark.parametrize('photos', [False, True])
def test_reconnected_channel_cannot_adopt_old_dialog_but_fresh_explicit_choice_works(receiving, tmp_path, monkeypatch, photos):
    prepare_choice(receiving, monkeypatch)
    service, peer, old_channel, old_connection, destination = receiving
    if photos: old_connection.desktop_session()._local_enabled(False)
    before = old_connection._preferences.read(); replacement = []
    late = tmp_path / 'Old-Channel-Path'; late.mkdir(mode=0o700)
    fresh = tmp_path / 'New-Explicit-Path'; fresh.mkdir(mode=0o700)
    owners = []
    def reconnect(window):
        owners.append(old_connection._native_destination_choice)
        service._end_native_file_connection(old_channel)
        channel, binding = bind(service, peer)
        connection = service.open_native_file_connection(peer['device_id'], peer['static_public'], channel, binding.generation)
        replacement.append((service, peer, channel, connection, destination))
        negotiate(service, peer, channel, connection, receive_enabled=not photos)
        ack_all(service,peer,channel)
        return str(late)
    try:
        with native_picker(receiving, tmp_path, reconnect, photos=photos) as (_, invoke, _, answers):
            invoke(); assert answers[-1][1]['ok'] is False
        current = replacement[0]
        assert current[3]._preferences.read() == before and not list(late.iterdir())
        assert owners[0].closed.is_set() and owners[0].book_fd is None
        with native_picker(current, tmp_path, str(fresh), photos=photos) as (_, invoke, _, answers):
            invoke(); assert answers[-1][1]['ok'] is True
        after = current[3]._preferences.read()
        assert (after.policy.destination if photos else after.policy.videos.destination).path == str(fresh)
    finally:
        if replacement: service._end_native_file_connection(replacement[0][2])


@pytest.mark.parametrize('receiving', [False], indirect=True)
def test_destination_metadata_preserves_pc_send_without_phone_read_receive_or_source_runtime(receiving, tmp_path, monkeypatch):
    service, peer, channel, connection, _ = receiving
    monkeypatch.setattr(service,'_resume_automatic_photos',lambda *args:None)
    ack_all(service,peer,channel)
    connection.desktop_session()._local_enabled(False)
    preferences = connection._preferences
    before = preferences.configure_sending(preferences.issue_action(), preferences.read(), photos=True, videos=False)
    assert connection._controls._remote.grants.send_files is False
    assert connection._controls._sent_grants.receive_files is False
    assert 23 not in peer['capabilities']['items']['device_status']['versions']
    target = tmp_path / 'Independent-Receive-Metadata'; target.mkdir(mode=0o700)
    sent = channel.send.call_count
    with native_picker(receiving, tmp_path, str(target), photos=True) as (_, invoke, _, answers):
        invoke(); assert answers[-1][1]['ok'] is True
    after = preferences.read()
    assert after.policy.sending == before.policy.sending and after.policy.sending.photos is True
    assert not after.policy.enabled and after.policy.destination.path == str(target)
    assert channel.send.call_count == sent and not list(target.iterdir())


@pytest.mark.parametrize('change', ['legacy', 'path_on_prepare', 'approval', 'missing_witness', 'wrong_token', 'cancel_path'])
def test_private_ipc_refuses_legacy_unowned_paths_and_malformed_choice_fields(change):
    fields = dict(peer_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', fingerprint='AAAA-BBBB-CCCC-DDDD',
        destination_action='prepare', media_type='images', selection=None, path=None, witness=None,
        book_version='b'*64,book_witness=[1]*9)
    operation = 'phone_photo_sync_destination_choice'
    background._request_shape(operation,fields)
    if change == 'legacy':
        operation='phone_photo_sync_photo_destination'; fields=dict(peer_id=fields['peer_id'],fingerprint=fields['fingerprint'],path='/unowned/path')
    elif change == 'path_on_prepare': fields['path']='/unowned/path'
    elif change == 'approval': fields['approved']=True
    elif change == 'missing_witness': fields.update(destination_action='commit',selection='a'*64,path='/unowned/path',book_version=None,book_witness=None)
    elif change == 'wrong_token': fields.update(destination_action='cancel',selection='a'*63,book_version=None,book_witness=None)
    elif change == 'cancel_path': fields.update(destination_action='cancel',selection='a'*64,path='/unowned/path',book_version=None,book_witness=None)
    with pytest.raises(background.IPCError): background._request_shape(operation,fields)


@pytest.mark.parametrize('photos', [False, True])
def test_native_destination_metadata_does_not_require_trash_or_a_deletion_permit(receiving, tmp_path, monkeypatch, photos):
    prepare_choice(receiving, monkeypatch)
    service, _, _, connection = receiving[:4]
    if photos: connection.desktop_session()._local_enabled(False)
    book = {'einstellungen': {'papierkorb': {'an': False, 'tage': 0}}}
    (tmp_path / 'daten.json').write_text(json.dumps(book))
    with NativeMediaRetention(service.store.root) as policy:
        token = policy.pause(); policy.publish_saved(token, book)
        assert policy._read()['days'] == 0
    monkeypatch.setattr(NativeMediaRetention, 'permit', lambda *args, **kwargs: pytest.fail('Destination borrowed a deletion permit'))
    monkeypatch.setattr(NativeMediaRetention, 'active_copy_permit', lambda *args, **kwargs: pytest.fail('Destination borrowed a copy/data permit'))
    target = tmp_path / 'Without-Trash-Permission'; target.mkdir(mode=0o700)
    with native_picker(receiving, tmp_path, str(target), photos=photos) as (_, invoke, _, answers):
        invoke(); assert answers[-1][1]['ok'] is True
    after = connection._preferences.read()
    assert (after.policy.destination if photos else after.policy.videos.destination).path == str(target)
    assert not list(target.iterdir())


@pytest.mark.parametrize('photos', [False, True])
def test_native_saved_book_pause_is_serialized_after_destination_metadata_commit(receiving, tmp_path, monkeypatch, photos):
    prepare_choice(receiving, monkeypatch)
    service, _, _, connection = receiving[:4]
    if photos: connection.desktop_session()._local_enabled(False)
    target = tmp_path / 'Serialized-Native-Choice'; target.mkdir(mode=0o700)
    attempting = threading.Event(); paused = threading.Event(); errors = []; workers = []
    original = connection._preferences._protect
    def pause():
        try:
            with NativeMediaRetention(service.store.root) as book:
                attempting.set(); book.pause(); paused.set()
        except BaseException as error: errors.append(error)
    def protect(value, purpose):
        encrypted = original(value, purpose)
        if purpose == 'policy' and not workers:
            worker = threading.Thread(target=pause); workers.append(worker); worker.start()
            assert attempting.wait(2)
            assert not paused.wait(.05), 'Native saved-book publisher crossed an in-flight destination writer'
        return encrypted
    monkeypatch.setattr(connection._preferences, '_protect', protect)
    try:
        with native_picker(receiving, tmp_path, str(target), photos=photos) as (_, invoke, _, answers):
            invoke(); assert answers[-1][1]['ok'] is True
        assert workers and paused.wait(5) and not errors
        after = connection._preferences.read()
        assert (after.policy.destination if photos else after.policy.videos.destination).path == str(target)
    finally:
        for worker in workers:
            worker.join(6); assert not worker.is_alive()


@pytest.mark.parametrize('change', ['resealed_head', 'copied_database'])
def test_context_owner_retains_actual_metadata_database_and_raw_authenticated_head(receiving, tmp_path, change):
    service, _, _, connection = receiving[:4]
    connection.desktop_session()._local_enabled(False)
    before = connection._preferences.read()
    owner = NativeDestinationFolderChoice(connection, 'images', **saved_book_inputs(connection))
    target = tmp_path / 'Exact-Native-Head'; target.mkdir(mode=0o700)
    try:
        with NativeCollectionRoot(str(target), lambda: True) as selected:
            witness = native_folder_witness(selected)
            with NativeMediaRetention(service.store.root) as book:
                if change == 'resealed_head':
                    original = book._read()
                    with book._transaction():book._write(original)
                    assert book._read() == original
                else:
                    duplicate = tmp_path / 'identical-metadata.sqlite'
                    with sqlite3.connect(duplicate) as output:book._db.backup(output)
                    duplicate.chmod(0o600)
            if change == 'copied_database':os.replace(duplicate, Path(service.store.root) / 'phone.db')
            with pytest.raises(TransferError):owner.commit(str(target), witness)
    finally:owner.close()
    assert owner.book_fd is None and owner.meta_fd is None
    assert connection._preferences.read() == before and not list(target.iterdir())


@pytest.mark.parametrize('photos', [False, True])
@pytest.mark.parametrize('change', ['none', 'preferences', 'book', 'expired', 'rollback', 'control'])
def test_context_owner_retains_original_input_and_only_fresh_choice_can_commit(receiving, tmp_path, monkeypatch, photos, change):
    prepare_choice(receiving, monkeypatch)
    connection = receiving[3]
    if photos:
        connection.desktop_session()._local_enabled(False)
    before = connection._preferences.read()
    now = [100.0]
    owner = NativeDestinationFolderChoice(connection, 'images' if photos else 'video', clock=lambda: now[0], **saved_book_inputs(connection))
    target = tmp_path / 'Original-Held-Selection'; target.mkdir(mode=0o700)
    try:
        with NativeCollectionRoot(str(target), lambda: True) as selected:
            witness = native_folder_witness(selected)
            if change == 'preferences':
                preferences = connection._preferences
                preferences.configure_sending(preferences.issue_action(), before, photos=True, videos=False)
            elif change == 'book':
                (tmp_path / 'daten.json').write_text('{"einstellungen":{"papierkorb":{"an":true,"tage":7}}}')
            elif change == 'expired': now[0] += 60
            elif change == 'rollback': now[0] -= 1
            elif change == 'control': connection._controls._session_epoch = 'e' * 64
            if change == 'none':
                result = owner.commit(str(target), witness)
                after = connection._preferences.read()
                destination = after.policy.destination if photos else after.policy.videos.destination
                assert destination.path == str(target) and result['version'] == after.version
                assert not after.policy.enabled if photos else not after.policy.videos.enabled
            else:
                with pytest.raises(TransferError): owner.commit(str(target), witness)
                after = connection._preferences.read()
                if change == 'preferences':
                    assert after.policy.sending.photos is True
                    assert after.policy.destination == before.policy.destination
                    assert after.policy.videos == before.policy.videos
                else:
                    assert after == before
            assert owner.closed.is_set() and owner.book_fd is None
            with pytest.raises(TransferError): owner.commit(str(target), witness)
    finally:
        owner.close()
    assert not list(target.iterdir())
