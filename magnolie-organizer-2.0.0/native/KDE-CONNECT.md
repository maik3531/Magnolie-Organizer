# Linux KDE Connect Coexistence

Magnolie prefers the session's existing or activatable KDE Connect service. It
does not activate that service, bind its UDP1716 port, change plugin settings,
pair a new phone, or import native trust into Magnolie's direct identity store.
An occupied UDP1716 in the shared network namespace also prevents a direct
fallback when a sandbox's filtered bus hides the service. No extra Flatpak,
D-Bus, firewall, filesystem or phone permissions are requested.

| Native capability | Behavior |
| --- | --- |
| Paired phone listing | Valid, deduplicated device IDs; names are display text, not identity. Pairing/reachability are read again from the current native owner. |
| SMS send | Explicit request to exactly one reachable, already-paired phone with the SMS plugin loaded. Explicit device selection resolves multiple phones. No attachments or retry after an ambiguous timeout. Queued does not mean delivered. |
| Clipboard/file reception | Unavailable in Magnolie's native route, even when old direct-backend receive preferences exist. No inbound subscriptions, proposals, file writes or clipboard application. |
| Incoming SMS/history | Unavailable in this native adapter; it does not fetch messages or subscribe to conversations. Native pairing alone is not new Magnolie consent to read messages. |
| New pairing | Unavailable through this native adapter; accepting a native pairing could enable native plugins without Magnolie's per-item controls. |
| Magnolie Notes WLAN | Separate service, identity, consent and setup path. Native KDE selection neither enables nor disables it. |

The native KDE plugins do not offer Magnolie a pre-application approval hook for
clipboard/file reception. Magnolie therefore disables these channels rather
than delegating its confirmations to KDE settings. Independently configured KDE
Connect can still perform its own desktop actions: Magnolie neither controls nor
claims to block those actions. It never calls `setPluginEnabled`, `requestPairing`,
`acceptPairing`, `unpair` or `StartServiceByName` in the native route.

Without a native service or port owner, the existing direct backend remains
available with its existing authenticated transport and approval controls.
Native service loss is exposed as a capability/status failure, not a reason to
take over the port. The other background services can reach `ready` normally.

## Notifications

`NativeNotifications.show()` means service acceptance, not visible delivery or
permission. Native notification actions forward a one-shot compositor token
only for the matching notification ID and service owner. Both
`XDG_ACTIVATION_TOKEN` and GTK3's `DESKTOP_STARTUP_ID` are supplied to the invoked
child, never installed globally or inherited by unrelated launches. The GTK
application registration carries platform activation data to an existing
instance. Focus remains subject to compositor policy.

The native-status explanations have manually authored translations in all 19
non-English catalogs, with English source text completing the 20 languages.
`pruefungen/test_kde_native.py` checks those translations and the real private
D-Bus wire contract, trust changes, no network binding, no inbound application,
disabled receive/pairing operations, unchanged startup permissions and token
scoping. It never uses a real phone, account or personal desktop profile.
