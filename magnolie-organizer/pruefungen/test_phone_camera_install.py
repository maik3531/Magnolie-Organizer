"""Controlled native PackageKit API; never install host packages."""
from pathlib import Path
from types import SimpleNamespace as NS
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import magnolie_phone_camera_install as install


def package_phase(*args,**kwargs):
    # Exercise the EXACT fixed root payload, but only controlled API adapters.
    namespace={'__name__':'controlled_install_test'}
    exec(compile(install.ROOT_INSTALL_SETUP,'fixed-install-and-setup','exec'),namespace)
    return namespace['install_package'](*args,**kwargs)


@pytest.mark.parametrize('family',['debian','ubuntu','linuxmint','arch','manjaro'])
def test_supported_distribution_has_only_fixed_driver_package(family):
    assert install.installation_plan(release=lambda:dict(ID=family),api=lambda:None)=='v4l2loopback-dkms'


def test_id_like_is_exact_and_unknown_appimage_host_has_manual_fallback():
    assert install.installation_plan(release=lambda:dict(ID='derivative',ID_LIKE='ubuntu debian'),api=lambda:None)=='v4l2loopback-dkms'
    for name in ('unknown','debian;install-other','fedora'):
        assert install.installation_plan(release=lambda:dict(ID=name),api=lambda:pytest.fail('unknown family used package API')) is None


def test_missing_system_integration_has_no_installation_offer():
    def unavailable():raise ImportError('controlled missing native PackageKit typelib')
    assert install.installation_plan(release=lambda:dict(ID='debian'),api=unavailable) is None
    def no_release():raise OSError('controlled missing os-release')
    assert install.installation_plan(release=no_release,api=lambda:pytest.fail('no release')) is None


def test_python39_without_os_release_helper_keeps_manual_fallback(monkeypatch):
    monkeypatch.delattr(install.platform,'freedesktop_os_release')
    assert install.installation_plan(api=lambda:pytest.fail('unknown Python3.9 host called PackageKit')) is None


class Timer:
    def __init__(self,seconds,callback):
        assert seconds==600
        self.callback=callback;self.cancelled=False
    def start(self):pass
    def cancel(self):self.cancelled=True


def controlled(*, packages=None, install_error=None, during=None, resolved_error=None, during_resolve=None):
    calls=[];timers=[];cancellable=NS(cancelled=False)
    cancellable.cancel=lambda:setattr(cancellable,'cancelled',True)
    package=NS(get_name=lambda:'v4l2loopback-dkms',get_id=lambda:'v4l2loopback-dkms;controlled;all;configured-repository')
    result=lambda error:NS(get_error_code=lambda:error,get_exit_code=lambda:0,
        get_package_array=lambda:[package] if packages is None else packages)
    class Client:
        def set_interactive(self,value):calls.append(('interactive',value))
        def resolve(self,filters,names,cancel,progress,data):
            calls.append(('resolve',filters,names));assert cancel is cancellable
            if during_resolve:during_resolve(timers[0],progress)
            return result(resolved_error)
        def install_packages(self,flags,ids,cancel,progress,data):
            calls.append(('install',flags,ids));assert cancel is cancellable
            if during:during(timers[0],progress)
            return result(install_error)
    pk=NS(Client=Client,FilterEnum=NS(NOT_INSTALLED=3,ARCH=18,NEWEST=16),
        TransactionFlagEnum=NS(ONLY_TRUSTED=1),ExitEnum=NS(SUCCESS=0))
    def timer(seconds,callback):
        value=Timer(seconds,callback);timers.append(value);return value
    return dict(api=lambda:(pk,NS(Cancellable=lambda:cancellable)),timer=timer),calls,timers,cancellable


def test_package_phase_uses_existing_root_approval_and_only_trusted_resolved_package():
    options,calls,timers,cancellation=controlled();guards=[]
    assert package_phase(lambda:guards.append(True),'v4l2loopback-dkms',**options)==''
    assert calls==[('interactive',False),('resolve',(1<<3)|(1<<18)|(1<<16),['v4l2loopback-dkms']),
        ('install',1<<1,['v4l2loopback-dkms;controlled;all;configured-repository'])]
    assert len(guards)>=4 and timers[0].cancelled and not cancellation.cancelled


@pytest.mark.parametrize('options',[dict(packages=[]),dict(install_error='permission_denied'),dict(resolved_error='no_backend')])
def test_native_denial_or_missing_package_does_not_claim_installation(options):
    arguments,calls,timers,_=controlled(**options)
    assert package_phase(lambda:True,'v4l2loopback-dkms',**arguments) in ('driver_installation_failed','driver_installation_unavailable')
    assert timers[0].cancelled
    if 'install_error' not in options:assert not any(call[0]=='install' for call in calls)


def test_unfamiliar_plan_never_loads_system_package_api():
    assert package_phase(lambda:True,'arbitrary-package',api=lambda:pytest.fail('unfamiliar package'))=='driver_installation_unavailable'


def test_deadline_cancels_native_transaction_and_reports_unconfirmed_state():
    arguments,calls,timers,cancellation=controlled(during=lambda timer,progress:timer.callback())
    assert package_phase(lambda:True,'v4l2loopback-dkms',**arguments)=='driver_installation_pending'
    assert cancellation.cancelled and timers[0].cancelled
    assert sum(call[0]=='install' for call in calls)==1


def test_revoked_context_prevents_installation_and_cancels_running_native_transaction():
    with pytest.raises(PermissionError):package_phase(lambda:False,'v4l2loopback-dkms',api=lambda:pytest.fail('revoked API'))
    current=[True]
    def revoke(timer,progress):current[0]=False;progress(None,None,None)
    arguments,_,timers,cancellation=controlled(during=revoke)
    with pytest.raises(PermissionError):package_phase(lambda:current[0],'v4l2loopback-dkms',**arguments)
    assert cancellation.cancelled and timers[0].cancelled


@pytest.mark.parametrize('packages',[
    [NS(get_name=lambda:'foreign-package')],
    [NS(get_name=lambda:'v4l2loopback-dkms'),NS(get_name=lambda:'v4l2loopback-dkms')],
])
def test_foreign_or_ambiguous_repository_result_never_installs(packages):
    arguments,calls,_,_=controlled(packages=packages)
    assert package_phase(lambda:True,'v4l2loopback-dkms',**arguments)=='driver_installation_unavailable'
    assert not any(call[0]=='install' for call in calls)


def test_missing_native_api_after_offer_keeps_manual_fallback():
    def unavailable():raise ValueError('controlled typelib removed')
    assert package_phase(lambda:True,'v4l2loopback-dkms',api=unavailable)=='driver_installation_unavailable'


def test_resolution_deadline_cancels_before_any_installation():
    arguments,calls,_,cancel=controlled(during_resolve=lambda timer,progress:timer.callback())
    assert package_phase(lambda:True,'v4l2loopback-dkms',**arguments)=='driver_installation_pending'
    assert cancel.cancelled and not any(call[0]=='install' for call in calls)


def test_original_context_revoked_while_resolving_never_starts_package_installation():
    current=[True]
    def revoke(timer,progress):current[0]=False;progress(None,None,None)
    arguments,calls,_,cancel=controlled(during_resolve=revoke)
    with pytest.raises(PermissionError):package_phase(lambda:current[0],'v4l2loopback-dkms',**arguments)
    assert cancel.cancelled and not any(call[0]=='install' for call in calls)
