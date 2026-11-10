"""Fixed setup commands and real private config files; NO host root/module IO."""
from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_camera_setup as setup


def payload():
    namespace = {'__name__': 'controlled_setup_test'}
    exec(compile(setup.ROOT_SETUP, 'isolated-fixed-webcam-setup', 'exec'), namespace)
    return namespace


def runner(config=b'', fail_load=False):
    calls=[]
    def run(command, **options):
        calls.append((command, options))
        if '--showconfig' not in command and fail_load:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0, stdout=config if '--showconfig' in command else b'')
    return run,calls


def test_fixed_privileged_setup_creates_only_exact_owned_autoload_files_and_is_idempotent(tmp_path):
    native=payload();run,calls=runner()
    native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    load=tmp_path/'etc/modules-load.d/magnolie-phone-webcam.conf'
    options=tmp_path/'etc/modprobe.d/magnolie-phone-webcam.conf'
    assert load.read_bytes()==native['LOAD'] and options.read_bytes()==native['OPTIONS']
    assert load.stat().st_mode & 0o777 == options.stat().st_mode & 0o777 == 0o644
    assert calls[-1][0]==['/controlled/modprobe','v4l2loopback','devices=1','exclusive_caps=1','card_label=Magnolie-Phone']
    before=(load.stat().st_ino,options.stat().st_ino)
    native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert (load.stat().st_ino,options.stat().st_ino)==before
    assert not list((tmp_path/'etc/modprobe.d').glob('.magnolie-*'))


def test_foreign_module_options_are_not_replaced_or_overridden(tmp_path):
    native=payload();run,calls=runner(b'options v4l2loopback video_nr=17 exclusive_caps=0\n')
    native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert calls[-1][0]==['/controlled/modprobe','v4l2loopback']
    assert not (tmp_path/'etc/modprobe.d/magnolie-phone-webcam.conf').exists()
    assert (tmp_path/'etc/modules-load.d/magnolie-phone-webcam.conf').read_bytes()==native['LOAD']


@pytest.mark.parametrize('fault',['foreign','symlink','hardlink','writable','directory'])
def test_setup_refuses_ambiguous_owned_filename_before_any_module_command(tmp_path,fault):
    native=payload();run,calls=runner()
    (tmp_path/'etc').mkdir(mode=0o755)
    directory=tmp_path/'etc/modules-load.d';directory.mkdir(mode=0o755)
    path=directory/'magnolie-phone-webcam.conf'
    if fault=='directory':path.mkdir()
    elif fault=='symlink':
        target=tmp_path/'keep';target.write_bytes(native['LOAD']);path.symlink_to(target)
    else:
        path.write_bytes(b'keep user configuration' if fault=='foreign' else native['LOAD'])
        path.chmod(0o644)
        if fault=='hardlink':os.link(path,tmp_path/'keep')
        elif fault=='writable':path.chmod(0o666)
    expected = OSError if fault == 'symlink' else RuntimeError
    with pytest.raises(expected) as error:native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    if expected is RuntimeError:assert str(error.value)=='foreign_setup_configuration'
    assert not calls and path.exists()


def test_module_load_failure_leaves_no_persistent_enablement(tmp_path):
    native=payload();run,calls=runner(fail_load=True)
    with pytest.raises(subprocess.CalledProcessError):native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert len(calls)==2 and not list((tmp_path/'etc').glob('*/*.conf'))


@pytest.mark.parametrize('name',['etc','modules-load.d','modprobe.d'])
def test_setup_never_follows_a_configuration_directory_symlink(tmp_path,name):
    native=payload();run,calls=runner();outside=tmp_path/'outside';outside.mkdir()
    etc=tmp_path/'etc'
    if name=='etc':etc.symlink_to(outside,target_is_directory=True)
    else:
        etc.mkdir(mode=0o755);(etc/name).symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert not calls and not list(outside.iterdir())


@pytest.mark.parametrize('edit',[False,True])
def test_configuration_failure_removes_only_unchanged_new_owned_files(tmp_path,monkeypatch,edit):
    native=payload();run,_=runner();original=os.link;links=[]
    load=tmp_path/'etc/modules-load.d/magnolie-phone-webcam.conf'
    def link(*args,**kwargs):
        links.append(True)
        if len(links)==2:
            if edit:load.write_bytes(b'new independent administrator content')
            raise OSError('controlled second configuration publication failure')
        return original(*args,**kwargs)
    monkeypatch.setattr(os,'link',link)
    with pytest.raises(OSError):native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert load.exists() is edit
    if edit:assert load.read_bytes()==b'new independent administrator content'
    assert not list((tmp_path/'etc').glob('*/.magnolie-*'))


def test_already_loaded_module_keeps_foreign_live_parameters(tmp_path):
    (tmp_path/'sys/module/v4l2loopback').mkdir(parents=True)
    native=payload();run,calls=runner()
    native['enable'](str(tmp_path),run=run,tool='/controlled/modprobe')
    assert calls[-1][0]==['/controlled/modprobe','v4l2loopback']
    assert not (tmp_path/'etc/modprobe.d/magnolie-phone-webcam.conf').exists()


