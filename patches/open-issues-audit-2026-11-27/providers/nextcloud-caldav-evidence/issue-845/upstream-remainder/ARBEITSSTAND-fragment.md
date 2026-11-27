## Geprüfter enger #845-Nachtrag auf7a490dd8

Die BDAY-Grundkorrektur ist upstream in7a490dd8 enthalten; der frühere8d-
Alternativpatch wird nicht erneut angewendet. Der getrennte kleine Folgepatch
schließt zwei tatsächlich reproduzierte Reste: Linux-DAV blockiert den noch
unvollständigen typisierten Jahrestagsscope #441 jetzt auch für korrekt erkannte
Nextcloud-BDAY, statt ihn mit Erfolg still auszulassen. Beide Desktopcodecs
erhalten die Februar-Monatsende-Regel bei unverändertem29.Februar und Änderung
von Typ oder Jahr/Jahrlosigkeit, auch nach zwei Export-/Reimport-Runden. Separate
Serienausnahmen bleiben im Ereignispfad; Änderungen auf andere Monat/Tag-Werte
verwenden weiterhin die passende normale Jahresregel.

Gleiche Tests auf7a: Python6Fehler/19bestanden, C#-Gruppe rot am Regelverlust.
Auf dem Folgepatch: Python25/25, C#Nextcloud-ICS-Geburtstagsgruppe1/1 und
vorhandene CalDAV/CardDAV/Discovery/ETag-Gruppe1/1 bestanden; Build ohne
Warnungen/Fehler. Keine reale Server-, Konto-, native GUI-/Geräte-/Paketabnahme.
Vollständiger Linux-Scope #441 und DAV-Gesamtabnahme #683 bleiben offen.

Der zusätzlich tatsächlich bestätigte normale C#-NC-BDAY-Export mit nachträglicher
Serienausnahme ist durch Zusatzcommit573905f5 ebenfalls eng korrigiert: Der schon
vorhandene Detached-Guard gilt nun vor der gesamten betroffenen Jahrestagswahl.
Gleiche neue Regression auf559c rot, nach dem Zusatz C#-Gruppe1/1 grün; normale
Kontrolle ohne Ausnahme bleibt bestehen. Build ohne Warnungen/Fehler. Beide
Python-Eingaben und übrige Produktdateien sind seit559c unverändert.
