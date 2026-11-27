## Review-Nachtrag zu #841 – arabische Systemsprache

Auf Basis `0cdd6f992e094cd724203713da3bf145c36958fc` wurde die tatsächliche
Desktopinitialisierung mit regionalen arabischen Sprachcodes geprüft. Die
arabischen Texte waren vorhanden, doch `App.init` setzte die Leserichtung bei
`ar-EG`, `AR_sa`, `ar-Arab-EG` und der entsprechenden Systemauswahl auf `ltr`.
Die Bestimmung nach dem primären Sprachcode hält nun `rtl` auf beiden
Desktopquellen. Der englische Rückfall ohne arabischen Katalog bleibt `ltr`.

Patchstand: `f24d6456e4c505e819a2a8f34e459b3c194d8a5e`.
Sechzehn Startfälle auf tatsächlichen Linux-/Windows-Webquellen mit den über
den vorhandenen Generator erzeugten PO-Katalogen: vorher acht grün/acht rot,
danach sechzehn grün. Die vorhandene Uhrzeiteingabe besteht zusätzlich in je
zwanzig Sprachen auf beiden Quellen; die Lokalisierungsvollprüfung besteht
nach der regulären Erzeugung des nativen Katalogs. Dessen bereits bekannte
portugiesische Ableitung aus #828 gehört nicht zu diesem Patch.

Der Handbuch-Laufzeitkern bestimmt die Richtung bereits nach dem primären
Sprachcode. JSDOM prüft hier Controller und DOM-Zustand; native
GTK-/WebView2-/macOS-/Android-Darstellungsabnahmen und Pakete sind nicht Teil
dieses Nachweises. Der Patch ist zur späteren Übernahme im Issue bestimmt.
