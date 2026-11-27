## Enger Patch und getrennte Leistungsnachweise bereitgestellt

Die Namensvorschläge im Terminfenster werden mit dem geprüften Teilpatch erst bei Bedarf erzeugt; höchstens 250 passende Optionen werden gleichzeitig dargestellt. Der vollständige aktuelle Kontaktbestand bleibt durchsuchbar. Die gezielten Fälle einschließlich später exakter Kurznamen, freier Namen, Firmenkontakten und Mehrfachadressen sind abgesichert. Kein dauerhafter Kontaktcache wurde ergänzt.

[Gesamter Performancebericht](https://github.com/maik3531/Magnolie-Organizer/blob/work/open-issues-audit-20261127/patches/open-issues-audit-2026-11-27/performance/README.md), [#395-Vorher/Nachher](https://github.com/maik3531/Magnolie-Organizer/blob/work/open-issues-audit-20261127/patches/open-issues-audit-2026-11-27/performance/395-suggestions/README.md) und [Patchserie](https://github.com/maik3531/Magnolie-Organizer/tree/work/open-issues-audit-20261127/patches/open-issues-audit-2026-11-27/final-patches) sind bereitgestellt.

Die synthetische bestehende Suite bestand mit 50.000 Gesamteinträgen. Bei 250.000 Gesamteinträgen bestanden die Daten-/Dublettenprüfungen, zwei bestehende Zeitgrenzen wurden überschritten. Numerische erfolglose Suche bleibt ein eingegrenzter Aufwand. Die im Host gemessenen RSS-Werte sind keine native Organizer-RAM-Messung. Ein vollständiger 250.000-Einträge-Nachlauf nach dem Teilpatch, die ursprüngliche N100-Ursache und der 30-Tage-Tray-Nachweis werden nicht als erledigt behauptet.

Der ergänzend gefundene #843-Worker-Ressourcenfehler wurde inzwischen upstream in `66b50c44` behoben und unabhängig nachgeprüft. Der frühere Alternativpatch wird nicht zusätzlich empfohlen. Die nativen Großbestands-/Dauerbetriebsanforderungen dieses Issues und ihr Verweis in #113 bleiben offen.
