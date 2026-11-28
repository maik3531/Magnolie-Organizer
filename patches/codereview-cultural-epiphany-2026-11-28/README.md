# #853 – Zwei kulturelle Motive am 6. Januar (ES/IT)

Basis `6f14985fa6590c251b73ca4430d997a750525dc6`, beide Produktblobs `56eba97333365fc1f808db2792e66147d77541a0`. Erweiterung, kein neuer reproduzierter Produktfehler: bisher liefert holiday("2026-01-06", "ES"/"IT") jeweils none. Eigene SVGs: drei Kronen mit Stern und Geschenken, Befana-Strumpf und Besen. Unveränderter gemeinsamer currentColor/80×80/2px-Renderer, CSS unverändert. Nationale Motive haben weiterhin Vorrang. Moderne konservative Grenzen ES ab 1984 (nach RD 2001/1983), IT ab 1986 (DPR 792/1985, wirksam 1.1.1986). Das sind bewusst keine Ursprungsdaten der Traditionen und keine Behauptung landesweiter gesetzlicher Arbeitsfreiheit in allen Jahren/Regionen. Die Motive dekorieren nur die verifizierte kulturelle Festidentität; kein Feiertagsdaten-/Cacheeintrag, keine Sprach- oder Glaubenszuschreibung.

Quellen am 28.11.2026 gelesen:
- [Spanisches staatliches Tourismusportal: Día de Reyes am 6. Januar, Geschenke/Könige](https://socialnewsroom.spain.info/three-kings-day-in-spain-2024/).
- [BOE: RD 2001/1983 Art.45, Epifanía](https://www.boe.es/eli/es/rd/1983/07/28/2001), mit regionalen Substitutions-/Arbeitskalenderregeln, nicht als heutiger Arbeitskalender verwendet.
- [Italienisches staatliches Tourismusportal: Befana, Strumpf/Besen am 6. Januar](https://www.italia.it/en/italy/things-to-do/epiphany-in-italy-befana-meaning-and-traditions).
- [Italienischer Präsidialerlass 792/1985](https://presidenza.governo.it/USRI/confessioni/norme/85DPR792prn.html), Art.1/2.

## Tatsächlich ausgeführt
- magnolie-organizer/web/appearance.js: 174/200 → 200/200, vollständiges Originalmodul im V8-DOM-Double-Host.
- magnolie-organizer-windows/app/web/appearance.js: 174/200 → 200/200, vollständiges Originalmodul im V8-DOM-Double-Host.
Vorher/Nachher identische Probe, bisherige 144 Fälle plus neue Kulturfälle; exakte Vorwärts-/Rückwärtsanwendung der erzeugten Text-Hunks. Explizite Vorschau bleibt standardmäßig aus; neue Optionen nutzen vorhandene übersetzte Ländernamen und ISO-Monat-Tag (01-06), keine neuen msgids. Kein Netzwerk, keine Native-Calls im Prüfer, keine Datenwrites. Reproduktion nach isolierter Anwendung: `node magnolie-organizer/pruefungen/test-cultural-epiphany-853.cjs /pfad/zum/checkout`.

Mac-Projektor `db385137c6c2065192c1226ce20488ded046a23e` kopiert kanonische web-Dateien; Tablet-Projektor `2895fa5baf490ac5a3aa2f77da0de71e4db2b3e3` kopiert web-Dateien und führt appearance.js im Scriptinventar. Das ist **Quellinspektion**, kein vollständiger Projektions-/Gerätetest. Git-Checkout DNS blockiert; kein tatsächlicher git apply, keine Raster-/Kontrast-/Druck-/Katalog-/native Abnahme. Handbuchnachtrag für neue Motive und verifizierte weitere regionale Identitäten offen. Die 12 bisherigen Nationalmotive und ihr Handbuch wurden inzwischen von Codex übernommen (50627053/aa79d361). #128 Desktop-Pumpfix 17f9a79c übernommen; aktuell Codex aktiv am Notes-WLAN-Spätbestätigungsfall (7244998510), keine parallele Arbeit. #860 PL weiterhin ohne Freischaltung; #864 externer Patch vollständig geliefert. Keine neuen Issues, kein Produktmerge.

[Einzelpatch](cultural-epiphany-853.patch) · [Probe](probe.cjs) · [Vollständige Ergebnisse](results.json).
