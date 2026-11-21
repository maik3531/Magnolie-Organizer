"""Real GTK response and private preparation in an isolated synthetic profile."""
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
from time import monotonic_ns

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_photo_relocation_dialog import _confirm_gif_relocation_selection
from test_media_relocation_record import ANIMATED, GIF_FRAME, record
from test_file_authenticated_desktop import native
from test_file_desktop_receive import receiving, reconnect


@pytest.mark.parametrize('response',['yes','no','close','revoked','expired','destroy_parent','revoked_after_yes','expired_after_yes'])
def test_native_gif_dialog_is_one_shot_default_no_and_requires_live_yes(response):
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import GLib, Gtk

    assert Gtk.init_check()[0], 'Run under an isolated GTK display (Xvfb)'
    parent=Gtk.Window();parent.show()
    assert parent.get_mapped()
    owner=object();active=[True];now=[1];observed=[]
    action=NativePhotoDestinationAction(owner,lambda:now[0],native_current=lambda:active[0])
    selection=bind_relocation_selection((record(),),occupied=())

    def respond():
        dialogs=[window for window in Gtk.Window.list_toplevels()
            if isinstance(window,Gtk.MessageDialog) and window.get_transient_for() is parent]
        dialog,=dialogs
        observed.append((dialog.get_modal(),dialog.get_default_widget() is dialog.get_widget_for_response(Gtk.ResponseType.NO)))
        if response=='destroy_parent':parent.destroy()
        else:
            if response=='revoked':active[0]=False
            if response=='expired':now[0]=60_001
            dialog.response({'no':Gtk.ResponseType.NO,'close':Gtk.ResponseType.DELETE_EVENT}.get(response,Gtk.ResponseType.YES))
        return False

    # Refuse an unbound record before showing or consuming the native action.
    with pytest.raises(TransferError,match='native_confirmation_required'):
        _confirm_gif_relocation_selection(parent,(record(),),action,owner)
    GLib.idle_add(respond)
    try:
        if response in ('revoked','expired'):
            with pytest.raises(TransferError,match='native_guard_changed|action_not_current'):
                _confirm_gif_relocation_selection(parent,selection,action,owner)
        else:
            result=_confirm_gif_relocation_selection(parent,selection,action,owner)
            if response in ('yes','revoked_after_yes','expired_after_yes'):
                assert result.selection_sha256==selection[0].selection_sha256
                with pytest.raises(TransferError,match='native_confirmation_ended'):result._claim(object())
                if response=='revoked_after_yes':active[0]=False
                if response=='expired_after_yes':now[0]=60_001
                if response=='yes':
                    originals,require_original=result._claim(owner)
                    assert originals is selection and require_original() is True
                    active[0]=False
                    with pytest.raises(TransferError,match='native_guard_changed'):require_original()
                else:
                    with pytest.raises(TransferError,match='native_guard_changed|action_not_current'):result._claim(owner)
                with pytest.raises(TransferError,match='native_confirmation_ended'):result._claim(owner)
            else:assert result is None
        assert observed==[(True,True)]
        if response!='destroy_parent':
            with pytest.raises(TransferError,match='action_not_current'):
                _confirm_gif_relocation_selection(parent,selection,action,owner)
        assert not any(isinstance(window,Gtk.MessageDialog) and window.get_transient_for() is parent
            for window in Gtk.Window.list_toplevels())
    finally:parent.destroy()


