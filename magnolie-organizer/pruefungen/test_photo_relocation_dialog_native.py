"""Real GTK response boundary in an isolated Xvfb, with no media I/O."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_photo_destination import NativePhotoDestinationAction
from magnolie_photo_relocation_dialog import _confirm_gif_relocation_selection
from test_media_relocation_record import record


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
