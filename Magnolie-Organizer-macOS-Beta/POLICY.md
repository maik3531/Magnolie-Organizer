# macOS Beta Identity, Data And Release Policy

## Version And Names

`Resources/BetaIdentity.json` is the Beta version input: **2.0.18-beta.1**.
The projected About/version and Beta release-note metadata use it. Desktop release
notes advertising unavailable native sync features are not presented as Beta features.

- Display name, executable and `.app`: `Magnolie Organizer macOS Beta`.
- Bundle identifier: `io.gitlab.maik3531.MagnolieOrganizer.macOSBeta`.
- `CFBundleShortVersionString`: `2.0.18` (Apple numeric format).
- `CFBundleVersion`: `2018.1` (numeric Beta build sequence).
- `MagnolieBetaVersion`: `2.0.18-beta.1` (full semantic prerelease identity).
- Development artifact path:
  `Output/Magnolie Organizer macOS Beta-2.0.18-beta.1/Magnolie Organizer macOS Beta.app`.
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

Only the macOS subtree is owned by this phase. The repository has ongoing work by
other owners. No changes to shared frontend/desktop files or active workflows are
part of the port. No commit, push, CI dispatch, remote publication, VM, OS image,
GPU task or production signing was performed.

`ci/macos-beta-manual.yml.example` is an inactive, manual-only proposal for a real
GitHub macOS runner. Installing it requires explicit approval on a reviewed ref.
It has read-only contents permissions, no persisted checkout credentials, isolated
test dependencies, Swift jobs limited to two, a 15-minute job cap, and no upload
or release steps. Linux Swift tests cannot substitute for Apple's SDK or macOS.

The local development builder prepares a debug app and local ad-hoc signature on
macOS only. That is not production signing, notarization, Gatekeeper approval or
publication. Independent reviews, native acceptance and final release authorization
remain separate gates. Having an existing GitHub repository is not permission to
push changes, spend runner resources or publish artifacts unexpectedly.
