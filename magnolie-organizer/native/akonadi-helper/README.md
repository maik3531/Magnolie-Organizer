# Magnolie Organizer KDE integration

Optional native bridge for KDE Plasma installations. It reads exactly one JSON
object (maximum 16 MiB) from stdin and writes exactly one JSON object (maximum
64 MiB) to stdout. Supported commands are `status`, `snapshot`, `create`,
`modify`, `delete`, and `exists`; errors use `{"ok":false,"error":"..."}`.
The helper invokes Akonadi APIs directly and neither accepts credentials nor
starts a shell.

Requests use these exact keys: `status` takes only `command`; `snapshot` takes
`kind`, `collection`, `generation`, and `instance`; `create` adds `content`; `modify` adds `id`,
`revision`, and `content`; `delete` takes `kind`, `collection`, `id`, and `revision`;
`exists` takes `kind`, `collection`, and `uid`. `kind` is `calendar` or
`addressbook`, and IDs/revisions are JSON integers. Successful responses have
`ok:true`; snapshots explicitly return `complete:true`, are all-or-nothing,
and calendar snapshots include events only. Item responses contain `id`,
`revision`, logical `gid`, and complete iCalendar or vCard `content`. The
generation and instance values come from `status` and bind every later
operation to the same Akonadi database.

Build and stage it with:

```sh
cmake -S native/akonadi-helper -B build/akonadi-helper -DCMAKE_BUILD_TYPE=Release
cmake --build build/akonadi-helper
cmake --install build/akonadi-helper --prefix /usr
```

Build the single DEB with all three internal backends using the isolated builder:

```sh
python3 werkzeuge/kde_deb_bauen.py /tmp/opencode/kde-component
```

Install `magnolie-organizer-kde_2.0.18_amd64.deb` on Debian, Ubuntu, Kubuntu or
Linux Mint. The optional launcher selects only a complete, configured native KDE
ABI from the installed dpkg database. It never installs KDE PIM. Missing native
requirements return errors rather than empty data. There is no old-name download.
See [the single-DEB recipe](DEB-TARGETS.md) for genuine per-backend dependency
audits, one coherent DSC/source tar, separate same-artifact runtime gates and the
explicit downgrade policy for previously distributed suffixed test candidates.

`werkzeuge/rpm_fedora_bauen.sh` creates and tests the matching RPM and SRPM in
its pinned Fedora 42 environment.

CMake prefers Qt 6 with `KPim6Akonadi`, `KF6CalendarCore`, and `KF6Contacts`,
then falls back to the corresponding Qt 5/KF5 development packages. Packaging
should place `magnolie-akonadi-helper` in `libexec` and make the package an
optional suggested dependency only on KDE-capable distributions. Runtime
requires a configured, running Akonadi session bus service and its calendar or
contacts serializer plugins.
