"""One fixed authorization boundary; private pipes/children, NO root/package IO."""
from pathlib import Path
import json
import math
import os
import struct
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
import magnolie_phone_camera_install as install


def namespace():
    result={'__name__':'controlled_combined_test'}
    exec(compile(install.ROOT_INSTALL_SETUP,'fixed-combined-installation','exec'),result)
    return result


class Process:
    def __init__(self,code,hook=None):
        self.reader,writer=os.pipe();os.set_blocking(self.reader,False)
        self.stdin=os.fdopen(writer,'wb',buffering=0)
        self.code=code;self.returncode=None;self.received=b'';self.hook=hook;self.terminated=False
    def poll(self):return self.returncode
    def wait(self,timeout):
        try:self.received+=os.read(self.reader,4096)
        except BlockingIOError:pass
        if self.hook:
            callback,self.hook=self.hook,None;callback()
            raise subprocess.TimeoutExpired('controlled-authorized-process',timeout)
        self.returncode=self.code;return self.code
    def terminate(self):self.terminated=True;self.returncode=-15
    def close(self):
        self.stdin.close();os.close(self.reader)


@pytest.mark.parametrize('code,reason',[(0,''),(70,'driver_setup_failed'),(71,'driver_installation_failed'),
    (72,'driver_installation_pending'),(73,'driver_installation_pending'),(74,'driver_installation_unavailable'),
    (126,'driver_authentication_cancelled'),(127,'driver_authentication_cancelled')])
def test_one_fixed_system_authorization_handles_both_phases_without_password_input(monkeypatch,code,reason):
    monkeypatch.setattr(install.os,'geteuid',lambda:1000)
    process=Process(code);calls=[]
    def popen(command,**options):calls.append((command,options));return process
    try:
        assert install.install_driver(lambda:True,'v4l2loopback-dkms',popen=popen,
            tool=lambda names:names[0],clock=lambda:10)==reason
        assert len(calls)==1
        command,options=calls[0]
        assert command==['/usr/bin/pkexec','--disable-internal-agent','/usr/bin/python3','-I','-c',install.ROOT_INSTALL_SETUP,'720.000000']
        assert options['stdin']==subprocess.PIPE and options['stdout']==options['stderr']==subprocess.DEVNULL
        assert process.stdin.closed and process.received==struct.pack('!d',10)
        assert not process.terminated
    finally:process.close()


def test_unknown_plan_missing_tools_or_revoked_context_never_request_authorization():
    denied=lambda *a,**k:pytest.fail('Unexpected system authorization')
    assert install.install_driver(lambda:True,'foreign-package',popen=denied)=='driver_installation_unavailable'
    assert install.install_driver(lambda:True,'v4l2loopback-dkms',tool=lambda _:None,popen=denied)=='driver_installation_unavailable'
    with pytest.raises(PermissionError):install.install_driver(lambda:False,'v4l2loopback-dkms',popen=denied)


def test_original_context_change_closes_only_original_pipe_and_never_reauthorizes(monkeypatch):
    monkeypatch.setattr(install.os,'geteuid',lambda:1000)
    current=[True];calls=[];process=Process(0,hook=lambda:current.__setitem__(0,False))
    def popen(*args,**kwargs):calls.append(True);return process
    try:
        assert install.install_driver(lambda:current[0],'v4l2loopback-dkms',popen=popen,
            tool=lambda names:names[0])=='driver_installation_pending'
        assert calls==[True] and process.stdin.closed and process.terminated
        assert len(process.received)==8
    finally:process.close()


class Lease:
    def __init__(self):self.current=True;self.calls=[]
    def require(self):
        if not self.current:raise PermissionError('original installation revoked')
    def register_cancel(self,callback):self.calls.append('cancel-registered')
    def begin_setup(self):self.require();self.calls.append('setup-begun')


@pytest.mark.parametrize('reason,code',[('',0),('driver_installation_failed',71),
    ('driver_installation_unavailable',74),('driver_installation_pending',72)])
def test_exact_combined_payload_joins_package_and_setup_without_second_authentication(reason,code):
    native=namespace();lease=Lease();calls=[]
    def package(current,plan,register_cancel):
        current();assert plan=='v4l2loopback-dkms';calls.append('package');register_cancel(lambda:None);return reason
    result=native['run_combined'](lease,package=package,setup=lambda:calls.append('setup'),loaded=lambda:True)
    assert result==code
    assert calls==(['package','setup'] if not reason else ['package'])


