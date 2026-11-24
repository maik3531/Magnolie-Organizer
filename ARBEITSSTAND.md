# Aktueller Arbeitsstand

`main` ist die Standardquelle. Dieser Eintrag trennt den verifizierten
Quellstand von der installierten Produktversion. Die nachfolgenden
Integrationsstände sind noch nicht Teil von `main`. Ihre Git-Zweige beim
Wechsel des Werkzeugs im autorisierten privaten Projekt-Git prüfen
(in der bestehenden Arbeitskopie: Remote `work-private`; in einer neuen
Arbeitskopie den vorhandenen autorisierten Remote einrichten). Ein
Arbeitsverzeichnis eines Assistenten ist keine Wiederherstellungsquelle.

Vor Änderungen `git status` lesen und fremde Änderungen im bestehenden
Arbeitsbaum stehen lassen. Die Zweige lassen sich nach
`git fetch work-private` mit
`git log -1 work-private/work/330-linux-settings` (entsprechend für Notes
oder Windows) prüfen. Erst den Pin vergleichen, dann bei Bedarf einen
eigenen Git-Arbeitsbaum auf dieser Revision anlegen.

| Aufgabe | Integrationszweig | Quellstand |
| --- | --- | --- |
| [#330](https://github.com/maik3531/Magnolie-Organizer/issues/330), Linux | `work/330-linux-settings` | `c418ddfaf5c9de1e422b03fdecb8bb9f92e72747` |
| #330, Android Notes | `work/330-notes-settings` | `3fb976ecd45fbb6c4ad7a6f059990aa1eaa40d9e` |
| #330, Windows (nur Quelle) | `work/330-windows-media` | `7c83bdee58f2d56235032735b02952a2fc162caf` |

**Geprüft:** Linux-Oberfläche und beide Seiten des Einstellungsabgleichs in
Quell-/Loopback-Tests. Der Abgleich startet keinen Medienvorgang. Linux
gleicht gespeicherte WLAN-Einstellungen auch dann wieder ab, wenn der
Dateivorgang aufgrund eines fehlenden Zielordners oder einer nicht
unterstützten Richtung sicher gesperrt bleibt. Windows: String-/UI- und
portable Prüfungen sowie Windows-Zielkompilierung, kein nativer Medienlauf.

Die kombinierte Wiederholungsprobe ist auf den verlinkten Linux-/Notes-Pins
bestanden: Nach erneutem Verbinden blieb die Übereinkunft auf demselben
verschlüsselten Testkanal trotz unveränderter höherer Fähigkeitsrevision und
verspäteter älterer Meldung auf beiden Seiten erhalten. Kein Dateivorgang.
Das ist kein installierter WLAN- oder Gerätenachweis.

**Vorrangig [#763](https://github.com/maik3531/Magnolie-Organizer/issues/763):**
Eine zuvor aktive Telefonverbindung muss nach einem Notes-Update ohne Öffnen
der App oder manuelles Umschalten wiederkommen. AUS muss AUS bleiben. Der
Notes-Fix besteht drei Quelltests auf `work/763-notes-integration`
(`381d2a5724c54e79bd4d8925fa4ae3bbf4d75626`). Der getrennte, noch nicht
übernommene `main`-Kandidat ist `work/763-notes-main-candidate`
(`452e7b7004617a982dc0f10058af8042c47510a4`). Dessen eigener Lauf wurde
vor dem Start durch die Temperaturvorprüfung gesperrt. Die isolierte
Upgrade-Prüfung für AN und AUS ist vorbereitet: Sie kontrolliert den Dienst
und die authentifizierte WLAN-Verbindung noch vor dem Öffnen von Notes.
Die Messlogik ist mit zwölf Einzeltests geprüft; der alte Kandidat wird vor
dem Start abgelehnt. Der passende quellgebundene Nachfolger und der
installierte Nachweis stehen noch aus.

**Danach #330:** den sicheren Rückweg für bereits zugeordnete Handydateien
getrennt nachweisen. Den allgemeinen Neuimport dafür nicht verwenden; die
ursprüngliche Galerie-ID muss erhalten bleiben. Native Windows- und
Geräteabnahme stehen ebenfalls aus. Kein weiteres Benutzer-Testpaket; die installierte Ausgabe
nicht aus ihrer Versionsnummer ableiten. [Webcam #503](https://github.com/maik3531/Magnolie-Organizer/issues/503),
[Spiegelung #245](https://github.com/maik3531/Magnolie-Organizer/issues/245)
und [Erweiterung #727](https://github.com/maik3531/Magnolie-Organizer/issues/727)
bleiben getrennte Abnahmen.
