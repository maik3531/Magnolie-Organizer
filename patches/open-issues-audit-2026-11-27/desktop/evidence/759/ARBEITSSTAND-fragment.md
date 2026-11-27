- **#759 / #330, enges Windows-UI-Folgepaket auf 50b15122:** Der bestätigte
  Status ohne gemeinsame Medienwerte zeigt jetzt einen gesperrten Hauptschalter
  und einen Wartehinweis. Alte Einzeloptionen senden keine Änderungen mehr;
  bereits begonnene Änderungen werden auch nach wartendem Save-ACK geprüft.
  Der vorhandene automatische Transportpfad bleibt erhalten: genau eine
  Organizer-Änderung, ohne zusätzliche Bestätigung auf Notes. Der getrennte Aufbaufehler
  der lokalen Wiederherstellung ist behoben: anfängliche Historienanfragen und
  automatische Statusregistrierungen bleiben bis zum Anhängen der Telefonzeilen
  erhalten. Sechs Wartezustandsfälle, fünf Aufbau-/Recoveryfälle, 29 vorhandene
  Quellordnerfälle und das bestehende Medien-UI-Prüfprogramm bestanden mit dem
  tatsächlichen Modul in JSDOM. Kein installierter Windows-/Notes- oder
  Transfernachweis. Die produktive Shared-Anbindung und Paketparität bleiben
  unter #330 offen; die Standard-Notes-Fähigkeitsliste ist damit nicht erweitert.