def test_revoked_or_unloaded_combined_result_cannot_claim_setup_success():
    native=namespace();lease=Lease()
    def revoke(*a,**k):lease.current=False;return ''
    with pytest.raises(PermissionError):native['run_combined'](lease,package=revoke,setup=lambda:pytest.fail('Setup after revocation'))
    lease=Lease();calls=[]
    assert native['run_combined'](lease,package=lambda *a,**k:'',setup=lambda:calls.append(True),loaded=lambda:False)==70
    assert calls==[True]


@pytest.mark.parametrize('stamp',[float('nan'),float('inf'),8.,10.2])
def test_invalid_stale_or_future_heartbeat_is_not_original_context(stamp):
    native=namespace();reader,writer=os.pipe()
    lease=native['OriginalInstallLease'](20,reader,clock=lambda:10,interrupt=lambda:None,grace=lambda:None)
    try:
        os.write(writer,struct.pack('!d',stamp))
        with pytest.raises(PermissionError):lease.receive(0);lease.require()
    finally:lease.close();os.close(writer);os.close(reader)


def test_pipe_lease_rejects_partial_frames_and_cancels_on_original_parent_eof():
    native=namespace();reader,writer=os.pipe();events=[]
    lease=native['OriginalInstallLease'](20,reader,clock=lambda:10,interrupt=lambda:events.append('interrupt'),grace=lambda:events.append('grace'))
    try:
        payload=struct.pack('!d',10);os.write(writer,payload[:4]);lease.receive(0)
        with pytest.raises(PermissionError):lease.require()
        os.write(writer,payload[4:]);lease.acquire();lease.require()
        lease.register_cancel(lambda:events.append('cancel'));lease.begin_setup();lease.start()
        os.close(writer);writer=None
        deadline=time.monotonic()+1
        while not lease.revoked and time.monotonic()<deadline:time.sleep(.005)
        assert lease.revoked and events==['cancel','interrupt']
        with pytest.raises(PermissionError):lease.require()
    finally:
        lease.close()
        if writer is not None:os.close(writer)
        os.close(reader)
        assert not lease.worker.is_alive()


def test_old_queued_heartbeats_after_late_authorization_need_a_fresh_original_caller():
    native=namespace();reader,writer=os.pipe();now=[10.]
    lease=native['OriginalInstallLease'](20,reader,clock=lambda:now[0],interrupt=lambda:None,grace=lambda:None)
    def fresh():time.sleep(.05);os.write(writer,struct.pack('!d',10))
    worker=threading.Thread(target=fresh)
    try:
        os.write(writer,struct.pack('!d',5));worker.start();lease.acquire()
        assert lease.latest==10
        now[0]=20
        with pytest.raises(PermissionError):lease.require()
    finally:worker.join(1);lease.close();os.close(writer);os.close(reader)


@pytest.mark.parametrize('value',['nan','inf','-inf','-1','expired','too_far'])
def test_fixed_cli_refuses_invalid_original_deadline_before_package_or_setup(monkeypatch,value):
    if value=='expired':value=str(time.monotonic()-1)
    elif value=='too_far':value=str(time.monotonic()+1000)
    monkeypatch.setattr(os,'geteuid',lambda:0)
    monkeypatch.setattr(sys,'argv',['isolated-fixed-code',value])
    timers=[]
    monkeypatch.setattr(__import__('signal'),'setitimer',lambda *args:timers.append(args))
    with pytest.raises(SystemExit) as result:
        exec(compile(install.ROOT_INSTALL_SETUP,'fixed-combined-cli','exec'),{'__name__':'__main__'})
    assert result.value.code==72
    assert timers==[(__import__('signal').ITIMER_REAL,0)]


@pytest.mark.parametrize('uid,argv',[(1000,['fixed','100']), (0,['fixed','100','foreign-package'])])
def test_root_cli_rejects_unprivileged_or_extra_renderer_arguments_before_any_io(monkeypatch,uid,argv):
    monkeypatch.setattr(os,'geteuid',lambda:uid);monkeypatch.setattr(sys,'argv',argv)
    with pytest.raises(SystemExit) as result:
        exec(compile(install.ROOT_INSTALL_SETUP,'fixed-combined-cli','exec'),{'__name__':'__main__'})
    assert result.value.code==77


