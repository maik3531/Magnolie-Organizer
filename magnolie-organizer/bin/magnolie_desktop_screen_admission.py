"""One explicit GTK admission on the original reader. Not a product entry point."""

from threading import Event, Lock, current_thread, main_thread
from time import monotonic

from magnolie_desktop_screen_attempt import DesktopScreenDraftAttempt
from magnolie_desktop_screen_control import MAX_SETUP_MS, DesktopScreenSetupWindow
from magnolie_desktop_screen_portal import MONITOR, WINDOW
from magnolie_phone_screen_window import GLib, Gtk


class _NativeX11PortalParent:
    """Derive the portal parent from the original GTK window, never a caller ID."""
    def __init__(self, parent):
        if current_thread() is not main_thread() or not isinstance(parent, Gtk.Window):
            raise RuntimeError('desktop_screen_native_main_required')
        self._parent = parent
        self._window = parent.get_window()
        try:
            import gi
            gi.require_version('GdkX11', '3.0')
            from gi.repository import GdkX11
        except (ImportError, ValueError) as exc:
            raise PermissionError('desktop_screen_native_parent_export_unavailable') from exc
        if not isinstance(self._window, GdkX11.X11Window):
            # Wayland must use its own native export; there is no X11 fallback.
            raise PermissionError('desktop_screen_native_parent_export_unavailable')
        self._xid = self._window.get_xid()
        self.require_current()
        self.handle = f'x11:{self._xid:x}'

    def require_current(self):
        if current_thread() is not main_thread():
            raise RuntimeError('desktop_screen_native_main_required')
        if (not self._xid or self._window.is_destroyed() or self._parent.get_window() is not self._window or
                not self._parent.get_visible() or not self._parent.get_mapped() or
                self._window.get_xid() != self._xid):
            raise PermissionError('desktop_screen_native_parent_retired')


