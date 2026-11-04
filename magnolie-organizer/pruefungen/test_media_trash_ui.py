"""Actual native trash projection/handler; no browser paths or book mutations."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_trash import ProtectedMediaTrash
from magnolie_media_trash_ui import NativeMediaTrashUi
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings,save
from test_media_trash import trash,prepare,paths


def request(action='list',**fields):
    return dict(cmd='medien_papierkorb',request_id='native_ui_fixture_01',action=action,**fields)


def test_native_projection_and_offline_restore_use_only_opaque_ids_and_keep_notes_store(trash):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    root=Path(fixture[0].store.root);sent=fixture[2].send.call_count
    ui=NativeMediaTrashUi(str(root),lambda:True)
    listed=ui.handle(request())
    assert listed['ok'] and listed['total']==1 and listed['next_cursor'] is None
    row=listed['entries'][0]
    assert set(row)=={'scope','operation','version','name','media_type','state'}
    assert row['name']==original.name and row['media_type']=='images' and row['state']=='trashed'
    assert str(root) not in str(listed) and str(original.parent) not in str(listed)
    result=ui.handle(request('restore',**{key:row[key] for key in ('scope','operation','version')}))
    assert result['completed']==dict(scope=row['scope'],operation=row['operation'],state='restored')
    assert 'entries' not in result and original.read_bytes()==b'hello' and not payload.exists()
    assert ui.handle(request())['entries']==[] and fixture[2].send.call_count==sent


@pytest.mark.parametrize('extra',[{'path':'/untrusted'},{'scope':'a'*64},{'cursor':True},{'cursor':-1},
    {'cursor':16385},{'fingerprint':'a'*64},{'request_id':'bad space'},{'action':'delete'},{'action':'restore'}, {'action':'purge'}])
def test_invalid_ui_requests_are_rejected_before_native_history_io(tmp_path,extra,monkeypatch):
    ui=NativeMediaTrashUi(str(tmp_path),lambda:True)
    monkeypatch.setattr(ui,'_scopes',lambda:pytest.fail('Malformed browser request reached native history scan'))
    with pytest.raises(TransferError,match='invalid_request'):ui.handle({**request(),**extra})
    assert not list(tmp_path.iterdir())


def test_projection_never_bootstraps_native_root_and_lock_deadline_blocks_reads(tmp_path):
    root=tmp_path/'no-phone-root'
    ui=NativeMediaTrashUi(str(root),lambda:True)
    assert ui.handle(request())['entries']==[] and not root.exists()
    allowed=True;now=0
    ui=NativeMediaTrashUi(str(root),lambda:allowed,clock=lambda:now)
    allowed=False
    with pytest.raises(TransferError,match='native_ui_changed'):ui.handle(request())
    allowed=True;now=60
    with pytest.raises(TransferError,match='native_ui_changed'):ui.handle(request())
    assert not root.exists()


def test_stale_restore_and_destination_collision_keep_both_files(trash):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    ui=NativeMediaTrashUi(str(fixture[0].store.root),lambda:True);row=ui.handle(request())['entries'][0]
    fields={key:row[key] for key in ('scope','operation','version')}
    with pytest.raises(TransferError,match='stale_choice'):ui.handle(request('restore',**dict(fields,version='0'*64)))
    original.write_bytes(b'new user file');original.chmod(0o600)
    with pytest.raises(TransferError,match='move_conflict'):ui.handle(request('restore',**fields))
    assert original.read_bytes()==b'new user file' and payload.read_bytes()==b'hello'
    assert ui.handle(request())['entries'][0]['state']=='restore_prepared'


def test_verified_restore_completion_does_not_depend_on_unrelated_broken_scope(trash):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    root=Path(fixture[0].store.root);ui=NativeMediaTrashUi(str(root),lambda:True)
    row=ui.handle(request())['entries'][0]
    unfamiliar=root/('media-trash-anchor-v1-'+'f'*64+'.seal');unfamiliar.write_bytes(b'x'*32);unfamiliar.chmod(0o600)
    result=ui.handle(request('restore',**{key:row[key] for key in ('scope','operation','version')}))
    assert result['ok'] and result['completed']['state']=='restored'
    assert original.read_bytes()==b'hello' and not payload.exists() and unfamiliar.read_bytes()==b'x'*32


def test_projection_pages_real_entries_without_discarding_history(mappings,monkeypatch):
    fixture,mapping_store=mappings
    receiver,pages,_=save(fixture,count=2)
    _,records=mapping_store.commit_received(mapping_store.issue_action(),mapping_store.read(),receiver,pages)
    owner=ProtectedMediaTrash(fixture[3]._authority)
    try:
        for record in records:
            snapshot,_=owner.read()
            snapshot,entry=owner.prepare_local(owner.issue_action(),snapshot,mapping_store,record.association,record.protected_record_sha256)
            owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
        ui=NativeMediaTrashUi(str(fixture[0].store.root),lambda:True);monkeypatch.setattr(ui,'PAGE_SIZE',1)
        first=ui.handle(request());second=ui.handle(request(cursor=first['next_cursor']))
        assert first['total']==second['total']==2 and len(first['entries'])==len(second['entries'])==1
        assert first['entries'][0]['operation']!=second['entries'][0]['operation'] and second['next_cursor'] is None
        assert owner.read()[0].count==2
    finally:owner.close()


def native_handler(root,monkeypatch,*,supported=True):
    import magnolie_optional_phone
    monkeypatch.setattr(magnolie_optional_phone,'available',lambda feature:supported and feature=='photo_sync')
    tree=ast.parse((Path(__file__).parents[1]/'bin/magnolie-organizer').read_text())
    method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
        if isinstance(node,ast.FunctionDef) and node.name=='_medien_papierkorb_aktion')
    calls=[];answers=[]
    def join(base,leaf):
        assert base=='native-private-profile' and leaf=='telefon'
        calls.append((base,leaf));return str(root)
    namespace={'threading':threading,'os':SimpleNamespace(path=SimpleNamespace(join=join)),
        'daten_verzeichnis':lambda:'native-private-profile'}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-native-trash-handler','exec'),namespace)
    window=SimpleNamespace(_gesperrt=False,_organizer_geladen=True,_organizer_vertraut=lambda:True,
        antwort=lambda name,value:answers.append((name,value)),connect=lambda *args:None)
    def invoke(message):
        worker=namespace['_medien_papierkorb_aktion'](window,message)
        if worker is not None:worker.join(15);assert not worker.is_alive()
        return worker
    return window,invoke,calls,answers


def test_actual_native_handler_uses_own_root_and_late_lock_hides_metadata(trash,monkeypatch):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    window,invoke,calls,answers=native_handler(fixture[0].store.root,monkeypatch)
    assert invoke(request()) is not None and calls
    assert answers[-1][0]=='App.medienPapierkorbStand' and callable(answers[-1][1])
    assert answers[-1][1]()['total']==1
    window._gesperrt=True
    assert answers[-1][1]()['entries']==[] and answers[-1][1]()['ok'] is False
    before=len(calls);assert invoke(request()) is None and len(calls)==before


def test_actual_native_handler_rejects_browser_path_and_hides_unsupported_controls(tmp_path,monkeypatch):
    _,invoke,calls,answers=native_handler(tmp_path,monkeypatch)
    assert invoke(request(path='/untrusted')) is None and not calls and answers[-1][1]['ok'] is False
    _,invoke,calls,answers=native_handler(tmp_path,monkeypatch,supported=False)
    assert invoke(request()) is None and not calls and answers[-1][1]['supported'] is False
    assert not list(tmp_path.iterdir())


def test_lock_before_native_restore_move_keeps_payload_and_requires_fresh_ui(trash,monkeypatch):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    allowed=True;ui=NativeMediaTrashUi(str(fixture[0].store.root),lambda:allowed)
    row=ui.handle(request())['entries'][0];move=ProtectedMediaTrash._move
    def guarded_move(self,entry,fresh,**options):
        def boundary(at):
            nonlocal allowed
            if at=='before_move':allowed=False
        self._boundary=boundary
        return move(self,entry,fresh,**options)
    monkeypatch.setattr(ProtectedMediaTrash,'_move',guarded_move)
    with pytest.raises(TransferError):ui.handle(request('restore',**{key:row[key] for key in ('scope','operation','version')}))
    assert payload.read_bytes()==b'hello' and not original.exists()
    monkeypatch.setattr(ProtectedMediaTrash,'_move',move);allowed=True
    fresh_ui=NativeMediaTrashUi(str(fixture[0].store.root),lambda:allowed)
    row=fresh_ui.handle(request())['entries'][0]
    assert row['state']=='restore_prepared'
    assert fresh_ui.handle(request('restore',**{key:row[key] for key in ('scope','operation','version')}))['ok']
    assert original.read_bytes()==b'hello' and not payload.exists()


def test_actual_native_handler_restores_without_phone_service_or_socket(trash,monkeypatch):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    root=fixture[0].store.root;owner.close();fixture[0]._end_native_file_connection(fixture[2])
    row=NativeMediaTrashUi(str(root),lambda:True).handle(request())['entries'][0]
    window,invoke,_,answers=native_handler(root,monkeypatch)
    assert not hasattr(window,'_telefon')
    sent=fixture[2].send.call_count
    assert invoke(request('restore',**{key:row[key] for key in ('scope','operation','version')})) is not None
    result=answers[-1][1]()
    assert result['ok'] and result['completed']['state']=='restored'
    assert original.read_bytes()==b'hello' and not payload.exists() and fixture[2].send.call_count==sent


@pytest.mark.parametrize('missing',['anchor','journal'])
def test_overview_detects_either_missing_history_half_instead_of_reporting_empty(trash,missing):
    fixture,_,_,_,owner=trash
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True);owner.close()
    root=Path(fixture[0].store.root);name=owner._anchor if missing=='anchor' else owner._name
    (root/name).rename(root/(name+'.explicit-fixture-parked'))
    with pytest.raises(TransferError,match='original_anchor_required'):
        NativeMediaTrashUi(str(root),lambda:True).handle(request())
    assert payload.read_bytes()==b'hello' and not original.exists()
