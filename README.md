<p align="center">
  <img src=".github/assets/magnolie-preview.png" alt="Magnolie Organizer with its leather book cover" width="100%">
</p>

<p align="center">
  <strong>Your private organizer, designed like a real book.</strong><br>
  Calendar, tasks, contacts and notes for Linux, Windows and Android.
</p>

<p align="center">
  <a href="README.DE.md">Deutsch</a> · <strong>English</strong> ·
  <a href="https://github.com/maik3531/Magnolie-Organizer/releases/latest">Downloads</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <a href="https://github.com/maik3531/Magnolie-Organizer/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/maik3531/Magnolie-Organizer?style=flat-square&color=8b5e34"></a>
  <a href="https://github.com/maik3531/Magnolie-Organizer/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/maik3531/Magnolie-Organizer/total?style=flat-square&color=b08d57"></a>
  <img alt="Platforms" src="https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20Android-5b2333?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0%2B-6b705c?style=flat-square">
</p>

## A personal organizer, not another cloud account

Magnolie brings the familiar feeling of a leather-bound paper organizer to the
desktop and phone. It keeps appointments, tasks, contacts, notes, anniversaries,
planning and health records together while putting local storage and explicit
sharing first.

- **One visual language:** leather, paper, rings and tabs across desktop and mobile.
- **Local-first:** your primary data stays on your devices.
- **Private synchronization:** Magnolienbaum exchanges approved content directly
  over the local network, VPN or a configured remote endpoint.
- **Useful imports:** calendars, vCards, Lotus Organizer data and common note exports.
- **Accessible:** keyboard navigation, optional focus outlines and scalable layouts.
- **20 interface languages:** including English, German, French, Spanish, Arabic,
  Japanese and Ukrainian.

## Download

| Platform | Recommended package | Alternative |
|---|---|---|
| Linux | [Flatpak x86_64](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-2.0.18-x86_64.flatpak) | [AppImage](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-2.0.18-x86_64.AppImage) · [Debian package](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-organizer_2.0.18_all.deb) |
| Windows 10/11 x64 | [Setup](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-Windows-2.0.18-Setup-x64.exe) | [Portable ZIP](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-Windows-2.0.18-x64.zip) |
| Android | [Magnolie Notes APK](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Notes-1.0.14.apk) | Android 8.0 or newer |
| Handbook | [Debian package](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-handbuch_2.0.18_all.deb) | Included as an optional Windows component |

Optional KDE integration for the native Linux package:

| Distribution | KDE package (amd64 / x86_64) |
|---|---|
| Debian 13, Ubuntu / Kubuntu 24.04 and 26.04, Linux Mint 22 | [One KDE DEB](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-organizer-kde_2.0.18_amd64.deb) |
| Fedora 42 | [KDE RPM](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-organizer-kde-2.0.18-1.fc42.x86_64.rpm) |

The optional KDE DEB selects one of three internal native backends from the
existing, configured KDE packages and their complete ABI dependencies. It does not
install KDE PIM. There is no transitional-package download. Users of the former
package explicitly install `magnolie-organizer-kde`; versioned package relations
preserve upgrades from released 1.0.0. The suffixed 2.0.18 files were unreleased test
candidates and sort above 2.0.18 in dpkg: replacing them requires an explicit tester
downgrade decision. See [KDE requirements and upgrade policy](magnolie-organizer/native/akonadi-helper/DEB-TARGETS.md).

SHA-256 checksums and source archives are attached to the
[latest release](https://github.com/maik3531/Magnolie-Organizer/releases/latest).

## A look inside

<table>
  <tr>
    <td width="50%"><img src="magnolie-handbuch/web/02-woche.png" alt="Weekly calendar view"></td>
    <td width="50%"><img src="magnolie-handbuch/web/03-aufgaben.png" alt="Task list"></td>
  </tr>
  <tr>
    <td align="center"><strong>Week at a glance</strong></td>
    <td align="center"><strong>Tasks that stay manageable</strong></td>
  </tr>
</table>

<p align="center">
  <img src="magnolie-handbuch/web/14-karteikarte.png" alt="Magnolie contact card" width="70%"><br>
  <strong>Contacts presented as familiar index cards</strong>
</p>

## Project family

| Component | Technology | Source |
|---|---|---|
| Magnolie Organizer for Linux | Python 3, GTK 3, WebKit2GTK | [`magnolie-organizer`](magnolie-organizer/) |
| Magnolie Organizer for Windows | C#, .NET 8, WinForms, WebView2 | [`magnolie-organizer-windows`](magnolie-organizer-windows/) |
| Magnolie Notes for Android | Kotlin, Jetpack Compose | [`magnolie-notes`](magnolie-notes/) |
| Magnolie Handbook | Python, GTK, HTML/CSS/JavaScript | [`magnolie-handbuch`](magnolie-handbuch/) |

The repository contains the sources for release 2.0.18 / Notes 1.0.14; generated
packages are kept on the Releases page rather than in Git history.

## Security and privacy

Magnolie is built around local files, encrypted data exchange and explicit trust
between paired devices. No signing keys, credentials or private configuration
belong in this repository. Please report security issues privately as described
in [SECURITY.md](SECURITY.md).

## Contributing

Bug reports, translations and focused improvements are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md), use the issue templates, and keep changes
scoped to one component whenever possible.

## License

Program and handbook sources are licensed under **GPL-3.0-or-later** unless a
file states otherwise. Third-party fonts retain their included licenses. The
protected coffee QR and portrait have a separate, limited
[usage permission](PROTECTED-ASSETS-LICENSE.txt).
See [LICENSE.md](LICENSE.md) for the repository-wide overview.
