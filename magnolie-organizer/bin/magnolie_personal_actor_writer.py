"""Native-only serial writer invocation, never a wire/IPC/request object.

The GUI must retain its pristine mutation boundary until its actual save result.
Only metadata is retained here; candidate bytes remain in the normal bounded
native save queue. The controller rechecks the exact payload under its live
source gate at invocation, before the existing worker touches the document.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NativeHistoricalWriterInvocation:
    source: object = field(repr=False)
    registry: object = field(repr=False)
    handle: object = field(repr=False)
    claim_token: str = field(repr=False)

    def write(self, payload, native_writer):
        return self.source.write_personal_actor_historical_restore_save(
            self.registry, self.handle, self.claim_token, payload, native_writer)
