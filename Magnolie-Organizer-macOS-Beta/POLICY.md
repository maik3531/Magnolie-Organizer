# macOS Beta Identity, Data And Release Policy

## Version And Names

`Resources/BetaIdentity.json` is the Beta version input: **2.0.30-beta.1**.
The projected About/version and Beta release-note metadata use it.
The target desktop baseline is 2.0.30; this prerelease identity does not imply
native feature parity or completed macOS acceptance. Desktop release
notes advertising unavailable native sync features are not presented as Beta features.

- Display name, executable and `.app`: `Magnolie Organizer macOS Beta`.
- Bundle identifier: `io.gitlab.maik3531.MagnolieOrganizer.macOSBeta`.
- `CFBundleShortVersionString`: `2.0.30` (Apple numeric format).
- `CFBundleVersion`: `2030.1` (numeric Beta build sequence).
- `MagnolieBetaVersion`: `2.0.30-beta.1` (full semantic prerelease identity).
- Development artifact path:
  `Output/Magnolie Organizer macOS Beta-2.0.30-beta.1/Magnolie Organizer macOS Beta.app`.
- Export/recovery filenames contain `macOS Beta`; generated build records contain
  the full version, source input hashes and explicit native-UI/release false flags.

Changing a version requires changing the identity input and matching plist values;
tests/build checks reject disagreement. An existing output is retained, not overwritten.

## Isolation And Data

The profile stays under the Beta bundle identifier in Application Support. The
projected browser key is `magnolie-organizer-macOSBeta-daten`; WK storage is
nonpersistent. Native data remains authoritative. There is no automatic use of
Linux/Windows/Notes profiles, keychains, pairing identities or cloud accounts.

The JSON picker is explicit user authority to read one file. Its selected path and
bytes are checked again at restore, and the live profile is never used as an export
destination. Restore is complete replacement, not synchronization or additive import.
The current profile's encryption is retained; importing an encrypted profile into
a plain profile adopts the imported session. Nothing silently falls back to plain
text after crypto failure. Previous recovery files keep their original encryption
state and passwords. Enabling encryption does not rekey or erase historical copies.

Recovery files are local rollback material, not scheduled external backups. Each
pre-change/pre-restore file is written and synchronized before replacement, then
read back. There is no automatic expiry or purge and no recovery of unsaved UI text.

## Sources, Assets And Secrets

UI/assets/catalogs come from the **current shared source** at projection time.
There is no committed old application JS payload. Tests generate disposable trees;
development packaging requires the explicit source-freeze/reproduction checks.
All local scripts, font/icon bytes, licenses, MobileAlias metadata and Beta identity
are covered. Shared `.mga` containers are copied without decryption; rendering is
still unsupported. No production signing key, contributor/update public-key file,
credential, paired device secret or release identity is installed by the generator.
Crypto fixtures use public synthetic data and are test resources, not a live identity.

## Runner And Release Boundary

The user authorized updating both ports and using a GitHub Actions macOS runner.
The dedicated `ports-2.0.30.yml` workflow implements this request with read-only
contents permissions, no persisted checkout credentials, isolated dependencies,
two Swift jobs, a 25-minute Mac job limit and checksummed candidate uploads.
The tablet job retains its original process/resource/coordination gates. Desktop
sources are selected from the pinned published 2.0.30 commit only inside the
disposable runner. Shared sources and the Windows release workflow are unchanged
in the development checkout. The older example workflow remains inactive.

An Actions artifact is a development candidate; it is not a production release
or proof of complete native acceptance. Linux tests cannot substitute for Apple's
SDK or macOS. Runner execution, test outcomes and artifact availability must each
be verified before reporting success.

The local development builder prepares a debug app and local ad-hoc signature on
macOS only. That is not production signing, notarization, Gatekeeper approval or
publication. Independent reviews, native acceptance and final release authorization
remain separate gates. Having an existing GitHub repository is not permission to
push changes, spend runner resources or publish artifacts unexpectedly.
