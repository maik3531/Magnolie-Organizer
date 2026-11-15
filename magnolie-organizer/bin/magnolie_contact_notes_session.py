"""Explicit known-choice session composition, never startup/setup permission.

Native host callbacks only attach/detach an owned in-memory slot under the book
gate. No tree/service/thread/dialog/phone store is constructed or started here.
"""
import os
import threading

from cryptography.exceptions import InvalidTag

from magnolie_contact_notes_consent import NativeNotesChoiceStore
from magnolie_contact_notes_controller import NativeNotesController
from magnolie_contact_notes_key import NativeNotesExistingJournalKey
from magnolie_contact_notes_return import NativeNotesAckIntents
from magnolie_contact_notes_ui import NativeNotesUiSaveSession


class NativeNotesNativeSession:
    def __init__(self, profile_root, primary_path, choices, owned_text, book_gate, attach, detach,
                 require_usable=lambda: None):
        for path in (profile_root, primary_path):
            if type(path) is not str or not os.path.isabs(path) or os.path.normpath(path) != path:
                raise TypeError('notes_session_native_paths_required')
        if (type(choices) is not NativeNotesChoiceStore or
                not all(callable(value) for value in (owned_text, book_gate, attach, detach, require_usable))):
            raise TypeError('notes_session_native_dependencies_required')
        self.root, self.primary_path, self.choices = profile_root, primary_path, choices
        self._text, self._book_gate, self._attach, self._detach, self._usable = owned_text, book_gate, attach, detach, require_usable
        self._key = NativeNotesExistingJournalKey(os.path.join(profile_root, 'telefon'))
        self._lifecycle, self._state = threading.RLock(), threading.RLock()
        self._stopped = self._attached = False
        self.controller = self.ui = None

    @property
    def is_active(self):
        with self._state:
            return self._attached and not self._stopped and self.controller is not None and self.controller._active

    def _existing_key(self):
        # Separate short state lock: journal callbacks never wait on lifecycle
        # while holding work/book (admission order is lifecycle -> book).
        with self._state:
            if self._stopped: return None
        self._usable()
        key = self._key.read_existing()
        with self._state:
            return None if self._stopped else key

    def try_attach_known(self):
        with self._lifecycle:
            with self._state:
                if self._stopped: return 'stopped'
                if self._attached: return 'attached' if self.controller._active else 'stopped'
            controller = ui = None
            try:
                with self._book_gate():
                    self._usable()
                    selected = self.choices._discovery_sources(None)
                    if selected is None: return 'no-choice'
                    binding, sources = selected
                    if binding != self.primary_path or not sources: return 'held'
                    if self._existing_key() is None: return 'key-missing'
                    # Constructors do not create roots, keys, history or listeners.
                    outcomes = NativeNotesAckIntents(os.path.join(self.root, 'notes-original-outcomes'), self._existing_key)
                    controller = NativeNotesController(self.choices, outcomes, self._book_gate)
                    ui = NativeNotesUiSaveSession(controller, self._text)
                    self._usable()
                    if self.choices._discovery_sources(None) != selected:
                        raise PermissionError('notes_session_context_changed')
                    if self._attach(self, controller, ui) is not True:
                        raise PermissionError('notes_session_slot_occupied')
                    with self._state:
                        self.controller, self.ui, self._attached = controller, ui, True
                return 'attached'
            except (PermissionError, TypeError, ValueError, OSError, RuntimeError, InvalidTag):
                if ui is not None: ui.stop()
                if controller is not None: controller.stop()
                return 'held'

    def stop(self):
        with self._lifecycle:
            with self._state:
                if self._stopped: return
                self._stopped, self._attached = True, False
                controller, ui = self.controller, self.ui
            if ui is not None: ui.stop()
            if controller is not None: controller.stop()
            with self._book_gate():
                self._detach(self, controller, ui)  # Owned memory only; no history deletion.
