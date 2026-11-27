> Historischer Fragmentstand vor Upstream7a. Nicht als aktuellen Arbeitsstand übernehmen; siehe upstream-remainder.

## Geprüfter Review-Nachtrag zu #845

Auf #844-Folge `a6462407` erkennt der getrennte Quellpatch `8d7263fd` ausdrücklich
markierte, eindeutig abbildbare Nextcloud-BDAY-Ereignisse in beiden Desktopcodecs
als Geburtstage. Bekannte und jahrlose Daten bleiben getrennt; 1970/1972 sind bei
jahrlosen Nextcloud-Daten nur technische Anker. Die besondere Februar-Monatsende-
regel bleibt bei Export/Reimport und Typänderung erhalten. Mehrdeutige Marker,
nicht passende Serienregeln und separate Serienausnahmen werden nicht zu einem
ausnahmslosen Geburtstag vereinfacht. Eine bewusste Typänderung entfernt alte
BDAY-Marker; fremde Metadaten, Alarme, UID und Farben bleiben erhalten.

Geprüft: identischer finaler Testbestand auf der Basis Python21Fehler/23bestanden
und C#-Geburtstagsgruppe rot; auf dem Patch Python44/44, C#-Geburtstagsgruppe und
drei bestehende Farbgruppen bestanden, Build ohne Warnung/Fehler. Unabhängig
bestanden vier tatsächliche Python-Codec→Desktop-DOM→Speicher/Reload-Fälle für
28.02.2027/29.02.2028, Jahr/Alter und Farben sowie zwei Review-Grenzfälle.
Diese vier DOM-Fälle führen nicht zusätzlich den C#-Codec aus.

Linux-DAV-Jahrestage bleiben wegen des offenen vollständigen Scopes #441 vor
Kalenderwrites blockiert; der Codecfix macht keinen vollständigen DAV-Abgleich
verfügbar. Reale Server-, native Konten-/Geräte-/Paketabnahme aus #683/#121/#113
bleibt getrennt. Kein Main-Merge und keine Paketfreigabe aus diesem Quellpatch.
