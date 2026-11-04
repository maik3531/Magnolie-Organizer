# Notes connection controls and device status (Refs #374)

Personal synchronization belongs to the paired Notes phone in Organizer settings
under **Magnolie Notes phone connection**, not to the device-status dialog or
KDE Connect. Its existing shared-preference and legacy handlers, directions,
automatic/manual choices, deletion exception and durable-save-before-sync rules
are retained. Rendering either view does not change consent or start a run.

Linux and Windows use the same tested device-status DOM layout and matching
status CSS: phone/battery beside the status table, two label/value pairs on wide
views, responsive stacking on narrow views, bounded scrolling and an independent
Refresh/Close footer. No whole-platform frontend is overwritten to achieve this.
Source parity is asserted by the shared dual-platform DOM/CSS regression test.

Twelve source-host cases cover both platforms, English/German, legacy/shared
preferences and offline display. Both full frontend suites also pass, including
the existing manual synchronization save-ACK gate. These are not installed
WebKit/WebView2 GUI or physical-device acceptance.

Device status also shows the last confirmed successful personal synchronization
with regional date/time and its actual manual/automatic trigger, including offline.
The native peer-state projection is refreshed on opening and Refresh. The display
does not consult connection times, configured automatic mode, incoming reports or
unscoped frontend report history. Missing historical proof stays **Unknown**.

The native metadata is bound to the current phone public key and recorded only
after native actor completion or an accepted/duplicate ACK of a validated outgoing
complete/no-error report matching a known run's trigger. Native actor transport ACKs
are not completion proof. Current actor admission is manual-only; ordinary reports
retain their actual supported trigger. Supporting `auto_connection` in display
metadata does not widen the legacy Linux transport policy.

Failures, rejected/stale/unbound ACKs and replayed or older completions cannot
advance the last success. Changing preferences preserves it; changing phone keys
does not reassign it. Malformed display metadata stays unknown without repairing
settings or changing grants. Display metadata is excluded from actor authority and
does not emit ordinary callbacks from the terminal lane.

Proofs include dual-platform English/German DOM cases (actual manual and both
automatic labels, offline visibility, current peer changes, malformed records,
refresh, no report/contact fallback), native metadata persistence/identity tests,
actual outgoing report ACK dispatch and guarded actor completion/failure cases.
Both full frontend suites pass. Installed Linux/Windows and physical Notes
acceptance remain separate; no package, installation or publication is implied.
