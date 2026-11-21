"""Private GTK response for an exact GIF selection; no file or policy I/O."""
from gettext import gettext as _
import threading

from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import bind_relocation_selection
from magnolie_photo_destination import NativePhotoDestinationAction


def _confirm_gif_relocation_selection(parent, selection, action, native_owner):
    """Return the displayed selection digest only for a live, explicit Yes.

    The caller owns the native action and its live UI guard. The digest is not
    a write grant or a receipt and cannot reopen this prompt on the same action.
    """
    if (threading.current_thread() is not threading.main_thread()
            or type(action) is not NativePhotoDestinationAction
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
        return selection[0].selection_sha256
    finally:
        if dialog is not None:
            dialog.destroy()
        if parent.handler_is_connected(handler):
            parent.disconnect(handler)