def test_native_gif_dialog_prepares_only_its_fresh_original_selection(receiving,monkeypatch):
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import GLib, Gtk
    from magnolie_media_relocation_journal import ProtectedMediaRelocationJournal
    from magnolie_media_relocation_owner import ProtectedRelocationOwner
    from test_file_desktop_album_worker import ALBUM, phone_batches
    from test_photo_animation_layout import animation
    from test_photo_desktop_workflow import converge_controls

    assert Gtk.init_check()[0], 'Run under an isolated GTK display (Xvfb)'
    service,peer,channel,connection,root=receiving
    converge_controls(service,peer,channel)
    full=animation(receiving);original=replace(full.files[0],size=len(ANIMATED),sha256=sha256(ANIMATED).hexdigest())
    full=replace(full,files=(original,),total_bytes=len(ANIMATED))
    with phone_batches(receiving,[full],media_kinds={original.path:'animation'},content=ANIMATED) as (_,saved,_,_,errors):
        worker=connection.start_album_worker(connection.issue_receive_action(),ALBUM,True)
        assert worker.join(40) and worker.progress()['state']=='complete',worker.progress()
        assert not errors and len(saved)==1
    mappings,(mapping,),_=connection._mappings.candidate_page('images')
    choices=((mapping.association,mapping.protected_record_sha256),)
    jobs=connection._catalog.jobs();prefs=connection._preferences.read();messages=channel.send.call_count
    source=root/mapping.relative_path;target=root/'Animationen'/mapping.relative_path
    target.parent.parent.mkdir(mode=0o700);target.parent.mkdir(mode=0o700)
    preview=connection._preview_gif_relocation_selection(connection.issue_receive_action(),choices)
    parent=Gtk.Window();parent.show()
    alive=[True]
    def click(response):
        def respond():
            dialog,=(w for w in Gtk.Window.list_toplevels() if isinstance(w,Gtk.MessageDialog) and w.get_transient_for() is parent)
            dialog.response(response);return False
        GLib.idle_add(respond)
        action=NativePhotoDestinationAction(connection,lambda:monotonic_ns()//1_000_000,native_current=lambda:alive[0])
        return _confirm_gif_relocation_selection(parent,preview,action,connection)
    try:
        assert click(Gtk.ResponseType.NO) is None
        for unavailable in (None,preview[0].selection_sha256):
            with pytest.raises(TransferError,match='native_confirmation_required'):
                connection._prepare_confirmed_gif_relocation(unavailable,choices)
        declined=click(Gtk.ResponseType.YES);alive[0]=False
        with pytest.raises(TransferError,match='native_guard_changed'):
            connection._prepare_confirmed_gif_relocation(declined,choices)
        alive[0]=True
        stale=click(Gtk.ResponseType.YES)
        # A different valid animation on the same inode still needs its own confirmation.
        source.write_bytes(ANIMATED[:-1]+GIF_FRAME+b';')
        with pytest.raises(TransferError,match='confirmation_changed'):
            connection._prepare_confirmed_gif_relocation(stale,choices)
        source.write_bytes(ANIMATED)
        interrupted=click(Gtk.ResponseType.YES)
        original_preview=connection._preview_gif_relocation_selection
        with monkeypatch.context() as patch:
            def preview_then_change_catalog(*args,**kwargs):
                result=original_preview(*args,**kwargs)
                patch.setattr(connection._catalog,'jobs',lambda:())
                return result
            patch.setattr(connection,'_preview_gif_relocation_selection',preview_then_change_catalog)
            with pytest.raises(TransferError,match='confirmation_changed'):
                connection._prepare_confirmed_gif_relocation(interrupted,choices)
        with closing(ProtectedRelocationOwner(connection._authority)) as owner:
            assert owner.read_intent() is None
        accepted=click(Gtk.ResponseType.YES)
        intent,witness=connection._prepare_confirmed_gif_relocation(accepted,choices)
        with pytest.raises(TransferError,match='native_confirmation_ended'):
            connection._prepare_confirmed_gif_relocation(accepted,choices)
    finally:parent.destroy()
    assert source.read_bytes()==ANIMATED and not target.exists()
    assert connection._mappings.read()==mappings and connection._catalog.jobs()==jobs
    assert connection._preferences.read()==prefs and channel.send.call_count==messages
    with closing(ProtectedRelocationOwner(connection._authority)) as owner, closing(ProtectedMediaRelocationJournal(connection._authority)) as journal:
        assert owner.require_checkpoint(intent)==witness
        prepared=journal.read()
        assert prepared.records==preview and not prepared.attempts and not prepared.outcomes
    with reconnect(receiving) as fresh:
        reopened=fresh[3];out=fresh[2].send.call_count
        inode=source.stat().st_ino
        def inspect():return reopened._inspect_gif_relocation_recovery(reopened.issue_receive_action())
        observation,=inspect()
        assert (observation.ordinal,observation.state,observation.grants_write_authority)==(0,'prepared_at_source',False)
        new=b'a later local edit'
        source.write_bytes(new)
        observation,=inspect()
        assert (observation.state,observation.grants_write_authority)==('held',False)
        assert source.read_bytes()==new and source.stat().st_ino==inode and not target.exists()
        assert reopened._mappings.read()==mappings and fresh[2].send.call_count==out
        with (closing(ProtectedRelocationOwner(reopened._authority)) as owner,
                closing(ProtectedMediaRelocationJournal(reopened._authority)) as journal):
            assert owner.require_checkpoint(intent)==witness and journal.read()==prepared
