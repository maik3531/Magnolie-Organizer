"""Private GTK response for an exact GIF selection; no file or policy I/O."""
from dataclasses import dataclass, field
from gettext import gettext as _
import threading

from magnolie_file_transfer import TransferError
from magnolie_media_relocation_record import (GifRelocationFolderPlan, MissingGifTargetDraft,
    bind_gif_relocation_folder_plan, bind_relocation_selection)
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


@dataclass(frozen=True,eq=False,slots=True)
class _ConfirmedGifFolderPlan(_ConfirmedGifSelection):
    """Distinct handoff; the existing rename preparation does not accept it."""
    _selection: GifRelocationFolderPlan

    @property
    def selection_sha256(self):return self._selection.selection_sha256


def _confirm_gif_relocation_selection(parent, selection, action, native_owner):
    """Return a native handoff only for a live, explicit Yes.

    The caller owns the original action and the live UI guard (including the
    parent's lifetime after the response). This is not a write grant or receipt.
    """
    if bind_relocation_selection(selection, occupied=()) != selection:
        raise TransferError('photo_relocation_native_confirmation_required')
    detail=_("Move the %(count)d selected files into the Animations folder? "
        "The original files and edits are preserved. Choose No to leave them where they are.") % {'count': len(selection)}
    if _run_gif_confirmation(parent,action,native_owner,detail,selection):
        return _ConfirmedGifSelection(selection,action,native_owner)
    return None


def _confirm_gif_folder_plan(parent,plan,action,native_owner):
    """Disclose missing folder creation before collecting the original Yes."""
    if (type(plan) is not GifRelocationFolderPlan or type(plan.members) is not tuple or not plan.members
            or type(plan.members[0]) is not MissingGifTargetDraft
            or bind_gif_relocation_folder_plan(plan.members,plan.members[0].destination)!=plan
            or not any(member.target_parents.missing for member in plan.members)):
        raise TransferError('photo_relocation_native_confirmation_required')
    detail=_("Create the missing folders in the Animations folder and move the %(count)d selected files? "
        "Choose No to leave the files and folders unchanged.") % {'count': len(plan.members)}
    if _run_gif_confirmation(parent,action,native_owner,detail,plan.members):
        return _ConfirmedGifFolderPlan(plan,action,native_owner)
    return None


def _run_gif_confirmation(parent,action,native_owner,detail,members):
    if (threading.current_thread() is not threading.main_thread()
            or type(action) is not NativePhotoDestinationAction or not callable(action._native_current)):
        raise TransferError('photo_relocation_native_confirmation_required')
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import GLib, Gtk, Pango
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
        dialog.format_secondary_text(detail)
        rows=Gtk.ListStore(str,str)
        for member in members:
            label=member.source.rsplit('/',1)[-1]
            tooltip=GLib.markup_escape_text(member.source+'\n'+member.target)
            rows.append((label,tooltip))
        listing=Gtk.TreeView(model=rows)
        listing.set_tooltip_column(1)
        listing.get_selection().set_mode(Gtk.SelectionMode.NONE)
        renderer=Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
        listing.append_column(Gtk.TreeViewColumn(_("Files to move"),renderer,text=0))
        scroller=Gtk.ScrolledWindow()
        scroller.set_min_content_height(140)
        scroller.add(listing)
        dialog.get_content_area().pack_start(scroller,True,True,6)
        scroller.show_all()
        dialog.set_default_response(Gtk.ResponseType.NO)
        dialog.get_widget_for_response(Gtk.ResponseType.NO).grab_focus()
        action.validate(native_owner)
        response = dialog.run()
        if response != Gtk.ResponseType.YES:
            return False
        if destroyed or not parent.get_mapped():
            raise TransferError('photo_relocation_native_confirmation_ended')
        action.validate(native_owner)
        return True
    finally:
        if dialog is not None:
            dialog.destroy()
        if parent.handler_is_connected(handler):
            parent.disconnect(handler)
