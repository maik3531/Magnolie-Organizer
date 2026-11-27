- [#839](https://github.com/maik3531/Magnolie-Organizer/issues/839):
  Die erneute Prüfung bestätigte doppelte zeitgleiche absolute und gewöhnliche
  Meldungen in den Mac-/Tablet-Projektionen. Der Issue-Patch fasst sie je
  Eintrag und UTC-Zeit zusammen und erhält beide Meldeidentitäten. Alte
  verschlüsselte Tablet-Pläne werden auch ohne erneutes Web-Speichern erkannt;
  Belege bleiben nach dem Entfernen einer Alarmart und erneutem Öffnen gültig.
  macOS verhindert außerdem erneute Aufgabenmeldungen nach einer entsprechenden
  Quellaktualisierung innerhalb der geöffneten Sitzung. Auf Quellcommit
  `016f4e457a3313320c7eaa884375952e6d41ec03` bestanden 398 Mac-UI-Prüfungen,
  30 Tablet-UI-Fälle und 23 JVM-Prüfungen der tatsächlichen Speicher-/Belegklassen.
  JSDOM/JVM ersetzen keine Android-Zustellung oder native macOS-Mitteilung;
  installierbare Pakete wurden in dieser Reviewrunde nicht gebaut.
