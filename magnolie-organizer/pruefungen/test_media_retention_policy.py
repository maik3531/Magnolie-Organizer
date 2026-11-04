"""Existing-store saved policy and bounded local maintenance, no phone grants."""
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_media_retention import NativeMediaRetention,saved_book_retention,maintain_native_media_trash
from magnolie_media_trash_ui import NativeMediaTrashUi
from magnolie_file_transfer import TransferError
from test_file_authenticated_desktop import native,bind
from test_file_desktop_receive import receiving
from test_photo_mappings import mappings
from test_media_trash import trash,prepare,paths
from test_save_restore_boundary import native as gui_native,Probe,fixture_data


def book(days):return dict(einstellungen=dict(papierkorb=dict(an=True,tage=days)))


def root(trash):
    directory=Path(trash[0][0].store.root)
    book_file=directory.parent/'daten.json'
    if not book_file.exists():
        from magnolie_telefon import canonical
        book_file.write_bytes(canonical(book(0)));book_file.chmod(0o600)
    return directory


def test_no_native_store_or_key_is_created_for_saving_settings(tmp_path):
    missing=tmp_path/'missing'
    with saved_book_retention(str(missing),book(7)) as result:assert result=={}
    assert not missing.exists()
    existing=tmp_path/'existing';existing.mkdir(mode=0o700)
    with saved_book_retention(str(existing),book(7)):pass
    assert list(existing.iterdir())==[]
    assert maintain_native_media_trash(str(missing))==0 and not missing.exists()


def test_policy_is_absent_until_commit_then_persists_and_is_encrypted(trash):
    directory=root(trash)
    with NativeMediaRetention(str(directory)) as policy:
        with policy.permit() as permit:assert permit is None
        with saved_book_retention(str(directory),book(7)):
            with policy.permit() as permit:assert permit is None
        with policy.permit() as permit:assert permit.require_current()==7
        blob=policy._db.execute('SELECT value FROM meta WHERE key=?',(policy.KEY,)).fetchone()[0]
        assert b'book_sha256' not in blob and b'"days"' not in blob
    with NativeMediaRetention(str(directory)) as reopened:
        with reopened.permit() as permit:assert permit.require_current()==7


def test_failed_book_save_leaves_old_positive_retention_paused(trash):
    directory=str(root(trash))
    with saved_book_retention(directory,book(7)):pass
    with pytest.raises(OSError,match='native save failed'):
        with saved_book_retention(directory,book(0)):raise OSError('native save failed')
    with NativeMediaRetention(directory) as policy:
        with policy.permit() as permit:assert permit is None


def test_postcommit_policy_error_is_repair_pending_not_a_failed_book_save(trash,monkeypatch):
    directory=str(root(trash));committed=[]
    def fail(*_args):raise OSError('derived publication failed')
    monkeypatch.setattr(NativeMediaRetention,'publish_saved',fail)
    with saved_book_retention(directory,book(7)) as result:committed.append(True)
    assert committed==[True] and result=={'repair_error':'OSError'}
    with NativeMediaRetention(directory) as policy:
        with policy.permit() as permit:assert permit is None


def test_stale_save_token_and_invalid_days_cannot_reenable_cleanup(trash):
    with NativeMediaRetention(str(root(trash))) as policy:
        old=policy.pause();new=policy.pause()
        with pytest.raises(TransferError,match='superseded'):policy.publish_saved(old,book(7))
        for days in (True,'7',1,-1,None):
            with pytest.raises(TransferError,match='saved_setting_required'):policy.publish_saved(new,book(days))
        with policy.permit() as permit:assert permit is None
        policy.publish_saved(new,book(0))
        with policy.permit() as permit:assert permit.require_current()==0


def test_cross_owner_writer_lease_serializes_setting_change_before_byte_release(trash):
    directory=str(root(trash))
    with saved_book_retention(directory,book(7)):pass
    with NativeMediaRetention(directory) as first,NativeMediaRetention(directory) as second:
        second._db.execute('PRAGMA busy_timeout=0')
        with first.permit() as permit:
            with pytest.raises(sqlite3.OperationalError,match='locked'):second.pause()
            assert permit.require_current()==7
        token=second.pause();second.publish_saved(token,book(0))
        with first.permit() as permit:assert permit.require_current()==0


def test_tampered_policy_is_held_and_never_overwritten_by_save(trash):
    directory=str(root(trash))
    with saved_book_retention(directory,book(7)):pass
    with NativeMediaRetention(directory) as policy:
        with policy._db:
            policy._db.execute('UPDATE meta SET value=? WHERE key=?',(b'broken-authentication',policy.KEY))
        with pytest.raises(Exception):policy.pause()
        with pytest.raises(Exception):
            with policy.permit():pytest.fail('Corrupt policy admitted cleanup')
        assert policy._db.execute('SELECT value FROM meta WHERE key=?',(policy.KEY,)).fetchone()==(b'broken-authentication',)


