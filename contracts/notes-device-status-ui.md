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

The requested last-successful-sync time and actual automatic/manual trigger are
separate follow-up work in this issue. Connection times, configured automatic mode,
unscoped old reports and failed/queued attempts must not be substituted for a
confirmed successful run. Missing historical proof must stay unknown.
