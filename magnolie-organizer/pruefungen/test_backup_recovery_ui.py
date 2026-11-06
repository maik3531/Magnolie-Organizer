"""Actual native recovery handler and local controllers, without phone authority."""
import ast
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from test_media_backups import local_restore,mappings,receiving
from test_telefon import _complete_peer,FakeBluetooth
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
import magnolie_telefon as phone
from magnolie_media_backups import NativeMediaBackupRecoveryUi,NativeMediaBackupRestoreOwner
from magnolie_personal_actor_store import NativeBookOwnerScope
from magnolie_media_retention import NativeMediaRetention
import magnolie_optional_phone


@pytest.fixture
def native(tmp_path,monkeypatch):
    # The ordinary wire fixture uses an English "telephone" directory. This
    # native application handler intentionally uses the installed "telefon"
    # root; exercise that actual layout, not a path shim or a relaxed guard.
    service=phone.PhoneService(str(tmp_path/'telefon'),'Fixture PC',bluetooth_backend=FakeBluetooth())
    monkeypatch.setattr(service,'_native_photo_built',True)
    private=X25519PrivateKey.from_private_bytes(bytes([2])*32)
    public=private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
    peer=_complete_peer(public=public);peer['personal_sync'].update(own_device=True,remote_own_device=True)
    peer['file_pairing_epoch']=phone.native_file_pairing_epoch(bytes([1])*32)
    peer['capabilities']=phone.desktop_capabilities();peer['capabilities']['items']['device_status']['versions'].append(21)
    service.store.peers=[peer];service.store.save_peers();service.enabled=True
    return service,peer,private


def handler(fixture,monkeypatch,change=None):
    _,_,_,directory,_,locations,source,version,target=fixture
    tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
    method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
        if isinstance(node,ast.FunctionDef) and node.name=='_medien_backup_aktion')
    monkeypatch.setattr(magnolie_optional_phone,'available',lambda name:name=='photo_sync')
    queued=[];answers=[];dialogs=[];choices=[];owner=NativeBookOwnerScope();owner.set_ready(True)
    class Question:
        def __init__(self,**options):
            assert threading.current_thread() is threading.main_thread();dialogs.append(options)
        def format_secondary_text(self,text):assert version.name in text and target.path in text
        def run(self):return 'no' if change=='cancel_confirm' else 'yes'
        def destroy(self):pass
    gtk=SimpleNamespace(MessageDialog=Question,DialogFlags=SimpleNamespace(MODAL='modal'),
        MessageType=SimpleNamespace(QUESTION='question'),ButtonsType=SimpleNamespace(YES_NO='yes-no'),ResponseType=SimpleNamespace(YES='yes'))
    namespace={'_':lambda text:text,'threading':threading,'os':os,'Gtk':gtk,
        'GLib':SimpleNamespace(idle_add=queued.append),'daten_verzeichnis':lambda:str(Path(directory).parent)}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-backup-recovery-handler','exec'),namespace)
    data=json.loads((Path(directory).parent/'daten.json').read_text())
    window=SimpleNamespace(_gesperrt=False,_organizer_geladen=True,_aktuelle_daten=data,
        _organizer_vertraut=lambda:True,connect=lambda *_args:None,
        antwort=lambda name,value:answers.append((name,value() if callable(value) else value)))
    window._telefon_actor_buchquelle=lambda:owner.current('native-fixed-book-binding',not window._gesperrt)
    def choose(title,**options):
        assert threading.current_thread() is threading.main_thread();choices.append((title,options))
        if change=='cancel_folder':return None
        if change=='lock':window._gesperrt=True
        if change=='off_on':owner.set_ready(False);owner.set_ready(True)
        if change=='data_owner':window._aktuelle_daten=dict(window._aktuelle_daten)
        if change=='book':
            with NativeMediaRetention(directory) as policy:
                token=policy.pause();policy.publish_saved(token,data)
        return target.path
    window._ordner_waehlen=choose
    request=dict(cmd='medien_backup',request_id='native-recovery-request',action='restore',scope=locations._store._scope,
        source_id=source,reference=version.id,reference_sha256=version.record_sha256)
    def invoke(extra=None,*,replace=False):
        worker=namespace['_medien_backup_aktion'](window,extra if replace else {**request,**(extra or {})})
        if worker is not None:
            worker.join(20);assert not worker.is_alive()
            while queued:assert queued.pop(0)() is False
            window._medien_backup_worker.join(20);assert not window._medien_backup_worker.is_alive()
        return worker
    return window,invoke,answers,choices,dialogs,request