def test_actual_native_ui_maintenance_respects_never_then_saved_days_without_network(trash):
    owner=trash[4];owner._wall_clock_ms=lambda:1_600_000_000_000
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    snapshot,entry=owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    directory=str(root(trash));sent=trash[0][2].send.call_count
    ui=NativeMediaTrashUi(directory,lambda:True)
    request=dict(cmd='medien_papierkorb',request_id='retention_fixture_01',action='list')
    assert ui.handle(request)['total']==1 # First adoption reads native saved 0, not a default grant.
    with saved_book_retention(directory,book(0)):pass
    assert ui.handle(request)['total']==1 and payload.read_bytes()==b'hello'
    with saved_book_retention(directory,book(7)):pass
    assert ui.handle(request)['total']==0 and not payload.exists() and not original.exists()
    assert (original.parent/('.magnolie-purge-'+entry.operation)/'payload').stat().st_size==0
    assert trash[0][2].send.call_count==sent


def test_maintenance_guard_withdrawal_holds_bytes_and_never_uses_phone_consent(trash):
    owner=trash[4];owner._wall_clock_ms=lambda:1_600_000_000_000
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    directory=str(root(trash))
    with saved_book_retention(directory,book(7)):pass
    with pytest.raises(TransferError,match='native_ui_changed'):maintain_native_media_trash(directory,lambda:False)
    assert payload.read_bytes()==b'hello' and not original.exists()


def test_other_native_book_replacement_or_edit_cannot_inherit_cached_retention(trash):
    directory=root(trash);path=directory.parent/'daten.json'
    with saved_book_retention(str(directory),book(7)):pass
    replacement=path.with_name('fixture-replacement')
    replacement.write_bytes(path.read_bytes());replacement.chmod(0o600);replacement.replace(path)
    with NativeMediaRetention(str(directory)) as policy:
        with pytest.raises(TransferError,match='book_changed'):
            with policy.permit():pytest.fail('Changed native book reused old policy')
    with saved_book_retention(str(directory),book(0)):pass
    with NativeMediaRetention(str(directory)) as policy:
        with policy.permit() as permit:assert permit.require_current()==0


def test_missing_key_beside_existing_database_cannot_skip_pre_save_pause(trash):
    directory=root(trash)
    with saved_book_retention(str(directory),book(7)):pass
    key=directory/'storage.key';held=directory/'fixture-held-key';key.rename(held)
    try:
        with pytest.raises(FileNotFoundError):
            with saved_book_retention(str(directory),book(0)):pytest.fail('Save skipped required retention pause')
    finally:held.rename(key)


def test_actual_save_worker_publishes_only_after_commit_and_reports_derived_failure(gui_native,monkeypatch):
    import json
    import magnolie_optional_phone
    from magnolie_telefon import PhoneStore
    m=gui_native;directory=Path(m.daten_verzeichnis())/'telefon'
    PhoneStore(str(directory),'Synthetic policy writer') # Explicit fixture only.
    monkeypatch.setattr(magnolie_optional_phone,'available',lambda feature:feature=='photo_sync')
    monkeypatch.setattr(m,'erinnerungsdaten_schreiben',lambda **_kwargs:True)
    data=fixture_data('preserved note');data['einstellungen']['papierkorb']={'an':True,'tage':7}
    m.speichere_text(json.dumps(data));probe=Probe(m,data)
    assert probe.save(1,data)['committed']
    with NativeMediaRetention(str(directory)) as policy:
        with policy.permit() as permit:assert permit.require_current()==7
    data['einstellungen']['papierkorb']['tage']=0
    def fail(*_args):raise OSError('derived publication failed')
    monkeypatch.setattr(NativeMediaRetention,'publish_saved',fail)
    result=probe.save(2,data)
    assert result['ok'] and result['committed'] and result['repairPending']
    assert json.loads(Path(m.daten_datei()).read_text())['einstellungen']['papierkorb']['tage']==0
    with NativeMediaRetention(str(directory)) as policy:
        with policy.permit() as permit:assert permit is None