class DesktopScreenDraftAdmission:
    """Arm only after a native action selects this exact paired phone and mode.

    The GTK main thread owns start, close and cleanup. No request opens a
    portal until this separate native dialog is accepted. The caller supplies
    the existing logind observer and its own exported portal parent handle.
    """

    def __init__(self, dispatch, peer_id, channel, *, mode, bus, provider,
                 parent, parent_handle, session_lock, ended, require_parent=None, selection=None,
                 require_owner=None):
        if current_thread() is not main_thread() or not isinstance(parent, Gtk.Window):
            raise RuntimeError('desktop_screen_native_main_required')
        sources = {'monitor': MONITOR, 'window': WINDOW}
        if (not parent.get_visible() or not parent.get_realized() or not parent_handle or bus is None or
                provider.owner is None or provider.screen_version < 3 or
                not (provider.extended_output if mode == 'extend' else provider.mirror_sources & sources.get(mode, 0))):
            raise PermissionError('desktop_screen_native_mode_unavailable')
        self._unlocked = session_lock.claim()
        self._stopping = Event()
        self._approval = Event()
        self._state = Lock()
        self._pending = self._attempt = self._dialog = self._confirm = None
        self._showing = False
        self._terminal = False
        self._cleanup = None
        self._ended = ended
        self._parent = parent
        self._require_parent = require_parent or (lambda: None)
        self._require_owner = require_owner or (lambda: None)
        self._mode, self._wire_mode = mode, 2 if mode == 'extend' else 1
        self._bus, self._provider, self._parent_handle = bus, provider, parent_handle
        self._deadline = monotonic() + MAX_SETUP_MS / 1000
        self._original = dispatch.attach(peer_id, channel, self._receive, selection=selection)
        self._destroy_id = parent.connect('destroy', lambda _: self.close())
        self._unmap_id = parent.connect('unmap', self._parent_unmapped) if require_parent else None
        GLib.timeout_add(25, self._tick)

    def _parent_unmapped(self, _parent):
        # A quick hide/show must not revive a pending local confirmation.
        # After approval the active transfer owns its normal stop lifecycle.
        if self._attempt is None:
            self.close()

    def _require_live(self, original):
        if self._stopping.is_set():
            raise PermissionError('desktop_screen_native_admission_retired')
        original.require_current()
        self._unlocked()
        self._require_owner()
        if self._stopping.is_set():
            raise PermissionError('desktop_screen_native_admission_retired')

    def _require_approved(self):
        if not self._approval.is_set():
            raise PermissionError('desktop_screen_native_approval_required')
        self._require_live(self._original)

    def _receive(self, original, body, packet):
        self._require_live(original)
        with self._state:
            if self._stopping.is_set() or original.retired.is_set():
                return False
            attempt = self._attempt
            if attempt is None:
                if self._pending is not None or body['op'] != 'request' or body['mode'] != self._wire_mode:
                    return False
                try:
                    setup = DesktopScreenSetupWindow.receive(body, self._deadline)
                except TimeoutError:
                    return False
                self._pending = body, setup
                return True
        return attempt.receive(original.channel, packet)

    def _tick(self):
        if not self._stopping.is_set():
            try:
                self._require_live(self._original)
                with self._state:
                    pending, attempt = self._pending, self._attempt
                if attempt is None:
                    self._require_parent()
                    deadline = pending[1].deadline if pending is not None else self._deadline
                    if monotonic() >= deadline or not self._parent.get_visible():
                        self.close()
                    elif pending is not None and not self._showing:
                        self._prompt()
            except Exception:
                self.close()
        if not self._stopping.is_set() or (self._attempt is not None and self._cleanup is None):
            return True
        cleanup = self._cleanup
        # Portal Close does not observe compositor output removal. An actual
        # submitted virtual Start has no reusable slot in the draft until a
        # compositor-specific cleanup witness can establish that removal.
        clean = cleanup is None or (cleanup.transport_drained and cleanup.local.portal_closed and
            cleanup.local.reader_drained and cleanup.local.encoder_drained and not cleanup.local.virtual_start_submitted)
        if clean and not self._original.release():
            return True  # Retirement raced the last reader handoff.
        self._terminal = True  # Unconfirmed cleanup deliberately keeps the slot.
        for handler in (self._destroy_id, self._unmap_id):
            if handler is not None and self._parent.handler_is_connected(handler):
                self._parent.disconnect(handler)
        self._ended(cleanup)
        return False

    def _prompt(self):
        self._showing = True
        title, action = {
            'monitor': ('Bildschirm auf dem Telefon spiegeln?', 'Bildschirm auswählen'),
            'window': ('Fenster auf dem Telefon spiegeln?', 'Fenster auswählen'),
            'extend': ('Telefon als zusätzlichen Monitor verwenden?', 'Zusätzlichen Monitor anfragen'),
        }[self._mode]
        dialog = self._dialog = Gtk.MessageDialog(transient_for=self._parent, modal=True,
            destroy_with_parent=True, message_type=Gtk.MessageType.QUESTION, text=title)
        dialog.format_secondary_text('Gekoppeltes Gerät: ' + str(self._original.label)[:160])
        dialog.add_button('Abbrechen', Gtk.ResponseType.CANCEL)
        self._confirm = dialog.add_button(action, Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        dialog.connect('response', self._respond)
        dialog.connect('destroy', lambda _: self.close())
        dialog.show_all()

    def _respond(self, dialog, response):
        if (dialog is not self._dialog or response != Gtk.ResponseType.ACCEPT or
                self._approval.is_set()):
            self.close()
            return
        try:
            self._require_live(self._original)
            self._require_parent()
            with self._state:
                request, setup = self._pending
            deadline = setup.deadline
            if monotonic() >= deadline or not self._parent.get_visible() or not dialog.get_visible():
                raise PermissionError('desktop_screen_native_approval_expired')
            self._approval.set()
            attempt = DesktopScreenDraftAttempt(self._original.channel, request, self._require_approved,
                bus=self._bus, provider=self._provider, mode=self._mode, parent_window=self._parent_handle,
                width=960, height=540, deadline=deadline, ended=self._attempt_ended,
                require_terminal_parent=self._original.require_terminal_parent, setup=setup)
            with self._state:
                self._attempt = attempt
            attempt.begin()
            self._confirm.hide()
            dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).set_label('Übertragung beenden')
            dialog.set_property('text', 'Bildschirmübertragung')
            dialog.set_modal(False)
        except Exception:
            self.close()

    def _attempt_ended(self, result):
        self._cleanup = result
        self.close()

    def close(self):
        if current_thread() is not main_thread():
            raise RuntimeError('desktop_screen_native_main_required')
        if self._stopping.is_set() or self._terminal:
            return
        self._stopping.set()
        self._original.retire()
        with self._state:
            self._pending = None
            attempt = self._attempt
        if attempt is not None:
            attempt.stop()
        dialog, self._dialog = self._dialog, None
        if dialog is not None and not dialog.in_destruction():
            dialog.destroy()
