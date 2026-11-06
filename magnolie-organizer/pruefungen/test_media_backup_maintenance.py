"""Actual local catalogs, saved-book policy and caller-owned maintenance lanes."""
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from test_media_backups import vault,mappings,receiving,native,add_all,idle,DAY_MS
from magnolie_media_backups import NativeMediaBackups,NativeMediaBackupMaintenance
from magnolie_media_backup_codec import NativeBackupIdleObservation,MIN_IDLE_MS,MIN_AVAILABLE_BYTES
from magnolie_media_backup_idle import NativeLinuxBackupMaintenanceWorker
import magnolie_media_backups as backups_module
from magnolie_media_retention import NativeMediaRetention,saved_book_retention
from magnolie_telefon import canonical


def prepared(vault,monkeypatch):
    fixture,_,records,owner,raw,now=vault
    versions=add_all(vault);owner.close()
    constructor=NativeMediaBackups.__init__
    def init(self,*args,**kwargs):
        kwargs.setdefault('clock_ms',lambda:now[0]);constructor(self,*args,**kwargs)
    monkeypatch.setattr(NativeMediaBackups,'__init__',init)
    return fixture,records,versions,raw,now,fixture[3]._authority.binding.native_directory


def test_actual_maintenance_uses_saved_days_strict_age_dedup_and_verified_new_representation(vault,monkeypatch,tmp_path):
    fixture,records,versions,raw,now,directory=prepared(vault,monkeypatch)
    maintenance=NativeMediaBackupMaintenance(directory)
    def days(value):
        book=dict(einstellungen=dict(papierkorb=dict(an=True,tage=value)))
        with saved_book_retention(directory,book):
            (Path(directory).parent/'daten.json').write_bytes(canonical(book))
    original={record.relative_path:(fixture[4]/record.relative_path).read_bytes() for record in records}
    now[0]+=30*DAY_MS;assert maintenance.run_once(idle())['attempted']==0
    now[0]+=DAY_MS;days(30);assert maintenance.run_once(idle())['attempted']==0
    days(0);result=maintenance.run_once(idle());assert result['compressed']==result['attempted']==1 and result['held']==0
    assert maintenance.run_once(idle())['attempted']==0
    with NativeMediaBackups(records[0].destination,fixture[3]._authority.protection,lambda:True) as reader:
        assert reader.versions()==tuple(sorted(versions,key=lambda row:row.id))
        obj=reader._record('objects',versions[0].object_key)
        assert obj['codec']=='xz' and obj['raw_retired'] and (fixture[4]/'Backup'/obj['raw_name']).stat().st_size==0
        import os
        fd=os.open(tmp_path/'new-original-after-maintenance',os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
        try:
            reader.restore(versions[0],fd);assert os.pread(fd,len(raw),0)==raw
        finally:os.close(fd)
    assert original=={record.relative_path:(fixture[4]/record.relative_path).read_bytes() for record in records}


def test_maintenance_holds_active_copy_and_input_bound_without_touching_backup_bytes(vault,monkeypatch):
    fixture,_,_,_,now,directory=prepared(vault,monkeypatch);now[0]+=31*DAY_MS
    folder=fixture[4]/'Backup';before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    maintenance=NativeMediaBackupMaintenance(directory)
    with NativeMediaRetention(directory) as copy:
        with copy.active_copy_permit(lambda:True) as permit:
            assert permit is not None and maintenance.run_once(idle())['attempted']==0
    monkeypatch.setattr(maintenance,'MAX_INPUT_BYTES',1)
    assert maintenance.run_once(idle())['attempted']==0
    assert before=={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}


def test_idle_worker_single_lane_and_native_stop_ends_without_running_maintenance(tmp_path):
    entered=threading.Event();release=threading.Event();calls=[]
    class Probe:
        def observe(self):
            entered.set();assert release.wait(5)
            return NativeBackupIdleObservation(MIN_IDLE_MS,0,MIN_AVAILABLE_BYTES)
    worker=NativeLinuxBackupMaintenanceWorker(str(tmp_path/'never-created'),probe=Probe)
    worker._maintenance=SimpleNamespace(run_once=lambda *args:calls.append(True))
    assert worker.start(lambda:True) and entered.wait(5)
    assert worker.start(lambda:True) is False
    worker.stop();release.set();assert worker.join(5)
    assert not calls and worker.start(lambda:True) is False and not (tmp_path/'never-created').exists()


def test_idle_worker_missing_resource_evidence_never_runs_or_creates_native_root(tmp_path):
    calls=[]
    worker=NativeLinuxBackupMaintenanceWorker(str(tmp_path/'never-created'),probe=lambda:SimpleNamespace(observe=lambda:None))
    worker._maintenance=SimpleNamespace(run_once=lambda *args:calls.append(True))
    assert worker.start(lambda:True) and worker.join(5)
    assert not calls and worker.last_error is not None and not (tmp_path/'never-created').exists()


def test_actual_low_priority_worker_runs_single_verified_pass_without_lowering_ui_priority(vault,monkeypatch):
    import os
    _,_,_,_,now,directory=prepared(vault,monkeypatch);now[0]+=31*DAY_MS
    class Probe:
        def observe(self):return NativeBackupIdleObservation(MIN_IDLE_MS,0,MIN_AVAILABLE_BYTES)
    priority=os.getpriority(os.PRIO_PROCESS,threading.get_native_id())
    worker=NativeLinuxBackupMaintenanceWorker(directory,probe=Probe)
    try:
        assert worker.start(lambda:True) and worker.join(20)
        assert worker.last_error is None and worker.last_result['compressed']==1
    finally:
        worker.stop();assert worker.join(5)
    assert os.getpriority(os.PRIO_PROCESS,threading.get_native_id())==priority


def test_maintenance_idle_withdrawal_keeps_original_then_resumes_and_missing_catalog_stays_held(vault,monkeypatch):
    fixture,records,versions,raw,now,directory=prepared(vault,monkeypatch);now[0]+=31*DAY_MS
    maintenance=NativeMediaBackupMaintenance(directory);allowed=[True]
    original=backups_module.compress_candidate
    def compress(*args,**kwargs):
        result=original(*args,**kwargs);allowed[0]=False;return result
    monkeypatch.setattr(backups_module,'compress_candidate',compress)
    with pytest.raises(ValueError,match='maintenance_ended'):maintenance.run_once(idle(),lambda:allowed[0])
    folder=fixture[4]/'Backup';objects=list(folder.glob('object-*.raw'))
    assert len(objects)==1 and objects[0].read_bytes()==raw
    with NativeMediaBackups(records[0].destination,fixture[3]._authority.protection,lambda:True) as reader:
        assert reader.versions()==tuple(sorted(versions,key=lambda row:row.id))
        assert reader._record('objects',versions[0].object_key)['codec']=='raw'
    monkeypatch.setattr(backups_module,'compress_candidate',original);allowed[0]=True
    assert maintenance.run_once(idle())['compressed']==1
    held=folder.with_name('Backup-maintenance-original-held');folder.rename(held)
    before={p.name:p.read_bytes() for p in held.iterdir() if p.is_file()}
    result=maintenance.run_once(idle());assert result['attempted']==0 and result['held']>=1
    assert not folder.exists() and before=={p.name:p.read_bytes() for p in held.iterdir() if p.is_file()}


@pytest.mark.parametrize('vault',('random',),indirect=True)
def test_no_savings_trial_retains_original_bytes_and_does_not_repeat(vault,monkeypatch):
    fixture,records,versions,raw,now,directory=prepared(vault,monkeypatch);now[0]+=31*DAY_MS
    maintenance=NativeMediaBackupMaintenance(directory)
    result=maintenance.run_once(idle());assert result['attempted']==1 and result['compressed']==0
    assert maintenance.run_once(idle())['attempted']==0
    with NativeMediaBackups(records[0].destination,fixture[3]._authority.protection,lambda:True) as reader:
        obj=reader._record('objects',versions[0].object_key)
        assert obj['trial'] and obj['codec']=='raw' and not obj['raw_retired']
        assert (fixture[4]/'Backup'/obj['raw_name']).read_bytes()==raw
