# Personal-Sync: gezielter Notes-Einzelabgleich

Issue: #231. Ergänzt die bereits vorhandene explizite Organizer→Notes-Aufnahme
über `send_item`, ohne den normalen Gesamtabgleich anzustoßen.

## Anfrage

Notes verwendet für diese Richtung ausschließlich Datensatzformat 14 mit den
vorhandenen Feldern `run_id`, `trigger: "manual"`, genau einem Modul und
`send_item: {"kind": "note" | "task", "id": "…"}`. Der Request und seine Daten
laufen im vorhandenen Phone-Content-Scope-Umschlag. Dessen Referenz beschreibt
weiter die tatsächliche aktuelle Telefon-Sammlung, während `send_item` den Lauf
auf genau eines ihrer Mitglieder begrenzt.

Vor dem Erzeugen der Inhaltsprojektionen werden die persönlichen IDs ausgewählt.
Eine Notiz darf ihr benötigtes Notizbuch und ihre eigenen Anhänge mitnehmen.
Andere Notizen, Aufgaben, Notizbücher, Anhänge, Custom-Daten und Zeiterfassung
werden durch diese Aktion nicht übertragen. Aufgaben behalten ihre eigene UID,
Elternreferenz und Reihenfolge; die Elternreferenz löst keinen Versand weiterer
Aufgaben aus.

## Voraussetzungen und Antworten

Erforderlich sind die bestehende eigene Kopplung, beidseitige Freigaben, aktuelle
Kontrollnachrichten, übereinstimmende gemeinsame Einstellungen, eine bestätigte
Scope-Referenz und eine aktuelle aktive Verbindung. Offline, ein altes Gegenüber,
eine ausstehende Freigabe/Referenz oder ein bereits laufender Scoped-Abgleich
führt zu einem Fehler statt zu einem Gesamtabgleich oder einer automatischen
Kopplung. Die Auswahl schafft keine neuen Freigaben.

Die native Gegenstelle prüft die Scope-Mitgliedschaft und lehnt andere
Notiz-/Aufgaben-IDs bereits vor dem Staging ab. Die an die Desktop-Oberfläche
übergebene Auswahl stammt aus dem dauerhaft gespeicherten Request. Die
Oberfläche begrenzt sowohl Übernahme als auch Antwort auf diesen Eintrag und das
erforderliche Notizbuch. Eine vollständige Scope-Referenz ist dabei keine
Aufforderung, die übrige Sammlung zurückzusenden.

Request-Quittung, Anhangprüfung, dauerhafte Speicherquittung, Abschlussreport,
Schlüsselbindung, Kanalwechsel, Widerruf, Ablauf und Abbruch folgen dem
vorhandenen geschützten Transport. Die unmittelbare UI-Meldung bedeutet nur
„vorgemerkt, Bestätigung ausstehend“, nicht bereits bestätigte Speicherung auf
dem Rechner.

## Lokale Bedienung

Standardmäßig bedeutet physisches Rechtswischen Löschen mit der bestehenden
Rückfrage und physisches Linkswischen gezielten Abgleich. Die Richtungen bleiben
auch bei rechtsläufiger Oberfläche physisch links/rechts. Unter Einstellungen
können beide Aktionen unabhängig auf Löschen, Einzelabgleich oder keine Aktion
gestellt sowie gemeinsam ausgeschaltet werden. Die Wahl bleibt lokal gespeichert.
Teilwischen löst keine Aktion aus. Eine Löschbestätigung gilt nur für den dabei
angezeigten unveränderten Eintrag; zwischenzeitliche Änderungen werden vor dem
bestehenden Lösch-/Papierkorbpfad unter derselben Schreibsperre geprüft.
