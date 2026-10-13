"""Existing X11/XTest/libfakekey input APIs, scoped to one owned display."""
import ctypes
import ctypes.util
import os
import threading

from magnolie_kde_input import input_body, MODIFIERS

# KDE Connect's published specialKey table, not virtual-key guesses.
KEYSYMS = (0, 0xff08, 0xff09, 0xff0a, 0xff51, 0xff52, 0xff53, 0xff54,
    0xff55, 0xff56, 0xff50, 0xff57, 0xff0d, 0xffff, 0xff1b, 0xff15,
    0xff14, 0xffe3, 0xffe9, 0xffe1, 0xffeb,
    *range(0xffbe, 0xffca))
MODIFIER_KEYS = {'ctrl': 0xffe3, 'alt': 0xffe9, 'shift': 0xffe1, 'super': 0xffeb}


class X11Input:
    def __init__(self, display_name=None, fakekey_library=None):
        self.lock = threading.RLock()
        self.display = None
        self.held = None
        self.fake_context = None
        self.fake = None
        self.x = ctypes.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.test = ctypes.CDLL(ctypes.util.find_library('Xtst') or 'libXtst.so.6')
        self.x.XInitThreads.argtypes = []; self.x.XInitThreads.restype = ctypes.c_int
        self.x.XInitThreads()
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]; self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XCloseDisplay.argtypes = [ctypes.c_void_p]; self.x.XCloseDisplay.restype = ctypes.c_int
        self.x.XFlush.argtypes = [ctypes.c_void_p]; self.x.XFlush.restype = ctypes.c_int
        self.x.XDefaultScreen.argtypes = [ctypes.c_void_p]; self.x.XDefaultScreen.restype = ctypes.c_int
        self.x.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]; self.x.XDisplayWidth.restype = ctypes.c_int
        self.x.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]; self.x.XDisplayHeight.restype = ctypes.c_int
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]; self.x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.x.XGetPointerMapping.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
        self.x.XGetPointerMapping.restype = ctypes.c_int
        self.x.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]; self.x.XQueryKeymap.restype = ctypes.c_int
        self.test.XTestQueryExtension.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_int)] * 4
        self.test.XTestQueryExtension.restype = ctypes.c_int
        for name in ('XTestFakeButtonEvent', 'XTestFakeKeyEvent'):
            function = getattr(self.test, name)
            function.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            function.restype = ctypes.c_int
        self.test.XTestFakeRelativeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.test.XTestFakeRelativeMotionEvent.restype = ctypes.c_int
        self.test.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.test.XTestFakeMotionEvent.restype = ctypes.c_int
        self.display = self.x.XOpenDisplay(display_name.encode() if display_name else None)
        if not self.display:
            raise OSError('x11_input_display_unavailable')
        values = [ctypes.c_int() for _ in range(4)]
        if not self.test.XTestQueryExtension(self.display, *(ctypes.byref(value) for value in values)):
            self.close()
            raise OSError('x11_input_extension_unavailable')
        library = fakekey_library or ctypes.util.find_library('fakekey') or 'libfakekey.so.0'
        if library:
            try:
                self.fake = ctypes.CDLL(library)
                self.fake.fakekey_init.argtypes = [ctypes.c_void_p]; self.fake.fakekey_init.restype = ctypes.c_void_p
                self.fake.fakekey_press.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
                self.fake.fakekey_press.restype = ctypes.c_int
                self.fake.fakekey_release.argtypes = [ctypes.c_void_p]; self.fake.fakekey_release.restype = None
                self.fake.fakekey_reload_keysyms.argtypes = [ctypes.c_void_p]; self.fake.fakekey_reload_keysyms.restype = ctypes.c_int
                self.fake_context = self.fake.fakekey_init(self.display)
            except (OSError, AttributeError):
                self.fake = None

    @classmethod
    def create(cls):
        # XWayland does not grant control of the native Wayland desktop. That
        # session uses its existing native KDE/portal permission backend.
        if os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            return None
        try:
            return cls()
        except (OSError, AttributeError):
            return None

    def status(self):
        with self.lock:
            return {'pointer': bool(self.display), 'keys': bool(self.display),
                'keyboard': bool(self.display and self.fake_context), 'backend': 'x11',
                'reason': '' if self.fake_context else 'keyboard_text_library_unavailable'}

    def _button(self, button, down):
        if not self.test.XTestFakeButtonEvent(self.display, button, bool(down), 0):
            raise OSError('x11_input_rejected')

    def _key(self, code, down):
        if not code or not self.test.XTestFakeKeyEvent(self.display, code, bool(down), 0):
            raise OSError('x11_input_key_unavailable')

    def _click(self, button):
        self._button(button, True)
        try:
            self._button(button, False)
        except Exception:
            self.held = button
            raise

    def apply(self, body):
        body = input_body(body)
        with self.lock:
            if not self.display:
                raise OSError('x11_input_display_unavailable')
            mapping = (ctypes.c_ubyte * 20)()
            count = self.x.XGetPointerMapping(self.display, mapping, 20)
            left = 3 if count >= 3 and mapping[0] == 3 and mapping[2] == 1 else 1
            right = 1 if left == 3 else 3
            if body.get('singlehold'):
                if self.held is None:
                    self._button(left, True); self.held = left
            elif body.get('singlerelease'):
                self.release()
            elif any(body.get(flag) for flag in ('singleclick', 'doubleclick', 'middleclick', 'rightclick')):
                button = 2 if body.get('middleclick') else right if body.get('rightclick') else left
                self._click(button)
                if body.get('doubleclick'): self._click(button)
            elif body.get('scroll'):
                for axis, positive, negative in (('dy', 4, 5), ('dx', 7, 6)):
                    delta = body.get(axis, 0)
                    if delta: self._click(positive if delta > 0 else negative)
            elif 'key' in body or 'specialKey' in body:
                self._keyboard(body)
            elif 'x' in body:
                screen = self.x.XDefaultScreen(self.display)
                x = max(0, min(int(body['x']), max(0, self.x.XDisplayWidth(self.display, screen) - 1)))
                y = max(0, min(int(body['y']), max(0, self.x.XDisplayHeight(self.display, screen) - 1)))
                if not self.test.XTestFakeMotionEvent(self.display, screen, x, y, 0):
                    raise OSError('x11_input_rejected')
            elif not self.test.XTestFakeRelativeMotionEvent(self.display, int(body.get('dx', 0)), int(body.get('dy', 0)), 0):
                raise OSError('x11_input_rejected')
            self.x.XFlush(self.display)

    def _keyboard(self, body):
        if 'key' in body and not self.fake_context:
            raise OSError('keyboard_text_library_unavailable')
        original = (ctypes.c_ubyte * 32)()
        self.x.XQueryKeymap(self.display, original)
        pressed = []
        try:
            for modifier in MODIFIERS:
                if body.get(modifier):
                    code = self.x.XKeysymToKeycode(self.display, MODIFIER_KEYS[modifier])
                    if not code: raise OSError('x11_input_key_unavailable')
                    if not original[code // 8] & (1 << (code % 8)):
                        self._key(code, True); pressed.append(code)
            if 'specialKey' in body:
                code = self.x.XKeysymToKeycode(self.display, KEYSYMS[body['specialKey']])
                self._key(code, True)
                try: self._key(code, False)
                except Exception:
                    pressed.append(code)
                    raise
            else:
                self.fake.fakekey_reload_keysyms(self.fake_context)
                for character in body['key']:
                    raw = character.encode('utf-8')
                    try:
                        if not self.fake.fakekey_press(self.fake_context, raw, len(raw), 0):
                            raise OSError('x11_input_character_unavailable')
                    finally:
                        self.fake.fakekey_release(self.fake_context)
        finally:
            for code in reversed(pressed): self._key(code, False)
            self.x.XFlush(self.display)

    def release(self):
        with self.lock:
            if self.display and self.held is not None:
                button = self.held
                self._button(button, False)
                self.held = None
                self.x.XFlush(self.display)

    def close(self):
        with self.lock:
            if not self.display:
                return
            try:
                self.release()
            finally:
                if self.fake_context:
                    self.fake.fakekey_release(self.fake_context)
                    libc = ctypes.CDLL(None)
                    libc.free.argtypes = [ctypes.c_void_p]; libc.free.restype = None
                    libc.free(self.fake_context)
                    self.fake_context = None
                self.x.XCloseDisplay(self.display)
                self.display = None