def test_actual_native_offline_restore_confirms_on_main_and_publishes_new_file_without_phone(local_restore,monkeypatch):
    fixture,record,raw,directory,scope,_,_,_,target=local_restore
    fixture[3].close()
    window,invoke,answers,choices,dialogs,_=handler(local_restore,monkeypatch)
    assert not hasattr(window,'_telefon')
    assert invoke() is not None
    result=answers[-1][1]
    assert answers[-1][0]=='App.medienBackupStand' and result['ok'] is True and result['action']=='restore'
    assert len(choices)==len(dialogs)==1 and not window._medien_backup_busy
    completed=result['completed'];assert completed['state']=='restored' and (Path(target.path)/completed['name']).read_bytes()==raw
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:
        assert owner.history()[0].original_mapping==record and not owner.history()[0].is_saved_receipt


@pytest.mark.parametrize('change',('cancel_folder','cancel_confirm','lock','off_on','data_owner','book','injected_path','injected_confirmation'))
def test_native_recovery_cancel_or_stale_book_cannot_publish_or_manufacture_confirmation(local_restore,monkeypatch,change):
    _,_,_,directory,scope,_,_,_,target=local_restore
    window,invoke,answers,choices,dialogs,_=handler(local_restore,monkeypatch,change)
    extra={'path':target.path} if change=='injected_path' else {'confirmed':True} if change=='injected_confirmation' else None
    if extra:window._medien_backup_busy=True
    invoke(extra)
    assert answers[-1][1]['ok'] is (change in ('cancel_folder','cancel_confirm'))
    assert not list(Path(target.path).iterdir())
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:assert owner.history()==()
    if extra:
        assert not choices and not dialogs and window._medien_backup_busy is True
    elif change=='cancel_folder':assert len(choices)==1 and not dialogs


def test_recovery_browser_schema_never_accepts_native_paths_or_foreground_confirmation(local_restore):
    _,_,_,directory,_,locations,source,version,_=local_restore
    base=dict(cmd='medien_backup',request_id='native-schema-request',action='restore',scope=locations._store._scope,
        source_id=source,reference=version.id,reference_sha256=version.record_sha256)
    assert NativeMediaBackupRecoveryUi.validate_request(base)=='restore'
    for extra in ({'path':'/native/path'},{'destination':{}},{'confirmed':True},{'cursor':True}):
        with pytest.raises(ValueError):NativeMediaBackupRecoveryUi.validate_request({**base,**extra})
    with pytest.raises(ValueError,match='native_confirmation_required'):
        NativeMediaBackupRecoveryUi(directory,lambda:True).read_request(base)

def test_actual_native_offline_source_and_version_reads_do_not_open_dialog_or_create_restorations(local_restore,monkeypatch):
    fixture,_,_,directory,scope,locations,source,version,target=local_restore;fixture[3].close()
    _,invoke,answers,choices,dialogs,_=handler(local_restore,monkeypatch)
    before=locations.read()
    invoke(dict(cmd='medien_backup',request_id='native-read-sources',action='sources',cursor=0),replace=True)
    page=answers[-1][1];assert page['ok'] and page['action']=='sources'
    assert any(row['scope']==locations._store._scope and row['source_id']==source for row in page['entries'])
    invoke(dict(cmd='medien_backup',request_id='native-read-versions',action='versions',cursor=0,
        scope=locations._store._scope,source_id=source),replace=True)
    versions=answers[-1][1];assert versions['ok'] and versions['entries'][0]['id']==version.id
    json.dumps(versions)
    assert not choices and not dialogs and not list(Path(target.path).iterdir()) and locations.read()==before
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:assert owner.history()==()

def test_native_saved_book_pause_during_actual_copy_is_not_blocked_and_stops_publication(local_restore,monkeypatch):
    _,_,raw,directory,scope,_,_,_,target=local_restore
    original=NativeMediaBackupRestoreOwner.__init__
    def boundary(phase):
        if phase=='copied':
            with NativeMediaRetention(directory) as writer:writer.pause()
    def init(self,*args,**kwargs):original(self,*args,**kwargs,boundary=boundary)
    monkeypatch.setattr(NativeMediaBackupRestoreOwner,'__init__',init)
    _,invoke,answers,_,_,_=handler(local_restore,monkeypatch)
    invoke();assert answers[-1][1]['ok'] is False
    paths=tuple(Path(target.path).iterdir());assert len(paths)==1 and paths[0].suffix=='.part' and paths[0].read_bytes()==raw
    with NativeMediaBackupRestoreOwner(directory,scope,lambda:True) as owner:assert owner.history()[0].state=='prepared'
