<p align="center">
  <img src=".github/assets/magnolie-preview.png" alt="Magnolie Organizer unter Linux, Windows und Android" width="100%">
</p>

<p align="center">
  <strong>Dein privater Organizer, gestaltet wie ein echtes Buch.</strong><br>
  Kalender, Aufgaben, Kontakte und Notizen für Linux, Windows und Android.
</p>

<p align="center">
  <strong>Deutsch</strong> · <a href="README.md">English</a> ·
  <a href="https://github.com/maik3531/Magnolie-Organizer/releases/latest">Downloads</a> ·
  <a href="CHANGELOG.md">Änderungen</a>
</p>

## Ein persönlicher Organizer statt noch eines Cloud-Kontos

Magnolie bringt das vertraute Gefühl eines ledergebundenen Papier-Organizers auf
Rechner und Smartphone. Termine, Aufgaben, Kontakte, Notizen, Jahrestage,
Planung und Gesundheitsdaten bleiben zusammen. Im Mittelpunkt stehen lokale
Speicherung und bewusst freigegebener Datenaustausch.

- **Eine gemeinsame Gestaltung:** Leder, Papier, Ringe und Register auf allen Geräten.
- **Lokal zuerst:** Der primäre Datenbestand bleibt auf deinen Geräten.
- **Privater Abgleich:** Der Magnolienbaum tauscht freigegebene Inhalte direkt
  über das lokale Netz, VPN oder einen eingerichteten Fernendpunkt aus.
- **Praktische Einfuhr:** Kalender, vCards, Lotus-Organizer-Daten und verbreitete Notizexporte.
- **Barrierearm:** Tastaturbedienung, zuschaltbare Hilfsrahmen und anpassbare Ansichten.
- **20 Oberflächensprachen:** darunter Deutsch, Englisch, Französisch, Spanisch,
  Arabisch, Japanisch und Ukrainisch.

## Herunterladen

| Plattform | Empfohlenes Paket | Alternative |
|---|---|---|
| Linux | [Flatpak x86_64](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-2.0.17-x86_64.flatpak) | [AppImage](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-2.0.17-x86_64.AppImage) · [Debian-Paket](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-organizer_2.0.17_all.deb) |
| Windows 10/11 x64 | [Installationsprogramm](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-Windows-2.0.17-Setup-x64.exe) | [Portable ZIP](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Organizer-Windows-2.0.17-x64.zip) |
| Android | [Magnolie Notes APK](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/Magnolie-Notes-1.0.13.apk) | Android 8.0 oder neuer |
| Handbuch | [Debian-Paket](https://github.com/maik3531/Magnolie-Organizer/releases/latest/download/magnolie-handbuch_2.0.17_all.deb) | Optionale Komponente des Windows-Installers |

SHA-256-Prüfsummen und Quellarchive liegen in der
[aktuellen Freigabe](https://github.com/maik3531/Magnolie-Organizer/releases/latest).

> [!IMPORTANT]
> Die Windows-Artefakte 2.0.17 sind unsignierte Linux-Cross-Builds. Quellen-, Web-,
> Paket- und 30.000er-Coretests bestehen. Native Kompilierung, Laufzeitprüfung
> unter Windows und Authenticode-Signierung bleiben nicht verfügbar. Bitte vor
> der Nutzung die Freigabehinweise lesen.

## Einblick

<table>
  <tr>
    <td width="50%"><img src="magnolie-handbuch-stamm/web/02-woche.png" alt="Wochenansicht des Kalenders"></td>
    <td width="50%"><img src="magnolie-handbuch-stamm/web/03-aufgaben.png" alt="Aufgabenliste"></td>
  </tr>
  <tr>
    <td align="center"><strong>Die Woche auf einen Blick</strong></td>
    <td align="center"><strong>Aufgaben übersichtlich verwalten</strong></td>
  </tr>
</table>

<p align="center">
  <img src="magnolie-handbuch-stamm/web/14-karteikarte.png" alt="Magnolie-Karteikarte" width="70%"><br>
  <strong>Kontakte wie vertraute Karteikarten</strong>
</p>

## Projektfamilie

| Bestandteil | Technik | Quellen |
|---|---|---|
| Magnolie Organizer für Linux | Python 3, GTK 3, WebKit2GTK | [`magnolie-organizer-2.0.0`](magnolie-organizer-2.0.0/) |
| Magnolie Organizer für Windows | C#, .NET 8, WinForms, WebView2 | [`Magnolie-Organizer-Windows-2.0.0`](Magnolie-Organizer-Windows-2.0.0/) |
| Magnolie Notes für Android | Kotlin, Jetpack Compose | [`magnolie-notes-1.0.13`](magnolie-notes-1.0.13/) |
| Magnolie-Handbuch | Python, GTK, HTML/CSS/JavaScript | [`magnolie-handbuch-stamm`](magnolie-handbuch-stamm/) |

Jeder Ordner enthält eigene Bau- und Prüfanweisungen. Das Repository enthält
die veröffentlichten Quellen für Organizer 2.0.17 und Notes 1.0.13. Fertige
Pakete bleiben auf der Releases-Seite und belasten nicht die Git-Historie.

## Sicherheit und Datenschutz

Magnolie setzt auf lokale Dateien, verschlüsselten Datenaustausch und
ausdrückliches Vertrauen zwischen gekoppelten Geräten. Signierschlüssel,
Zugangsdaten und private Konfigurationen gehören nicht in dieses Repository.
Sicherheitsprobleme bitte vertraulich nach [SECURITY.md](SECURITY.md) melden.

## Mitwirken

Fehlerberichte, Übersetzungen und klar abgegrenzte Verbesserungen sind
willkommen. Hinweise stehen in [CONTRIBUTING.md](CONTRIBUTING.md). Bitte die
Issue-Vorlagen verwenden und Änderungen möglichst auf einen Bestandteil begrenzen.

## Lizenz

Programm- und Handbuchquellen stehen unter **GPL-3.0-or-later**, soweit eine
Datei nichts anderes nennt. Mitgelieferte Schriften behalten ihre eigenen
Lizenzen. Für den geschützten Kaffee-QR und das Porträt gilt der gesonderte
[Nutzungshinweis](PROTECTED-ASSETS-LICENSE.txt).
Eine Übersicht steht in [LICENSE.md](LICENSE.md).
