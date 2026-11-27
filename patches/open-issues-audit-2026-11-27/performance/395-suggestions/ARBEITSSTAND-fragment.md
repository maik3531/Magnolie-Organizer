- [#395](https://github.com/maik3531/Magnolie-Organizer/issues/395):
  Der enge Teilpatch `38edd46ef18259e232c786bf2e8e88903f96b655` auf
  `24927cf94cfe9a7bb5c4f148a38d6b04b0bc732b` baut Organisator-Namensvorschläge
  im Terminblatt erst bei Benutzung und mit höchstens 250 DOM-Treffern.
  Die gesamte Kontaktliste bleibt durchsuchbar; späte exakte Namen,
  Firmen und sämtliche E-Mail-Adressen gleicher Namen bleiben erreichbar.
  Fünf reguläre Öffnen-/Schließen-Zyklen mit 2.003 synthetischen Kontakten
  erzeugten vorher jeweils 2.002 unbenutzte Namensoptionen, nachher keine.
  Zehn gezielte JSDOM-Fälle auf Linux-/Windows-Quellen und die bestehende
  strukturierte Terminparitätsprüfung bestanden; unabhängiger Diffreview
  an Commit und Quellhashes gebunden. Kein globaler Kontaktcache und keine
  Zeitbudgetänderung. Der große Import-/Zeichenblock, native Datalist-/N100-
  Abnahme und langfristiger Tray-/RAM-Verlauf bleiben offen. Patchübergabe,
  kein neuer Paket- oder Gerätenachweis.
