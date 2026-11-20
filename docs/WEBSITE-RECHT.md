# Rechtsseiten der Website

Bearbeitungsstand: 20. November 2026. Zugehörige Issues: [#708](https://github.com/maik3531/Magnolie-Organizer/issues/708) und [#713](https://github.com/maik3531/Magnolie-Organizer/issues/713).

## Bestätigte Anbieterangaben und Pflege

Die Seiten `impressum/index.html` und `datenschutz/index.html` enthalten die zentralen Rechtsinformationen der Website. **Maik Walter hat am 20. November 2026 seine vollständige Anschrift ausdrücklich zur Veröffentlichung angegeben und bestätigt, selbst die redaktionelle Verantwortung für die Presseschau zu übernehmen.** Die Anschrift wird zentral im Impressum gepflegt; die Datenschutzerklärung verweist darauf. Die Texte sprechen für einen einzelnen Betreiber in der Ich-Form. Der Betreiber hat außerdem ausdrücklich klargestellt, dass Magnolie sein privates Open-Source-Projekt ist, in seiner Freizeit entsteht und kein Unternehmen dahintersteht. Dieser Projektcharakter wird im Impressum und in den Fußzeilen erklärt; daraus wird keine Ausnahme von gesetzlichen Pflichten abgeleitet.

Name **Maik Walter** und Kontaktadresse **maik3531@gmail.com** sind außerdem in `pad/magnolie-organizer-windows.xml` und `magnolie-organizer/debian/control` öffentlich belegt. Die frühere Dokumentation des PAD-Datensatzes zu dort damals noch nicht verifizierten Adressangaben bleibt historisch zutreffend; eine Erweiterung des PAD-Datensatzes gehört nicht zu dieser Websiteänderung.

Bei Änderungen:

- Anbieteranschrift und redaktionelle Verantwortung anhand bestätigter Angaben aktuell halten.
- Tatsächlich einschlägige zusätzliche Angaben nach § 5 DDG berücksichtigen, falls beispielsweise eine Gesellschaft, Registereintragung oder USt-IdNr./Wirtschafts-Identifikationsnummer hinzukommt. Keine private Steuer-ID oder normale Steuernummer veröffentlichen.
- Hosting, Kontaktwege und den beschriebenen Umgang mit Kontaktanfragen einschließlich der Aufbewahrung bei Änderungen der tatsächlichen Abläufe nachführen.
- Bestehende offene und besondere Lizenzbedingungen erhalten. Ein pauschaler Zustimmungsvorbehalt für jede Weiterverwendung passt nicht zu den bereits eingeräumten Rechten.
- Den vorhandenen statischen Website-Build ausführen und die veröffentlichten Seiten prüfen.

`noindex,follow` auf den Rechtsseiten ist lediglich ein Hinweis an Suchmaschinen und ersetzt keine Zugangsbeschränkung. Die Rechtsseiten bleiben ohne Anmeldung direkt über die Fußzeilen erreichbar. GitLab verlinkt weiterhin den zentralen GitHub-Auftritt und führt keine zweite Website.

## Sprachfassungen

Die deutschen Texte in `assets/legal-locales/de.json` sind die gemeinsame Ausgangsfassung für die 19 weiteren Übersetzungen. Die Betreiberangaben werden einmal in `operator.json` gepflegt. Alle Fassungen erhalten dieselben Abschnitte, Links und Platzhalter; beim Erzeugen werden diese strukturell abgeglichen. Die gesetzlichen Fundstellen und postalischen Anbieterangaben bleiben nachvollziehbar erhalten. Eine muttersprachliche juristische Prüfung sämtlicher Übersetzungen wird damit nicht behauptet. Fremdsprachige Rechtsseiten verlinken die deutsche Ausgangsfassung ohne eine zusätzliche rechtliche Vorrangklausel.

Die automatische Sprachauswahl läuft ausschließlich am allgemeinen Website-Einstieg anhand der Browserpräferenzen. Sie setzt keine Cookies, nutzt keinen Web Storage und übermittelt die Auswahl nicht an einen zusätzlichen Dienst. Alle Datenschutzfassungen beschreiben diese Funktion. Feste Sprachadressen und konkrete Sprachwechsel werden respektiert.

## Inhaltliche Grundlage

- [§ 18 MStV, aktuelle Fassung der Medienanstalten](https://www.die-medienanstalten.de/fileadmin/user_upload/Rechtsgrundlagen/Gesetze_Staatsvertraege/Medienstaatsvertrag_MStV.pdf): Anbietername und Anschrift bei nicht ausschließlich persönlichen/familiären Angeboten; zusätzliche redaktionelle Verantwortung bei entsprechend gestalteten Inhalten.
- [§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html): eigener geschäftsmäßiger Anwendungsbereich und je nach Anbieter einschlägige Pflichtangaben. Kostenlosigkeit allein entscheidet die Einordnung nicht.
- [Medienanstalten: Gestaltung eines Impressums](https://www.die-medienanstalten.de/aufgaben/aufsicht/impressumspflicht/): gut erkennbare, unmittelbar erreichbare und ständig verfügbare Angaben. Deshalb tragen alle Spracheinstiege und die Presseschau Footerlinks.
- [BGH, Urteil vom 18. Juni 2015, I ZR 74/14](https://juris.bundesgerichtshof.de/cgi-bin/rechtsprechung/document.py?Art=en&Blank=1.pdf&Datum=Aktuell&Gericht=bgh&Sort=12288&anz=509&nr=73259&pos=3): keine pauschale Haftungsbefreiung durch einen Link-Disclaimer; eigene beziehungsweise zu eigen gemachte Inhalte und Hinweise auf Rechtsverletzungen sind zu berücksichtigen. Der Website-Text beschreibt einen Meldeweg und die Prüfung solcher Hinweise.
- [§ 31 UrhG](https://www.gesetze-im-internet.de/urhg/__31.html) und die vorhandenen Dateien `LICENSE`, `PROTECTED-ASSETS-LICENSE.txt` sowie `SOURCE-NOTICES.txt`: bereits eingeräumte Nutzungsrechte und jeweils geltende Lizenzbedingungen bleiben erhalten. Der Urheberrechtshinweis erklärt weder alle Websiteelemente zu geschützten Werken noch sämtliche Bilder pauschal zu GPL-Material.
- [DSGVO, insbesondere Art. 6, 13, 15–21 und 77](https://eur-lex.europa.eu/eli/reg/2016/679/oj/deu): Zwecke, Rechtsgrundlagen, Empfänger, Übermittlungen, Speicherfristen/-kriterien und Rechte.
- [GitHub Pages: Datenerhebung](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages#data-collection) und [GitHub-Datenschutzerklärung](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement): IP-Protokollierung zu Sicherheitszwecken, internationale Verarbeitung und zweckabhängige Aufbewahrung. Keine feste Pages-Löschfrist, ausschließlich europäische Verarbeitung oder individuell abgeschlossener Auftragsverarbeitungsvertrag wird behauptet.
- [Google-Datenschutzerklärung](https://policies.google.com/privacy?hl=de) und [Übermittlungsrahmen](https://policies.google.com/privacy/frameworks?hl=de): das öffentlich angegebene Gmail-Postfach ist ein zusätzlicher Datenfluss bei einer Kontaktaufnahme.

Die technische Quellprüfung umfasst die statischen Sprach- und Rechtsseiten, `assets/site.js`, `assets/language.js` und die Website-Stylesheets: keine Tracker, Kontaktformulare, extern eingebetteten Medien/Schriften, Cookies oder Web-Storage-Zugriffe im Websitecode. Die Teilen-Funktion schreibt nur nach Klick in die Zwischenablage; der Druckknopf ruft die Browser-Druckfunktion auf. Der Spracheinstieg liest ausschließlich lokale Browserpräferenzen und navigiert zu einer festen Websiteadresse. Diese Prüfung macht keine Aussage über unbekannte Serverprotokolle des Hosters. Bei neuen Diensten oder Funktionen sind die Datenschutzhinweise erneut anzupassen.

Die Texte sind auf den geprüften technischen Stand zugeschnitten. Sie behaupten weder eine pauschale Haftungsfreiheit noch eine umfassend garantierte Rechtskonformität.
