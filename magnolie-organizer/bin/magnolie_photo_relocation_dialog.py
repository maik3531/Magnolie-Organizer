"""Private GTK response for an exact GIF selection; no file or policy I/O."""
from dataclasses import dataclass, field
from gettext import gettext as _
import threading

from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_photo_destination import NativePhotoDestinationAction


@dataclass(frozen=True,eq=False,slots=True)
class _ConfirmedGifSelection:
    """In-process, one-shot handoff of the exact selection, not a media grant."""
    _selection: tuple
    _action: NativePhotoDestinationAction
    _owner: object
    _claimed: threading.Event = field(init=False,default_factory=threading.Event,repr=False)
    _gate: object = field(init=False,default_factory=threading.Lock,repr=False)

    def _claim(self,native_owner):
        with self._gate:
            if self._claimed.is_set() or native_owner is not self._owner:
                raise TransferError('photo_relocation_native_confirmation_ended')
            self._claimed.set()
        def require_original():
            self._action.validate(native_owner)
            return True
        require_original()
        return self._selection,require_original

    @property
    def selection_sha256(self):return self._selection[0].selection_sha256


def _confirm_gif_relocation_selection(parent, selection, action, native_owner):
    """Return a native handoff only for a live, explicit Yes.

    The caller owns the original action and the live UI guard (including the
    parent's lifetime after the response). This is not a write grant or receipt.
    """
    if (threading.current_thread() is not threading.main_thread()
            or type(action) is not NativePhotoDestinationAction
            or not callable(action._native_current)
            or bind_relocation_selection(selection, occupied=()) != selection):
        raise TransferError('photo_relocation_native_confirmation_required')
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
    if not isinstance(parent, Gtk.Window) or not parent.get_mapped():
        raise TransferError('photo_relocation_native_confirmation_required')
    action.consume(native_owner)
    destroyed = False

    def parent_destroyed(_parent):
        nonlocal destroyed
        destroyed = True

    handler = parent.connect('destroy', parent_destroyed)
    dialog = None
    try:
        dialog = Gtk.MessageDialog(transient_for=parent, modal=True, destroy_with_parent=True,
            message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO,
            text=_("Move selected GIF animations?"))
        dialog.format_secondary_text(_(
            "Move the %(count)d selected files into the Animations folder? "
            "The original files and edits are preserved. Choose No to leave them where they are.") % {'count': len(selection)})
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.get_widget_for_response(Gtk.ResponseType.NO).grab_focus()
        action.validate(native_owner)
        response = dialog.run()
        if response != Gtk.ResponseType.YES:
            return None
        if destroyed or not parent.get_mapped():
            raise TransferError('photo_relocation_native_confirmation_ended')
        action.validate(native_owner)
        return _ConfirmedGifSelection(selection,action,native_owner)
    finally:
        if dialog is not None:
            dialog.destroy()
        if parent.handler_is_connected(handler):
            parent.disconnect(handler)