def controlled_child_popen(receipt,calls,*,revoke_marker=None):
    child='''import json,sys,time
namespace={'__name__':'controlled_child'}
exec(sys.argv[1],namespace)
events=[]
lease=namespace['OriginalInstallLease'](time.monotonic()+5,interrupt=lambda:None,grace=lambda:None)
try:
 lease.acquire();lease.start()
 def package(current,plan,register_cancel):
  current();events.append('package');register_cancel(lambda:events.append('cancel'));time.sleep(.15);current();return ''
 if sys.argv[3]:
  def package(current,plan,register_cancel):
   current();events.append('package');register_cancel(lambda:events.append('cancel'))
   with open(sys.argv[3],'w') as f:f.write('entered')
   until=time.monotonic()+2
   while not lease.revoked and time.monotonic()<until:time.sleep(.01)
   return 'driver_installation_pending'
 try:result=namespace['run_combined'](lease,package=package,setup=lambda:events.append('setup'),loaded=lambda:True)
 except PermissionError:result=73
finally:lease.close()
with open(sys.argv[2],'w') as f:json.dump({'events':events,'exit':result},f)
sys.exit(result)
'''
    def popen(command,**options):
        calls.append(command)
        process=subprocess.Popen([sys.executable,'-I','-c',child,install.ROOT_INSTALL_SETUP,str(receipt),str(revoke_marker or '')],**options)
        if revoke_marker is None:return process
        class CannotSignalRoot:
            def __getattr__(self,name):return getattr(process,name)
            def terminate(self):raise PermissionError('Controlled root ownership: original pipe must cancel')
        return CannotSignalRoot()
    return popen


def test_actual_unprivileged_child_exercises_combined_payload_with_original_pipe(tmp_path,monkeypatch):
    monkeypatch.setattr(install.os,'geteuid',lambda:1000)
    receipt=tmp_path/'controlled-combined.json';calls=[]
    popen=controlled_child_popen(receipt,calls)
    assert install.install_driver(lambda:True,'v4l2loopback-dkms',popen=popen,tool=lambda names:names[0])==''
    assert len(calls)==1 and calls[0][0]=='/usr/bin/pkexec'
    assert json.loads(receipt.read_text())==dict(events=['package','setup'],exit=0)


def test_actual_pipe_loss_cancels_child_package_phase_without_setup_or_reauthorization(tmp_path,monkeypatch):
    monkeypatch.setattr(install.os,'geteuid',lambda:1000)
    receipt=tmp_path/'revoked-combined.json';marker=tmp_path/'package-entered';calls=[]
    popen=controlled_child_popen(receipt,calls,revoke_marker=marker)
    assert install.install_driver(lambda:not marker.exists(),'v4l2loopback-dkms',popen=popen,
        tool=lambda names:names[0])=='driver_installation_pending'
    assert len(calls)==1 and json.loads(receipt.read_text())==dict(events=['package','cancel'],exit=73)


def test_actual_parent_loss_interrupts_setup_and_rolls_back_only_private_owned_files(tmp_path,monkeypatch):
    monkeypatch.setattr(install.os,'geteuid',lambda:1000)
    root=tmp_path/'controlled-config-root';root.mkdir(mode=0o700)
    receipt=tmp_path/'setup-result.json';marker=tmp_path/'setup-entered';calls=[]
    child='''import json,os,signal,sys,time
from types import SimpleNamespace
namespace={'__name__':'controlled_child'}
exec(sys.argv[1],namespace)
signal.signal(signal.SIGALRM,namespace['installation_deadline_expired'])
lease=namespace['OriginalInstallLease'](time.monotonic()+5)
events=[];links=[];original=os.link
def link(*args,**kwargs):
 links.append(True)
 if len(links)==2:
  with open(sys.argv[3],'w') as f:f.write('setup entered')
  time.sleep(3)
 return original(*args,**kwargs)
os.link=link
def package(current,plan,register_cancel):
 current();events.append('package');register_cancel(lambda:events.append('cancel'));return ''
def setup():
 namespace['enable'](sys.argv[4],run=lambda *a,**k:SimpleNamespace(stdout=b'',returncode=0),tool='/controlled/modprobe')
try:
 lease.acquire();lease.start()
 try:result=namespace['run_combined'](lease,package=package,setup=setup,loaded=lambda:True)
 except TimeoutError:result=72
finally:lease.close()
with open(sys.argv[2],'w') as f:json.dump({'events':events,'exit':result,'links':len(links)},f)
sys.exit(result)
'''
    def popen(command,**options):
        calls.append(command)
        process=subprocess.Popen([sys.executable,'-I','-c',child,install.ROOT_INSTALL_SETUP,str(receipt),str(marker),str(root)],**options)
        class CannotSignalRoot:
            def __getattr__(self,name):return getattr(process,name)
            def terminate(self):raise PermissionError('Use original root cancellation lease')
        return CannotSignalRoot()
    assert install.install_driver(lambda:not marker.exists(),'v4l2loopback-dkms',popen=popen,
        tool=lambda names:names[0])=='driver_installation_pending'
    assert len(calls)==1 and json.loads(receipt.read_text())==dict(events=['package','cancel'],exit=72,links=2)
    assert not list(root.glob('etc/*/*.conf')) and not list(root.glob('etc/*/.magnolie-*'))
