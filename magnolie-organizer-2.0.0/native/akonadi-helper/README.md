# Magnolie Akonadi helper

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

Build and install the standalone Debian native package with:

```sh
(cd native/akonadi-helper && dpkg-buildpackage -us -uc)
sudo apt install ../native/magnolie-organizer-akonadi_1.0.0_$(dpkg --print-architecture).deb
```

`werkzeuge/rpm_fedora_bauen.sh` creates and tests the matching RPM and SRPM in
its pinned Fedora 42 environment.

CMake prefers Qt 6 with `KPim6Akonadi`, `KF6CalendarCore`, and `KF6Contacts`,
then falls back to the corresponding Qt 5/KF5 development packages. Packaging
should place `magnolie-akonadi-helper` in `libexec` and make the package an
optional/recommended dependency only on KDE-capable distributions. Runtime
requires a configured, running Akonadi session bus service and its calendar or
contacts serializer plugins.
