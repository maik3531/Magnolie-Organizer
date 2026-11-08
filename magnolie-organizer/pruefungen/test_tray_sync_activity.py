"""Real encrypted writer ownership, passive projection and aggregate UI state."""
import socket
import threading
from types import SimpleNamespace
import pytest
from test_tray_media_activity import phone, background, product, ui_methods


def test_counter_overlap_duplicate_end_and_observer_failure():
    seen=[];activity=phone.NativeSyncActivity(lambda:seen.append(activity.active))
    first=activity.enter();second=activity.enter();first.dispose();first.dispose()
    assert activity.active
    second.dispose();assert seen==[True,True,True,False]
    activity.changed=lambda:(_ for _ in ()).throw(RuntimeError('visual observer'))
    with activity.enter():assert activity.active
    assert not activity.active


@pytest.mark.parametrize('kind',['personal_sync.batch','personal_sync.time_batch','personal_sync.actor_data','personal_sync.settings','personal_sync.time_settings'])
@pytest.mark.parametrize('fail',[False,True])
def test_actual_secure_writer_lease_spans_blocked_io_and_drain(monkeypatch,kind,fail):
    activity=phone.NativeSyncActivity(lambda:None);entered=threading.Event();release=threading.Event();errors=[]
    left,right=socket.socketpair();left.settimeout(3);right.settimeout(3)
    channel=phone.SecureChannel(left,b'1'*32,b'2'*32,b'3'*4,b'4'*32,b'5'*4);channel.sync_activity=activity
    native_send=phone.send_frame
    def send(sock,frame):
        entered.set();assert release.wait(3)
        if fail:raise OSError('actual write fixture failure')
        native_send(sock,frame)
    monkeypatch.setattr(phone,'send_frame',send)
    def worker():
        try:channel.send({'type':'message','kind':kind,'body':{}})
        except OSError as error:errors.append(error)
    thread=threading.Thread(target=worker);thread.start()
    try:
        assert entered.wait(3)
        expected=phone.tray_sync_data_frame({'type':'message','kind':kind})
        assert activity.active is expected
        # This probe must remain readable even while the actual sender owns its
        # stream monitor and some legacy callers own the service monitor too.
        service=phone.PhoneService.__new__(phone.PhoneService);service._native_sync_activity=activity
        assert service.tray_sync_activity()=={'synchronizing':expected}
        other=activity.enter();release.set();thread.join(3);assert not thread.is_alive() and activity.active
        other.dispose();assert not activity.active and bool(errors)==fail
        if not fail:assert phone.receive_frame(right,phone.SECURE_FRAME_MAX)['ciphertext']
    finally:release.set();thread.join(3);left.close();right.close()


def test_metadata_mode_and_unknown_frames_never_count_as_sync():
    import re
    from pathlib import Path
    windows=Path(__file__).parents[2]/'magnolie-organizer-windows/TraySyncFrames.cs'
    assert set(re.findall(r'"(personal_sync\.[a-z_]+)"',windows.read_text()))==phone.TRAY_SYNC_DATA_KINDS
    for kind in phone.TRAY_SYNC_DATA_KINDS:assert phone.tray_sync_data_frame({'type':'message','kind':kind})
    for kind in ('personal_sync.settings','personal_sync.time_settings','personal_sync.custom_settings','personal_sync.not_real','capabilities.update','file_transfer.chunk'):
        assert not phone.tray_sync_data_frame({'type':'message','kind':kind})
    for value in ({},{'type':'ack','kind':'personal_sync.batch'},{'type':'message','kind':[]},None):
        assert not phone.tray_sync_data_frame(value)