def test_actual_automatic_session_runs_native_maintenance_before_source_discovery(trash):
    from types import SimpleNamespace
    import threading
    from magnolie_file_desktop_connection import NativePhotoDesktopSession
    owner=trash[4];owner._wall_clock_ms=lambda:1_600_000_000_000
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    directory=str(root(trash))
    with saved_book_retention(directory,book(7)):pass
    session=object.__new__(NativePhotoDesktopSession)
    session.connection=SimpleNamespace(_authority=SimpleNamespace(binding=SimpleNamespace(native_directory=directory)),
        _closed=threading.Event(),_source_catalog=None)
    session._lock=threading.RLock();session._stop=threading.Event();session._video_enabled=False
    session._disable_pending=False;session._video_disable_pending=False;session._pending_mode=None
    session._state='albums';session._running=True;session._automatic_paused=False
    session._sync_activity=lambda active:None;session._notify=lambda:None;session._ensure_timer=lambda:None
    discovered=[]
    def discover(media_type):
        assert not payload.exists() # Cleanup precedes any new source READ/job.
        discovered.append(media_type);session._albums=[]
    session._discover=discover
    session._run('automatic',None)
    assert discovered==['images'] and not session._running and session._state!='held'
    assert not original.exists() and (original.parent/('.magnolie-purge-'+entry.operation)/'payload').stat().st_size==0


@pytest.mark.parametrize(('size','expected'),[(1,16),(30*1024*1024,13)])
def test_maintenance_preserves_existing_operation_and_byte_bounds(tmp_path,monkeypatch,size,expected):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import magnolie_media_retention as module
    from magnolie_media_trash import NativeMediaRetentionPermit
    entries=[SimpleNamespace(state='trashed',operation=str(index),mapping=SimpleNamespace(saved_size=size),
        expired=lambda days,now:True) for index in range(20)]
    completed=[]
    class Owner:
        def read(self):return object(),entries
        def _wall_clock_ms(self):return 1_800_000_000_000
        def issue_action(self):return object()
        def purge_expired(self,action,snapshot,operation,permit):
            completed.append(operation);return object(),SimpleNamespace(state='purged')
    @contextmanager
    def owner(*_args):yield Owner()
    class Policy:
        def __init__(self,*_args):pass
        def __enter__(self):return self
        def __exit__(self,*_args):pass
        def adopt_existing_saved(self,**_kwargs):return False
        @contextmanager
        def permit(self,current):yield NativeMediaRetentionPermit(7,lambda:7)
    monkeypatch.setattr(module,'NativeMediaRetention',Policy)
    monkeypatch.setattr(NativeMediaTrashUi,'_scopes',lambda self:('fixture',))
    monkeypatch.setattr(NativeMediaTrashUi,'_owner',owner)
    assert maintain_native_media_trash(str(tmp_path))==expected and len(completed)==expected


@pytest.mark.parametrize('days',[0,7])
def test_initial_automatic_maintenance_adopts_actual_saved_days_without_another_save(trash,days):
    from magnolie_telefon import canonical
    owner=trash[4];owner._wall_clock_ms=lambda:1_600_000_000_000
    snapshot,entry=prepare(trash);original,payload=paths(trash,entry)
    owner.trash(owner.issue_action(),snapshot,entry.operation,lambda:True)
    directory=root(trash);(directory.parent/'daten.json').write_bytes(canonical(book(days)))
    assert maintain_native_media_trash(str(directory))==(1 if days else 0)
    assert payload.exists()==(days==0) and not original.exists()


def test_adoption_never_revives_a_failed_save_pause_and_rejects_raced_book(trash):
    import json
    directory=root(trash);path=directory.parent/'daten.json'
    path.write_text(json.dumps(book(7)))
    with NativeMediaRetention(str(directory)) as policy:
        def race(raw):
            path.write_text(json.dumps(book(0)));return json.loads(raw)
        with pytest.raises(TransferError,match='lease_changed'):policy.adopt_existing_saved(race)
        with policy.permit() as permit:assert permit is None
        token=policy.pause()
        assert not policy.adopt_existing_saved()
        with policy.permit() as permit:assert permit is None
        policy.publish_saved(token,book(0))


@pytest.mark.parametrize('encrypted',[False,True])
def test_actual_native_load_unlock_helper_adopts_saved_book_not_mutable_ui_data(gui_native,monkeypatch,encrypted):
    import json
    from types import SimpleNamespace
    import magnolie_optional_phone
    from magnolie_telefon import PhoneStore
    m=gui_native;directory=Path(m.daten_verzeichnis())/'telefon'
    PhoneStore(str(directory),'Synthetic first adoption')
    monkeypatch.setattr(magnolie_optional_phone,'available',lambda feature:feature=='photo_sync')
    password='Synthetic fixture password' if encrypted else ''
    m.speichere_text(m.daten_text_erzeugen(book(0),password or None))
    probe=SimpleNamespace(_gesperrt=False,_ladefehler='',_kennwort=password,_aktuelle_daten=book(7))
    with NativeMediaRetention(str(directory)) as policy:
        if encrypted:
            assert not policy.adopt_existing_saved() # No unattended decrypt/default days.
    m.Fenster._medien_papierkorb_aufbewahrung_laden(probe)
    with NativeMediaRetention(str(directory)) as policy:
        with policy.permit() as permit:assert permit.require_current()==0
