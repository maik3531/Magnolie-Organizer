"""Current native media metadata only: no files, paths, listener or transfers."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mcp_phone import owned_service
from modul_laden import quellmodul_laden


def request(service):
    state = service.mcp_status()
    peer = state['peers'][0]
    return dict(action='media_status_read', expectedRevision=state['revision'], peerId=peer['id'], fingerprint=peer['fingerprint'])


def test_current_media_projection_excludes_files_paths_and_grants(tmp_path, monkeypatch):
    service, peer, events = owned_service(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    seen = []
    def native(peer_id):
        seen.append(peer_id)
        return dict(available=True, enabled=False, video_enabled=True, video_supported=True, mode='manual', busy=False,
            shared_media=dict(agreed=False, private='secret'), albums=['secret'], destination='secret', owner_token='secret')
    monkeypatch.setattr(service, 'photo_sync_state', native)
    result = service.mcp_action(request(service))
    assert result['ok'] and seen == [peer['device_id']]
    value = result['mediaStatus']
    assert value['supported'] and value['photos_enabled'] is False and value['videos_enabled'] is True
    assert value['shared_settings_present'] is True and value['shared_settings_agreed'] is False
    assert not value['persisted'] and not value['transfer_started']
    assert 'secret' not in json.dumps(result) and not events and service.server is None
    assert {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()} == before


def test_unsupported_media_does_not_invent_opt_outs(tmp_path, monkeypatch):
    service, _, _ = owned_service(tmp_path)
    monkeypatch.setattr(service, 'photo_sync_state', lambda _: None)
    value = service.mcp_action(request(service))['mediaStatus']
    assert not value['supported'] and value['photos_enabled'] is None and value['videos_enabled'] is None
    assert value['automatic_wifi'] is None and value['shared_settings_present'] is None


@pytest.mark.parametrize('change', ['extra', 'revision', 'fingerprint', 'peer'])
def test_bad_selection_never_reads_native_media(tmp_path, monkeypatch, change):
    service, _, _ = owned_service(tmp_path)
    def forbidden(_): raise AssertionError('Invalid selection reached native media')
    monkeypatch.setattr(service, 'photo_sync_state', forbidden)
    value = request(service)
    value.update({'extra': dict(path='/private'), 'revision': dict(expectedRevision='0'*64),
        'fingerprint': dict(fingerprint='wrong'), 'peer': dict(peerId='foreign')}[change])
    assert service.mcp_action(value)['ok'] is False


def test_replaced_connection_during_native_read_is_rejected(tmp_path, monkeypatch):
    service, peer, _ = owned_service(tmp_path)
    service.connections[peer['device_id']] = object()
    def native(_):
        service.connections[peer['device_id']] = object()
        return dict(available=True, enabled=True)
    monkeypatch.setattr(service, 'photo_sync_state', native)
    assert service.mcp_action(request(service)) == dict(ok=False, code='source_changed')


def test_daemon_proxy_keeps_media_read_non_subscribing(tmp_path, monkeypatch):
    import magnolie_hintergrund as background
    from test_hintergrunddienst import FakeBackend
    service, _, events = owned_service(tmp_path)
    monkeypatch.setattr(service, 'photo_sync_state', lambda _: None)
    path = str(tmp_path/'runtime'/'background.sock')
    server = background.IPCServer(FakeBackend(), path, phone_backend=service).start()
    proxy = background.PhoneServiceProxy(path)
    try:
        value = proxy.mcp_action(request(service))
        assert value['ok'] and not value['mediaStatus']['supported']
        assert proxy._event_thread is None and service.server is None and not events
        with pytest.raises(background.IPCError):
            proxy.mcp_action({**request(service), 'enabled': True})
    finally: server.close()


@pytest.mark.parametrize('withdraw', [None, 'lock', 'source'])
def test_window_reads_only_at_current_mainloop_delivery(tmp_path, monkeypatch, withdraw):
    monkeypatch.setitem(sys.modules, 'gi', None)
    for key in ('HOME','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','XDG_RUNTIME_DIR'):
        folder=tmp_path/key;folder.mkdir();monkeypatch.setenv(key,str(folder))
    native=quellmodul_laden('mcp_media_window',Path(__file__).resolve().parents[1]/'bin/magnolie-organizer')
    calls=[];answers=[]
    service=SimpleNamespace(mcp_action=lambda value: calls.append(value) or dict(ok=True,mediaStatus={'supported':False}))
    host=SimpleNamespace(_gesperrt=False,_telefon=service,_organizer_vertraut=lambda:True,
        _telefon_dienst_pflegen=lambda **kwargs: None,antwort=lambda _,value:answers.append(value))
    message=dict(requestId='owned',request=dict(action='media_status_read',peerId='original'))
    native.Fenster._telefon_mcp(host,message)
    assert not calls and len(answers)==1 and callable(answers[0])
    message['request']['peerId']='mutated'
    if withdraw=='lock':host._gesperrt=True
    if withdraw=='source':host._telefon=object()
    value=answers[0]()
    if withdraw:assert value['code']=='source_changed' and not calls
    else:assert value['ok'] and calls[0]['peerId']=='original'