@pytest.mark.parametrize('result,reason',[(0,''),(126,'driver_authentication_cancelled'),(127,'driver_authentication_cancelled'),(70,'driver_setup_failed')])
def test_explicit_activation_uses_only_fixed_isolated_system_command(monkeypatch,result,reason):
    monkeypatch.setattr(setup.os,'geteuid',lambda:1000)
    calls=[];checks=[]
    def run(command,**options):
        calls.append((command,options))
        return SimpleNamespace(returncode=0 if len(calls)==1 else result)
    assert setup.prepare_driver(lambda:checks.append(True),run=run,tool=lambda names:names[0],loaded=lambda:True,clock=lambda:10)==reason
    assert calls[0][0]==['/usr/sbin/modinfo','-F','filename','v4l2loopback']
    assert calls[1][0]==['/usr/bin/pkexec','--disable-internal-agent','/usr/bin/python3','-I','-c',setup.ROOT_SETUP,'120.000000']
    assert calls[1][1]['timeout']==120 and calls[1][1]['stdin']==subprocess.DEVNULL and len(checks)>=3


def test_missing_driver_never_requests_root_authorization():
    calls=[]
    def run(command,**options):calls.append(command);return SimpleNamespace(returncode=1)
    assert setup.prepare_driver(lambda:True,run=run,tool=lambda names:names[0])=='driver_not_installed'
    assert calls==[['/usr/sbin/modinfo','-F','filename','v4l2loopback']]


def test_revoked_original_context_cannot_continue_after_driver_probe():
    checks=[];calls=[]
    def current():
        checks.append(True)
        if len(checks)==2:raise PermissionError('original source revoked')
    def run(command,**options):calls.append(command);return SimpleNamespace(returncode=0)
    with pytest.raises(PermissionError):setup.prepare_driver(current,run=run,tool=lambda names:names[0])
    assert len(calls)==1


def test_false_source_guard_cannot_start_driver_probe_or_authorization():
    with pytest.raises(PermissionError):
        setup.prepare_driver(lambda:False,run=lambda *args,**kwargs:pytest.fail('IO after original source denial'))


@pytest.mark.parametrize('value',['100','99','211','nan','inf','-inf','not-a-deadline'])
def test_privileged_payload_cannot_recapture_time_after_late_authorization(value):
    with pytest.raises((ValueError,RuntimeError)):payload()['remaining'](value,100)


def test_privileged_payload_retains_only_remaining_original_setup_time():
    assert payload()['remaining']('210',100)==110
    assert payload()['remaining']('210',209)==1


@pytest.mark.parametrize('missing,reason',[
    ('/usr/sbin/modinfo','driver_probe_unavailable'),
    ('/usr/bin/python3','driver_authentication_unavailable'),
    ('/usr/bin/pkexec','driver_authentication_unavailable'),
])
def test_missing_system_tool_fails_without_administrator_command(monkeypatch,missing,reason):
    monkeypatch.setattr(setup.os,'geteuid',lambda:1000)
    calls=[]
    def run(command,**options):
        calls.append(command);return SimpleNamespace(returncode=0)
    assert setup.prepare_driver(lambda:True,run=run,
        tool=lambda names:None if names[0]==missing else names[0])==reason
    assert all(command[0]=='/usr/sbin/modinfo' for command in calls)


@pytest.mark.parametrize('stage',[1,2])
def test_native_command_timeout_is_typed_and_never_retried(monkeypatch,stage):
    monkeypatch.setattr(setup.os,'geteuid',lambda:1000)
    calls=[]
    def run(command,**options):
        calls.append(command)
        if len(calls)==stage:raise subprocess.TimeoutExpired(command,options['timeout'])
        return SimpleNamespace(returncode=0)
    assert setup.prepare_driver(lambda:True,run=run,tool=lambda names:names[0])==(
        'driver_probe_unavailable' if stage==1 else 'driver_setup_failed')
    assert len(calls)==stage


def test_successful_authorization_cannot_admit_revoked_original_source(monkeypatch):
    monkeypatch.setattr(setup.os,'geteuid',lambda:1000)
    current=[True];calls=[]
    def run(command,**options):
        calls.append(command)
        if len(calls)==2:current[0]=False
        return SimpleNamespace(returncode=0)
    with pytest.raises(PermissionError,match='webcam_original_choice_changed'):
        setup.prepare_driver(lambda:current[0],run=run,tool=lambda names:names[0],
            loaded=lambda:pytest.fail('Revoked setup admitted a module result'))
    assert len(calls)==2


@pytest.mark.parametrize('selector,name',[('user','modinfo'),('root','modprobe')])
def test_root_owned_multicall_target_keeps_original_invocation_alias(tmp_path,monkeypatch,selector,name):
    target=tmp_path/'controlled-kmod';target.write_text('#!/usr/bin/python3\nimport os,sys\nprint(os.path.basename(sys.argv[0]))\n')
    target.chmod(0o755);alias=tmp_path/name;alias.symlink_to(target)
    original=os.stat
    def root_owned(path,*args,**kwargs):
        info=original(path,*args,**kwargs)
        if os.fspath(path)==str(target):
            values=list(info);values[4]=0;return os.stat_result(values)
        return info
    monkeypatch.setattr(os,'stat',root_owned)
    selected=(setup.system_tool if selector=='user' else payload()['trusted_tool'])((str(alias),))
    assert selected==str(alias) and selected!=str(target)
    assert subprocess.run([selected],capture_output=True,text=True,check=True,timeout=5).stdout.strip()==name
    target.chmod(0o777)
    if selector=='user':assert setup.system_tool((str(alias),)) is None
    else:
        with pytest.raises(RuntimeError,match='setup_tool_missing'):payload()['trusted_tool']((str(alias),))