def test_real_ipc_projection_does_not_start_service_or_take_its_monitor(tmp_path):
    path=str(tmp_path/'runtime'/'activity.sock');server=background.IPCServer(None,path).start()
    activity=phone.NativeSyncActivity(lambda:None);service=phone.PhoneService.__new__(phone.PhoneService)
    service._native_sync_activity=activity;service.lock=threading.Lock()
    proxy=background.PhoneServiceProxy(path)
    try:
        assert proxy.tray_sync_activity()=={'synchronizing':False}
        assert proxy._event_thread is None and server.phone_backend is None
        server.phone_backend=service
        with activity.enter(),service.lock,server._mutation_lock:
            assert proxy.tray_sync_activity()=={'synchronizing':True}
        with pytest.raises(background.IPCError):background.ipc_request('phone_tray_sync_activity',{'synchronizing':True},path)
    finally:server.close()


def test_actor_receive_counts_only_matching_native_admission_and_unwinds_failure():
    service=phone.PhoneService.__new__(phone.PhoneService);service.lock=threading.RLock()
    service._native_sync_activity=phone.NativeSyncActivity(lambda:None)
    peer={'device_id':'fixture','static_public':'current-key'};channel=object()
    service.connections={'fixture':channel}
    service.personal_actor_admissions={'run':{'peer':'fixture','key':'current-key','channel':channel}}
    def admitted(*_args):
        assert service.tray_sync_activity()=={'synchronizing':True}
        raise OSError('actual processing fixture failure')
    service._receive_personal_actor_active=admitted
    with pytest.raises(OSError):service._receive_personal_actor(peer,channel,{'body':{'run_id':'run'}})
    assert service.tray_sync_activity()=={'synchronizing':False}
    service._receive_personal_actor(peer,object(),{'body':{'run_id':'run'}})
    service._receive_personal_actor(peer,channel,{'body':{'run_id':'queued-only'}})
    assert not service._native_sync_activity.active


def test_actual_time_receive_and_commit_project_only_current_work(tmp_path,monkeypatch):
    from test_time_sync_runtime import ready
    service,peer,channel,incoming,events=ready(tmp_path,monkeypatch)
    projected=[];original=service.callback
    def callback(kind,value):
        if kind=='personal_time_batch':projected.append(service.tray_sync_activity()['synchronizing'])
        original(kind,value)
    service.callback=callback
    service._payload(service.store.peer(peer),channel,incoming)
    assert projected==[True] and service.tray_sync_activity()=={'synchronizing':False}
    # Durable staged/pending metadata is deliberately not a running worker.
    staged=events[-1][1];native_commit=service.store.commit_time_batch
    def commit(*args,**kwargs):
        assert service.tray_sync_activity()=={'synchronizing':True}
        return native_commit(*args,**kwargs)
    monkeypatch.setattr(service.store,'commit_time_batch',commit)
    assert service.commit_time_sync(peer,incoming['message_id'],staged['commit_token'],True)
    assert service.tray_sync_activity()=={'synchronizing':False} and channel.sent[-1]['status']=='accepted'


def test_fresh_activity_refresh_avoids_full_report_and_keeps_other_owners():
    methods=ui_methods('_tray_personal_sync_aktualisieren','_tray_zaehler_anzeigen')
    state={'synchronizing':True};seen=[]
    methods['_']=lambda value:value;methods['ngettext']=lambda singular,plural,count:plural
    service=SimpleNamespace(tray_sync_activity=lambda:dict(state),report=lambda:pytest.fail('Full report blocked behind transport IO'))
    window=SimpleNamespace(_telefon=service,_tray_medien=(False,False),_tray_indikator=SimpleNamespace(),
        _tray_einstellungen={},_tray_zaehler=0,_tray_art='appindicator',_tray_medien_symbol_setzen=lambda *args:seen.append(args))
    window._tray_zaehler_anzeigen=lambda:methods['_tray_zaehler_anzeigen'](window)
    methods['_tray_personal_sync_aktualisieren'](window);assert seen[-1]==(True,False)
    state['synchronizing']=False;window._tray_medien=(True,False)
    methods['_tray_personal_sync_aktualisieren'](window);assert seen[-1]==(True,False)
    window._tray_medien=(False,False)
    methods['_tray_personal_sync_aktualisieren'](window);assert seen[-1]==(False,False)
