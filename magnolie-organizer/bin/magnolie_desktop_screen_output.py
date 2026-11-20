"""Read-only KWin output witness for the desktop-screen draft (#727).

This is not a backend detector and conveys no capture or input authority.
The future native caller must verify the KDE portal route independently, use
one original Wayland registry, and deliver settled initial and subsequent
snapshots including all membership changes. No product caller is wired here.
"""

import re
from threading import Event

from magnolie_desktop_screen_cast import ScreenCastTarget


_KWIN_VIRTUAL = re.compile(r'Virtual-virtual-xdp-kde-[A-Za-z0-9_.-]{0,231}')


def _outputs(snapshot):
    if type(snapshot) is not dict or len(snapshot) > 128 or any(
            type(id_) is not int or not 0 < id_ < 2**32 or type(name) is not str or
            not name or len(name) > 255 or not name.isprintable() for id_, name in snapshot.items()):
        raise ValueError('kwin_output_snapshot_invalid')
    return snapshot.copy()


class KWinOutputWitness:
    """One original observation, armed from a complete pre-Start baseline.

    Keys are registry global IDs, not connector names. For a live Wayland
    connection the adapter must keep immutable names per ID and report its
    ordered removals, never substitute a snapshot from a new connection.
    """

    def __init__(self, registry, baseline):
        if registry is None:
            raise ValueError('kwin_original_registry_required')
        self._registry = registry
        self._live = _outputs(baseline)
        self._baseline_names = frozenset(self._live.values())
        self._seen = self._live.copy()
        self._target = self._output = None
        self._lost = False
        self._withdrawn = Event()

    def observe(self, registry, snapshot):
        if self._lost or registry is not self._registry:
            return False
        try:
            live = _outputs(snapshot)
            if any(id_ in self._seen and (id_ not in self._live or self._seen[id_] != name)
                   for id_, name in live.items()):
                raise ValueError('kwin_registry_identity_discontinuous')
            if len(self._seen.keys() | live.keys()) > 256:
                raise ValueError('kwin_registry_history_limit')
        except ValueError:
            self.retire(registry)
            return False
        self._seen.update(live)
        self._live = live
        return self._correlate()

    def bind(self, target):
        """Bind once to the original target; the native name may arrive later."""
        if self._lost or self._target is not None or type(target) is not ScreenCastTarget or (
                target.mode != 'extend' or type(target.serial) is not int or not 0 < target.serial < 2**64 or
                type(target.mapping_id) is not str or
                _KWIN_VIRTUAL.fullmatch(target.mapping_id) is None or target.mapping_id in self._baseline_names):
            return False
        self._target = target
        return self._correlate()

    def mark_start(self):
        """Exclude names already reported before this portal Start."""
        if self._lost or self._target is not None:
            raise PermissionError('kwin_original_output_witness_unavailable')
        self._baseline_names = frozenset(self._seen.values())

    def _correlate(self):
        if self._target is not None:
            matches = [id_ for id_, name in self._seen.items() if name == self._target.mapping_id]
            if len(matches) > 1 or (matches and self._output is None and matches[0] not in self._live):
                self.retire(self._registry)
                return False
            if matches and self._output is None:
                self._output = matches[0]
            if self._output is not None and self._output not in self._live:
                self._withdrawn.set()
        return True

    def present(self, target):
        return target is self._target and self._output is not None and not self._withdrawn.is_set()

    @property
    def lost(self):
        return self._lost

    def removal_observed(self, target):
        """Only disappearance of the bound instance on the original registry.

        The caller must additionally account for Portal Close, reader, encoder,
        and transport drain; this result alone never releases the run slot.
        """
        return (not self._lost and target is self._target and self._output is not None and
                self._output not in self._live)

    def retire(self, registry):
        if registry is self._registry:
            self._lost = True
            self._withdrawn.set()


class KWinOutputFeed:
    """Consume bounded complete lines from one owned read-only observer.

    The caller must stop reading and close this feed on EOF, invalid records,
    or process/connection loss. No second observer can continue this feed.
    """

    def __init__(self):
        self._registry = object()
        self._live = {}
        self.witness = None
        self._closed = False
        self._taken = False

    def take_for_run(self):
        if self._taken or self._closed or self.witness is None or self.witness.lost:
            raise PermissionError('kwin_original_output_witness_unavailable')
        self._taken = True
        return self.witness

    def consume(self, raw):
        if self._closed:
            return False
        try:
            if type(raw) is not bytes or not raw.endswith(b'\n') or len(raw) > 270:
                raise ValueError('kwin_feed_invalid_line')
            if raw == b'ready\n' and self.witness is None:
                self.witness = KWinOutputWitness(self._registry, self._live)
                return True
            fields = raw[:-1].decode('ascii').split('\t')
            if len(fields) not in (2, 3) or not re.fullmatch(r'[1-9][0-9]{0,9}', fields[1]):
                raise ValueError('kwin_feed_invalid_record')
            id_ = int(fields[1])
            live = self._live.copy()
            if fields[0] == '+' and len(fields) == 3 and id_ not in live:
                live[id_] = fields[2]
            elif fields[0] == '-' and len(fields) == 2 and id_ in live and self.witness is not None:
                del live[id_]
            else:
                raise ValueError('kwin_feed_identity_invalid')
            self._live = _outputs(live)
            if self.witness is None or self.witness.observe(self._registry, self._live):
                return True
        except ValueError:
            pass
        self.close()
        return False

    def close(self):
        self._closed = True
        if self.witness is not None:
            self.witness.retire(self._registry)
