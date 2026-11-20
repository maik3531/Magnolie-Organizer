# Rechtsseiten der Website

Bearbeitungsstand: 20. November 2026. Zugehöriges Issue: [#708](https://github.com/maik3531/Magnolie-Organizer/issues/708).

## Status vor Veröffentlichung

Die neuen Seiten `impressum/index.html` und `datenschutz/index.html` sind zunächst **Entwürfe**. Der zugehörige Pull Request darf erst nach Ergänzung der ausstehenden Anbieterangaben zusammengeführt und veröffentlicht werden. Die Produktionswebsite wird durch einen Draft-Pull-Request nicht geändert.

Vor der Veröffentlichung:

- Vollständige, zur öffentlichen Verwendung bestätigte Anbieteranschrift ergänzen: Straße/Hausnummer, Postleitzahl, Ort und Land. Keine Anschrift aus nicht zugehörigen Quellen ableiten.
- Redaktionell verantwortliche Person für die Presseschau bestätigen, einschließlich Anschrift und der Voraussetzungen nach § 18 Abs. 2 MStV. Wenn dies Maik Walter ist, kann im Impressum auf dessen Anbieteranschrift verwiesen werden.
- Die markierten Angaben (`data-required-before-publish`), sichtbaren Entwurfsvermerke und den Entwurfsstand auf beiden Seiten auflösen. Das vorhandene `noindex,follow` kann auch auf fertigen Rechtsseiten bestehen bleiben; es ersetzt keine Zugangsbeschränkung.
- Etwaige tatsächlich einschlägige zusätzliche Anbieterangaben nach § 5 DDG berücksichtigen, wenn beispielsweise eine Gesellschaft, Registereintragung oder USt-IdNr./Wirtschafts-Identifikationsnummer vorliegt. Solche Angaben sind bisher nicht belegt und werden nicht erfunden. Keine private Steuer-ID oder normale Steuernummer ergänzen.
- Prüfen, ob die beschriebenen Abläufe zur Bearbeitung und Löschung von Kontaktanfragen weiterhin stimmen.
- Den normalen statischen Website-Build ausführen und erst den vervollständigten Stand veröffentlichen.

Bereits öffentlich belegt sind **Maik Walter** und **maik3531@gmail.com** in `pad/magnolie-organizer-windows.xml` und `magnolie-organizer/debian/control`. `docs/PAD.md` dokumentiert diese Herkunft und die bislang fehlende verifizierte Postanschrift. Diese Website-Angaben betreffen keine eigene GitLab-Website; GitLab verlinkt weiterhin nur den zentralen GitHub-Auftritt.

## Inhaltliche Grundlage

- [§ 18 MStV, aktuelle Fassung der Medienanstalten](https://www.die-medienanstalten.de/fileadmin/user_upload/Rechtsgrundlagen/Gesetze_Staatsvertraege/Medienstaatsvertrag_MStV.pdf): Anbietername und Anschrift bei nicht ausschließlich persönlichen/familiären Angeboten; zusätzliche redaktionelle Verantwortung bei entsprechend gestalteten Inhalten.
- [§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html): eigener geschäftsmäßiger Anwendungsbereich und je nach Anbieter einschlägige Pflichtangaben. Kostenlosigkeit allein entscheidet die Einordnung nicht.
- [Medienanstalten: Gestaltung eines Impressums](https://www.die-medienanstalten.de/aufgaben/aufsicht/impressumspflicht/): gut erkennbare, unmittelbar erreichbare und ständig verfügbare Angaben. Deshalb tragen alle Spracheinstiege und die Presseschau Footerlinks.
- [BGH, Urteil vom 18. Juni 2015, I ZR 74/14](https://juris.bundesgerichtshof.de/cgi-bin/rechtsprechung/document.py?Art=en&Blank=1.pdf&Datum=Aktuell&Gericht=bgh&Sort=12288&anz=509&nr=73259&pos=3): keine pauschale Haftungsbefreiung durch einen Link-Disclaimer; eigene beziehungsweise zu eigen gemachte Inhalte und Hinweise auf Rechtsverletzungen sind zu berücksichtigen. Der Website-Text beschreibt einen Meldeweg und die Prüfung solcher Hinweise.
- [DSGVO, insbesondere Art. 6, 13, 15–21 und 77](https://eur-lex.europa.eu/eli/reg/2016/679/oj/deu): Zwecke, Rechtsgrundlagen, Empfänger, Übermittlungen, Speicherfristen/-kriterien und Rechte.
- [GitHub Pages: Datenerhebung](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages#data-collection) und [GitHub-Datenschutzerklärung](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement): IP-Protokollierung zu Sicherheitszwecken, internationale Verarbeitung und zweckabhängige Aufbewahrung. Keine feste Pages-Löschfrist, ausschließlich europäische Verarbeitung oder individuell abgeschlossener Auftragsverarbeitungsvertrag wird behauptet.
- [Google-Datenschutzerklärung](https://policies.google.com/privacy?hl=de) und [Übermittlungsrahmen](https://policies.google.com/privacy/frameworks?hl=de): das öffentlich angegebene Gmail-Postfach ist ein zusätzlicher Datenfluss bei einer Kontaktaufnahme.

Die technische Quellprüfung umfasst 21 bestehende HTML-Seiten, `assets/site.js` und die Website-Stylesheets: keine Tracker, Kontaktformulare, extern eingebetteten Medien/Schriften, Cookies oder Web-Storage-Zugriffe im Websitecode. Die Teilen-Funktion schreibt nur nach Klick in die Zwischenablage; der Druckknopf ruft die Browser-Druckfunktion auf. Diese Prüfung macht keine Aussage über unbekannte Serverprotokolle des Hosters. Bei neuen Diensten oder Funktionen sind die Datenschutzhinweise erneut anzupassen.

Die Texte sind auf den geprüften technischen Stand zugeschnitten. Sie behaupten weder eine pauschale Haftungsfreiheit noch eine umfassend garantierte Rechtskonformität.
