"""Original Notes offers and actual GUI/IPC; package installation is controlled."""
import ast
from pathlib import Path
from types import SimpleNamespace
import sys
import threading

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from test_file_authenticated_desktop import native
from test_phone_camera_native_dispatch import connected
from magnolie_phone_camera_ui import NativeWebcamUi
import magnolie_hintergrund as background


def controlled(service, *, result='', missing_after=False):
    state=dict(installed=False);calls=[];devices=[];now=[10]
    def setup(current):
        current();calls.append('probe')
        if not state['installed'] or missing_after:return 'driver_not_installed'
        devices.append(dict(path='/dev/video42',label='Controlled installed output'))
        return ''
    def installer(current,plan):
        current();assert plan=='v4l2loopback-dkms';calls.append('install');state['installed']=True
        return result
    manager=NativeWebcamUi(service,inventory=lambda:list(devices),setup=setup,
        installer=installer,install_plan=lambda:'v4l2loopback-dkms',clock=lambda:now[0],
        video_factory=lambda _:pytest.fail('Installation opened capture output'))
    return manager,calls,state,now


def test_enable_only_offers_installation_and_decline_consumes_offer_without_installing(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service)
    assert manager.status()['phase']=='off' and not calls
    offered=manager.prepare('notes');assert offered['install_token'] and calls==['probe']
    assert not offered['enabled'] and not offered['choices'] and not offered['action']
    manager.cancel(offered['install_token'])
    with pytest.raises(PermissionError):manager.install_driver(offered['install_token'])
    assert calls==['probe'] and service._native_webcam_owner is None


def test_confirmed_installation_consumes_original_offer_and_rechecks_module_without_capture(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service)
    token=manager.prepare('notes')['install_token'];ready=manager.install_driver(token)
    assert ready['choices'] and ready['action'] and not ready['enabled']
    assert calls==['probe','install','probe'] and service._native_webcam_owner is None
    with pytest.raises(PermissionError):manager.install_driver(token)
    assert calls.count('install')==1


@pytest.mark.parametrize('change',['expired','generation','provider','cancel','foreign_token'])
def test_stale_or_changed_original_offer_cannot_install(connected,change):
    service,_,_=connected;manager,calls,_,now=controlled(service)
    token=manager.prepare('auto')['install_token']
    if change=='expired':now[0]+=60
    elif change=='generation':service._generation+=1
    elif change=='provider':manager.prepare('kdeconnect')
    elif change=='cancel':manager.cancel(token)
    else:token='f'*64
    with pytest.raises(PermissionError):manager.install_driver(token)
    assert calls==['probe']


@pytest.mark.parametrize('reason',['driver_installation_failed','driver_installation_unavailable','driver_installation_pending'])
def test_denied_failed_or_unconfirmed_installation_has_no_choices_or_automatic_retry(connected,reason):
    service,_,_=connected;manager,calls,_,_=controlled(service,result=reason)
    token=manager.prepare('notes')['install_token'];result=manager.install_driver(token)
    assert result['reason']==reason and not result['choices'] and not result['action']
    assert calls==['probe','install'] and not result['enabled']
    with pytest.raises(PermissionError):manager.install_driver(token)
    if reason=='driver_installation_pending':
        assert manager.status()['reason']==reason
        assert manager.prepare('notes')['reason']==reason and calls==['probe','install']


def test_transaction_success_without_current_kernel_module_falls_back_to_manual_installation(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service,missing_after=True)
    result=manager.install_driver(manager.prepare('notes')['install_token'])
    assert result['reason']=='driver_installation_failed' and 'install_token' not in result
    assert manager.install_offer is None and calls==['probe','install','probe']


def test_unknown_appimage_host_has_no_install_offer_but_can_use_existing_output(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service)
    manager.install_plan=lambda:None
    result=manager.prepare('notes')
    assert result['reason']=='driver_not_installed' and 'install_token' not in result and calls==['probe']
    manager.inventory=lambda:[dict(path='/dev/video42',label='Existing native output')]
    assert manager.prepare('notes')['choices'] and calls==['probe']


def test_context_change_during_install_never_prepares_a_replacement_phone(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service)
    def revoke(current,plan):current();calls.append('install');service._generation+=1;return ''
    manager.installer=revoke
    with pytest.raises(PermissionError):manager.install_driver(manager.prepare('notes')['install_token'])
    assert calls==['probe','install'] and manager.install_offer is None and manager.action is None


def test_installation_singleflight_refuses_concurrent_command_without_consuming_offer(connected):
    service,_,_=connected;manager,calls,_,_=controlled(service)
    token=manager.prepare('notes')['install_token']
    manager.setup_gate.acquire()
    try:assert manager.install_driver(token)['reason']=='driver_setup_busy'
    finally:manager.setup_gate.release()
    assert calls==['probe'] and manager.install_offer['token']==token
    assert manager.install_driver(token)['choices'] and calls.count('install')==1


def test_service_never_constructs_installer_from_a_forged_offer_without_prepare(connected):
    service,_,_=connected
    assert service._native_webcam_ui is None
    with pytest.raises(PermissionError):service.webcam_action(dict(action='install_driver',install_token='a'*64))
    assert service._native_webcam_ui is None


def test_actual_gui_worker_private_unix_proxy_requires_offer_and_uses_install_only_timeout(connected,tmp_path,monkeypatch):
    service,_,_=connected;manager,calls,_,_=controlled(service);service._native_webcam_ui=manager
    tree=ast.parse((Path(__file__).resolve().parents[1]/'bin/magnolie-organizer').read_text())
    method=next(node for cls in tree.body if isinstance(cls,ast.ClassDef) for node in cls.body
        if isinstance(node,ast.FunctionDef) and node.name=='_telefon_webcam')
    namespace={};exec(compile(ast.Module(body=[method],type_ignores=[]),'actual-install-gui-worker','exec'),namespace)
    server=background.IPCServer(None,path=str(tmp_path/'install.sock'),phone_backend=service).start()
    actual=background.ipc_request;timeouts=[];answers=[]
    def ipc(operation,arguments,path,timeout):
        timeouts.append(timeout);return actual(operation,arguments,path,timeout)
    monkeypatch.setattr(background,'ipc_request',ipc)
    try:
        window=SimpleNamespace(_gesperrt=False,_organizer_vertraut=lambda:True,
            _telefon=background.PhoneServiceProxy(server.path),antwort=lambda name,value:answers.append(value))
        def call(request):
            worker=threading.Thread(target=namespace['_telefon_webcam'],args=(window,
                dict(cmd='telefon_webcam_aktion',requestId='controlled',request=request)))
            worker.start();worker.join(5);assert not worker.is_alive()
            assert answers[-1]['ok'];return answers[-1]['webcam']
        offered=call(dict(action='prepare',provider='notes'))
        ready=call(dict(action='install_driver',install_token=offered['install_token']))
        call(dict(action='cancel',action_token=ready['action']))
        assert timeouts==[150,780,30] and calls==['probe','install','probe']
        assert service._native_webcam_owner is None
    finally:server.close()


@pytest.mark.parametrize('payload',[
    dict(action='install_driver',install_token='/dev/video0'),
    dict(action='install_driver',install_token='a'*64,package='foreign-package'),
    dict(action='install_driver',install_token='a'*64,command=['apt','install']),
    dict(action='install_driver'),
])
def test_install_ipc_refuses_arbitrary_packages_paths_and_commands(payload):
    with pytest.raises(background.IPCError):background._request_shape('phone_webcam_action',dict(request=payload))
