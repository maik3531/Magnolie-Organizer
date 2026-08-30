/* Funktionstest der Organizer-Oberfläche unter jsdom (ohne echtes GTK). */
"use strict";

const fs = require("fs");
const path = require("path");
const knoten = require("assert");
/* Objekte aus dem jsdom-Fenster tragen dessen Object.prototype, nicht den des
   Node-Realms. assert.deepStrictEqual vergleicht auch den Prototyp und würde
   deshalb bei jedem Wert scheitern, der drinnen entstanden ist. Das Umtopfen
   bewahrt anders als JSON auch undefined, NaN, -0, Datumswerte und Zyklen. */
const umTopfen = (wert, gesehen = new Map()) => {
  if (wert === null || typeof wert !== "object") return wert;
  if (gesehen.has(wert)) return gesehen.get(wert);
  if (Object.prototype.toString.call(wert) === "[object Date]") {
    return new Date(wert.getTime());
  }
  if (Array.isArray(wert)) {
    const liste = [];
    gesehen.set(wert, liste);
    for (const eintrag of wert) liste.push(umTopfen(eintrag, gesehen));
    return liste;
  }
  const objekt = {};
  gesehen.set(wert, objekt);
  for (const schluessel of Object.keys(wert)) {
    objekt[schluessel] = umTopfen(wert[schluessel], gesehen);
  }
  return objekt;
};
const assert = Object.assign(Object.create(knoten), knoten, {
  deepStrictEqual: (ist, soll, meldung) =>
    knoten.deepStrictEqual(umTopfen(ist), umTopfen(soll), meldung)
});
const { JSDOM } = require("jsdom");

const WEB = process.env.MAGNOLIE_WEB || path.resolve(__dirname, "..", "web");
const html = fs.readFileSync(WEB + "/index.html", "utf8");
const js = fs.readFileSync(WEB + "/anwendung.js", "utf8");
const i18nJs = fs.readFileSync(WEB + "/i18n.js", "utf8");
const deJs = fs.readFileSync(WEB + "/i18n/de.js", "utf8");
const css = fs.readFileSync(WEB + "/stil.css", "utf8");
const liesmich = fs.readFileSync(path.resolve(WEB, "..", "LIESMICH.md"), "utf8");

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  url: "https://organizer.test/",
  pretendToBeVisual: true
});
const w = dom.window;
const d = w.document;

function ladeAnwendung(fenster, sprache = "de") {
  fenster.TextEncoder ||= globalThis.TextEncoder;
  fenster.TextDecoder ||= globalThis.TextDecoder;
  fenster.eval(i18nJs);
  fenster.eval(deJs);
  fenster.MagnolieI18n.setLocale(sprache);
  fenster.eval(js);
}

ladeAnwendung(w);

const tick = () => new Promise((r) => setTimeout(r, 0));
const $ = (s) => d.querySelector(s);
const $$ = (s) => Array.from(d.querySelectorAll(s));
const T = w.OrganizerTest;

function klickeTab(name) {
  const tab = $$(".registerknopf").find((b) => b.textContent === name);
  assert.ok(tab, "Registerzunge fehlt: " + name);
  tab.click();
}

function setze(elm, wert) {
  elm.value = wert;
  elm.dispatchEvent(new w.Event("input", { bubbles: true }));
}

function knopfMit(text, wurzel) {
  return Array.from((wurzel || d).querySelectorAll("button"))
    .find((b) => b.textContent.trim() === text);
}

(async () => {

  assert.throws(() => assert.deepStrictEqual({ a: undefined }, {}),
    "Realm-Umtopfen verliert undefined-Eigenschaften");
  assert.throws(() => assert.deepStrictEqual(new Date(0), new Date(1)),
    "Realm-Umtopfen verliert Datumswerte");
  assert.deepStrictEqual({ nan: NaN, negativNull: -0 },
    { nan: NaN, negativNull: -0 },
  "Realm-Umtopfen verändert NaN oder -0");
  assert.match(js, /querySelectorAll\(auswahl\)[\s\S]*?element\.matches\("\.mini-termin"\)/,
    "beabsichtigt gekürzte Termintexte gelten nicht als übersetzte Bedienelemente");
  const terminReihenfolge = [
    { id: "spaet", zeit: "18:00", titel: "Spaet" },
    { id: "ganz", zeit: "", titel: "Ganztags" },
    { id: "frueh", zeit: "08:00", titel: "Frueh" }
  ].sort(T.sortiereTermineNachZeit).map((termin) => termin.id);
  assert.deepStrictEqual(terminReihenfolge, ["ganz", "frueh", "spaet"],
    "Ganztagstermine stehen nicht vor Terminen mit Uhrzeit");
  assert.match(js,
    /kasten\.title = DATEN\.einstellungen\.kalender\.klickLegtAn[\s\S]*?Create a new appointment immediately/,
    "Wochenkästen erklären den voreingestellten Klick nicht wahrheitsgemäß");
  const gsmErlaubt = "äöüÄÖÜéàèùìòÇØøÅåÆæÑñ¿¡£¥€^{}\\[~]|";
  assert.strictEqual(T.smsTextAnpassen(gsmErlaubt).text, gsmErlaubt,
    "zulässige GSM-Zeichen werden verändert");
  assert.deepStrictEqual(T.smsTextAnpassen("Grüße 🙂 ❤️ 👍🏽 — ‘ok’ …"), {
    text: "Grüße :) <3 +1 - 'ok' ...", einheiten: 25, teile: 1, geaendert: true
  }, "SMS-Normalisierung ist nicht deterministisch");
  assert.strictEqual(T.smsTextAnpassen("a".repeat(160)).teile, 1);
  assert.strictEqual(T.smsTextAnpassen("a".repeat(161)).teile, 2);
  assert.strictEqual(T.smsTextAnpassen("^".repeat(80)).teile, 1);
  assert.strictEqual(T.smsTextAnpassen("^".repeat(81)).teile, 2);

  const csp = d.querySelector("meta[http-equiv='Content-Security-Policy']");
  assert.ok(csp && csp.content.includes("default-src 'none'") &&
    csp.content.includes("script-src 'self'") &&
    csp.content.includes("connect-src 'none'") &&
    csp.content.includes("object-src 'none'") &&
    csp.content.includes("frame-src 'none'") &&
    csp.content.includes("base-uri 'none'") &&
    csp.content.includes("form-action 'none'") &&
    !csp.content.includes("unsafe-eval"),
  "die Hauptoberfläche besitzt keine strikte CSP ohne dynamischen Code");
  assert.ok(!/\b(?:eval|Function)\s*\(/.test(i18nJs),
    "die Pluralauswertung darf keinen JavaScript-Quelltext ausführen");
  assert.ok(js.includes("window.__MAGNOLIE_BRUECKE__") &&
    js.includes("messageHandlers[this.name]") &&
    !js.includes("messageHandlers.bridge.postMessage"),
  "die Oberfläche verwendet nicht den zufälligen nativen Bridge-Namen");
  assert.ok(!js.includes('querySelectorAll("[data-fokus]")') &&
    js.includes("document.querySelector('[data-fokus=\"'"),
  "der Fokusanker wird nicht direkt nachgeschlagen");
  assert.ok(/#dialog-schleier,[\s\S]{0,100}\.eingabe-schleier,[\s\S]{0,180}position:\s*fixed;[\s\S]{0,80}inset:\s*0;[\s\S]{0,160}align-items:\s*center;[\s\S]{0,80}justify-content:\s*center/.test(css) &&
    !/#eingabe-schleier/.test(css) && js.includes("focus({ preventScroll: true })"),
  "dynamische Dialoge sind nicht als scrollfestes, zentriertes Overlay definiert");
  const einstellungenCss = css.match(/#einstellungen-blatt\s*\{([^}]*)\}/)?.[1] || "";
  assert.ok(/height:\s*min\(820px,\s*96vh\)/.test(einstellungenCss) &&
    /overflow:\s*hidden/.test(einstellungenCss) && !/max-height:/.test(einstellungenCss),
  "das Einstellungsblatt besitzt keine eindeutige feste Viewporthöhe");
  assert.ok(/\.gesundheit-papiertabelle\s*\{[\s\S]{0,120}width:\s*100%;[\s\S]{0,80}min-width:\s*0;[\s\S]{0,80}max-width:\s*100%;[\s\S]{0,100}table-layout:\s*fixed/.test(css) &&
    !/\.gesundheit-papiertabelle\s*\{[^}]*min-width:\s*680px/.test(css) &&
    /@container \(max-width:\s*520px\)/.test(css) &&
    /@media \(max-height:\s*800px\)[\s\S]{0,220}height:\s*28px/.test(css) &&
    /\.gesundheit-seitenrolle::-webkit-scrollbar/.test(css) &&
    /\.gesundheit-papiertabelle thead th\s*\{[\s\S]{0,220}overflow-wrap:\s*anywhere;[\s\S]{0,60}word-break:\s*normal/.test(css) &&
    /\.knopf\.gesundheit-suchknopf,[\s\S]{0,80}\.knopf\.gesundheit-plusknopf\s*\{[\s\S]{0,180}flex:\s*0 0 22px;[\s\S]{0,300}min-width:\s*22px;[\s\S]{0,180}min-height:\s*22px;[\s\S]{0,180}padding:\s*0;/.test(css),
  "Gesundheitstabellen besitzen noch eine feste Mindestbreite oder keine kompakte Darstellung");
  assert.ok(liesmich.includes("Strg+Alt+H") &&
    liesmich.includes("WebKitGTK 2.38") &&
    liesmich.includes("voreingestellt deaktiviert"),
  "Hilfsrahmen oder inert-Kompatibilitätsgrenze sind nicht dokumentiert");

  /* jsdom feuert DOMContentLoaded asynchron – kurz auf den Start warten */
  for (let i = 0; i < 50 && !T.daten().notizen.length; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }

  /* ---- Start: Willkommensnotiz, Deckel, Register ---- */
  assert.ok(w.App, "App fehlt");
  assert.strictEqual(d.documentElement.lang, "de",
    "der deutsche Katalog wird nicht vor der Anwendung aktiviert");
  assert.strictEqual($("#knopf-einstellungen").textContent, "Einstellungen",
    "englischer Basistext wird nicht vollständig ins Deutsche übersetzt");
  assert.strictEqual(w.MagnolieI18n.format(
    w.MagnolieI18n.ngettext("%(count)s day", "%(count)s days", 2), { count: 2 }),
  "2 Tage", "deutsche gettext-Pluralform wird im Webkatalog nicht ausgewertet");
  w.MagnolieI18n.registerCatalog("xy", {
    pluralForms: "nplurals=3; plural=n%10==1 && n%100!=11 ? 0 : " +
      "n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2;",
    messages: { item: ["eins", "wenige", "viele"] }
  });
  w.MagnolieI18n.setLocale("xy");
  assert.deepStrictEqual([1, 2, 5, 11, 21, 22, 25].map((n) =>
    w.MagnolieI18n.ngettext("item", "items", n)),
  ["eins", "wenige", "viele", "viele", "eins", "wenige", "viele"],
  "der begrenzte Gettext-Parser wertet verschachtelte Pluralregeln falsch aus");
  w.MagnolieI18n.registerCatalog("zz", {
    pluralForms: "nplurals=2; plural=Function('return 0')();",
    messages: { item: ["ein", "mehr"] }
  });
  w.MagnolieI18n.setLocale("zz");
  assert.strictEqual(w.MagnolieI18n.ngettext("item", "items", 2), "mehr",
    "eine ungültige Pluralregel fällt nicht sicher auf die Standardregel zurück");
  w.MagnolieI18n.setLocale("en");
  assert.strictEqual($("#knopf-einstellungen").textContent, "Settings",
    "englischer Rückfall der Weboberfläche funktioniert nicht");
  w.MagnolieI18n.setLocale("de");
  assert.strictEqual(T.daten().notizen.length, 1, "Willkommensnotiz fehlt");
  assert.strictEqual(T.daten().version, 6, "neue Daten tragen keine Schema-Version 6");
  assert.deepStrictEqual({
    rechtschreibung: T.daten().einstellungen.schrift.rechtschreibung,
    ansicht: T.daten().einstellungen.ansicht,
    gesundheit: T.daten().einstellungen.allgemein.registerkarten.gesundheit
  }, { rechtschreibung: true, ansicht: "week", gesundheit: true },
  "neue Organizer-Daten verwenden nicht die korrigierten Standardwerte");
  const ausdruecklicheStandards = T.normalisiere({ einstellungen: {
    schrift: { rechtschreibung: false }, ansicht: "month",
    allgemein: { registerkarten: { gesundheit: false } },
    kalender: { gesundheitAn: true } } });
  assert.deepStrictEqual({
    rechtschreibung: ausdruecklicheStandards.einstellungen.schrift.rechtschreibung,
    ansicht: ausdruecklicheStandards.einstellungen.ansicht,
    gesundheit: ausdruecklicheStandards.einstellungen.allgemein.registerkarten.gesundheit
  }, { rechtschreibung: false, ansicht: "month", gesundheit: false },
  "explizite Nutzerentscheidungen werden durch neue Standards überschrieben");
  const hintergrundNormalisiert = T.normalisiere({ einstellungen: { sicherheit: {
    hintergrund: { enabled: true, autostart: "yes", encryptionPolicy: "invalid",
      password: "must-not-survive", permissions: { kde_pairing: true, unknown: true } } } } })
    .einstellungen.sicherheit.hintergrund;
  assert.strictEqual(hintergrundNormalisiert.enabled, true);
  assert.strictEqual(hintergrundNormalisiert.autostart, false);
  assert.strictEqual(hintergrundNormalisiert.encryptionPolicy, "notify_then_unlock");
  assert.strictEqual(hintergrundNormalisiert.permissions.kde_pairing, true);
  assert.ok(!Object.prototype.hasOwnProperty.call(hintergrundNormalisiert, "password") &&
    !Object.prototype.hasOwnProperty.call(hintergrundNormalisiert.permissions, "unknown"),
  "Hintergrunddienst-Spiegel wird nicht streng und geheimnisfrei normalisiert: " +
    JSON.stringify(hintergrundNormalisiert));
  assert.ok(!Object.prototype.hasOwnProperty.call(T.normalisiere({ einstellungen: { sync: {
    kdeEmpfang: { dateienAutomatisch: true } } } }).einstellungen.sync.kdeEmpfang,
  "dateienAutomatisch"), "alte automatische KDE-Dateiannnahme wird nicht entfernt");
  const edsAltbestand = T.normalisiere({ letzteSyncs: { adressbuecher: {
    "eds-alt": { initialisiert: true, letzterSync: 1234, remoteAnzahl: 2,
      snapshotHash: "a".repeat(64) } } } });
  assert.strictEqual(
    edsAltbestand.syncMetadaten.eds.adressbuecher["eds-alt"].letzterSync, 1234,
    "ausgelieferte EDS-Adressbuch-Baseline wird nicht ins gemeinsame Schema migriert");
  assert.ok(!edsAltbestand.letzteSyncs.adressbuecher["eds-alt"],
    "migrierte EDS-Adressbuch-Baseline bleibt parallel im Altschema");
  const davMapping = { id: "https://cloud.example/dav/item", etag: "\"e1\"",
    geaendert: 1234, eigen: true };
  const davRoundtrip = T.normalisiere({ termine: [{ uid: "t1", datum: "2026-08-17",
    sync: true, syncQuellen: { "nextcloud-calendar:test": davMapping } }],
  kontakte: [{ uid: "k1", nachname: "Probe", sync: true,
    syncQuellen: { "nextcloud-addressbook:test": davMapping } }],
  geloescht: { termine: [{ uid: "tot-t", zeit: 1234,
    syncQuellen: { "nextcloud-calendar:test": davMapping } }],
  kontakte: [{ uid: "tot-k", zeit: 1234,
    syncQuellen: { "nextcloud-addressbook:test": davMapping } }] } });
  assert.deepStrictEqual(davRoundtrip.termine[0].syncQuellen["nextcloud-calendar:test"], davMapping,
    "Termin-Normalisierung verlor die DAV-Remote-ID oder das ETag");
  assert.deepStrictEqual(davRoundtrip.kontakte[0].syncQuellen["nextcloud-addressbook:test"], davMapping,
    "Kontakt-Normalisierung verlor die DAV-Remote-ID oder das ETag");
  assert.deepStrictEqual(davRoundtrip.geloescht.termine[0].syncQuellen["nextcloud-calendar:test"], davMapping,
    "Termin-Tombstone verlor die DAV-Löschzuordnung");
  assert.deepStrictEqual(davRoundtrip.geloescht.kontakte[0].syncQuellen["nextcloud-addressbook:test"], davMapping,
    "Kontakt-Tombstone verlor die DAV-Löschzuordnung");
  const smsNormalisiert = T.normalisiere({ smsVerlauf: [
    { id: "gut", kontaktId: "k1", nummer: "0171 1234567", richtung: "ausgang",
      text: "x".repeat(6000), zeit: Date.now(), status: "sent", client_ref: "ref-1",
      weg: "kde", geraet: "g".repeat(300), fehler: "f".repeat(2000) },
    { id: "schlecht", nummer: "x", richtung: "seitlich", text: "Text", zeit: -1 }
  ], einstellungen: { adressen: { kommunikation: {
    sms: { art: "program", programm: "  app {nummer}  " },
    anruf: { art: "kde", programm: "ignoriert" } } } } });
  assert.strictEqual(smsNormalisiert.smsVerlauf.length, 1,
    "SMS-Verlauf verwirft ungültige Einträge nicht");
  assert.deepStrictEqual({ nummer: smsNormalisiert.smsVerlauf[0].nummer,
    text: smsNormalisiert.smsVerlauf[0].text.length,
    status: smsNormalisiert.smsVerlauf[0].status,
    clientRef: smsNormalisiert.smsVerlauf[0].clientRef,
    fehler: smsNormalisiert.smsVerlauf[0].fehler.length },
  { nummer: "+491711234567", text: 5000, status: "sent", clientRef: "ref-1", fehler: 1000 },
  "SMS-Verlauf wird nicht streng begrenzt und normalisiert");
  assert.deepStrictEqual(smsNormalisiert.einstellungen.adressen.kommunikation,
    { sms: { art: "program", programm: "app {nummer}" },
      anruf: { art: "magnolie", programm: "ignoriert", eingehendBenachrichtigen: false,
        computerTelefonie: false, klingeltonLeiser: false, hfpAdresse: "" } },
  "Kommunikationsbelegung wird nicht streng nach SMS-/Anrufsemantik normalisiert");
  assert.strictEqual(smsNormalisiert.einstellungen.adressen.smsBenachrichtigungDauer, 60,
    "die SMS-Benachrichtigungsdauer fällt nicht auf 60 Sekunden zurück");
  assert.strictEqual(T.normalisiere({ einstellungen: { adressen: {
    smsBenachrichtigungDauer: 0 } } }).einstellungen.adressen.smsBenachrichtigungDauer, 0,
  "die Einstellung Nie automatisch wird nicht bewahrt");
  assert.strictEqual(T.normalisiere({ einstellungen: { adressen: { kommunikation: { anruf: {
    art: "magnolie", telefonId: "telefon-gebunden", computerTelefonie: true } } } } })
    .einstellungen.adressen.kommunikation.anruf.telefonId, "telefon-gebunden",
  "die Gerätebindung gespeicherter Anrufrechte geht bei der Normalisierung verloren");
  assert.strictEqual(T.normalisiere({ einstellungen: { adressen: { kommunikation: { anruf: {
    art: "magnolie", hfpAdresse: "aa:bb:cc:dd:ee:ff" } } } } })
    .einstellungen.adressen.kommunikation.anruf.hfpAdresse, "AA:BB:CC:DD:EE:FF",
  "eine gültige HFP-Adresse wird nicht kanonisch gespeichert");
  assert.strictEqual(T.normalisiere({ einstellungen: { adressen: { kommunikation: { anruf: {
    art: "magnolie", hfpAdresse: "AA:BB:CC:DD:EE:FF\n--command" } } } } })
    .einstellungen.adressen.kommunikation.anruf.hfpAdresse, "",
  "eine manipulierte HFP-Adresse wird nicht verworfen");
  assert.strictEqual($("#contributor-wasserzeichen"), null,
    "ein normaler Quellbau enthält das Contributor-Wasserzeichen");

  const contributorDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://contributor.test/",
    pretendToBeVisual: true
  });
  const contributorNachrichten = [];
  contributorDom.window.__MAGNOLIE_BRUECKE__ = "contributor_bridge";
  contributorDom.window.webkit = { messageHandlers: { contributor_bridge: {
    postMessage: (text) => contributorNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(contributorDom.window, "de");
  contributorDom.window.document.dispatchEvent(new contributorDom.window.Event(
    "DOMContentLoaded", { bubbles: true }));
  contributorDom.window.App.init({ daten: {}, neu: false, contributorAktiv: true,
    regional: { language: "de" } });
  const contributorDokument = contributorDom.window.document;
  assert.strictEqual(contributorDokument.querySelector("#contributor-wasserzeichen")
    .textContent, "No valid coffee allowance",
  "das Contributor-Wasserzeichen ist übersetzt oder verwendet nicht den festen Wortlaut");
  contributorDom.window.OrganizerTest.oeffneEinstellungen();
  contributorDokument.querySelector("#einst-tab-ueber").click();
  const contributorFeld = contributorDokument.querySelector("#contributor-key");
  contributorFeld.value = "nur-ein-testwert";
  contributorDokument.querySelector("#contributor-freischalten").click();
  assert.ok(contributorNachrichten.some((nachricht) =>
    nachricht.cmd === "contributor_pruefen" && nachricht.key === "nur-ein-testwert"),
  "der Contributor Key wird nicht durch den nativen Host geprüft");
  contributorDom.window.App.contributorGeprueft({ ok: true });
  assert.strictEqual(contributorDokument.querySelector("#contributor-wasserzeichen"), null,
    "die Freischaltung entfernt das Contributor-Wasserzeichen nicht");
  assert.strictEqual(contributorDokument.querySelector("#contributor-key"), null,
    "das Contributor-Key-Feld bleibt nach der Freischaltung sichtbar");
  contributorDom.window.close();
  const anhangDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://attachment.test/", pretendToBeVisual: true
  });
  const anhangNachrichten = [];
  anhangDom.window.__MAGNOLIE_BRUECKE__ = "attachment_bridge";
  anhangDom.window.webkit = { messageHandlers: { attachment_bridge: {
    postMessage: (text) => anhangNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(anhangDom.window, "en");
  const anhangW = anhangDom.window, anhangD = anhangW.document;
  anhangW.App.init({ daten: { notizen: [{ id: "attachment-note", titel: "Files",
    notizbuchId: "lose-notizen", anhaenge: [
      { id: "attachment-image", name: "Photo.png", art: "image",
        daten: "data:image/png;base64,iVBORw0KGgo=" },
      { id: "attachment-pdf", name: "Paper.pdf", art: "pdf",
        daten: "data:application/pdf;base64,JVBERi0xLjQ=" }] }] }, neu: false,
    regional: { language: "en" } });
  anhangW.OrganizerTest.zustand().notizen.auswahlId = "attachment-note";
  anhangW.OrganizerTest.wechsel("notizen");
  const anhangDateiNachrichten = () => anhangNachrichten.filter(
    (nachricht) => nachricht.cmd === "notiz_anhang_datei");
  const bildAktion = anhangD.querySelector(".notiz-anhang.image .notiz-anhang-bild");
  bildAktion.click();
  assert.deepStrictEqual(Array.from(anhangD.querySelectorAll(
    "#notiz-anhang-aktion-schleier .dialog-knoepfe button"), (b) => b.textContent),
  ["Cancel", "Save as…", "Open"], "Anhangsdialog bietet nicht genau drei Aktionen");
  anhangD.dispatchEvent(new anhangW.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await tick();
  assert.strictEqual(anhangDateiNachrichten().length, 0,
    "Escape löst eine Anhangsaktion aus");
  anhangD.querySelector(".notiz-anhang.pdf .notiz-anhang-symbol").click();
  anhangD.querySelector("#notiz-anhang-aktion-schleier").click();
  await tick();
  assert.strictEqual(anhangDateiNachrichten().length, 0,
    "Klick außerhalb löst eine Anhangsaktion aus");
  anhangD.querySelector(".notiz-anhang.pdf .notiz-anhang-name").click();
  Array.from(anhangD.querySelectorAll("#notiz-anhang-aktion-schleier button"))
    .find((b) => b.textContent === "Open").click();
  await tick();
  assert.deepStrictEqual(anhangDateiNachrichten().at(-1), {
    cmd: "notiz_anhang_datei", id: 1,
    aktion: "open", name: "Paper.pdf",
    daten: "data:application/pdf;base64,JVBERi0xLjQ=" },
  "PDF-Öffnen erreicht die native Bridge nicht unverändert");
  bildAktion.click();
  Array.from(anhangD.querySelectorAll("#notiz-anhang-aktion-schleier button"))
    .find((b) => b.textContent === "Save as…").click();
  await tick();
  assert.strictEqual(anhangDateiNachrichten().at(-1).aktion, "save",
    "Bild-Speichern-unter erreicht die native Bridge nicht");
  const anzahlVorEntfernen = anhangDateiNachrichten().length;
  Array.from(anhangD.querySelectorAll(".notiz-anhang.image figcaption button"))
    .find((b) => b.textContent === "Remove").click();
  assert.strictEqual(anhangD.querySelector("#notiz-anhang-aktion-schleier"), null,
    "Entfernen öffnet fälschlich den Anhangsaktionsdialog");
  assert.ok(anhangD.querySelector("#dialog-text").textContent.includes("Photo.png"),
    "Entfernen öffnet nicht seinen eigenen Bestätigungsdialog");
  assert.strictEqual(anhangDateiNachrichten().length, anzahlVorEntfernen,
    "Entfernen sendet fälschlich eine Dateiaktion");
  anhangD.querySelector("#dialog-nein").click();
  anhangDom.window.close();

  /* ---- Zentraler Änderungswächter ---- */
  const guardDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://guard.test/", pretendToBeVisual: true
  });
  const guardNachrichten = [];
  guardDom.window.__MAGNOLIE_BRUECKE__ = "guard_bridge";
  guardDom.window.webkit = { messageHandlers: { guard_bridge: {
    postMessage: (text) => guardNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(guardDom.window, "en");
  const gw = guardDom.window, gd = gw.document, gT = gw.OrganizerTest;
  const guardStil = gd.createElement("style");
  guardStil.textContent = css;
  gd.head.append(guardStil);
  gw.App.init({ daten: { kontakte: [
    { id: "guard-one", uid: "", nachname: "One", vorname: "Alice" },
    { id: "guard-two", uid: "", nachname: "Other", vorname: "Bob" }
  ] }, neu: false, regional: { language: "en" } });
  const gButton = (text, wurzel = gd) => Array.from(wurzel.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === text);
  const gAktion = (text) => gButton(text, gd.querySelector("#aenderungen-schleier"));
  const gGesundheit = (titel) => Array.from(gd.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === titel);
  const gSetze = (feld, wert) => {
    feld.value = wert;
    feld.dispatchEvent(new gw.Event("input", { bubbles: true }));
  };

  await gT.wechsel("adressen");
  gButton("New").click();
  gButton("Calendar").click();
  await tick();
  assert.strictEqual(gd.querySelector("#aenderungen-schleier"), null,
    "ein unveränderter neuer Kontakt fragt beim Verlassen nach");
  assert.strictEqual(gT.zustand().sektion, "kalender");

  await gT.wechsel("adressen");
  gButton("New").click();
  const neuerName = gd.querySelector("#kontakt-nachname");
  gSetze(neuerName, "Guard new");
  gSetze(neuerName, "");
  gButton("Calendar").click();
  await tick();
  assert.strictEqual(gd.querySelector("#aenderungen-schleier"), null,
    "Kontaktänderung und Rückänderung gelten noch als geändert");

  await gT.wechsel("adressen");
  gButton("New").click();
  gSetze(gd.querySelector("#kontakt-nachname"), "Keep me");
  const schreibtisch = gd.querySelector("#schreibtisch");
  const schreibtischEltern = schreibtisch.parentNode;
  const schreibtischIndex = Array.from(gd.body.children).indexOf(schreibtisch);
  const rechteckWerte = (element) => {
    const r = element.getBoundingClientRect();
    return [r.x, r.y, r.width, r.height, r.top, r.right, r.bottom, r.left];
  };
  const schreibtischRechteck = rechteckWerte(schreibtisch);
  gButton("Calendar").click();
  gButton("Calendar").click();
  assert.strictEqual(gd.querySelectorAll("#aenderungen-schleier").length, 1,
    "Doppelklick öffnet mehr als einen Änderungsdialog");
  const aenderungsSchleier = gd.querySelector("#aenderungen-schleier");
  const overlayStil = gw.getComputedStyle(aenderungsSchleier);
  assert.strictEqual(overlayStil.position, "fixed",
    "der Änderungsdialog liegt in jsdom nicht über dem Dokumentfluss");
  assert.strictEqual(overlayStil.display, "flex");
  assert.strictEqual(overlayStil.alignItems, "center");
  assert.strictEqual(overlayStil.justifyContent, "center");
  assert.strictEqual(aenderungsSchleier.parentNode, gd.body,
    "der Overlay-Vertrag erwartet den Schleier direkt unter body");
  assert.strictEqual(schreibtisch.parentNode, schreibtischEltern);
  assert.strictEqual(Array.from(gd.body.children).indexOf(schreibtisch), schreibtischIndex,
    "das Öffnen des Overlays verschiebt den Schreibtisch im DOM");
  assert.deepStrictEqual(rechteckWerte(schreibtisch), schreibtischRechteck,
    "das Öffnen des Overlays verändert in jsdom das Schreibtisch-Rechteck");
  gd.dispatchEvent(new gw.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await tick();
  assert.strictEqual(gT.zustand().sektion, "adressen");
  assert.strictEqual(gd.querySelector("#kontakt-nachname").value, "Keep me",
    "Escape hält den Kontakteditor nicht unverändert offen");

  gButton("Calendar").click();
  gAktion("Discard").click();
  await tick();
  assert.strictEqual(gT.daten().kontakte.length, 2,
    "Verwerfen eines neuen Kontakts mutiert DATEN");
  assert.strictEqual(gT.zustand().sektion, "kalender");

  await gT.wechsel("adressen");
  gButton("New").click();
  gSetze(gd.querySelector("#kontakt-nachname"), "Saved guard");
  gButton("Calendar").click();
  gAktion("Save").click();
  await tick();
  assert.ok(gT.daten().kontakte.some((kontakt) => kontakt.nachname === "Saved guard") &&
    gT.zustand().sektion === "kalender",
  "Speichern im Guard legt neuen Kontakt nicht vollständig vor Navigation an");

  await gT.wechsel("adressen");
  gT.zustand().adressen.buchstabe = "O";
  gT.zustand().adressen.modus = "ansehen";
  gT.wechsel("kalender"); await tick(); await gT.wechsel("adressen");
  gT.zustand().adressen.auswahlId = "guard-one";
  gT.zustand().adressen.modus = "ansehen";
  gd.querySelector("#register-links,#register-rechts");
  gT.wechsel("kalender");
  await tick();
  await gT.wechsel("adressen");
  Array.from(gd.querySelectorAll(".zeilen-aktion"))
    .find((button) => button.textContent.includes("One")).click();
  gButton("Edit").click();
  gSetze(gd.querySelector("#kontakt-vorname"), "Changed");
  Array.from(gd.querySelectorAll(".zeilen-aktion"))
    .find((button) => button.textContent.includes("Other")).click();
  gAktion("Discard").click();
  await tick();
  assert.strictEqual(gT.daten().kontakte.find((kontakt) => kontakt.id === "guard-one").vorname,
    "Alice", "Verwerfen eines bestehenden Kontakts mutiert DATEN");
  assert.strictEqual(gT.zustand().adressen.auswahlId, "guard-two",
    "Kontaktlistennavigation wird nach Verwerfen nicht ausgeführt");

  Array.from(gd.querySelectorAll(".zeilen-aktion"))
    .find((button) => button.textContent.includes("One")).click();
  gButton("Edit").click();
  gSetze(gd.querySelector("#kontakt-nachname"), "");
  gSetze(gd.querySelector("#kontakt-vorname"), "");
  gButton("Calendar").click();
  gAktion("Save").click();
  await tick();
  assert.strictEqual(gT.zustand().sektion, "adressen",
    "ungültiger bestehender Kontakt navigiert nach fehlgeschlagenem Speichern");
  assert.ok(gd.querySelector("#kontakt-nachname"), "Validierungsfehler schließt den Kontakteditor");
  gButton("Calendar").click(); gAktion("Discard").click(); await tick();

  await gT.wechsel("gesundheit");
  const gesundFeld = gd.querySelector(".vitalwert-tabelle input");
  gSetze(gesundFeld, "2026-08-12");
  gGesundheit("Medication plan").click();
  assert.ok(gd.querySelector("#aenderungen-schleier"),
    "Gesundheits-Unteransicht umgeht den zentralen Guard");
  gd.querySelector("#aenderungen-schleier").click();
  await tick();
  assert.ok(gd.querySelector(".vitalwert-tabelle") && gesundFeld.isConnected,
    "Außenklick hält den Gesundheitseditor nicht offen");
  gGesundheit("Medication plan").click(); gAktion("Discard").click(); await tick();
  assert.strictEqual(gT.daten().gesundheit.vitalwerte.length, 0,
    "Verwerfen eines Gesundheitsentwurfs mutiert DATEN");

  gGesundheit("Vital signs").click();
  const gesundFeld2 = gd.querySelector(".vitalwert-tabelle input");
  gSetze(gesundFeld2, "2026-08-12");
  gSetze(gesundFeld2, "");
  gGesundheit("Medication plan").click(); await tick();
  assert.strictEqual(gd.querySelector("#aenderungen-schleier"), null,
    "Gesundheitsänderung und Rückänderung gelten noch als geändert");

  gGesundheit("Vital signs").click();
  const gesundFelder = gd.querySelector(".vitalwert-tabelle").querySelectorAll("input");
  gSetze(gesundFelder[2], "80");
  gButton("Calendar").click(); gAktion("Save").click(); await tick();
  assert.strictEqual(gT.zustand().sektion, "gesundheit",
    "Gesundheitsvalidierung ohne Datum lässt Navigation zu");
  gButton("Calendar").click(); gAktion("Discard").click(); await tick();

  await gT.wechsel("adressen"); gButton("New").click();
  gSetze(gd.querySelector("#kontakt-nachname"), "Unload");
  const unload = new gw.Event("beforeunload", { cancelable: true });
  assert.strictEqual(gw.dispatchEvent(unload), false,
    "beforeunload wird bei geändertem Editor nicht verhindert");
  gw.App.vorBeenden();
  await tick();
  gAktion("Cancel").click(); await tick();
  assert.ok(guardNachrichten.some((nachricht) => nachricht.cmd === "beenden_abgebrochen") &&
    !guardNachrichten.some((nachricht) => nachricht.cmd === "beenden_bereit"),
  "natives Abbrechen setzt Beenden nicht explizit zurück");
  gw.App.vorBeenden(); await tick(); gAktion("Save").click(); await tick();
  const guardSpeichern = guardNachrichten.filter((nachricht) => nachricht.cmd === "speichern").at(-1);
  assert.ok(guardSpeichern && gT.daten().kontakte.some(
    (kontakt) => kontakt.nachname === "Unload"),
  "natives Speichern übernimmt den Kontakt nicht vollständig");
  const abbruecheVorSpeicherfehler = guardNachrichten.filter(
    (nachricht) => nachricht.cmd === "beenden_abgebrochen").length;
  gw.App.gespeichert({ id: guardSpeichern.id, ok: false });
  await tick();
  assert.strictEqual(guardNachrichten.filter(
    (nachricht) => nachricht.cmd === "beenden_abgebrochen").length,
  abbruecheVorSpeicherfehler + 1,
  "Speicherfehler setzt den nativen Schließzustand nicht zurück");
  gw.App.vorBeenden();
  await tick();
  let bestaetigteGuardSpeicher = 0;
  while (!guardNachrichten.some((nachricht) => nachricht.cmd === "beenden_bereit")) {
    const saves = guardNachrichten.filter((nachricht) => nachricht.cmd === "speichern");
    if (bestaetigteGuardSpeicher >= saves.length) break;
    const save = saves[bestaetigteGuardSpeicher++];
    gw.App.gespeichert({ id: save.id, ok: true });
    await tick();
  }
  assert.ok(guardNachrichten.some((nachricht) => nachricht.cmd === "beenden_bereit"),
    "natives Beenden wird nicht erst nach bestätigtem Speichern freigegeben");
  guardDom.window.close();
  const schema3 = T.normalisiere({ version: 2,
    termine: [{ datum: "2026-08-04", titel: "Alt", wiederholung: { art: "woche" } }],
    kontakte: [{ nachname: "Alt", anschriften: [
      { strasse: "Weg 1", ort: "Duisburg", typen: ["X-ZWEITSITZ"] }],
      sozialeMedien: [{ dienstId: "phone", wert: "0203 123456",
        aktionArtId: "program", aktionZiel: "dial {ziel}" }] }],
    jahrestage: [
      { name: "Oma", datum: "1950-03-04", typ: "Geburtstag" },
      { name: "Familie", datum: "2000-03-04", typ: "Familientag" }],
    feiertage: [{ von: "2026-07-01", name: "Sommerferien", art: "ferien" }],
    papierkorb: [{ art: "termin", name: "Alt", geloescht: 1,
      eintrag: { datum: "2026-08-05", titel: "Korb",
        wiederholung: { art: "monat" } } }],
    einstellungen: { schrift: { art: "hand", farbe: "blau", groesse: "gross",
      radRichtung: "hoch-spaeter" }, ansicht: "woche",
      erinnerung: { art: "meldung" }, adressen: { sortierung: "vorname",
        briefLayout: "kompakt" }, allgemein: { wetterDarstellung: "ausfuehrlich",
        tray: { oeffnen: "zentriert" } } } });
  assert.deepStrictEqual({
    version: schema3.version,
    wiederholung: schema3.termine[0].wiederholung.art,
    anschrift: schema3.kontakte[0].anschriften[0].typen,
    dienst: schema3.kontakte[0].sozialeMedien[0].dienst,
    aktion: schema3.kontakte[0].sozialeMedien[0].aktionArt,
    jahrestage: schema3.jahrestage.map((eintrag) => eintrag.typ),
    feiertag: schema3.feiertage[0].art,
    papierkorb: [schema3.papierkorb[0].art,
      schema3.papierkorb[0].eintrag.wiederholung.art],
    schrift: schema3.einstellungen.schrift,
    ansicht: schema3.einstellungen.ansicht,
    erinnerung: schema3.einstellungen.erinnerung.art,
    sortierung: schema3.einstellungen.adressen.sortierung,
    briefLayout: schema3.einstellungen.adressen.briefLayout,
    wetter: schema3.einstellungen.allgemein.wetterDarstellung,
    wetterOhneOrt: schema3.einstellungen.allgemein.wetterOhneOrtAbrufen,
    tray: schema3.einstellungen.allgemein.tray.oeffnen
  }, {
    version: 6, wiederholung: "weekly", anschrift: ["X-SECONDARY-OFFICE"],
    dienst: "phone", aktion: "program", jahrestage: ["birthday", "Familientag"],
    feiertag: "school-holiday", papierkorb: ["appointment", "monthly"],
    schrift: { art: "handwriting", farbe: "blue", groesse: "large",
      rechtschreibung: true, linien: true, radRichtung: "up-later" },
    ansicht: "week", erinnerung: "notification", sortierung: "first-name",
    briefLayout: "compact", wetter: "detailed", wetterOhneOrt: true,
    tray: "centered"
  }, "Schema 6 migriert kontrollierte Altwerte nicht vollständig");
  const begrenzterPapierkorb = T.normalisiere({ papierkorb: Array.from(
    { length: 3002 }, (_, i) => ({ id: "korb-" + i, art: "termin", name: "Korb " + i,
      geloescht: i + 1, eintrag: { id: "termin-" + i, datum: "2026-08-04", titel: "Termin " + i } })) });
  assert.strictEqual(begrenzterPapierkorb.papierkorb.length, 3000,
    "eingelesener Papierkorb überschreitet die feste Obergrenze");
  assert.deepStrictEqual(begrenzterPapierkorb.papierkorb.map((x) => x.id).slice(0, 2),
    ["korb-2", "korb-3"], "Papierkorbbegrenzung verwirft nicht die ältesten Einträge");
  assert.ok(js.includes("edsZeigerBereinigt || papierkorbBereinigt"),
    "beim Start entfernte Papierkorbeinträge werden nicht dauerhaft gespeichert");
  const geburtstagsMigration = T.normalisiere({ kontakte: [{ id: "kontakt-mit-jt",
    vorname: "Erika", nachname: "Beispiel", geburtstag: "1980-04-05" }],
    jahrestage: [{ kontaktId: "kontakt-mit-jt", name: "Erika Beispiel",
      datum: "2000-06-07", typ: "wedding-anniversary" }] });
  assert.ok(geburtstagsMigration.jahrestage.some((j) =>
    j.kontaktId === "kontakt-mit-jt" && j.typ === "birthday" &&
    j.datum === "1980-04-05"),
  "ein anderer verknüpfter Jahrestag unterdrückt die Geburtstagsmigration");
  const datumsMigration = T.normalisiere({ kontakte: [
    { id: "teil", geburtstag: "--02-29" },
    { id: "wahr", geburtstag: "1980-04-05", geburtstagJahrUnbekannt: true },
    { id: "falsch", geburtstag: "1900-02-28", geburtstagJahrUnbekannt: false },
    { id: "fehlend-1604", geburtstag: "1604-12-30" },
    { id: "fehlend-2000", geburtstag: "2000-01-02" }
  ], jahrestage: [
    { name: "Teil", datum: "--02-29" },
    { name: "Wahr", datum: "1980-04-05", jahrUnbekannt: true },
    { name: "Falsch", datum: "1900-04-03", jahrUnbekannt: false },
    { name: "Geburt 1604", datum: "1604-11-19", typ: "birthday" },
    { name: "Jahr 2000", datum: "2000-06-07" }
  ] });
  assert.deepStrictEqual(datumsMigration.kontakte.map((k) =>
    [k.geburtstag, k.geburtstagJahrUnbekannt]), [
    ["--02-29", true], ["--04-05", true], ["1900-02-28", false],
    ["1604-12-30", false], ["2000-01-02", false]
  ], "Kontaktmigration beachtet nicht exakt true, false und fehlende Altflags");
  assert.deepStrictEqual(datumsMigration.jahrestage.filter((j) => !j.kontaktId).map((j) =>
    [j.datum, j.jahrUnbekannt]), [
    ["--02-29", true], ["--04-05", true], ["1900-04-03", false],
    ["1604-11-19", false], ["2000-06-07", false]
  ], "Jahrestagsmigration darf weder Jahreszahl noch Geburtstagstyp als Sentinel deuten");
  const verknuepftesDatum = T.normalisiere({ kontakte: [
    { id: "gleich", geburtstag: "1980-04-05", geburtstagJahrUnbekannt: true }
  ], jahrestage: [
    { kontaktId: "gleich", name: "Gleich", datum: "1999-06-07", typ: "birthday" }
  ] });
  assert.deepStrictEqual([verknuepftesDatum.kontakte[0].geburtstag,
    verknuepftesDatum.jahrestage[0].datum], ["--04-05", "--04-05"],
  "verknüpfter Kontakt und Geburtstag verwenden nicht denselben kanonischen Wert");
  assert.deepStrictEqual([
    T.gueltigesTeildatum("--02-29"), T.gueltigesTeildatum("--02-30"),
    T.gueltigesTeildatum("--13-01"), T.gueltigesJahresdatum("2000-02-29"),
    T.gueltigesJahresdatum("1900-02-29")
  ], [true, false, false, true, false], "strikte Teil- oder Volldatumsprüfung ist fehlerhaft");
  assert.deepStrictEqual([
    T.monatTag("--12-30"), T.monatTag("1604-12-30"),
    T.projiziereJahresdatum("--02-29", 2024),
    T.projiziereJahresdatum("--02-29", 2025),
    T.hatBekanntesJahr("--02-29"), T.hatBekanntesJahr("1604-02-29")
  ], ["12-30", "12-30", "2024-02-29", "2025-02-28", false, true],
  "Monat-Tag, bekanntes Jahr oder Schaltjahrprojektion ist fehlerhaft");
  assert.strictEqual(T.naechsterJahrestag({ datum: "--02-29", typ: "birthday" }).anzahl,
    null, "ein Geburtstag ohne Jahr erzeugt eine Altersangabe");
  const projiziertSortiert = ["--12-30", "--01-02", "1604-06-07"]
    .sort((a, b) => T.projiziereJahresdatum(a, 2026)
      .localeCompare(T.projiziereJahresdatum(b, 2026)));
  assert.deepStrictEqual(projiziertSortiert, ["--01-02", "1604-06-07", "--12-30"],
    "Jahresprojektion liefert keine chronologische Sortiergrundlage");
  const baumTeil = { vorname: "Ada", geburtstag: "--02-29", telefone: [],
    emailEintraege: [], anschriften: [], foto: "", baumKontakt: {
      freigabeId: "teil-payload", version: 1, quelle: "test", geaendert: 1 } };
  assert.strictEqual(T.kontaktBaumInhalt(baumTeil).kontakt.geburtstag, "--02-29",
    "Magnolienbaum-Nutzlast verwirft oder erfindet das unbekannte Geburtsjahr");
  baumTeil.geburtstag = "1900-02-28";
  assert.strictEqual(T.kontaktBaumInhalt(baumTeil).kontakt.geburtstag, "1900-02-28",
    "Magnolienbaum-Nutzlast verändert ein bekanntes altes Geburtsjahr");
  baumTeil.geburtstag = "--02-30";
  assert.strictEqual(T.kontaktBaumInhalt(baumTeil).kontakt.geburtstag, "",
    "Magnolienbaum-Nutzlast sendet ein unmögliches Teildatum");
  const jahrestageVorMerge = T.daten().jahrestage.length;
  T.mergeJahrestage([
    { name: "Kanonischer Merge", datum: "2000-09-08", jahrUnbekannt: true },
    { name: "Ungültiger Merge", datum: "--02-30" }
  ]);
  assert.deepStrictEqual(T.daten().jahrestage.slice(jahrestageVorMerge).map((j) => j.datum),
    ["--09-08"], "Jahrestagsimport normalisiert Teildaten nicht konservativ");
  T.daten().jahrestage.splice(jahrestageVorMerge);
  T.mergeKontakte([{ uid: "kanonischer-kontakt-merge", vorname: "Merge",
    nachname: "Teil", geburtstag: "--02-29" }]);
  const kontaktMerge = T.daten().kontakte.find((k) => k.uid === "kanonischer-kontakt-merge");
  const kontaktMergeJt = T.daten().jahrestage.find((j) =>
    kontaktMerge && j.kontaktId === kontaktMerge.id && j.typ === "birthday");
  assert.deepStrictEqual([kontaktMerge && kontaktMerge.geburtstag,
    kontaktMergeJt && kontaktMergeJt.datum], ["--02-29", "--02-29"],
  "Kontaktmerge hält Kontakt und abgeleiteten Geburtstag nicht kanonisch gleich");
  T.daten().kontakte = T.daten().kontakte.filter((k) => k !== kontaktMerge);
  T.daten().jahrestage = T.daten().jahrestage.filter((j) => j !== kontaktMergeJt);
  const wetterOptout = T.normalisiere({ einstellungen: {
    allgemein: { wetterOhneOrtAbrufen: false } } });
  assert.strictEqual(wetterOptout.einstellungen.allgemein.wetterOhneOrtAbrufen, false,
    "die gespeicherte Wetter-Datenschutzoption übersteht die Normalisierung nicht");
  const registerNormalisiert = T.normalisiere({ einstellungen: {
    allgemein: { registerkarten: { aufgaben: false, adressen: false,
      notizen: true, jahrestage: false, planer: true, gesundheit: true } },
    kalender: { gesundheitAn: false } } });
  assert.deepStrictEqual(registerNormalisiert.einstellungen.allgemein.registerkarten,
    { aufgaben: false, adressen: false, notizen: true, jahrestage: false,
      planer: true, gesundheit: true },
  "die gewählte Registerausstattung übersteht Speichern und Laden nicht");
  assert.ok(registerNormalisiert.einstellungen.kalender.gesundheitAn,
    "das Gesundheitsregister und seine bestehenden Kalenderoptionen laufen auseinander");
  const registerAltbestand = T.normalisiere({ einstellungen: {
    kalender: { gesundheitAn: true } } });
  assert.ok(registerAltbestand.einstellungen.allgemein.registerkarten.gesundheit,
    "ein bisher sichtbares Gesundheitsregister verschwindet bei der Migration");
  const muellNormalisiert = T.normalisiere({ muelltermine: [
    { name: "Restmüll", von: "2026-08-03", intervallTage: 999,
      farbe: "#ABCDEF", art: "residual" },
    { name: "Ungültig", von: "morgen", intervallTage: 14 }
  ], einstellungen: { kalender: { muellkalenderAn: true } } });
  assert.deepStrictEqual(muellNormalisiert.muelltermine.map((termin) => ({
    name: termin.name, von: termin.von, intervallTage: termin.intervallTage,
    farbe: termin.farbe, art: termin.art
  })), [{ name: "Restmüll", von: "2026-08-03", intervallTage: 365,
    farbe: "#abcdef", art: "residual" }],
  "Müllabholungen werden nicht begrenzt und sicher normalisiert");
  assert.ok(muellNormalisiert.einstellungen.kalender.muellkalenderAn,
    "der Müllkalender-Schalter übersteht die Normalisierung nicht");
  const gesundheitNormalisiert = T.normalisiere({ gesundheit: {
    vitalwerte: [{ datum: "2026-08-03", systolisch: 120, diastolisch: 80,
      gewicht: "72,5", groesse: 180 }, { datum: "morgen", puls: 70 }],
    blutzucker: [{ datum: "2026-08-03", wert: 105, einheit: "mg/dL" }],
    medikamente: [{ name: "Beispiel", art: "insulin", von: "2026-08-01",
      bis: "2026-08-31", wochentage: [1, 1, 9], aktiv: true }]
  }, einstellungen: { kalender: { gesundheitAn: true } } });
  assert.deepStrictEqual([
    gesundheitNormalisiert.gesundheit.vitalwerte.length,
    gesundheitNormalisiert.gesundheit.vitalwerte[0].gewicht,
    gesundheitNormalisiert.gesundheit.blutzucker[0].wert,
    gesundheitNormalisiert.gesundheit.medikamente[0].wochentage,
    gesundheitNormalisiert.einstellungen.kalender.gesundheitAn
  ], [1, 72.5, 105, [1], true],
  "Gesundheitsdaten werden nicht begrenzt und rückwärtskompatibel normalisiert");
  const gesundheitOhneAnsicht = T.normalisiere({ einstellungen: { kalender: {
    gesundheitBereiche: { vital: false, medikamente: false, blutzucker: false, verlauf: false }
  } } });
  assert.deepStrictEqual(gesundheitOhneAnsicht.einstellungen.kalender.gesundheitBereiche,
    { vital: true, medikamente: false, blutzucker: false, verlauf: false },
  "importierte Einstellungen ohne Gesundheitsansicht erhalten keinen sicheren Rückfall");
  assert.strictEqual(T.kanonischerText(" Straße  ÄÖÜ "), "strasse aou",
    "fachliche Textschlüssel hängen weiterhin von Sprache oder Akzenten ab");

  const anhangLesen = (bytes, name, type, art) => new Promise((aufloesen) => {
    const datei = new w.File([new Uint8Array(bytes)], name, { type: type });
    T.notizAnhangLesen(datei, art, (anhang, fehler) => aufloesen({ anhang, fehler }));
  });
  const anhangProben = [
    ["image", "probe.jpg", "image/png", [0xff, 0xd8, 0xff, 0xe0], "image/jpeg"],
    ["image", "probe.png", "", [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
      "image/png"],
    ["image", "probe.webp", "application/octet-stream",
      [0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50], "image/webp"],
    ["image", "probe.gif", "", [0x47, 0x49, 0x46, 0x38, 0x37, 0x61], "image/gif"],
    ["image", "probe-89.gif", "application/octet-stream",
      [0x47, 0x49, 0x46, 0x38, 0x39, 0x61], "image/gif"],
    ["pdf", "probe.pdf", "application/x-pdf", [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31],
      "application/pdf"]
  ];
  const geleseneAnhaenge = [];
  for (const [art, name, type, bytes, mime] of anhangProben) {
    const ergebnis = await anhangLesen(bytes, name, type, art);
    assert.ok(ergebnis.anhang && !ergebnis.fehler &&
      ergebnis.anhang.daten.startsWith("data:" + mime + ";base64,") &&
      ergebnis.anhang.name === name && ergebnis.anhang.art === art,
    "signaturbasierter Anhang fehlt für " + name + " mit MIME " + (type || "leer"));
    geleseneAnhaenge.push(ergebnis.anhang);
  }
  const falschesBild = await anhangLesen(
    [0x25, 0x50, 0x44, 0x46, 0x2d], "umbenannt.png", "image/png", "image");
  const falschesPdf = await anhangLesen(
    [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
    "umbenannt.pdf", "application/pdf", "pdf");
  assert.ok(!falschesBild.anhang && !falschesPdf.anhang &&
    falschesBild.fehler === "Die Datei hat ein nicht unterstütztes Format." &&
    falschesPdf.fehler === falschesBild.fehler,
  "Dateiname oder deklarierter MIME-Typ umgehen die Signaturprüfung");
  const zuGross = new w.File([new Uint8Array(8 * 1024 * 1024 + 1)], "gross.png",
    { type: "image/png" });
  const zuGrossErgebnis = await new Promise((aufloesen) =>
    T.notizAnhangLesen(zuGross, "image", (anhang, fehler) =>
      aufloesen({ anhang, fehler })));
  assert.ok(!zuGrossErgebnis.anhang &&
    zuGrossErgebnis.fehler === "Die Datei ist größer als 8 Megabyte.",
  "die 8-MiB-Einzelgrenze wird beim ArrayBuffer-Lesen nicht durchgesetzt");
  const anhangBestand = T.normalisiere({ notizen: [{ id: "anhang-rundlauf",
    titel: "Linux-Anhänge", anhaenge: geleseneAnhaenge }] });
  assert.deepStrictEqual(anhangBestand.notizen[0].anhaenge.map((anhang) => ({
    name: anhang.name, art: anhang.art, daten: anhang.daten
  })), geleseneAnhaenge.map((anhang) => ({
    name: anhang.name, art: anhang.art, daten: anhang.daten
  })), "JPEG, PNG, WebP, GIF und PDF überstehen den Speichern/Laden-Rundlauf nicht");
  assert.deepStrictEqual(T.daten().einstellungen.regional,
    { language: "de", formatLocale: "de-DE", hourCycle: "h23",
      firstDayOfWeek: "monday", weekRule: "iso",
      temperatureUnit: "celsius", timeZone: "system" },
  "deutsches Bestandsprofil wird regional nicht unverändert festgeschrieben");
  assert.strictEqual(T.fmtPunkt("2026-08-03"), "03.08.2026",
    "deutsches kurzes Datumsformat hat sich geändert");
  assert.strictEqual(T.fmtLang("2026-08-03"), "Montag, 3. August 2026",
    "deutsches langes Datumsformat hat sich geändert");
  const zonenProbe = new Date("2026-08-05T02:07:00Z");
  T.daten().einstellungen.regional.timeZone = "America/New_York";
  assert.deepStrictEqual(T.organizerDatumzeitTeile(zonenProbe),
    { jahr: 2026, monat: 8, tag: 4, stunde: 22, minute: 7, sekunde: 0 },
  "absolute Zeit wird nicht in die Organizer-Zeitzone umgerechnet");
  assert.strictEqual(T.isoHeute(zonenProbe), "2026-08-04",
    "Heute folgt nicht dem Kalendertag der Organizer-Zeitzone");
  assert.deepStrictEqual(T.vorgabeZeiten(zonenProbe),
    { zeit: "22:15", endZeit: "22:45" },
  "Terminvorschlag folgt nicht der Uhrzeit der Organizer-Zeitzone");
  assert.strictEqual(T.terminZeitpunkt({ datum: "2026-08-04", zeit: "22:07" })
    .toISOString(), "2026-08-05T02:07:00.000Z",
  "Organizer-Wandzeit wird nicht als absoluter Zeitpunkt verglichen");
  assert.strictEqual(T.datumText(zonenProbe,
    { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, true), "22:07",
  "absolute Zeitstempel werden nicht in der Organizer-Zeitzone angezeigt");
  const dstMatrix = [
    ["Europe/Berlin", "2026-03-29T01:30:00Z",
      { jahr: 2026, monat: 3, tag: 29, stunde: 3, minute: 30, sekunde: 0 }],
    ["Etc/UTC", "2026-03-29T01:30:00Z",
      { jahr: 2026, monat: 3, tag: 29, stunde: 1, minute: 30, sekunde: 0 }],
    ["America/New_York", "2026-03-29T01:30:00Z",
      { jahr: 2026, monat: 3, tag: 28, stunde: 21, minute: 30, sekunde: 0 }],
    ["Australia/Lord_Howe", "2026-03-29T01:30:00Z",
      { jahr: 2026, monat: 3, tag: 29, stunde: 12, minute: 30, sekunde: 0 }]
  ];
  for (const [zone, zeitpunkt, erwartet] of dstMatrix) {
    T.daten().einstellungen.regional.timeZone = zone;
    assert.deepStrictEqual(T.organizerDatumzeitTeile(new Date(zeitpunkt)),
      erwartet, `absolute DST-Umrechnung für ${zone} stimmt nicht`);
  }
  const wandzeitMatrix = [
    ["Europe/Berlin", "2026-07-01T08:00:00.000Z"],
    ["Etc/UTC", "2026-07-01T10:00:00.000Z"],
    ["America/New_York", "2026-07-01T14:00:00.000Z"],
    ["Australia/Lord_Howe", "2026-06-30T23:30:00.000Z"]
  ];
  for (const [zone, erwartet] of wandzeitMatrix) {
    T.daten().einstellungen.regional.timeZone = zone;
    assert.strictEqual(T.terminZeitpunkt({ datum: "2026-07-01", zeit: "10:00" })
      .toISOString(), erwartet, `Organizer-Wandzeit für ${zone} stimmt nicht`);
  }
  const sprungMatrix = [
    ["Europe/Berlin", "2026-03-29T00:30:00Z", 1, 30],
    ["Europe/Berlin", "2026-03-29T01:30:00Z", 3, 30],
    ["America/New_York", "2026-03-08T06:30:00Z", 1, 30],
    ["America/New_York", "2026-03-08T07:30:00Z", 3, 30],
    ["Australia/Lord_Howe", "2026-10-03T15:15:00Z", 1, 45],
    ["Australia/Lord_Howe", "2026-10-03T15:45:00Z", 2, 45]
  ];
  for (const [zone, zeitpunkt, stunde, minute] of sprungMatrix) {
    T.daten().einstellungen.regional.timeZone = zone;
    const teile = T.organizerDatumzeitTeile(new Date(zeitpunkt));
    assert.strictEqual(`${teile.stunde}:${teile.minute}`, `${stunde}:${minute}`,
      `DST-Sprunggrenze für ${zone} stimmt nicht`);
  }
  T.daten().einstellungen.regional.timeZone = "system";

  const enDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://organizer-en.test/",
    pretendToBeVisual: true
  });
  /* Produktionsreihenfolge: Erst lädt die deutsche Fundamentphase die
     Anwendung, danach liefert App.init die tatsächliche Sprachwahl. */
  ladeAnwendung(enDom.window, "de");
  for (let i = 0; i < 50 && !enDom.window.OrganizerTest.daten().notizen.length; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  const enD = enDom.window.document;
  const enT = enDom.window.OrganizerTest;
  const enDatenPfad = "/home/User/Organizer Data";
  enDom.window.App.init({ daten: null, neu: true, datenPfad: enDatenPfad,
    migriert: true, regional: { language: "en", formatLocale: "en-US" } });
  assert.strictEqual(enT.daten().notizen[0].titel, "Welcome ✱",
    "englischer Titel der Erststartnotiz fehlt");
  assert.ok(enT.daten().notizen[0].text.includes("We are glad you are here!") &&
    enT.daten().notizen[0].text.includes("Your data is stored at:\n" + enDatenPfad) &&
    !enT.daten().notizen[0].text.includes("Schön, dass Sie da sind!"),
  "englischer Inhalt oder unveränderter Datenpfad der Erststartnotiz fehlt");
  assert.strictEqual(enD.querySelector("#zettel").textContent,
    "Your data from “Organizer Klassik” has been imported.",
  "englische Rückmeldung zur Klassik-Übernahme fehlt");
  enDom.window.App.ablage({ text: "" });
  assert.strictEqual(enD.querySelector("#zettel").textContent,
    "The clipboard is empty.", "englischer Zwischenablagehinweis fehlt");
  enDom.window.App.wortGemerkt({ ok: true, wort: "Duisburg" });
  assert.strictEqual(enD.querySelector("#zettel").textContent,
    "“Duisburg” is now in the dictionary.",
  "englische Wörterbuchmeldung verändert das aufgenommene Wort");
  enT.daten().einstellungen.regional.formatLocale = "en-US";
  enT.wechsel("aufgaben");
  const enButton = (text, root = enD) => Array.from(root.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === text);
  assert.strictEqual(enD.querySelector("#kopf-links h2").textContent, "Tasks",
    "englische Aufgabenüberschrift fehlt");
  assert.strictEqual(enD.querySelector("#kopf-rechts h2").textContent, "New task",
    "englischer Aufgabenkopf fehlt");
  assert.ok(enButton("New task") && enButton("People"),
    "englische Aufgabenknöpfe fehlen");
  assert.strictEqual(enD.querySelector("#aufgabe-titel").placeholder,
    "What needs to be done?", "englischer Aufgabenplatzhalter fehlt");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll("#inhalt-rechts .feldname"))
    .filter((label) => label.parentElement.style.display !== "none")
    .map((label) => label.textContent),
  ["Title", "Priority", "Due on", "Note", "Custom notification"],
  "englische Aufgabenbeschriftungen sind unvollständig");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(
    "#inhalt-rechts select option"), (option) => option.textContent),
  ["1 - high", "2 - medium", "3 - low"],
  "englische Prioritätsstufen fehlen");
  assert.deepStrictEqual(Array.from(enD.querySelector(
    "#aufgabe-titel-vorschlaege").options, (option) => option.value),
  ["Send documents", "Errands", "Call", "Schedule an appointment",
    "Pay invoice", "Shopping", "Follow up", "Pick up"],
  "englische Aufgabenvorschläge fehlen");
  assert.deepStrictEqual(Array.from(enD.querySelector(
    "#aufgabe-erinnerung-vorschlaege").options, (option) => option.value),
  ["1 day before", "2 days before", "3 days before", "4 days before",
    "5 days before", "6 days before", "7 days before"],
  "englische Erinnerungsvorschläge fehlen");
  enT.daten().aufgaben.push({ id: "english-user-task", titel: "Mülltonne rausstellen",
    faellig: "2026-08-03", prio: 1, erledigt: false, notiz: "", personen: [],
    erinnern: false });
  enT.daten().einstellungen.allgemein.wetter = true;
  enT.wechsel("kalender");
  enT.wechsel("aufgaben");
  assert.ok(enD.querySelector("#inhalt-links").textContent.includes("Mülltonne rausstellen"),
    "Benutzerdaten wurden in der englischen Oberfläche verändert");
  assert.strictEqual(enD.querySelector(".check").title, "Mark as completed",
    "englischer Erledigt-Tooltip fehlt");
  assert.strictEqual(enD.querySelector(".loesch-x").title, "Delete task",
    "englischer Löschen-Tooltip fehlt");
  enT.oeffnePersonenblatt();
  assert.strictEqual(enD.querySelector("#personen-schleier .personen-blatt")
    .getAttribute("aria-label"),
    "Manage people", "englisches Personenblatt fehlt");
  assert.strictEqual(enD.querySelector("#person-neu").placeholder, "Person's name",
    "englischer Personenplatzhalter fehlt");
  assert.ok(enButton("Add person", enD.querySelector("#personen-schleier")),
    "englischer Personenknopf fehlt");
  enD.querySelector("#personen-schleier").remove();
  enT.oeffneDruckvorschau(null, "aufgaben");
  assert.strictEqual(enD.querySelector(".druck-blatt h2").textContent, "Print · Tasks",
    "englischer Aufgabendruckkopf fehlt");
  assert.strictEqual(enButton("ODS", enD.querySelector("#druck-schleier")), undefined,
    "ODS darf außerhalb der Kontakte nicht angeboten werden");
  assert.ok(enD.querySelector(".druck-vorschau").textContent.includes("due 08/03/2026") &&
    enD.querySelector(".druck-vorschau").textContent.includes("high"),
  "englische Aufgabendruckangaben fehlen");
  enD.querySelector("#druck-schleier").remove();
  enT.wechsel("kalender");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(".registerknopf"),
    (b) => b.textContent),
  ["Calendar", "Tasks", "Contacts", "Notes", "Anniversaries", "Planner", "Health"],
  "englische Registerbeschriftungen fehlen");
  assert.ok(/\.registerknopf\s*\{[^}]*width:\s*152px;/s.test(css),
  "englische Jahrestagsbeschriftung bekommt keine ausreichend breite Registerzunge");
  const enJahrestagsRegister = Array.from(enD.querySelectorAll(".registerknopf"))
    .find((b) => b.textContent === "Anniversaries");
  assert.ok(enJahrestagsRegister.querySelector(".registertext") &&
    enJahrestagsRegister.querySelector(".registertext").style.fontSize === "11px" &&
    /#register-rechts \.registerknopf\s*\{[^}]*padding-left:\s*25px;[^}]*padding-right:\s*21px;/s
      .test(css),
  "lange englische Registerbeschriftung ist nicht mittig oder schmal genug");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll("#ansicht-umschalter .u-wort"),
    (e) => e.textContent), ["Month", "Week", "Day"],
  "englische Kalendernavigation fehlt");
  assert.ok(Array.from(enD.querySelectorAll("button")).some(
    (b) => b.textContent.trim() === "Today"), "englischer Heute-Knopf fehlt");
  assert.strictEqual(enT.fmtPunkt("2026-08-03"), "08/03/2026",
    "en-US-Datumsreihenfolge wird nicht verwendet");
  assert.strictEqual(enT.fmtLang("2026-08-03"), "Monday, August 3, 2026",
    "englisches langes Datum wird nicht regional formatiert");
  enT.daten().einstellungen.regional.hourCycle = "h12";
  assert.match(enT.zeitText("2026-08-03", "18:05"), /^0?6:05\sPM$/,
    "zwölfstündige Uhrzeit wird nicht regional formatiert");
  assert.match(enT.zeitspanneText({ datum: "2026-08-03", zeit: "18:05",
    endZeit: "19:30" }), /^0?6:05\sPM–0?7:30\sPM$/,
  "zwölfstündige Terminspanne ist unvollständig");
  enT.daten().einstellungen.regional.hourCycle = "h23";
  assert.strictEqual(enT.zeitText("2026-08-03", "18:05"), "18:05",
    "24-stündige Uhrzeit wird nicht bewahrt");
  enT.daten().einstellungen.regional.hourCycle = "system";
  assert.strictEqual(enT.zeitText("2026-08-03", "18:05"),
    new Intl.DateTimeFormat("en-US", { hour: "2-digit", minute: "2-digit" })
      .format(new Date(2026, 7, 3, 18, 5)),
  "Systemvorgabe für Uhrzeiten wird nicht von Intl übernommen");
  enT.daten().einstellungen.regional.hourCycle = "h23";
  enT.daten().einstellungen.regional.firstDayOfWeek = "sunday";
  assert.strictEqual(enT.ersterWochentag(), 0,
    "ausdrücklicher Sonntagsbeginn wird nicht angewandt");
  assert.deepStrictEqual(enT.wochentageKurz(),
    ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    "englische Wochentage beginnen nicht am Sonntag");
  assert.strictEqual(enT.wochenbeginnVon("2026-08-05").getDay(), 0,
    "Wochenansicht beginnt trotz Regionalregel nicht am Sonntag");
  enT.daten().einstellungen.regional.firstDayOfWeek = "locale";
  assert.strictEqual(enT.ersterWochentag(), 0,
    "en-US bestimmt bei automatischer Regionalregel keinen Sonntagsbeginn");
  enT.daten().einstellungen.regional.firstDayOfWeek = "monday";
  enT.daten().einstellungen.regional.formatLocale = "de-DE";
  assert.strictEqual(enT.fmtLang("2026-08-03"), "Monday, 3 August 2026",
    "englische Datumsnamen gehen bei deutschen Regionalregeln verloren");
  enT.daten().einstellungen.regional.formatLocale = "en-US";
  enD.querySelector('#ansicht-umschalter [data-ansicht="month"]').click();
  assert.strictEqual(enD.querySelector(".wetter-kasten").getAttribute("aria-label"),
    "Weather for the next three days", "englische Wetterbeschriftung fehlt");
  assert.ok(enD.querySelector(".wetter-status").textContent.includes(
    "Weather is available in the installed application."),
  "englischer Wetterstatus fehlt");
  enT.oeffneTerminBlatt(null, "2026-08-03");
  const enTerminBlatt = enD.querySelector("#termin-schleier");
  assert.strictEqual(enTerminBlatt.querySelector("h2").textContent, "New appointment",
    "englischer Terminkopf fehlt");
  assert.strictEqual(enTerminBlatt.querySelector("#tb-titel").placeholder,
    "What is it about?", "englischer Terminplatzhalter fehlt");
  assert.ok(enTerminBlatt.textContent.includes("Through") &&
    enTerminBlatt.textContent.includes("Custom notification") &&
    enTerminBlatt.textContent.includes("recurring appointment") &&
    enTerminBlatt.textContent.includes("Related tasks") &&
    enTerminBlatt.textContent.includes("More fields") &&
    !enTerminBlatt.textContent.includes("More fields (Lotus)"),
  "englische Terminbeschriftungen sind unvollständig");
  assert.ok(/button, input, select, textarea\s*\{\s*font-family:\s*inherit;/s.test(css) &&
    /\.termin-blatt input\[type="time"\]::\-webkit-datetime-edit,[\s\S]*?font-family:\s*inherit;/s.test(css),
  "native Terminsteuerelemente verwenden nicht die vorgegebene Linux-Schrift");
  assert.deepStrictEqual(Array.from(enTerminBlatt.querySelectorAll(
    "#tb-wiederholung option"), (option) => option.textContent),
  ["every day", "Interval in days: 2", "Interval in days: 14",
    "every week on the same weekday", "Interval in days: 21", "every month on the same day",
    "every month on the first Monday", "every year on the same date", "Custom"],
  "englische Wiederholungsregeln fehlen");
  assert.ok(enButton("Add appointment", enTerminBlatt) && enButton("Cancel", enTerminBlatt),
    "englische Terminaktionen fehlen");
  enButton("Cancel", enTerminBlatt).click();
  enT.zustand().kalender.ansicht = "day";
  enT.wechsel("aufgaben");
  enT.wechsel("kalender");
  assert.ok(enButton("＋ Add appointment"), "englischer Tagesknopf fehlt");
  assert.strictEqual(enD.querySelector(".stunden-marke").textContent, "06:00",
    "englische Stundenmarke fehlt");
  enT.zustand().kalender.ansicht = "month";
  enT.wechsel("aufgaben");
  enT.wechsel("kalender");
  enT.daten().kontakte.push({ id: "contact-en", uid: "", nachname: "Example",
    vorname: "Alice", firma: "User company", telefon: "", mobil: "",
    telefone: [{ wert: "+1 555 0100", typen: ["CELL"] }],
    email: "alice@example.test", emails: ["alice@example.test"],
    emailEintraege: [{ wert: "alice@example.test", typen: ["WORK"] }],
    strasse: "", plz: "", ort: "", anschriften: [
      { strasse: "User Street 1", plz: "12345", ort: "User Town",
        land: "Userland", typen: ["HOME"] }],
    kontaktpersonen: [{ name: "Bob User", telefon: "+1 555 0101", status: "Friend" }],
    sozialeMedien: [], notiz: "User note", foto: "", sync: false });
  enT.zustand().adressen.auswahlId = "contact-en";
  enT.zustand().adressen.modus = "ansehen";
  enT.wechsel("adressen");
  assert.strictEqual(enD.querySelector("#kopf-links h2").textContent, "Contacts",
    "englischer Adressbuchkopf fehlt");
  assert.strictEqual(enD.querySelector("#kopf-rechts h2").textContent, "Contact card",
    "englischer Karteikartenkopf fehlt");
  const enKontaktText = enD.querySelector(".kontakt-karte").textContent;
  assert.ok(enKontaktText.includes("Example, Alice") &&
    enKontaktText.includes("Home address") && enKontaktText.includes("Mobile") &&
    enKontaktText.includes("Work") && enKontaktText.includes("Emergency contacts") &&
    enKontaktText.includes("User note"),
  "englische Karteikarte oder unveränderte Benutzerdaten fehlen: " + enKontaktText);
  assert.ok(enButton("Letter") && enButton("Map") && enButton("Message") &&
    enButton("Edit") && enButton("Delete"), "englische Kontaktaktionen fehlen");
  enT.oeffneDruckvorschau(enT.daten().kontakte.find((k) => k.id === "contact-en"),
    "adressen");
  const enKontaktDruck = enD.querySelector(".druck-vorschau").textContent;
  assert.ok(enKontaktDruck.includes("Emergency contact: Bob User (Friend)") &&
    enKontaktDruck.includes("Emergency contact phone: +1 555 0101"),
  "englische Notfallkontaktbeschriftungen fehlen im Druck");
  assert.ok(enButton("ODS", enD.querySelector("#druck-schleier")),
    "englischer Kontaktdruck bietet ODS an");
  enD.querySelector("#druck-schleier").remove();

  const odsNachrichten = [];
  const odsDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://organizer-ods.test/",
    pretendToBeVisual: true
  });
  odsDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => odsNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(odsDom.window, "en");
  const odsW = odsDom.window;
  const odsD = odsW.document;
  const odsT = odsW.OrganizerTest;
  const odsDaten = odsT.leereDaten();
  const odsKontakt = { id: "ods-one", uid: "", nachname: "Müller & Sons",
    vorname: "Zoë", firma: "Tea <Trading>", telefon: "", mobil: "",
    telefone: [
      { wert: "0203 1", typen: ["VOICE"] },
      { wert: "0171 2", typen: ["CELL"] },
      { wert: "0203 3", typen: ["WORK"] },
      { wert: "0203 4", typen: ["HOME"] },
      { wert: "0203 5", typen: ["FAX"] },
      { wert: "0203 6", typen: ["PAGER"] },
      { wert: "0203 7", typen: [], label: "Studio hotline" }
    ], email: "must-not-export@example.test", emails: [], emailEintraege: [],
    strasse: "", plz: "", ort: "", anschriften: [
      { strasse: "Home & Lane 1", plz: "47051", ort: "Duisburg",
        land: "Germany", typen: ["HOME"] },
      { strasse: "Office <West> 2", plz: "47441", ort: "Moers",
        land: "Germany", typen: ["WORK"], label: "Warehouse" }
    ], kontaktpersonen: [
      { name: "Ada One", status: "Sister", telefon: "111" },
      { name: "Bob Two", beziehung: "Friend", telefon: "222" }
    ], sozialeMedien: [], notiz: "Line one\nLine <two> & more", foto: "", sync: false };
  odsDaten.kontakte.push(odsKontakt, Object.assign({}, odsKontakt,
    { id: "ods-two", nachname: "Not selected", vorname: "Other" }));
  odsDaten.jahrestage.push({ id: "ods-birthday", kontaktId: "", uid: "",
    name: "Zoë Müller & Sons", datum: "1980-04-05", typ: "birthday" });
  odsW.App.init({ daten: odsDaten, neu: false, datenPfad: "" });
  await tick();
  odsT.oeffneDruckvorschau(null, "adressen");
  assert.ok(odsD.querySelector(".ods-knopf .sinnbild") &&
    odsD.querySelector(".druck-zeile-text"),
  "ODS-Tabellensymbol oder stabile Beschriftung der Druckauswahl fehlt");
  assert.strictEqual(odsD.querySelector(".ods-feldauswahl").tagName, "DETAILS");
  assert.ok(odsD.querySelector(".ods-feldauswahl > summary") &&
    odsD.querySelector(".ods-feldliste") && !odsD.querySelector(".ods-feldauswahl").open,
  "die ODS-Spaltenauswahl ist keine zunächst geschlossene Aufklappliste");
  assert.strictEqual(odsD.querySelectorAll(".ods-feldauswahl input").length, 14,
    "die ODS-Inhaltsauswahl fragt nicht alle verfügbaren Spalten ab");
  assert.ok(Array.from(odsD.querySelectorAll("button"))
    .some((button) => button.textContent.trim() === "ODS"),
  "englischer ODS-Knopf fehlt bei Kontakten");
  Array.from(odsD.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "ODS").click();
  assert.strictEqual(odsNachrichten.filter((nachricht) =>
    nachricht.cmd === "adressen_ods").length, 0,
    "ohne ausgewählten Kontakt darf keine ODS-Nachricht gesendet werden");
  assert.strictEqual(odsD.querySelector("#zettel").textContent, "Select something first.",
    "englischer Auswahldialoghinweis fehlt");
  odsD.querySelector("#druck-schleier").remove();
  odsT.oeffneDruckvorschau(odsKontakt, "adressen");
  Array.from(odsD.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "ODS").click();
  const odsExporte = odsNachrichten.filter((nachricht) =>
    nachricht.cmd === "adressen_ods");
  assert.strictEqual(odsExporte.length, 1, "ODS-Nachricht fehlt");
  const odsNutzlast = odsExporte[0];
  assert.strictEqual(odsNutzlast.cmd, "adressen_ods");
  assert.deepStrictEqual(Array.from(odsNutzlast.spalten),
    ["Last name", "First name", "Company", "Birthday", "Street / house number",
      "Postal code / city", "Country", "Other addresses", "Landline", "Mobile",
      "Other phone numbers", "Email addresses", "Emergency contacts", "Note"],
  "ODS-Spalten folgen nicht der Nachnamensortierung");
  assert.strictEqual(odsNutzlast.zeilen.length, 1,
    "ODS enthält nicht genau die ausgewählte Karte");
  const odsText = Array.from(odsNutzlast.zeilen[0]).join("\n");
  for (const erwartet of ["Müller & Sons", "Zoë", "Tea <Trading>",
    "1980", "Home & Lane 1", "47051 Duisburg", "Warehouse", "Office <West> 2",
    "0203 1", "0171 2", "0203 3", "0203 4", "0203 5", "0203 6", "0203 7",
    "Ada One · Sister", "111", "Bob Two · Friend",
    "222", "Line one\nLine <two> & more"]) {
    assert.ok(odsText.includes(erwartet), "ODS-Inhalt fehlt: " + erwartet);
  }
  assert.ok(odsText.includes("must-not-export@example.test"),
    "ausgewählte E-Mail-Adressen fehlen in ODS");
  assert.ok(!odsText.includes("Email: must-not-export@example.test") &&
    !odsText.includes("Phone: 0203 1") && !odsText.includes("Mobile: 0171 2") &&
    !odsText.includes("Work phone:") && !odsText.includes("Home phone:") &&
    !odsText.includes("Studio hotline:") && !odsText.includes("Home address"),
  "dedizierte ODS-Spalten wiederholen weiterhin ihre Standardbezeichnung");
  odsKontakt.geburtstag = "1980-04-05";
  const odsMitGeburtstag = odsT.adressenOdsNutzlast(
    [odsKontakt], ["nachname", "geburtstag", "emails"]);
  assert.deepStrictEqual(Array.from(odsMitGeburtstag.spalten),
    ["Last name", "Birthday", "Email addresses"],
    "Geburtstag oder gezielte ODS-Spaltenauswahl fehlt");
  assert.ok(/1980/.test(odsMitGeburtstag.zeilen[0][1]) &&
    /04/.test(odsMitGeburtstag.zeilen[0][1]) && /05/.test(odsMitGeburtstag.zeilen[0][1]),
    "Geburtstag folgt im ODS-Export nicht dem Formatgebiet");
  assert.strictEqual(odsT.adressenOdsNutzlast(
    [Object.assign({}, odsKontakt, { nachname: "No birthday", geburtstag: "", email: "", emails: [],
      emailEintraege: [] })], ["geburtstag", "emails"]).spalten.length, 0,
  "vollständig leere ausgewählte ODS-Spalten bleiben erhalten");
  odsT.daten().einstellungen.adressen.sortierung = "first-name";
  assert.deepStrictEqual(Array.from(odsT.adressenOdsNutzlast([odsKontakt]).spalten.slice(0, 2)),
    ["First name", "Last name"], "ODS-Spalten folgen nicht der Vornamensortierung");
  odsW.MagnolieI18n.setLocale("de");
  odsT.oeffneDruckvorschau(odsKontakt, "adressen");
  assert.ok(Array.from(odsD.querySelectorAll("button"))
    .some((button) => button.textContent.trim() === "ODS"),
  "deutscher ODS-Knopf fehlt bei Kontakten");
  odsD.querySelector("#druck-schleier").remove();
  odsT.oeffneDruckvorschau(null, "notizen");
  assert.ok(!Array.from(odsD.querySelectorAll("button"))
    .some((button) => button.textContent.trim() === "ODS"),
  "ODS wird im deutschen Notizdruck fälschlich angeboten");
  odsD.querySelector("#druck-schleier").remove();
  odsW.MagnolieI18n.setLocale("en");
  odsT.zustand().planer.jahr = 2026;
  odsT.zustand().kalender.monat = 0;
  odsT.daten().feiertage = [
    { id: "planner-holiday", von: "2026-01-01", bis: "2026-01-01",
      name: "New Year", art: "public-holiday", region: "", regionName: "" },
    { id: "planner-vacation", von: "2026-07-06", bis: "2026-07-17",
      name: "Summer break", art: "school-holiday", region: "", regionName: "" }];
  odsT.daten().einstellungen.kalender.urlaubsplanerAn = true;
  odsT.daten().urlaube = [{ id: "planner-personal-vacation", von: "2026-01-12",
    bis: "2026-01-16", symbol: "palm", darstellung: "symbol-text" }];
  odsT.daten().einstellungen.kalender.zykluskalenderAn = true;
  odsT.daten().zyklusmarker = [{ id: "planner-cycle", name: "Cycle rule", symbol: "◇",
    farbe: "#ad3f50", art: "custom" }];
  odsT.daten().tagmarken = [{ datum: "2026-01-05", schichtId: "",
    zyklusIds: ["planner-cycle"] }];
  odsT.daten().einstellungen.kalender.muellkalenderAn = true;
  odsT.daten().muelltermine = [{ id: "planner-waste", von: "2026-01-05",
    name: "Residual waste", intervallTage: 14, farbe: "#4c4b47", art: "residual" }];
  odsT.oeffneDruckvorschau(null, "planer");
  assert.strictEqual(odsD.querySelectorAll(".planer-druck-kalender th").length, 12,
    "Planervorschau besitzt nicht zwölf Monatsspalten");
  assert.strictEqual(odsD.querySelectorAll(".planer-druck-kalender tbody tr").length, 31,
    "Planervorschau besitzt nicht 31 Tageszeilen");
  assert.ok(odsD.querySelector(".pk-feiertag") && odsD.querySelector(".pk-ferien") &&
    odsD.querySelectorAll(".planer-druck-option input").length >= 4,
  "Feiertage, Ferien oder ihre Planerdruckoptionen fehlen");
  assert.ok(!odsD.querySelector(".druck-zeile") && !Array.from(
    odsD.querySelectorAll("button")).some((button) =>
    button.textContent.trim() === "Delete selection"),
  "Planerdruck bietet weiterhin Terminwahl oder Löschen an");
  odsD.querySelector("#planer-druck-art").value = "month";
  odsD.querySelector("#planer-druck-art").dispatchEvent(
    new odsW.Event("change", { bubbles: true }));
  assert.ok(odsD.querySelector(".planer-monatskalender") &&
    odsD.querySelectorAll(".planer-monatskalender thead th").length === 8 &&
    odsD.querySelectorAll(".planer-monatskalender tbody tr").length === 6 &&
    odsD.querySelector("#planer-druck-monat").closest(".formzeile").style.display !== "none",
  "Umschalten auf die Monatsvorschau oder Monatswahl fehlt");
  const zyklusDruck = odsD.querySelector('[data-druck-option="zyklus"]');
  const muellDruck = odsD.querySelector('[data-druck-option="muell"]');
  assert.ok(zyklusDruck && muellDruck && odsD.querySelector(".pm-zyklus") &&
    odsD.querySelector(".pm-muell") && odsD.querySelector(".pm-muell").textContent === "Residual waste",
  "Regel-/Zyklusmarkierung oder Müllentleerung fehlt in der Monatsvorschau");
  zyklusDruck.click();
  muellDruck.click();
  assert.ok(!odsD.querySelector(".pm-zyklus") && !odsD.querySelector(".pm-muell"),
    "Regel-/Zyklusmarkierung oder Müllentleerung lässt sich nicht abwählen");
  zyklusDruck.click();
  muellDruck.click();
  assert.ok(odsD.querySelector(".pm-zyklus") && odsD.querySelector(".pm-muell"),
    "Regel-/Zyklusmarkierung oder Müllentleerung lässt sich nicht wieder anwählen");
  odsD.querySelector("#planer-druck-art").value = "year";
  odsD.querySelector("#planer-druck-art").dispatchEvent(
    new odsW.Event("change", { bubbles: true }));
  Array.from(odsD.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "ODS").click();
  const planerOds = odsNachrichten.find((nachricht) => nachricht.cmd === "planer_ods");
  assert.ok(planerOds && planerOds.layout === "year" && planerOds.jahr === 2026 &&
    planerOds.spalten.length === 12 &&
    planerOds.zeilen.length === 31 && planerOds.stile.length === 31 &&
    planerOds.inhalte.length === 31 &&
    planerOds.stile.some((zeile) => zeile.includes("holiday")) &&
    planerOds.stile.some((zeile) => zeile.includes("vacation")) &&
    planerOds.stile.some((zeile) => zeile.includes("personal-vacation")),
  "Planer-ODS enthält nicht den vollständigen gestalteten Jahreskalender");
  const monatsModell = odsT.planerMonatsModell(2026, 0, {
    termine: true, jahrestage: true, feiertage: true, ferien: true, schichten: true,
    zyklus: true, muell: true });
  const monatsOds = odsT.planerOdsNutzlast(monatsModell);
  const monatsInhalte = monatsOds.inhalte.flat();
  const monatsModellOhneMarken = odsT.planerMonatsModell(2026, 0, {
    zyklus: false, muell: false });
  assert.ok(monatsModell.wochen.length === 6 &&
    monatsModell.wochen.every((woche) => woche.tage.length === 7) &&
    monatsOds.layout === "month" && monatsOds.spalten.length === 8 &&
    monatsOds.zeilen.length === 6 && monatsOds.stile.length === 6 &&
    monatsOds.inhalte.length === 6 && monatsOds.inhalte[0].length === 8 &&
    monatsInhalte.some((zelle) => (zelle.marker || []).some((marker) => marker.text === "◇")) &&
    monatsInhalte.some((zelle) => zelle.eintraege.some((eintrag) =>
      eintrag.art === "muell" && eintrag.text === "Residual waste" &&
      eintrag.farbe === "#4c4b47")) &&
    monatsModellOhneMarken.wochen.every((woche) => woche.tage.every((tag) =>
      !tag.zyklus.length && !tag.eintraege.some((eintrag) => eintrag.art === "muell"))),
  "Monatsvorschau oder Monats-ODS besitzt nicht sechs Kalenderwochen");
  odsT.daten().einstellungen.kalender.vergangeneTermine = true;
  odsT.daten().einstellungen.kalender.vergangeneJahrestage = true;
  odsT.daten().termine.push({ id: "planner-historical-appointment", datum: "2020-01-08",
    endDatum: "", zeit: "", endZeit: "", titel: "Historical appointment" });
  odsT.daten().jahrestage.push({ id: "planner-historical-anniversary", datum: "2010-01-09",
    name: "Historical anniversary", typ: "" });
  odsT.planeSpeichern();
  const historischerMonat = odsT.planerMonatsModell(2020, 0);
  assert.ok(historischerMonat.wochen.some((woche) => woche.tage.some((tag) =>
    tag.eintraege.some((eintrag) => eintrag.text.includes("Historical appointment")))) &&
    historischerMonat.wochen.some((woche) => woche.tage.some((tag) =>
      tag.eintraege.some((eintrag) => eintrag.text.includes("Historical anniversary")))),
  "ausdrücklich gewählte historische Termine oder Jahrestage fehlen im Planerdruck");
  odsDom.window.close();
  enButton("Edit").click();
  const enKontaktForm = enD.querySelector(".kontakt-formular");
  assert.strictEqual(enKontaktForm.querySelector("legend").textContent, "Contact card");
  assert.deepStrictEqual(Array.from(enKontaktForm.querySelectorAll(
    "#kontakt-telefon-arten option"), (option) => option.value),
  ["Landline", "Mobile", "Work", "Home", "Private", "Fax", "Pager"],
  "englische Rufnummernarten fehlen");
  assert.deepStrictEqual(Array.from(enKontaktForm.querySelectorAll(
    "#kontakt-email-arten option"), (option) => option.value),
  ["Home", "Private", "Work", "Other"], "englische E-Mail-Arten fehlen");
  assert.deepStrictEqual(Array.from(enKontaktForm.querySelectorAll(
    "#kontakt-anschrift-arten option"), (option) => option.value),
  ["Postal address", "Head office", "Secondary office", "Work", "Private"],
  "englische Anschriftsarten fehlen");
  assert.ok(enKontaktForm.textContent.includes("Phone numbers") &&
    enKontaktForm.textContent.includes("Email addresses") &&
    enKontaktForm.textContent.includes("Addresses") &&
    enKontaktForm.textContent.includes("Social media") &&
    enKontaktForm.textContent.includes("Appointments for this person") &&
    enButton("Save changes", enKontaktForm) && enButton("Cancel", enKontaktForm),
  "englisches Kontaktformular ist unvollständig");
  enButton("Cancel", enKontaktForm).click();
  enT.oeffneEinstellungen();
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(".einst-reiter-knopf"),
    (button) => button.textContent),
  ["General", "Import", "Export", "Synchronization", "Country & holidays",
    "Typography", "Notifications", "Contacts", "Security", "Calendar",
    "Magnolia tree", "About"], "englische Einstellungsreiter fehlen");
  const enAllgemein = enD.querySelector("#einstellungen-inhalt");
  assert.ok(enAllgemein.textContent.includes("Basic operation and appearance") &&
    enAllgemein.textContent.includes("Show the “Selection options” button") &&
    enAllgemein.textContent.includes("currently has keyboard focus") &&
    enAllgemein.textContent.includes("Tab, arrow keys, Enter and Space") &&
    enAllgemein.textContent.includes("Enable tray applet") &&
    enAllgemein.textContent.includes("notification count on the tray icon") &&
    !enAllgemein.textContent.includes("Backup folder"),
  "englische Seite General ist unvollständig");
  assert.ok(!enD.querySelector("#allgemein-gruppe-tray").open,
    "Tray-Einstellungen sind beim Öffnen nicht zugeklappt");
  assert.deepStrictEqual(Array.from(enD.querySelector("#allgemein-rad").options,
    (option) => option.value), ["up-earlier", "up-later"],
  "interne Mausradwerte wurden übersetzt");
  assert.deepStrictEqual(Array.from(enD.querySelector("#allgemein-tray-oeffnen").options,
    (option) => option.value), ["previous", "centered", "maximized"],
  "interne Tray-Fensterwerte wurden übersetzt");
  assert.ok(!enD.querySelector("#einst-tab-regional") &&
    !enButton("Language & region", enD.querySelector(".einst-reiter")),
  "regionale Einstellungen sind weiterhin als Reiter sichtbar");
  enButton("Security", enD.querySelector(".einst-reiter")).click();
  const enSicherungsbereiche = enD.querySelector("#einstellungen-inhalt");
  assert.ok(enSicherungsbereiche.textContent.includes("Backup folder") &&
    enSicherungsbereiche.textContent.includes("Recovery snapshots") &&
    enButton("Restore backup …", enSicherungsbereiche),
  "Sicherungen sind nicht als eigene Bereiche unter Sicherheit eingeordnet");
  enDom.window.App.journalStand({ ok: true, status: "scheduled", interval: "weekly",
    maximum: 20, last: "2026-08-23T04:00:00Z", next: "2026-08-30T04:00:00Z",
    snapshots: [] });
  assert.ok(!enD.querySelector("#einstellungen-inhalt .einst-warnung"),
    "planmäßiger Journalstatus wird als Warnung dargestellt");
  const enJournalAnzahl = enD.querySelector("#journal-anzahl");
  assert.ok(enJournalAnzahl && enJournalAnzahl.min === "1" &&
    enJournalAnzahl.max === "100" && enSicherungsbereiche.textContent.includes(
      "Maximum recovery snapshots"),
  "Anzahl der Wiederherstellungspunkte ist nicht wählbar");
  enJournalAnzahl.value = "7";
  enJournalAnzahl.dispatchEvent(new enDom.window.Event("change", { bubbles: true }));
  assert.strictEqual(enT.daten().einstellungen.allgemein.wiederherstellungsanzahl, 7,
    "gewählte Anzahl der Wiederherstellungspunkte erreicht die Daten nicht");
  enDom.window.App.sicherungAusgewaehlt({ ok: true,
    pfad: "/tmp/Meine Sicherung.json", verschluesselt: true });
  assert.strictEqual(enD.querySelector("#sicherung-titel").textContent,
    "Restore backup", "englischer Sicherungsdialogtitel fehlt");
  assert.ok(enD.querySelector("#sicherung-text").textContent.includes(
    "/tmp/Meine Sicherung.json") && enD.querySelector("#sicherung-text")
      .textContent.includes("completely replaced"),
  "Sicherungspfad oder englischer Dialogtext wurde verändert");
  enD.querySelector("#sicherung-abbrechen").click();
  enDom.window.App.gespeichert(true);
  assert.ok(enD.querySelector("#status-speicher").textContent.startsWith("Saved ✓"),
    "englischer Speicherstatus fehlt");
  enButton("Import", enD.querySelector(".einst-reiter")).click();
  assert.ok(enButton("From this computer (Evolution/Thunderbird)",
    enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Calendar file (.ics/.vcs/.lcs) …", enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Lotus Organizer CSV …", enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Contacts (.vcf) …", enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Claws Mail (.xml/.ldif) …", enD.querySelector("#einstellungen-inhalt")),
  "englische Importaktionen oder Dateiendungen fehlen");
  assert.ok(enD.querySelector("#einstellungen-inhalt").textContent.includes(
    "does not change them"), "englischer Importhinweis fehlt");
  enButton("Export", enD.querySelector(".einst-reiter")).click();
  assert.ok(enButton("Appointments (.ics)", enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Appointments as Lotus CSV", enD.querySelector("#einstellungen-inhalt")) &&
    enButton("Contacts (.vcf)", enD.querySelector("#einstellungen-inhalt")) &&
    enD.querySelector("#einstellungen-inhalt").textContent.includes("VORLAEUFIGZUSAGEN"),
  "englische Exportaktionen oder unveränderte Lotus-Spalten fehlen");
  enDom.window.App.importErgebnis({ art: "ics", abgebrochen: false,
    aufgaben: [{ uid: "english-import-task", titel: "Mülltonne rausstellen",
      faellig: "2026-08-04", prio: 2, erledigt: false }],
    uebersprungen: 1, wiederholend: 2, bericht: "Provider-Bericht." });
  assert.ok(enD.querySelector("#zettel").textContent.includes("Imported: 1 task") &&
    enD.querySelector("#zettel").textContent.includes("1 unreadable row omitted") &&
    enD.querySelector("#zettel").textContent.includes(
      "2 recurring appointments imported only once") &&
    enD.querySelector("#zettel").textContent.includes("Provider-Bericht") &&
    enT.daten().aufgaben.some((a) => a.titel === "Mülltonne rausstellen"),
  "englische Importmeldung oder unveränderte Importdaten fehlen");
  enDom.window.App.importErgebnis({ art: "claws", abgebrochen: false,
    fehler: "File could not be read: DOCTYPE is not allowed in a Claws Mail address book." });
  assert.strictEqual(enD.querySelector("#zettel").textContent,
    "Import failed: File could not be read: DOCTYPE is not allowed in a Claws Mail address book.",
    "englische Claws-Fehlerkette wird in der Oberfläche verändert");
  enDom.window.App.exportErgebnis({ ok: true, abgebrochen: false,
    pfad: "/tmp/Meine Termine.ics", anzahl: 1, uebersprungen: 1 });
  assert.strictEqual(enD.querySelector("#zettel").textContent,
    "Saved to: /tmp/Meine Termine.ics (1 entry) 1 unreadable row omitted.",
    "englischer Exportpfad, Singular oder Auslassungshinweis ist falsch");
  enT.schliesseEinstellungen();

  const enSyncNachrichten = [];
  const enSyncDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://organizer-sync-en.test/",
    pretendToBeVisual: true
  });
  enSyncDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => enSyncNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(enSyncDom.window, "en");
  const enSW = enSyncDom.window;
  const enSD = enSW.document;
  const enST = enSW.OrganizerTest;
  const enSyncDaten = enST.leereDaten();
  enSyncDaten.einstellungen.regional.formatLocale = "en-US";
  enSyncDaten.letzterSync = new Date(2026, 7, 3, 9, 5).getTime();
  enSW.App.init({ daten: enSyncDaten, neu: false, datenPfad: "",
    trayVerfuegbar: false, handbuchInstalliert: true });
  await tick();
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "background_settings_get"),
    "Initialisierung fragt den Hintergrunddienststand nicht an");
  enSyncNachrichten.length = 0;
  enST.daten().einstellungen.allgemein.startseite = "jahr";
  enSD.querySelector("#knopf-sicherung").click();
  const sicherungsSave = enSyncNachrichten.find((nachricht) =>
    nachricht.cmd === "speichern");
  assert.ok(sicherungsSave && !enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "sicherung"),
  "die Sicherung wartet nicht auf den dauerhaften neuesten Datenstand");
  enSW.App.gespeichert({ id: sicherungsSave.id, ok: true });
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "sicherung"),
    "nach dem Save wird die vorgemerkte Sicherung nicht ausgeführt");
  enSyncNachrichten.length = 0;
  enST.daten().einstellungen.allgemein.startseite = "adressen";
  enSW.App.vorBeenden();
  const ersterSchreibvorgang = enSyncNachrichten.find((nachricht) =>
    nachricht.cmd === "speichern");
  assert.ok(ersterSchreibvorgang && Number.isInteger(ersterSchreibvorgang.id),
  "Beenden fordert keinen abschließenden Schreibvorgang an");
  enSW.App.gespeichert({ id: ersterSchreibvorgang.id, ok: false,
    fehler: "Disk full" });
  assert.ok(enSD.querySelector("#zettel").textContent.includes("Disk full"),
    "der genaue Speicherfehler erreicht die Oberfläche nicht");
  enSW.App.vorBeenden();
  const schreibvorgaenge = enSyncNachrichten.filter((nachricht) =>
    nachricht.cmd === "speichern");
  assert.strictEqual(schreibvorgaenge.length, 2,
  "ein fehlgeschlagener Schreibvorgang wird beim Beenden nicht wiederholt");
  const zweiterSchreibvorgang = schreibvorgaenge[1];
  enSW.App.gespeichert({ id: ersterSchreibvorgang.id, ok: true });
  assert.notStrictEqual(enSyncNachrichten.at(-1).cmd, "beenden_bereit",
    "eine verspätete Bestätigung gibt das Beenden frei");
  enSW.App.gespeichert({ id: zweiterSchreibvorgang.id, ok: true });
  assert.strictEqual(enSyncNachrichten.at(-1).cmd, "beenden_bereit",
    "nach bestätigtem Speichern wird das Beenden nicht freigegeben");
  enST.oeffneEinstellungen();
  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Synchronization").click();
  enSW.App.edsStatus({ verfuegbar: true, buchOk: true,
    kalender: [
      { uid: "google-privat", name: "Kalender von Müller" },
      { uid: "arbeit-uid", name: "Arbeit & Team" }
    ], adressbuecher: [{ uid: "buch-privat", name: "Privates Adressbuch" }] });
  enSW.App.baumBriefkastenStatus({ davAktiv: true, briefkastenAktiv: false,
    url: "https://cloud.example", benutzer: "user", kennwortVorhanden: true,
    zustand: "bereit", fehler: "" });
  assert.strictEqual(enSD.querySelector("#einstellungen-inhalt h3").textContent,
    "Calendars and contacts", "englische Synchronisationsseite fehlt");
  assert.ok(enSD.querySelector("#sync-status").textContent.includes("Last synchronized:") &&
    enSD.querySelector("#sync-status").textContent.includes("08/03/2026"),
  "englischer Abgleichzeitpunkt folgt nicht dem Formatgebiet");
  assert.ok(enSD.querySelector("#nextcloud-konto") &&
    enSD.querySelector("#nextcloud-kalender-kontakte") &&
    enSD.querySelector("#nextcloud-briefkasten") &&
    !enSD.querySelector("#einst-tab-nextcloud"),
  "Nextcloud ist nicht vollständig in die Synchronisationsseite integriert");
  const enSyncReihenfolge = Array.from(enSD.querySelectorAll(
    "#nextcloud-kalender-kontakte, #nextcloud-konto, #nextcloud-briefkasten"))
    .map((element) => element.id);
  assert.deepStrictEqual(enSyncReihenfolge,
    ["nextcloud-kalender-kontakte", "nextcloud-konto", "nextcloud-briefkasten"],
    "Nextcloud-Konto steht nicht direkt vor dem Magnolienbaum-Briefkasten");
  const enDav = enSD.querySelector("#nextcloud-dav-an");
  enDav.checked = false;
  enDav.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#einst-tab-allgemein").click();
  enSD.querySelector("#einst-tab-sync").click();
  assert.strictEqual(enSD.querySelector("#nextcloud-dav-an").checked, false,
    "deaktivierter Nextcloud-Entwurf geht beim Reiterwechsel verloren");
  enST.schliesseEinstellungen();
  enSW.App.baumBriefkastenStatus({ davAktiv: true, briefkastenAktiv: false,
    url: "https://cloud.echt.example", benutzer: "user", kennwortVorhanden: true,
    zustand: "bereit", fehler: "" });
  enST.oeffneEinstellungen();
  assert.strictEqual(enSD.querySelector("#nextcloud-dav-an").checked, true,
    "ein verworfener Nextcloud-Entwurf maskiert nach erneutem Öffnen den echten Stand");
  assert.strictEqual(enSD.querySelector("#briefkasten-url").value,
    "https://cloud.echt.example",
    "die verworfene Nextcloud-Adresse bleibt nach erneutem Öffnen sichtbar");
  const enKalender = Array.from(enSD.querySelectorAll(".sync-kalender input"));
  assert.deepStrictEqual(enKalender.map((feld) => feld.value),
    ["google-privat", "arbeit-uid"], "Kalender-UIDs wurden übersetzt");
  assert.ok(enSD.querySelector("#sync-wahl").textContent.includes("Kalender von Müller") &&
    enSD.querySelector("#sync-wahl").textContent.includes("Arbeit & Team") &&
    enSD.querySelector("#sync-wahl").textContent.includes("Privates Adressbuch"),
  "Anbieternamen wurden übersetzt oder fehlen");
  enKalender[0].click();
  enKalender[1].click();
  const enAdressbuch = enSD.querySelector("#sync-wahl select");
  enAdressbuch.value = "buch-privat";
  enAdressbuch.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  Array.from(enSD.querySelectorAll("button"))
    .find((button) => button.textContent === "Synchronize now").click();
  let enSyncBefehl = enSyncNachrichten.find((nachricht) => nachricht.cmd === "sync");
  if (!enSyncBefehl) {
    const syncVorSave = enSyncNachrichten.filter((nachricht) =>
      nachricht.cmd === "speichern").at(-1);
    enSW.App.gespeichert({ id: syncVorSave.id, ok: true });
    enSyncBefehl = enSyncNachrichten.find((nachricht) => nachricht.cmd === "sync");
  }
  assert.deepStrictEqual(enSyncBefehl.wahl, {
    kalenderUid: "google-privat", kalenderUids: ["google-privat", "arbeit-uid"],
    adressbuchUid: "buch-privat"
  }, "englische Oberfläche verändert den EDS-Quellenvertrag");
  enSW.App.syncFertig({ termine: [], kontakte: [], jahrestage: [],
    geloescht: { termine: [], kontakte: [] }, letzterSync: Date.now(),
    letzteSyncs: { kalender: { "google-privat": 1, "arbeit-uid": 2 } },
    bericht: "Provider-Bericht unverändert." });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Provider-Bericht unverändert.", "Backendbericht wurde im Web verändert");
  enSyncNachrichten.length = 0;
  enSW.App.syncFertig({ termine: [], kontakte: [{ uid: "remote-1",
      nachname: "Remote", sync: true }], jahrestage: [],
    geloescht: { termine: [], kontakte: [] }, letzterSync: Date.now(),
    letzteSyncs: { kalender: {}, adressbuecher: {} },
    adressbuchBaselineKandidat: { sourceUid: "buch-privat", initialisiert: true,
      letzterSync: 1234, remoteAnzahl: 1, snapshotHash: "a".repeat(64) },
    bericht: "1 received." });
  const datenSave = enSyncNachrichten.find((nachricht) => nachricht.cmd === "speichern");
  assert.ok(datenSave &&
    !JSON.parse(datenSave.text).syncMetadaten.eds.adressbuecher["buch-privat"],
    "die Adressbuch-Baseline wird vor dem erfolgreichen Datenspeichern gesetzt");
  enSW.App.gespeichert({ id: datenSave.id, ok: true });
  const baselineSave = enSyncNachrichten.filter((nachricht) =>
    nachricht.cmd === "speichern").at(-1);
  assert.ok(baselineSave !== datenSave &&
    JSON.parse(baselineSave.text).syncMetadaten.eds.adressbuecher["buch-privat"].letzterSync === 1234 &&
    !JSON.parse(baselineSave.text).letzteSyncs.adressbuecher["buch-privat"],
    "die Baseline wird nach dem Datenspeichern nicht separat persistiert");
  enSW.App.gespeichert({ id: baselineSave.id, ok: false, fehler: "Baseline disk full" });
  assert.ok(!enST.daten().syncMetadaten.eds.adressbuecher["buch-privat"],
    "ein Baseline-Speicherfehler lässt EDS-Metadaten im Speicher initialisiert");
  enSW.App.syncFehler("EDS-Technikfehler X");
  assert.strictEqual(enSD.querySelector("#sync-status").textContent,
    "Synchronization failed.", "englischer Synchronisationsfehlerstatus fehlt");
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Synchronization failed: EDS-Technikfehler X",
    "technische Fehlerangabe wurde übersetzt oder falsch gerahmt");

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Contacts").click();
  const enAdressen = enSD.querySelector("#einstellungen-inhalt");
  assert.strictEqual(enAdressen.querySelector("h3").textContent,
    "Use contact addresses", "englische Kontakt-Nutzungsseite fehlt");
  assert.ok(enAdressen.textContent.includes("Your address") &&
    enAdressen.textContent.includes("Import from LibreOffice") &&
    enAdressen.textContent.includes("Letter template") &&
    enAdressen.textContent.includes("Country for searches") &&
    enAdressen.textContent.includes("Merge duplicate contact cards"),
  "englische Kontakt-Nutzungsbeschriftungen fehlen");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#adressen-sortierung").options,
    (option) => option.value), ["last-name", "first-name"],
  "englische Sortierung verändert gespeicherte Werte");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#adressen-brief-layout").options,
    (option) => option.value), ["compact", "din5008"],
  "englische Briefvorlage verändert gespeicherte Werte");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#adressen-karten").options,
    (option) => option.value), ["auto", "gnome-maps", "openstreetmap", "google"],
  "englische Kartenauswahl verändert Providerkennungen");
  const enAbsender = enSD.querySelector("#adressen-absender");
  enAbsender.value = "Erika Beispiel\nMusterweg 3\n47051 Duisburg";
  enAbsender.dispatchEvent(new enSW.Event("input", { bubbles: true }));
  enSD.querySelector("#adressen-land").value = "Österreich";
  enSD.querySelector("#adressen-land").dispatchEvent(
    new enSW.Event("input", { bubbles: true }));
  Array.from(enAdressen.querySelectorAll("button"))
    .find((button) => button.textContent === "Import from LibreOffice").click();
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "lo_benutzer") &&
    enST.daten().einstellungen.adressen.absender.includes("Musterweg 3") &&
    enST.daten().einstellungen.adressen.land === "Österreich",
  "englische Kontaktseite verändert Anschrift, Land oder LibreOffice-Befehl");
  enSW.App.loBenutzer({ ok: true,
    absender: "Erika Beispiel\nMusterweg 3\n47051 Duisburg" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Address imported from LibreOffice.", "englische LibreOffice-Rückmeldung fehlt");
  enSW.App.adressWeg({ womit: "gnome-maps", fehler: "" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Opened in GNOME Maps.", "englische Karten-Rückmeldung fehlt");
  enSD.querySelector("#adressen-dubletten").click();
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "No duplicate contact cards were found.", "englischer Dublettenleerstand fehlt");
  enST.daten().kontakte.push(
    { id: "en-d1", nachname: "Doppel", vorname: "Dieter",
      email: "dieter@example.test", telefone: [], anschriften: [] },
    { id: "en-d2", nachname: "Doppel", vorname: "Dieter",
      email: "dieter@example.test", telefone: [], anschriften: [] });
  enSD.querySelector("#adressen-dubletten").click();
  assert.ok(enSD.querySelector("#dialog-text").textContent.includes(
    "Found 1 group containing 2 contact cards in total") &&
    enSD.querySelector("#dialog-text").textContent.includes("Doppel"),
  "englischer Dublettenfund oder unveränderter Kontaktname fehlt");
  enSD.querySelector("#dialog-ja").click();
  await tick();
  await tick();
  assert.ok(enSD.querySelector("#dialog-text").textContent.includes(
    "Really merge one contact card") &&
    enSD.querySelector("#dialog-ja").textContent === "Yes, merge",
  "englische zweite Dublettenbestätigung fehlt: " +
    enSD.querySelector("#dialog-text").textContent + " / " +
    enSD.querySelector("#dialog-ja").textContent);
  enSD.querySelector("#dialog-nein").click();
  enST.daten().kontakte = enST.daten().kontakte.filter(
    (kontakt) => !kontakt.id.startsWith("en-d"));

  enST.inDenPapierkorb("notiz", { id: "en-pk", titel: "Nicht übersetzen" },
    "Nicht übersetzen");
  enSW.App.backgroundSettings({ enabled: true, autostart: false, running: true,
    encryption_policy: "notify_then_unlock", keyring_available: false,
    native_notifications_supported: true, native_actions_supported: false,
    permissions: { kde_pairing: true, kde_incoming_files: false,
      sms_phone_notifications: true, phone_monitor: true,
      phone_sms_notifications: true, phone_selected_notifications: false,
      phone_call_notifications: true, phone_pairing_decisions: false,
      phone_personal_sync_offers: true, magnolienbaum_change_offers: false } });
  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Security").click();
  const enSicherheit = enSD.querySelector("#einstellungen-inhalt");
  assert.ok(Array.from(enSicherheit.querySelectorAll("h3"),
    (heading) => heading.textContent).includes("Recycle bin") &&
    Array.from(enSicherheit.querySelectorAll("h3"),
      (heading) => heading.textContent).includes("Password protection"),
  "englische Sicherheitsabschnitte fehlen");
  const hintergrundAbschnitt = enSicherheit.querySelector(".hintergrunddienst-abschnitt");
  const sicherheitsUeberschriften = Array.from(enSicherheit.querySelectorAll("h3"),
    (heading) => heading.textContent);
  assert.ok(hintergrundAbschnitt && hintergrundAbschnitt.querySelector("#hintergrunddienst-an") &&
    hintergrundAbschnitt.querySelector("#hintergrunddienst-autostart") &&
    hintergrundAbschnitt.querySelectorAll("[data-permission]").length === 10 &&
    hintergrundAbschnitt.textContent.includes("Service running") &&
    hintergrundAbschnitt.textContent.includes(
      "Pairing, file and clipboard requests are confirmed in this window.") &&
    hintergrundAbschnitt.textContent.includes("Magnolienbaum change offers") &&
    hintergrundAbschnitt.textContent.includes("(unavailable)"),
  "Hintergrunddienst-Steuerung oder Laufzeitstatus fehlt unter Sicherheit");
  assert.ok(hintergrundAbschnitt.querySelector(".einst-warnung").textContent.includes(
    "Pairing, file and clipboard requests are confirmed in this window.") &&
    !hintergrundAbschnitt.querySelector(".baum-zustand.gut").textContent.includes(
      "Pairing, file and clipboard requests are confirmed in this window.") &&
    !hintergrundAbschnitt.querySelector(".einst-warnung").textContent.includes("Start Organizer"),
  "fehlende Benachrichtigungsaktionen erscheinen nicht als Warnung");
  assert.ok(sicherheitsUeberschriften.indexOf("Background service") <
    sicherheitsUeberschriften.indexOf("Backups"),
  "Hintergrunddienst steht nicht vor den Sicherungsabschnitten");
  const rechteGruppe = hintergrundAbschnitt.querySelector("#hintergrunddienst-rechte");
  assert.ok(rechteGruppe && !rechteGruppe.open &&
    rechteGruppe.querySelector("summary").textContent === "Allowed background functions" &&
    rechteGruppe.querySelector("#hintergrunddienst-rechte-alle") &&
    rechteGruppe.querySelector("#hintergrunddienst-rechte-keine"),
  "Hintergrundrechte sind nicht geschlossen oder besitzen keine Schnellwahl");
  const keyringOption = hintergrundAbschnitt.querySelector(
    '#hintergrunddienst-verschluesselung option[value="keyring"]');
  assert.ok(keyringOption && keyringOption.disabled &&
    hintergrundAbschnitt.textContent.includes("cannot be enabled"),
  "nicht unterstützter Schlüsselbund bleibt auswählbar oder unerklärt");
  const pairingPermission = hintergrundAbschnitt.querySelector('[data-permission="kde_pairing"]');
  pairingPermission.checked = false;
  pairingPermission.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const hintergrundSave = enSyncNachrichten.filter((nachricht) =>
    nachricht.cmd === "background_settings_set").at(-1);
  assert.ok(hintergrundSave && hintergrundSave.settings.permissions.kde_pairing === false &&
    hintergrundSave.settings.encryption_policy === "notify_then_unlock" &&
    !Object.prototype.hasOwnProperty.call(hintergrundSave.settings, "running") &&
    !Object.prototype.hasOwnProperty.call(hintergrundSave.settings, "password"),
  "Hintergrunddienst-Änderung sendet keinen sauberen unmittelbaren Bridge-Nutzlast");
  rechteGruppe.querySelector("#hintergrunddienst-rechte-keine").click();
  let schnellwahlSave = enSyncNachrichten.filter((nachricht) =>
    nachricht.cmd === "background_settings_set").at(-1);
  assert.ok(Array.from(rechteGruppe.querySelectorAll("[data-permission]"),
    (feld) => !feld.checked).every(Boolean) &&
    Object.values(schnellwahlSave.settings.permissions).every((wert) => wert === false),
  "Schnellwahl Keine lässt ein Hintergrundrecht aktiv");
  rechteGruppe.querySelector("#hintergrunddienst-rechte-alle").click();
  schnellwahlSave = enSyncNachrichten.filter((nachricht) =>
    nachricht.cmd === "background_settings_set").at(-1);
  assert.ok(Array.from(rechteGruppe.querySelectorAll("[data-permission]:not(:disabled)"),
    (feld) => feld.checked).every(Boolean) &&
    schnellwahlSave.settings.permissions.magnolienbaum_change_offers === false,
  "Schnellwahl Alle aktiviert verfügbare Rechte nicht oder ein gesperrtes Recht doch");
  assert.ok(enSD.querySelector("#papierkorb-stand").textContent.includes("1 note") &&
    enSicherheit.textContent.includes("Nicht übersetzen") &&
    enSicherheit.textContent.includes("Use the recycle bin") &&
    enSicherheit.textContent.includes("Delete permanently"),
  "englischer Papierkorb oder unveränderte Benutzerdaten fehlen");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#papierkorb-tage").options,
    (option) => option.value), ["7", "30", "90", "365", "0"],
  "englischer Papierkorb verändert Aufbewahrungswerte");
  assert.ok(enSicherheit.textContent.includes(
    "Allow notifications despite password protection") &&
    enSicherheit.textContent.includes("may read the separate reminder data"),
  "englische Freigabeerklärung fehlt");
  const enErinnernMitKennwort = enSD.querySelector("#kennwort-erinnerungen");
  const enVertraulich = enSD.querySelector("#kennwort-vertraulich");
  enErinnernMitKennwort.click();
  enVertraulich.click();
  assert.deepStrictEqual({
    erinnern: enST.daten().einstellungen.sicherheit.erinnernTrotzKennwort,
    vertraulich: enST.daten().einstellungen.sicherheit.vertraulicheErinnerungen
  }, { erinnern: true, vertraulich: true },
  "englische Sicherheitsseite verändert Freigabewerte");
  const enKennwort = enSD.querySelector("#kennwort-neu");
  const enKennwort2 = enSD.querySelector("#kennwort-neu2");
  enKennwort.value = "abc";
  enKennwort2.value = "abc";
  enSD.querySelector("#kennwort-an").click();
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Choose at least four characters.", "englische Kennwortlängenprüfung fehlt");
  enKennwort.value = "Magnolie 1896";
  enKennwort2.value = "Magnolie 1896";
  enSD.querySelector("#kennwort-an").click();
  assert.ok(enSD.querySelector("#dialog-text").textContent.includes(
    "Without the password, it will be irretrievably lost") &&
    enSD.querySelector("#dialog-ja").textContent === "Enable",
  "englische Kennwortwarnung fehlt");
  enSD.querySelector("#dialog-ja").click();
  await tick();
  const enKennwortBefehl = enSyncNachrichten.find(
    (nachricht) => nachricht.cmd === "kennwort_setzen");
  assert.deepStrictEqual(enKennwortBefehl, {
    cmd: "kennwort_setzen", alt: "", neu: "Magnolie 1896",
    sicherungen: true, sicherungsordner: ""
  }, "englische Kennwortseite verändert sensible Bridge-Daten");
  enSW.App.kennwortStand({ ok: true, an: true, sicherungen: 1,
    sicherungenFehler: 2, journal: 1, journalFehler: 2 });
  assert.ok(enSD.querySelector("#zettel").textContent.includes(
    "one backup was encrypted as well") && enSD.querySelector("#zettel").textContent
      .includes("2 backups could not be updated") &&
    enSD.querySelector("#zettel").textContent.includes(
      "one recovery snapshot was encrypted as well") &&
    enSD.querySelector("#zettel").textContent.includes(
      "2 recovery snapshots could not be updated"),
  "englischer Sicherungs- und Journalbericht verwendet keine Pluralformen");
  enSD.querySelector("#kennwort-weg").click();
  assert.ok(enSD.querySelector("#dialog-text").textContent.includes(
    "stored unencrypted in your home directory again") &&
    enSD.querySelector("#dialog-ja").textContent === "Remove",
  "englische Kennwortentfernungswarnung fehlt");
  enSD.querySelector("#dialog-ja").click();
  await tick();
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "kennwort_entfernen" && nachricht.alt === "" &&
    nachricht.sicherungsordner === ""),
  "englische Kennwortentfernung verändert den Bridge-Vertrag");

  enST.zeigeSperrbildschirm(61);
  assert.strictEqual(enSD.querySelector("#sperr-schleier .sperr-blatt")
    .getAttribute("aria-label"),
    "Unlock Magnolie Organizer", "englische Sperrbildschirm-Beschriftung fehlt");
  assert.strictEqual(enSD.querySelector("#sperr-hinweis").textContent,
    "Please unlock", "englischer Entsperrhinweis fehlt");
  assert.ok(enSD.querySelector("#sperr-fuss").textContent.includes(
    "wait 1 minute 01 second"), "englischer Sperr-Countdown fehlt");
  enST.zeigeSperrbildschirm(0);
  enSD.querySelector("#sperr-umschalter").click();
  const enSperrFeld = enSD.querySelector("#sperr-feld");
  enSperrFeld.value = "Magnolie 1896";
  enSperrFeld.dispatchEvent(new enSW.Event("input", { bubbles: true }));
  enSperrFeld.dispatchEvent(new enSW.KeyboardEvent("keydown",
    { key: "Enter", bubbles: true }));
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "entsperren" && nachricht.kennwort === "Magnolie 1896"),
  "englischer Sperrbildschirm verändert Kennwort oder Bridge-Befehl");
  enSW.App.init({ gesperrt: true, neu: false, datenPfad: "",
    regional: { language: "en", formatLocale: "en-US" } });
  const baumBefehleVorSperre = enSyncNachrichten.filter(
    (nachricht) => nachricht.cmd === "baum_eingang_geleert").length;
  enSW.App.baumStand({ eingang: [{ id: "hinter-sperre", art: "stand",
    inhalt: { art: "stand", id: "nicht-geladen", erledigt: true } }] });
  assert.strictEqual(enSyncNachrichten.filter(
    (nachricht) => nachricht.cmd === "baum_eingang_geleert").length,
  baumBefehleVorSperre,
  "Magnolienbaum-Nachrichten werden hinter dem Sperrbildschirm nicht verarbeitet");
  enSW.App.entsperrtFehler({ wartet: 0, fehler: "" });
  assert.strictEqual(enSD.querySelector("#sperr-hinweis").textContent,
    "That is not correct.", "englischer Entsperr-Rückfall fehlt");
  enSW.App.init({ daten: enSyncDaten, neu: false, datenPfad: "",
    kennwort: false, trayVerfuegbar: false, handbuchInstalliert: true });
  enST.oeffneEinstellungen();

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Country & holidays").click();
  assert.strictEqual(enSD.querySelector("#einstellungen-inhalt h3").textContent,
    "Country and region", "englische Land-und-Region-Seite fehlt");
  const enLand = enSD.querySelector("#ort-land");
  assert.strictEqual(Array.from(enLand.options).find((option) => option.value === "DE")
    .textContent, "Germany", "englischer Ländername oder ISO-Code fehlt");
  enLand.value = "DE";
  enLand.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const enRegion = enSD.querySelector("#ort-region");
  assert.strictEqual(Array.from(enRegion.options).find(
    (option) => option.value === "DE-NW").textContent, "North Rhine-Westphalia",
  "englischer Regionsname oder ISO-Code fehlt");
  enRegion.value = "DE-NW";
  enRegion.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#ort-ferien").checked = true;
  enSD.querySelector("#ort-ferien").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  Array.from(enSD.querySelectorAll("button"))
    .find((button) => button.textContent === "Retrieve now").click();
  const enFeiertagBefehl = enSyncNachrichten.find(
    (nachricht) => nachricht.cmd === "feiertage");
  assert.strictEqual(enFeiertagBefehl.land, "DE");
  assert.strictEqual(enFeiertagBefehl.region, "DE-NW");
  assert.strictEqual(enFeiertagBefehl.regionErforderlich, true);
  assert.strictEqual(enFeiertagBefehl.ferien, true);
  assert.ok(enFeiertagBefehl.jahre.every(Number.isInteger) &&
    !Object.keys(enFeiertagBefehl).some((key) => /country|state|holiday/i.test(key)),
  "englische Feiertagsseite verändert Bridge-Schlüssel oder Jahreswerte");
  enSW.App.feiertageErgebnis({ feiertage: [
    { von: "2026-10-03", bis: "2026-10-03", name: "Tag der Deutschen Einheit",
      art: "feiertag", region: "DE-NW", regionName: "North Rhine-Westphalia" },
    { von: "2026-07-01", bis: "2026-08-01", name: "Sommerferien",
      art: "ferien", region: "DE-NW", regionName: "North Rhine-Westphalia" }
  ], jahre: [2026], bericht: "Provider report unchanged." });
  assert.ok(enSD.querySelector("#ort-stand").textContent.includes("1 public holiday") &&
    enSD.querySelector("#ort-stand").textContent.includes("1 holiday period"),
  "englische Feiertags-Singularformen fehlen");
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Provider report unchanged.", "Providerbericht wurde im Web übersetzt");
  assert.deepStrictEqual(enST.daten().feiertage.map((eintrag) => [
    eintrag.name, eintrag.art, eintrag.region]), [
    ["Tag der Deutschen Einheit", "public-holiday", "DE-NW"],
    ["Sommerferien", "school-holiday", "DE-NW"]
  ], "Bestandsnamen, Feiertagsarten oder Regionscodes wurden übersetzt");

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Typography").click();
  assert.strictEqual(enSD.querySelector("#einstellungen-inhalt h3").textContent,
    "Typography for your entries", "englische Typografieseite fehlt");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#schrift-art").options,
    (option) => [option.value, option.textContent]),
  [["regular", "As usual (print)"], ["handwriting", "Handwriting"]],
  "englische Schriftarten oder interne Werte fehlen");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#schrift-farbe").options,
    (option) => option.value), ["black", "blue"],
  "interne Tintenwerte wurden übersetzt");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#schrift-groesse").options,
    (option) => option.value), ["normal", "medium", "large"],
  "interne Schriftgrößen wurden übersetzt");
  assert.ok(enSD.querySelector("#schrift-probe").textContent.includes(
    "Preview of your entries") && enSD.querySelector("#schrift-probe").innerHTML
      .includes("<b>bold</b>") && enSD.querySelector("#einstellungen-inhalt")
      .textContent.includes("sudo apt install hunspell-en-us") &&
      enST.rechtschreibSprache() === "en" &&
      enST.rechtschreibPaket() === "hunspell-en-us",
  "englische Vorschau oder passender Wörterbuchbefehl fehlt");
  enSD.querySelector("#schrift-art").value = "handwriting";
  enSD.querySelector("#schrift-art").dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#schrift-farbe").value = "blue";
  enSD.querySelector("#schrift-farbe").dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#schrift-groesse").value = "large";
  enSD.querySelector("#schrift-groesse").dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#schrift-pruefung").checked = true;
  enSD.querySelector("#schrift-pruefung").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  assert.deepStrictEqual({ art: enST.daten().einstellungen.schrift.art,
    farbe: enST.daten().einstellungen.schrift.farbe,
    groesse: enST.daten().einstellungen.schrift.groesse },
  { art: "handwriting", farbe: "blue", groesse: "large" },
  "englische Typografieseite verändert gespeicherte Auswahlwerte");
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "rechtschreibung" && nachricht.an === true &&
      nachricht.sprache === "en") &&
    Array.from(enSD.querySelectorAll("[spellcheck=true]")).every(
      (feld) => feld.getAttribute("lang") === "en"),
  "englische Rechtschreibbefehle oder Feldsprachen sind nicht englisch");

  const enRechtschreibFeld = enSD.createElement("input");
  enRechtschreibFeld.type = "text";
  enRechtschreibFeld.value = "wrnog";
  enSD.body.append(enRechtschreibFeld);
  enRechtschreibFeld.setSelectionRange(2, 2);
  enRechtschreibFeld.dispatchEvent(new enSW.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 90, clientY: 90 }));
  const enVorschlagsBefehl = enSyncNachrichten.find((nachricht) =>
    nachricht.cmd === "vorschlaege" && nachricht.wort === "wrnog");
  assert.ok(enVorschlagsBefehl && enVorschlagsBefehl.sprache === "en",
    "englische Vorschlagsanfrage überträgt ihre Sprache nicht");
  enSW.App.vorschlaege({ kennung: enST.kennung(), wort: "wrnog", richtig: false,
    vorschlaege: ["wrong"], fehler: "" });
  Array.from(enSD.querySelectorAll("#vorschlags-menue .vm-eintrag"))
    .find((button) => button.textContent === "Add to dictionary").click();
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "wort_merken" && nachricht.wort === "wrnog" &&
      nachricht.sprache === "en"),
  "englischer Wörterbucheintrag überträgt seine Sprache nicht");
  enRechtschreibFeld.remove();

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Calendar").click();
  assert.strictEqual(enSD.querySelector("#einstellungen-inhalt h3").textContent,
    "Calendar", "englische Kalendereinstellungsseite fehlt");
  assert.deepStrictEqual(Array.from(enSD.querySelector("#kalender-klick").options,
    (option) => [option.value, option.textContent]), [
    ["tag", "Open the day in the daily view"],
    ["neu", "Create a new appointment immediately"]
  ], "englische Tagesklick-Auswahl oder interne Werte fehlen");
  const enKalenderText = enSD.querySelector("#einstellungen-inhalt").textContent;
  assert.ok(enKalenderText.includes("Show week numbers in the monthly view") &&
    enKalenderText.includes("Show week numbers in the planner") &&
    enKalenderText.includes("Hide past appointments") &&
    enKalenderText.includes("Also hide past anniversaries") &&
    enKalenderText.includes("Also hide past school holidays"),
  "englische Kalenderoptionen sind unvollständig");
  assert.deepStrictEqual(Array.from(enSD.querySelectorAll(
    "#einstellungen-inhalt details.einst-gruppe > summary"),
  (summary) => summary.textContent),
  ["Week numbers", "Weather", "Shift planner", "Cycle calendar", "Vacation planner",
    "Waste collection calendar", "Health"],
  "die voreingestellte Gesundheitsgruppe fehlt in den Kalendereinstellungen");
  assert.ok(Array.from(enSD.querySelectorAll("#einstellungen-inhalt details.einst-gruppe"))
    .every((details) => !details.open),
  "Kalendergruppen sind beim Öffnen nicht vollständig geschlossen");
  enSD.querySelector("#kalender-schichtplaner").click();
  Array.from(enSD.querySelectorAll("#kalender-gruppe-schichtplaner button"))
    .find((button) => button.textContent.includes("Add shift")).click();
  const schichtFelder = enSD.querySelectorAll(".schicht-definition input");
  setze(schichtFelder[0], "Early shift");
  schichtFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  schichtFelder[1].value = "06:00";
  schichtFelder[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  schichtFelder[2].value = "14:00";
  schichtFelder[2].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#kalender-zykluskalender").click();
  Array.from(enSD.querySelectorAll("#kalender-gruppe-zykluskalender button"))
    .find((button) => button.textContent.includes("Add cycle marker")).click();
  const zyklusFelder = enSD.querySelectorAll(".zyklus-definition input");
  setze(zyklusFelder[0], "Fertile days");
  zyklusFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  setze(zyklusFelder[1], "◇");
  zyklusFelder[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.ok(enST.daten().einstellungen.kalender.schichtplanerAn &&
    enST.daten().einstellungen.kalender.zykluskalenderAn &&
    enST.daten().schichten[0].name === "Early shift" &&
    enST.daten().schichten[0].von === "06:00" &&
    enST.daten().schichten[0].bis === "14:00" &&
    enST.daten().zyklusmarker[0].name === "Fertile days" &&
    enST.daten().zyklusmarker[0].symbol === "◇",
  "Schicht- oder Zyklusdefinition wird nicht gespeichert");
  enSD.querySelector("#kalender-urlaubsplaner").click();
  Array.from(enSD.querySelectorAll("#kalender-gruppe-urlaubsplaner button"))
    .find((button) => button.textContent.includes("Add vacation period")).click();
  const urlaubsFelder = enSD.querySelectorAll(".urlaubs-zeile .datumsfeld");
  urlaubsFelder[0].value = "2026-08-04";
  urlaubsFelder[0].dispatchEvent(new enSW.Event("input", { bubbles: true }));
  urlaubsFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  urlaubsFelder[1].value = "2026-08-06";
  urlaubsFelder[1].dispatchEvent(new enSW.Event("input", { bubbles: true }));
  urlaubsFelder[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.ok(enST.daten().einstellungen.kalender.urlaubsplanerAn &&
    enST.urlaubeAm("2026-08-05").length === 1 &&
    enST.urlaubeAm("2026-08-07").length === 0,
  "mehrtägiger Urlaub wird nicht einschließlich seiner Grenzen gespeichert");
  enSD.querySelector("#kalender-muellkalender").click();
  Array.from(enSD.querySelectorAll("#kalender-gruppe-muellkalender button"))
    .find((button) => button.textContent.includes("Residual waste")).click();
  const muellFelder = enSD.querySelectorAll(".muell-zeile input");
  muellFelder[1].value = "2026-08-03";
  muellFelder[1].dispatchEvent(new enSW.Event("input", { bubbles: true }));
  muellFelder[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  muellFelder[2].value = "14";
  muellFelder[2].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.ok(enST.daten().einstellungen.kalender.muellkalenderAn &&
    enST.muelltermineAm("2026-08-03").length === 1 &&
    enST.muelltermineAm("2026-08-17").length === 1 &&
    enST.muelltermineAm("2026-08-18").length === 0 &&
    enST.daten().muelltermine[0].farbe === "#4c4b47",
  "vierzehntägige farbige Müllabholung wird nicht richtig gespeichert oder berechnet");
  Array.from(enSD.querySelectorAll("#kalender-gruppe-muellkalender button"))
    .find((button) => button.textContent.includes("Custom")).click();
  const eigeneMuellFelder = enSD.querySelectorAll(".muell-zeile")[1].querySelectorAll("input");
  setze(eigeneMuellFelder[0], "Hazardous waste");
  eigeneMuellFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  eigeneMuellFelder[1].value = "2026-08-04";
  eigeneMuellFelder[1].dispatchEvent(new enSW.Event("input", { bubbles: true }));
  eigeneMuellFelder[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  eigeneMuellFelder[3].value = "#9b2734";
  eigeneMuellFelder[3].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.ok(enST.muelltermineAm("2026-08-04").some((termin) =>
    termin.name === "Hazardous waste" && termin.farbe === "#9b2734") &&
    !enST.muelltermineAm("2026-08-05").some((termin) => termin.name === "Hazardous waste"),
  "eine benutzerdefinierte einmalige Müllart wird nicht mit eigener Farbe gespeichert");
  enSD.querySelector("#kalender-klick").value = "tag";
  enSD.querySelector("#kalender-klick").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#kalender-wochennummern").click();
  enSD.querySelector("#kalender-planer-wochennummern").click();
  enSD.querySelector("#kalender-vergangene-termine").click();
  enSD.querySelector("#kalender-vergangene-jahrestage").click();
  enSD.querySelector("#kalender-vergangene-ferien").click();
  assert.deepStrictEqual({
    klickLegtAn: enST.daten().einstellungen.kalender.klickLegtAn,
    wochenNummern: enST.daten().einstellungen.kalender.wochenNummern,
    planerWochenNummern: enST.daten().einstellungen.kalender.planerWochenNummern,
    vergangeneTermine: enST.daten().einstellungen.kalender.vergangeneTermine,
    vergangeneJahrestage: enST.daten().einstellungen.kalender.vergangeneJahrestage,
    vergangeneFerien: enST.daten().einstellungen.kalender.vergangeneFerien
  }, { klickLegtAn: false, wochenNummern: true, planerWochenNummern: true,
    vergangeneTermine: true, vergangeneJahrestage: true, vergangeneFerien: true },
  "englische Kalendertexte verändern gespeicherte Vertragswerte");
  assert.deepStrictEqual(Array.from(enSD.querySelector(
    "#kalender-wetter-darstellung").options, (option) => [option.value, option.textContent]), [
    ["symbol", "Magnolia weather symbols only"],
    ["temperature", "Symbols and temperatures"],
    ["detailed", "Symbols, temperatures and description"]
  ], "englische Wetterdarstellung oder interne Werte fehlen");
  assert.deepStrictEqual(Array.from(enSD.querySelector(
    "#kalender-wetter-intervall").options, (option) => option.value),
  ["30", "60", "180", "360", "720"],
  "Wetterintervalle wurden übersetzt");
  assert.ok(enSD.querySelector("#einstellungen-inhalt").textContent.includes(
    "Weather requests are sent to wttr.in") && enSD.querySelector(
      "#einstellungen-inhalt").textContent.includes("public IP address") &&
    enSD.querySelector("#kalender-wetter-ohne-ort").disabled,
  "englischer Wetter- oder Standorthinweis fehlt");
  enST.daten().einstellungen.adressen.absender =
    "Erika Beispiel\nMusterweg 3\n47051 Duisburg\nDeutschland";
  enSD.querySelector("#kalender-wetter").click();
  enSD.querySelector("#kalender-wetter-darstellung").value = "detailed";
  enSD.querySelector("#kalender-wetter-darstellung").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#kalender-wetter-intervall").value = "30";
  enSD.querySelector("#kalender-wetter-intervall").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  assert.deepStrictEqual({
    wetter: enST.daten().einstellungen.allgemein.wetter,
    darstellung: enST.daten().einstellungen.allgemein.wetterDarstellung,
    intervall: enST.daten().einstellungen.allgemein.wetterIntervall,
    ohneOrt: enST.daten().einstellungen.allgemein.wetterOhneOrtAbrufen
  }, { wetter: true, darstellung: "detailed", intervall: 30, ohneOrt: true },
  "englische Wettertexte verändern gespeicherte Werte");
  const enWetterBefehl = enSyncNachrichten.find((nachricht) => nachricht.cmd === "wetter");
  assert.ok(enWetterBefehl && enWetterBefehl.ort === "47051 Duisburg" &&
    enWetterBefehl.ohneOrtAbrufen === true && Number.isInteger(enWetterBefehl.kennung),
  "englische Wetterseite verändert Ort oder Bridge-Nutzlast");
  enSD.querySelector('#ansicht-umschalter [data-ansicht="month"]').click();
  enSW.App.wetterErgebnis({ ok: true, kennung: enWetterBefehl.kennung,
    ort: "Duisburg", quelle: "ip", tage: [
      { datum: "2026-08-03", min: 17, max: 25, code: 113, beschreibung: "Sonnig" }
    ] });
  assert.ok(enSD.querySelector(".wetter-kasten").textContent.includes("Duisburg") &&
    enSD.querySelector(".wetter-kasten").textContent.includes("Sonnig") &&
    enSD.querySelector(".wetter-kasten").textContent.includes("public IP address"),
  "englischer Wetterrahmen oder unveränderte Providerdaten fehlen");
  enSW.App.wetterErgebnis({ ok: true, kennung: enWetterBefehl.kennung,
    ort: "Duisburg", quelle: "ip", tage: [] });
  assert.strictEqual(enST.wetterStand().fehler,
    "The weather service returned no forecast.",
    "englischer Rückfall für leere Vorhersagen fehlt");
  enSW.App.wetterErgebnis({ ok: true, kennung: enWetterBefehl.kennung,
    ohneOrt: true, tage: [] });
  assert.strictEqual(enST.wetterStand().fehler, "",
    "bewusst unterbundener Wetterabruf wird fälschlich als Fehler behandelt");
  assert.ok(enSD.querySelector(".wetter-kasten").textContent.includes(
    "Weather was not retrieved because no location is available."),
  "englischer Hinweis zum unterbundenen Wetterabruf fehlt");
  enST.daten().einstellungen.adressen.absender = "";
  enSD.querySelector("#kalender-wetter-ohne-ort").click();
  const enWetterSperrbefehl = enSyncNachrichten.filter(
    (nachricht) => nachricht.cmd === "wetter").at(-1);
  assert.ok(enST.daten().einstellungen.allgemein.wetterOhneOrtAbrufen === false &&
    enWetterSperrbefehl.ohneOrtAbrufen === false,
  "englische Datenschutzoption erreicht die Wetter-Bridge nicht");

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Notifications").click();
  const enErinnerung = enSD.querySelector("#einstellungen-inhalt");
  assert.strictEqual(enErinnerung.querySelector("h3").textContent,
    "Appointment reminders", "englische Benachrichtigungsseite fehlt");
  assert.ok(enErinnerung.textContent.includes("Enable reminders") &&
    enErinnerung.textContent.includes("Wake the computer from suspend") &&
    enErinnerung.textContent.includes("Also remind me about anniversaries") &&
    enErinnerung.textContent.includes("Keep a troubleshooting log") &&
    enErinnerung.textContent.includes("Show preview") &&
    enErinnerung.textContent.includes("Show log"),
  "englische Erinnerungsbeschriftungen fehlen");
  const enWeckOption = enErinnerung.querySelector(".erinnerung-weckoption");
  assert.ok(enWeckOption && enWeckOption.querySelector("#erinnerung-wecken") &&
    enWeckOption.previousElementSibling?.querySelector("#erinnerung-verpasst"),
  "Weckoption steht nicht unter der Erinnerung an verpasste Termine");
  const enErinnerungAn = enSD.querySelector("#erinnerung-an");
  enErinnerungAn.click();
  const enVorlauf = enSD.querySelector("#erinnerung-vorlauf");
  enVorlauf.value = "60";
  enVorlauf.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const enStil = enSD.querySelector("#erinnerung-stil");
  enStil.value = "magnolie";
  enStil.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const enJahrestage = enSD.querySelector("#erinnerung-jahrestage");
  enJahrestage.click();
  const enJtTage = enSD.querySelector("#erinnerung-jahrestage-tage");
  enJtTage.value = "2";
  enJtTage.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.deepStrictEqual({
    an: enST.daten().einstellungen.erinnerung.an,
    vorlauf: enST.daten().einstellungen.erinnerung.vorlauf,
    stil: enST.daten().einstellungen.erinnerung.stil,
    jahrestage: enST.daten().einstellungen.erinnerung.jahrestage.tage
  }, { an: true, vorlauf: 60, stil: "magnolie", jahrestage: 2 },
  "englische Erinnerungsseite verändert gespeicherte Werte");
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "erinnerung_einrichten" && nachricht.an === true &&
    nachricht.vorlauf === 60 && Array.isArray(nachricht.termine)),
  "englische Erinnerungsseite verändert den Einrichtungsbefehl");
  enSD.querySelector("#erinnerung-probe").click();
  const enProbe = enSyncNachrichten.find((nachricht) =>
    nachricht.cmd === "erinnerung_zeigen");
  assert.deepStrictEqual(enProbe, {
    cmd: "erinnerung_zeigen", art: "both", stil: "magnolie",
    kopf: "Magnolie Organizer",
    rumpf: "This is how the organizer reminds you about an appointment."
  }, "englische Vorschau verändert die Bridge-Nutzlast");
  enSW.App.protokollStand({ ok: true, pfad: "/tmp/Erinnerungen.log" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "Log opened: /tmp/Erinnerungen.log", "englischer Protokollpfad fehlt");
  enSW.App.protokollStand({ ok: false, fehler: "" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "The log could not be opened.", "englischer Protokollfehler fehlt");

  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "About").click();
  const enUeber = enSD.querySelector("#einstellungen-inhalt");
  assert.strictEqual(enUeber.querySelector("h3").textContent,
    "About the Magnolie Organizer", "englische Über-Seite fehlt");
  assert.ok(enUeber.querySelector(".ueber-seite .ueber-raster") &&
    enUeber.querySelectorAll(".ueber-spalte").length === 2 &&
    enUeber.querySelector(".ueber-programmspalte") &&
    enUeber.querySelector(".ueber-werkzeugspalte"),
  "Über-Seite ist nicht in zwei ausgewogene Informationsflächen gegliedert");
  assert.ok(enUeber.querySelector(".ueber-fassung").textContent.includes("Version 2.0.13") &&
    enUeber.textContent.includes("Author") && enUeber.textContent.includes("License") &&
    enUeber.textContent.includes("Updates") &&
    enUeber.textContent.includes("No update check has been performed yet") &&
    enUeber.textContent.includes("/usr/share/common-licenses/GPL-3"),
  "englische Versions-, Lizenz- oder Updateangaben fehlen");
  assert.strictEqual(enUeber.querySelector("#kaffee-anschrift").textContent,
    "maik3531@gmail.com", "Kontaktanschrift wurde übersetzt");
  assert.strictEqual(enUeber.querySelector("#kaffee-anschrift").title,
    "This address can be selected and copied.", "englischer Kopierhinweis fehlt");
  const kaffeeQr = enUeber.querySelector(".kaffee-qr");
  assert.ok(kaffeeQr && kaffeeQr.src.endsWith("/kaffee-qr.png") &&
    kaffeeQr.previousElementSibling.classList.contains("kaffee-text"),
  "QR-Code steht nicht direkt hinter dem Kaffeetext");
  enUeber.querySelector("#handbuch-oeffnen").click();
  enUeber.querySelector("#update-pruefen").click();
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "handbuch_oeffnen") &&
    enSyncNachrichten.some((nachricht) => nachricht.cmd === "update_pruefen"),
  "englische Über-Seite verändert Handbuch- oder Update-Befehl");
  const enUpdateUrl = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/" +
    "Magnolie-Organitzer/magnolie-organizer_2.0.14_all.deb";
  enSW.App.updateErgebnis({ ok: true, aktuell: false, version: "2.0.14",
    url: enUpdateUrl, sha256: "ab".repeat(32), fehler: "" });
  assert.ok(enSD.querySelector("#update-stand").textContent.includes(
    "New version 2.0.14 is available") &&
    enSD.querySelector("#update-herunterladen").textContent.includes("2.0.14") &&
    enSD.querySelector(".update-pruefsumme").textContent.includes("ab".repeat(32)) &&
    enSD.querySelector(".update-pruefsumme").textContent.includes("sha256sum"),
  "englischer neuer Update-Stand fehlt");
  Array.from(enSD.querySelectorAll(".update-pruefsumme button"))
    .find((button) => button.textContent === "Copy").click();
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "ablage_kopieren" && nachricht.text === "ab".repeat(32)),
  "Update-Prüfsumme lässt sich nicht unverändert kopieren");
  const enUpdateSpeicherstand = enSyncNachrichten.filter(
    (nachricht) => nachricht.cmd === "speichern").length;
  enSD.querySelector("#update-herunterladen").click();
  assert.ok(enSD.querySelector("#dialog-text").textContent.includes(
    "All changes will be saved") && enSD.querySelector("#dialog-text").textContent.includes(
      "close and restart"),
  "vor dem Update fehlt die verständliche Speicher- und Neustartabfrage");
  enSD.querySelector("#dialog-ja").click();
  for (let i = 0; i < 10 && enSyncNachrichten.filter(
    (nachricht) => nachricht.cmd === "speichern").length === enUpdateSpeicherstand; i++) {
    await tick();
  }
  const enUpdateBestaetigt = new Set();
  for (let i = 0; i < 20 && !enSyncNachrichten.some(
    (nachricht) => nachricht.cmd === "update_herunterladen"); i++) {
    const speichern = enSyncNachrichten.filter((nachricht) =>
      nachricht.cmd === "speichern" && !enUpdateBestaetigt.has(nachricht.id)).at(-1);
    if (speichern) {
      enUpdateBestaetigt.add(speichern.id);
      enSW.App.gespeichert({ ok: true, id: speichern.id });
    }
    await tick();
  }
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "update_herunterladen" && Object.keys(nachricht).length === 1),
  "bestätigtes Update startet keinen parameterlosen geprüften Download: " +
    JSON.stringify(enSyncNachrichten.slice(-8)));
  enSW.App.updateHeruntergeladen({ ok: true, bereit: true,
    version: "2.0.14", artifact: "deb" });
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "update_installieren"),
    "verifiziertes Update wird nicht zur Installation vorbereitet");
  enSW.App.updateInstallationVorbereitet({ ok: true, bereitZumBeenden: true,
    version: "2.0.14", artifact: "deb" });
  assert.ok(enSyncNachrichten.some((nachricht) => nachricht.cmd === "beenden"),
    "nach vorbereiteter Installation startet der sichere Beenden- und Neustartablauf nicht");
  enSW.App.updateGeoeffnet({ ok: false, fehler: "" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "The package could not be opened.", "englischer Paketfehler fehlt");
  enSW.App.handbuchGeoeffnet({ ok: false, fehler: "" });
  assert.strictEqual(enSD.querySelector("#zettel").textContent,
    "The manual could not be opened.", "englischer Handbuchfehler fehlt");
  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "General").click();
  assert.ok(enST.daten().einstellungen.kalender.gesundheitAn,
    "das Gesundheitsregister ist bei fehlender Nutzerentscheidung nicht aktiv");
  Array.from(enSD.querySelectorAll(".einst-reiter-knopf"))
    .find((button) => button.textContent === "Calendar").click();
  assert.ok(enSD.querySelectorAll(".gesundheit-einstellkopf .sinnbild").length === 4 &&
    enSD.querySelector("#kalender-gesundheit-plan-vital") &&
    enSD.querySelector("#kalender-gesundheit-einheit-temperatur") &&
    enSD.querySelector("#kalender-gesundheit-einheit-blutzucker"),
  "Gesundheitsansichten, Einheiten oder Kalenderplanung fehlen im Aufklappmenü");
  enST.daten().einstellungen.kalender.gesundheitEinheiten.temperatur = "fahrenheit";
  assert.strictEqual(enST.gesundheitAnzeigeWert("temperatur", 37), "98.6",
    "gespeicherte Celsiuswerte werden für Fahrenheit nicht umgerechnet");
  assert.ok(Math.abs(enST.gesundheitBasisWert("temperatur", "98,6") - 37) < 0.01,
    "Fahrenheit-Eingaben werden nicht metrisch zurückgespeichert");
  enST.daten().einstellungen.kalender.gesundheitEinheiten.temperatur = "auto";
  enST.schliesseEinstellungen();
  assert.ok(Array.from(enSD.querySelectorAll(".registerknopf")).some(
    (button) => button.textContent === "Health"),
  "das aktivierte Gesundheitsregister erscheint nicht nach dem Planer");
  enST.wechsel("gesundheit");
  assert.strictEqual(enSD.querySelectorAll(".gesundheit-symbolknopf").length, 4,
    "dem Gesundheitsbereich fehlen Unteransichten");
  assert.strictEqual(enSD.querySelectorAll(".vitalwert-tabelle").length, 2,
    "die Vitalwerttabelle ist nicht auf beide Buchseiten verteilt");
  assert.deepStrictEqual(Array.from(enSD.querySelectorAll(".vitalwert-tabelle tbody")).map(
    (koerper) => koerper.querySelectorAll("tr").length), [18, 18],
  "die Vitalwerttabellen nutzen die Buchseiten nicht bis unten aus");
  assert.ok(js.includes("new ResizeObserver(planeGesundheitReserve)") &&
    js.includes('window.addEventListener("resize", gesundheitReserveFensterFn)') &&
    js.includes("requestAnimationFrame"),
  "dynamische Gesundheitszeilen beobachten Größenänderungen nicht gebündelt mit Rückfall");
  const simuliereHoehe = (element, hoehe) => Object.defineProperty(element, "clientHeight",
    { configurable: true, value: hoehe });
  const simuliereTabellenmasse = (tabelle) => {
    Object.defineProperty(tabelle.tHead, "offsetHeight", { configurable: true, value: 40 });
    Object.defineProperty(tabelle.tBodies[0].rows[0], "offsetHeight",
      { configurable: true, value: 34 });
  };
  const sichtbareZeilen = (tabelle) => Array.from(tabelle.querySelectorAll("tbody tr"))
    .filter((zeile) => !zeile.classList.contains("gesundheit-reserve-verborgen"));
  let vitalTabellen = enSD.querySelectorAll(".vitalwert-tabelle");
  vitalTabellen.forEach(simuliereTabellenmasse);
  simuliereHoehe(vitalTabellen[0].parentElement, 210);
  simuliereHoehe(vitalTabellen[1].closest(".gesundheit-seitenrolle"), 278);
  enST.aktualisiereGesundheitReserve();
  assert.deepStrictEqual(Array.from(vitalTabellen, (tabelle) => sichtbareZeilen(tabelle).length),
    [5, 7], "Vitalhälften verwenden ihre jeweils eigene höhenabhängige Grundzahl nicht");
  const entfernteVitalzeile = vitalTabellen[0].querySelectorAll("tbody tr")[7].querySelector("input");
  enST.setzeDatumswert(entfernteVitalzeile, enST.isoHeute());
  entfernteVitalzeile.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  enST.aktualisiereGesundheitReserve();
  assert.strictEqual(sichtbareZeilen(vitalTabellen[0]).length, 9,
    "nach einer echten Vitalzeile bleibt nicht genau eine zusätzliche Reservezeile sichtbar");
  setze(entfernteVitalzeile, "");
  simuliereHoehe(vitalTabellen[0].parentElement, 700);
  enST.aktualisiereGesundheitReserve();
  assert.strictEqual(sichtbareZeilen(vitalTabellen[0]).length, 18,
    "eine große Seitenhöhe gibt nicht alle logischen Vitalzeilen frei");
  assert.ok(vitalTabellen[1].closest(".gesundheit-seitenrolle")
    .classList.contains("gesundheit-reserve-leer"),
  "eine leere Gesundheitstabelle behält eine vertikale Rollfläche");
  assert.ok(/\.gesundheit-papiertabelle th,\s*\.gesundheit-papiertabelle td\s*\{[^}]*height:\s*34px;/s
    .test(css) && !/\.gesundheit-papiertabelle[^}]*\{[^}]*min-height:\s*40px;/s.test(css),
  "Gesundheitsdatenzeilen behalten nicht ihre seitenfüllende Höhe von 34 Pixeln");
  assert.ok(enSD.querySelector("#inhalt-links .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-rechts .einst-warnung") &&
    !enSD.querySelector("#inhalt-rechts .gesundheit-referenzhinweis"),
  "der neutrale Referenzhinweis steht nicht ausschließlich auf der linken Seite");
  const vitalZeile = enSD.querySelector(".vitalwert-tabelle tbody tr");
  const vitalFelder = vitalZeile.querySelectorAll("input");
  const vitalZeit = vitalFelder[1];
  assert.ok(vitalZeit.type === "text" && vitalZeit.value === "" && vitalZeit.placeholder === "" &&
    vitalZeit.maxLength === 5 && vitalZeit.classList.contains("gesundheit-zeit") &&
    !vitalZeit.querySelector("input"),
  "die Vitalwertzeit ist nicht ein einzelnes leeres Segmentfeld ohne Browser-Uhr");
  setze(vitalZeit, "25:90");
  assert.ok(vitalZeit.value === "25:90" && !vitalZeit.checkValidity(),
    "das Vitalwertzeitfeld hält eine ungültige Uhrzeit nicht sichtbar und speichersperrend");
  setze(vitalZeit, "23:59");
  vitalZeit.setSelectionRange(0, 2);
  vitalZeit.dispatchEvent(new enSW.WheelEvent("wheel",
    { deltaY: -1, bubbles: true, cancelable: true }));
  assert.strictEqual(vitalZeit.value, "00:59",
    "das Mausrad ändert nicht nur das gewählte Stundensegment");
  vitalZeit.setSelectionRange(3, 5);
  vitalZeit.dispatchEvent(new enSW.WheelEvent("wheel",
    { deltaY: -1, bubbles: true, cancelable: true }));
  assert.strictEqual(vitalZeit.value, "00:00",
    "das Mausrad ändert nicht nur das gewählte Minutensegment");
  setze(vitalFelder[0], "2082026");
  assert.ok(vitalFelder[0].value === "20.08.2026" &&
    enST.datumswert(vitalFelder[0]) === "2026-08-20",
  "die eindeutige Ziffernfolge 2082026 wird nicht zu 20.08.2026 korrigiert");
  const datumVorschlaege = enSD.querySelectorAll("#gesundheit-datum-vorschlaege option");
  let datumPickerGeoeffnet = false;
  vitalFelder[0].showPicker = () => { datumPickerGeoeffnet = true; };
  vitalFelder[0].click();
  assert.ok(vitalFelder[0].getAttribute("list") === "gesundheit-datum-vorschlaege" &&
    datumVorschlaege.length === 3 && datumPickerGeoeffnet,
  "die unsichtbare Datumsauswahl bietet nicht heute und die zwei Vortage per Klick an");
  enST.setzeDatumswert(vitalFelder[0], enST.isoHeute());
  vitalFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  setze(vitalFelder[2], "80");
  setze(vitalFelder[3], "120");
  setze(vitalFelder[4], "80");
  assert.ok(vitalFelder[3].type === "text" &&
    vitalFelder[3].classList.contains("gesundheit-ampel-gruen"),
  "Blutdruckfeld verwendet noch native Pfeile oder erhält keine Referenzampel");
  assert.strictEqual(vitalFelder[4], vitalFelder[3].nextElementSibling.nextElementSibling,
    "systolischer und diastolischer Blutdruck sind nicht getrennt per Tab erreichbar");
  assert.ok(vitalFelder[2].closest("td").classList.contains("gesundheit-ampel-gruen") &&
    vitalZeile.classList.contains("gesundheit-zeile-ampel-gruen"),
  "normaler Puls färbt weder seine Zelle noch die Messzeile dezent grün");
  setze(vitalFelder[3], "135");
  setze(vitalFelder[4], "85");
  assert.ok(vitalFelder[3].closest("td").classList.contains("gesundheit-ampel-orange") &&
    vitalZeile.classList.contains("gesundheit-zeile-ampel-orange"),
  "hoch-normaler Blutdruck wird nicht orange eingeordnet");
  setze(vitalFelder[3], "145");
  setze(vitalFelder[4], "95");
  assert.ok(vitalFelder[3].closest("td").classList.contains("gesundheit-ampel-rot") &&
    vitalZeile.classList.contains("gesundheit-zeile-ampel-rot"),
  "Blutdruck ab 140 oder 90 wird nicht rot eingeordnet");
  setze(vitalFelder[3], "120");
  setze(vitalFelder[4], "80");
  setze(vitalFelder[5], "98.6");
  assert.ok(vitalFelder[5].closest("td").classList.contains("gesundheit-ampel-gruen"),
    "Normaltemperatur wird nicht grün eingeordnet");
  setze(vitalFelder[6], "154");
  setze(vitalFelder[7], "66.9");
  assert.ok(vitalZeile.querySelector("td:last-child").classList.contains("gesundheit-ampel-gruen"),
    "Normalgewicht wird zusammen mit der Größe nicht über den BMI grün eingeordnet");
  setze(vitalFelder[5], "0,5");
  assert.ok(!vitalFelder[5].checkValidity(),
    "eine unmögliche Körpertemperatur wird als gültig angenommen");
  setze(vitalFelder[5], "0");
  assert.strictEqual(vitalFelder[5].value, "", "ein Nullwert bleibt im Gesundheitsfeld sichtbar");
  setze(vitalFelder[6], "1");
  assert.ok(!vitalFelder[6].checkValidity(), "ein unrealistisches Gewicht von 1 kg wird zugelassen");
  setze(vitalFelder[6], "0");
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Save").click();
  assert.ok(enST.daten().gesundheit.vitalwerte.length === 1 &&
    enST.daten().gesundheit.vitalwerte[0].zeit === "00:00" &&
    !enST.gesundheitsMarkenAm(enST.isoHeute()).length,
  "ein gespeicherter Vitalwert verliert seine segmentierte Zeit oder erzeugt ein Kalendersymbol");
  const gespeicherteVitalwerte = enST.daten().gesundheit.vitalwerte.slice();
  enST.daten().gesundheit.vitalwerte = [
    { id: "bmi-height", datum: "2026-08-18", zeit: "08:00", groesse: 180 },
    { id: "bmi-weight", datum: "2026-08-19", zeit: "08:00", gewicht: 81 }
  ];
  Array.from(enSD.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === "History").click();
  assert.ok(enSD.querySelector(".gesundheit-bmi").textContent.endsWith(": 25.0"),
    "der Verlauf berechnet den BMI nicht aus dem jüngsten gespeicherten Gewicht und der jüngsten Größe");
  enST.daten().gesundheit.vitalwerte = gespeicherteVitalwerte;
  Array.from(enSD.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === "Vital signs").click();
  Object.assign(enST.daten().einstellungen.kalender.gesundheitPlanung.vital,
    { an: true, von: enST.isoHeute(), zeit: "", intervallTage: 1 });
  assert.ok(enST.gesundheitsMarkenAm(enST.isoHeute()).some((marke) => marke.art === "vital"),
    "aktivierte Vitalwertplanung erzeugt kein anklickbares Kalendersymbol");
  enST.daten().einstellungen.regional.timeZone = "Europe/Berlin";
  assert.strictEqual(enST.aktuelleGesundheitsZeit(new Date("2026-08-20T12:37:00Z")), "14:37",
    "der Klick auf ein Gesundheitssymbol verwendet nicht die aktuelle Organizer-Zeit");
  assert.ok(/\.tb-eigene-daten-steuerung \.knopf\s*\{[^}]*flex:\s*0 0 auto;[^}]*white-space:\s*nowrap;/s
    .test(css), "der übersetzte Aufnehmen-Knopf darf weiterhin schmaler als seine Beschriftung werden");
  assert.ok(/\.vitalwert-tabelle th:nth-child\(1\)\s*\{\s*width:\s*16%;/s.test(css) &&
    /\.vitalwert-tabelle th:nth-child\(2\)\s*\{\s*width:\s*12%;/s.test(css),
  "Vitalwertspalten wurden zur Umgehung eines Darstellungsfehlers verbreitert");
  assert.ok(/\.gesundheit-zellenfeld\s*\{[^}]*font:\s*10px\/1\.2 var\(--sans\);/s.test(css) &&
    !/font-size:\s*7\.5px/.test(css) &&
    !/\.termin-blatt \.zeitspanne \.datumsfeld\s*\{/.test(css) &&
    /\.feld\.gesundheit-zellenfeld\s*\{[^}]*padding-inline:\s*0;[^}]*font-size:\s*15px;/s.test(css) &&
    /@container \(max-width:\s*568px\)\s*\{\s*\.feld\.gesundheit-zellenfeld\s*\{\s*font-size:\s*12px;/s.test(css) &&
    /\.gesundheit-zellenfeld\.datumsfeld::\-webkit-calendar-picker-indicator,[^}]*display:\s*none\s*!important;[^}]*width:\s*0;/s.test(css) &&
    /\.gesundheit-insulinart-kopf\s*\{[^}]*grid-template-columns:\s*1fr 140px;/s.test(css),
  "Datumsfelder behalten nicht die ursprünglichen Schriftgrößen");
  const leereGesundheitsOds = enST.gesundheitOdsNutzlast({ leer: true, vital: true,
    blutzucker: true, medikamente: true }, []);
  assert.ok(leereGesundheitsOds.cmd === "gesundheit_ods" &&
    leereGesundheitsOds.tabellen.length === 3 &&
    leereGesundheitsOds.tabellen[0].links.length === 8 &&
    leereGesundheitsOds.tabellen[0].rechts.length === 8 &&
    leereGesundheitsOds.tabellen[0].zeilen.length === 20 &&
    leereGesundheitsOds.tabellen[1].links.join("|") ===
      leereGesundheitsOds.tabellen[1].rechts.join("|"),
  "Gesundheits-ODS bildet keine getrennten A4-Doppeltabellen");
  const deutscheGesundheitsOds = T.gesundheitOdsNutzlast({ leer: true, vital: true,
    blutzucker: false, medikamente: true }, []);
  assert.ok(deutscheGesundheitsOds.tabellen[0].links.includes("Temp. °C") &&
    deutscheGesundheitsOds.tabellen[1].rechts.includes("Besonder-\nheiten"),
  "ODS-Köpfe kürzen Temperatur oder trennen Besonderheiten nicht druckgerecht");
  Array.from(enSD.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === "Medication plan").click();
  assert.ok(enSD.querySelector(".medikament-links") && enSD.querySelector(".medikament-rechts"),
    "der Medikamentenplan ist nicht als zusammengehörige Doppelseitentabelle aufgebaut");
  assert.strictEqual(enSD.querySelectorAll(".medikament-links tbody tr").length, 18,
    "der Medikamentenplan bietet nicht genügend Zeilen mit weiterer Blätterfunktion");
  const medLinksTabelle = enSD.querySelector(".medikament-links");
  const medRechtsTabelle = enSD.querySelector(".medikament-rechts");
  [medLinksTabelle, medRechtsTabelle].forEach(simuliereTabellenmasse);
  simuliereHoehe(medLinksTabelle.parentElement, 346);
  simuliereHoehe(medRechtsTabelle.closest(".gesundheit-seitenrolle"), 244);
  enST.aktualisiereGesundheitReserve();
  assert.deepStrictEqual([sichtbareZeilen(medLinksTabelle).length,
    sichtbareZeilen(medRechtsTabelle).length], [6, 6],
  "Medikamentenhälften verwenden nicht dieselbe sichtbare Indexmenge aus dem kleineren Platz");
  const entfernteMedZeile = medLinksTabelle.querySelectorAll("tbody tr")[7].querySelector("input");
  setze(entfernteMedZeile, "Reserveprobe");
  enST.aktualisiereGesundheitReserve();
  assert.deepStrictEqual([sichtbareZeilen(medLinksTabelle).length,
    sichtbareZeilen(medRechtsTabelle).length], [9, 9],
  "belegte Medikamentenzeilen und ihre Reserve bleiben nicht auf beiden Seiten synchron sichtbar");
  setze(entfernteMedZeile, "");
  assert.ok(enSD.querySelector("#inhalt-links .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-rechts .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-rechts .einst-warnung"),
  "der neutrale Medikamentenhinweis steht nicht ausschließlich auf der linken Seite");
  const medZeileLinks = enSD.querySelector(".medikament-links tbody tr");
  const medLinksFelder = medZeileLinks.querySelectorAll("input");
  setze(medLinksFelder[0], "Testmedikament");
  setze(medLinksFelder[1], "10 mg");
  medZeileLinks.querySelector(".gesundheit-suchknopf").click();
  assert.ok(enSyncNachrichten.some((nachricht) =>
    nachricht.cmd === "medikament_suchen" && nachricht.name === "Testmedikament"),
  "die feste Online-Medikamentensuche erreicht die Bridge nicht");
  const medRechtsFelder = enSD.querySelector(".medikament-rechts tbody tr").querySelectorAll("input");
  setze(medRechtsFelder[0], "1");
  setze(medRechtsFelder[4], "1");
  setze(medRechtsFelder[5], "Tablette");
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Save").click();
  assert.strictEqual(enST.daten().gesundheit.medikamente[0].name, "Testmedikament",
    "Medikamentenzeile wird nicht gespeichert");
  assert.ok(!enST.gesundheitsMarkenAm(enST.isoHeute()).some((marke) => marke.art === "medikamente"),
    "Medikamentenplan erscheint trotz abgeschalteter Kalenderplanung im Kalender");
  const medVor = Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
    .find((button) => button.textContent === "›");
  assert.ok(medVor && medVor.disabled,
    "eine unvollständige Medikamentenseite gibt bereits ein leeres Folgeblatt frei");
  Array.from(enSD.querySelectorAll(".medikament-links tbody tr")).slice(1)
    .forEach((zeile, index) => setze(zeile.querySelector("input"), "Testmedikament " + (index + 2)));
  enST.aktualisiereGesundheitReserve();
  assert.ok(!medVor.disabled, "eine maximal belegte Medikamentenseite gibt kein Folgeblatt frei");
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Save").click();
  const medVorVoll = Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
    .find((button) => button.textContent === "›");
  medVorVoll.click();
  assert.ok(enSD.querySelector(".gesundheit-seitennummer").textContent.includes("2") &&
    !Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
      .find((button) => button.textContent === "‹").disabled,
  "die neue Medikamentenseite besitzt keinen Rückweg");
  setze(enSD.querySelector(".medikament-links tbody tr input"), "Medikament auf Seite 2");
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Save").click();
  assert.ok(enST.daten().gesundheit.medikamente.some((mittel) =>
    mittel.name === "Medikament auf Seite 2" && mittel.seite === 1),
  "die neue Medikamentenseite wird nicht dauerhaft getrennt gespeichert");
  Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
    .find((button) => button.textContent === "‹").click();
  Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
    .find((button) => button.textContent === "›").click();
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Delete entries…").click();
  const loeschblatt = enSD.querySelector(".gesundheit-loeschblatt");
  assert.ok(loeschblatt && loeschblatt.querySelectorAll(".gesundheit-loeschliste input").length === 1,
    "gespeicherte Gesundheitseinträge lassen sich nicht einzeln auswählen");
  Array.from(loeschblatt.querySelectorAll("button"))
    .find((button) => button.textContent === "Delete page").click();
  enSD.querySelector("#dialog-ja").click();
  await tick();
  assert.ok(!enST.daten().gesundheit.medikamente.some((mittel) =>
    mittel.name === "Medikament auf Seite 2") &&
    enSD.querySelector(".gesundheit-seitennummer").textContent.includes("1"),
  "eine vollständige Medikamentenseite wird nicht gelöscht oder Seiten rücken nicht nach");
  Array.from(enSD.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === "Blood glucose table").click();
  assert.strictEqual(enSD.querySelectorAll(".blutzucker-tabelle").length, 1,
    "der Organizer zeigt rechts fälschlich eine zweite Blutzuckertabelle");
  assert.strictEqual(enSD.querySelectorAll(".blutzucker-tabelle tbody tr").length, 18,
    "die linke Blutzuckertabelle nutzt die Buchseite nicht vollständig");
  const zuckerTabelle = enSD.querySelector(".blutzucker-tabelle");
  simuliereTabellenmasse(zuckerTabelle);
  simuliereHoehe(zuckerTabelle.parentElement, 244);
  enST.aktualisiereGesundheitReserve();
  assert.strictEqual(sichtbareZeilen(zuckerTabelle).length, 6,
    "die linke Blutzuckertabelle reagiert nicht auf eine kleine verfügbare Höhe");
  assert.ok(enSD.querySelector("#inhalt-rechts .gesundheit-insulinschema") &&
    !enSD.querySelector("#inhalt-rechts .blutzucker-tabelle"),
  "die rechte Organizerseite ist nicht ausschließlich dem Insulinschema vorbehalten");
  assert.ok(enSD.querySelector("#inhalt-links .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-rechts .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-rechts .einst-warnung"),
  "der neutrale Blutzuckerhinweis steht nicht ausschließlich auf der linken Seite");
  assert.ok(enSD.querySelector("#inhalt-rechts.gesundheit-seite-mit-aktionen") &&
    enSD.querySelector("#inhalt-rechts > .gesundheit-tabellenaktionen"),
  "Speichern und Verwerfen bleiben beim Scrollen nicht sichtbar");
  const zuckerZeile = enSD.querySelector(".blutzucker-tabelle tbody tr");
  const zuckerFelder = zuckerZeile.querySelectorAll("input");
  enST.setzeDatumswert(zuckerFelder[0], enST.isoHeute());
  zuckerFelder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const zuckerEinheit = zuckerZeile.querySelector("select");
  zuckerEinheit.value = "mmol/L";
  zuckerEinheit.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  setze(zuckerFelder[2], "5,5");
  assert.ok(zuckerFelder[2].type === "text" &&
    zuckerFelder[2].classList.contains("gesundheit-ampel-gruen") &&
    enST.parseGesundheitsZahl("5,5") === 5.5,
  "Blutzucker akzeptiert kein Dezimalkomma oder zeigt keine grüne Referenzampel");
  zuckerFelder[2].dispatchEvent(new enSW.WheelEvent("wheel", { deltaY: 100, bubbles: true }));
  assert.strictEqual(zuckerFelder[2].value, "5.4",
    "Blutzucker lässt sich nicht ohne Pfeiltasten per Mausrad ändern");
  zuckerEinheit.value = "mg/dL";
  zuckerEinheit.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  zuckerFelder[2].dispatchEvent(new enSW.WheelEvent("wheel", { deltaY: 100, bubbles: true }));
  assert.strictEqual(zuckerFelder[2].value, "96",
    "Blutzucker in mg/dL wird per Mausrad nicht in ganzen Einheiten geändert");
  zuckerEinheit.value = "mmol/L";
  zuckerEinheit.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  setze(zuckerFelder[2], "6.4");
  assert.ok(zuckerFelder[2].classList.contains("gesundheit-ampel-orange"),
    "Blutzucker außerhalb des grünen Referenzbereichs wird nicht orange markiert");
  setze(zuckerFelder[3], "4");
  zuckerFelder[3].dispatchEvent(new enSW.WheelEvent("wheel", { deltaY: 100, bubbles: true }));
  assert.strictEqual(zuckerFelder[3].value, "3.5",
    "Insulineinheiten werden per Mausrad nicht in halben Einheiten geändert");
  setze(zuckerFelder[3], "4");
  const schemaFelder = enSD.querySelectorAll(".gesundheit-insulinschema input");
  assert.ok(Array.from(enSD.querySelectorAll("#gesundheit-insulin-vorschlaege-langzeit option"))
    .some((option) => option.value === "Lantus") &&
    Array.from(enSD.querySelectorAll("#gesundheit-insulin-vorschlaege-kurzzeit option"))
      .some((option) => option.value === "Actrapid"),
  "frei editierbare Vorschläge für Lang- und Kurzzeitinsulin fehlen");
  schemaFelder[0].click();
  setze(schemaFelder[1], "6");
  const insulinModi = enSD.querySelectorAll(".gesundheit-insulinart select");
  insulinModi[1].value = "scheme";
  insulinModi[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  const kurzzeitBlock = enSD.querySelectorAll(".gesundheit-insulinart")[1];
  Array.from(kurzzeitBlock.querySelectorAll("button"))
    .find((button) => button.textContent.includes("Add scheme row")).click();
  const schemaZeile = kurzzeitBlock.querySelector(".gesundheit-schema-zeile");
  const schemaAuswahl = schemaZeile.querySelectorAll("select");
  const schemaZahlen = schemaZeile.querySelectorAll("input");
  schemaAuswahl[0].value = ">";
  schemaAuswahl[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  schemaAuswahl[1].value = "-";
  schemaAuswahl[1].dispatchEvent(new enSW.Event("change", { bubbles: true }));
  setze(schemaZahlen[0], "5");
  setze(schemaZahlen[1], "2");
  assert.ok(enSD.querySelector("#gesundheit-schema-treffer").textContent.includes("> 5 mmol/L") &&
    enSD.querySelector("#gesundheit-schema-treffer").textContent.includes("4 IE (6 - 2)"),
  "passende benutzerdefinierte Insulinschemazeile wird nicht angezeigt: " +
    enSD.querySelector("#gesundheit-schema-treffer").textContent);
  Array.from(enSD.querySelectorAll(".gesundheit-tabellenaktionen button"))
    .find((button) => button.textContent === "Save").click();
  assert.ok(enST.daten().gesundheit.blutzucker[0].wert === 6.4 &&
    enST.daten().gesundheit.blutzucker[0].ie === 4 &&
    enST.daten().gesundheit.insulinschema.basisAn &&
    enST.daten().gesundheit.insulinschema.basisEinheiten === 6 &&
    enST.daten().gesundheit.insulinschema.kurzzeitRegeln[0].vergleich === ">",
  "Blutzuckerzeile oder Basiseinheiten werden nicht gespeichert");
  const zuckerVor = Array.from(enSD.querySelectorAll(".gesundheit-seitenpfeil"))
    .find((button) => button.textContent === "›");
  assert.ok(zuckerVor && zuckerVor.disabled,
    "eine unvollständige Blutzuckerseite gibt bereits ein leeres Folgeblatt frei");
  const zuckerZeilen = Array.from(enSD.querySelectorAll(".blutzucker-tabelle tbody tr"));
  zuckerZeilen.slice(1).forEach((zeile, index) => {
    const felder = zeile.querySelectorAll("input");
    enST.setzeDatumswert(felder[0], enST.isoHeute());
    felder[0].dispatchEvent(new enSW.Event("change", { bubbles: true }));
    setze(felder[2], String(5 + index / 10));
  });
  enST.aktualisiereGesundheitReserve();
  assert.ok(!zuckerVor.disabled, "eine maximal belegte Blutzuckerseite gibt kein Folgeblatt frei");
  zuckerZeilen.slice(1).forEach((zeile) => {
    setze(zeile.querySelectorAll("input")[0], "");
    setze(zeile.querySelectorAll("input")[2], "");
  });
  enST.aktualisiereGesundheitReserve();
  assert.ok(zuckerVor.disabled &&
    enSD.querySelector(".gesundheit-seitennummer").textContent.includes("1"),
  "nach geleerten Reservezeilen bleibt die Blutzuckerseite instabil oder vorwärts freigegeben");
  const gesundheitsDruck = enST.oeffneDruckvorschau(null, "gesundheit");
  assert.ok(gesundheitsDruck.querySelector(".gesundheit-druck-optionen") &&
    gesundheitsDruck.querySelectorAll(".gesundheit-druck-optionen input[type=radio]").length === 4 &&
    gesundheitsDruck.querySelectorAll(".gesundheit-druck-optionen input[type=checkbox]").length === 1 &&
    gesundheitsDruck.querySelector(".ods-knopf"),
  "Gesundheitsauswahl bietet nicht Tabellen, Schema, Verlauf, Vorlage und ODS gemeinsam an");
  assert.ok(gesundheitsDruck.querySelector(".gesundheit-druck-seite-vorschau table"),
  "der Gesundheitsdruck zeigt keine echte A4-Seitenvorschau");
  const druckHaken = Array.from(gesundheitsDruck.querySelectorAll(
    ".gesundheit-druck-optionen label.hak"));
  const zuckerHaken = druckHaken.find((label) => label.textContent.includes("Blood glucose table"));
  const schemaHaken = druckHaken.find((label) => label.textContent.trim() === "Insulin scheme");
  assert.ok(zuckerHaken && schemaHaken && druckHaken.indexOf(schemaHaken) ===
    druckHaken.indexOf(zuckerHaken) + 1 && schemaHaken.style.display !== "none",
  "Insulinschema steht im Druckdialog nicht direkt unter der Blutzuckertabelle");
  const vitalHaken = druckHaken.find((label) => label.textContent.includes("Vital signs table"));
  vitalHaken.querySelector("input").click();
  assert.ok(gesundheitsDruck.querySelectorAll(
    ".gesundheit-druck-optionen input[type=radio]:checked").length === 1 &&
    schemaHaken.style.display === "none",
  "Vitalwerte, Medikamentenplan und Blutzucker sind nicht exklusiv auswählbar");
  const keineTabelleHaken = druckHaken.find((label) => label.textContent.includes("history only"));
  keineTabelleHaken.querySelector("input").click();
  const verlaufWahl = Array.from(gesundheitsDruck.querySelectorAll("select"))
    .find((feld) => Array.from(feld.options).some((option) => option.value === "all"));
  verlaufWahl.value = "all";
  verlaufWahl.dispatchEvent(new enSW.Event("change", { bubbles: true }));
  assert.ok(gesundheitsDruck.querySelectorAll(".gesundheit-druck-seite-vorschau table").length === 0 &&
    gesundheitsDruck.querySelectorAll(".gesundheit-druck-seite-vorschau .diagramm").length === 6,
  "nur die sechs Verläufe lassen sich nicht ohne Gesundheitstabelle auswählen");
  zuckerHaken.querySelector("input").click();
  assert.notStrictEqual(schemaHaken.style.display, "none",
    "Insulinschema erscheint bei gewählter Blutzuckertabelle nicht");
  const vitalDruck = enST.gesundheitDruckSeite({ leer: true, vital: true,
    blutzucker: false, medikamente: false, verlauf: "none" });
  assert.ok(vitalDruck.includes("size:A4 landscape") &&
    vitalDruck.includes("class='haelften'") &&
    (vitalDruck.match(/<tbody><tr>/g) || []).length === 2 &&
    (vitalDruck.match(/<tr>/g) || []).length >= 42 && !vitalDruck.includes("Blood glucose"),
  "Vitalwertvorlage wird nicht doppelseitig auf A4 quer aufgebaut");
  const ausgewaehltesMedikament = Object.assign({ _gesundheitArt: "medikamente" },
    enST.daten().gesundheit.medikamente[0]);
  const auswahlDruck = enST.gesundheitDruckSeite(false, [ausgewaehltesMedikament]);
  assert.ok(auswahlDruck.includes("Testmedikament") && auswahlDruck.includes("Medication plan") &&
    !auswahlDruck.includes("Vital signs") && !auswahlDruck.includes("Blood glucose table"),
  "die allgemeine Gesundheitsdruckauswahl ignoriert den gewählten Datensatztyp");
  const zuckerDruck = enST.gesundheitDruckSeite({ leer: true, vital: false,
    blutzucker: true, schema: true, medikamente: false, verlauf: "none" });
  assert.ok(zuckerDruck.indexOf("<table") < zuckerDruck.indexOf("Insulin scheme") &&
    zuckerDruck.includes("Insulin scheme") && (zuckerDruck.match(/<table/g) || []).length === 1,
  "das Insulinschema ersetzt im Druck nicht die rechte Blutzuckertabelle");
  const schemaOds = enST.gesundheitOdsNutzlast({ leer: false, vital: false,
    blutzucker: true, schema: true, medikamente: false }, [Object.assign({
      _gesundheitArt: "blutzucker" }, enST.daten().gesundheit.blutzucker[0])]);
  assert.ok(schemaOds.tabellen[0].links.length === 6 &&
    schemaOds.tabellen[0].rechtsTitel === "Insulin scheme" &&
    schemaOds.tabellen[0].rechts.join("|").includes("Blood glucose scheme") &&
    schemaOds.tabellen[0].rechts.join("|") !== schemaOds.tabellen[0].links.join("|") &&
    schemaOds.tabellen[0].zeilen.some((zeile) => zeile.includes("4 (6 - 2)")),
  "das Insulinschema ersetzt in der ODS nicht die rechte Blutzuckertabelle");
  const verlaufOds = enST.gesundheitOdsNutzlast({ leer: false, vital: false,
    blutzucker: false, medikamente: false, verlauf: "all", verlaufWert: "blood-pressure" },
  enST.gesundheitDruckEintraege({ leer: false, vital: false, blutzucker: false,
    medikamente: false, verlauf: "all", verlaufWert: "blood-pressure", von: "", bis: "" }));
  assert.ok(verlaufOds.cmd === "gesundheit_ods" && verlaufOds.tabellen.length === 1 &&
    verlaufOds.tabellen[0].diagramme.length === 6 &&
    verlaufOds.tabellen[0].diagramme.find((diagramm) => diagramm.titel === "Blood glucose")
      .serien.some((serie) => serie.punkte.some((punkt) => Math.abs(punkt[1] - 6.4) < 0.01)),
  "ODS für die sechs Verläufe übernimmt nicht alle Messwertarten als Diagrammraster");
  assert.ok(Math.abs(enST.gesundheitBlutzuckerMmol(
    { wert: 180.182, einheit: "mg/dL" }) - 10) < 0.001 &&
    enST.gesundheitBlutzuckerMmol({ wert: 5.5, einheit: "mmol/L" }) === 5.5,
  "gemischte Blutzuckereinheiten werden für Verlaufsdiagramme nicht vereinheitlicht");
  const einzelVerlaufOds = enST.gesundheitOdsNutzlast({ leer: false, vital: false,
    blutzucker: false, medikamente: false, verlauf: "single", verlaufWert: "blood-pressure" },
  enST.gesundheitDruckEintraege({ leer: false, vital: false, blutzucker: false,
    medikamente: false, verlauf: "single", verlaufWert: "blood-pressure", von: "", bis: "" }));
  assert.ok(einzelVerlaufOds.tabellen.length === 1 &&
    einzelVerlaufOds.tabellen[0].links[0] === "Date" &&
    einzelVerlaufOds.tabellen[0].rechts.length === 1 &&
    einzelVerlaufOds.tabellen[0].diagramm.serien.length === 2,
  "ein einzelner ODS-Verlauf besteht nicht aus Messwertliste und Diagramm");
  const diagrammDruck = enST.gesundheitDruckSeite({ leer: false, vital: false,
    blutzucker: false, medikamente: false, verlauf: "all" });
  assert.strictEqual((diagrammDruck.match(/<div class='diagramm'>/g) || []).length, 6,
    "Druckauswahl erzeugt nicht alle sechs Verlaufsdiagramme im A4-Raster");
  gesundheitsDruck.querySelector("header button").click();
  Array.from(enSD.querySelectorAll(".gesundheit-symbolknopf"))
    .find((button) => button.title === "History").click();
  const verlaufSvg = enSD.querySelector(".gesundheit-verlauf-diagramm svg");
  const verlaufRahmen = verlaufSvg.querySelector(".gesundheit-diagramm-rahmen");
  assert.ok(verlaufRahmen && verlaufSvg.lastElementChild === verlaufRahmen &&
    Array.from(verlaufSvg.querySelectorAll("circle")).every((punkt) =>
      Number(punkt.getAttribute("cx")) > 38 && Number(punkt.getAttribute("cx")) < 428 &&
      Number(punkt.getAttribute("cy")) > 40 && Number(punkt.getAttribute("cy")) < 210),
  "der Verlaufsrahmen wird weiterhin von Randpunkten optisch geöffnet");
  assert.ok(enSD.querySelector("#inhalt-links .gesundheit-referenzhinweis") &&
    !enSD.querySelector("#inhalt-links .einst-warnung"),
  "der Verlaufshinweis verwendet nicht die neutrale Referenzgestaltung");
  assert.ok(/body\[data-hilfsrahmen="an"\] \.gesundheit-verlauf-steuerung :focus-visible\s*\{[^}]*outline-offset:\s*-3px/.test(css),
    "der Barrierefreiheitsrahmen im linken Verlauf wird weiterhin abgeschnitten");
  enST.wechsel("kalender");
  enST.oeffneTerminBlatt(null, "2026-08-03");
  assert.ok(enSD.querySelector("#tb-schicht") &&
    enSD.querySelector(".tb-marken-zeile .sinnbild") &&
    enSD.querySelector(".zyklus-schnellknopf"),
  "Aktenkoffer- oder Zyklusschnellwahl fehlt im neuen Terminblatt");
  enSD.querySelector("#tb-datum-bis").value = "2026-08-05";
  enSD.querySelector("#tb-datum-bis").dispatchEvent(
    new enSW.Event("input", { bubbles: true }));
  enSD.querySelector("#tb-datum-bis").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  enSD.querySelector("#tb-schicht").value = enST.daten().schichten[0].id;
  enSD.querySelector("#tb-schicht").dispatchEvent(
    new enSW.Event("change", { bubbles: true }));
  enSD.querySelector(".zyklus-schnellknopf").click();
  assert.ok(Array.from(enSD.querySelectorAll(".zyklus-schnellknopf")).every(
    (button) => Number.parseFloat(button.style.fontSize) <= 16),
  "mehrteilige Zyklussymbole werden nicht an den runden Schalter angepasst");
  const enBereich = enST.daten().tagmarken.filter((marke) =>
    marke.datum >= "2026-08-03" && marke.datum <= "2026-08-05");
  assert.ok(enBereich.length === 3 && enBereich.every((marke) =>
    marke.schichtId === enST.daten().schichten[0].id &&
    marke.zyklusIds.includes(enST.daten().zyklusmarker[0].id)),
  "Schicht und Zyklusmarkierung werden nicht dem gesamten Datumsbereich zugewiesen");
  enSD.querySelector("#termin-schleier header button").click();
  enST.zustand().kalender.jahr = 2026;
  enST.zustand().kalender.monat = 7;
  enST.zustand().kalender.tag = "2026-08-03";
  enST.wechsel("aufgaben");
  enST.wechsel("kalender");
  assert.ok(enSD.querySelector(".schicht-marke") &&
    enSD.querySelector(".zyklus-marke") && enSD.querySelector(".urlaub-marke") &&
    enSD.querySelector(".muell-marke .sinnbild") &&
    !enSD.querySelector(".tagmarken-streifen.kompakt[style*='position']"),
  "Schicht, Zyklus, Urlaub oder Müllabholung fehlt im kollisionsfreien Monatskalender");
  enSyncDom.window.close();

  enT.wechsel("jahrestage");
  assert.strictEqual(enD.querySelector("#kopf-links h2").textContent, "Anniversaries",
    "englische Jahrestagsüberschrift fehlt");
  assert.strictEqual(enD.querySelector("#kopf-rechts h2").textContent,
    "New anniversary", "englischer Jahrestagskopf fehlt");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll("#inhalt-rechts .feldname"),
    (label) => label.textContent), ["Name / occasion", "Date", "Type"],
  "englische Jahrestagsbeschriftungen fehlen");
  assert.strictEqual(enD.querySelector("#jt-typ").placeholder, "e.g. Birthday",
    "englischer Jahrestagsplatzhalter fehlt");
  assert.ok(Array.from(enD.querySelector("#jt-typen-vorschlaege").options,
    (option) => option.value).includes("Death anniversary"),
  "englische Jahrestagsarten fehlen");
  const enHeute = new Date();
  const enGeburtstag = enHeute.getFullYear() - 30 + "-" +
    String(enHeute.getMonth() + 1).padStart(2, "0") + "-" +
    String(enHeute.getDate()).padStart(2, "0");
  enT.daten().jahrestage.push(
    { id: "english-birthday", name: "Alice", datum: enGeburtstag, typ: "Birthday" },
    { id: "historic-death", name: "Großvater", datum: "1987-04-03", typ: "Todestag" },
    { id: "custom-anniversary", name: "Eigene Feier", datum: "2000-02-03",
      typ: "Familientag" });
  enT.wechsel("kalender");
  enT.wechsel("jahrestage");
  assert.ok(enD.querySelector("#inhalt-links").textContent.includes("today!") &&
    enD.querySelector("#inhalt-links").textContent.includes("turns 30"),
  "englischer Jahrestagsabstand oder Alterstext fehlt");
  assert.ok(enD.querySelector("#inhalt-links").textContent.includes("Großvater") &&
    enD.querySelector("#inhalt-links").textContent.includes("Death anniversary") &&
    enD.querySelector("#inhalt-links").textContent.includes("Familientag"),
  "historische Standardarten oder freie Jahrestagsdaten werden falsch dargestellt");
  const enHistorisch = Array.from(enD.querySelectorAll("#inhalt-links .zeile"))
    .find((row) => row.textContent.includes("Großvater"));
  assert.strictEqual(enHistorisch.querySelector(".loesch-x").title,
    "Delete anniversary", "englischer Jahrestags-Löschhinweis fehlt");
  enHistorisch.querySelector(".loesch-x").click();
  assert.strictEqual(enD.querySelector("#dialog-text").textContent,
    "Delete anniversary “Großvater”?", "englischer Jahrestags-Löschdialog fehlt");
  enD.querySelector("#dialog-nein").click();
  enT.oeffneDruckvorschau(null, "jahrestage");
  assert.strictEqual(enD.querySelector(".druck-blatt h2").textContent,
    "Print · Anniversaries", "englischer Jahrestagsdruckkopf fehlt");
  assert.ok(enD.querySelector(".druck-vorschau").textContent.includes("Großvater") &&
    enD.querySelector(".druck-vorschau").textContent.includes("Death anniversary"),
  "Jahrestagsdaten fehlen im englischen Druck");
  enD.querySelector("#druck-schleier").remove();
  const enPlanerJahr = enT.zustand().planer.jahr + 1;
  enT.zustand().planer.jahr = enPlanerJahr;
  enT.daten().einstellungen.kalender.vergangeneTermine = true;
  enT.daten().termine.push(
    { id: "planner-multi-day", datum: enPlanerJahr + "-02-10",
      endDatum: enPlanerJahr + "-02-12", zeit: "", endZeit: "", titel: "Multi-day" },
    { id: "planner-recurring", datum: (enPlanerJahr - 2) + "-01-01", endDatum: "",
      zeit: "", endZeit: "", titel: "Recurring", wiederholung: { art: "custom",
        daten: [enPlanerJahr + "-06-15"] } });
  enT.planeSpeichern();
  enT.wechsel("planer");
  assert.strictEqual(enD.querySelector("#kopf-links h2").textContent,
    "Year planner " + enPlanerJahr, "englische Planerüberschrift fehlt");
  assert.strictEqual(enD.querySelector("#kopf-links .kopf-neben").textContent,
    "January – June", "englisches erstes Halbjahr fehlt");
  assert.strictEqual(enD.querySelector("#kopf-rechts .kopf-neben").textContent,
    "July – December", "englisches zweites Halbjahr fehlt");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(".mm-titel"),
    (element) => element.textContent),
  ["January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December"],
  "englische Planermonate fehlen");
  assert.deepStrictEqual(Array.from(enD.querySelector(".mini-monat")
    .querySelectorAll(".mm-wt"), (element) => element.textContent),
  ["M", "T", "W", "T", "F", "S", "S"], "englische Wochentage fehlen");
  const enJahrPfeile = enD.querySelectorAll("#kopf-links .pfeil");
  assert.strictEqual(enJahrPfeile[0].title, "Previous year");
  assert.strictEqual(enJahrPfeile[1].title, "Next year");
  assert.strictEqual(enD.querySelector("#ecke-links").title, "Previous year");
  assert.strictEqual(enD.querySelector("#ecke-rechts").title, "Next year");
  for (const iso of [enPlanerJahr + "-02-10", enPlanerJahr + "-02-11",
    enPlanerJahr + "-02-12", enPlanerJahr + "-06-15"]) {
    assert.ok(enD.querySelector('[data-fokus="planer-tag:' + iso + '"]').classList.contains("hat"),
      "Jahresplaner markiert Mehrtagstermin oder Serienvorkommen nicht: " + iso);
  }
  enButton("Choose year…").click();
  assert.strictEqual(enD.querySelector("#eingabe-titel").textContent,
    "Open year in planner", "englischer Jahresdialog fehlt");
  assert.strictEqual(enD.querySelector("#eingabe-schleier .feldname").textContent,
    "Year", "englische Jahresbeschriftung fehlt");
  enD.querySelector("#eingabe-feld").value = "999";
  enButton("Open year", enD.querySelector("#eingabe-schleier")).click();
  assert.strictEqual(enD.querySelector("#eingabe-fehler").textContent,
    "Please enter a four-digit year from 1000 onwards.",
  "englische Jahresvalidierung fehlt");
  enButton("Cancel", enD.querySelector("#eingabe-schleier")).click();
  enT.daten().einstellungen.kalender.planerWochenNummern = true;
  enT.daten().termine.push({ id: "planner-print-en", datum: enPlanerJahr + "-08-03",
    endDatum: "", zeit: "", endZeit: "", titel: "Untranslated user title",
    kategorien: "Eigene Kategorie", notiz: "Eigene Notiz" });
  enT.wechsel("kalender");
  enT.wechsel("planer");
  assert.strictEqual(enD.querySelector("#knopf-drucken").textContent, "Print",
    "im Planer heißt die allgemeine Auswahl weiterhin Auswahloptionen");
  assert.strictEqual(enD.querySelector("#knopf-drucken").title,
    "Preview, print or export the year planner",
    "englischer Hinweis für den Planerdruck fehlt");
  assert.strictEqual(enD.querySelector(".mm-kw-kopf").textContent, "CW",
    "englischer Wochennummernkopf fehlt");
  assert.match(enD.querySelector(".mm-kw").title, /^Calendar week \d+$/);
  enT.oeffneDruckvorschau(null, "planer");
  assert.strictEqual(enD.querySelector(".druck-blatt h2").textContent,
    "Print · Year planner " + enPlanerJahr, "englischer Planerdruckkopf fehlt");
  assert.ok(enD.querySelector(".planer-druck-kalender") &&
    !enD.querySelector(".druck-zeile") && !enD.querySelector(".druck-wahlkopf"),
  "englischer Planerdruck ist weiterhin eine Terminauswahl");
  const enPlanerHtml = enT.planerDruckSeite(enT.planerKalenderModell(enPlanerJahr));
  assert.ok(enPlanerHtml.includes("size: A4 landscape") &&
    enPlanerHtml.includes("<table>") && !enPlanerHtml.includes("Untranslated user title"),
  "Planerdruck ist nicht als eigenständiger Jahreskalender im Querformat aufgebaut");
  enD.querySelector("#druck-schleier").remove();
  enT.wechsel("notizen");
  assert.strictEqual(enD.querySelector("#kopf-links h2").textContent, "Notes",
    "englische Notizüberschrift fehlt");
  assert.strictEqual(enD.querySelector("#kopf-rechts h2").textContent,
    "Writing sheet", "englischer Schreibblattkopf fehlt");
  assert.ok(enButton("New page") && enButton("New notebook") &&
    enButton("New group") && enButton("Customize"),
  "englische Notizstrukturknöpfe fehlen");
  assert.strictEqual(enD.querySelector("#notiz-suche").placeholder, "Search",
    "englische Notizsuche fehlt");
  assert.strictEqual(enD.querySelector("#notiz-titel").placeholder, "Heading",
    "englischer Notiztitelplatzhalter fehlt");
  assert.strictEqual(enD.querySelector("#notiz-text").getAttribute("aria-label"),
    "Note text", "englische Schreibflächenbeschriftung fehlt");
  assert.strictEqual(enD.querySelector("#notiz-text").dataset.placeholder,
    "Write here …", "englischer Schreibflächenplatzhalter fehlt");
  assert.strictEqual(enD.querySelector(".notiz-gruppe-name").textContent, "General",
    "englische Standardgruppe fehlt");
  assert.strictEqual(enD.querySelector(".notizbuch-name").textContent, "Loose Notes",
    "englisches Standardnotizbuch fehlt");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(".werkzeug-knopf"),
    (button) => button.textContent), ["B", "I", "U", "S"],
  "englische Auszeichnungszeichen fehlen");
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(".werkzeug-knopf"),
    (button) => button.getAttribute("aria-label")),
  ["Bold", "Italic", "Underline", "Strikethrough"],
  "englische Auszeichnungsnamen fehlen");
  const enEinfuegen = enD.querySelector(".notiz-einfuegen");
  assert.strictEqual(enEinfuegen.getAttribute("aria-label"), "Embed links and files",
    "englische Einbettungsbeschriftung fehlt");
  enButton("Link", enEinfuegen).click();
  assert.strictEqual(enD.querySelector("#eingabe-titel").textContent, "Insert link");
  assert.strictEqual(enD.querySelector("#eingabe-schleier .eingabe-hinweis").textContent,
    "Enter a web or email address.");
  enD.querySelector("#eingabe-feld").value = "";
  enButton("Insert link", enD.querySelector("#eingabe-schleier")).click();
  assert.strictEqual(enD.querySelector("#eingabe-fehler").textContent,
    "Please enter an address.", "englische Linkvalidierung fehlt");
  enButton("Cancel", enD.querySelector("#eingabe-schleier")).click();
  enButton("Image", enEinfuegen).click();
  assert.strictEqual(enD.querySelector("#eingabe-titel").textContent, "Embed image");
  assert.strictEqual(enD.querySelector("#eingabe-schleier .eingabe-datei-knopf").textContent,
    "Choose file…", "englische Dateiauswahl fehlt");
  assert.strictEqual(enD.querySelector("#eingabe-schleier .eingabe-dateiname").textContent,
    "No file selected", "englischer leerer Dateiname fehlt");
  enButton("Embed", enD.querySelector("#eingabe-schleier")).click();
  assert.strictEqual(enD.querySelector("#eingabe-fehler").textContent,
    "Please select a file first.", "englische Dateivalidierung fehlt");
  enButton("Cancel", enD.querySelector("#eingabe-schleier")).click();
  enT.daten().notizen[0].anhaenge.push(
    { id: "image-en", name: "User image.png", art: "bild",
      daten: "data:image/png;base64,iVBORw0KGgo=" },
    { id: "pdf-en", name: "User document.pdf", art: "pdf",
      daten: "data:application/pdf;base64,JVBERi0xLjQ=" },
    { id: "image-empty-en", name: "", art: "bild",
      daten: "data:image/png;base64,iVBORw0KGgo=" },
    { id: "pdf-empty-en", name: "", art: "pdf",
      daten: "data:application/pdf;base64,JVBERi0xLjQ=" });
  enT.wechsel("kalender");
  enT.wechsel("notizen");
  assert.strictEqual(enD.querySelector(".notiz-anhaenge h3").textContent,
    "Embedded files", "englische Anhangsüberschrift fehlt");
  assert.strictEqual(enD.querySelector(".notiz-anhang-teiler").title,
    "Drag the attachment area up or down");
  assert.ok(Array.from(enD.querySelectorAll(".notiz-anhang-symbol"), (link) => link.title)
    .includes("Open User image.png"), "englischer Öffnen-Text fehlt");
  assert.ok(Array.from(enD.querySelectorAll(".notiz-anhang-symbol"), (link) => link.title)
    .includes("Open Image") &&
    Array.from(enD.querySelectorAll(".notiz-anhang-name"), (link) => link.textContent)
      .includes("Document.pdf") &&
    Array.from(enD.querySelectorAll(".notiz-anhang figcaption"), (caption) => caption.textContent)
      .some((text) => text.startsWith("Document.pdf")),
  "englische Namen für namenlose Anhänge sind uneinheitlich");
  assert.ok(enButton("Remove", enD.querySelector(".notiz-anhaenge")),
    "englische Anhangsentfernung fehlt");
  const enTitelFeld = enD.querySelector("#notiz-titel");
  enTitelFeld.setSelectionRange(0, enTitelFeld.value.length);
  enTitelFeld.dispatchEvent(new enDom.window.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 80, clientY: 80 }));
  assert.deepStrictEqual(Array.from(enD.querySelectorAll(
    "#vorschlags-menue .vm-eintrag"), (button) => button.textContent),
  ["Cut", "Copy", "Paste", "Select all"],
  "englisches Bearbeitungsmenü ist unvollständig");
  enD.querySelector("#vorschlags-menue").remove();
  enButton("Customize").click();
  assert.strictEqual(enD.querySelector("#notiz-anpassen-titel").textContent,
    "Customize notebooks", "englische Notizverwaltung fehlt");
  assert.ok(enButton("Sort everything alphabetically",
    enD.querySelector("#notiz-anpassen-schleier")) &&
    enButton("Done", enD.querySelector("#notiz-anpassen-schleier")),
  "englische Verwaltungsaktionen fehlen");
  enButton("Done", enD.querySelector("#notiz-anpassen-schleier")).click();
  enT.oeffneDruckvorschau(enT.daten().notizen[0], "notizen");
  assert.strictEqual(enD.querySelector(".druck-blatt h2").textContent,
    "Print · Notes", "englischer Notizdruckkopf fehlt");
  assert.strictEqual(enD.querySelector(".druck-titel").textContent, "Pages",
    "englische Notizdruckauswahl fehlt");
  assert.ok(enD.querySelector(".druck-vorschau").textContent.includes("Welcome") &&
    !enD.querySelector(".druck-vorschau").textContent.includes("Willkommen"),
  "englische Willkommensnotiz fehlt in der Druckvorschau");
  enDom.window.MagnolieI18n.setLocale("de");
  assert.ok(enT.daten().notizen[0].titel.includes("Welcome"),
    "gespeicherte Willkommensnotiz wurde beim Sprachwechsel verändert");
  enD.querySelector("#druck-schleier").remove();
  enDom.window.close();

  const enNotbremseDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://organizer-fallback-en.test/",
    pretendToBeVisual: true
  });
  const enNotbremseBefehle = [];
  enNotbremseDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => enNotbremseBefehle.push(JSON.parse(text))
  } } };
  ladeAnwendung(enNotbremseDom.window, "en");
  await new Promise((r) => setTimeout(r, 2600));
  assert.strictEqual(enNotbremseDom.window.document.querySelector("#zettel").textContent,
    "Notice: The connection to storage was not confirmed.",
  "englische Notbremse bei ausbleibender Speicherantwort fehlt");
  assert.ok(enNotbremseBefehle.some((befehl) => befehl.cmd === "bereit") &&
    enNotbremseBefehle.some((befehl) => befehl.cmd === "baum_stand"),
  "Notbremse verändert die Bridge-Befehle");
  enNotbremseDom.window.close();

  assert.ok(T.daten().notizen[0].titel.includes("Willkommen") &&
    T.daten().notizen[0].text.includes("Schön, dass Sie da sind!"),
  "deutsche Willkommensnotiz fehlt");

  assert.ok($("#buch").classList.contains("geschlossen"));
  $("#deckel").click();
  assert.ok($("#buch").classList.contains("offen"), "Buch öffnet nicht");

  assert.strictEqual($$(".registerknopf").length, 7, "7 Registerzungen erwartet");
  assert.strictEqual($$("#register-links .registerknopf").length, 0, "Start: links leer");
  assert.ok($("#kopf-links h2"), "Kopfzeile fehlt");
  assert.ok($$(".wo-tag").length === 7, "die voreingestellte Woche hat keine 7 Tage");
  assert.strictEqual($$(".kal-kw").length, 0,
    "Wochennummern müssen voreingestellt ausgeblendet sein");
  assert.ok($("#status-datum").textContent.includes("Heute ist"));

  /* ---- Kalender: drei Ansichten ---- */
  const umschalter = $$("#ansicht-umschalter .u-knopf").map((b) => b.dataset.ansicht);
  assert.deepStrictEqual(umschalter, ["month", "week", "day"],
    "Monat, Woche und Tag erwartet");
  assert.ok($("#ansicht-umschalter .u-zeichen"),
    "die Umschalter tragen keine Sinnbilder");

  /* ---- Termin über das Terminblatt anlegen ---- */
  let notizlinienPlanungen = 0;
  const urspruenglicheAnimationsplanung = w.requestAnimationFrame.bind(w);
  w.requestAnimationFrame = (callback) => {
    notizlinienPlanungen += 1;
    return urspruenglicheAnimationsplanung(callback);
  };
  const heuteIso2 = T.zustand().kalender.tag;
  T.oeffneTerminBlatt(null, heuteIso2);
  assert.ok($("#termin-schleier"), "Terminblatt erscheint nicht");
  assert.strictEqual($(".termin-blatt h2").textContent, "Neuer Termin");
  assert.strictEqual($$(".tb-spalten > div").length, 2,
    "linke Angaben und rechte Notiz erwartet");
  assert.ok($("#tb-notiz"), "Notizfeld fehlt");
  assert.ok(notizlinienPlanungen > 0,
    "das dynamisch erzeugte Terminfeld plant keine Notizlinienmessung");
  assert.strictEqual($("#tb-titel").value, "",
    "ein neuer Termin darf keinen Titel vorgeben");
  assert.deepStrictEqual(Array.from($("#termin-titel-vorschlaege").options,
    (o) => o.value), ["Arztbesuch", "Besprechung", "Telefonat", "Hausbesuch",
      "Behördentermin", "Werkstatttermin", "Kontrolltermin", "Geburtstagsfeier"],
    "die typischen Termintitel fehlen");
  assert.strictEqual($("#tb-individuelle-erinnerung").value, "",
    "ein neuer Termin darf keinen individuellen Vorlauf vorgeben");
  assert.strictEqual($("#tb-individuelle-erinnerung").placeholder,
    "z.B. 1 Tag vorher", "der Hinweis zur individuellen Meldung fehlt");
  assert.deepStrictEqual(Array.from($("#tb-erinnerung-vorschlaege").options,
    (o) => o.value), ["1 Tag vorher", "2 Tage vorher", "3 Tage vorher",
      "4 Tage vorher", "5 Tage vorher", "6 Tage vorher", "7 Tage vorher"],
    "die individuellen Terminvorschläge sind unvollständig");
  assert.strictEqual($("#tb-standard-erinnerung-zeile").style.display, "none",
    "ohne individuellen Vorlauf darf die Standardauswahl nicht erscheinen");
  assert.strictEqual($("#tb-standard-erinnerung").checked, true,
    "ohne individuellen Vorlauf muss die Standardbenachrichtigung aktiv sein");
  setze($("#tb-individuelle-erinnerung"), "3 Tage vorher");
  assert.strictEqual($("#tb-standard-erinnerung-zeile").style.display, "",
    "bei individuellem Vorlauf erscheint die Standardauswahl nicht");
  $("#tb-standard-erinnerung").checked = false;
  setze($("#tb-titel"), "Zahnarzt");
  setze($("#tb-zeit"), "14:30");
  setze($("#tb-endzeit"), "15:00");
  setze($("#tb-notiz"), "Versichertenkarte");
  assert.strictEqual($("#tb-fertig").textContent, "Einfügen");
  $("#tb-fertig").click();
  await tick();
  assert.strictEqual(T.daten().termine.length, 1, "Termin nicht angelegt");
  assert.ok(!$("#termin-schleier"), "Terminblatt schließt nicht");
  assert.strictEqual(T.daten().termine[0].notiz, "Versichertenkarte",
    "Notiz nicht übernommen");
  assert.strictEqual(T.daten().termine[0].individuelleErinnerungTage, 3,
    "individueller Terminvorgang wurde nicht gespeichert");
  assert.strictEqual(T.daten().termine[0].standardErinnerung, false,
    "die abgewählte Standardbenachrichtigung wurde nicht gespeichert");
  T.daten().termine[0].kategorien =
    "Arbeit, http://schemas.google.com/g/2005#event, Privat";
  T.daten().kontakte.push(...T.normalisiere({ kontakte: [{ id: "org-kontakt",
    vorname: "Anna", nachname: "Beispiel", emailEintraege: [
      { wert: "anna@example.test", typen: ["WORK"] },
      { wert: "privat@example.test", typen: ["HOME"] }
    ] }, { id: "org-kontakt-gleich", vorname: "Anna", nachname: "Beispiel",
      emailEintraege: [{ wert: "weitere@example.test", typen: ["WORK"] }] },
    { id: "org-kontakt-anders", vorname: "Berta", nachname: "Anders",
      emailEintraege: [{ wert: "unbeteiligt@example.test", typen: ["WORK"] }] }
  ] }).kontakte);

  /* Der Termin steht in der Übersicht rechts, nach Zeit geordnet */
  $$('#ansicht-umschalter [data-ansicht="month"]')[0].click();
  assert.ok($(".termin-uebersicht"), "Terminübersicht fehlt");
  assert.ok($("#inhalt-rechts").textContent.includes("Zahnarzt"),
    "Termin fehlt in der Übersicht");
  assert.ok($(".kal-tag.gewaehlt .mini"), "Termin erscheint nicht im Monatsraster");

  /* Ein Klick auf den Termin in der Übersicht öffnet das Blatt */
  $(".ue-termin").click();
  assert.ok($("#termin-schleier"), "Klick auf Termin öffnet kein Blatt");
  assert.strictEqual($(".termin-blatt h2").textContent, "Termin bearbeiten");
  assert.strictEqual($("#tb-titel").value, "Zahnarzt");
  assert.strictEqual($("#tb-individuelle-erinnerung").value, "3 Tage vorher",
    "individueller Terminvorlauf fehlt beim Bearbeiten");
  assert.strictEqual($("#tb-standard-erinnerung").checked, false,
    "Standardbenachrichtigung ist beim Bearbeiten wieder aktiv");
  assert.strictEqual($("#tb-fertig").textContent, "Termin bearbeiten");
  assert.strictEqual($("#tb-datum-von").parentElement, $("#tb-datum-bis").parentElement,
    "Datum und Bis einschließlich stehen nicht in einer Zeile");
  assert.ok($("#tb-datum-von").parentElement.classList.contains("zeitspanne"));
  assert.strictEqual($("#tb-datum-bis").getAttribute("aria-label"), "Bis einschließlich");
  assert.strictEqual($("#tb-zeit").parentElement, $("#tb-endzeit").parentElement,
    "Uhrzeiten stehen nicht in einer Zeile");
  assert.ok($("#tb-wiederholung-hinweis").compareDocumentPosition($("#tb-erinnerungsbereich")) &
    w.Node.DOCUMENT_POSITION_FOLLOWING,
  "Erinnerungen stehen nicht nach dem wiederkehrenden Termin");
  assert.strictEqual($(".tb-aufklapper").textContent, "▾ Weitere Felder",
    "Lotus-Zusatz fehlt nicht am Aufklapper");
  assert.strictEqual($(".tb-aufklapper").getAttribute("aria-controls"), "tb-weitere-felder");
  assert.strictEqual($(".tb-aufklapper").getAttribute("aria-expanded"), "true");
  assert.deepStrictEqual(Array.from($("#tb-kategorien-vorschlaege").options,
    (option) => option.value), ["Arbeit", "Privat"], "Kategorienvorschläge fehlen");
  assert.ok(Array.from($("#tb-organisator-namen").options,
    (option) => option.value).includes("Anna Beispiel"), "Organisatorvorschlag fehlt");
  setze($("#tb-organisator-name"), "Anna Beispiel");
  assert.deepStrictEqual(Array.from($("#tb-organisator-emails").options,
    (option) => option.value), ["anna@example.test", "privat@example.test",
      "weitere@example.test"],
  "E-Mail-Vorschläge gehören nicht zum gewählten Kontakt");
  setze($("#tb-kategorien"), "Eigene Kategorie");
  setze($("#tb-organisator-email"), "andere@example.test");
  setze($("#tb-titel"), "Zahnarzt Dr. Berg");
  $("#tb-fertig").click();
  await tick();
  assert.strictEqual(T.daten().termine[0].titel, "Zahnarzt Dr. Berg");
  assert.strictEqual(T.daten().termine[0].kategorien, "Eigene Kategorie");
  assert.deepStrictEqual(T.daten().termine[0].organisator,
    { name: "Anna Beispiel", email: "andere@example.test", uri: "" },
  "freie Organisatorangaben wurden nicht gespeichert");
  T.daten().kontakte = T.daten().kontakte.filter((kontakt) =>
    !["org-kontakt", "org-kontakt-gleich", "org-kontakt-anders"].includes(kontakt.id));

  /* Löschen aus dem Terminblatt heraus */
  $(".ue-termin").click();
  $("#tb-loeschen").click();
  assert.ok(!$("#dialog-schleier").classList.contains("verborgen"), "Nachfrage fehlt");
  assert.ok(/#dialog-schleier,[\s\S]{0,260}z-index:\s*140/.test(css) &&
    /\.termin-schleier[\s\S]{0,220}z-index:\s*120/.test(css),
  "Löschdialog liegt im CSS nicht über dem Terminblatt");
  $("#dialog-ja").click();
  await tick();
  assert.strictEqual(T.daten().termine.length, 0, "Termin nicht gelöscht");
  assert.ok(T.daten().papierkorb.some((s) => s.art === "appointment"),
    "der gelöschte Termin fehlt im Papierkorb");

  /* Termin für Planer-Prüfung wieder anlegen */
  T.oeffneTerminBlatt(null, heuteIso2);
  setze($("#tb-titel"), "Planungstermin");
  $("#tb-fertig").click();
  await tick();

  /* Eselsohr: Monat vorblättern */
  const monatVorher = $("#kopf-links h2").textContent;
  $("#ecke-rechts").click();
  assert.notStrictEqual($("#kopf-links h2").textContent, monatVorher, "Eselsohr blättert nicht");
  knopfMit("Heute").click();

  /* Langes Drücken auf den Monatspfeil läuft selbsttätig weiter. */
  const monatStart = T.zustand().kalender.jahr * 12 + T.zustand().kalender.monat;
  const monatVor = $$("#kopf-links .pfeil")[1];
  monatVor.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 720));
  w.dispatchEvent(new w.Event("pointerup"));
  const monatEnde = T.zustand().kalender.jahr * 12 + T.zustand().kalender.monat;
  assert.ok(monatEnde - monatStart >= 2,
    "langes Drücken blättert den Monat nicht schnell weiter");
  knopfMit("Heute").click();

  /* ---- Aufgaben ---- */
  klickeTab("Aufgaben");
  assert.strictEqual($$("#register-links .registerknopf").length, 1, "Kalender-Tab müsste links sein");
  assert.strictEqual($("#kopf-links h2").textContent, "Aufgaben",
    "deutsche Aufgabenüberschrift fehlt");
  assert.strictEqual($("#kopf-rechts h2").textContent, "Neue Aufgabe",
    "deutscher Aufgabenkopf fehlt");
  assert.strictEqual($("#aufgabe-titel").placeholder, "Was ist zu erledigen?",
    "deutscher Aufgabenplatzhalter fehlt");
  assert.deepStrictEqual($$("#inhalt-rechts .feldname")
    .filter((label) => label.parentElement.style.display !== "none")
    .map((label) => label.textContent),
    ["Titel", "Priorität", "Fällig am", "Notiz", "Individuelle Benachrichtigung"],
  "deutsche Aufgabenbeschriftungen sind unvollständig");
  assert.strictEqual($("#aufgabe-titel").value, "",
    "eine neue Aufgabe darf keinen Titel vorgeben");
  assert.deepStrictEqual(Array.from($("#aufgabe-titel-vorschlaege").options,
    (o) => o.value), ["Unterlagen senden", "Besorgungen", "Anrufen",
      "Termin vereinbaren", "Rechnung bezahlen", "Einkaufen", "Nachfragen", "Abholen"],
    "die typischen Aufgabentitel fehlen");
  assert.strictEqual($("#aufgabe-faellig-zeit-zeile").style.display, "none",
    "Aufgabenzeit ist ohne Auswahl sichtbar");
  $("#aufgabe-faellig-zeile").dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 20, clientY: 20 }));
  assert.ok($("#vorschlags-menue").textContent.includes("Uhrzeit") &&
    $("#vorschlags-menue").textContent.includes("von"),
  "Rechtsklick auf Fälligkeit bietet Zeit und Zeitfenster nicht an");
  $("#vorschlags-menue .vm-eintrag").click();
  assert.strictEqual($("#aufgabe-faellig-zeit-zeile").style.display, "",
    "gewählte Fälligkeitszeit wird nicht eingeblendet");
  setze($("#inhalt-rechts fieldset input[type=text]"), "Steuer vorbereiten");
  setze($("#inhalt-rechts fieldset .datumsfeld"), "2020-01-01"); /* überfällig */
  setze($("#aufgabe-faellig-zeit-zeile input"), "09:30");
  knopfMit("Aufnehmen").click();
  assert.strictEqual(T.daten().aufgaben.length, 1);
  assert.strictEqual(T.daten().aufgaben[0].faelligZeit, "09:30",
    "Fälligkeitszeit der Aufgabe wird nicht gespeichert");
  assert.match($("#inhalt-links .faellig").textContent, /0?9:30/,
    "Fälligkeitszeit der Aufgabe wird in der Liste nicht angezeigt");
  assert.ok($(".faellig.ueber"), "Überfällig-Markierung fehlt");

  $(".check").click(); /* abhaken */
  assert.strictEqual(T.daten().aufgaben[0].erledigt, true, "Abhaken wirkt nicht");
  assert.ok($("#inhalt-links").textContent.includes("Erledigt (1)"));
  $(".check.an").click(); /* wieder öffnen */
  assert.strictEqual(T.daten().aufgaben[0].erledigt, false);

  /* ---- Adressen ---- */
  klickeTab("Adressen");
  knopfMit("Neu").click();
  assert.ok($("#kontakt-foto-knopf"),
    "die deutsche Fotoauswahl fehlt trotz Voreinstellung");
  assert.strictEqual($("#kontakt-foto-knopf").textContent, "Foto auswählen …",
    "der Fotoknopf ist nicht deutsch beschriftet");
  assert.ok($("#kontakt-foto-datei").classList.contains("datei-versteckt"),
    "das fremd gestaltete Browser-Dateifeld ist noch sichtbar");
  assert.ok($(".kontakt-formular.neu") && $(".kontakt-foto-wahl.leer") &&
    !$(".kontakt-foto-platzhalter").classList.contains("verborgen") &&
    $(".kontakt-foto-platzhalter").textContent === "Kein Foto",
  "die leere Fotovorschau bleibt nicht sichtbar");
  assert.ok(!$("#kontakt-notiz").closest(".kontakt-weitere"),
    "die Kontakt-Notiz ist weiterhin unter Weitere Felder verborgen");
  assert.ok($("#kontakt-foto-knopf").compareDocumentPosition($("#kontakt-nachname")) &
    w.Node.DOCUMENT_POSITION_FOLLOWING, "das Foto steht nicht oben im Formular");
  assert.deepStrictEqual(Array.from($("#kontakt-anschrift-arten").options, (o) => o.value),
    ["Anschrift", "Hauptsitz", "Zweitsitz", "Arbeit", "Privat"],
    "die Anschriftsauswahl ist nicht vollständig");
  assert.strictEqual($(".kontakt-anschrift-art").value, "",
    "die Anschriftsart darf nicht vorausgewählt sein");
  assert.strictEqual($(".kontakt-anschrift-art").placeholder, "z.B. Privat",
    "der Platzhalter der Anschriftsart stimmt nicht");
  assert.deepStrictEqual(Array.from($("#kontakt-telefon-arten").options, (o) => o.value),
    ["Festnetz", "Mobil", "Arbeit", "Zuhause", "Privat", "Fax", "Pager"],
    "die Rufnummernauswahl ist nicht vollständig");
  assert.strictEqual($(".kontakt-telefon-art").value, "",
    "die Rufnummernart darf nicht vorausgewählt sein");
  assert.strictEqual($(".kontakt-telefon-art").placeholder, "z.B. Mobil",
    "der Platzhalter der Rufnummernart stimmt nicht");
  assert.deepStrictEqual(Array.from($("#kontakt-email-arten").options, (o) => o.value),
    ["Zuhause", "Privat", "Arbeit", "Sonstige"],
    "die E-Mail-Auswahl ist nicht vollständig");
  assert.strictEqual($(".kontakt-email-art").value, "",
    "die E-Mail-Art darf nicht vorausgewählt sein");
  assert.strictEqual($(".kontakt-email-art").placeholder, "z.B. Arbeit",
    "der Platzhalter der E-Mail-Art stimmt nicht");
  setze($("#kontakt-nachname"), "Beispiel");
  setze($("#kontakt-vorname"), "Anna");
  setze($(".kontakt-anschrift-strasse"), "Musterstraße 7");
  setze($(".kontakt-anschrift-plz"), "47051");
  setze($("#kontakt-ort"), "Duisburg");
  setze($(".kontakt-telefon-nummer"), "0203 123456");
  const weitereNummern = [
    ["Mobil", "0171 1111111"], ["Arbeit", "0203 222222"],
    ["Privat", "0203 333333"], ["Fax", "0203 444444"],
    ["Pager", "0203 555555"], ["Festnetz", "0203 666666"],
    ["Mobil", "0171 7777777"], ["Pforte", "0203 888888"]
  ];
  for (const [art, nummer] of weitereNummern) {
    knopfMit("+ Rufnummer").click();
    const arten = $$(".kontakt-telefon-art");
    const nummern = $$(".kontakt-telefon-nummer");
    setze(arten[arten.length - 1], art);
    setze(nummern[nummern.length - 1], nummer);
  }
  knopfMit("+ Anschrift").click();
  let anschriftZeilen = $$(".kontakt-anschrift-zeile");
  setze(anschriftZeilen[1].querySelector(".kontakt-anschrift-art"), "Pflegebereich");
  setze(anschriftZeilen[1].querySelector(".kontakt-anschrift-strasse"), "Zweigweg 9");
  setze(anschriftZeilen[1].querySelector(".kontakt-anschrift-plz"), "47441");
  setze(anschriftZeilen[1].querySelector(".kontakt-anschrift-ort"), "Moers");
  knopfMit("+ Anschrift").click();
  anschriftZeilen = $$(".kontakt-anschrift-zeile");
  setze(anschriftZeilen[2].querySelector(".kontakt-anschrift-strasse"), "Musterstr. 7");
  setze(anschriftZeilen[2].querySelector(".kontakt-anschrift-plz"), "47051");
  setze(anschriftZeilen[2].querySelector(".kontakt-anschrift-ort"), "Duisburg");
  $("#kontakt-weitere-aufklapper").click();
  setze($("#kontakt-firma"), "Beispiel GmbH");
  assert.deepStrictEqual(Array.from($("#kontaktperson-status-vorschlaege").options,
    (o) => o.value), ["Sohn", "Tochter", "Betreuer", "Betreuerin", "Nachbar",
      "Nachbarin", "Lebensgefährte", "Lebensgefährtin", "Ehepartner",
      "Ehepartnerin", "Freund", "Freundin", "Angehöriger", "Angehörige",
      "Pflegedienst", "Sonstige"], "die Beziehungsvorschläge sind unvollständig");
  assert.strictEqual($("#kontaktperson-status").value, "",
    "der Notfallkontaktstatus darf nicht vorausgewählt sein");
  assert.strictEqual($("#kontaktperson-status").placeholder, "z.B. Sohn",
    "der Platzhalter für die Beziehung stimmt nicht");
  assert.ok($(".kontaktperson-zeile"), "der gestrichelte Notfallkontakt fehlt");
  const anschriftStil = css.match(/\.kontakt-anschrift-zeile\s*\{([^}]*)\}/);
  assert.ok(anschriftStil && !/border/.test(anschriftStil[1]),
    "normale Anschriften sind weiterhin gestrichelt eingerahmt");
  assert.ok(/\.kontaktperson-zeile\s*\{[^}]*border:\s*1px dashed/.test(css),
    "der gestrichelte Rahmen liegt nicht beim Notfallkontakt");
  setze($("#kontaktperson-name"), "Peter Beispiel");
  setze($("#kontaktperson-telefon"), "0203 765432");
  setze($("#kontaktperson-status"), "Sohn");
  knopfMit("+ Notfallkontakt").click();
  let notfallkontakte = $$(".kontaktperson-zeile");
  setze(notfallkontakte[1].querySelector(".kontaktperson-name"), "Maria Nachbar");
  setze(notfallkontakte[1].querySelector(".kontaktperson-telefon"), "0203 111222");
  setze(notfallkontakte[1].querySelector(".kontaktperson-status"), "Nachbarin");
  assert.deepStrictEqual(Array.from($("#kontakt-jahrestagsarten").options, (o) => o.value),
    ["Geburtstag", "Todestag", "Hochzeitstag", "Partnerschaftstag", "Namenstag",
      "Tauftag", "Kommunion", "Konfirmation", "Firmung", "Jubiläum",
      "Vereinsjubiläum", "Dienstjubiläum", "Gründungstag", "Gedenktag", "Sonstiges"],
    "die Jahrestagsauswahl ist nicht vollständig");
  assert.strictEqual($(".kontakt-ereignis-typ").value, "",
    "die Jahrestagsart darf nicht vorausgewählt sein");
  assert.strictEqual($(".kontakt-ereignis-typ").placeholder, "z.B. Geburtstag",
    "der Platzhalter der Jahrestagsart stimmt nicht");
  const kontaktJahrestagDatum = $("#kontakt-jahrestag-datum");
  assert.strictEqual(kontaktJahrestagDatum.value, "",
    "ein neuer Kontaktjahrestag darf kein Datum vorauswählen");
  for (const ziffer of "12041990") kontaktJahrestagDatum.dispatchEvent(
    new w.KeyboardEvent("keydown", { key: ziffer, bubbles: true, cancelable: true }));
  await tick();
  assert.strictEqual(kontaktJahrestagDatum.value, "12.04.1990",
    "Kontaktjahrestag nimmt TTMMJJJJ nicht direkt an");
  assert.strictEqual(T.datumswert(kontaktJahrestagDatum), "1990-04-12",
    "Kontaktjahrestag hält intern keinen gültigen ISO-Wert");
  assert.strictEqual(kontaktJahrestagDatum.getAttribute("aria-label"), "Datum",
    "Kontaktjahrestag besitzt keine zugängliche Beschriftung");
  setze($(".kontakt-ereignis-typ"), "Geburtstag");
  setze($("#kontakt-jahrestag-datum"), "1990-04-12");
  $("#kontakt-ereignis-plus").click();
  assert.strictEqual($$(".kontakt-ereignis-zeile").length, 2,
    "mit + lässt sich kein weiterer Jahrestag ergänzen");
  setze($$(".kontakt-ereignis-typ")[1], "Hochzeitstag");
  setze($$(".kontakt-ereignis-datum")[1], "--08-22");
  setze($("#kontakt-termin-titel"), "Jahresgespräch");
  setze($("#kontakt-termin-datum"), "2030-05-03");
  assert.deepStrictEqual(Array.from($("#kontakt-termin-vorschlaege").options,
    (o) => o.value), ["Arztbesuch", "Besprechung", "Telefonat", "Hausbesuch",
      "Behördentermin", "Werkstatttermin", "Kontrolltermin", "Geburtstagsfeier"],
    "die Terminvorschläge fehlen im Kontaktformular");
  knopfMit("+ Weitere Termine").click();
  const kontaktTermine = $$(".kontakt-termin-zeile");
  setze(kontaktTermine[1].querySelector(".kontakt-termin-titel"), "Arztbesuch");
  setze(kontaktTermine[1].querySelector(".kontakt-termin-datum"), "2030-05-04");
  setze($("#kontakt-aufgabe-titel"), "Unterlagen senden");
  setze($("#kontakt-aufgabe-datum"), "2030-05-01");
  assert.deepStrictEqual(Array.from($("#kontakt-aufgabe-vorschlaege").options,
    (o) => o.value), ["Unterlagen senden", "Besorgungen", "Anrufen",
      "Termin vereinbaren", "Rechnung bezahlen", "Einkaufen", "Nachfragen", "Abholen"],
    "die Aufgabenvorschläge fehlen im Kontaktformular");
  knopfMit("+ Weitere Aufgaben").click();
  const kontaktAufgaben = $$(".kontakt-aufgabe-zeile");
  setze(kontaktAufgaben[1].querySelector(".kontakt-aufgabe-titel"), "Besorgungen");
  setze(kontaktAufgaben[1].querySelector(".kontakt-aufgabe-datum"), "2030-05-02");
  setze($(".kontakt-email-art"), "Arbeit");
  setze($(".kontakt-email-adresse"), "anna@example.org");
  for (const [art, adresse] of [["Sonstige", "47110815"],
    ["Verein", "anna@arbeit.example"], ["Sonstige", "Kundennummer 9821"]]) {
    knopfMit("+ E-Mail-Adresse").click();
    const arten = $$(".kontakt-email-art");
    const adressen = $$(".kontakt-email-adresse");
    setze(arten[arten.length - 1], art);
    setze(adressen[adressen.length - 1], adresse);
  }
  knopfMit("Kontakt anlegen").click();
  assert.strictEqual(T.daten().kontakte.length, 1);
  assert.strictEqual(T.daten().kontakte[0].telefone.length, 9,
    "nicht alle neun Rufnummern wurden gespeichert");
  assert.strictEqual(T.daten().kontakte[0].anschriften.length, 2,
    "mehrere oder gleich geschriebene Anschriften wurden falsch behandelt");
  assert.strictEqual(T.daten().kontakte[0].telefone[8].label, "Pforte",
    "eigene Rufnummernbezeichnung wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].anschriften[1].label, "Pflegebereich",
    "eigene Anschriftsbezeichnung wurde nicht gespeichert");
  assert.strictEqual(T.daten().jahrestage.filter((j) => j.typ === "birthday").length, 1,
    "der Kontaktgeburtstag fehlt bei den Jahrestagen");
  assert.strictEqual(T.daten().jahrestage[0].kontaktId, T.daten().kontakte[0].id,
    "der Geburtstag ist nicht mit dem Kontakt verknüpft");
  assert.ok(T.daten().jahrestage.some((j) => j.typ === "wedding-anniversary" &&
    j.kontaktId === T.daten().kontakte[0].id && j.datum === "--08-22" &&
    j.jahrUnbekannt),
  "der zusätzliche Hochzeitstag fehlt bei den Jahrestagen");
  assert.strictEqual(T.daten().termine.find((t) => t.titel === "Jahresgespräch").kontaktId,
    T.daten().kontakte[0].id, "der Kontakttermin ist nicht verknüpft");
  assert.strictEqual(T.daten().termine.find((t) => t.titel === "Arztbesuch").kontaktId,
    T.daten().kontakte[0].id, "der zweite Kontakttermin ist nicht verknüpft");
  assert.strictEqual(T.daten().aufgaben.find((a) => a.titel === "Unterlagen senden").kontaktId,
    T.daten().kontakte[0].id, "die Kontaktaufgabe ist nicht verknüpft");
  assert.strictEqual(T.daten().aufgaben.find((a) => a.titel === "Besorgungen").kontaktId,
    T.daten().kontakte[0].id, "die zweite Kontaktaufgabe ist nicht verknüpft");
  assert.deepStrictEqual(Array.from(T.daten().kontakte[0].emails),
    ["anna@example.org", "anna@arbeit.example"],
    "mehrere E-Post-Anschriften werden nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].emailEintraege[0].typen.includes("WORK"), true,
    "die E-Mail-Art Arbeit wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].emailEintraege[1].label, "Verein",
    "die freie E-Mail-Bezeichnung wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].kontaktpersonName, "Peter Beispiel",
    "Name der Kontaktperson wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].kontaktpersonTelefon, "0203 765432",
    "Rufnummer der Kontaktperson wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].kontaktpersonStatus, "Sohn",
    "Status der Kontaktperson wurde nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].kontaktpersonen.length, 2,
    "mehrere Notfallkontakte wurden nicht gespeichert");
  assert.strictEqual(T.daten().kontakte[0].kontaktpersonen[1].status, "Nachbarin",
    "die Beziehung des zweiten Notfallkontakts fehlt");
  assert.strictEqual(T.zustand().adressen.buchstabe, "B", "Register springt nicht auf B");
  assert.ok($("#inhalt-rechts").textContent.includes("Beispiel, Anna"));
  assert.ok($("#inhalt-rechts").textContent.includes("0203 888888") &&
    $("#inhalt-rechts").textContent.includes("Zweigweg 9") &&
    $("#inhalt-rechts").textContent.includes("Peter Beispiel") &&
    $("#inhalt-rechts").textContent.includes("Sohn") &&
    $("#inhalt-rechts").textContent.includes("Pforte") &&
    $("#inhalt-rechts").textContent.includes("Pflegebereich") &&
    $("#inhalt-rechts").textContent.includes("Maria Nachbar") &&
    $("#inhalt-rechts").textContent.includes("Nachbarin"),
    "weitere Rufnummern, Anschriften oder die Kontaktperson fehlen auf der Karteikarte");
  assert.ok(!$("#inhalt-rechts").textContent.includes("Geburtstag"),
    "der Geburtstag wird unnötig auf der Karteikarte wiederholt");
  assert.ok(!$("#inhalt-rechts").textContent.includes("Jahresgespräch") &&
    !$("#inhalt-rechts").textContent.includes("Unterlagen senden"),
    "verknüpfte Termine oder Aufgaben werden auf der Karteikarte wiederholt");
  assert.ok(T.termineAm("2030-05-03").some((t) => t.titel === "Jahresgespräch"),
    "der im Adressdialog angelegte Termin fehlt im Kalender");
  T.daten().kontakte[0].foto = "data:image/png;base64,AA==";
  knopfMit("Bearbeiten").click();
  assert.strictEqual($("#kontakt-foto-knopf").textContent, "Foto entfernen",
    "der gemeinsame Fotoknopf erkennt ein vorhandenes Foto nicht");
  $("#kontakt-foto-knopf").click();
  assert.strictEqual($("#kontakt-foto-knopf").textContent, "Foto auswählen …",
    "der gemeinsame Fotoknopf schaltet nach dem Entfernen nicht um");
  assert.ok($("#kontakt-firma").compareDocumentPosition($("#kontakt-notiz")) &
    w.Node.DOCUMENT_POSITION_FOLLOWING, "Firma steht nicht direkt vor der Notiz");
  knopfMit("Änderungen speichern").click();
  assert.strictEqual(T.daten().jahrestage.filter((j) => j.kontaktId === T.daten().kontakte[0].id).length, 2,
    "erneutes Speichern verdoppelt oder verliert die Kontaktjahrestage");
  assert.strictEqual(T.daten().termine.filter((t) => t.titel === "Jahresgespräch").length, 1,
    "erneutes Speichern verdoppelt den Kontakttermin");
  assert.strictEqual(T.daten().aufgaben.filter((a) => a.titel === "Unterlagen senden").length, 1,
    "erneutes Speichern verdoppelt die Kontaktaufgabe");
  const postKnopf = $("#inhalt-rechts .post-anschrift");
  assert.ok(postKnopf, "anklickbare E-Post-Anschrift fehlt");
  assert.strictEqual(postKnopf.textContent, "anna@example.org",
    "die E-Post-Anschrift steht nicht auf der Karte");
  assert.ok(postKnopf.title.includes("anna@example.org"),
    "kein Hinweis, wohin der Klick führt");
  assert.strictEqual($$("#inhalt-rechts .post-anschrift").length, 2,
    "die zweite E-Post-Anschrift fehlt auf der Karte");
  const kontaktUid = T.daten().kontakte[0].uid;
  w.App.importErgebnis({ kontakte: [{ uid: kontaktUid, nachname: "Beispiel",
    vorname: "Anna", email: "anna@example.org",
    emails: ["anna@example.org", "ANNA@ARBEIT.EXAMPLE", "774921",
      "Anna Beispiel <anna@verein.example>"],
    telefone: [{ wert: "+49 (0)203 123456", typen: ["WORK"] },
      { wert: "0203 999999", typen: ["VOICE"] },
      { wert: "131526931463024", typen: ["CELL"] }],
    anschriften: [{ strasse: "Musterstrasse 7", plz: "47051", ort: "Duisburg" }] }] });
  assert.strictEqual(T.daten().kontakte.length, 1,
    "erneuter Import hat den Kontakt verdoppelt");
  assert.deepStrictEqual(Array.from(T.daten().kontakte[0].emails),
    ["anna@example.org", "anna@arbeit.example", "anna@verein.example"],
    "erneuter Import vereinigt E-Post-Anschriften nicht");
  assert.strictEqual(T.daten().kontakte[0].telefone.length, 10,
    "Landesvorwahl-Dublette oder neue Rufnummer wurde falsch zusammengeführt");
  assert.strictEqual(T.daten().kontakte[0].anschriften.length, 2,
    "Straße/Str./Strasse hat eine Anschrift verdoppelt");
  w.App.importErgebnis({ kontakte: [{ uid: "anderer-cache-eintrag",
    nachname: "Beispiel", vorname: "Anna",
    email: "4d87d88e8c565eed@nowhere.invalid",
    emails: ["4d87d88e8c565eed@nowhere.invalid"] }] });
  assert.strictEqual(T.daten().kontakte.length, 1,
    "eine sparsame Cache-Karte wurde als Dublette angelegt");
  assert.ok(!T.daten().kontakte[0].emails.some((mail) => /\.invalid$/i.test(mail)),
    "eine reservierte Platzhalteradresse blieb im Kontakt");
  const abcB = $$(".abc").find((b) => b.textContent === "B");
  assert.ok(abcB.classList.contains("voll") && abcB.classList.contains("aktiv"));

  const suchfeld = $(".suchfeld");
  setze(suchfeld, "duis");
  assert.ok($("#inhalt-links").textContent.includes("Beispiel, Anna"), "Suche findet nichts");
  setze(suchfeld, "+49 203 123456");
  assert.ok($("#inhalt-links").textContent.includes("Beispiel, Anna"),
    "Suche erkennt nationale und internationale Rufnummer nicht als gleich");
  setze(suchfeld, "xyz-nichts");
  assert.ok($("#inhalt-links").textContent.includes("Nichts gefunden"));
  setze(suchfeld, "");

  /* ---- Notizen ---- */
  const planungenVorNotiz = notizlinienPlanungen;
  klickeTab("Notizen");
  assert.ok(notizlinienPlanungen > planungenVorNotiz,
    "die dynamisch erzeugte Notiz plant keine Notizlinienmessung");
  assert.ok($(".notiz-gruppe-name") && $(".notizbuch-zeile"),
    "Notizbuchgruppe und Notizbuch fehlen");
  assert.ok(knopfMit("Neue Gruppe") && knopfMit("Neues Notizbuch"),
    "Schaltflächen für die Notizstruktur fehlen");
  assert.ok($("#notiz-suche"), "Suche für Notizbuch und Notiz fehlt");
  assert.strictEqual($("#notiz-suche").placeholder, "Suche",
    "das Suchfeld ist nicht knapp beschriftet");
  assert.ok($("#notiz-anpassen") && $(".notiz-suche-zeile"),
    "Anpassen-Knopf neben der Suche fehlt");
  assert.ok(/\.notiz-suche-zeile \.suchfeld[\s\S]{0,120}flex:\s*1/.test(css),
    "das Notiz-Suchfeld nutzt den freien Platz nicht");

  knopfMit("Neue Gruppe").click();
  assert.ok($("#eingabe-schleier") && $("#eingabe-feld"),
    "Magnolie-Eingabedialog für die neue Gruppe fehlt");
  setze($("#eingabe-feld"), "Projekte");
  knopfMit("Gruppe anlegen", $("#eingabe-schleier")).click();
  await tick();
  let projektGruppe = $$(".notiz-gruppe").find(
    (gruppe) => gruppe.querySelector(".notiz-gruppe-name").textContent === "Projekte");
  assert.ok(projektGruppe, "neue Notizbuchgruppe wurde nicht angelegt");
  const projektDaten = T.daten().notizgruppen.find((g) => g.name === "Projekte");
  const projektBuch = T.daten().notizbuecher.find((b) => b.gruppeId === projektDaten.id);
  const projektSeite = T.daten().notizen.find((n) => n.notizbuchId === projektBuch.id);
  assert.ok(projektBuch && projektSeite && !projektSeite.titel && !projektSeite.text,
    "eine neue Gruppe erhält nicht sofort Notizbuch und leere Seite");
  assert.strictEqual(T.zustand().notizen.auswahlId, projektSeite.id,
    "die leere Seite der neuen Gruppe wird nicht aufgeschlagen");
  projektGruppe.querySelector('[aria-label="Gruppe bearbeiten"]').click();
  setze($("#eingabe-feld"), "Vorhaben");
  knopfMit("Änderung speichern", $("#eingabe-schleier")).click();
  await tick();
  projektGruppe = $$(".notiz-gruppe").find(
    (gruppe) => gruppe.querySelector(".notiz-gruppe-name").textContent === "Vorhaben");
  assert.ok(projektGruppe, "Notizbuchgruppe wurde nicht umbenannt");
  $("#notiz-anpassen").click();
  assert.ok($("#notiz-anpassen-schleier") && $(".notiz-anpassen-dialog"),
    "Verwaltungsblatt für Notizbücher fehlt");
  assert.ok(knopfMit("Alles alphabetisch sortieren", $("#notiz-anpassen-schleier")),
    "alphabetische Sortierung fehlt");
  const vorhabenVerwaltung = $$(".notiz-anpassen-gruppe").find(
    (gruppe) => gruppe.querySelector(".notiz-anpassen-name").textContent === "Vorhaben");
  const zielGruppe = T.daten().notizgruppen.find((g) => g.id !== projektDaten.id);
  const gruppenWahl = vorhabenVerwaltung.querySelector(".notiz-anpassen-buch .feld");
  gruppenWahl.value = zielGruppe.id;
  gruppenWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(projektBuch.gruppeId, zielGruppe.id,
    "Notizbuch wird nicht in die gewählte Gruppe verschoben");
  knopfMit("Fertig", $("#notiz-anpassen-schleier")).click();
  assert.ok(!$("#notiz-anpassen-schleier"), "Verwaltungsblatt schließt nicht");
  projektGruppe = $$(".notiz-gruppe").find(
    (gruppe) => gruppe.querySelector(".notiz-gruppe-name").textContent === "Vorhaben");
  projektGruppe.querySelector('[aria-label="Gruppe löschen"]').click();
  $("#dialog-ja").click();
  await tick();
  assert.ok(!$$(".notiz-gruppe-name").some((name) => name.textContent === "Vorhaben"),
    "leere Notizbuchgruppe wurde nicht gelöscht");

  /* Testeinträge entfernen, damit die folgenden Schreibblattprüfungen
     weiterhin mit genau einer vorhandenen Seite beginnen. */
  T.daten().notizen = T.daten().notizen.filter((n) => n.id !== projektSeite.id);
  T.daten().notizbuecher = T.daten().notizbuecher.filter((b) => b.id !== projektBuch.id);
  T.zustand().notizen.notizbuchId = T.daten().notizbuecher[0].id;
  T.zustand().notizen.gruppeId = T.daten().notizbuecher[0].gruppeId;
  T.zustand().notizen.auswahlId = T.daten().notizen[0].id;
  T.wechsel("kalender");
  T.wechsel("notizen");

  knopfMit("Neues Notizbuch").click();
  setze($("#eingabe-feld"), "Arbeit");
  knopfMit("Notizbuch anlegen", $("#eingabe-schleier")).click();
  await tick();
  let arbeitBuch = $$(".notizbuch-eintrag").find(
    (buch) => buch.querySelector(".notizbuch-name").textContent === "Arbeit");
  assert.ok(arbeitBuch, "neues Notizbuch wurde nicht angelegt");
  arbeitBuch.querySelector('[aria-label="Notizbuch bearbeiten"]').click();
  setze($("#eingabe-feld"), "Beruf");
  knopfMit("Änderung speichern", $("#eingabe-schleier")).click();
  await tick();
  arbeitBuch = $$(".notizbuch-eintrag").find(
    (buch) => buch.querySelector(".notizbuch-name").textContent === "Beruf");
  arbeitBuch.querySelector('[aria-label="Notizbuch löschen"]').click();
  $("#dialog-ja").click();
  await tick();
  assert.ok(!$$(".notizbuch-name").some((name) => name.textContent === "Beruf"),
    "Notizbuch wurde nicht gelöscht");

  knopfMit("Neue Seite").click();
  assert.strictEqual(T.daten().notizen.length, 2);
  setze($("#notiz-titel"), "Einkauf");
  const schreibflaeche = $("#notiz-text");
  assert.strictEqual(schreibflaeche.getAttribute("contenteditable"), "true",
    "Schreibblatt ist nicht beschreibbar");
  schreibflaeche.innerHTML = "Milch<br>Brot";
  schreibflaeche.dispatchEvent(new w.Event("input", { bubbles: true }));
  const neue = T.daten().notizen[1];
  assert.strictEqual(neue.titel, "Einkauf");
  assert.strictEqual(neue.html, "Milch<br>Brot", "Notiztext nicht gespeichert");
  assert.strictEqual(neue.text, "Milch\nBrot", "Reiner Text nicht abgeleitet");
  assert.ok($("#inhalt-links").textContent.includes("Einkauf"), "Listeneintrag aktualisiert nicht");

  /* Auszeichnen: vier Knöpfe, Auswahl wird eingefasst und wieder gelöst */
  const werkzeuge = $$(".werkzeug-knopf");
  assert.strictEqual(werkzeuge.length, 4, "vier Auszeichnungsknöpfe erwartet");
  assert.deepStrictEqual(werkzeuge.map((b) => b.getAttribute("aria-label")),
    ["Fett", "Kursiv", "Unterstrichen", "Durchgestrichen"], "Beschriftungen");

  /* Die Leiste zeigt sich erst beim Schreiben oder Markieren */
  const leiste = $("#schreib-werkzeug");
  assert.ok(leiste, "Werkzeugleiste fehlt");
  schreibflaeche.innerHTML = "";
  schreibflaeche.dispatchEvent(new w.Event("input", { bubbles: true }));
  T.zeigeWerkzeugleiste();
  assert.ok(leiste.classList.contains("verborgene-leiste"),
    "leeres Blatt zeigt die Leiste trotzdem");
  schreibflaeche.innerHTML = "Milch<br>Brot";
  schreibflaeche.dispatchEvent(new w.Event("input", { bubbles: true }));
  schreibflaeche.focus();
  T.zeigeWerkzeugleiste();
  assert.ok(!leiste.classList.contains("verborgene-leiste"),
    "Leiste bleibt beim Schreiben verborgen");

  const markiere = (knoten, von, bis) => {
    if (!knoten || knoten.nodeType !== 3 || bis > knoten.textContent.length) {
      throw new Error("Markierung unmöglich – Knoten: " +
        (knoten ? knoten.nodeName + " " + JSON.stringify(knoten.textContent) : "keiner") +
        " Bereich " + von + ".." + bis + " – Inhalt: " + $("#notiz-text").innerHTML);
    }
    const bereich = d.createRange();
    bereich.setStart(knoten, von);
    bereich.setEnd(knoten, bis);
    const auswahl = w.getSelection();
    auswahl.removeAllRanges();
    auswahl.addRange(bereich);
  };
  markiere(schreibflaeche.firstChild, 0, 5);      /* „Milch“ */
  werkzeuge[0].click();
  assert.ok(/<b>Milch<\/b>/.test(T.daten().notizen[1].html),
    "Fett nicht angewandt: " + T.daten().notizen[1].html);
  assert.strictEqual(T.daten().notizen[1].text, "Milch\nBrot",
    "Reiner Text ändert sich durch Auszeichnung nicht");

  /* Zweiter Klick hebt wieder auf – auch wenn die Markierung, wie in WebKit
     üblich, außerhalb der Auszeichnung liegt. */
  const ausserhalb = d.createRange();
  ausserhalb.selectNode($("#notiz-text b"));
  const auswahl2 = w.getSelection();
  auswahl2.removeAllRanges();
  auswahl2.addRange(ausserhalb);
  werkzeuge[0].click();
  assert.ok(!/<b>/.test(T.daten().notizen[1].html),
    "Fett nicht wieder gelöst: " + T.daten().notizen[1].html);
  assert.strictEqual($("#notiz-text").textContent, "MilchBrot",
    "Text nach dem Aufheben unverändert");

  /* Nach dem Auszeichnen bleibt die Markierung stehen: sofort erneut möglich */
  markiere($("#notiz-text").firstChild, 0, 5);
  werkzeuge[1].click();
  assert.ok(/<i>Milch<\/i>/.test(T.daten().notizen[1].html), "Kursiv fehlt");
  assert.ok(werkzeuge[1].classList.contains("aktiv"),
    "Knopf zeigt die geltende Auszeichnung nicht an");
  assert.ok(!werkzeuge[0].classList.contains("aktiv"),
    "Fett dürfte hier nicht als geltend gelten");
  werkzeuge[1].click();
  assert.ok(!/<i>/.test(T.daten().notizen[1].html),
    "Zweiter Klick hebt nicht auf: " + T.daten().notizen[1].html);
  assert.ok(!werkzeuge[1].classList.contains("aktiv"),
    "Knopf bleibt nach dem Aufheben hervorgehoben");

  /* Nur ein Teil einer Auszeichnung wird befreit */
  $("#notiz-text").innerHTML = "<b>Milch und Brot</b>";
  $("#notiz-text").dispatchEvent(new w.Event("input", { bubbles: true }));
  markiere($("#notiz-text b").firstChild, 6, 9);   /* „und“ */
  werkzeuge[0].click();
  assert.strictEqual(T.daten().notizen[1].html, "<b>Milch </b>und<b> Brot</b>",
    "Teilbereich unerwartet: " + T.daten().notizen[1].html);

  /* Fremdes <strong> wird ebenso aufgehoben */
  $("#notiz-text").innerHTML = "<strong>Fett</strong>";
  $("#notiz-text").dispatchEvent(new w.Event("input", { bubbles: true }));
  markiere($("#notiz-text strong").firstChild, 0, 4);
  werkzeuge[0].click();
  assert.strictEqual(T.daten().notizen[1].html, "Fett",
    "strong nicht aufgehoben: " + T.daten().notizen[1].html);

  /* Tastenkürzel Strg+B wirken ebenfalls */
  $("#notiz-text").innerHTML = "Zettel";
  $("#notiz-text").dispatchEvent(new w.Event("input", { bubbles: true }));
  $("#notiz-text").focus();
  markiere($("#notiz-text").firstChild, 0, 6);
  d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "b", code: "KeyB", ctrlKey: true, bubbles: true, cancelable: true }));
  assert.ok(/<b>Zettel<\/b>/.test(T.daten().notizen[1].html),
    "Strg+B wirkt nicht: " + T.daten().notizen[1].html);
  d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "d", code: "KeyD", ctrlKey: true, bubbles: true, cancelable: true }));
  assert.ok(/<s>/.test(T.daten().notizen[1].html),
    "Strg+D wirkt nicht: " + T.daten().notizen[1].html);
  d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "d", code: "KeyD", ctrlKey: true, bubbles: true, cancelable: true }));
  assert.ok(!/<s>/.test(T.daten().notizen[1].html),
    "Strg+D hebt nicht wieder auf: " + T.daten().notizen[1].html);

  /* Unerwünschte Auszeichnungen werden beim Einlesen entfernt */
  const gesaeubert = T.saeubereHtml(
    '<b onclick="boes()">fett</b><script>boes()</script><span style="x">rein</span>' +
    '<img src=x><i>kursiv</i>');
  assert.strictEqual(gesaeubert, "<b>fett</b><span>rein</span><i>kursiv</i>",
    "Reinigung unerwartet: " + gesaeubert);
  const links = T.saeubereHtml(
    '<a href="https://example.org" onclick="x()">sicher</a>' +
    '<a href="javascript:boese()">unsicher</a>');
  assert.ok(links.includes('href="https://example.org"') &&
    !links.includes("javascript:") && !links.includes("onclick"),
    "sichere Notizlinks werden nicht korrekt bereinigt: " + links);
  const verschachtelt = T.saeubereHtml(
    '<fremd onclick="x()"><b>bleibt</b><script><i>weg</i></script>' +
    '<svg><a href="https://boese.test">weg</a></svg></fremd>');
  assert.strictEqual(verschachtelt, "<b>bleibt</b>",
    "unbekannte Hüllen oder aktive Namensräume umgehen die Reinigung: " + verschachtelt);
  const zuGrossesHtml = "<span>x</span>".repeat(10001);
  const grenzStand = {};
  T.saeubereHtml(zuGrossesHtml, grenzStand);
  assert.strictEqual(grenzStand.gekuerzt, true,
    "die HTML-Grenze wird dem Aufrufer nicht gemeldet");
  assert.strictEqual(T.normalisiere({ notizen: [{ id: "gross", titel: "Groß",
    text: "x", html: zuGrossesHtml }] }).notizen[0].html, zuGrossesHtml,
  "die Normalisierung ersetzt eine übergroße Notiz durch die gekürzte Ansicht");
  const htmlVorGrenze = neue.html;
  schreibflaeche.innerHTML = zuGrossesHtml;
  schreibflaeche.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.strictEqual(neue.html, htmlVorGrenze,
    "eine gekürzte übergroße Notiz wurde in den Daten gespeichert");
  schreibflaeche.innerHTML = htmlVorGrenze;
  neue.html = zuGrossesHtml;
  T.wechsel("kalender");
  T.wechsel("notizen");
  assert.strictEqual($("#notiz-text").getAttribute("contenteditable"), "false",
    "eine übergroße gespeicherte Notiz bleibt ohne Schutz bearbeitbar");
  assert.ok($(".notiz-editor .einst-warnung") &&
    $(".notiz-editor .einst-warnung").textContent.trim(),
  "bei einer übergroßen Notiz fehlt die sichtbare Warnung");
  assert.strictEqual(neue.html, zuGrossesHtml,
    "das Öffnen einer übergroßen Notiz verändert das gespeicherte Original");
  neue.html = htmlVorGrenze;
  T.wechsel("kalender");
  T.wechsel("notizen");

  setze($("#notiz-suche"), "Einkauf");
  assert.ok($("#inhalt-links").textContent.includes("Einkauf"),
    "Notizsuche findet den Titel nicht");
  setze($("#notiz-suche"), "Lose Notizen");
  assert.ok($("#inhalt-links").textContent.includes("Lose Notizen"),
    "Notizsuche findet das Notizbuch nicht");
  setze($("#notiz-suche"), "");

  neue.anhaenge.push(
    { id: "bild-1", name: "Plan.png", art: "image",
      daten: "data:image/png;base64,iVBORw0KGgo=" },
    { id: "pdf-1", name: "Unterlagen.pdf", art: "pdf",
      daten: "data:application/pdf;base64,JVBERi0xLjQ=" });
  neue.anhaenge.push(...geleseneAnhaenge);
  T.wechsel("kalender");
  T.wechsel("notizen");
  assert.ok($(".notiz-anhang.image img"), "eingebettetes Notizbild fehlt");
  assert.ok(!$(".notiz-anhang.pdf object") && $(".notiz-anhang.pdf button"),
  "PDF-Dateien müssen ohne aktives Einbettungsobjekt bedienbar bleiben");
  for (const anhang of geleseneAnhaenge) {
    const karte = Array.from($$(".notiz-anhang"))
      .find((element) => element.querySelector(".notiz-anhang-name")?.textContent === anhang.name);
    assert.ok(karte && !karte.querySelector("a[href], [download]") &&
      (anhang.art === "pdf" || karte.querySelector("img")?.src === anhang.daten),
    "persistierter Anhang wird nicht kanonisch angezeigt: " + anhang.name);
  }
  assert.strictEqual($$(".notiz-anhang-symbol").length, 2 + geleseneAnhaenge.length,
    "für kleine Anhangsbereiche fehlen die kompakten Bild- und PDF-Symbole");
  assert.strictEqual(d.querySelectorAll(".notiz-anhang a[href], .notiz-anhang [download]").length,
    0, "Notizanhänge dürfen keine Data-URL-Navigation oder Downloads besitzen");
  assert.ok($(".notiz-anhang-teiler"),
    "der Anhangsbereich besitzt keinen ziehbaren Trenngriff");
  $(".notiz-anhang-teiler").dispatchEvent(new w.MouseEvent("pointerdown",
    { bubbles: true, button: 0, clientY: 100 }));
  d.dispatchEvent(new w.MouseEvent("pointerup",
    { bubbles: true, button: 0, clientY: 180 }));
  assert.ok($(".notiz-anhaenge").classList.contains("kompakt") &&
    parseInt($(".notiz-anhaenge").style.height, 10) <= 125,
  "nach unten Ziehen verkleinert die Anhänge nicht zur Symbolansicht");
  assert.ok(T.daten().einstellungen.allgemein.notizAnhangHoehe <= 125,
    "die gewählte Anhangshöhe wird nicht gespeichert");
  assert.ok(/\.notiz-anhang figcaption \.knopf[^}]*white-space:\s*nowrap/.test(css),
    "der Entfernen-Knopf darf nicht umbrechen");
  const anhangAnzahlVorFehler = neue.anhaenge.length;
  knopfMit("Bild").click();
  assert.ok($("#eingabe-schleier .eingabe-datei-knopf"),
    "vor dem Betriebssystem-Dateiwähler fehlt der Magnolie-Dialog");
  const falscheDatei = new w.File([
    new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], "umbenannt.png",
  { type: "image/png" });
  const anhangEingabe = $("#eingabe-schleier input[type='file']");
  Object.defineProperty(anhangEingabe, "files", { value: [falscheDatei] });
  anhangEingabe.dispatchEvent(new w.Event("change", { bubbles: true }));
  knopfMit("Einbetten", $("#eingabe-schleier")).click();
  for (let i = 0; i < 20 && $("#zettel").textContent !==
      "Die Datei hat ein nicht unterstütztes Format."; i++) await tick();
  assert.strictEqual(neue.anhaenge.length, anhangAnzahlVorFehler,
  "eine abgewiesene umbenannte Datei verändert den vorhandenen Notizzustand");
  assert.strictEqual($("#zettel").textContent,
    "Die Datei hat ein nicht unterstütztes Format.",
    "eine abgewiesene umbenannte Datei meldet den Signaturfehler nicht");

  knopfMit("Link").click();
  await tick();
  const linkFeld = $("#eingabe-feld");
  linkFeld.setSelectionRange(0, linkFeld.value.length);
  linkFeld.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 820, clientY: 540 }));
  assert.ok($("#vorschlags-menue") &&
    $("#vorschlags-menue").classList.contains("bearbeiten-menue"),
    "Bearbeiten-Menü im Linkdialog fehlt");
  assert.ok(/\.vorschlags-menue[\s\S]{0,100}z-index:\s*160/.test(css),
    "Bearbeiten-Menü liegt nicht über dem Eingabedialog");
  knopfMit("Kopieren", $("#vorschlags-menue")).click();
  knopfMit("Abbrechen", $("#eingabe-schleier")).click();

  $("#ecke-links").click(); /* zurück zur Willkommensseite */
  assert.ok($("#notiz-titel").value.includes("Willkommen"));

  /* Ohne Markierung haben die Rechtschreibvorschläge Vorrang */
  T.daten().einstellungen.schrift.rechtschreibung = true;
  klickeTab("Notizen");
  const rsBlatt = $("#notiz-text");
  rsBlatt.innerHTML = "Milhc";
  rsBlatt.dispatchEvent(new w.Event("input", { bubbles: true }));
  const wegAuswahl = w.getSelection();
  if (wegAuswahl) wegAuswahl.removeAllRanges();
  rsBlatt.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 90, clientY: 90 }));
  assert.ok($("#vorschlags-menue"), "gar kein Menü erschienen");
  /* Meldet die Prüfung „richtig geschrieben“, gehört dort das
     Bearbeiten-Menü hin – ein Hinweis nützt niemandem. */
  w.App.vorschlaege({ kennung: T.kennung(), wort: "Milch", richtig: true,
    vorschlaege: [], fehler: "" });
  assert.ok($("#vorschlags-menue") &&
    $("#vorschlags-menue").classList.contains("bearbeiten-menue"),
    "bei richtig geschriebenem Wort fehlt das Bearbeiten-Menü");
  assert.ok($$("#vorschlags-menue .vm-eintrag")
    .some((e) => e.textContent === "Einfügen"),
    "Einfügen muss auch ohne Markierung angeboten werden");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

  /* Mit Markierung erscheint das Bearbeiten-Menü */
  const rsBereich = d.createRange();
  rsBereich.setStart(rsBlatt.firstChild, 0);
  rsBereich.setEnd(rsBlatt.firstChild, 5);
  const rsAuswahl = w.getSelection();
  rsAuswahl.removeAllRanges();
  rsAuswahl.addRange(rsBereich);
  rsBlatt.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 90, clientY: 90 }));
  assert.ok($("#vorschlags-menue") &&
    $("#vorschlags-menue").classList.contains("bearbeiten-menue"),
    "mit Markierung fehlt das Bearbeiten-Menü");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

  /* Ohne Rechtschreibprüfung bleibt das Bearbeiten-Menü */
  T.daten().einstellungen.schrift.rechtschreibung = false;
  if (w.getSelection()) w.getSelection().removeAllRanges();
  rsBlatt.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 90, clientY: 90 }));
  assert.ok($("#vorschlags-menue") &&
    $("#vorschlags-menue").classList.contains("bearbeiten-menue"),
    "ohne Rechtschreibprüfung fehlt das Bearbeiten-Menü");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  T.daten().einstellungen.schrift.rechtschreibung = true;

  /* ---- Rechtschreibvorschläge im eigenen Menü ---- */
  const wortProbe = (text, stelle) => {
    const e = T.wortAnStelle(text, stelle);
    return [e.wort, e.von, e.bis];
  };
  assert.deepStrictEqual(wortProbe("Milch und Brot", 2), ["Milch", 0, 5],
    "Wort am Anfang");
  assert.deepStrictEqual(wortProbe("Milch und Brot", 10), ["Brot", 10, 14],
    "Wort am Ende");
  assert.strictEqual(T.wortAnStelle("Grüße für Müller-Lüdenscheidt", 3).wort,
    "Grüße", "Umlaute gehören zum Wort");
  assert.strictEqual(T.wortAnStelle("Milch  Brot", 6).wort, "",
    "zwischen zwei Wörtern kein Treffer");

  /* Menü aufbauen und mit einer Antwort füllen */
  klickeTab("Notizen");
  const blatt = $("#notiz-text");
  blatt.innerHTML = "Milhc kaufen";
  blatt.dispatchEvent(new w.Event("input", { bubbles: true }));
  T.setzeVorschlagsStelle({ art: "flaeche", knoten: blatt.firstChild,
    flaeche: blatt, von: 0, bis: 5 });
  T.zeigeVorschlagsMenue(120, 90, "Milhc");
  const menue = $("#vorschlags-menue");
  assert.ok(menue, "Vorschlagsmenü erscheint nicht");
  assert.ok(menue.querySelector(".vm-laden"), "Wartehinweis fehlt");
  assert.strictEqual(menue.querySelector(".vm-kopf").textContent, "Milhc",
    "Das geprüfte Wort steht nicht im Kopf");

  w.App.vorschlaege({ kennung: T.kennung(), wort: "Milhc", richtig: false,
    vorschlaege: ["Milch", "Molch"], fehler: "" });
  const eintraege = $$("#vorschlags-menue .vm-eintrag");
  assert.strictEqual(eintraege.length, 4,
    "zwei Vorschläge, Einfügen und der Wörterbuch-Eintrag erwartet");
  assert.ok(eintraege.some((e) => e.textContent === "Einfügen"),
    "auch aus dem Vorschlagsmenü soll sich einfügen lassen");
  assert.deepStrictEqual(eintraege.slice(0, 2).map((e) => e.textContent),
    ["Milch", "Molch"], "Vorschläge unerwartet");
  assert.ok(eintraege[3].textContent.includes("Wörterbuch"),
    "Eintrag zum Aufnehmen fehlt");
  assert.ok(!$("#vorschlags-menue .vm-laden"), "Wartehinweis bleibt stehen");

  /* Auswahl ersetzt das Wort und schließt das Menü */
  eintraege[0].click();
  assert.strictEqual($("#notiz-text").textContent, "Milch kaufen",
    "Wort nicht ersetzt: " + $("#notiz-text").textContent);
  assert.ok(T.daten().notizen.some((n) => n.text === "Milch kaufen"),
    "Ersetzung nicht gespeichert");
  assert.ok(!$("#vorschlags-menue"), "Menü bleibt nach der Wahl offen");

  /* Späte Antwort auf eine ältere Frage wird nicht mehr eingehängt */
  T.setzeVorschlagsStelle({ art: "flaeche", knoten: $("#notiz-text").firstChild,
    flaeche: $("#notiz-text"), von: 0, bis: 5 });
  T.zeigeVorschlagsMenue(120, 90, "Milch");
  w.App.vorschlaege({ kennung: "999", wort: "alt", richtig: false,
    vorschlaege: ["Veraltet"], fehler: "" });
  assert.strictEqual($$("#vorschlags-menue .vm-eintrag").length, 0,
    "veraltete Antwort landet im Menü");

  /* Richtig geschriebenes Wort: statt eines Hinweises kommt das
     Bearbeiten-Menü, damit sich wenigstens einfügen lässt. */
  w.App.vorschlaege({ kennung: T.kennung(), wort: "Milch", richtig: true,
    vorschlaege: [], fehler: "" });
  assert.ok($("#vorschlags-menue") &&
    $("#vorschlags-menue").classList.contains("bearbeiten-menue"),
    "bei richtigem Wort fehlt das Bearbeiten-Menü");
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.ok(!$("#vorschlags-menue"), "Escape schließt das Menü nicht");

  /* In einem Eingabefeld wird ebenso ersetzt */
  klickeTab("Jahrestage");
  assert.strictEqual($("#kopf-links h2").textContent, "Jahrestage",
    "deutsche Jahrestagsüberschrift fehlt");
  assert.strictEqual($("#kopf-rechts h2").textContent, "Neuer Jahrestag",
    "deutscher Jahrestagskopf fehlt");
  assert.deepStrictEqual($$("#inhalt-rechts .feldname").map((label) => label.textContent),
    ["Name / Anlass", "Datum", "Art"],
  "deutsche Jahrestagsbeschriftungen fehlen");
  const namensfeld = $("#inhalt-rechts fieldset input[type=text]");
  setze(namensfeld, "Anna Beispeil");
  T.setzeVorschlagsStelle({ art: "feld", feld: namensfeld, von: 5, bis: 13 });
  T.zeigeVorschlagsMenue(100, 100, "Beispeil");
  w.App.vorschlaege({ kennung: T.kennung(), wort: "Beispeil", richtig: false,
    vorschlaege: ["Beispiel"], fehler: "" });
  $("#vorschlags-menue .vm-eintrag").click();
  assert.strictEqual(namensfeld.value, "Anna Beispiel",
    "Feldinhalt nicht ersetzt: " + namensfeld.value);
  klickeTab("Jahrestage");
  setze($("#inhalt-rechts fieldset input[type=text]"), "Anna Beispiel");
  assert.strictEqual($("#jt-typ").tagName, "INPUT",
    "Jahrestagsarten müssen direkt beschreibbar sein");
  assert.strictEqual($("#jt-typ").value, "",
    "ein neuer Jahrestag darf nicht als Geburtstag vorausgewählt sein");
  assert.strictEqual($("#jt-typ").placeholder, "z.B. Geburtstag",
    "der Jahrestagsplatzhalter stimmt nicht");
  assert.ok($("#jt-typen-vorschlaege") &&
    Array.from($("#jt-typen-vorschlaege").options).some((o) => o.value === "Todestag"),
    "Vorschläge für Jahrestagsarten fehlen");
  const heute = new Date();
  const iso = heute.getFullYear() - 30 + "-" +
    String(heute.getMonth() + 1).padStart(2, "0") + "-" +
    String(heute.getDate()).padStart(2, "0");
  setze($("#inhalt-rechts fieldset .datumsfeld"), iso);
  for (const ziffer of "03041987") {
    $("#jt-datum").dispatchEvent(new w.KeyboardEvent("keydown",
      { key: ziffer, bubbles: true, cancelable: true }));
  }
  await tick();
  assert.strictEqual($("#jt-datum").value, "03.04.1987",
    "achtstellig getipptes Jahrestagsdatum wird nicht vollständig übernommen");
  assert.strictEqual(T.datumswert($("#jt-datum")), "1987-04-03",
    "achtstellig getipptes Jahrestagsdatum wird intern nicht normalisiert");
  setze($("#jt-datum"), "");
  $("#jt-datum").setSelectionRange(0, 0);
  $("#jt-datum").dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  for (const ziffer of "2902") {
    $("#jt-datum").dispatchEvent(new w.KeyboardEvent("keydown",
      { key: ziffer, bubbles: true, cancelable: true }));
  }
  assert.strictEqual($("#jt-datum").value, "29.02.",
    "Jahrestag ohne bekanntes Jahr wird nicht ohne Jahr angezeigt");
  assert.strictEqual(T.datumswert($("#jt-datum")), "--02-29",
    "Jahrestag ohne bekanntes Jahr erhält kein kanonisches Teildatum");
  setze($("#jt-datum"), iso);
  setze($("#jt-typ"), "Geburtstag");
  knopfMit("Eintragen").click();
  assert.strictEqual(T.daten().jahrestage.length, 3,
    "manueller Jahrestag und Kontaktjahrestage fehlen");
  assert.ok($("#inhalt-links").textContent.includes("heute!"), "»heute!«-Hinweis fehlt");
  assert.ok($("#inhalt-links").textContent.includes("wird 30"), "Altersangabe fehlt");

  setze($("#jt-name"), "Großvater");
  setze($("#jt-datum"), "1987-04-03");
  setze($("#jt-typ"), "Todestag");
  knopfMit("Eintragen").click();
  const todestag = T.daten().jahrestage.find((j) => j.name === "Großvater");
  assert.ok(todestag && todestag.typ === "death-anniversary",
    "Todestag lässt sich nicht als Jahrestagsart eintragen");
  const todestagHeute = heute.getFullYear() - 20 + "-" +
    String(heute.getMonth() + 1).padStart(2, "0") + "-" +
    String(heute.getDate()).padStart(2, "0");
  setze($("#jt-name"), "Peter");
  setze($("#jt-datum"), todestagHeute);
  setze($("#jt-typ"), "Todestag");
  knopfMit("Eintragen").click();

  /* Jahrestag muss im Kalender auftauchen */
  klickeTab("Kalender");
  assert.ok($(".kal-tag.heute .jt-stern"), "Stern im Kalender fehlt");
  assert.ok($(".ue-jahrestag"),
    "Jahrestag fehlt in der Terminübersicht");
  /* und ebenso in der Tagesansicht */
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "day").click();
  assert.ok($(".jt-kasten"), "Jahrestags-Kasten in der Tagesansicht fehlt");
  const tagesJahrestage = $(".jt-kasten").textContent;
  assert.ok(tagesJahrestage.includes("Geburtstag") &&
    !tagesJahrestage.includes("birthday"),
  "die Tagesansicht übersetzt den gespeicherten Geburtstagstyp nicht");
  assert.ok(tagesJahrestage.includes("Peter (20. Todestag)") &&
    !tagesJahrestage.includes("death-anniversary") &&
    !tagesJahrestage.includes("Peter – Todestag"),
  "der Todestag ist in der Tagesansicht nicht übersetzt oder doppelt beschriftet");
  assert.ok($$(".tages-spalte").length === 2,
    "die Tagesansicht zeigt nicht zwei Tage");
  assert.ok($$("#inhalt-links .stunden-reihe").length > 10,
    "die Stundenleiste fehlt");
  assert.ok(/^\d{2}:\d{2}$/.test($("#inhalt-links .stunden-marke").textContent),
    "Zeitangaben fehlen am linken Rand");
  assert.ok($(".tages-neu"), "Knopf zum Hinzufügen fehlt");
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();
  T.daten().einstellungen.regional.firstDayOfWeek = "saturday";
  T.wechsel("aufgaben");
  T.wechsel("kalender");
  assert.ok($(".kal-wt").textContent.startsWith("Sa") &&
    T.wochenbeginnVon("2026-08-05").getDay() === 6,
  "Samstagsbeginn wird im Monatsraster und Wochenbereich angewandt");
  T.daten().einstellungen.regional.firstDayOfWeek = "monday";
  T.wechsel("aufgaben");
  T.wechsel("kalender");

  /* ---- Planer ---- */
  klickeTab("Planer");
  assert.strictEqual($$(".mini-monat").length, 12, "12 Minimonate erwartet");
  assert.strictEqual($("#kopf-links h2").textContent,
    "Jahresplaner " + T.zustand().planer.jahr, "deutsche Planerüberschrift fehlt");
  assert.strictEqual($("#kopf-links .kopf-neben").textContent, "Januar – Juni");
  assert.strictEqual($("#kopf-rechts .kopf-neben").textContent, "Juli – Dezember");
  assert.deepStrictEqual($$(".mm-titel").map((element) => element.textContent),
    ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
      "September", "Oktober", "November", "Dezember"],
  "deutsche Planermonate fehlen");
  assert.deepStrictEqual(Array.from($(".mini-monat").querySelectorAll(".mm-wt"),
    (element) => element.textContent),
  ["M", "D", "M", "D", "F", "S", "S"], "deutsche Wochentage fehlen");
  const jahrPfeile = $$("#kopf-links .pfeil");
  assert.strictEqual(jahrPfeile[0].title, "Voriges Jahr");
  assert.strictEqual(jahrPfeile[1].title, "Nächstes Jahr");
  assert.strictEqual($("#ecke-links").title, "Voriges Jahr");
  assert.strictEqual($("#ecke-rechts").title, "Nächstes Jahr");
  assert.ok($(".mm-tag.hat"), "Termin-Markierung im Planer fehlt");
  assert.ok($(".mm-tag.heute"), "Heute-Markierung im Planer fehlt");
  assert.strictEqual($$(".mm-kw").length, 0,
    "Wochennummern müssen im Planer voreingestellt ausgeblendet sein");
  assert.strictEqual($$("#register-links .registerknopf").length, 5, "Planer: 5 Tabs links");
  const jahrDirekt = T.zustand().planer.jahr;
  knopfMit("Jahr wählen …").click();
  setze($("#eingabe-feld"), "2040");
  knopfMit("Jahr aufschlagen", $("#eingabe-schleier")).click();
  await tick();
  assert.strictEqual(T.zustand().planer.jahr, 2040,
    "direkte Jahreswahl im Planer wirkt nicht");
  T.zustand().planer.jahr = jahrDirekt;
  T.wechsel("kalender");
  T.wechsel("planer");
  const jahrStart = T.zustand().planer.jahr;
  const jahrVor = $$("#kopf-links .pfeil")[1];
  jahrVor.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 720));
  w.dispatchEvent(new w.Event("pointerup"));
  assert.ok(T.zustand().planer.jahr - jahrStart >= 2,
    "langes Drücken blättert den Jahresplaner nicht schnell weiter");
  T.zustand().planer.jahr = jahrStart;
  T.wechsel("kalender");
  T.wechsel("planer");
  const heuteMini = $(".mm-tag.heute");
  heuteMini.click();
  assert.strictEqual(T.zustand().sektion, "kalender", "Planer-Klick springt nicht zum Kalender");
  T.zustand().planer.jahr = 1800;
  klickeTab("Planer");
  assert.ok(!$(".mm-tag.jt"),
    "Jahrestag wird vor seinem Ausgangsjahr im Planer markiert");
  T.zustand().planer.jahr = new Date().getFullYear();
  klickeTab("Kalender");

  /* ---- Speichern über den Browser-Ersatzspeicher ---- */
  T.speichereJetzt();
  const gespeichert = JSON.parse(w.localStorage.getItem("magnolie-organizer-daten"));
  assert.strictEqual(gespeichert.kontakte.length, 1, "Speicherung unvollständig");
  assert.ok($("#status-speicher").textContent.includes("Gespeichert"));

  /* ---- Tastatur: Strg+4 → Notizen ---- */
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "4", ctrlKey: true, bubbles: true }));
  assert.strictEqual(T.zustand().sektion, "notizen", "Strg+4 wechselt nicht");

  /* ================= Magnolie 1.1 ================= */

  /* ---- Neuer Name und Einstellungen-Knopf ---- */
  assert.ok(d.title.includes("Magnolie"), "Fenstertitel ohne Magnolie");
  assert.ok($(".praegeblume"), "Prägeblume auf dem Deckel fehlt");
  assert.ok(/\.deckel-rueck\s*\{[\s\S]{0,100}display:\s*none/.test(css),
    "der MATE-sichere Deckel-Fallback fehlt");
  assert.ok($("#knopf-einstellungen"), "Einstellungen-Knopf fehlt");

  /* ---- Wochenansicht ---- */
  klickeTab("Kalender");
  assert.strictEqual(T.zustand().kalender.ansicht, "month", "Start nicht im Monat");
  assert.strictEqual($$(".u-knopf").length, 3, "drei Ansichten erwartet");
  $$(".u-knopf").find((b) => b.textContent === "Woche").click();
  assert.strictEqual(T.zustand().kalender.ansicht, "week", "Umschalten auf Woche");
  assert.strictEqual($$(".wo-tag").length, 7, "7 Tageskästen erwartet");
  assert.ok($("#kopf-links h2").textContent.includes("Woche"), "KW-Überschrift fehlt");
  const unter = $("#kopf-links h2 .kopf-unter");
  assert.ok(unter, "Datumsspanne steht nicht als Unterzeile im Titel");
  assert.ok(/^\d{2}\.\d{2}\. – \d{2}\.\d{2}\.\d{4}$/.test(unter.textContent),
    "Datumsspanne unerwartet: " + unter.textContent);
  assert.strictEqual($$("#kopf-links .kopf-neben").length, 0,
    "Datumsspanne darf nicht mehr neben dem Titel stehen");
  assert.ok($(".wo-tag.heute"), "Heute-Kasten fehlt");
  assert.ok(/\.wo-tag\.heute::after\s*\{[\s\S]{0,180}border:\s*2px solid var\(--rot\)/.test(css) &&
    !/\.wo-tag\.heute\s*\{[\s\S]{0,100}box-shadow/.test(css),
  "der Heute-Rahmen der Woche kann weiterhin in den Folgetag hinein fragmentieren");

  const tagVorher = T.zustand().kalender.tag;
  $("#ecke-rechts").click();
  const tagNachher = T.zustand().kalender.tag;
  const diffTage = Math.round((new Date(tagNachher) - new Date(tagVorher)) / 86400000);
  assert.strictEqual(diffTage, 7, "Eselsohr blättert nicht eine Woche vor");
  knopfMit("Heute").click();
  assert.strictEqual(T.zustand().kalender.tag, tagVorher, "Heute-Knopf in der Woche");
  const wocheStart = T.zustand().kalender.tag;
  const wocheVor = $$("#kopf-links .pfeil")[1];
  wocheVor.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 720));
  w.dispatchEvent(new w.Event("pointerup"));
  assert.ok(Math.round((new Date(T.zustand().kalender.tag) -
    new Date(wocheStart)) / 86400000) >= 14,
  "langes Drücken blättert die Woche nicht schnell weiter");
  knopfMit("Heute").click();

  /* Voreingestellt legt ein Klick auf eine freie Stelle gleich einen
     Termin an. */
  assert.strictEqual(T.daten().einstellungen.kalender.klickLegtAn, true,
    "„gleich anlegen“ soll voreingestellt sein");
  $(".wo-tag").click();
  assert.ok($("#termin-schleier"),
    "der Klick auf einen freien Tag öffnet kein Terminblatt");
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  /* Mit der anderen Wahl wird stattdessen der Tag aufgeschlagen */
  T.daten().einstellungen.kalender.klickLegtAn = false;
  $(".wo-tag").click();
  assert.strictEqual(T.zustand().kalender.ansicht, "day",
    "der Klick auf einen Tag führt nicht in die Tagesansicht");
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();
  T.daten().einstellungen.kalender.klickLegtAn = true;

  /* Der Überlauf ist selbst kein freier Bereich: Er öffnet immer den Tag,
     auch wenn freie Kalenderflächen sofort einen neuen Termin anlegen. */
  const ueberlaufDatum = "2026-08-06";
  for (let i = 1; i <= 5; i++) {
    T.oeffneTerminBlatt(null, ueberlaufDatum);
    setze($("#tb-titel"), "Überlaufprobe " + i);
    $("#tb-fertig").click();
    await tick();
  }
  T.zustand().kalender.jahr = Number(ueberlaufDatum.slice(0, 4));
  T.zustand().kalender.monat = Number(ueberlaufDatum.slice(5, 7)) - 1;
  T.zustand().kalender.tag = ueberlaufDatum;
  T.wechsel("aufgaben");
  T.wechsel("kalender");
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "week").click();
  const ueberlaufTag = $$(".wo-tag").find((tag) =>
    Number(tag.querySelector(".wo-nr").textContent) === Number(ueberlaufDatum.slice(8)));
  const mehrTermine = ueberlaufTag && ueberlaufTag.querySelector(".wo-mehr");
  assert.ok(mehrTermine && /^\+\d+/.test(mehrTermine.textContent),
    "der Wochenüberlauf wird nicht als eigener Bedienknopf angezeigt");
  mehrTermine.click();
  assert.strictEqual(T.zustand().kalender.ansicht, "day",
    "der Wochenüberlauf wechselt nicht in die Tagesansicht");
  assert.strictEqual(T.zustand().kalender.tag, ueberlaufDatum,
    "der Wochenüberlauf öffnet den falschen Tag");
  assert.strictEqual($("#termin-schleier"), null,
    "der Wochenüberlauf legt fälschlich einen neuen Termin an");
  T.daten().termine = T.daten().termine.filter(
    (termin) => !String(termin.titel || "").startsWith("Überlaufprobe "));
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();

  /* Ein Klick auf einen Termin im Raster öffnet diesen zum Bearbeiten */
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  setze($("#tb-titel"), "Rasterprobe");
  $("#tb-fertig").click();
  await tick();
  const miniTermin = $$(".kal-tag.gewaehlt .mini-termin")
    .find((m) => m.textContent.includes("Rasterprobe"));
  assert.ok(miniTermin, "der Termin steht nicht anklickbar im Raster");
  miniTermin.click();
  assert.ok($("#termin-schleier"), "Klick auf den Termin öffnet kein Blatt");
  assert.strictEqual($("#tb-titel").value, "Rasterprobe");
  knopfMit("Abbrechen", $("#termin-schleier")).click();
  T.daten().termine = T.daten().termine.filter((x) => x.titel !== "Rasterprobe");
  T.planeSpeichern();
  T.wechsel("notizen");
  klickeTab("Kalender");
  assert.ok($(".termin-uebersicht"),
    "nach der Rückkehr fehlt die Terminübersicht");

  /* ---- Mausrad, Vorgabezeiten und Mindestabstand ---- */
  const tippeDatum = async (feld, ziffern) => {
    for (const ziffer of String(ziffern)) feld.dispatchEvent(new w.KeyboardEvent(
      "keydown", { key: ziffer, bubbles: true, cancelable: true }));
    await tick();
  };
  const rad = (elm, dy, shift) => elm.dispatchEvent(new w.WheelEvent("wheel",
    { deltaY: dy, shiftKey: !!shift, bubbles: true, cancelable: true }));
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  const zeitFelder = [$("#tb-zeit"), $("#tb-endzeit")];
  assert.ok(zeitFelder[0] && zeitFelder[1], "Beginn- und Endzeitfeld erwartet");
  const [von, bis] = zeitFelder;
  const minuten = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
  assert.ok(/^\d{2}:\d{2}$/.test(von.value), "Beginn ohne Vorgabezeit: " + von.value);
  assert.ok(/^\d{2}:\d{2}$/.test(bis.value), "Ende ohne Vorgabezeit: " + bis.value);
  assert.strictEqual(minuten(von.value) % 15, 0, "Vorgabe liegt nicht auf der Viertelstunde");
  assert.strictEqual(minuten(bis.value) - minuten(von.value), 30,
    "Vorgabe-Dauer ist nicht eine halbe Stunde");
  assert.strictEqual(T.datumswert($("#tb-datum-von")), T.zustand().kalender.tag,
    "Anfangsdatum des Terminblatts");
  assert.strictEqual(T.datumswert($("#tb-datum-bis")), T.zustand().kalender.tag,
    "Enddatum ist zunächst der Anfangstag");
  const datumVorEingabetest = T.datumswert($("#tb-datum-von"));
  await tippeDatum($("#tb-datum-von"), "11021982");
  assert.strictEqual($("#tb-datum-von").value, "11.02.1982",
    "achtstellige Datumseingabe TTMMJJJJ wird nicht übernommen");
  assert.strictEqual(T.datumswert($("#tb-datum-von")), "1982-02-11",
    "achtstellige Datumseingabe wird intern nicht als ISO gespeichert");
  setze($("#tb-datum-von"), "");
  $("#tb-datum-von").setSelectionRange(0, 0);
  $("#tb-datum-von").dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  await tippeDatum($("#tb-datum-von"), "1102");
  assert.strictEqual(T.datumswert($("#tb-datum-von")),
    T.isoHeute().slice(0, 4) + "-02-11",
    "vierstellige Datumseingabe ergänzt nicht das aktuelle Jahr");
  assert.strictEqual($("#tb-datum-von").selectionStart, 6,
    "nach Tag und Monat ist das Jahressegment nicht ausgewählt");
  $("#tb-datum-von").setSelectionRange(0, 2);
  $("#tb-datum-von").dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "Tab", bubbles: true, cancelable: true }));
  assert.deepStrictEqual([$("#tb-datum-von").selectionStart,
    $("#tb-datum-von").selectionEnd], [3, 5],
  "Tab wechselt nicht vom Tag- zum Monatssegment");
  setze($("#tb-datum-von"), "");
  $("#tb-datum-von").dispatchEvent(new w.FocusEvent("blur", { bubbles: true }));
  assert.strictEqual(T.datumswert($("#tb-datum-von")), T.isoHeute(),
    "ein leeres verpflichtendes Datum fällt nicht auf heute zurück");
  setze($("#tb-datum-von"), datumVorEingabetest);
  setze($("#tb-datum-bis"), datumVorEingabetest);

  setze(von, "09:00");
  setze(bis, "09:30");
  rad(von, 100);
  assert.strictEqual(von.value, "09:05", "Runterrollen = 5 Minuten später");
  assert.strictEqual(bis.value, "09:35", "Ende ist nicht mitgewandert");
  rad(von, -100);
  assert.strictEqual(von.value, "09:00", "Hochrollen = 5 Minuten früher");
  assert.strictEqual(bis.value, "09:30", "Ende wandert auch rückwärts mit");
  rad(von, 100, true);
  assert.strictEqual(von.value, "10:00", "Umschalt-Dreh = ganze Stunde");
  assert.strictEqual(bis.value, "10:30", "Ende hält die halbe Stunde Abstand");

  /* Endfeld dreht für sich, kann aber nicht vor den Beginn rutschen */
  rad(bis, 100);
  assert.strictEqual(bis.value, "10:35", "Endfeld dreht für sich allein");
  assert.strictEqual(von.value, "10:00", "Beginn bleibt beim Endfeld-Dreh stehen");
  for (let i = 0; i < 10; i++) rad(bis, -100);
  assert.strictEqual(bis.value, "10:00", "Ende darf nicht vor den Beginn rutschen");

  /* Das Endfeld bleibt beim Tippen unabhängig; Beginnänderungen halten die Dauer. */
  setze(von, "10:00");
  setze(bis, "17:45");
  assert.strictEqual(bis.value, "17:45",
    "direkte Eingabe im Endfeld wird durch den Beginn überschrieben");
  bis.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(bis.value, "17:45", "gültige Endzeit ändert sich beim Verlassen");
  setze(bis, "10:10");
  setze(von, "10:30");
  von.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(bis.value, "10:40",
    "Ende hält die Dauer bei getippter Anfangszeit genau einmal");

  /* ---- Ganztägig: Zeitfelder gesperrt, Termin ohne Uhrzeit ---- */
  const hakGanz = $("#tb-ganztaegig");
  assert.ok(hakGanz, "Schalter „ganztägig“ fehlt");
  assert.strictEqual(hakGanz.checked, false, "neuer Termin ist nicht ganztägig");
  hakGanz.checked = true;
  hakGanz.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok(von.disabled && bis.disabled, "Zeitfelder werden nicht gesperrt");
  const startGanz = T.datumswert($("#tb-datum-von"));
  const endeGanzDate = new Date(startGanz + "T12:00:00");
  endeGanzDate.setDate(endeGanzDate.getDate() + 2);
  const endeGanz = endeGanzDate.toISOString().slice(0, 10);
  setze($("#tb-datum-bis"), endeGanz);
  setze($("#tb-titel"), "Betriebsausflug");
  $("#tb-fertig").click();
  await tick();
  const ganz = T.daten().termine.find((t) => t.titel === "Betriebsausflug");
  assert.ok(ganz, "Ganztagstermin nicht angelegt");
  assert.strictEqual(ganz.zeit, "", "Ganztagstermin hat eine Uhrzeit");
  assert.strictEqual(ganz.endZeit, "", "Ganztagstermin hat eine Endzeit");
  assert.strictEqual(ganz.endDatum, endeGanz, "Enddatum des Ganztagstermins fehlt");
  assert.ok(T.termineAm(endeGanz).some((t) => t.id === ganz.id),
    "mehrtägiger Termin fehlt am letzten Tag");
  assert.ok($$(".ue-zeit").some((s) => s.textContent === "ganztägig"),
    "Vermerk „ganztägig“ fehlt in der Terminübersicht");

  /* Beim Bearbeiten steht der Schalter wieder richtig */
  $$(".ue-termin").find(
    (z2) => z2.textContent.includes("Betriebsausflug")).click();
  assert.strictEqual($("#tb-ganztaegig").checked, true,
    "Ganztagstermin öffnet ohne Haken");
  assert.ok($("#tb-zeit").disabled, "Zeitfelder müssten gesperrt sein");
  assert.strictEqual(T.datumswert($("#tb-datum-bis")), endeGanz,
    "Enddatum fehlt beim Bearbeiten");
  const anfangVorEingabetest = T.datumswert($("#tb-datum-von"));
  const endeVorEingabetest = T.datumswert($("#tb-datum-bis"));
  setze($("#tb-datum-von"), "1980" + anfangVorEingabetest.slice(4));
  await tippeDatum($("#tb-datum-bis"), "11021987");
  assert.strictEqual(T.datumswert($("#tb-datum-bis")), "1987-02-11",
    "achtstelliges Termin-Datum wird beim Bearbeiten nicht richtig übernommen");
  setze($("#tb-datum-von"), anfangVorEingabetest);
  setze($("#tb-datum-bis"), endeVorEingabetest);
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  /* ---- Termin mit Endzeit und Lotus-Feldern ---- */
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  setze($("#tb-zeit"), "09:00");
  setze($("#tb-endzeit"), "10:15");
  setze($("#tb-titel"), "Projektbesprechung");
  assert.ok($(".tb-aufklapper"), "Aufklapper für die Lotus-Felder fehlt");
  $(".tb-aufklapper").click();
  const hakVertraulich = $("#tb-vertraulich");
  assert.ok(hakVertraulich, "Haken „vertraulich“ fehlt");
  hakVertraulich.checked = true;
  setze($("#tb-kategorien"), "Geschäftlich");
  $("#tb-fertig").click();
  await tick();
  const neuer = T.daten().termine.find((t) => t.titel === "Projektbesprechung");
  assert.ok(neuer, "Termin mit Endzeit nicht angelegt");
  assert.strictEqual(neuer.zeit, "09:00");
  assert.strictEqual(neuer.endZeit, "10:15");
  assert.strictEqual(neuer.vertraulich, true, "Vertraulich-Haken nicht gespeichert");
  assert.ok(neuer.uid.startsWith("mag-"), "Sync-Kennung fehlt");
  assert.strictEqual(neuer.kategorien, "Geschäftlich",
    "Lotus-Feld nicht gespeichert");
  assert.ok($$(".ue-zeit").some((s) => s.textContent.includes("–")),
    "Zeitspanne fehlt in der Terminübersicht");
  assert.ok($("#inhalt-rechts .stempel.rot"), "Vertraulich-Stempel fehlt");

  /* ---- Löschvermerk für synchronisierte Termine ---- */
  neuer.sync = true;
  $$(".ue-termin").find(
    (z2) => z2.textContent.includes("Projektbesprechung")).click();
  $("#tb-loeschen").click();
  $("#dialog-ja").click();
  await tick();
  assert.ok(!T.daten().termine.find((t) => t.titel === "Projektbesprechung"),
    "Termin nicht gelöscht");
  assert.strictEqual(T.daten().geloescht.termine.length, 1, "Löschvermerk fehlt");
  assert.strictEqual(T.daten().geloescht.termine[0].uid, neuer.uid, "Falsche uid im Vermerk");

  /* ---- Einstellungen-Blatt mit eigenen Themenseiten ---- */
  T.oeffneEinstellungen();
  assert.ok(!$("#einstellungen-schleier").classList.contains("verborgen"),
    "Einstellungen öffnen nicht");
  const reiterKnoepfe = $$(".einst-reiter-knopf");
  assert.strictEqual(reiterKnoepfe.length, 12, "zwölf Reiter erwartet");
  assert.deepStrictEqual(reiterKnoepfe.map((b) => b.textContent),
    ["Allgemein", "Übernehmen", "Weitergeben", "Synchronisation", "Land & Feiertage",
      "Schrift", "Benachrichtigung", "Adressen", "Sicherheit", "Kalender",
      "Magnolienbaum", "Über"],
    "Reiterbeschriftungen");
  assert.ok(reiterKnoepfe[0].classList.contains("aktiv"), "erster Reiter nicht aktiv");

  /* Seite „Allgemein“ */
  assert.strictEqual($$("#einstellungen-inhalt h3").length, 1,
    "je Reiter nur ein Abschnitt");
  assert.ok($("#allgemein-drucken"), "allgemeine Druckeinstellung fehlt");
  assert.ok($("#allgemein-drucken").checked, "Drucken ist voreingestellt");
  assert.ok($("#allgemein-hilfsrahmen"), "Hilfsrahmen fehlt unter Allgemein");
  assert.strictEqual($("#allgemein-hilfsrahmen").checked, false,
    "der Hilfsrahmen ist nicht voreingestellt deaktiviert");
  assert.ok($("#einstellungen-inhalt").textContent.includes(
    "Barrierefreiheit: Hilfsrahmen") &&
    !$("#einstellungen-inhalt").textContent.includes(
      "Druckknopf auf der Karteikarte"),
  "Hilfsrahmenbeschriftung oder bereinigter Auswahlhinweis stimmt nicht");
  assert.strictEqual(d.body.dataset.hilfsrahmen, "aus",
    "die deaktivierte Voreinstellung wirkt nicht auf die Oberfläche");
  const barriereGruppe = $("#allgemein-gruppe-barrierefreiheit");
  const registerGruppe = $("#allgemein-gruppe-registerkarten");
  const trayGruppe = $("#allgemein-gruppe-tray");
  assert.ok(barriereGruppe && !barriereGruppe.open && registerGruppe && !registerGruppe.open &&
    trayGruppe && !trayGruppe.open &&
    !!(barriereGruppe.compareDocumentPosition(registerGruppe) & w.Node.DOCUMENT_POSITION_FOLLOWING) &&
    !!(registerGruppe.compareDocumentPosition(trayGruppe) & w.Node.DOCUMENT_POSITION_FOLLOWING),
  "Registerkarten stehen nicht als geschlossenes Aufklappmenü unter Barrierefreiheit");
  assert.deepStrictEqual(Array.from(registerGruppe.querySelectorAll("label"),
    (label) => label.textContent.trim()),
  ["Aufgaben", "Adressen", "Notizen", "Jahrestage", "Planer", "Gesundheit"],
  "die sechs optionalen Registerkarten sind nicht einzeln auswählbar");
  const registerAuswahl = registerGruppe.querySelector(".allgemein-register-auswahl");
  assert.ok(registerAuswahl && registerAuswahl.children.length === 6 &&
    /\.allgemein-register-auswahl\s*\{[\s\S]{0,120}flex-wrap:\s*wrap/.test(css),
  "die Registerkartenauswahl besitzt keine getrennte umbrechende Anordnung");

  $("#einst-tab-adressen").click();
  $(".einst-seite").scrollTop = 400;
  T.daten().einstellungen.allgemein.registerkarten.adressen = false;
  T.baueEinstellungen();
  await new Promise((resolve) => w.requestAnimationFrame(resolve));
  assert.strictEqual($(".einst-seite").id, "einst-seite-allgemein",
    "eine ausgeblendete Einstellungsseite wechselt nicht zu Allgemein");
  assert.strictEqual($(".einst-seite").scrollTop, 0,
    "die Rollposition einer ausgeblendeten Seite landet auf Allgemein");
  T.daten().einstellungen.allgemein.registerkarten.adressen = true;
  T.baueEinstellungen();

  const allgemeinSeite = $(".einst-seite");
  allgemeinSeite.scrollTop = 180;
  $("#allgemein-register-aufgaben").click();
  await new Promise((resolve) => w.requestAnimationFrame(resolve));
  assert.strictEqual($(".einst-seite").scrollTop, 180,
    "eine Einstellung auf derselben Seite setzt die Rollposition zurück");
  for (const id of ["adressen", "notizen", "jahrestage", "planer", "gesundheit"]) {
    $("#allgemein-register-" + id).click();
    assert.ok($("#allgemein-gruppe-registerkarten").open,
      "die Registerkartenauswahl klappt nach einer Änderung wieder zu");
  }
  assert.strictEqual($$(".registerknopf").length, 0,
    "der allein verbleibende Kalender besitzt weiterhin eine Registerkarte");
  assert.strictEqual($("#buch").dataset.registerAnzahl, "1",
    "die Registeranzahl wird bei allein sichtbarem Kalender nicht aktualisiert");
  assert.ok(!$("#einst-tab-adressen"),
    "die Adressoptionen bleiben trotz deaktivierter Adressregisterkarte sichtbar");
  $("#einst-tab-kalender").click();
  assert.ok(!$("#kalender-planer-wochennummern") &&
    !$("#kalender-vergangene-jahrestage") && !$("#kalender-gruppe-gesundheit"),
  "Optionen deaktivierter Registerkarten bleiben unter Kalender sichtbar");
  $("#einst-tab-export").click();
  assert.ok($("#gesamtarchiv-export"),
    "die Schaltfläche für den Gesamtarchiv-Export fehlt");
  assert.ok(!$("#einstellungen-inhalt").textContent.includes("Aufgaben (.ics)") &&
    !$("#einstellungen-inhalt").textContent.includes("Jahrestage (.ics)") &&
    !$("#einstellungen-inhalt").textContent.includes("Adressen (.vcf)"),
  "Exportaktionen deaktivierter Registerkarten bleiben sichtbar");
  $("#einst-tab-import").click();
  assert.ok($("#gesamtarchiv-import"),
    "die Schaltfläche für den Gesamtarchiv-Import fehlt");
  w.App.gesamtarchivAusgewaehlt({ ok: true, geprueft: true, pfad: "/tmp/probe.magnolie",
    plattform: "windows", appversion: "1.0.0", erstellt: "2026-08-11T12:34:56+00:00",
    anzahlen: { termine: 1, kontakte: 4 }, fotos: 4, anhaenge: 3 });
  assert.strictEqual($("#sicherung-bestaetigen").textContent, "Vollständig wiederherstellen",
    "die validierte Gesamtarchivvorschau fordert keinen vollständigen Ersatz an");
  $("#sicherung-abbrechen").click();
  $("#einst-tab-allgemein").click();
  for (const id of ["aufgaben", "adressen"]) $("#allgemein-register-" + id).click();
  assert.deepStrictEqual($$(".registerknopf").map((knopf) => knopf.textContent),
    ["Kalender", "Aufgaben", "Adressen"],
  "drei sichtbare Bereiche erzeugen nicht genau drei Registerkarten");
  assert.strictEqual($("#buch").dataset.registerAnzahl, "3",
    "die hohe Drei-Register-Darstellung wird nicht aktiviert");
  assert.ok(/data-register-anzahl="4"[\s\S]{0,180}\.registerknopf[\s\S]{0,80}width:\s*60px/.test(css) &&
    /data-register-anzahl="4"[\s\S]{0,900}writing-mode:\s*vertical-rl/.test(css) &&
    /data-register-anzahl="2"[\s\S]{0,900}text-orientation:\s*mixed/.test(css) &&
    /writing-mode:\s*vertical-rl[\s\S]{0,180}white-space:\s*nowrap[\s\S]{0,100}overflow-wrap:\s*normal/.test(css),
  "bei höchstens vier Registern fehlen schmale senkrechte Registerzungen");
  for (const id of ["notizen", "jahrestage", "planer"]) {
    $("#allgemein-register-" + id).click();
  }
  assert.strictEqual($$(".registerknopf").length, 6,
    "das Wiederaktivieren stellt die bisherigen Registerkarten nicht wieder her");
  assert.ok(!$("#allgemein-kalenderauswahl").checked,
    "Kalenderschaltflächen sind nicht voreingestellt deaktiviert");
  assert.ok(!$("#allgemein-tray-zaehler").checked,
    "der Tray-Zähler ist nicht voreingestellt deaktiviert");
  assert.ok($$(".datumsfeld").every((feld) => feld.type === "text") &&
    !$$("input[type=date]").length,
  "bei deaktivierter Kalenderauswahl existiert noch ein natives Datumsfeld");
  $("#allgemein-kalenderauswahl").checked = true;
  $("#allgemein-kalenderauswahl").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.kalenderAuswahl, true,
    "Kalenderauswahl wird nicht gespeichert");
  assert.strictEqual(d.body.dataset.kalenderauswahl, "an",
    "aktivierte Kalenderauswahl wirkt nicht auf neue Datumsfelder");
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  assert.ok($("#tb-datum-von").type === "text" &&
    $("#tb-datum-von").value === T.fmtPunkt(T.zustand().kalender.tag),
  "Termindaten hängen weiterhin von plattformabhängigen nativen Datumssegmenten ab");
  $("#termin-schleier header button").click();
  $("#allgemein-kalenderauswahl").checked = false;
  $("#allgemein-kalenderauswahl").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  $("#allgemein-hilfsrahmen").checked = true;
  $("#allgemein-hilfsrahmen").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.hilfsrahmen, true,
    "der Hilfsrahmen wird nicht gespeichert");
  assert.strictEqual(d.body.dataset.hilfsrahmen, "an",
    "der Hilfsrahmen wird nicht unmittelbar aktiviert");
  $("#allgemein-hilfsrahmen").checked = false;
  $("#allgemein-hilfsrahmen").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "h", ctrlKey: true, altKey: true, bubbles: true, cancelable: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.hilfsrahmen, true,
    "Strg+Alt+H schaltet den Hilfsrahmen nicht ein");
  assert.strictEqual($("#allgemein-hilfsrahmen").checked, true,
    "das Tastenkürzel aktualisiert die geöffnete Einstellung nicht");
  d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: "H", ctrlKey: true, altKey: true, bubbles: true, cancelable: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.hilfsrahmen, false,
    "Strg+Alt+H schaltet den Hilfsrahmen nicht wieder aus");
  assert.ok($("#allgemein-linien"), "Linien fehlen unter Allgemein");
  assert.ok($("#allgemein-linien").checked, "liniert ist die Voreinstellung");
  assert.ok(!$("#allgemein-jahrestagsarten"),
    "die überflüssige globale Umschaltung der Jahrestagsarten ist noch vorhanden");
  assert.deepStrictEqual(
    Array.from($("#allgemein-rad").options).map((o) => o.value),
    ["up-earlier", "up-later"], "zwei Drehrichtungen unter Allgemein");
  assert.ok(!$("#allgemein-sicherungsordner"),
    "der Sicherungsordner steht weiterhin unter Allgemein");
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Sicherheit").click();
  assert.ok($("#allgemein-sicherungsordner") && $("#journal-intervall"),
    "Sicherungsdateien und Wiederherstellungspunkte fehlen unter Sicherheit");
  assert.ok($("#allgemein-sicherung-wiederherstellen"),
    "der Knopf zum Wiederherstellen einer Sicherung fehlt");
  assert.strictEqual($("#allgemein-sicherungsordner").value, "",
    "ohne Wahl gilt weiterhin der Standardordner");
  assert.ok($("#einstellungen-inhalt").textContent.includes("Sicherungsordner") &&
    $("#einstellungen-inhalt").textContent.includes("Wiederherstellungspunkte"),
  "deutsche Sicherungsbereiche unter Sicherheit fehlen");
  setze($("#allgemein-sicherungsordner"), "/media/maik/Sicherungen");
  assert.strictEqual(
    T.daten().einstellungen.allgemein.sicherungsordner,
    "/media/maik/Sicherungen", "der Sicherungsordner wird gemerkt");
  w.App.sicherungAusgewaehlt({ ok: true, pfad: "/tmp/sicherung.json",
    verschluesselt: true, brauchtKennwort: true });
  assert.ok(!$("#sicherung-schleier").classList.contains("verborgen"),
    "der Wiederherstellungsdialog öffnet sich nicht");
  assert.ok(!$("#sicherung-kennwort-zeile").classList.contains("verborgen"),
    "für die verschlüsselte Sicherung fehlt die Kennwortabfrage");
  assert.strictEqual($("#sicherung-titel").textContent, "Sicherung wiederherstellen",
    "deutscher Sicherungsdialogtitel fehlt");
  assert.ok($("#sicherung-text").textContent.includes("/tmp/sicherung.json"),
    "Sicherungspfad wurde im deutschen Dialog verändert");
  $("#sicherung-abbrechen").click();

  /* Seite „Übernehmen“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Übernehmen").click();
  let reihen = $$("#einstellungen-inhalt .knopfreihe");
  assert.strictEqual(reihen[0].querySelectorAll("button").length, 6, "6 Import-Knöpfe einschließlich Gesamtarchiv");
  assert.ok(reihen[0].textContent.includes("Vom Rechner"), "Rechner-Knopf fehlt");
  assert.ok(reihen[0].textContent.includes("Claws-Mail"), "Claws-Mail-Import fehlt");

  /* Seite „Weitergeben“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Weitergeben").click();
  reihen = $$("#einstellungen-inhalt .knopfreihe");
  assert.strictEqual(reihen[0].querySelectorAll("button").length, 7, "7 Export-Knöpfe einschließlich Gesamtarchiv");
  assert.ok($("#einstellungen-inhalt h3").textContent.includes("Weitergeben"),
    "falsche Seite nach Reiterwechsel");

  /* Seite „Synchronisation“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Synchronisation").click();
  assert.ok($("#sync-status").textContent.includes("installierten Programm"),
    "Hinweis auf Browser-Betrieb fehlt");
  assert.ok($("#sync-jetzt").disabled, "Sync-Knopf müsste gesperrt sein");
  w.App.edsStatus({ verfuegbar: true, buchOk: false, kalender: [
    { uid: "google-privat", name: "Google – Privat" },
    { uid: "google-arbeit", name: "Google – Arbeit" }
  ] });
  const kalenderHaken = $$(".sync-kalender-liste input");
  assert.strictEqual(kalenderHaken.length, 2,
    "Kalender werden nicht als Mehrfachauswahl angeboten");
  kalenderHaken[0].click();
  kalenderHaken[1].click();
  assert.deepStrictEqual(Array.from(T.daten().einstellungen.sync.kalenderUids),
    ["google-privat", "google-arbeit"], "mehrere Kalender werden nicht gespeichert");
  assert.strictEqual(T.daten().einstellungen.sync.kalenderUid, "google-privat",
    "der erste Kalender wird nicht als Ziel für neue Termine verwendet");
  kalenderHaken[0].click();
  assert.strictEqual(T.daten().einstellungen.sync.kalenderUid, "google-arbeit",
    "nach Abwahl wird kein neuer Hauptkalender bestimmt");
  w.App.edsStatus({ verfuegbar: false, pakete: "EDS-PAKETE" });
  assert.ok($("#sync-status").textContent.includes("sudo apt install EDS-PAKETE") &&
    $("#nextcloud-konto") && $("#nextcloud-briefkasten"),
  "bei fehlendem EDS fehlt der Installationshinweis oder die direkte Nextcloud-Einrichtung");
  assert.strictEqual(w.MagnolieI18n.gettext("Test connection"), "Verbindung testen",
    "deutscher Nextcloud-Verbindungstest ist nicht übersetzt");
  assert.strictEqual(w.MagnolieI18n.gettext("Testing…"), "Verbindung wird getestet…",
    "deutscher Nextcloud-Prüfstatus ist nicht übersetzt");

  /* Seite „Land & Feiertage“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Land & Feiertage").click();
  const landWahl = $("#ort-land");
  assert.ok(landWahl, "Länderauswahl fehlt");
  assert.ok(!$("#ort-region"), "Bundesland erscheint erst nach der Landwahl");
  assert.ok(Array.from(landWahl.options).some((o) => o.value === "DE"),
    "Deutschland fehlt in der Länderliste");
  landWahl.value = "DE";
  landWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  const regionWahl = $("#ort-region");
  assert.ok(regionWahl, "Bundeslandauswahl erscheint nicht");
  assert.strictEqual(regionWahl.options.length, 17,
    "16 Bundesländer und die Aufforderung zur Auswahl erwartet");
  assert.strictEqual(regionWahl.value, "",
    "ohne ausdrückliche Wahl darf kein Bundesland geraten werden");
  assert.ok($("#ort-alle-regionen"), "ausdrückliche Wahl aller Bundesländer fehlt");
  $("#ort-alle-regionen").checked = true;
  $("#ort-alle-regionen").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.ort.alleRegionen, true,
    "Wahl aller Bundesländer nicht gemerkt");
  assert.ok(regionWahl.disabled, "Bundeslandwahl bleibt bei „alle“ aktiv");
  $("#ort-alle-regionen").checked = false;
  $("#ort-alle-regionen").dispatchEvent(new w.Event("change", { bubbles: true }));
  regionWahl.value = "DE-NW";
  regionWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.ort.land, "DE", "Land nicht gemerkt");
  assert.strictEqual(T.daten().einstellungen.ort.region, "DE-NW", "Region nicht gemerkt");
  assert.strictEqual(T.daten().einstellungen.ort.regionName, "Nordrhein-Westfalen",
    "Regionsname nicht gemerkt");
  assert.ok($("#ort-abrufen").disabled, "Abruf ohne Brücke müsste gesperrt sein");
  assert.ok($("#ort-ferien").checked, "Schulferien sind voreingestellt");

  /* Abrufergebnis einspielen */
  w.App.feiertageErgebnis({ jahre: [2026], bericht: "Abgerufen: 2 Feiertage.",
    feiertage: [
      { von: "2026-07-24", bis: "2026-07-24", name: "Prüftag", art: "feiertag" },
      { von: "2026-07-20", bis: "2026-07-26", name: "Sommerferien", art: "ferien" }
    ] });
  assert.strictEqual(T.daten().feiertage.length, 2, "Feiertage nicht übernommen");
  assert.ok($("#ort-stand").textContent.includes("1 Feiertag") &&
    $("#ort-stand").textContent.includes("1 Ferienabschnitt"),
    "Standanzeige nach Abruf: " + $("#ort-stand").textContent);
  w.App.feiertageErgebnis({ jahre: [2027], feiertage: [
    { von: "2027-01-01", bis: "2027-01-01", name: "Neujahr", art: "feiertag" }
  ] });
  assert.strictEqual(T.daten().feiertage.length, 3,
    "ein Abruf darf Einträge anderer Jahre nicht entfernen");
  assert.deepStrictEqual(T.daten().einstellungen.ort.jahre, [2026, 2027],
    "die Standanzeige muss erhaltene und neu abgerufene Jahre nennen");
  w.App.feiertageErgebnis({ jahre: [2027], feiertage: [
    { von: "2027-01-02", bis: "2027-01-02", name: "Ersatztag", art: "feiertag" }
  ] });
  assert.ok(T.daten().feiertage.some((f) => f.name === "Ersatztag") &&
    !T.daten().feiertage.some((f) => f.name === "Neujahr") &&
    T.daten().feiertage.some((f) => f.name === "Prüftag"),
    "ein Neuabruf muss nur das angefragte Jahr ersetzen");
  T.daten().feiertage = T.daten().feiertage.filter((f) => f.von.startsWith("2026-"));
  T.daten().einstellungen.ort.jahre = [2026];
  const syncFerien = { id: "sync-ferien-sn", uid: "ferien-sn-2026",
    datum: "2026-07-20", endDatum: "2026-07-26", zeit: "", endZeit: "",
    titel: "Sommerferien Sachsen 2026", sync: true };
  const privaterFerientermin = { id: "privat-ferien", uid: "privat-ferien-2026",
    datum: "2026-07-22", endDatum: "", zeit: "", endZeit: "",
    titel: "Urlaub in den Sommerferien", sync: true };
  const syncFeiertag = { id: "sync-prueftag", uid: "prueftag-2026",
    datum: "2026-07-24", endDatum: "", zeit: "", endZeit: "",
    titel: "Prüftag", kategorien: "", sync: true };
  const publicFeiertag = { id: "sync-tag-arbeit", uid: "tag-arbeit-2026",
    datum: "2026-05-01", endDatum: "", zeit: "", endZeit: "",
    titel: "Tag der Arbeit NRW 2026", kategorien: "Public", sync: true };
  T.daten().termine.push(syncFerien, privaterFerientermin,
    syncFeiertag, publicFeiertag);
  T.planeSpeichern();
  assert.ok(T.istSynchronisierteFerien(syncFerien),
    "synchronisierte Sommerferien werden nicht erkannt");
  const bundeslaender = ["Baden-Württemberg", "Bayern", "Berlin",
    "Brandenburg", "Bremen", "Hamburg", "Hessen", "Mecklenburg-Vorpommern",
    "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland",
    "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen"];
  assert.ok(bundeslaender.every((region) => T.istSynchronisierteFerien(
    Object.assign({}, syncFerien, { titel: "Sommerferien " + region + " 2026" }))) &&
    T.istSynchronisierteFerien(Object.assign({}, syncFerien,
      { titel: "Sommerferien NRW 2026" })) &&
    [1980, 2025, 2027, 2035, 2200].every((jahr) =>
      T.istSynchronisierteFerien(Object.assign({}, syncFerien,
        { titel: "Sommerferien NRW " + jahr }))) &&
    T.istSynchronisierteFerien(Object.assign({}, syncFerien,
      { titel: "Sommerferien NRW" })),
    "Ferienbezeichnungen aller Bundesländer und Jahre werden nicht erkannt");
  assert.ok(!T.istSynchronisierteFerien(privaterFerientermin) &&
    !T.istSynchronisierteFerien(Object.assign({}, syncFerien, { sync: false })) &&
    !T.istSynchronisierteFerien(Object.assign({}, syncFerien, { zeit: "09:00" })) &&
    !T.istSynchronisierteFerien(Object.assign({}, syncFerien,
      { titel: "Sommerferien planen" })),
    "persönliche oder zeitgebundene Termine dürfen nicht als Ferien gelten");
  assert.ok(!T.termineAm("2026-07-22").some((t) => t.id === syncFerien.id),
    "erkannte Ferien erscheinen weiterhin als normaler Ganztagstermin");
  assert.ok(T.termineAm("2026-07-22").some((t) => t.id === privaterFerientermin.id),
    "ein persönlicher Ferientermin wurde fälschlich ausgeblendet");
  assert.strictEqual(T.feiertageAm("2026-07-22")
    .filter((f) => f.art === "school-holiday").length, 1,
    "eingelesene und synchronisierte Sommerferien werden nicht zusammengeführt");
  const einzelneFerien = T.daten().feiertage;
  const regionenMitCode = [
    ["DE-BW", "Baden-Württemberg"], ["DE-BY", "Bayern"], ["DE-BE", "Berlin"],
    ["DE-BB", "Brandenburg"], ["DE-HB", "Bremen"], ["DE-HH", "Hamburg"],
    ["DE-HE", "Hessen"], ["DE-MV", "Mecklenburg-Vorpommern"],
    ["DE-NI", "Niedersachsen"], ["DE-NW", "Nordrhein-Westfalen"],
    ["DE-RP", "Rheinland-Pfalz"], ["DE-SL", "Saarland"],
    ["DE-SN", "Sachsen"], ["DE-ST", "Sachsen-Anhalt"],
    ["DE-SH", "Schleswig-Holstein"], ["DE-TH", "Thüringen"]
  ];
  T.daten().einstellungen.ort.alleRegionen = true;
  T.daten().feiertage = regionenMitCode.map(([code, name], index) => ({
    von: index % 2 ? "2026-07-21" : "2026-07-20",
    bis: index % 3 ? "2026-07-27" : "2026-07-26",
    name: "Sommerferien (" + name + ")", art: "school-holiday", region: code
  }));
  T.daten().feiertage.push(Object.assign({}, T.daten().feiertage[14]));
  T.planeSpeichern();
  const alleFerienAmTag = T.feiertageAm("2026-07-22")
    .filter((f) => f.art === "school-holiday");
  assert.strictEqual(alleFerienAmTag.length, 1,
    "überlappende Ferien werden nicht tagesweise zusammengeführt");
  assert.strictEqual(alleFerienAmTag[0].name,
    "Sommerferien (BW, BY, BE, BB, HB, HH, HE, MV, NI, NW, RP, SL, SN, ST, SH, TH)",
    "Bundeslandkürzel fehlen, sind falsch sortiert oder doppelt");
  T.daten().einstellungen.ort.alleRegionen = false;
  T.daten().feiertage = einzelneFerien;
  T.planeSpeichern();
  assert.ok(T.istSynchronisierterFeiertag(syncFeiertag) &&
    !T.termineAm("2026-07-24").some((t) => t.id === syncFeiertag.id) &&
    T.feiertageAm("2026-07-24").filter((f) => f.art === "public-holiday").length === 1,
    "eingelesener und synchronisierter Feiertag wird nicht zusammengeführt");
  assert.ok(T.istSynchronisierterFeiertag(publicFeiertag) &&
    T.feiertageAm("2026-05-01").some((f) =>
      f.art === "public-holiday" && f.synchronisiert),
    "gesetzlicher Feiertag mit Public-Kategorie wird ohne Abruf nicht rot geführt");
  const feiertagsMuster = [
    ["Heilige Drei Könige (ST,BW,BY)", "2026-01-06"],
    ["Fronleichnam (HE,SL,NW,BW,RP,BY)", "2026-06-04"],
    ["Friedensfest (BY-AU)", "2026-08-08"],
    ["Buß- und Bettag (SN)", "2026-11-18"]
  ];
  assert.ok(feiertagsMuster.every(([titel, datum]) =>
    T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { titel: titel, datum: datum }))) &&
    bundeslaender.every((region) => T.istSynchronisierterFeiertag(
      Object.assign({}, publicFeiertag,
        { titel: "Tag der Arbeit " + region + " 2026" }))) &&
    [1980, 2025, 2027, 2035, 2200].every((jahr) =>
      T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
        { datum: jahr + "-05-01", titel: "Tag der Arbeit NRW " + jahr }))),
    "Feiertage aller Bundesländer und Jahre werden nicht erkannt");
  assert.ok(!T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
    { sync: false })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { zeit: "09:00" })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { endDatum: "2026-05-02" })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { titel: "Tag der Arbeit planen" })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { kategorien: "School", titel: "Reformationsfest (BW)" })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { kategorien: "", titel: "Neujahr", datum: "2026-01-01" })) &&
    !T.istSynchronisierterFeiertag(Object.assign({}, publicFeiertag,
      { titel: "Tag der Arbeit NRW 2025" })),
    "persönliche oder unpassende Termine dürfen nicht als Feiertag gelten");
  /* Seite „Schrift“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Schrift").click();
  const artWahl = $("#schrift-art");
  const farbWahl = $("#schrift-farbe");
  assert.ok(artWahl && farbWahl, "Schriftauswahl fehlt");
  assert.strictEqual(artWahl.value, "regular", "Druckschrift ist Voreinstellung");
  assert.strictEqual(farbWahl.value, "black", "Schwarz ist Voreinstellung");
  assert.ok($("#schrift-probe"), "Vorschau fehlt");
  assert.strictEqual(d.body.getAttribute("data-schrift"), "regular",
    "Schriftmerkmal am Buch fehlt");
  artWahl.value = "handwriting";
  artWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  farbWahl.value = "blue";
  farbWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.schrift.art, "handwriting", "Schriftart nicht gemerkt");
  assert.strictEqual(T.daten().einstellungen.schrift.farbe, "blue", "Farbe nicht gemerkt");
  assert.strictEqual(d.body.getAttribute("data-schrift"), "handwriting",
    "Handschrift wirkt nicht auf das Buch");
  assert.strictEqual(d.body.getAttribute("data-tinte"), "blue",
    "Tintenfarbe wirkt nicht auf das Buch");
  assert.strictEqual($("#schrift-probe").getAttribute("data-tinte"), "blue",
    "Vorschau folgt der Auswahl nicht");

  /* Schriftgröße */
  const groessenWahl = $("#schrift-groesse");
  assert.ok(groessenWahl, "Größenauswahl fehlt");
  assert.deepStrictEqual(Array.from(groessenWahl.options).map((o) => o.value),
    ["normal", "medium", "large"], "drei Schriftgrößen erwartet");
  assert.strictEqual(groessenWahl.value, "normal", "Normal ist Voreinstellung");
  assert.strictEqual(d.body.getAttribute("data-groesse"), "normal",
    "Größenmerkmal am Buch fehlt");
  groessenWahl.value = "large";
  groessenWahl.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.schrift.groesse, "large",
    "Schriftgröße nicht gemerkt");
  assert.strictEqual(d.body.getAttribute("data-groesse"), "large",
    "Große Schrift wirkt nicht auf das Buch");
  assert.strictEqual($("#schrift-probe").getAttribute("data-groesse"), "large",
    "Vorschau folgt der Größe nicht");

  /* Rechtschreibprüfung */
  const pruefHak = $("#schrift-pruefung");
  assert.ok(pruefHak, "Haken für die Rechtschreibprüfung fehlt");
  assert.strictEqual(pruefHak.checked, true, "Prüfung ist nicht voreingestellt an");
  assert.strictEqual(d.body.getAttribute("data-pruefung"), "an",
    "Prüfmerkmal am Buch fehlt");
  pruefHak.checked = false;
  pruefHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.schrift.rechtschreibung, false,
    "explizites Abschalten der Rechtschreibprüfung wird nicht gemerkt");
  pruefHak.checked = true;
  pruefHak.dispatchEvent(new w.Event("change", { bubbles: true }));

  /* Die Felder tragen die Prüfung nun selbst */
  T.schliesseEinstellungen();
  klickeTab("Notizen");
  assert.strictEqual($("#notiz-text").getAttribute("spellcheck"), "true",
    "Schreibblatt ohne Rechtschreibprüfung");
  assert.strictEqual($("#notiz-titel").getAttribute("spellcheck"), "true",
    "Überschrift ohne Rechtschreibprüfung");
  klickeTab("Jahrestage");
  assert.strictEqual($("#inhalt-rechts fieldset input[type=text]")
    .getAttribute("spellcheck"), "true", "Textfeld ohne Rechtschreibprüfung");

  /* Wieder zurück auf die gewohnten Werte */
  T.oeffneEinstellungen();
  $("#schrift-pruefung").checked = false;
  $("#schrift-pruefung").dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#schrift-groesse").value = "normal";
  $("#schrift-groesse").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(d.body.getAttribute("data-pruefung"), "aus",
    "Prüfung ließ sich nicht abschalten");
  const artWahl2 = $("#schrift-art");
  artWahl2.value = "regular";
  artWahl2.dispatchEvent(new w.Event("change", { bubbles: true }));
  const farbWahl2 = $("#schrift-farbe");
  farbWahl2.value = "black";
  farbWahl2.dispatchEvent(new w.Event("change", { bubbles: true }));

  /* Seite „Benachrichtigung“ */
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Benachrichtigung").click();
  const anHak = $("#erinnerung-an");
  assert.ok(anHak, "Schalter für Erinnerungen fehlt");
  assert.strictEqual(anHak.checked, false, "Erinnerungen sind voreingestellt aus");
  assert.ok($("#erinnerung-vorlauf").disabled,
    "Felder müssten gesperrt sein, solange nichts erinnert wird");
  assert.ok($("#erinnerung-stand").textContent.includes("erinnert derzeit nicht"),
    "Standtext: " + $("#erinnerung-stand").textContent);
  assert.deepStrictEqual(
    Array.from($("#erinnerung-vorlauf").options).map((o) => o.value),
    ["0", "5", "10", "15", "30", "60", "120"], "Vorlaufzeiten");
  assert.deepStrictEqual(
    Array.from($("#erinnerung-art").options).map((o) => o.value),
    ["notification", "sound", "both"], "Meldung, Ton oder beides");

  anHak.checked = true;
  anHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.an, true,
    "Einschalten nicht gemerkt");
  assert.ok(!$("#erinnerung-vorlauf").disabled, "Felder bleiben gesperrt");
  $("#erinnerung-vorlauf").value = "30";
  $("#erinnerung-vorlauf").dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#erinnerung-art").value = "sound";
  $("#erinnerung-art").dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#erinnerung-verpasst").checked = false;
  $("#erinnerung-verpasst").dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#erinnerung-wecken").checked = true;
  $("#erinnerung-wecken").dispatchEvent(new w.Event("change", { bubbles: true }));
  const erWahl = T.daten().einstellungen.erinnerung;
  assert.strictEqual(erWahl.vorlauf, 30, "Vorlauf nicht gemerkt");
  assert.strictEqual(erWahl.art, "sound", "Art nicht gemerkt");
  assert.strictEqual(erWahl.verpasste, false, "Verpasste-Haken nicht gemerkt");
  assert.strictEqual(erWahl.wecken, true, "Weckruf nicht gemerkt");

  /* Der Klang gehört zum Gewand – eine eigene Auswahl gibt es nicht mehr */
  assert.ok(!$("#erinnerung-klang"), "die Tonauswahl ist entfallen");

  /* Im Gewand des Systems entscheidet dieses über Ton und Aussehen */
  $("#erinnerung-stil").value = "system";
  $("#erinnerung-stil").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual($("#erinnerung-art-zeile").style.display, "none",
    "beim Systemstil darf die Art nicht wählbar sein");
  assert.ok($("#erinnerung-stil-hinweis").textContent.includes("Systems"),
    "Hinweis zum Systemstil fehlt");
  $("#erinnerung-stil").value = "magnolie";
  $("#erinnerung-stil").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual($("#erinnerung-art-zeile").style.display, "",
    "beim eigenen Stil ist die Art wählbar");
  assert.ok($("#erinnerung-stil-hinweis").textContent.includes("Glockenspiel"),
    "Hinweis zum eigenen Stil fehlt");

  /* Jahrestage */
  const jtHak = $("#erinnerung-jahrestage");
  assert.ok(jtHak, "Schalter für Jahrestage fehlt");
  assert.strictEqual(jtHak.checked, false, "Jahrestage sind voreingestellt aus");
  assert.strictEqual($("#erinnerung-jahrestage-tage-zeile").style.display, "none",
    "der Vorlauf erscheint erst, wenn Jahrestage gewünscht sind");
  jtHak.checked = true;
  jtHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.jahrestage.an, true,
    "Jahrestage nicht gemerkt");
  assert.strictEqual($("#erinnerung-jahrestage-tage-zeile").style.display, "",
    "der Vorlauf erscheint nicht");
  assert.deepStrictEqual(
    Array.from($("#erinnerung-jahrestage-tage").options).map((o) => o.value),
    ["0", "1", "2", "3", "4", "5", "6", "7"],
    "der Jahrestagsvorlauf reicht nicht bis sieben Tage");
  $("#erinnerung-jahrestage-tage").value = "7";
  $("#erinnerung-jahrestage-tage").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.jahrestage.tage, 7,
    "Vorlauf der Jahrestage nicht gemerkt");
  assert.strictEqual($("#erinnerung-jahrestage-amtag-zeile").style.display, "",
    "die zweite Erinnerung am Tag selbst fehlt");
  $("#erinnerung-jahrestage-tage").value = "0";
  $("#erinnerung-jahrestage-tage").dispatchEvent(
    new w.Event("change", { bubbles: true }));
  assert.strictEqual($("#erinnerung-jahrestage-amtag-zeile").style.display, "none",
    "ohne Vorlauf ist die zweite Erinnerung sinnlos");
  jtHak.checked = false;
  jtHak.dispatchEvent(new w.Event("change", { bubbles: true }));

  /* Fehlersuche: Protokoll */
  assert.ok($("#erinnerung-protokoll"), "Knopf für das Protokoll fehlt");
  const protHak = $("#erinnerung-protokoll-an");
  assert.ok(protHak, "Schalter für das Protokoll fehlt");
  assert.strictEqual(protHak.checked, false,
    "das Protokoll muss voreingestellt aus sein");
  protHak.checked = true;
  protHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.protokoll, true,
    "Einschalten des Protokolls nicht gemerkt");
  w.App.protokollStand({ ok: true, pfad: "/heim/wecker.log", womit: "xed" });
  assert.ok($("#zettel").textContent.includes("wecker.log"),
    "Rückmeldung zum Protokoll fehlt");

  /* Bei „Nur Ton“ bleibt der Bildschirm ruhig */
  $("#erinnerung-stil").value = "magnolie";
  $("#erinnerung-stil").dispatchEvent(new w.Event("change", { bubbles: true }));
  T.meldeErinnerung("Termin steht an", "Nur Ton");
  assert.ok(!$(".erinnerungs-blatt"),
    "bei „Nur Ton“ darf kein Blatt erscheinen");
  $("#erinnerung-art").value = "both";
  $("#erinnerung-art").dispatchEvent(new w.Event("change", { bubbles: true }));

  /* Aussehen wählbar: Systemmeldung oder eigenes Papierblatt */
  assert.deepStrictEqual(
    Array.from($("#erinnerung-stil").options).map((o) => o.value),
    ["system", "magnolie"], "zwei Gewänder für die Meldung");
  $("#erinnerung-stil").value = "magnolie";
  $("#erinnerung-stil").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.stil, "magnolie",
    "Aussehen nicht gemerkt");

  T.meldeErinnerung("Termin steht an", "Zahnarzt – um 10:00 Uhr");
  const erBlatt = $(".erinnerungs-blatt");
  assert.ok(erBlatt, "Erinnerungsblatt erscheint nicht");
  assert.strictEqual(erBlatt.querySelector(".eb-kopf").textContent, "Termin steht an",
    "Überschrift des Blattes");
  assert.ok(erBlatt.textContent.includes("Zahnarzt"), "Termintext fehlt");
  assert.strictEqual(erBlatt.querySelectorAll("button").length, 2,
    "Knöpfe zum Kalender und zum Schließen erwartet");
  erBlatt.querySelectorAll("button")[1].click();
  assert.ok(!$(".erinnerungs-blatt"), "Blatt lässt sich nicht schließen");

  $("#erinnerung-stil").value = "system";
  $("#erinnerung-stil").dispatchEvent(new w.Event("change", { bubbles: true }));
  T.meldeErinnerung("Termin steht an", "Sport");
  assert.ok(!$(".erinnerungs-blatt"),
    "im Systemstil darf kein eigenes Blatt erscheinen");

  w.App.erinnerungStand({ ok: false, fehler: "Kein systemd gefunden." });
  assert.ok($("#erinnerung-stand").textContent.includes("systemd"),
    "Fehlermeldung erscheint nicht im Stand");

  /* Terminzeitpunkt: ganztägige Termine gelten ab 8 Uhr */
  const zp = T.terminZeitpunkt({ datum: "2026-08-01", zeit: "" });
  assert.strictEqual(zp.getHours(), 8, "Ganztagstermin nicht auf 8 Uhr gelegt");
  assert.strictEqual(T.terminZeitpunkt({ datum: "krumm", zeit: "" }), null,
    "unbrauchbares Datum liefert nichts");

  $("#erinnerung-an").checked = false;
  $("#erinnerung-an").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.erinnerung.an, false,
    "Abschalten nicht gemerkt");

  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.ok($("#einstellungen-schleier").classList.contains("verborgen"),
    "Escape schließt Einstellungen nicht");

  /* ---- Feiertage erscheinen im Kalender ---- */
  T.zustand().kalender.jahr = 2026;
  T.zustand().kalender.monat = 6;
  T.zustand().kalender.tag = "2026-07-24";
  klickeTab("Kalender");
  const ftZelle = $$(".kal-tag").find((z2) => z2.classList.contains("feiertag"));
  assert.ok(ftZelle, "Feiertag im Monatsgitter nicht gekennzeichnet");
  assert.ok(ftZelle.textContent.includes("Prüftag"), "Name des Feiertags fehlt");
  assert.ok(!$(".termin-uebersicht").textContent.includes("(Schulferien)"),
    "Ferien werden unnötig zusätzlich als Schulferien bezeichnet");
  assert.ok($$(".kal-tag").some((z2) => z2.classList.contains("ferien")),
    "Ferientage im Monatsgitter nicht gekennzeichnet");
  assert.ok(!$(".mini-termin[data-termin-id='sync-ferien-sn']"),
    "synchronisierte Ferien stehen zusätzlich als normaler Termin im Monatsgitter");
  /* In der Übersicht steht der Feiertag beim jeweiligen Tag */
  assert.ok($$(".ue-feiertag").some((k) => k.textContent.includes("Prüftag (Feiertag)")),
    "Feiertag fehlt in der Terminübersicht");
  assert.ok($$(".ue-feiertag").some((k) => k.classList.contains("ferien")),
    "Ferien werden in der Übersicht nicht abgesetzt");
  assert.ok(!$(".termin-uebersicht").textContent.includes("Sommerferien Sachsen 2026"),
    "die Terminübersicht zeigt die synchronisierten Ferien doppelt");
  /* und in der Tagesansicht als Kasten */
  T.daten().einstellungen.kalender.klickLegtAn = false;
  ftZelle.click();
  assert.strictEqual(T.zustand().kalender.ansicht, "day",
    "der Klick führt nicht in die Tagesansicht");
  T.daten().einstellungen.kalender.klickLegtAn = true;
  assert.ok($(".ft-kasten"), "Feiertagskasten in der Tagesansicht fehlt");
  assert.ok($(".ft-kasten").textContent.includes("Prüftag (Feiertag)"),
    "Feiertagskasten ohne Kennzeichnung: " + $(".ft-kasten").textContent);
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();
  $$(".u-knopf").find((b) => b.textContent === "Woche").click();
  assert.ok($$(".wo-tag").some((k) => k.classList.contains("feiertag")),
    "Feiertag im Wochenblatt fehlt");
  assert.ok($$(".wo-ft").some((z2) => z2.textContent.includes("Sommerferien")),
    "Ferien im Wochenblatt fehlen");
  assert.ok(!$$(".wo-liste").some((z2) =>
    z2.textContent.includes("Sommerferien Sachsen 2026")),
    "das Wochenblatt zeigt Ferien zusätzlich als Ganztagstermin");
  $$(".u-knopf").find((b) => b.textContent === "Monat").click();

  /* Auch ohne OpenHolidays bleibt der synchronisierte Zeitraum grün. */
  const abgerufeneFeiertage = T.daten().feiertage;
  T.daten().feiertage = abgerufeneFeiertage.filter((f) => f.art !== "school-holiday");
  T.planeSpeichern();
  assert.ok(T.feiertageAm("2026-07-22").some((f) =>
    f.synchronisiert && f.name === "Sommerferien Sachsen 2026"),
    "synchronisierte Ferien werden ohne Abruf nicht als grüner Zeitraum geführt");
  T.zustand().kalender.tag = "2026-07-22";
  T.zustand().kalender.jahr = 2026;
  T.zustand().kalender.monat = 6;
  T.wechsel("aufgaben");
  T.wechsel("kalender");
  assert.ok($$(".kal-tag.ferien .ft-marke").some((m) =>
    m.textContent.includes("Sommerferien Sachsen 2026")),
    "synchronisierte Ferien werden im Monatsblatt nicht grün beschriftet");
  T.daten().feiertage = abgerufeneFeiertage;
  T.daten().termine = T.daten().termine.filter((t) =>
    ![syncFerien.id, privaterFerientermin.id].includes(t.id));
  T.planeSpeichern();

  /* ---- Import-Zusammenführung (ohne Dateidialog, direkt über App) ---- */
  const vorherT = T.daten().termine.length;
  const vorherJ = T.daten().jahrestage.length;
  const nutzlast = {
    art: "ics", abgebrochen: false,
    termine: [{ datum: "2026-07-30", endDatum: "2026-09-12",
      zeit: "09:00", endZeit: "09:45",
      titel: "Import-Test", kategorien: "Arbeit",
      individuelleErinnerungTage: 3, standardErinnerung: false,
      wiederholung: { art: "woche", bis: "2026-10-01" } }],
    aufgaben: [{ uid: "todo-import-1", titel: "Import-Aufgabe",
      faellig: "2026-08-02", prio: 1, erledigt: false }],
    geburtstage: [{ name: "Oma Erna", datum: "1950-03-04" }],
    wiederholend: 1
  };
  w.App.importErgebnis(nutzlast);
  assert.ok($("#zettel").textContent.includes("1 Termin") &&
    $("#zettel").textContent.includes("1 Aufgabe") &&
    $("#zettel").textContent.includes("1 Geburtstag") &&
    $("#zettel").textContent.includes("1 wiederkehrender Termin"),
  "deutsche Singularformen der Importmeldung fehlen");
  assert.strictEqual(T.daten().termine.length, vorherT + 1, "Import-Termin fehlt");
  const imp = T.daten().termine.find((t) => t.titel === "Import-Test");
  assert.ok(imp.uid.startsWith("mag-"), "Import-Termin ohne Kennung");
  assert.strictEqual(imp.endDatum, "2026-09-12", "Import-Enddatum fehlt");
  assert.deepStrictEqual(imp.wiederholung, { art: "weekly", bis: "2026-10-01" },
    "einfache ICS-Wiederholung wurde beim Webimport verworfen");
  assert.ok(imp.individuelleErinnerungTage === 3 && !imp.standardErinnerung,
    "ICS-Erinnerungsfelder wurden beim Webimport verworfen");
  assert.ok(T.termineAm("2026-08-02").some((t) => t.id === imp.id),
    "Import-Termin fehlt an einem Zwischentag");
  const druckJahr = T.zustand().kalender.jahr;
  const druckMonat = T.zustand().kalender.monat;
  T.zustand().kalender.jahr = 2026;
  T.zustand().kalender.monat = 7;
  T.daten().termine.push({ id: "sync-holiday-print", datum: "2026-08-15",
    endDatum: "", zeit: "", endZeit: "", titel: "Mariä Himmelfahrt",
    kategorien: "Public", notiz: "", sync: true });
  const zeitraumDruck = T.oeffneDruckvorschau(null, "kalender");
  assert.ok(zeitraumDruck.textContent.includes("Import-Test"),
    "im Vormonat beginnender Zeitraum fehlt im Monatsdruck");
  assert.ok(!zeitraumDruck.textContent.includes("Mariä Himmelfahrt"),
    "synchronisierter Feiertag erscheint als klassischer Termin in Auswahloptionen");
  zeitraumDruck.remove();
  T.daten().termine = T.daten().termine.filter((t) => t.id !== "sync-holiday-print");
  T.zustand().kalender.jahr = druckJahr;
  T.zustand().kalender.monat = druckMonat;
  assert.strictEqual(T.daten().aufgaben.find((a) => a.titel === "Import-Aufgabe").uid,
    "todo-import-1", "VTODO-UID wurde beim Import verworfen");
  const oma = T.daten().jahrestage.find((j) => j.name === "Oma Erna");
  assert.ok(oma, "Geburtstag nicht als Jahrestag übernommen");
  assert.strictEqual(oma.typ, "birthday");
  w.App.importErgebnis(nutzlast);
  assert.strictEqual(T.daten().termine.length, vorherT + 1, "Duplikat nicht erkannt");
  assert.strictEqual(T.daten().jahrestage.length, vorherJ + 1, "Geburtstag doppelt");
  w.App.importErgebnis({ art: "ics", abgebrochen: false, termine: [
    { uid: "parallel-a", datum: "2026-09-10", zeit: "10:00", titel: "Parallel" },
    { uid: "parallel-b", datum: "2026-09-10", zeit: "10:00", titel: "Parallel",
      icsKomplex: true, icsSerienUid: "parallel-b" }
  ] });
  const parallele = T.daten().termine.filter((t) => t.titel === "Parallel");
  assert.ok(parallele.length === 2 && parallele.some((t) =>
    t.uid === "parallel-b" && t.icsKomplex && t.icsSerienUid === "parallel-b"),
  "verschiedene ICS-UIDs oder Schutzmarkierung wurden als Duplikat verworfen");
  const parallelA = parallele.find((t) => t.uid === "parallel-a");
  w.App.importErgebnis({ art: "ics", abgebrochen: false, termine: [
    { uid: "parallel-a", datum: "2026-09-11", zeit: "11:00", titel: "Neuere Fassung",
      geaendert: parallelA.geaendert + 1000, icsRoundtrip: ["LOCATION:Raum 9"] }
  ], aufgaben: [{ uid: "todo-import-1", titel: "Import-Aufgabe neu",
    faellig: "2026-08-03", prio: 2, erledigt: false, erinnern: true,
    individuelleErinnerungTage: 4,
    geaendert: T.daten().aufgaben.find((a) => a.uid === "todo-import-1").geaendert + 1000 }],
  notizen: [{ titel: "HTML-Import", text: "Sicher", html: "<p><b>Sicher</b><script>weg</script></p>",
    anhaenge: [{ name: "Bild.png", daten: "data:image/png;base64,iVBORw0KGgo=" }] }],
  kontakte: [{ uid: "geburtstags-import", vorname: "Lina", nachname: "Link",
    geburtstag: "2000-02-29", geburtstagJahrUnbekannt: true }] });
  assert.ok(parallelA.titel === "Neuere Fassung" && parallelA.datum === "2026-09-11" &&
    parallelA.icsRoundtrip[0] === "LOCATION:Raum 9",
  "neuere UID-identische Termine werden nicht blind übersprungen");
  w.App.importErgebnis({ art: "ics", abgebrochen: false, termine: [
    { uid: "eds-komplex-neu", datum: "2026-09-12", zeit: "10:00",
      titel: "Komplex von EDS", icsKomplex: true, icsSerienUid: "eds-serie",
      icsRoundtrip: ["ATTACH:web+opaque:anbieter/42"], icsReadOnly: true,
      icsReadOnlyGrund: "EDS", icsQuelleName: "Evolution Data Server",
      icsQuelleId: "eds:kalender-a" }
  ] });
  const edsKomplex = T.daten().termine.find((t) => t.uid === "eds-komplex-neu");
  assert.ok(edsKomplex && edsKomplex.icsReadOnly &&
    edsKomplex.icsRoundtrip[0] === "ATTACH:web+opaque:anbieter/42" &&
    edsKomplex.icsQuelleId === "eds:kalender-a",
  "Nur-Lese- und Quellenfelder komplexer EDS-Termine gehen beim Webimport verloren");
  const edsNormalisiert = T.normalisiere({ termine: [edsKomplex] }).termine[0];
  assert.ok(edsNormalisiert.icsReadOnly && edsNormalisiert.icsQuelleName ===
    "Evolution Data Server" && edsNormalisiert.icsQuelleId === "eds:kalender-a",
  "Nur-Lese- und Quellenfelder überstehen die dauerhafte Normalisierung nicht");
  const syncNormalisiert = T.normalisiere({ termine: [{ id: "sync-meta", datum: "2026-09-12",
    zeit: "08:00:00", endZeit: "09:15:59", icsSequence: 7,
    icsAenderungszeitFehlt: true,
    syncKonflikte: Array.from({ length: 20 }, (_, i) => ({ id: "k" + i })) }] }).termine[0];
  assert.ok(syncNormalisiert.zeit === "08:00" && syncNormalisiert.endZeit === "09:15" &&
    syncNormalisiert.icsSequence === 7 && syncNormalisiert.icsAenderungszeitFehlt &&
    syncNormalisiert.syncKonflikte.length === 16 && syncNormalisiert.syncKonflikte[0].id === "k4",
  "Sync-Metadaten oder Sekundenzeiten überstehen die begrenzte Normalisierung nicht");
  const aufgabenZeiten = T.normalisiere({ aufgaben: [{ id: "sekunden-aufgabe",
    startZeit: "07:30:45", faelligZeit: "17:05:01" }] }).aufgaben[0];
  assert.ok(aufgabenZeiten.startZeit === "07:30" && aufgabenZeiten.faelligZeit === "17:05",
  "Aufgabenzeiten mit Sekunden werden nicht auf Minuten normalisiert");
  const edsBlatt = T.oeffneTerminBlatt(edsKomplex, edsKomplex.datum);
  assert.ok(/read only|nur lesen/i.test(edsBlatt.textContent) &&
    edsBlatt.querySelector("#tb-titel").disabled && !edsBlatt.querySelector("#tb-loeschen"),
  "komplexer EDS-Termin ist nicht klar als nur lesbar gesperrt");
  edsBlatt.remove();
  const aktualisierteAufgabe = T.daten().aufgaben.find((a) => a.uid === "todo-import-1");
  assert.ok(aktualisierteAufgabe.erinnern && aktualisierteAufgabe.individuelleErinnerungTage === 4,
    "Aufgaben-Erinnerungsfelder gehen beim UID-Update verloren");
  const htmlImport = T.daten().notizen.find((n) => n.titel === "HTML-Import");
  assert.ok(htmlImport.html.includes("<b>Sicher</b>") && !htmlImport.html.includes("script") &&
    htmlImport.anhaenge.length === 1,
  "Notiz-HTML oder sicherer Anhang geht beim Import verloren");
  const geburtstagsImport = T.daten().kontakte.find((k) => k.uid === "geburtstags-import");
  assert.ok(geburtstagsImport && T.daten().jahrestage.some((j) =>
    j.kontaktId === geburtstagsImport.id && j.jahrUnbekannt),
  "Kontaktgeburtstag wird nicht mit der Karte verknüpft");

  /* ---- Rechner-Import: Fundbericht erscheint auf dem Zettel ---- */
  w.App.importErgebnis({ art: "lokal", abgebrochen: false,
    kontakte: [{ nachname: "Lokal", vorname: "Lena", email: "lena@rechner.de" }],
    bericht: "Gefunden – Evolution: 1 Adressen." });
  assert.ok(T.daten().kontakte.some((k) => k.nachname === "Lokal"),
    "Rechner-Kontakt nicht übernommen");
  assert.ok($("#zettel").textContent.includes("Gefunden – Evolution"),
    "Fundbericht fehlt auf dem Zettel");
  assert.ok(/art === "lokal"[\s\S]{0,80}cmd: "import_lokal"/.test(js),
    "Rechner-Import sendet nicht import_lokal");
  w.App.exportErgebnis({ ok: true, abgebrochen: false,
    pfad: "/tmp/Meine Termine.ics", anzahl: 2 });
  assert.strictEqual($("#zettel").textContent,
    "Abgelegt: /tmp/Meine Termine.ics (2 Einträge)",
    "deutscher Exportpfad oder Plural ist falsch");

  /* ---- Datenübernahme aus „Organizer Klassik“ (Browser-Speicher) ---- */
  const dom2 = new JSDOM(html, { runScripts: "dangerously",
    url: "https://organizer.test/", pretendToBeVisual: true });
  dom2.window.localStorage.setItem("organizer-klassik-daten", JSON.stringify({
    version: 1,
    termine: [{ id: "alt1", datum: "2026-07-30", zeit: "14:00", titel: "Alter Termin" }],
    aufgaben: [], kontakte: [], notizen: [], jahrestage: []
  }));
  ladeAnwendung(dom2.window);
  for (let i = 0; i < 50 && !dom2.window.OrganizerTest.daten().termine.length; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  const alt = dom2.window.OrganizerTest.daten();
  assert.strictEqual(alt.termine.length, 1, "Migration übernimmt Termine nicht");
  assert.strictEqual(alt.termine[0].titel, "Alter Termin");
  assert.strictEqual(alt.notizen.length, 0, "Migration darf keine Willkommensnotiz anlegen");
  assert.strictEqual(alt.version, 6, "alte Daten werden nicht auf Schema 6 normalisiert");
  assert.strictEqual(alt.einstellungen.regional.language, "de",
    "alte Daten verlieren die bisherige deutsche Darstellung");
  assert.strictEqual(alt.einstellungen.adressen.foto, true,
    "beim Umstieg werden Kontaktfotos einmalig eingeschaltet");
  assert.strictEqual(alt.einstellungen.erinnerung.protokoll, false,
    "beim Umstieg wird das Fehlerprotokoll einmalig ausgeschaltet");

  /* ---- Gewählte Ansicht überdauert den Neustart ---- */
  klickeTab("Kalender");
  $$(".u-knopf").find((b) => b.textContent === "Woche").click();
  assert.strictEqual(T.daten().einstellungen.ansicht, "week",
    "Wochenansicht nicht gemerkt");
  T.speichereJetzt();
  const gemerkt = JSON.parse(w.localStorage.getItem("magnolie-organizer-daten"));
  assert.strictEqual(gemerkt.einstellungen.ansicht, "week",
    "Ansicht nicht mitgespeichert");

  const dom3 = new JSDOM(html, { runScripts: "dangerously",
    url: "https://organizer.test/", pretendToBeVisual: true });
  dom3.window.localStorage.setItem("magnolie-organizer-daten",
    JSON.stringify(gemerkt));
  ladeAnwendung(dom3.window);
  for (let i = 0; i < 50 && !dom3.window.OrganizerTest.daten().notizen.length; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.strictEqual(dom3.window.OrganizerTest.zustand().kalender.ansicht, "week",
    "Wochenansicht wird beim Start nicht wiederhergestellt");
  assert.strictEqual(
    dom3.window.OrganizerTest.daten().einstellungen.erinnerung.protokoll, true,
    "bewusst eingeschaltetes Protokoll wird nach der Umstellung bewahrt");
  assert.strictEqual(dom3.window.document.querySelectorAll(".wo-tag").length, 7,
    "Wochenblatt erscheint nach dem Start nicht");
  $$(".u-knopf").find((b) => b.textContent === "Monat").click();

  /* ---- Tagesverzeichnis bleibt bei Änderungen aktuell ---- */
  klickeTab("Kalender");
  const heuteIso = T.zustand().kalender.tag;
  const vorher = T.daten().termine.filter((x) => x.datum === heuteIso).length;
  T.daten().termine.push({ id: "idx1", uid: "mag-idx@x", datum: heuteIso,
    zeit: "06:05", endZeit: "06:35", titel: "Frühe Prüfung", notiz: "",
    kategorien: "", vertraulich: false, vorlaeufig: false,
    kostenstelle: "", kunde: "", geaendert: Date.now(), sync: false });
  T.planeSpeichern();
  T.wechsel("notizen");
  T.wechsel("kalender");
  assert.ok($("#inhalt-rechts").textContent.includes("Frühe Prüfung"),
    "neuer Termin erscheint nicht im Tagesblatt");
  assert.strictEqual(
    T.daten().termine.filter((x) => x.datum === heuteIso).length, vorher + 1,
    "Termin wurde nicht angelegt");
  const zeilen = $$("#inhalt-rechts .ue-zeit").map((z) => z.textContent);
  assert.ok(zeilen.length, "keine Termine in der Übersicht");
  assert.strictEqual(zeilen[0].slice(0, 5), "06:05",
    "Übersicht nicht nach der Zeit sortiert: " + zeilen.join(", "));
  T.daten().termine = T.daten().termine.filter((x) => x.id !== "idx1");
  T.planeSpeichern();
  T.wechsel("notizen");
  T.wechsel("kalender");
  assert.ok(!$("#inhalt-rechts").textContent.includes("Frühe Prüfung"),
    "gelöschter Termin verschwindet nicht aus dem Tagesblatt");

  /* ---- Adressen weiterverwenden ---- */
  klickeTab("Adressen");
  const kartenName = $$("#inhalt-links .zeile")[0];
  if (kartenName) kartenName.click();
  assert.ok($(".kontakt-karte"), "Karteikarte wird nicht gezeigt");
  const wegeKnoepfe = $$(".k-wege .bildknopf").map((b) => b.textContent);
  assert.ok(wegeKnoepfe.includes("Brief"), "Knopf „Brief“ fehlt: " + wegeKnoepfe);
  assert.ok(wegeKnoepfe.includes("Karte"), "Knopf „Karte“ fehlt");
  assert.ok(!wegeKnoepfe.includes("Drucken"),
    "die Karteikarte darf keinen zweiten Druckknopf enthalten");
  assert.ok($$(".k-wege .sinnbild").length >= 3,
    "die Knöpfe tragen keine Sinnbilder");

  /* Druckvorschau mit Mehrfachauswahl */
  const druckSuchKontakt = T.daten().kontakte[0];
  const alteDruckSuchNotiz = druckSuchKontakt.notiz;
  druckSuchKontakt.notiz = "DrucksucheEinzigartig";
  $("#knopf-drucken").click();
  assert.ok($("#druck-schleier"), "Druckvorschau erscheint nicht");
  const haken = $$(".druck-zeile input");
  assert.strictEqual(haken.length, T.daten().kontakte.length,
    "jede Karteikarte muss wählbar sein");
  assert.strictEqual(haken.filter((h) => h.checked).length, 0,
    "der allgemeine Druckknopf soll zunächst keine Karte vorauswählen");
  const druckSuche = $(".druck-suche");
  assert.ok(druckSuche && druckSuche.placeholder === "Suche",
    "Suchfeld mit übersetzter Beschriftung fehlt in den Auswahloptionen");
  druckSuche.value = "drucksucheeinzigartig";
  druckSuche.dispatchEvent(new w.Event("input", { bubbles: true }));
  const sichtbareDruckzeilen = $$(".druck-zeile").filter((zeile) => !zeile.hidden);
  assert.strictEqual(sichtbareDruckzeilen.length, 1,
    "Druckauswahl durchsucht nicht den vollständigen Eintrag");
  sichtbareDruckzeilen[0].querySelector("input").click();
  druckSuche.value = "ohne-jeden-treffer";
  druckSuche.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.ok(!$(".druck-kein-suchtreffer").hidden,
    "Druckauswahl zeigt bei einer erfolglosen Suche keinen Hinweis");
  druckSuche.value = "";
  druckSuche.dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.ok(haken[0].checked && $$(".druck-zeile").every((zeile) => !zeile.hidden),
    "Filtern verliert gesetzte Haken oder stellt die Liste nicht wieder her");
  knopfMit("Keine", $("#druck-schleier")).click();
  druckSuchKontakt.notiz = alteDruckSuchNotiz;
  knopfMit("Alle", $("#druck-schleier")).click();
  assert.strictEqual($$(".druck-vorschau .druck-karte").length,
    T.daten().kontakte.length, "„Alle“ wählt nicht alles aus");
  knopfMit("Keine", $("#druck-schleier")).click();
  assert.strictEqual($$(".druck-vorschau .druck-karte").length, 0,
    "„Keine“ leert die Auswahl nicht");
  assert.ok($(".druck-vorschau").textContent.includes("auswählen"),
    "ohne Auswahl fehlt der Hinweis");

  /* Drucken geht auch auf den anderen Seiten */
  if ($("#druck-schleier")) {
    knopfMit("Abbrechen", $("#druck-schleier")).click();
  }
  assert.ok(!$("#druck-schleier"), "Druckvorschau lässt sich nicht schließen");
  assert.ok($("#knopf-drucken"), "Druckknopf in der Statusleiste fehlt");
  klickeTab("Aufgaben");
  $("#knopf-drucken").click();
  assert.ok($("#druck-schleier"), "Druckvorschau der Aufgaben fehlt");
  assert.ok($(".druck-blatt h2").textContent.includes("Aufgaben"),
    "falsche Überschrift: " + $(".druck-blatt h2").textContent);
  assert.ok($(".druck-vorschau").textContent.includes("☐") ||
    $(".druck-vorschau").textContent.includes("☑"),
    "Aufgaben werden nicht als Kästchen gezeigt");
  knopfMit("Abbrechen", $("#druck-schleier")).click();

  klickeTab("Notizen");
  $("#knopf-drucken").click();
  assert.ok($(".druck-blatt h2").textContent.includes("Notizen"),
    "Druckvorschau der Notizen fehlt");
  assert.strictEqual($$(".druck-zeile").length, T.daten().notizen.length,
    "jede Notizseite muss wählbar sein");
  assert.ok(knopfMit("Auswahl löschen", $("#druck-schleier")),
    "Sammellöschen fehlt in den Auswahloptionen der Notizen");
  knopfMit("Abbrechen", $("#druck-schleier")).click();

  klickeTab("Kalender");
  $("#knopf-drucken").click();
  assert.ok($(".druck-blatt h2").textContent.includes("Termine"),
    "Druckvorschau des Kalenders fehlt");
  knopfMit("Abbrechen", $("#druck-schleier")).click();

  klickeTab("Jahrestage");
  $("#knopf-drucken").click();
  assert.ok($(".druck-blatt h2").textContent.includes("Jahrestage"),
    "Druckvorschau der Jahrestage fehlt");
  assert.ok(knopfMit("Auswahl löschen", $("#druck-schleier")),
    "Sammellöschen fehlt in den Auswahloptionen der Jahrestage");
  knopfMit("Abbrechen", $("#druck-schleier")).click();

  const sammelNotiz = { id: "sammel-notiz", titel: "Sammelnotiz", text: "Probe",
    html: "<p>Probe</p>", anhaenge: [], notizbuchId: T.daten().notizbuecher[0].id,
    geaendert: "2026-08-05" };
  T.daten().notizen.push(sammelNotiz);
  T.oeffneDruckvorschau(sammelNotiz, "notizen");
  knopfMit("Auswahl löschen", $("#druck-schleier")).click();
  $("#dialog-ja").click();
  await tick();
  assert.ok(!T.daten().notizen.some((n) => n.id === sammelNotiz.id) &&
    T.daten().papierkorb.some((e) => e.art === "note" && e.eintrag.id === sammelNotiz.id),
  "ausgewählte Notizen werden nicht gesammelt über den Papierkorb gelöscht");
  knopfMit("Abbrechen", $("#druck-schleier")).click();
  T.daten().papierkorb = T.daten().papierkorb.filter((e) => e.eintrag.id !== sammelNotiz.id);

  const geburtstagsKontakt = T.daten().kontakte[0];
  const alterGeburtstag = geburtstagsKontakt.geburtstag;
  geburtstagsKontakt.geburtstag = "1980-04-05";
  const sammelJahrestag = { id: "sammel-jahrestag", kontaktId: geburtstagsKontakt.id,
    uid: "", name: "Sammelgeburtstag", datum: "1980-04-05", typ: "birthday" };
  T.daten().jahrestage.push(sammelJahrestag);
  T.oeffneDruckvorschau(null, "jahrestage");
  knopfMit("Keine", $("#druck-schleier")).click();
  const sammelZeile = Array.from($$(".druck-zeile"))
    .find((zeile) => zeile.textContent.includes("Sammelgeburtstag"));
  sammelZeile.querySelector("input").click();
  knopfMit("Auswahl löschen", $("#druck-schleier")).click();
  $("#dialog-ja").click();
  await tick();
  assert.ok(!T.daten().jahrestage.some((j) => j.id === sammelJahrestag.id) &&
    geburtstagsKontakt.geburtstag === "" &&
    T.daten().papierkorb.some((e) => e.art === "anniversary" &&
      e.eintrag.id === sammelJahrestag.id),
  "ausgewählte Jahrestage löschen weder Papierkorbeintrag noch Kontaktgeburtstag korrekt: " +
    JSON.stringify({ vorhanden: T.daten().jahrestage.some((j) =>
      j.id === sammelJahrestag.id), geburtstag: geburtstagsKontakt.geburtstag,
      papierkorb: T.daten().papierkorb.map((e) => [e.art, e.eintrag.id]) }));
  knopfMit("Abbrechen", $("#druck-schleier")).click();
  geburtstagsKontakt.geburtstag = alterGeburtstag;
  T.daten().papierkorb = T.daten().papierkorb.filter(
    (e) => e.eintrag.id !== sammelJahrestag.id);
  klickeTab("Adressen");
  if ($$("#inhalt-links .zeile")[0]) $$("#inhalt-links .zeile")[0].click();

  /* Die Seite, die aufs Papier geht */
  const seite = T.druckSeite(T.daten().kontakte.slice(0, 2));
  assert.ok(seite.startsWith("<!DOCTYPE html"), "Druckseite ist kein HTML");
  assert.ok(seite.includes("@page"), "Seitenränder fehlen");
  assert.ok(seite.includes("Magnolie Organizer"), "Kopfzeile fehlt");
  assert.strictEqual((seite.match(/class="karte"/g) || []).length, 2,
    "es müssen beide Karteikarten enthalten sein");
  assert.ok(seite.includes("0203 999999") && seite.includes("Zweigweg 9"),
    "zusätzliche Rufnummern oder Anschriften fehlen im Ausdruck");
  assert.ok(seite.includes("Peter Beispiel") && seite.includes("0203 765432"),
    "die Kontaktperson fehlt im Ausdruck");
  const boese = T.druckSeite([{ id: "x", nachname: "<script>", vorname: "",
    firma: "", strasse: "", plz: "", ort: "", telefon: "", mobil: "",
    email: "", notiz: "" }]);
  assert.ok(!boese.includes("<script>"), "spitze Klammern nicht entschärft");
  const boeserTitel = T.druckSeite([], {
    titel: '</title><script id="titel-angriff">boese()</script>',
    wort: "Einträge", karte: () => "", anzahl: () => "0 Einträge"
  });
  assert.ok(!boeserTitel.includes('<script id="titel-angriff">') &&
    boeserTitel.includes("Content-Security-Policy"),
    "Drucktitel ist nicht als Text behandelt oder die CSP fehlt");

  /* Einstellungsseite „Adressen“ */
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  assert.ok($("#adressen-absender"), "Feld für die eigene Anschrift fehlt");
  setze($("#adressen-absender"), "Erika Beispiel\nMusterweg 3");
  assert.ok(T.daten().einstellungen.adressen.absender.includes("Erika"),
    "eigene Anschrift nicht gemerkt");
  assert.deepStrictEqual(
    Array.from($("#adressen-karten").options).map((o) => o.value),
    ["auto", "gnome-maps", "openstreetmap", "google"], "vier Kartenwege");
  assert.ok($("#adressen-land"), "Feld für das Land fehlt");
  assert.strictEqual($("#adressen-land").value, "Deutschland",
    "Deutschland ist nicht voreingestellt");
  setze($("#adressen-land"), "Österreich");
  assert.strictEqual(T.daten().einstellungen.adressen.land, "Österreich",
    "Land nicht gemerkt");
  setze($("#adressen-land"), "Deutschland");
  assert.ok($("#adressen-foto"), "optionale Kontaktfotos fehlen");
  assert.strictEqual($("#adressen-foto").checked, true,
    "Kontaktfotos müssen voreingestellt sein");
  assert.strictEqual(T.daten().einstellungen.adressen.foto, true,
    "Foto-Voreinstellung nicht gemerkt");
  assert.strictEqual($("#adressen-brief-layout").value, "compact",
    "die kompakte Absenderzeile muss die voreingestellte Briefvorlage sein");
  assert.deepStrictEqual(
    Array.from($("#adressen-brief-layout").options).map((o) => o.value),
    ["compact", "din5008"], "beide eindeutig benannten Briefvorlagen fehlen");
  assert.ok(!$("#adressen-brief-layout").textContent.includes("wie bisher"),
    "die Briefvorlage darf kein Vorwissen voraussetzen");
  w.App.loBenutzer({ ok: true, absender: "Erika Beispiel\nMusterweg 3" });
  assert.ok(T.daten().einstellungen.adressen.absender.includes("Musterweg"),
    "Anschrift aus LibreOffice nicht übernommen");
  assert.strictEqual($("#adressen-absender").value.split("\n")[0],
    "Erika Beispiel", "das Feld zeigt die übernommene Anschrift nicht");

  /* Sortierung des Adressbuchs */
  const sortWahl = $("#adressen-sortierung");
  assert.ok(sortWahl, "Auswahl der Sortierung fehlt");
  assert.strictEqual(sortWahl.value, "last-name",
    "nach Nachnamen ist die Voreinstellung");
  T.schliesseEinstellungen();
  klickeTab("Adressen");
  assert.ok($("#inhalt-links").textContent.includes("Beispiel, Anna"),
    "Name steht nicht in der gewohnten Form");
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  $("#adressen-sortierung").value = "first-name";
  $("#adressen-sortierung").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.adressen.sortierung, "first-name",
    "Sortierung nicht gemerkt");
  T.schliesseEinstellungen();
  klickeTab("Adressen");
  assert.ok($("#inhalt-links").textContent.includes("Anna Beispiel"),
    "Name folgt der Sortierung nicht: " + $("#inhalt-links").textContent.slice(0, 80));
  const aktivesRegister = T.zustand().adressen.buchstabe;
  assert.strictEqual(aktivesRegister, "A",
    "Register springt bei Vornamen-Sortierung nicht auf A (war " +
    aktivesRegister + ")");
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  $("#adressen-sortierung").value = "last-name";
  $("#adressen-sortierung").dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#adressen-karte").checked = false;
  $("#adressen-karte").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.adressen.karte, false,
    "Ausblenden nicht gemerkt");
  T.schliesseEinstellungen();
  klickeTab("Adressen");
  if ($$("#inhalt-links .zeile")[0]) $$("#inhalt-links .zeile")[0].click();
  assert.ok(!$$(".k-wege .bildknopf").map((b) => b.textContent).includes("Karte"),
    "ausgeblendeter Knopf erscheint trotzdem");
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  $("#adressen-karte").checked = true;
  $("#adressen-karte").dispatchEvent(new w.Event("change", { bubbles: true }));
  T.schliesseEinstellungen();

  /* ---- Papierkorb ---- */
  klickeTab("Notizen");
  knopfMit("Neue Seite").click();
  const zumLoeschen = T.daten().notizen[T.daten().notizen.length - 1];
  setze($("#notiz-titel"), "Wegwerfseite");
  const anzahlVorher = T.daten().notizen.length;
  const loeschX = $$("#inhalt-links .zeile").find(
    (z2) => z2.textContent.includes("Wegwerfseite")).querySelector(".loesch-x");
  loeschX.click();
  $("#dialog-ja").click();
  await tick();
  assert.strictEqual(T.daten().notizen.length, anzahlVorher - 1,
    "Notiz nicht gelöscht");
  const imKorb = T.daten().papierkorb.find((s) => s.name === "Wegwerfseite");
  assert.ok(imKorb, "die gelöschte Notiz liegt nicht im Papierkorb");
  assert.strictEqual(imKorb.art, "note", "falsche Art im Papierkorb");

  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Sicherheit").click();
  assert.ok($("#papierkorb-an"), "Schalter für den Papierkorb fehlt");
  assert.ok($("#papierkorb-stand").textContent.includes("1 Notiz"),
    "Standanzeige nennt die Notizen nicht: " + $("#papierkorb-stand").textContent);
  assert.deepStrictEqual(
    Array.from($("#papierkorb-tage").options).map((o) => o.value),
    ["7", "30", "90", "365", "0"], "Fristen zum endgültigen Löschen");
  assert.strictEqual($("#papierkorb-tage").value, "30",
    "30 Tage sind voreingestellt");
  const holZeile = $$("#papierkorb-liste .pk-zeile").find(
    (z2) => z2.textContent.includes("Wegwerfseite"));
  assert.ok(holZeile, "die Notiz steht nicht in der Papierkorbliste");
  const holKnopf = holZeile.querySelector("button");
  assert.ok(holKnopf, "Knopf zum Zurückholen fehlt");
  holKnopf.click();
  assert.strictEqual(T.daten().notizen.length, anzahlVorher,
    "Notiz nicht zurückgeholt");
  assert.ok(!T.daten().papierkorb.some((s) => s.name === "Wegwerfseite"),
    "Eintrag bleibt im Papierkorb liegen");

  /* Alte Einträge verschwinden von selbst */
  T.inDenPapierkorb("termin", { id: "alt", datum: "2020-01-01", titel: "Uralt" },
    "Uralt");
  T.daten().papierkorb[T.daten().papierkorb.length - 1].geloescht =
    Date.now() - 40 * 86400000;
  assert.strictEqual(T.raeumePapierkorbAuf(), 1,
    "alter Eintrag wird nicht weggeräumt");

  /* ---- Doppelte Karteikarten ---- */
  T.daten().kontakte.push(
    { id: "d1", uid: "mag-d1@x", nachname: "Doppel", vorname: "Dieter",
      firma: "", strasse: "Musterstraße 7", plz: "47051", ort: "Duisburg", telefon: "0203 1",
      mobil: "", email: "maik3531@gmail.com", emails: ["maik3531@gmail.com"],
      anschriften: [{ strasse: "Musterstraße 7", plz: "47051", ort: "Duisburg" }],
      notiz: "erste Karte", geaendert: 1, sync: false },
    { id: "d2", uid: "mag-d2@x", nachname: "Doppel", vorname: "Dieter",
      firma: "Doppel GmbH", strasse: "Musterstr. 7", plz: "47051", ort: "Duisburg",
      telefon: "", mobil: "0171 2", email: "MAIK3531@GMAIL.COM",
      emails: ["MAIK3531@GMAIL.COM", "d@example.de"],
      anschriften: [{ strasse: "Musterstr. 7", plz: "47051", ort: "Duisburg" },
        { strasse: "Zweigweg 9", plz: "47441", ort: "Moers" }],
      notiz: "zweite Karte", geaendert: 2, sync: false });
  const gruppen = T.findeDubletten();
  assert.ok(gruppen.some((g) => g.length === 2 &&
    g.every((k) => k.nachname === "Doppel")),
    "die doppelte Karteikarte wird nicht gefunden");
  const erg = T.fuehreZusammen(gruppen.find((g) => g[0].nachname === "Doppel"));
  assert.strictEqual(erg.entfernt.length, 1, "eine Karte müsste weichen");
  assert.ok(/Musterstr/.test(erg.bleibt.strasse), "Straße nicht übernommen");
  assert.strictEqual(erg.bleibt.ort, "Duisburg", "Ort nicht ergänzt");
  assert.deepStrictEqual(Array.from(erg.bleibt.emails),
    ["MAIK3531@GMAIL.COM", "d@example.de"],
    "E-Post-Großschreibung wurde nicht als dieselbe Adresse erkannt");
  assert.strictEqual(erg.bleibt.telefone.length, 2, "Rufnummern nicht zusammengelegt");
  assert.strictEqual(erg.bleibt.anschriften.length, 2,
    "gleich geschriebene und zusätzliche Anschriften falsch zusammengelegt");
  assert.ok(erg.bleibt.notiz.includes("erste") && erg.bleibt.notiz.includes("zweite"),
    "Notizen nicht zusammengelegt: " + erg.bleibt.notiz);
  const cardbookZusammen = T.fuehreZusammen([
    { id: "cb", nachname: "CardBook", vorname: "Clara", firma: "Google",
      telefon: "", mobil: "0171 222222", telefone: [
        { wert: "0171 222222", typen: ["CELL"] }], notiz: "aktive Karte" },
    { id: "tb", nachname: "CardBook", vorname: "Clara", firma: "",
      telefon: "0171 222222", mobil: "", telefone: [
        { wert: "0171 222222", typen: ["FAX"] }], notiz: "" }
  ]).bleibt;
  assert.strictEqual(cardbookZusammen.telefone.length, 1,
    "dieselbe CardBook- und Thunderbird-Nummer wird doppelt behalten");
  assert.ok(cardbookZusammen.telefone[0].typen.includes("CELL") &&
    !cardbookZusammen.telefone[0].typen.includes("FAX"),
  "passiver Thunderbird-Typ überschreibt CardBooks Mobil-Kennzeichnung");
  T.daten().kontakte = T.daten().kontakte.filter(
    (k) => k.id !== "d1" && k.id !== "d2");

  /* ---- Bearbeiten-Menü beim Rechtsklick ---- */
  klickeTab("Jahrestage");
  const textfeld = $("#inhalt-rechts fieldset input[type=text]");
  setze(textfeld, "Zum Kopieren");
  textfeld.focus();
  textfeld.setSelectionRange(0, 4);
  textfeld.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 100, clientY: 100 }));
  assert.ok($("#vorschlags-menue"), "Bearbeiten-Menü erscheint nicht");
  const menueWorte = $$("#vorschlags-menue .vm-eintrag").map((b) => b.textContent);
  assert.ok(menueWorte.some((x) => x.includes("Kopieren")), "Kopieren fehlt");
  assert.ok(menueWorte.some((x) => x.includes("Ausschneiden")), "Ausschneiden fehlt");
  assert.ok(menueWorte.some((x) => x.includes("Einfügen")), "Einfügen fehlt");
  $$("#vorschlags-menue .vm-eintrag").find(
    (b) => b.textContent.includes("Ausschneiden")).click();
  assert.strictEqual(textfeld.value, "Kopieren",
    "Ausschneiden entfernt den markierten Text nicht: " + textfeld.value);
  textfeld.focus();
  textfeld.setSelectionRange(0, 0);
  textfeld.dispatchEvent(new w.MouseEvent("contextmenu",
    { bubbles: true, cancelable: true, clientX: 100, clientY: 100 }));
  $$("#vorschlags-menue .vm-eintrag").find(
    (b) => b.textContent.includes("Einfügen")).click();
  w.App.ablage({ text: "Zum " });
  assert.strictEqual(textfeld.value, "Zum Kopieren",
    "Einfügen setzt den Text nicht wieder ein: " + textfeld.value);
  const rechtschreibungVorher = T.daten().einstellungen.schrift.rechtschreibung;
  for (const [typ, rechtschreibung, inhalt] of [
    ["tel", false, "+49 203 123456"], ["email", true, "post@example.de"]]) {
    T.daten().einstellungen.schrift.rechtschreibung = rechtschreibung;
    const feld = d.createElement("input");
    feld.type = typ;
    d.body.append(feld);
    feld.focus();
    try { feld.setSelectionRange(0, 0); } catch (fehler) { /* nicht jeder Eingabetyp erlaubt es */ }
    feld.dispatchEvent(new w.MouseEvent("contextmenu",
      { bubbles: true, cancelable: true, clientX: 120, clientY: 120 }));
    const einfuegen = $$("#vorschlags-menue .vm-eintrag").find(
      (b) => b.textContent.includes("Einfügen"));
    assert.ok(einfuegen && !einfuegen.disabled,
      "Einfügen fehlt im Rechtsklickmenü für input[type=" + typ + "]");
    einfuegen.click();
    w.App.ablage({ text: inhalt });
    assert.strictEqual(feld.value, inhalt,
      "Rechtsklick-Einfügen funktioniert nicht für input[type=" + typ + "]");
    feld.remove();
  }
  T.daten().einstellungen.schrift.rechtschreibung = rechtschreibungVorher;
  w.App.ablage({ text: "" });
  assert.strictEqual($("#zettel").textContent, "Die Zwischenablage ist leer.",
    "deutscher Zwischenablagehinweis fehlt");
  w.App.wortGemerkt({ ok: true, wort: "Duisburg" });
  assert.strictEqual($("#zettel").textContent,
    "„Duisburg“ steht nun im Wörterbuch.",
  "deutsche Wörterbuchmeldung verändert das aufgenommene Wort");
  setze(textfeld, "");

  /* ---- Sperrbildschirm mit Zahlenschloss ---- */
  const bestand = JSON.parse(JSON.stringify(T.daten()));
  w.App.init({ gesperrt: true, wartet: 0, datenPfad: "/heim" });
  assert.ok($("#sperr-schleier"), "Sperrbildschirm erscheint nicht");
  assert.ok($(".sperr-bluete"), "die Magnolienblüte fehlt auf dem Schloss");
  const tasten = $$(".zahl-taste");
  assert.strictEqual(tasten.length, 12,
    "zehn Ziffern, Löschen und Bestätigen erwartet");
  assert.deepStrictEqual(tasten.slice(0, 9).map((b) => b.textContent),
    ["1", "2", "3", "4", "5", "6", "7", "8", "9"], "Ziffernfolge");

  /* Eingabe über die Tastatur (auch am Zahlenblock) */
  const tippe = (taste) => d.dispatchEvent(new w.KeyboardEvent("keydown",
    { key: taste, bubbles: true, cancelable: true }));
  tippe("4"); tippe("7"); tippe("0"); tippe("5");
  assert.strictEqual(T.sperrEingabe(), "4705",
    "Ziffern von der Tastatur kommen nicht an: " + T.sperrEingabe());
  assert.strictEqual($$("#sperr-punkte .sperr-punkt").length, 4,
    "die Punkte folgen der Tastatureingabe nicht");
  tippe("Backspace");
  assert.strictEqual(T.sperrEingabe(), "470", "Rücktaste löscht nicht");
  tippe("Escape");
  assert.strictEqual(T.sperrEingabe(), "", "Escape leert die Eingabe nicht");

  tasten.find((b) => b.textContent === "1").click();
  tasten.find((b) => b.textContent === "9").click();
  tasten.find((b) => b.textContent === "0").click();
  assert.strictEqual(T.sperrEingabe(), "190", "Eingabe wird nicht gesammelt");
  assert.strictEqual($$("#sperr-punkte .sperr-punkt").length, 3,
    "drei Punkte für drei Stellen erwartet");
  tasten.find((b) => b.textContent === "←").click();
  assert.strictEqual(T.sperrEingabe(), "19", "Löschen wirkt nicht");
  assert.strictEqual($$("#sperr-punkte .sperr-punkt").length, 2,
    "Punktzahl folgt der Eingabe nicht");

  /* Einfügen aus der Zwischenablage ist nicht erlaubt */
  const sperrFeld = $("#sperr-feld");
  const einfuegeEreignis = new w.Event("paste", { bubbles: true, cancelable: true });
  sperrFeld.dispatchEvent(einfuegeEreignis);
  assert.ok(einfuegeEreignis.defaultPrevented,
    "Einfügen in das Kennwortfeld müsste unterbunden sein");

  /* Umschalten auf Buchstaben */
  $("#sperr-umschalter").click();
  assert.strictEqual($("#zahlenschloss").style.display, "none",
    "Zahlenschloss bleibt sichtbar");
  assert.notStrictEqual($("#sperr-feld").style.display, "none",
    "Kennwortfeld erscheint nicht");
  $("#sperr-umschalter").click();

  /* Fehlversuch mit Wartezeit */
  w.App.entsperrtFehler({ fehler: "Das Kennwort stimmt nicht.", wartet: 300 });
  assert.strictEqual(T.sperrEingabe(), "", "die Eingabe wird nicht geleert");
  assert.ok($("#sperr-hinweis").textContent.includes("stimmt nicht"),
    "die Meldung fehlt");
  assert.ok($("#sperr-fuss").textContent.includes("Fehlversuche"),
    "die Wartezeit wird nicht angezeigt: " + $("#sperr-fuss").textContent);
  assert.ok($("#zahlenschloss").classList.contains("gesperrt"),
    "das Zahlenschloss müsste gesperrt sein");
  assert.ok($("#sperr-feld").disabled, "das Kennwortfeld müsste gesperrt sein");

  /* Reiter: alle nebeneinander oder kompakt auf zwei Zeilen */
  const bestandVorReitern = JSON.parse(JSON.stringify(T.daten()));
  w.App.init({ daten: bestandVorReitern, neu: false, datenPfad: "/heim" });
  T.oeffneEinstellungen();
  const reiterZeile = $(".einst-reiter");
  assert.ok(reiterZeile, "Reiterzeile fehlt");
  assert.strictEqual(T.reiterOrdnung(852, 888), "eine-reihe",
    "auf breitem Blatt gehören alle Reiter in eine Zeile");
  assert.strictEqual(T.reiterOrdnung(852, 700), "zwei-reihen",
    "auf schmalem Blatt sind es zwei Reihen");
  assert.strictEqual(T.reiterOrdnung(700, 700), "eine-reihe",
    "genau passend zählt als eine Reihe");
  assert.strictEqual(T.reiterOrdnung(701, 700), "eine-reihe",
    "ein Gerätepunkt Spielraum bleibt");
  assert.strictEqual(T.reiterOrdnung(702, 700), "zwei-reihen",
    "darüber wird umgebrochen");
  assert.strictEqual(T.reiterOrdnung(852, 0), "eine-reihe",
    "ohne Messung wird nichts umgebrochen");
  const art = T.ordneReiter();
  assert.ok(art === "eine-reihe" || art === "zwei-reihen",
    "die Reiter wurden nicht eingeordnet: " + art);
  if (art === "zwei-reihen") {
    assert.ok(reiterZeile.classList.contains("zwei-reihen"),
      "bei zwei Reihen fehlt die Kennzeichnung");
  } else {
    assert.ok(!reiterZeile.classList.contains("zwei-reihen"),
      "eine Reihe darf nicht als zwei gekennzeichnet sein");
  }
  T.schliesseEinstellungen();
  w.App.init({ gesperrt: true, wartet: 0, datenPfad: "/heim" });

  /* Die Notbremse beim Start darf die Sperre nicht wegräumen */
  await new Promise((r) => setTimeout(r, 3000));
  assert.ok($("#sperr-schleier"),
    "der Sperrbildschirm verschwand von selbst – die Notbremse hat zugeschlagen");
  assert.strictEqual(T.daten().kontakte.length, 0,
    "hinter der Sperre darf kein Buch aufgeschlagen werden");

  /* Solange gesperrt, wird nichts gespeichert */
  const vorherGespeichert = w.localStorage.getItem("magnolie-organizer-daten");
  T.speichereJetzt();
  assert.strictEqual(w.localStorage.getItem("magnolie-organizer-daten"),
    vorherGespeichert, "während der Sperre wurde geschrieben");

  /* Nach dem Entsperren verschwindet alles wieder */
  w.App.init({ daten: bestand, neu: false, datenPfad: "/heim", kennwort: true });
  assert.ok(!$("#sperr-schleier"), "Sperrbildschirm bleibt stehen");
  assert.strictEqual(T.daten().kontakte.length, bestand.kontakte.length,
    "die Daten kamen nicht zurück");

  /* ---- Tagesansicht im Einzelnen ---- */
  klickeTab("Kalender");
  const heuteT = T.zustand().kalender.tag;
  T.oeffneTerminBlatt(null, heuteT);
  setze($("#tb-titel"), "Frühbesprechung");
  setze($("#tb-zeit"), "07:30");
  setze($("#tb-endzeit"), "08:15");
  $("#tb-fertig").click();
  await tick();

  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "day").click();
  assert.strictEqual(T.zustand().kalender.ansicht, "day", "Tagesansicht nicht aktiv");
  assert.strictEqual($$(".tages-spalte").length, 2, "zwei Tage erwartet");

  /* Links der gewählte Tag, rechts der folgende */
  const dLinks = new Date(T.zustand().kalender.tag);
  const dRechts = new Date(dLinks);
  dRechts.setDate(dRechts.getDate() + 1);
  assert.ok($("#kopf-rechts").textContent.includes(String(dRechts.getDate())),
    "rechts steht nicht der folgende Tag: " + $("#kopf-rechts").textContent);

  /* Zeitangaben am linken Rand */
  const marken = $$("#inhalt-links .stunden-marke").map((m) => m.textContent);
  assert.ok(marken.includes("06:00"), "6 Uhr fehlt: " + marken.slice(0, 3));
  assert.ok(marken.includes("09:00") && marken.includes("12:00"),
    "9 und 12 Uhr fehlen");
  const stundenReihen = $$("#inhalt-links .stunden-reihe");
  assert.strictEqual(stundenReihen.length, 17, "das Tagesraster hat nicht 17 Stunden");
  assert.deepStrictEqual(stundenReihen.map((r) => Number(r.dataset.stunde)),
    Array.from({ length: 17 }, (_, i) => i + 6),
    "die Stunden des Tagesrasters sind nicht lückenlos");
  assert.ok(css.includes("flex: 1 0 var(--tages-stundenhoehe);"),
    "die Stundenreihen teilen den verfügbaren Platz nicht gleichmäßig");
  assert.ok(css.includes("scrollbar-gutter: stable;"),
    "das Tagesraster reserviert keinen stabilen Platz für den Rollbalken");
  const linkeSpalte = $("#inhalt-links .tages-spalte");
  assert.strictEqual(linkeSpalte.lastElementChild.className, "tages-fuss",
    "der Fußbereich schließt die Tagesansicht nicht ab");

  /* Der Termin steht in seiner Stunde */
  const stunde7 = $$("#inhalt-links .stunden-reihe").find(
    (r) => r.dataset.stunde === "7");
  assert.ok(stunde7, "die 7-Uhr-Reihe fehlt");
  assert.ok(stunde7.textContent.includes("Frühbesprechung"),
    "der Termin steht nicht in seiner Stunde");

  /* Zwei Tage weiterblättern */
  const vorherTag = T.zustand().kalender.tag;
  $("#ecke-rechts").click();
  const nachherTag = T.zustand().kalender.tag;
  const abstand = Math.round((new Date(nachherTag) - new Date(vorherTag)) / 86400000);
  assert.strictEqual(abstand, 2, "das Eselsohr blättert nicht zwei Tage");
  knopfMit("Heute").click();

  /* Klick auf eine freie Stunde legt einen Termin mit dieser Zeit an */
  const freieStunde = $$("#inhalt-links .stunden-feld").find(
    (f2) => !f2.children.length);
  assert.ok(freieStunde, "keine freie Stunde gefunden");
  freieStunde.click();
  assert.ok($("#termin-schleier"), "Klick auf freie Stunde öffnet kein Blatt");
  assert.ok(/^\d{2}:00$/.test($("#tb-zeit").value),
    "die angeklickte Stunde wurde nicht übernommen: " + $("#tb-zeit").value);
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  /* Der Knopf am Fuß legt einen Termin für genau diesen Tag an */
  const linkerJetzt = new Date(T.zustand().kalender.tag);
  const rechterJetzt = new Date(linkerJetzt);
  rechterJetzt.setDate(rechterJetzt.getDate() + 1);
  $$(".tages-neu")[1].click();
  assert.ok($("#termin-schleier"), "Knopf am Fuß öffnet kein Blatt");
  assert.ok($(".tb-datum").textContent.includes(String(rechterJetzt.getDate())),
    "der Knopf rechts legt nicht für den rechten Tag an: " +
    $(".tb-datum").textContent);
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  T.daten().termine = T.daten().termine.filter((x) => x.titel !== "Frühbesprechung");
  T.planeSpeichern();
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();

  /* ---- Einstellungsseite „Kalender" ---- */
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Kalender").click();
  assert.ok($("#kalender-klick"), "Wahl des Klickverhaltens fehlt");
  assert.deepStrictEqual(
    Array.from($("#kalender-klick").options).map((o) => o.value),
    ["tag", "neu"], "zwei Möglichkeiten erwartet");
  assert.strictEqual($("#kalender-klick").value, "neu",
    "voreingestellt soll gleich ein Termin angelegt werden");
  const wochenNummernHak = $("#kalender-wochennummern");
  assert.ok(wochenNummernHak, "Wahl der Wochennummern fehlt unter Kalender");
  assert.strictEqual(wochenNummernHak.checked, false,
    "Wochennummern müssen voreingestellt aus sein");
  wochenNummernHak.checked = true;
  wochenNummernHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.kalender.wochenNummern, true,
    "Wahl der Wochennummern wird nicht gemerkt");
  assert.strictEqual($$(".kal-kw").length, 6,
    "die Monatsansicht zeigt nicht genau sechs ISO-Wochennummern");
  assert.ok($(".kal-huelle").classList.contains("mit-wochen") &&
    $(".kal-kw-kopf").textContent === "KW",
  "Wochennummern erweitern das Monatsraster nicht um eine KW-Spalte");
  const planerWochenNummernHak = $("#kalender-planer-wochennummern");
  assert.ok(planerWochenNummernHak,
    "Wahl der Wochennummern für den Planer fehlt unter Kalender");
  assert.strictEqual(planerWochenNummernHak.closest("label").textContent.trim(),
    "Wochennummern im Planer anzeigen", "deutsche Planer-Einstellung fehlt");
  assert.strictEqual(planerWochenNummernHak.checked, false,
    "Planer-Wochennummern müssen voreingestellt aus sein");
  planerWochenNummernHak.checked = true;
  planerWochenNummernHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.kalender.planerWochenNummern, true,
    "Wahl der Planer-Wochennummern wird nicht gemerkt");
  T.wechsel("planer");
  assert.ok($$(".mm-kw").length >= 60 && $$(".mm-kw-kopf").length === 12,
    "der Jahresplaner zeigt keine ISO-Wochennummern für alle Monate");
  assert.strictEqual($(".mm-kw-kopf").textContent, "KW");
  assert.match($(".mm-kw").title, /^Kalenderwoche \d+$/);
  T.wechsel("kalender");

  const vergangeneTermineHak = $("#kalender-vergangene-termine");
  const vergangeneJahrestageHak = $("#kalender-vergangene-jahrestage");
  const vergangeneFerienHak = $("#kalender-vergangene-ferien");
  assert.ok(vergangeneTermineHak && vergangeneJahrestageHak && vergangeneFerienHak,
    "Einstellungen zum Ausblenden vergangener Kalendereinträge fehlen");
  assert.ok(!vergangeneTermineHak.checked &&
    $(".kalender-vergangen-felder").style.display === "none",
  "Vergangenheitsfilter oder Unteroptionen sind voreingestellt aktiv");
  const gesternDatum = new Date();
  gesternDatum.setDate(gesternDatum.getDate() - 1);
  const gesternIso = gesternDatum.getFullYear() + "-" +
    String(gesternDatum.getMonth() + 1).padStart(2, "0") + "-" +
    String(gesternDatum.getDate()).padStart(2, "0");
  const vergangenTermin = { id: "vergangen-filter-probe", datum: gesternIso,
    endDatum: "", zeit: "10:00", endZeit: "", titel: "Vergangener Probetermin" };
  const vergangenJahrestag = { id: "vergangen-jahrestag-probe",
    datum: "1900-" + gesternIso.slice(5), name: "Vergangener Probejahrestag",
    typ: "memorial-day" };
  const vergangenFerien = { von: gesternIso, bis: gesternIso,
    name: "Probeferien", art: "school-holiday" };
  const vergangenFeiertag = { von: gesternIso, bis: gesternIso,
    name: "Probe-Feiertag", art: "public-holiday" };
  T.daten().termine.push(vergangenTermin);
  T.daten().jahrestage.push(vergangenJahrestag);
  T.daten().feiertage = T.daten().feiertage.concat(vergangenFerien, vergangenFeiertag);
  T.planeSpeichern();
  assert.ok(T.termineAm(gesternIso).some((t) => t.id === vergangenTermin.id) &&
    T.jahrestageAm(gesternIso).some((jt) => jt.id === vergangenJahrestag.id) &&
    T.feiertageAm(gesternIso).some((f) => f.name === "Probeferien"),
  "vergangene Probeeinträge sind vor dem Einschalten nicht sichtbar");
  vergangeneTermineHak.checked = true;
  vergangeneTermineHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok(!T.termineAm(gesternIso).length && T.jahrestageAm(gesternIso).length &&
    T.feiertageAm(gesternIso).some((f) => f.name === "Probeferien") &&
    $(".kalender-vergangen-felder").style.display === "",
  "der Hauptschalter blendet nicht ausschließlich vergangene Termine aus");
  vergangeneJahrestageHak.checked = true;
  vergangeneJahrestageHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  vergangeneFerienHak.checked = true;
  vergangeneFerienHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok(!T.jahrestageAm(gesternIso).length &&
    !T.feiertageAm(gesternIso).some((f) => f.name === "Probeferien") &&
    T.feiertageAm(gesternIso).some((f) => f.name === "Probe-Feiertag"),
  "Unteroptionen blenden Jahrestage/Ferien nicht getrennt von Feiertagen aus");
  vergangeneTermineHak.checked = false;
  vergangeneTermineHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  T.daten().termine = T.daten().termine.filter((t) => t.id !== vergangenTermin.id);
  T.daten().jahrestage = T.daten().jahrestage.filter((jt) => jt.id !== vergangenJahrestag.id);
  T.daten().feiertage = T.daten().feiertage.filter((f) =>
    !["Probeferien", "Probe-Feiertag"].includes(f.name));
  T.planeSpeichern();
  const wetterHak = $("#kalender-wetter");
  assert.ok(wetterHak, "Wetterwahl fehlt unter Kalender");
  assert.strictEqual(wetterHak.checked, false, "Wetter muss voreingestellt aus sein");
  const wetterDarstellung = $("#kalender-wetter-darstellung");
  const wetterIntervall = $("#kalender-wetter-intervall");
  const wetterOhneOrt = $("#kalender-wetter-ohne-ort");
  assert.deepStrictEqual(Array.from(wetterDarstellung.options).map((o) => o.value),
    ["symbol", "temperature", "detailed"],
    "drei Wetterdarstellungen erwartet");
  assert.strictEqual(wetterDarstellung.value, "temperature",
    "Symbole und Temperaturen müssen Voreinstellung sein");
  assert.deepStrictEqual(Array.from(wetterIntervall.options).map((o) => o.value),
    ["30", "60", "180", "360", "720"],
    "fünf Wetterintervalle erwartet");
  assert.strictEqual(wetterIntervall.value, "180",
    "Wetter muss voreingestellt alle drei Stunden laden");
  assert.ok(wetterDarstellung.disabled && wetterIntervall.disabled &&
    wetterOhneOrt.disabled && !wetterOhneOrt.checked,
    "Wetteroptionen müssen bis zum Einschalten gesperrt sein");
  wetterHak.checked = true;
  wetterHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.wetter, true,
    "Wetterwahl wird nicht gemerkt");
  const wetterDatum = (plus) => {
    const tag = new Date();
    tag.setDate(tag.getDate() + plus);
    return tag.toISOString().slice(0, 10);
  };
  w.App.wetterErgebnis({ ok: true, ort: "Duisburg", quelle: "ip", tage: [
    { datum: wetterDatum(0), min: 17, max: 25, code: 113, beschreibung: "Sonnig" },
    { datum: wetterDatum(1), min: 15, max: 21, code: 296, beschreibung: "Regen" },
    { datum: wetterDatum(2), min: 16, max: 24, code: 116, beschreibung: "Wolkig" }
  ] });
  assert.strictEqual($$(".wetter-tag").length, 3,
    "die Wetteranzeige enthält nicht genau drei Tage");
  assert.strictEqual($$(".wetter-symbol-svg").length, 3,
    "Magnolie-Wettersymbole fehlen");
  assert.strictEqual($$(".wetter-temperatur").length, 3,
    "Temperaturen fehlen in der voreingestellten Darstellung");
  assert.strictEqual($(".wetter-temperatur").textContent, "17° / 25°C",
    "Celsiusdarstellung nennt Wert und Einheit nicht korrekt");
  T.daten().einstellungen.regional.temperatureUnit = "fahrenheit";
  assert.strictEqual(T.temperaturSpanne({ min: 17, max: 25 }), "63° / 77°F",
    "Fahrenheitdarstellung wird nicht aus Celsius berechnet");
  T.daten().einstellungen.regional.temperatureUnit = "system";
  T.daten().einstellungen.regional.formatLocale = "en-US";
  assert.strictEqual(T.temperaturEinheit(), "fahrenheit",
    "US-Systemvorgabe verwendet nicht Fahrenheit");
  T.daten().einstellungen.regional.formatLocale = "de-DE";
  assert.strictEqual(T.temperaturEinheit(), "celsius",
    "deutsche Systemvorgabe verwendet nicht Celsius");
  T.daten().einstellungen.regional.temperatureUnit = "celsius";
  assert.strictEqual($$(".wetter-beschreibung").length, 0,
    "die kompakte Voreinstellung ist nicht kompakt");
  assert.ok($(".wetter-kasten").textContent.includes("Duisburg") &&
    $(".wetter-kasten").textContent.includes("öffentlichen IP-Adresse"),
    "Wetterort oder Hinweis zur IP-Ermittlung fehlt");
  T.daten().einstellungen.adressen.absender =
    "Erika Beispiel\nMusterweg 3\n47051 Duisburg\nDeutschland";
  assert.strictEqual(T.wetterOrtAusAbsender(), "47051 Duisburg",
    "Ort wird nicht aus der eigenen Anschrift gelesen");
  T.daten().einstellungen.adressen.absender = "";
  wetterDarstellung.value = "symbol";
  wetterDarstellung.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual($$(".wetter-temperatur").length, 0,
    "bei Nur-Symbol dürfen keine Temperaturen erscheinen");
  wetterDarstellung.value = "detailed";
  wetterDarstellung.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual($$(".wetter-beschreibung").length, 3,
    "in der ausführlichen Darstellung fehlen Beschreibungen");
  wetterIntervall.value = "30";
  wetterIntervall.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.wetterIntervall, 30,
    "gewählter Wetterabstand wird nicht gemerkt");
  $$("#ansicht-umschalter .u-knopf")
    .find((b) => b.dataset.ansicht === "week").click();
  assert.ok(!$(".wetter-kasten") && $(".wochen-spalte"),
    "eine eigene Wetterleiste zerstört weiterhin das Wochenblatt");
  assert.ok($$(".wo-wetter").length >= 1 && $$(".wo-wetter").length <= 3,
    "das sichtbare Drei-Tage-Wetter steht nicht in den passenden Tageskästen");
  assert.ok($$(".wo-wetter").every((wetter) => wetter.closest(".wo-tag")),
    "Wochenwetter steht außerhalb seines Tages");
  $$("#ansicht-umschalter .u-knopf")
    .find((b) => b.dataset.ansicht === "day").click();
  assert.ok($(".wetter-kasten") && $(".tages-spalte"),
    "Wetter fehlt im Tagesblatt");
  $$("#ansicht-umschalter .u-knopf")
    .find((b) => b.dataset.ansicht === "month").click();
  wetterOhneOrt.checked = true;
  wetterOhneOrt.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.allgemein.wetterOhneOrtAbrufen, false,
    "Wetter-Datenschutzoption wird nicht gespeichert");
  w.App.wetterErgebnis({ ok: true, ohneOrt: true, quelle: "none", tage: [] });
  const wetterLeertext = $(".wetter-kasten").textContent;
  assert.ok(wetterLeertext.includes("kein Ort verfügbar"),
    "unterbundener IP-Fallback zeigt keinen neutralen Leerzustand: " + wetterLeertext);
  assert.ok(!$(".wetter-tag") && !T.wetterStand().fehler,
    "unterbundener IP-Fallback behält alte Wetterdaten oder einen Fehler");
  wetterHak.checked = false;
  wetterHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok(!$(".wetter-kasten"), "Wetter bleibt nach dem Abschalten sichtbar");
  assert.ok(!$("#systemkalender-schalten"),
    "die unzuverlässige Systemkalender-Wahl ist noch vorhanden");
  T.schliesseEinstellungen();

  klickeTab("Jahrestage");
  assert.strictEqual($("#jt-typ").tagName, "INPUT",
    "freie Jahrestagsarten werden nicht als Textfeld angeboten");
  assert.ok($("#jt-typen-vorschlaege") &&
    Array.from($("#jt-typen-vorschlaege").options)
      .some((o) => o.value === "Gründungstag"),
    "bei freier Eingabe fehlen die Vorschläge");
  setze($("#jt-name"), "Eigene Artenprobe");
  setze($("#jt-datum"), "2000-02-03");
  setze($("#jt-typ"), "Familientag");
  knopfMit("Eintragen").click();
  assert.ok(T.daten().jahrestage.some((jt) => jt.typ === "Familientag"),
    "eigene Jahrestagsart wird nicht gespeichert");

  klickeTab("Jahrestage");
  $$("#inhalt-links .zeile").find((zeile) =>
    zeile.textContent.includes("Eigene Artenprobe")).click();
  assert.strictEqual($("#jt-typ").tagName, "INPUT",
    "eine gespeicherte eigene Jahrestagsart ist nicht weiter beschreibbar");
  assert.strictEqual($("#jt-typ").value, "Familientag",
    "eine bereits gespeicherte eigene Art geht verloren");
  T.daten().jahrestage = T.daten().jahrestage.filter((jt) =>
    jt.name !== "Eigene Artenprobe");
  T.zustand().jahrestage.bearbeiteId = null;
  T.planeSpeichern();

  /* ---- Route statt bloßer Karte ---- */
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  const routeHak = $("#adressen-route");
  assert.ok(routeHak, "Ankreuzfeld für die Route fehlt");
  assert.strictEqual(routeHak.checked, false, "Route ist voreingestellt aus");
  routeHak.checked = true;
  routeHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.adressen.route, true,
    "Route nicht gemerkt");
  T.schliesseEinstellungen();
  klickeTab("Adressen");
  if ($$("#inhalt-links .zeile")[0]) $$("#inhalt-links .zeile")[0].click();
  const wegeWorte = $$(".k-wege .bildknopf").map((b) => b.textContent);
  assert.ok(wegeWorte.includes("Route"),
    "der Knopf müsste nun „Route“ heißen: " + wegeWorte);

  /* Ohne eigene Anschrift wird gewarnt statt eine leere Route zu öffnen */
  T.daten().einstellungen.adressen.absender = "";
  const routeKnopf = $$(".k-wege .bildknopf").find(
    (b) => b.textContent === "Route");
  routeKnopf.click();
  assert.ok($("#zettel").textContent.includes("Ausgangspunkt"),
    "es fehlt der Hinweis auf die eigene Anschrift: " + $("#zettel").textContent);

  /* Mit eigener Anschrift erscheint auf der Seite der passende Hinweis */
  T.daten().einstellungen.adressen.absender = "Erika Beispiel\nMusterweg 3\n47051 Duisburg";
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Adressen").click();
  await tick();
  assert.ok($("#adressen-route-hinweis").textContent.includes("Ausgangspunkt"),
    "Hinweis zum Ausgangspunkt fehlt: " + $("#adressen-route-hinweis").textContent);
  assert.ok(!$("#adressen-route-hinweis").classList.contains("warnt"),
    "mit hinterlegter Anschrift darf nicht gewarnt werden");
  T.schliesseEinstellungen();
  T.daten().einstellungen.adressen.route = false;

  /* ---- Voreinstellungen ---- */
  const frisch = T.leereDaten ? T.leereDaten() : null;
  if (frisch) {
    assert.strictEqual(frisch.einstellungen.erinnerung.stil, "magnolie",
      "die Meldung im Stil der Magnolie soll voreingestellt sein");
    assert.strictEqual(frisch.einstellungen.kalender.klickLegtAn, true,
      "„gleich anlegen“ soll voreingestellt sein");
    assert.strictEqual(frisch.einstellungen.kalender.jahrestagsartenFrei, false,
      "die feste Jahrestagsliste soll voreingestellt sein");
    assert.strictEqual(frisch.einstellungen.allgemein.wetter, false,
      "Wetter soll erst nach ausdrücklicher Wahl erscheinen");
    assert.strictEqual(frisch.einstellungen.allgemein.wetterDarstellung, "temperature",
      "kompakte Wetterdarstellung soll voreingestellt sein");
    assert.strictEqual(frisch.einstellungen.allgemein.wetterIntervall, 180,
      "Wetter soll voreingestellt alle drei Stunden aktualisieren");
    assert.strictEqual(frisch.einstellungen.allgemein.handbuchHinweisGezeigt, false,
      "der Handbuchhinweis darf bei neuen Daten noch nicht als gezeigt gelten");
  }

  /* ---- Beschriebene Flächen rollen nicht selbst ---- */
  klickeTab("Notizen");
  assert.ok($(".schreibrahmen"), "der rollende Rahmen um das Schreibblatt fehlt");
  assert.strictEqual($(".schreibrahmen").firstElementChild.id, "notiz-text",
    "die Schreibfläche liegt nicht im Rahmen");
  klickeTab("Kalender");
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  assert.ok($(".tb-notizrahmen"), "der Rahmen um das Notizfeld fehlt");
  assert.strictEqual($(".tb-notizrahmen").firstElementChild.id, "tb-notiz",
    "das Notizfeld liegt nicht im Rahmen");
  /* Das Feld wächst mit dem Text, statt selbst zu rollen */
  const notizFeld = $("#tb-notiz");
  notizFeld.value = Array.from({ length: 25 }, (_, i) => "Zeile " + i).join("\n");
  notizFeld.dispatchEvent(new w.Event("input", { bubbles: true }));
  await tick();
  assert.ok(notizFeld.style.height,
    "das Notizfeld wächst nicht mit dem Text");
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  /* ---- Wiederkehrende Termine ---- */
  klickeTab("Kalender");
  $$("#ansicht-umschalter .u-knopf").find((b) => b.dataset.ansicht === "month").click();
  const startTag = T.zustand().kalender.tag;
  T.oeffneTerminBlatt(null, startTag);
  assert.ok($("#tb-wiederholt"), "Schalter für Wiederholung fehlt");
  assert.strictEqual($("#tb-wiederholt").checked, false,
    "voreingestellt ist ein einmaliger Termin");
  assert.strictEqual($("#tb-wiederholung-zeile").style.display, "none",
    "die Wahl erscheint erst, wenn gewünscht");
  setze($("#tb-titel"), "Mülltonne raus");
  setze($("#tb-zeit"), "08:00");
  $("#tb-wiederholt").checked = true;
  $("#tb-wiederholt").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual($("#tb-wiederholung-zeile").style.display, "",
    "die Wahl erscheint nicht");
  assert.deepStrictEqual(
    Array.from($("#tb-wiederholung").options).map((o) => o.value),
    ["daily", "daily-2", "daily-14", "weekly", "weekly-3", "monthly",
      "monthly-weekday", "yearly", "custom"],
    "täglich, wöchentlich, monatlicher Wochentag, jährlich");
  assert.ok($("#tb-wiederholung-hinweis").textContent.includes("jeden"),
    "der Hinweis nennt den Wochentag nicht: " +
    $("#tb-wiederholung-hinweis").textContent);
  $("#tb-fertig").click();
  await tick();

  const reihe = T.daten().termine.find((x) => x.titel === "Mülltonne raus");
  assert.ok(reihe, "der wiederkehrende Termin wurde nicht angelegt");
  assert.strictEqual(reihe.wiederholung.art, "weekly", "Regel nicht gemerkt");

  const monatsRundlauf = T.normalisiere(JSON.parse(JSON.stringify({ termine: [{
    id: "monat-2th", datum: "2024-01-11", titel: "Zweiter Donnerstag",
    wiederholung: { art: "monthly", bis: "", ordinal: 2, wochentag: "TH" }
  }] })));
  assert.deepStrictEqual(monatsRundlauf.termine[0].wiederholung,
    { art: "monthly", bis: "", ordinal: 2, wochentag: "TH" },
  "ordinaler Monatswochentag übersteht Speichern und Neustart nicht");
  const intervalle = T.normalisiere({ termine: [
    { id: "zweitaeglich", datum: "2026-08-01", titel: "Zweitäglich",
      wiederholung: { art: "daily", intervall: 2 } },
    { id: "vierzehn", datum: "2026-08-01", titel: "Vierzehn",
      wiederholung: { art: "daily", intervall: 14 } },
    { id: "dreiwochen", datum: "2026-08-03", titel: "Drei Wochen",
      wiederholung: { art: "weekly", intervall: 3 } },
    { id: "eigene-tage", datum: "2026-08-01", titel: "Eigene Tage",
      wiederholung: { art: "custom", daten: ["2026-09-05", "2026-08-19", "2026-08-19"] } }
  ] }).termine;
  T.daten().termine.push(...intervalle);
  T.planeSpeichern();
  assert.ok(T.termineAm("2026-08-03").some((t) => t.id === "zweitaeglich") &&
    !T.termineAm("2026-08-04").some((t) => t.id === "zweitaeglich") &&
    T.termineAm("2026-08-15").some((t) => t.id === "vierzehn") &&
    T.termineAm("2026-08-24").some((t) => t.id === "dreiwochen") &&
    !T.termineAm("2026-08-17").some((t) => t.id === "dreiwochen") &&
    T.termineAm("2026-08-19").some((t) => t.id === "eigene-tage") &&
    !T.termineAm("2026-08-20").some((t) => t.id === "eigene-tage"),
  "Intervall- oder benutzerdefinierte Terminserie wird falsch expandiert");
  assert.deepStrictEqual(intervalle[3].wiederholung.daten,
    ["2026-08-19", "2026-09-05"], "benutzerdefinierte Tage werden nicht kanonisiert");
  T.daten().termine = T.daten().termine.filter((t) =>
    !["zweitaeglich", "vierzehn", "dreiwochen", "eigene-tage"].includes(t.id));
  T.daten().termine.push(monatsRundlauf.termine[0]);
  T.planeSpeichern();
  assert.ok(T.termineAm("2024-02-08").some((t) => t.id === "monat-2th") &&
    T.termineAm("2024-03-14").some((t) => t.id === "monat-2th") &&
    T.termineAm("2024-04-11").some((t) => t.id === "monat-2th") &&
    !T.termineAm("2024-03-07").some((t) => t.id === "monat-2th"),
  "zweiter Donnerstag wird in Anzeige/Suche falsch expandiert");
  const zweitaegig = T.normalisiere({ termine: [{ id: "zweitaegig",
    datum: "2026-01-13", endDatum: "2026-01-14", zeit: "09:15", endZeit: "10:45",
    titel: "Zweitägig", wiederholung: { art: "monthly", ordinal: 2,
      wochentag: "TU", rruleForm: "byday", bis: "" } }] }).termine[0];
  T.daten().termine.push(zweitaegig);
  T.planeSpeichern();
  const februarFolge = T.termineAm("2026-02-11").find((t) => t.id === "zweitaegig");
  assert.ok(februarFolge && februarFolge.datum === "2026-02-10" &&
    februarFolge.endDatum === "2026-02-11" && februarFolge.zeit === "09:15" &&
    februarFolge.endZeit === "10:45", "zweitägige zeitgebundene Folge verliert Dauer");
  T.daten().termine = T.daten().termine.filter((x) => x.id !== "zweitaegig");
  T.oeffneTerminBlatt(monatsRundlauf.termine[0], "2024-03-14");
  assert.strictEqual($("#tb-wiederholung").value, "monthly-weekday");
  assert.strictEqual($("#tb-monats-ordinal").value, "2");
  assert.strictEqual($("#tb-monats-wochentag").value, "TH");
  assert.ok($("#tb-wiederholung-hinweis").textContent.includes("zweiten Donnerstag"),
    "Monatswochentag wird nicht verständlich angezeigt");
  knopfMit("Abbrechen", $("#termin-schleier")).click();
  T.daten().termine = T.daten().termine.filter((x) => x.id !== "monat-2th");

  /* Er erscheint auch eine Woche später, ohne zweimal gespeichert zu sein */
  const inEinerWoche = new Date(startTag);
  inEinerWoche.setDate(inEinerWoche.getDate() + 7);
  const isoWoche = inEinerWoche.getFullYear() + "-" +
    String(inEinerWoche.getMonth() + 1).padStart(2, "0") + "-" +
    String(inEinerWoche.getDate()).padStart(2, "0");
  const spaeter = T.termineAm(isoWoche);
  assert.ok(spaeter.some((x) => x.titel === "Mülltonne raus"),
    "das nächste Mal fehlt im Kalender");
  assert.strictEqual(
    T.daten().termine.filter((x) => x.titel === "Mülltonne raus").length, 1,
    "es darf nur ein Eintrag gespeichert sein");

  /* Ein errechnetes Mal führt beim Anklicken zum Ursprung */
  const mal = spaeter.find((x) => x.titel === "Mülltonne raus");
  assert.strictEqual(mal.folge, true, "das Mal ist nicht als Folge erkennbar");
  T.oeffneTerminBlatt(mal, isoWoche);
  assert.strictEqual($("#tb-titel").value, "Mülltonne raus");
  assert.strictEqual($("#tb-wiederholt").checked, true,
    "die Regel wird beim Bearbeiten nicht angezeigt");
  assert.ok($(".termin-blatt .einst-warnung"),
    "der Hinweis auf die Reihe fehlt");
  knopfMit("Abbrechen", $("#termin-schleier")).click();

  T.daten().termine = T.daten().termine.filter((x) => x.titel !== "Mülltonne raus");
  T.planeSpeichern();

  /* ---- Seite „Über" mit Lizenz und Kaffeehinweis ---- */
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Über").click();
  const ueberText = $("#einstellungen-inhalt").textContent;
  assert.ok(ueberText.includes("Maik Walter"), "der Autor fehlt");
  assert.ok(ueberText.includes("General Public License"), "die Lizenz fehlt");
  assert.ok(ueberText.includes("Version 3"), "die Lizenzfassung fehlt");
  assert.ok($(".ueber-fassung").textContent.includes("Fassung"),
    "die Programmfassung fehlt");
  assert.ok($(".ueber-fassung").textContent.includes("2.0.13"),
    "die neue Programmfassung fehlt");
  assert.ok($(".ueber-blume"), "die Magnolienblüte fehlt");
  const beschreibung = $(".ueber-beschreibung");
  assert.ok(!beschreibung.querySelector("br"), "die alte Plattformzeile ist noch vorhanden");
  assert.ok(!beschreibung.textContent.includes("Linux") &&
    beschreibung.textContent.endsWith("."), "die Produktbeschreibung ist nicht plattformneutral");

  assert.ok($("#update-automatisch").checked,
    "tägliche Aktualisierungsprüfung ist nicht voreingestellt");
  assert.ok($("#update-pruefen"), "Knopf zur sofortigen Aktualisierungsprüfung fehlt");
  assert.ok($("#update-pruefen").disabled,
    "im Browser muss die Aktualisierungsprüfung gesperrt sein");
  assert.ok($("#handbuch-oeffnen"), "Knopf zum Öffnen des Handbuchs fehlt");
  assert.ok($("#handbuch-oeffnen").disabled,
    "ohne installiertes Handbuch muss der Knopf gesperrt sein");
  assert.ok(!$("#handbuch-aktualisieren"),
    "neben der gemeinsamen Aktualisierungsprüfung ist ein zweiter Prüfknopf sichtbar");
  assert.ok($("#handbuch-stand").textContent.includes("nicht installiert"),
    "der Handbuchstatus nennt die fehlende Installation nicht");
  assert.ok(!T.istNeuereFassung("2.0.1") && !T.istNeuereFassung("2.0.13") &&
    T.istNeuereFassung("2.0.14"),
    "Fassungsvergleich der Oberfläche stimmt nicht");
  assert.ok(T.vergleicheText("Termin 2", "Termin 10") < 0,
    "der regionale Collator sortiert Zahlen weiterhin rein lexikografisch");
  w.App.updateErgebnis({ ok: true, aktuell: false, version: "2.0.14",
    url: "https://gitlab.com/maik3531/mint-forgs/-/raw/main/" +
      "Magnolie-Organitzer/magnolie-organizer_2.0.14_all.deb" });
  assert.ok($("#update-stand").textContent.includes("2.0.14"),
    "gefundene Fassung erscheint nicht unter Über");
  assert.ok($("#update-herunterladen"), "Downloadknopf für neue Fassung fehlt");
  assert.strictEqual(T.daten().einstellungen.update.letzteVersion, "2.0.14",
    "Prüfstand wird nicht gespeichert");
  $("#update-automatisch").checked = false;
  $("#update-automatisch").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.update.automatisch, false,
    "tägliche Prüfung lässt sich nicht abschalten");
  assert.ok(/cmd: "update_pruefen"/.test(js) && /cmd: "update_herunterladen"/.test(js) &&
    /cmd: "update_installieren"/.test(js),
    "Brückenbefehle für Prüfung, sicheren Download oder Installation fehlen");
  assert.ok(/cmd: "handbuch_oeffnen"/.test(js),
    "Brückenbefehl zum Öffnen des Handbuchs fehlt");

  const kaffee = $("#kaffee-anschrift");
  assert.ok(kaffee, "der Hinweis auf einen Kaffee fehlt");
  assert.strictEqual(kaffee.textContent, "maik3531@gmail.com",
    "die Anschrift stimmt nicht");
  assert.strictEqual(kaffee.tagName, "P",
    "die Anschrift soll schlichter Text sein");
  assert.ok(!$("#einstellungen-inhalt a[href^='mailto:']"),
    "die Anschrift darf nicht anklickbar sein");
  assert.ok($(".kaffee-satz").textContent.includes("Kaffee"),
    "der Satz zum Kaffee fehlt");
  T.schliesseEinstellungen();

  /* ---- Personen und Zuweisung von Aufgaben ---- */
  klickeTab("Aufgaben");
  assert.ok($("#aufgaben-personen"), "Knopf „Personen“ fehlt");
  const personenBlatt = T.oeffnePersonenblatt();
  assert.ok($("#personen-schleier"), "Personenblatt erscheint nicht");
  setze($("#person-neu"), "Max");
  $("#person-anlegen").click();
  setze($("#person-neu"), "Erika");
  $("#person-anlegen").click();
  assert.strictEqual(T.daten().personen.length, 2, "zwei Personen erwartet");
  assert.strictEqual(T.daten().personen[0].name, "Max");
  assert.ok($$(".person-zeile").length === 2, "beide stehen in der Liste");
  assert.ok($(".person-zeichen").textContent.length <= 3,
    "das Kürzel ist zu lang");
  personenBlatt.remove();
  T.wechsel("notizen");

  /* Aufgabe einer Person zuweisen */
  klickeTab("Aufgaben");
  assert.ok($("#aufgabe-personen"), "Auswahl der Verantwortlichen fehlt");
  const maxId = T.daten().personen[0].id;
  setze($("#inhalt-rechts fieldset input[type=text]"), "Mülltonne rausstellen");
  const maxHak = $$("#aufgabe-personen input[type=checkbox]").find(
    (h) => h.dataset.person === maxId);
  assert.ok(maxHak, "Ankreuzfeld für Max fehlt");
  maxHak.checked = true;
  maxHak.dispatchEvent(new w.Event("change", { bubbles: true }));
  $("#aufgabe-erinnern").checked = true;
  assert.deepStrictEqual(Array.from($("#aufgabe-erinnerung-vorschlaege").options,
    (o) => o.value), ["1 Tag vorher", "2 Tage vorher", "3 Tage vorher",
      "4 Tage vorher", "5 Tage vorher", "6 Tage vorher", "7 Tage vorher"],
    "die individuellen Aufgabenvorschläge sind unvollständig");
  setze($("#aufgabe-individuelle-erinnerung"), "2 Tage vorher");
  knopfMit("Aufnehmen").click();
  const neueAufgabe = T.daten().aufgaben.find(
    (a) => a.titel === "Mülltonne rausstellen");
  assert.ok(neueAufgabe, "Aufgabe nicht angelegt");
  /* Die Liste stammt aus dem Fenster der Seite – daher über den Inhalt
     vergleichen, nicht über die Bauart. */
  assert.strictEqual(JSON.stringify(neueAufgabe.personen),
    JSON.stringify([maxId]), "Zuweisung nicht gespeichert");
  assert.strictEqual(neueAufgabe.erinnern, true, "Erinnerung nicht gemerkt");
  assert.strictEqual(neueAufgabe.individuelleErinnerungTage, 2,
    "individuelle Aufgabenerinnerung nicht gemerkt");
  assert.ok($("#inhalt-links .person-leiste"),
    "die Person erscheint nicht in der Liste");

  /* Auswahl nach Person */
  assert.ok($("#aufgaben-filter"), "Auswahlleiste fehlt");
  const erikaId = T.daten().personen[1].id;
  $("#filter-person").value = erikaId;
  $("#filter-person").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok(!$("#inhalt-links").textContent.includes("Mülltonne"),
    "die Auswahl nach Person wirkt nicht");
  $("#filter-person").value = maxId;
  $("#filter-person").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.ok($("#inhalt-links").textContent.includes("Mülltonne"),
    "die Aufgabe von Max fehlt");

  /* Der Druck übernimmt die Auswahl samt Person im Titel */
  $("#knopf-drucken").click();
  assert.ok($(".druck-blatt h2").textContent.includes("Max"),
    "der Ausdruck nennt die Person nicht: " + $(".druck-blatt h2").textContent);
  assert.strictEqual($$(".druck-zeile").length, 1,
    "es darf nur die ausgewählte Aufgabe zur Wahl stehen");
  knopfMit("Abbrechen", $("#druck-schleier")).click();
  $("#filter-weg").click();

  /* ---- Termin mit Aufgabe verknüpfen ---- */
  klickeTab("Kalender");
  const besorgungFrueh = { id: "besorgung-frueh", titel: "Besorgungen",
    faellig: "2031-02-03", prio: 2, erledigt: false,
    notiz: "Im Supermarkt Getränke holen", personen: [], erinnern: false };
  const besorgungSpaet = { id: "besorgung-spaet", titel: "Besorgungen",
    faellig: "2031-02-08", prio: 2, erledigt: false,
    notiz: "Medikamente aus der Apotheke abholen", personen: [], erinnern: false };
  T.daten().aufgaben.push(besorgungFrueh, besorgungSpaet);
  for (let i = 0; i < 55; i++) {
    T.daten().aufgaben.push({ id: "routine-" + i, titel: "Routineaufgabe " + (i + 1),
      faellig: "2032-03-" + String(i % 28 + 1).padStart(2, "0"), prio: 2,
      erledigt: false, notiz: "Prüfbestand Nummer " + (i + 1), personen: [],
      erinnern: false });
  }
  T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
  assert.ok($("#tb-aufgaben"), "Bereich für Aufgaben im Terminblatt fehlt");
  assert.strictEqual($("#tb-aufgabe-waehlen").tagName, "INPUT",
    "vorhandene Aufgaben werden noch in einer langen Auswahlliste gezeigt");
  setze($("#tb-aufgabe-waehlen"), "Besorgungen");
  const besorgungsTreffer = $$(".tb-aufgaben-treffer");
  assert.ok(besorgungsTreffer.some((b) => b.textContent.includes("03.02.2031") &&
    b.textContent.includes("Supermarkt")),
  "die erste gleichnamige Aufgabe ist nicht anhand Datum und Notiz erkennbar");
  assert.ok(besorgungsTreffer.some((b) => b.textContent.includes("08.02.2031") &&
    b.textContent.includes("Apotheke")),
  "die zweite gleichnamige Aufgabe ist nicht anhand Datum und Notiz erkennbar");
  besorgungsTreffer.find((b) => b.textContent.includes("Apotheke")).click();
  assert.ok($(".tb-aufgabenliste").textContent.includes("08.02.2031") &&
    $(".tb-aufgabenliste").textContent.includes("Apotheke"),
  "die verknüpfte gleichnamige Aufgabe ist anschließend wieder uneindeutig");
  setze($("#tb-aufgabe-waehlen"), "Routineaufgabe");
  assert.strictEqual($$(".tb-aufgaben-treffer").length, 12,
    "eine große Treffermenge wird nicht begrenzt");
  assert.ok($(".tb-aufgaben-trefferstand").textContent.includes("12 von 55"),
    "bei großen Beständen fehlt der Hinweis zum genaueren Suchen");
  setze($("#tb-aufgabe-neu"), "Unterlagen mitnehmen");
  $("#tb-aufgabe-erinnern").checked = true;
  $("#tb-aufgabe-anlegen").click();
  const dazu = T.daten().aufgaben.find((a) => a.titel === "Unterlagen mitnehmen");
  assert.ok(dazu, "die Aufgabe wurde nicht angelegt");
  assert.strictEqual(dazu.erinnern, true, "Erinnerung nicht übernommen");
  assert.ok($(".tb-aufgabenzeile"), "die Aufgabe erscheint nicht im Blatt");
  setze($("#tb-titel"), "Behördengang");
  $("#tb-fertig").click();
  await tick();
  const mitAufgabe = T.daten().termine.find((x) => x.titel === "Behördengang");
  assert.ok(mitAufgabe.aufgaben.includes(dazu.id),
    "die Verknüpfung wurde nicht gespeichert");
  assert.ok(mitAufgabe.aufgaben.includes(besorgungSpaet.id),
    "die ausgewählte gleichnamige Aufgabe wurde nicht verknüpft");

  /* ---- Linienabstand und Zeilenhöhe stammen aus einer Quelle ----
     Geprüft wird am Stil selbst, weil jsdom keine Seitenmaße rechnet. */
  const stilText = fs.readFileSync(path.join(WEB, "stil.css"), "utf8");
  const blattRegel = stilText.slice(stilText.indexOf("#notiz-text,"));
  assert.ok(/line-height:\s*1\.87/.test(blattRegel) &&
    /--zeilenhoehe:\s*1\.87em/.test(blattRegel) &&
    /@supports\s*\(height:\s*1lh\)/.test(stilText) &&
    /--zeilenhoehe:\s*1lh/.test(stilText),
    "die Linien folgen nicht der tatsächlich skalierten Zeilenhöhe");
  assert.ok(/background-size:\s*100%\s*var\(--zeilenhoehe\)/.test(blattRegel),
    "der Linienabstand kommt nicht aus derselben Größe");
  assert.ok(/--linien-stelle:\s*1\.4212em/.test(blattRegel) &&
    /--linien-stelle:\s*0\.76lh/.test(stilText) &&
    !/body\s*\{\s*--zeilenhoehe/.test(stilText) &&
    /function notizlinienGrundlinie\(feld\)/.test(js) &&
    /\[\$\("#notiz-text"\),\s*\$\("#tb-notiz"\)\]/.test(js) &&
    /const periode = zweite - erste/.test(js) &&
    /setProperty\("--zeilenhoehe",\s*metrik\.zeilenhoehe \+ "px"\)/.test(js),
  "Linienperiode und Grundlinie folgen nicht der effektiven Textfeldschrift");
  assert.ok(/\.planer-druck-kalender \.pk-anlass\s*\{[\s\S]{0,100}font-size:\s*5\.5px/
    .test(stilText) && T.planerDruckSeite(T.planerKalenderModell(2026))
      .includes(".anlass{display:block;font-size:4.8pt"),
  "Feiertags- und Ferienbeschriftungen im Jahresdruck sind nicht verkleinert");
  assert.ok(/body\[data-linien="aus"\][\s\S]{0,120}background-image:\s*none/
    .test(stilText), "ohne Linien fehlt die Regel zum Abschalten");
  assert.ok(/\.baum-kennzeile\s*\{[\s\S]{0,180}grid-template-columns:\s*minmax\(122px,\s*max-content\)\s*minmax\(0,\s*1fr\)/
    .test(stilText), "Fingerabdruck und Beschriftung sind nicht getrennt");

  /* ---- Linien abschaltbar, Mausradrichtung ---- */
  T.oeffneEinstellungen();
  $$(".einst-reiter-knopf").find((b) => b.textContent === "Allgemein").click();
  assert.ok($("#allgemein-linien"), "Schalter für die Linien fehlt");
  assert.strictEqual($("#allgemein-linien").checked, true,
    "liniert ist die Voreinstellung");
  $("#allgemein-linien").checked = false;
  $("#allgemein-linien").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(d.body.getAttribute("data-linien"), "aus",
    "das Papier wird nicht glatt");
  $("#allgemein-linien").checked = true;
  $("#allgemein-linien").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.deepStrictEqual(
    Array.from($("#allgemein-rad").options).map((o) => o.value),
    ["up-earlier", "up-later"], "zwei Drehrichtungen erwartet");
  $("#allgemein-rad").value = "up-later";
  $("#allgemein-rad").dispatchEvent(new w.Event("change", { bubbles: true }));
  assert.strictEqual(T.daten().einstellungen.schrift.radRichtung, "up-later",
    "Drehrichtung nicht gemerkt");
  T.schliesseEinstellungen();

  /* ---- Magnolienbaum: Internetweg und bestätigte Angebote ---- */
  const baumNachrichten = [];
  const baumDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://magnolienbaum.test/",
    pretendToBeVisual: true
  });
  baumDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => baumNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(baumDom.window);
  await tick();
  const bw = baumDom.window;
  const bd = bw.document;
  const baumDaten = bw.OrganizerTest.leereDaten();
  baumDaten.kontakte.push({ id: "sozial-1", uid: "", nachname: "Beispiel",
    vorname: "Anna", firma: "", telefone: [
      { wert: "+49 170 1234567", typen: ["CELL"] },
      { wert: "0203 765432", typen: ["VOICE"] }], anschriften: [], emailEintraege: [],
    sozialeMedien: [{ dienst: "whatsapp", wert: "+49 170 1234567",
      aktionArt: "programm", aktionZiel: "zapzap {ziel}" },
      { dienst: "mastodon", wert: "@anna@beispiel.social" },
      { dienst: "teams", wert: "anna@beispiel.de" },
      { dienst: "snapchat", wert: "anna" }, { dienst: "tiktok", wert: "anna" },
      { dienst: "youtube", wert: "anna" }, { dienst: "telegram", wert: "anna" },
      { dienst: "x", wert: "anna" }, { dienst: "linkedin", wert: "anna" },
      { dienst: "reddit", wert: "anna" },
      { dienst: "phone", wert: "+49 170 1234567" },
      { dienst: "custom", wert: "https://irc.example/anna", symbol: "twitch" }],
    notiz: "Lokal", foto: "data:image/png;base64,iVBORw0KGgo=", geaendert: Date.now(),
    sync: false, baumKontakt: null });
  baumDaten.notizen.push({ id: "gemeinsam-1", titel: "Gemeinsam", text: "Text",
    html: "<p>Text</p>", anhaenge: [], notizbuchId: "lose-notizen",
    geaendert: "2026-08-02", baumFreigabe: { id: "a:n1", partner: ["b"] },
    baumGeaendert: 12345, baumVersion: 4, baumQuelle: "a" });
  bw.App.init({ daten: baumDaten, neu: false, datenPfad: "",
    trayVerfuegbar: true, trayEinstellungen: { aktiv: true,
      minimierenInTray: true, schliessenInTray: true,
      startMinimiert: false, autostart: false, zaehler: true,
      oeffnen: "zentriert" } });
  bw.OrganizerTest.oeffneEinstellungen();
  assert.ok(bd.querySelector("#allgemein-tray-aktiv").checked,
    "das aktivierte Tray-Applet wird in den Einstellungen angezeigt");
  assert.ok(bd.querySelector("#allgemein-tray-zaehler").checked &&
    !bd.querySelector("#allgemein-gruppe-tray").open,
  "Tray-Zähler oder geschlossene Tray-Gruppe wird nicht übernommen");
  assert.notStrictEqual(bd.querySelector(".allgemein-tray-felder").style.display, "none",
    "Tray-Unteroptionen sind bei aktiviertem Applet sichtbar");
  bd.querySelector("#allgemein-tray-aktiv").checked = false;
  bd.querySelector("#allgemein-tray-aktiv")
    .dispatchEvent(new bw.Event("change", { bubbles: true }));
  assert.strictEqual(bd.querySelector(".allgemein-tray-felder").style.display, "none",
    "Tray-Unteroptionen verschwinden nach dem Abschalten");
  assert.ok(baumNachrichten.some((n) => n.cmd === "tray_einstellungen" &&
    n.einstellungen.aktiv === false),
  "geänderte Tray-Einstellungen erreichen den Programmkern");
  bd.querySelector("#allgemein-tray-aktiv").checked = true;
  bd.querySelector("#allgemein-tray-aktiv")
    .dispatchEvent(new bw.Event("change", { bubbles: true }));
  bw.OrganizerTest.schliesseEinstellungen();
  assert.strictEqual(bw.OrganizerTest.daten().notizen[0].baumFreigabe.id, "a:n1",
    "die Freigabe einer gemeinsamen Notiz übersteht das erneute Öffnen");
  assert.strictEqual(bw.OrganizerTest.daten().notizen[0].baumVersion, 4,
    "der Abgleichstand einer gemeinsamen Notiz übersteht das erneute Öffnen");
  assert.strictEqual(
    bw.OrganizerTest.daten().notizen[0].baumFreigabe.anhangPartner.length, 0,
    "ältere gemeinsame Notizen erlauben Anhänge nicht stillschweigend");
  bw.OrganizerTest.zustand().notizen.auswahlId = "gemeinsam-1";
  bw.OrganizerTest.wechsel("notizen");
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", port: 8737, partner: [{ kennung: "b", name: "Werkstatt",
      bestaetigt: true }], post: 0, postOffen: 0, eingang: [] });
  assert.ok(bd.querySelector(".baum-freigabe > .baum-notiz-stand") &&
    bd.querySelector(".baum-notiz-stand").textContent ===
      "Änderungen werden automatisch übernommen" &&
    /\.baum-notiz-stand\s*\{[^}]*position:\s*static;[^}]*white-space:\s*normal;/s.test(css),
  "der Abgleichstatus bricht nicht innerhalb der linken Freigabegruppe um");
  bw.App.baumStand({ moeglich: true, an: false, laeuft: false, name: "Küche",
    kennung: "a", port: 8737, partner: [], post: 0, postOffen: 0, eingang: [] });
  assert.ok(!bd.querySelector(".baum-notiz-stand"),
    "eine gemeinsame Notiz behauptet bei abgeschaltetem Magnolienbaum keinen Abgleich");
  bw.OrganizerTest.wechsel("kalender");
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", fingerabdruck: "AAAA-BBBB-CCCC-DDDD", port: 8737,
    partner: [{ kennung: "b", name: "Werkstatt", bestaetigt: true,
      fingerabdruck: "1111-2222-3333-4444" }], post: 0, postOffen: 0,
    eingang: [{ id: "angebot-1", von: "b", vonName: "Werkstatt", art: "termin",
      inhalt: { art: "termin", datum: "2026-08-10", titel: "Teamtreffen" } }]
  });
  bw.OrganizerTest.oeffneEinstellungen();
  Array.from(bd.querySelectorAll(".einst-reiter-knopf"))
    .find((b) => b.textContent === "Magnolienbaum").click();
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741, peers: [],
    bluetooth: { available: false, devices: [] }, kdeconnect: { available: false,
      paired: 1, listening: true, listen_port: 1739, reason: "no_device" } });
  const telefonAbschnitt = bd.querySelector(".telefon-karte");
  const kdeAbschnitt = bd.querySelector(".telefon-kde-karte");
  assert.ok(telefonAbschnitt && kdeAbschnitt &&
    telefonAbschnitt.compareDocumentPosition(kdeAbschnitt) & bw.Node.DOCUMENT_POSITION_FOLLOWING,
  "Magnolie-Telefonverbindung und KDE-SMS sind nicht getrennt oder falsch geordnet");
  assert.ok(telefonAbschnitt.textContent.includes("8741") &&
    !telefonAbschnitt.textContent.includes("1739") && kdeAbschnitt.textContent.includes("1739") &&
    !kdeAbschnitt.textContent.includes("8741"),
  "Listenerports 8741 und KDE 1716-1764 sind den falschen Abschnitten zugeordnet");
  const reconnect = Array.from(kdeAbschnitt.querySelectorAll("button"))
    .find((button) => button.textContent === "Erneut verbinden");
  assert.ok(reconnect && !Array.from(kdeAbschnitt.querySelectorAll("button"))
    .some((button) => button.textContent.includes("koppeln")),
  "gekoppeltes offline KDE-Telefon zeigt nicht ausschließlich Erneut verbinden");
  reconnect.click();
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_reconnect"),
    "KDE erneut verbinden löst keine sichere aktive Discovery aus");
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741, peers: [],
    kdeconnect: { available: false, paired: 0, legacy_pinned_count: 1,
      locally_pinned_count: 1, transport_reachable: true, device_count: 0,
      listening: true, listen_port: 1716, unpaired_candidate_count: 1,
      unpaired_candidate_id: "kde-galaxy", unpaired_candidate_name: "Galaxy S24",
      unpaired_candidate_reachable: true } });
  const reachableKde = bd.querySelector(".telefon-kde-karte");
  const complete = Array.from(reachableKde.querySelectorAll("button"))
    .find((button) => ["Kopplung abschließen", "Complete pairing"].includes(button.textContent));
  assert.ok(complete && /erreichbar|reachable/i.test(reachableKde.textContent) &&
    !reachableKde.textContent.toLowerCase().includes("online"),
  "nur TLS-erreichbares KDE-Telefon wird nicht klar als unbestätigt angeboten");
  complete.click();
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_pairing_complete" &&
    nachricht.kennung === "kde-galaxy"),
  "Kopplungsabschluss verwendet die bestehende verschlüsselte Verbindung nicht");
  const stableCandidateButton = complete;
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741, peers: [],
    kdeconnect: { available: false, paired: 0, transport_reachable: false,
      listening: true, listen_port: 1716, unpaired_candidate_count: 1,
      unpaired_candidate_id: "kde-galaxy", unpaired_candidate_name: "Galaxy S24",
      unpaired_candidate_reachable: false, unpaired_candidate_age_seconds: 31 } });
  const cachedKde = bd.querySelector(".telefon-kde-karte");
  const cachedPair = Array.from(cachedKde.querySelectorAll("button"))
    .find((button) => ["Kopplung abschließen", "Complete pairing"].includes(button.textContent));
  assert.ok(cachedPair && !cachedPair.disabled && /zuletzt gefunden|last found/i.test(cachedKde.textContent) &&
    !cachedKde.textContent.toLowerCase().includes("online"),
  "gecachter KDE-Kandidat verliert bei Linkabbruch Button oder klare Statusangabe");
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741,
    peers: [{ display_name: "SM-S921B" }], kdeconnect: { available: false,
      paired: 1, peer_id: "kde-galaxy", peer_name: "Galaxy S24", listening: true,
      listen_port: 1716, reason: "no_device", unpaired_candidate_count: 1,
      unpaired_candidate_id: "kde-galaxy-new", unpaired_candidate_name: "Galaxy S24",
      replacement_peer_id: "kde-galaxy" } });
  const staleKdeAbschnitt = bd.querySelector(".telefon-kde-karte");
  const renew = Array.from(staleKdeAbschnitt.querySelectorAll("button"))
    .find((button) => button.textContent === "Kopplung erneuern");
  assert.ok(renew && staleKdeAbschnitt.textContent.includes("Vertrauen") &&
    staleKdeAbschnitt.textContent.includes("Magnolie Notes"),
  "stale KDE-Kopplung bietet keine klar getrennte, sichere Erneuerung an");
  renew.click();
  const confirmRenew = Array.from(bd.querySelectorAll("button"))
    .find((button) => button.textContent === "Kopplung erneuern");
  confirmRenew.click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_pairing_start" &&
    nachricht.kennung === "kde-galaxy-new" && nachricht.erneuern === true),
  "KDE-Pin-Erneuerung startet nicht erst nach expliziter Sicherheitsabfrage");
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741, peers: [],
    kdeconnect: { available: true, paired: 1, peer_id: "b".repeat(32),
      peer_name: "Galaxy S24", device_id: "b".repeat(32), device_count: 1,
      listening: true, listen_port: 1716, reason: "" } });
  const empfangAbschnitt = bd.querySelector(".telefon-kde-karte");
  const empfangGruppen = empfangAbschnitt.querySelectorAll(".kde-empfang-option");
  assert.strictEqual(empfangGruppen.length, 2,
    "KDE-Connect-Bereich enthält nicht getrennte Datei- und Zwischenablageoptionen");
  const dateiEmpfang = empfangGruppen[0].querySelectorAll("input");
  assert.ok(dateiEmpfang.length === 1 && !dateiEmpfang[0].checked &&
    !empfangGruppen[0].textContent.includes("automatisch"),
    "KDE-Dateiempfang bietet weiterhin automatische Annahme an");
  dateiEmpfang[0].checked = true;
  dateiEmpfang[0].dispatchEvent(new bw.Event("change", { bubbles: true }));
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_receive_settings" &&
    nachricht.deviceId === "b".repeat(32) && nachricht.files === true &&
    !Object.prototype.hasOwnProperty.call(nachricht, "filesAutomatic")),
  "aktivierter KDE-Dateiempfang erreicht den Programmkern nicht im Bestätigungsmodus");
  const ordnerAuswahl = empfangAbschnitt.querySelector(".kde-empfangsordner");
  assert.ok(ordnerAuswahl && !ordnerAuswahl.querySelector("button").disabled,
    "die KDE-Empfangsordnerwahl wird für aktivierten Dateiempfang nicht angeboten");
  ordnerAuswahl.querySelector("button").click();
  assert.ok(baumNachrichten.some((nachricht) =>
    nachricht.cmd === "kde_empfangsordner_waehlen"),
  "die KDE-Empfangsordnerwahl erreicht den Programmkern nicht");
  const kdeSeite = bd.querySelector(".einst-seite");
  const kdeFeld = bd.querySelector("#kde-empfangsordner");
  kdeSeite.scrollTop = 210;
  bw.App.kdeEmpfangsordnerGewaehlt({ pfad: "/home/test/KDE-Dateien" });
  assert.strictEqual(bd.querySelector(".einst-seite"), kdeSeite,
    "die KDE-Ordnerwahl baut die Einstellungsseite unnötig neu");
  assert.strictEqual(bd.querySelector("#kde-empfangsordner"), kdeFeld,
    "die KDE-Ordnerwahl ersetzt das schreibgeschützte Pfadfeld");
  assert.strictEqual(bd.querySelector("#kde-empfangsordner").value,
    "/home/test/KDE-Dateien", "der gewählte KDE-Empfangsordner wird nicht angezeigt");
  assert.strictEqual(bd.querySelector(".einst-seite").scrollTop, 210,
    "die KDE-Ordnerwahl setzt die Rollposition zurück");
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_receive_settings" &&
    nachricht.directory === "/home/test/KDE-Dateien"),
  "der gewählte KDE-Empfangsordner wird nicht angewendet");
  const zielBeiAnnahme = bd.querySelector("#kde-empfang-ordner-bei-annahme");
  zielBeiAnnahme.click();
  assert.ok(baumNachrichten.filter((nachricht) =>
    nachricht.cmd === "kde_receive_settings").at(-1).chooseDirectory === true &&
    Array.from(ordnerAuswahl.querySelectorAll("button")).every((button) => button.disabled),
  "Speicherortwahl je angenommener KDE-Datei wird nicht gespeichert oder sperrt den Festordner nicht");
  bw.App.kdeEmpfangAngebot({ id: "f".repeat(32), device_id: "b".repeat(32),
    name: "Dokument.pdf", size: 2048 });
  bd.querySelector("#dialog-ja").click();
  await Promise.resolve();
  assert.ok(baumNachrichten.some((nachricht) =>
    nachricht.cmd === "kde_receive_ziel_waehlen" && nachricht.id === "f".repeat(32)),
  "angenommene KDE-Datei öffnet nicht die einmalige Speicherortwahl");
  bw.OrganizerTest.daten().einstellungen.sync.kdeEmpfang.dateien = false;
  bw.OrganizerTest.daten().einstellungen.sync.kdeEmpfang.zwischenablage = false;
  bw.App.kdeEmpfangsordnerGewaehlt({ pfad: "/home/test/KDE-Aus" });
  assert.strictEqual(baumNachrichten.filter((nachricht) =>
    nachricht.cmd === "kde_receive_settings").at(-1).deviceId, "",
  "deaktivierter KDE-Empfang behält eine veraltete Gerätebindung");
  bw.App.kdeEmpfangAngebot({ id: "a".repeat(32), device_id: "b".repeat(32),
    text: "Text vom Telefon" });
  assert.ok(!bd.querySelector("#dialog-schleier").classList.contains("verborgen") &&
    bd.querySelector("#dialog-hinweis").textContent === "Text vom Telefon",
  "KDE-Zwischenablagetext wird nicht vor dem Kopieren sichtbar bestätigt");
  bd.querySelector("#dialog-ja").click();
  await Promise.resolve();
  assert.ok(baumNachrichten.some((nachricht) => nachricht.cmd === "kde_receive_decide" &&
    nachricht.id === "a".repeat(32) && nachricht.accept === true),
  "bestätigter KDE-Empfang sendet keine gebundene Annahmeentscheidung");
  bw.OrganizerTest.daten().einstellungen.sync.kdeEmpfang.dateien = true;
  bw.OrganizerTest.daten().einstellungen.sync.kdeEmpfang.ordner = "/home/test/KDE-Aus";
  bw.App.telefonStand({ enabled: true, listening: true, port: 8741, peers: [],
    bluetooth: { available: false, devices: [] }, kdeconnect: { available: false,
      paired: 0, listening: false, listen_port: null, reason: "udp_port_unavailable" } });
  const neuerKdeAbschnitt = bd.querySelector(".telefon-kde-karte");
  assert.ok(Array.from(neuerKdeAbschnitt.querySelectorAll("button"))
    .some((button) => button.textContent === "KDE Connect-Telefon koppeln") &&
    neuerKdeAbschnitt.textContent.includes("UDP-Port 1716"),
  "ungekoppeltes KDE-Telefon oder lokalisierter Dauerlistenerfehler fehlt");
  const gesperrteOrdnerKnoepfe = neuerKdeAbschnitt.querySelectorAll(".kde-empfangsordner button");
  assert.ok(gesperrteOrdnerKnoepfe.length === 2 &&
    Array.from(gesperrteOrdnerKnoepfe).every((button) => button.disabled),
  "KDE-Ordnerknöpfe bleiben ohne empfangsbereites Gegengerät aktiv");
  const nachrichtenVorOrdnerKlick = baumNachrichten.length;
  gesperrteOrdnerKnoepfe.forEach((button) => button.click());
  assert.strictEqual(baumNachrichten.length, nachrichtenVorOrdnerKlick,
    "gesperrte KDE-Ordnerknöpfe senden weiterhin Befehle");
  const baumAbschnitt = Array.from(bd.querySelectorAll(".einst-abschnitt"))
    .find((abschnitt) => abschnitt.querySelector("h3")?.textContent === "Magnolienbaum");
  assert.ok(baumAbschnitt && !baumAbschnitt.textContent.includes("KDE") &&
    !baumAbschnitt.querySelector('[class*="kde"]'),
  "Magnolienbaum nennt KDE weiterhin als Verbindungsmöglichkeit");
  assert.ok(bd.querySelector("#baum-internet"), "der Internetweg fehlt");
  assert.ok(bd.querySelector("#baum-paarungsdatei-erzeugen") &&
    bd.querySelector("#baum-paarungsqr-erzeugen") &&
    bd.querySelector("#baum-paarungsdatei-importieren"),
  "Datei- und QR-Wege der einmaligen Paarung fehlen");
  bd.querySelector("#baum-paarungsdatei-adresse").value = "2001:db8::10";
  bd.querySelector("#baum-paarungsdatei-erzeugen").click();
  bd.querySelector("#baum-paarungsqr-erzeugen").click();
  bd.querySelector("#baum-paarungsdatei-importieren").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_paarungsdatei_erzeugen" &&
    n.adresse === "2001:db8::10") && baumNachrichten.some(
      (n) => n.cmd === "baum_paarungsqr_erzeugen" && n.adresse === "2001:db8::10") &&
    baumNachrichten.some(
      (n) => n.cmd === "baum_paarungsdatei_importieren"),
  "Paarungsdateien und QR bleiben vollständig im nativen Programmkern");
  bw.App.baumPaarungsdatei({ ok: true, art: "qr",
    bild: "data:image/svg+xml;base64,PHN2Zy8+", gueltigBis: 123 });
  assert.equal(bd.querySelector(".baum-paarungsqr img")?.getAttribute("src"),
    "data:image/svg+xml;base64,PHN2Zy8+");
  assert.ok(!bd.querySelector(".baum-paarungsqr").textContent.includes("magnolie-pair:"),
    "der geheime Paarungslink wird nicht zusätzlich als Text offengelegt");
  assert.ok(Array.from(bd.querySelectorAll(".baum-angebot"))
    .some((x) => x.textContent.includes("Teamtreffen")),
  "ein angebotener Termin wartet sichtbar auf Bestätigung");
  bd.querySelector("#baum-internet").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_internet_adresse"),
    "die öffentliche IP wird erst auf ausdrücklichen Klick angefordert");
  bw.App.baumInternet({ ok: true, adresse: "2001:4860:4860::8888", fehler: "" });
  assert.ok(bd.querySelector("#einstellungen-inhalt").textContent.includes(
    "[2001:4860:4860::8888]:8737"),
  "die öffentliche IPv6-Adresse und der Port werden eindeutig angezeigt");
  bd.querySelector("#baum-internet-adresse").value = "2001:db8::20";
  bd.querySelector("#baum-internet-fingerabdruck").value = "1111-2222-3333-4444";
  Array.from(bd.querySelectorAll("button"))
    .find((b) => b.textContent === "Sichere Anfrage senden").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_paaren" &&
    n.adresse === "2001:db8::20" && n.fingerabdruck === "1111-2222-3333-4444"),
  "Internet-IP und erwarteter Fingerabdruck erreichen den Programmkern");
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  assert.ok(bw.OrganizerTest.daten().termine.some((t) => t.titel === "Teamtreffen"),
    "ein bestätigter Termin wird übernommen");
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_eingang_geleert" &&
    n.ids.includes("angebot-1")), "das bearbeitete Angebot wird quittiert");

  const bildDaten = "data:image/png;base64,iVBORw0KGgo=";
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", fingerabdruck: "AAAA-BBBB-CCCC-DDDD", port: 8737,
    partner: [{ kennung: "b", name: "Werkstatt", bestaetigt: true,
      fingerabdruck: "1111-2222-3333-4444" }], post: 0, postOffen: 0,
    eingang: [{ id: "notiz-angebot", von: "b", vonName: "Werkstatt", art: "notiz",
      inhalt: { art: "notiz", freigabeId: "b:n2", titel: "Bilderliste",
        text: "Mit Bild", html: "<p>Mit Bild</p>", version: 1, quelle: "b",
        anhaenge: [{ id: "bild-1", name: "Plan.png", art: "bild",
          daten: bildDaten }] } }]
  });
  assert.ok(bd.querySelector("#zettel").textContent.includes("Magnolienbaum-Anfrage"),
    "eine neue Anfrage wird im geöffneten Organizer gemeldet");
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen und merken").click();
  assert.strictEqual(bd.querySelector("#dialog-ja").textContent,
    "Übernehmen und merken", "die dauerhafte Zustimmung ist eindeutig benannt");
  bd.querySelector("#dialog-ja").click();
  await tick();
  const gemeinsameNotiz = bw.OrganizerTest.daten().notizen
    .find((n) => n.baumFreigabe && n.baumFreigabe.id === "b:n2");
  assert.strictEqual(gemeinsameNotiz.anhaenge[0].name, "Plan.png",
    "ein ausdrücklich angenommener Notizanhang wird übernommen");
  assert.strictEqual(gemeinsameNotiz.baumFreigabe.anhangPartner.join(","), "b",
    "die Anhangzustimmung wird nur für diese Notiz und diesen Partner gemerkt");
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", port: 8737, partner: [{ kennung: "b", name: "Werkstatt",
      bestaetigt: true }], post: 0, postOffen: 0,
    eingang: [{ id: "notiz-sync", von: "b", vonName: "Werkstatt",
      art: "notiz_sync", inhalt: { art: "notiz_sync", freigabeId: "b:n2",
        titel: "Bilderliste neu", text: "Ohne Bild", html: "<p>Ohne Bild</p>",
        version: 2, quelle: "b", anhaenge: [] } }]
  });
  assert.strictEqual(gemeinsameNotiz.titel, "Bilderliste neu",
    "spätere Änderungen einer gemerkten gemeinsamen Notiz kommen automatisch an");
  assert.strictEqual(gemeinsameNotiz.anhaenge.length, 0,
    "auch das Entfernen eines Anhangs wird automatisch übernommen");

  const syncVersion = gemeinsameNotiz.baumVersion;
  bw.OrganizerTest.daten().notizen.push({ id: "lokal-sync", titel: "Lokale Notiz",
    text: "Bleibt stabil", html: "<p>Bleibt stabil</p>", anhaenge: [],
    notizbuchId: "lose-notizen", geaendert: "2026-08-03", baumFreigabe: null,
    baumGeaendert: 0, baumVersion: 0, baumQuelle: "" });
  bw.OrganizerTest.daten().aufgaben.push(
    { id: "eigene-aufgabe", titel: "Eigene Aufgabe", notiz: "", faellig: "",
      prio: 2, erledigt: false, erinnern: false, geaendert: 100, herkunft: "a" },
    { id: "fremde-aufgabe", titel: "Fremde Aufgabe", notiz: "", faellig: "",
      prio: 2, erledigt: false, erinnern: false, geaendert: 100, herkunft: "x",
      fremdId: "x:1" });
  const vorVertrauensSync = baumNachrichten.length;
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", port: 8737, partner: [{ kennung: "b", name: "Werkstatt",
      bestaetigt: true, vertraut: true, kontakte: false,
      fernAdresse: "vpn.example", fernPort: 9443,
      fingerabdruck: "1111-2222-3333-4444" }], post: 0, postOffen: 0,
    eingang: [
      { id: "auto-aufgabe", von: "b", vonName: "Werkstatt", art: "aufgabe",
        inhalt: { art: "aufgabe", id: "b:a1", titel: "Automatisch", herkunft: "b" } },
      { id: "auto-notiz", von: "b", vonName: "Werkstatt", art: "notiz",
        inhalt: { art: "notiz", freigabeId: "b:auto", titel: "Auto-Notiz",
          text: "Vertraut", html: "<p>Vertraut</p>", version: 1, quelle: "b" } },
      { id: "sync-anfrage", von: "b", vonName: "Werkstatt", art: "sync_anfrage",
        inhalt: { art: "sync_anfrage" } },
      { id: "unbekannt", von: "b", vonName: "Werkstatt", art: "spaeter",
        inhalt: { art: "spaeter" } }
    ] });
  assert.ok(bw.OrganizerTest.daten().aufgaben.some((a) => a.titel === "Automatisch") &&
    bw.OrganizerTest.daten().notizen.some((n) => n.titel === "Auto-Notiz"),
  "vertraute bestätigte Partner werden für erste Aufgaben und Notizen automatisch angenommen");
  const vertrauensSync = baumNachrichten.slice(vorVertrauensSync);
  assert.ok(vertrauensSync.some((n) => n.cmd === "baum_delegieren" &&
    n.aufgabe.id === "eigene-aufgabe") && !vertrauensSync.some((n) =>
      n.cmd === "baum_delegieren" && n.aufgabe.id === "fremde-aufgabe"),
  "eine Sync-Anfrage sendet nur eigene Aufgaben mit stabiler ID");
  assert.ok(vertrauensSync.some((n) => n.cmd === "baum_teilen" &&
    n.art === "notiz" && n.inhalt.freigabeId === "a:lokal-sync") &&
    !vertrauensSync.some((n) => n.cmd === "baum_teilen" && n.art === "sync_anfrage"),
  "eine eingehende Sync-Anfrage teilt lokale Notizen, aber erzeugt keine Antwortschleife");
  assert.ok(vertrauensSync.some((n) => n.cmd === "baum_eingang_geleert" &&
    n.ids.includes("sync-anfrage")) && !vertrauensSync.some((n) =>
      n.cmd === "baum_eingang_geleert" && n.ids.includes("unbekannt")),
  "verarbeitete Sync-Anfragen werden quittiert, unbekannte Inhalte nicht autoakzeptiert");
  assert.strictEqual(gemeinsameNotiz.baumVersion, syncVersion,
    "Vollabgleich erhöht die Version einer schon geteilten Notiz nicht künstlich");

  const fernAdresseFeld = bd.querySelector('[data-baum-fern-adresse="b"]');
  const fernPortFeld = bd.querySelector('[data-baum-fern-port="b"]');
  assert.ok(bd.querySelector('[data-baum-vertraut="b"]').checked &&
    !bd.querySelector('[data-baum-kontakte="b"]').checked &&
    !bd.querySelector('[data-baum-kontakt-loeschen="b"]').checked &&
    fernAdresseFeld.value === "vpn.example" && fernPortFeld.value === "9443",
  "Vertrauen und fernes Direktziel werden je bestätigtem Partner angezeigt");
  assert.ok(!baumNachrichten.some((n) => n.art === "kontakt_sync"),
    "Kontaktabgleich startet nicht automatisch für vertraute Partner");
  bd.querySelector('[data-baum-kontakte="b"]').checked = true;
  bd.querySelector('[data-baum-kontakte="b"]')
    .dispatchEvent(new bw.Event("change", { bubbles: true }));
  const vorKontaktSync = baumNachrichten.length;
  Array.from(bd.querySelectorAll("#baum-partner button"))
    .find((b) => b.textContent === "Kontakte synchronisieren").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  const kontaktSendung = baumNachrichten.slice(vorKontaktSync)
    .find((n) => n.cmd === "baum_teilen" && n.art === "kontakt_sync");
  assert.ok(kontaktSendung && kontaktSendung.inhalt.fassung === 1 &&
    kontaktSendung.inhalt.kontakt.nachname === "Beispiel" &&
    kontaktSendung.inhalt.kontakt.foto === "data:image/png;base64,iVBORw0KGgo=" &&
    !Object.prototype.hasOwnProperty.call(kontaktSendung.inhalt.kontakt, "id"),
  "der eigene Kontaktknopf sendet das gültige Foto bytegetreu ohne lokale IDs");
  const kontaktMetadaten = bw.OrganizerTest.daten().kontakte[0].baumKontakt;
  assert.ok(kontaktMetadaten.freigabeId && kontaktMetadaten.version === 1 &&
    kontaktMetadaten.partner.includes("b"),
  "stabile Kontaktbindung und Version werden migrationssicher im Webmodell gespeichert");
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Küche",
    kennung: "a", port: 8737, partner: [{ kennung: "b", name: "Werkstatt",
      bestaetigt: true, vertraut: true, kontakte: true }], post: 0, postOffen: 0,
    eingang: [{ id: "kontakt-update", von: "b", vonName: "Werkstatt",
      art: "kontakt_sync", inhalt: { art: "kontakt_sync", fassung: 1,
        freigabeId: kontaktMetadaten.freigabeId, version: 2, quelle: "b",
        geaendert: 1786500000000, kontakt: { vorname: "Remote", nachname: "",
          firma: "Neue Firma", notiz: "Fernnotiz", geburtstag: "2000-01-02",
          foto: "data:image/jpeg;base64,/9j/2Q==",
          telefone: [{ art: "arbeit", wert: "0203 999" }],
          emailEintraege: [{ art: "arbeit", wert: "neu@example.test" }],
          anschriften: [] } } }] });
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  const gemischt = bw.OrganizerTest.daten().kontakte[0];
  assert.ok(gemischt.vorname === "Anna" && gemischt.firma === "Neue Firma" &&
    gemischt.notiz.includes("Lokal") && gemischt.notiz.includes("Fernnotiz") &&
    gemischt.telefone.some((e) => e.wert === "0203 999") &&
    gemischt.foto === "data:image/png;base64,iVBORw0KGgo=",
  "Kontaktupdates behalten ein abweichendes nichtleeres lokales Foto");
  const kontaktAnzahl = bw.OrganizerTest.daten().kontakte.length;
  bw.App.baumStand({ moeglich: true, an: true, kennung: "a",
    partner: [{ kennung: "b", bestaetigt: true, vertraut: true, kontakte: true }],
    post: 0, postOffen: 0, eingang: [{ id: "kontakt-update-wiederholt", von: "b",
      art: "kontakt_sync", inhalt: { art: "kontakt_sync", fassung: 1,
        freigabeId: kontaktMetadaten.freigabeId, version: 2, quelle: "b",
        geaendert: 1786500000000, kontakt: { vorname: "Anders", nachname: "",
          firma: "", notiz: "Fernnotiz", geburtstag: "", telefone: [],
          emailEintraege: [], anschriften: [] } } }] });
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  assert.strictEqual(bw.OrganizerTest.daten().kontakte.length, kontaktAnzahl,
    "freigabeId, Version und Quelle machen Kontaktupdates idempotent");
  assert.strictEqual(gemischt.vorname, "Anna",
    "ein wiederholter Kontaktstand wird nicht erneut angewendet");
  gemischt.foto = "";
  bw.App.baumStand({ moeglich: true, an: true, kennung: "a",
    partner: [{ kennung: "b", bestaetigt: true, vertraut: true, kontakte: true }],
    post: 0, postOffen: 0, eingang: [{ id: "kontakt-foto-ergaenzen", von: "b",
      art: "kontakt_sync", inhalt: { art: "kontakt_sync", fassung: 1,
        freigabeId: kontaktMetadaten.freigabeId, version: 3, quelle: "b",
        geaendert: 1786500000001, kontakt: { vorname: "", nachname: "", firma: "",
          notiz: "", geburtstag: "", foto: "data:image/webp;base64,UklGRg==",
          telefone: [], emailEintraege: [], anschriften: [] } } }] });
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  assert.strictEqual(gemischt.foto, "data:image/webp;base64,UklGRg==",
    "ein gebundenes Kontaktupdate ergänzt ein leeres lokales Foto bytegetreu");
  bw.App.baumStand({ moeglich: true, an: true, kennung: "a",
    partner: [{ kennung: "b", bestaetigt: true, vertraut: true, kontakte: true }],
    post: 0, postOffen: 0, eingang: [{ id: "kontakt-foto-leer", von: "b",
      art: "kontakt_sync", inhalt: { art: "kontakt_sync", fassung: 1,
        freigabeId: kontaktMetadaten.freigabeId, version: 4, quelle: "b",
        geaendert: 1786500000002, kontakt: { vorname: "", nachname: "", firma: "",
          notiz: "", geburtstag: "", foto: "", telefone: [],
          emailEintraege: [], anschriften: [] } } }] });
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Übernehmen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  assert.strictEqual(gemischt.foto, "data:image/webp;base64,UklGRg==",
    "ein leeres Remote-Foto löscht das lokale Foto nicht");
  const loeschKontakt = bw.OrganizerTest.normalisiere({ kontakte: [{ id: "loeschbar",
    vorname: "Lena", nachname: "Löschbar", baumKontakt: {
      freigabeId: "b:loeschbar", version: 1, quelle: "b", geaendert: 1,
      partner: ["b"], staende: [] } }] }).kontakte[0];
  bw.OrganizerTest.daten().kontakte.push(loeschKontakt);
  const vorLoeschAuto = bw.OrganizerTest.daten().kontakte.length;
  bw.App.baumStand({ moeglich: true, an: true, kennung: "a",
    partner: [{ kennung: "b", name: "Werkstatt", bestaetigt: true, vertraut: true,
      kontakte: true, kontaktLoeschen: true }], post: 0, postOffen: 0,
    eingang: [{ id: "loesch-vorschlag", von: "b", vonName: "Werkstatt",
      art: "kontakt_loeschen", inhalt: { art: "kontakt_loeschen", fassung: 1,
        freigabeId: "b:loeschbar", version: 5, quelle: "b",
        geaendert: 1786500000003 } }] });
  assert.strictEqual(bw.OrganizerTest.daten().kontakte.length, vorLoeschAuto,
    "eingehende Löschvorschläge werden niemals automatisch angewendet");
  assert.ok(Array.from(bd.querySelectorAll(".baum-eingang button"))
    .some((b) => b.textContent === "Löschen"),
  "ein exakt partnergebundener Löschvorschlag wartet auf Einzelbestätigung");
  Array.from(bd.querySelectorAll(".baum-eingang button"))
    .find((b) => b.textContent === "Löschen").click();
  bd.querySelector("#dialog-ja").click();
  await tick();
  assert.strictEqual(bw.OrganizerTest.daten().kontakte.length, vorLoeschAuto - 1,
    "einzeln bestätigter Löschvorschlag entfernt genau den gebundenen Kontakt");
  assert.ok(bw.OrganizerTest.daten().papierkorb.some((x) =>
    x.art === "contact" && x.eintrag.baumKontakt.freigabeId === "b:loeschbar"),
  "bestätigte Baum-Löschung verwendet den normalen Papierkorbweg");
  const sicherheitsDaten = bw.OrganizerTest.daten();
  sicherheitsDaten.baumKontaktBestand.b = 20;
  sicherheitsDaten.baumKontaktErfolgreich.b = true;
  sicherheitsDaten.baumKontaktGeloescht = Array.from({ length: 3 }, (_x, i) => ({
    freigabeId: "b:weg:" + i, version: 1, quelle: "a", geaendert: i + 1,
    name: "Weg " + i, partner: ["b"] }));
  assert.strictEqual(bw.OrganizerTest.kontaktLoeschVorschlaege("b",
    { kontaktLoeschen: true }), null,
  "mehr als zehn Prozent gebundener Kontakte blockieren alle Löschvorschläge");
  sicherheitsDaten.baumKontaktBestand.b = 100;
  assert.strictEqual(bw.OrganizerTest.kontaktLoeschVorschlaege("b",
    { kontaktLoeschen: true }), null,
  "weniger als die Hälfte des letzten gebundenen Bestands blockiert Löschvorschläge");
  sicherheitsDaten.baumKontaktBestand.b = 0;
  assert.deepStrictEqual(bw.OrganizerTest.kontaktLoeschVorschlaege("x",
    { kontaktLoeschen: true }), [],
  "lokale Löschmarken werden keinem falschen Partner vorgeschlagen");
  const dubletteA = bw.OrganizerTest.normalisiere({ kontakte: [{ id: "dup-a",
    vorname: "Dora", nachname: "Doppelt", firma: "Firma", email: "dup@example.test",
    baumKontakt: { freigabeId: "b:dup-a", partner: ["b"] } }] }).kontakte[0];
  const dubletteB = bw.OrganizerTest.normalisiere({ kontakte: [{ id: "dup-b",
    vorname: "Andere", nachname: "Person", firma: "", email: "DUP@example.test",
    baumKontakt: { freigabeId: "b:dup-b", partner: ["b"] } }] }).kontakte[0];
  sicherheitsDaten.kontakte.push(dubletteA, dubletteB);
  const vorDublettenPruefung = sicherheitsDaten.kontakte.length;
  assert.strictEqual(bw.OrganizerTest.baumKontaktDubletten("b").length, 1,
    "normalisierte eindeutige E-Mail erkennt eine mögliche Baum-Dublette");
  assert.strictEqual(sicherheitsDaten.kontakte.length, vorDublettenPruefung,
    "die Dublettenprüfung erzeugt nur Vorschläge und führt nichts automatisch zusammen");
  bw.App.baumStand({ moeglich: true, an: true, kennung: "a", partner: [{ kennung: "b",
    name: "Werkstatt", bestaetigt: true, vertraut: true, kontakte: true }],
    post: 0, postOffen: 0, eingang: [] });
  const partnerKarte = bd.querySelector("#baum-partner .baum-zeile");
  const dublettenBereich = partnerKarte.querySelector(".baum-dubletten");
  const gefahrenBereich = partnerKarte.querySelector(".baum-verbindung-gefahr");
  assert.ok(dublettenBereich && dublettenBereich.textContent.includes(
    "Mögliche Dubletten unter lokalen und eingehenden Kontakten") &&
    dublettenBereich.textContent.includes("Dieses Paar einzeln zusammenführen") &&
    gefahrenBereich === partnerKarte.lastElementChild &&
    gefahrenBereich.querySelector("button.rot")?.textContent === "Verbindung entfernen" &&
    gefahrenBereich.textContent.includes("Synchronisationsstand, wartende Nachrichten und Metadaten") &&
    /\.baum-verbindung-gefahr\s*\{[^}]*margin-top:\s*18px;[^}]*border-top:/s.test(css),
  "Dubletten und Verbindungsgefahr sind nicht klar getrennt oder falsch angeordnet");
  gefahrenBereich.querySelector("button").click();
  assert.ok(bd.querySelector("#dialog-text").textContent.includes("Werkstatt") &&
    bd.querySelector("#dialog-text").textContent.includes(
      "Bereits übernommene Kontakte und lokale Daten bleiben erhalten") &&
    bd.querySelector("#dialog-ja").textContent === "Verbindung entfernen",
  "die getrennte Verbindungsbestätigung nennt Partner und Folgen nicht eindeutig");
  bd.querySelector("#dialog-nein").click();
  bd.querySelector('[data-baum-fern-adresse="b"]').value = "tunnel.example";
  bd.querySelector('[data-baum-fern-port="b"]').value = "10443";
  Array.from(bd.querySelectorAll(".baum-fernziel button"))
    .find((b) => b.textContent === "Endpunkt speichern").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_partner_einstellungen" &&
    n.kennung === "b" && n.vertraut === true &&
    n.fernAdresse === "tunnel.example" && n.fernPort === "10443"),
  "geänderte Partneroptionen erreichen gemeinsam die native Validierung");
  const vorManuell = baumNachrichten.length;
  Array.from(bd.querySelectorAll("#baum-partner button"))
    .find((b) => b.textContent === "Alles synchronisieren").click();
  const manuell = baumNachrichten.slice(vorManuell);
  assert.strictEqual(manuell.filter((n) => n.cmd === "baum_teilen" &&
    n.art === "sync_anfrage").length, 1,
  "manueller Vollabgleich sendet genau eine verschlüsselte Sync-Anfrage");

  bw.MagnolieI18n.setLocale("en");
  bw.App.baumStand({ moeglich: true, an: true, laeuft: true, name: "Kitchen",
    kennung: "a", port: 8737,
    partner: [{ kennung: "b", name: "Workshop", bestaetigt: true },
      { kennung: "c", name: "Office", bestaetigt: true }], post: 3, postOffen: 2,
    eingang: [
      { id: "offer-en-appointment", von: "b", vonName: "Workshop", art: "termin",
        inhalt: { art: "termin", datum: "2026-08-12", titel: "User meeting" } },
      { id: "offer-en-note", von: "c", vonName: "Office", art: "notiz",
        inhalt: { art: "notiz", freigabeId: "c:n3", titel: "User note",
          text: "User text", html: "<p>User text</p>", version: 1, quelle: "c",
          anhaenge: [{ id: "user-file", name: "User file.png", art: "bild",
            daten: bildDaten }] } }
    ]
  });
  assert.ok(bd.querySelector("#zettel").textContent.includes(
    "2 new Magnolienbaum requests await your decision."),
  "englische Mehrzahl der Freigabeanfragen fehlt");
  const enBaumText = bd.querySelector("#einstellungen-inhalt").textContent;
  assert.ok(enBaumText.includes(
    "Several Magnolie Organizers can connect and securely share tasks.") &&
    enBaumText.includes("Name of this branch") &&
    enBaumText.includes("Fingerprint") &&
    enBaumText.includes("Participate in the Magnolienbaum") &&
    enBaumText.includes("Queue: 2 of 3 transmissions await delivery.") &&
    enBaumText.includes("confirmed"),
  "englische Magnolienbaum-Einrichtungsseite ist unvollständig");
  assert.strictEqual(bd.querySelector("#baum-name").placeholder,
    "e.g. kitchen or workshop", "englischer Zweignamenshinweis fehlt");
  assert.strictEqual(bd.querySelector("#baum-adresse").placeholder,
    "or enter a host name or IP address", "englischer Adresshinweis fehlt");
  assert.strictEqual(bd.querySelector("#baum-internet").textContent,
    "Hide internet access", "englischer Internetzugang fehlt");
  assert.strictEqual(bd.querySelector("#baum-internet-adresse").placeholder,
    "Public IPv4 or IPv6 address of the other branch");
  const enSuche = bd.querySelector("#baum-suchen");
  enSuche.click();
  assert.strictEqual(enSuche.textContent, "Searching…", "englischer Suchstand fehlt");
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_suchen"),
    "englische Netzsuche erreicht den Programmkern nicht");
  bw.App.baumGefunden({ nachbarn: [{ name: "IPv6 branch", kennung: "ipv6-branch",
    adresse: "2001:db8::42", port: 8737, fingerabdruck: "1234-5678-9ABC-DEF0" }] });
  assert.ok(bd.querySelector(".baum-adresse").textContent.includes(
    "[2001:db8::42]:8737"), "mDNS-IPv6-Adresse wird eindeutig angezeigt");
  Array.from(bd.querySelectorAll(".baum-nachbarn button"))
    .find((b) => b.textContent === "Connect").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "baum_paaren" &&
    n.adresse === "2001:db8::42"), "mDNS-IPv6-Adresse erreicht unverändert den Kern");
  bw.App.baumGefunden({ nachbarn: [] });
  assert.ok(bd.querySelector("#zettel").textContent.includes("No other branch was found."),
    "englischer leerer Suchstand fehlt");
  bw.App.baumPaarung({ ok: true, kennung: "d", name: "Garden",
    code: "123 456", fingerabdruck: "AAAA-1111-BBBB-2222" });
  assert.ok(bd.querySelector("#dialog-text").textContent.includes(
    "The same code must appear on both computers:") &&
    bd.querySelector("#dialog-text").textContent.includes("Other branch: Garden") &&
    bd.querySelector("#dialog-text").textContent.includes("Fingerprint: AAAA-1111-BBBB-2222"),
  "englischer Paarungsdialog fehlt");
  assert.strictEqual(bd.querySelector("#dialog-ja").textContent,
    "Yes, the code matches");
  bd.querySelector("#dialog-nein").click();
  assert.strictEqual(bd.querySelector(".baum-eingang").previousElementSibling.textContent,
    "2 incoming offers", "englische Angebotsüberschrift fehlt");
  const enAngebote = Array.from(bd.querySelectorAll(".baum-angebot"),
    (element) => element.textContent);
  assert.ok(enAngebote.some((text) => text.includes("Appointment: User meeting") &&
    text.includes("from Workshop")), "englische Terminbeschreibung fehlt");
  assert.ok(enAngebote.some((text) => text.includes("Shared note: User note") &&
    text.includes("1 attachment")), "englische Notiz- und Anhangsbeschreibung fehlt");
  const enAngebotKnoepfe = Array.from(bd.querySelectorAll(".baum-eingang button"),
    (button) => button.textContent);
  assert.ok(enAngebotKnoepfe.includes("Accept and remember") &&
    enAngebotKnoepfe.includes("Reject"), "englische Angebotsaktionen fehlen");
  bw.OrganizerTest.schliesseEinstellungen();
  bw.OrganizerTest.wechsel("notizen");
  const enFreigabe = bd.querySelector(".baum-freigabe");
  assert.ok(enFreigabe && enFreigabe.textContent.includes("Extend sharing"),
    "englische Notizfreigabe fehlt");
  assert.strictEqual(enFreigabe.querySelector("option").textContent, "Workgroup (all)",
    "englische Arbeitsgruppenauswahl fehlt");
  Array.from(enFreigabe.querySelectorAll("button"))
    .find((button) => button.textContent === "Extend sharing").click();
  assert.strictEqual(bd.querySelector("#dialog-text").textContent,
    "Share this entry explicitly with the workgroup?",
  "englische Freigabebestätigung fehlt");
  bd.querySelector("#dialog-nein").click();
  bw.App.baumGesendet({ ok: true, zugestellt: false, an: "Workshop" });
  assert.ok(bd.querySelector("#zettel").textContent.includes(
    "Addressed to Workshop; it will be delivered when the branch is available."),
  "englische vorgemerkte Zustellung fehlt");
  bw.MagnolieI18n.setLocale("de");

  bw.OrganizerTest.zustand().adressen.auswahlId = "sozial-1";
  bw.OrganizerTest.zustand().adressen.modus = "ansehen";
  bw.OrganizerTest.wechsel("adressen");
  assert.strictEqual(bd.querySelectorAll(".sozialknopf").length, 11,
    "andere soziale Medien erscheinen weiterhin als einheitliche kleine Symbole");
  const anrufKnopf = bd.querySelector(".kontakt-anruf");
  assert.ok(anrufKnopf && anrufKnopf.querySelector("path").getAttribute("d") &&
    anrufKnopf.textContent.includes("Anrufen"),
  "der Anrufdienst besitzt kein Telefonsymbol mit barrierefreiem Text");
  assert.strictEqual(bd.querySelectorAll(".sozial-phone,.sozial-sms").length, 0,
    "phone und sms werden in der sozialen Symbolschleife doppelt ausgegeben");
  assert.strictEqual(bd.querySelectorAll(".sozial-kuerzel").length, 0,
    "Markensymbole werden nicht mehr durch Buchstaben überdeckt");
  assert.notStrictEqual(
    bd.querySelector(".sozial-whatsapp path").getAttribute("d"),
    bd.querySelector(".sozial-mastodon path").getAttribute("d"),
    "jeder Kommunikationsdienst besitzt eine eigene erkennbare Magnolie-Form");
  const neueSozialPfade = Array.from(bd.querySelectorAll(
    ".sozial-teams path,.sozial-snapchat path,.sozial-tiktok path,.sozial-youtube path," +
    ".sozial-telegram path,.sozial-x path,.sozial-linkedin path,.sozial-reddit path," +
    ".sozial-custom path"), (pfad) => pfad.getAttribute("d"));
  assert.strictEqual(neueSozialPfade.length, 9,
    "nicht alle neuen Kommunikationsdienste besitzen ein Magnolie-Symbol");
  assert.strictEqual(new Set(neueSozialPfade).size, 9,
    "neue Kommunikationsdienste verwenden keine unterscheidbaren Symbole");
  bd.querySelector(".sozial-teams").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "sozial" && n.dienst === "teams"),
    "Teams reicht seine stabile Dienstkennung nicht an den Kern weiter");
  bd.querySelector(".sozial-whatsapp").click();
  assert.ok(baumNachrichten.some((n) => n.cmd === "sozial" &&
    n.dienst === "whatsapp" && n.wert.includes("170") &&
    n.aktionArt === "program" && n.aktionZiel === "zapzap {ziel}"),
  "ein Kommunikationssymbol reicht Dienst, Kennung und angepasste Aktion sicher weiter");
  Array.from(bd.querySelectorAll("button"))
    .find((b) => b.textContent === "Bearbeiten").click();
  assert.strictEqual(bd.querySelector(".kontakt-sozial-dienst").value, "whatsapp",
    "gespeicherte soziale Medien stehen unter Weitere Felder bereit");
  const dienstOptionen = Array.from(bd.querySelector(".kontakt-sozial-dienst").options,
    (option) => option.textContent);
  assert.deepStrictEqual(dienstOptionen.slice(1, 8),
    ["WhatsApp", "Instagram", "Facebook", "Telegram", "Signal", "Teams", "Threema"],
    "soziale Medien sind nicht nach der erwartbaren Nutzungshäufigkeit geordnet");
  for (const dienstName of ["Teams", "Snapchat", "TikTok", "YouTube", "Telegram",
    "X (vormals Twitter)", "LinkedIn", "Reddit", "Benutzerdefiniert"]) {
    assert.ok(dienstOptionen.includes(dienstName),
      "neuer Kommunikationsdienst fehlt: " + dienstName);
  }
  const eigeneZeile = Array.from(bd.querySelectorAll(".kontakt-sozial-eintrag"))
    .find((eintrag) => eintrag.querySelector(".kontakt-sozial-dienst").value === "custom");
  assert.ok(eigeneZeile && eigeneZeile.querySelector(".kontakt-sozial-symbol").value === "twitch",
    "das gewählte Twitch-Symbol für Benutzerdefiniert wird nicht wiederhergestellt");
  assert.deepStrictEqual(Array.from(eigeneZeile.querySelector(".kontakt-sozial-symbol").options,
    (option) => option.value), ["custom", "twitch", "irc", "discord", "matrix", "slack", "github"],
  "die vorrätigen benutzerdefinierten Symbole sind unvollständig");
  assert.ok(bd.querySelector(".kontakt-form-knoepfe") &&
    bd.querySelector(".kontakt-form-knoepfe").textContent.includes("Änderungen speichern") &&
    bd.querySelector(".kontakt-form-knoepfe").textContent.includes("Abbrechen"),
  "Speichern und Abbrechen stehen dauerhaft in einer eigenen Haftleiste bereit");
  assert.strictEqual(bd.querySelector(".kontakt-formular").lastElementChild,
    bd.querySelector(".kontakt-form-knoepfe"),
    "die feste Aktionsleiste liegt unten und nicht über dem Kontaktformular");
  assert.ok(bd.querySelector(".kontakt-form-inhalt .kontakt-weitere"),
    "auch ausgeklappte weitere Felder scrollen oberhalb der festen Aktionsleiste");
  assert.strictEqual(bd.querySelector(".kontakt-sozial-bearbeitung").children.length, 3,
    "die schmale Zahnrad-Konfiguration bleibt vollständig im Formular sichtbar");
  const sozialWert = bd.querySelector(".kontakt-sozial-wert");
  sozialWert.dispatchEvent(new bw.Event("focus"));
  assert.deepStrictEqual(Array.from(
    bd.querySelector("#kontakt-sozial-telefon-vorschlaege").options, (o) => o.value),
  ["+49 170 1234567", "0203 765432", "0203 999"],
  "telefonbasierte Dienste bieten die Rufnummern des Kontakts an");
  const sozialBearbeitung = bd.querySelector(".kontakt-sozial-bearbeitung");
  assert.strictEqual(sozialBearbeitung.style.display, "none",
    "die Aktionskonfiguration bleibt zunächst hinter dem Zahnrad verborgen");
  bd.querySelector(".kontakt-sozial-zahnrad").click();
  assert.strictEqual(sozialBearbeitung.style.display, "grid",
    "das Zahnrad öffnet die Aktionskonfiguration");
  assert.strictEqual(bd.querySelector(".kontakt-sozial-aktion-art").value, "program");
  assert.strictEqual(bd.querySelector(".kontakt-sozial-aktion-ziel").value,
    "zapzap {ziel}", "der angepasste Programmbefehl wird wieder angezeigt");
  bw.OrganizerTest.oeffneEinstellungen();
  Array.from(bd.querySelectorAll(".einst-reiter-knopf"))
    .find((b) => b.textContent === "Adressen").click();
  assert.ok(bd.querySelector("#adressen-soziale-symbole").checked,
    "die Kommunikationssymbole sind unter Einstellungen ▸ Adressen schaltbar");
  bd.querySelector("#adressen-soziale-symbole").checked = false;
  bd.querySelector("#adressen-soziale-symbole")
    .dispatchEvent(new bw.Event("change", { bubbles: true }));
  bw.OrganizerTest.schliesseEinstellungen();
  bw.OrganizerTest.zustand().adressen.modus = "ansehen";
  bw.OrganizerTest.wechsel("kalender");
  bw.OrganizerTest.wechsel("adressen");
  assert.strictEqual(bd.querySelectorAll(".sozialknopf").length, 0,
    "abgeschaltete Kommunikationssymbole verschwinden von der Karteikarte");
  baumDom.window.close();

  /* ---- Einmaliger Handbuchhinweis im installierten Programm ---- */
  const handbuchNachrichten = [];
  const handbuchDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://handbuch-hinweis.test/",
    pretendToBeVisual: true
  });
  handbuchDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => handbuchNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(handbuchDom.window);
  await new Promise((r) => setTimeout(r, 0));
  const hw = handbuchDom.window;
  const hd = hw.document;
  hw.App.init({ daten: null, neu: true, datenPfad: "",
    handbuchInstalliert: true });
  hw.OrganizerTest.oeffneBuch();
  await new Promise((r) => setTimeout(r, 500));
  assert.ok(!hd.querySelector("#dialog-schleier").classList.contains("verborgen"),
    "der Handbuchhinweis erscheint beim ersten Aufschlagen nicht");
  assert.strictEqual(hd.querySelector("#dialog-ja").textContent, "Handbuch öffnen");
  assert.strictEqual(hd.querySelector("#dialog-nein").textContent, "Nicht jetzt");
  assert.ok(hd.querySelector("#dialog-hinweis") instanceof hw.HTMLElement &&
    hd.querySelector("#dialog-hinweis").tagName === "STRONG" &&
    hd.querySelector("#dialog-hinweis").textContent.includes("Strg+Alt+H"),
  "der Ersteinrichtungsdialog hebt das Hilfsrahmen-Kürzel nicht fett hervor");
  assert.strictEqual(hw.OrganizerTest.daten().einstellungen.allgemein
    .handbuchHinweisGezeigt, true, "der einmalige Hinweis wird nicht gemerkt");
  hd.querySelector("#dialog-ja").click();
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(handbuchNachrichten.some((n) => n.cmd === "handbuch_oeffnen"),
    "„Handbuch öffnen“ erreicht den Programmkern nicht");
  assert.strictEqual(hw.OrganizerTest.zeigeHandbuchHinweis(), false,
    "der Handbuchhinweis darf nicht zweimal erscheinen");
  hw.OrganizerTest.oeffneEinstellungen();
  Array.from(hd.querySelectorAll(".einst-reiter-knopf"))
    .find((b) => b.textContent === "Über").click();
  assert.ok(!hd.querySelector("#handbuch-oeffnen").disabled,
    "das installierte Handbuch bleibt unter Über erreichbar");
  assert.ok(hd.querySelector("#update-pruefen") &&
    !hd.querySelector("#handbuch-aktualisieren"),
    "Organizer und Handbuch besitzen nicht genau einen gemeinsamen Prüfknopf");
  hw.OrganizerTest.schliesseEinstellungen();
  const ohneHandbuch = hw.OrganizerTest.leereDaten();
  hw.App.init({ daten: ohneHandbuch, neu: false, datenPfad: "",
    handbuchInstalliert: false });
  assert.strictEqual(hw.OrganizerTest.zeigeHandbuchHinweis(), false,
    "ohne installiertes Handbuch darf kein Hinweis erscheinen");
  assert.strictEqual(hw.OrganizerTest.daten().einstellungen.allgemein
    .handbuchHinweisGezeigt, false,
    "ohne Handbuch darf der Hinweis nicht als gezeigt gespeichert werden");
  const handbuchUrl = "https://gitlab.com/maik3531/mint-forgs/-/raw/main/" +
    "Magnolie-Organitzer/magnolie-handbuch_1.9.8_all.deb";
  hw.App.updateErgebnis({ ok: true, aktuell: true, version: "2.0.13", url: "",
    sha256: "ab".repeat(32), handbuch: { version: "1.9.8", url: handbuchUrl,
      sha256: "cd".repeat(32) }, fehler: "" });
  assert.ok(!hd.querySelector("#dialog-schleier").classList.contains("verborgen") &&
    hd.querySelector("#dialog-text").textContent.includes("1.9.8") &&
    hd.querySelector("#dialog-ja").textContent === "Handbuch herunterladen",
  "ohne installiertes Handbuch fehlt das Downloadangebot aus update.xml");
  assert.ok(hd.querySelector("#dialog-hinweis").textContent.includes("Tastaturfokus"),
    "der Hilfsrahmen wird im Handbuchhinweis nicht als Tastaturfokus erklärt");
  hd.querySelector("#dialog-ja").click();
  await tick();
  assert.ok(handbuchNachrichten.some((n) =>
    n.cmd === "handbuch_herunterladen" && n.url === handbuchUrl),
  "der Handbuchdownload erreicht den Programmkern nicht mit der geprüften URL");
  handbuchDom.window.close();

  /* ---- Einfacher Kontaktassistent nach dem Handbuchhinweis ---- */
  const assistentNachrichten = [];
  const assistentDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://kontakt-assistent.test/",
    pretendToBeVisual: true
  });
  assistentDom.window.webkit = { messageHandlers: { bridge: {
    postMessage: (text) => assistentNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(assistentDom.window);
  await tick();
  const aw = assistentDom.window;
  const ad = aw.document;
  aw.App.init({ daten: null, neu: true, echterErststart: true, datenPfad: "",
    handbuchInstalliert: true });
  aw.OrganizerTest.oeffneBuch();
  await new Promise((r) => setTimeout(r, 500));
  assert.ok(!ad.querySelector(".kontakt-assistent") &&
    !ad.querySelector("#dialog-schleier").classList.contains("verborgen"),
  "der Kontaktassistent erscheint vor dem Handbuchhinweis");
  ad.querySelector("#dialog-nein").click();
  await tick();
  await tick();
  const assistent = ad.querySelector(".kontakt-assistent");
  assert.ok(assistent && assistent.querySelectorAll(".kontakt-assistent-knopf").length === 3 &&
    assistent.textContent.includes("Evolution/Thunderbird") &&
    assistent.textContent.includes("Kontakt") && assistent.textContent.includes("Nicht jetzt"),
  "der einfache Kontaktassistent erscheint nicht mit großen Quellen und Überspringen: " +
    (assistent?.textContent || "fehlt") + " " +
    JSON.stringify(aw.OrganizerTest.kontaktAssistentStand()));
  Array.from(assistent.querySelectorAll("button"))
    .find((button) => button.textContent === "Nicht jetzt").click();
  const assistentSpeichern = assistentNachrichten.filter(
    (nachricht) => nachricht.cmd === "speichern").at(-1);
  assert.ok(ad.querySelector(".kontakt-assistent") && assistentSpeichern &&
    Array.from(assistent.querySelectorAll("button")).every((button) => button.disabled),
  "der Assistent wartet nicht sichtbar auf die dauerhafte Speicherung");
  const assistentBestaetigt = new Set();
  for (let i = 0; i < 20 && ad.querySelector(".kontakt-assistent"); i++) {
    const speichern = assistentNachrichten.filter((nachricht) =>
      nachricht.cmd === "speichern" && !assistentBestaetigt.has(nachricht.id)).at(-1);
    if (speichern) {
      assistentBestaetigt.add(speichern.id);
      aw.App.gespeichert({ ok: true, id: speichern.id });
    }
    await tick();
  }
  assert.ok(!ad.querySelector(".kontakt-assistent") &&
    aw.OrganizerTest.daten().einstellungen.allgemein.kontaktErsteinrichtungVersion === 1,
  "Überspringen schließt oder merkt den Kontaktassistenten nach dem Speichern nicht");
  assert.ok(assistentNachrichten.some((nachricht) => nachricht.cmd === "speichern"),
    "der Abschluss des Kontaktassistenten wird nicht dauerhaft gespeichert");
  assistentDom.window.close();

  /* ---- Tastatur, Fokusfallen und logische Fokus-Rückgabe ---- */
  const fokusDom = new JSDOM(html, {
    runScripts: "dangerously", url: "https://fokus.test/",
    pretendToBeVisual: true
  });
  ladeAnwendung(fokusDom.window);
  await new Promise((r) => setTimeout(r, 0));
  const fw = fokusDom.window;
  const fd = fw.document;
  const fT = fw.OrganizerTest;
  const fokusDaten = fT.leereDaten();
  const fokusDatum = fT.isoHeute();
  fokusDaten.einstellungen.ansicht = "month";
  fokusDaten.einstellungen.kalender.klickLegtAn = true;
  fokusDaten.aufgaben.push({ id: "fokus-aufgabe", titel: "Tastaturprüfung",
    prio: 2, faellig: fokusDatum, erledigt: false, notiz: "", personen: [],
    erinnern: false, individuelleErinnerungTage: 0, geaendert: Date.now() });
  fokusDaten.termine.push({ id: "fokus-termin", uid: "fokus-termin-uid",
    datum: fokusDatum, endDatum: "", zeit: "09:00", endZeit: "09:30",
    titel: "Fokusprüfung", notiz: "", kategorien: "", wiederholung: null });
  fw.App.init({ daten: fokusDaten, neu: false, datenPfad: "" });
  fT.oeffneBuch();

  const monatsraster = fd.querySelector(".monatsraster");
  assert.strictEqual(monatsraster.getAttribute("role"), "grid",
    "das Monatsblatt ist kein Tastaturraster");
  let kalenderZellen = Array.from(monatsraster.querySelectorAll("[role=gridcell]"));
  assert.strictEqual(kalenderZellen.filter((zelle) => zelle.tabIndex === 0).length, 1,
    "im Monatsraster gibt es nicht genau einen roving Fokus");
  let kalenderFokus = kalenderZellen.find((zelle) => zelle.tabIndex === 0);
  kalenderFokus.focus();
  kalenderFokus.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "ArrowRight", bubbles: true, cancelable: true }));
  assert.strictEqual(fd.activeElement,
    kalenderZellen[kalenderZellen.indexOf(kalenderFokus) + 1],
    "Pfeil rechts verschiebt den Fokus nicht um einen Kalendertag");
  kalenderFokus = fd.activeElement;
  const seitenDatum = new fw.Date(kalenderFokus.dataset.fokus.slice("kalender-tag:".length) +
    "T12:00:00");
  seitenDatum.setMonth(seitenDatum.getMonth() + 1);
  const seitenIso = seitenDatum.getFullYear() + "-" +
    String(seitenDatum.getMonth() + 1).padStart(2, "0") + "-" +
    String(seitenDatum.getDate()).padStart(2, "0");
  kalenderFokus.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "PageDown", bubbles: true, cancelable: true }));
  assert.strictEqual(fd.activeElement.dataset.fokus, "kalender-tag:" + seitenIso,
    "Bild ab verschiebt den roving Fokus nicht um einen Monat");

  const rueckkehrMarke = fd.activeElement.dataset.fokus;
  fd.activeElement.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Enter", bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 0));
  const terminDialog = fd.querySelector(".termin-blatt");
  assert.ok(terminDialog && fd.activeElement.id === "tb-titel",
    "Enter auf einem Kalendertag öffnet den Termin nicht mit Anfangsfokus");
  assert.ok(fd.querySelector("#schreibtisch").hasAttribute("inert") &&
    fd.querySelector("#statusleiste").hasAttribute("inert"),
  "ein Modalblatt nimmt Buch und Fußleiste nicht aus der Fokusreihenfolge");
  const modalElemente = Array.from(terminDialog.querySelectorAll(
    "button:not([disabled]), input:not([disabled]):not([type=hidden]), " +
    "select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"));
  modalElemente[modalElemente.length - 1].focus();
  fd.activeElement.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Tab", bubbles: true, cancelable: true }));
  assert.strictEqual(fd.activeElement, modalElemente[0],
    "Tab verlässt das obere Modalblatt am Ende");
  modalElemente[0].dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }));
  assert.strictEqual(fd.activeElement, modalElemente[modalElemente.length - 1],
    "Umschalt+Tab verlässt das obere Modalblatt am Anfang");
  Array.from(terminDialog.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "Abbrechen").click();
  assert.strictEqual(fd.activeElement.dataset.fokus, rueckkehrMarke,
    "nach dem Kalenderdialog fehlt die logische Fokus-Rückgabe");
  assert.ok(!fd.querySelector("#schreibtisch").hasAttribute("inert") &&
    !fd.querySelector("#statusleiste").hasAttribute("inert"),
  "nach dem Modalblatt bleibt der Hintergrund inert");

  fT.wechsel("aufgaben");
  let aufgabenAktion = fd.querySelector("[data-fokus='aufgabe:fokus-aufgabe']");
  assert.strictEqual(aufgabenAktion.tagName, "BUTTON",
    "die Aufgabenhauptaktion ist kein nativer Knopf");
  aufgabenAktion.focus();
  aufgabenAktion.click();
  assert.strictEqual(fd.activeElement.dataset.fokus, "aufgabe:fokus-aufgabe",
    "das Neuzeichnen verliert den Fokus der Aufgabenzeile");
  const aufgabenStatus = fd.querySelector(
    "[data-fokus='aufgabe-status:fokus-aufgabe']");
  aufgabenStatus.focus();
  aufgabenStatus.click();
  assert.strictEqual(fd.activeElement.dataset.fokus,
    "aufgabe-status:fokus-aufgabe",
  "das Verschieben einer erledigten Aufgabe verliert den Statusfokus");

  fT.wechsel("kalender");
  kalenderFokus = fd.querySelector("[data-fokus^='kalender-tag:'][tabindex='0']");
  kalenderFokus.focus();
  fT.oeffneTerminBlatt(fT.daten().termine[0], fokusDatum);
  await new Promise((r) => setTimeout(r, 0));
  const loeschen = fd.querySelector("#tb-loeschen");
  loeschen.focus();
  loeschen.click();
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(fd.querySelector("#termin-schleier").hasAttribute("inert") &&
    fd.querySelector(".termin-blatt").getAttribute("aria-hidden") === "true",
  "ein verschachtelter Dialog deaktiviert das darunterliegende Modalblatt nicht");
  fd.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Escape", bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(fd.querySelector("#dialog-schleier").classList.contains("verborgen") &&
    fd.querySelector("#termin-schleier"),
  "Escape schließt nicht ausschließlich den obersten Dialog");
  assert.strictEqual(fd.activeElement, loeschen,
    "nach dem verschachtelten Dialog kehrt der Fokus nicht zum Auslöser zurück");
  fd.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Escape", bubbles: true, cancelable: true }));
  assert.ok(!fd.querySelector("#termin-schleier") &&
    fd.activeElement.dataset.fokus === kalenderFokus.dataset.fokus,
  "Escape schließt das Terminblatt nicht mit Fokus-Rückgabe");

  const einstellungenAusloeser = fd.querySelector("#knopf-einstellungen");
  einstellungenAusloeser.focus();
  fT.oeffneEinstellungen();
  await new Promise((r) => setTimeout(r, 0));
  const ersterReiter = fd.querySelector(".einst-reiter-knopf");
  ersterReiter.focus();
  ersterReiter.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "ArrowRight", bubbles: true, cancelable: true }));
  const aktiverReiter = fd.activeElement;
  assert.strictEqual(aktiverReiter.getAttribute("aria-selected"), "true",
    "Pfeiltasten aktivieren den nächsten Einstellungsreiter nicht");
  assert.strictEqual(fd.querySelector("[role=tabpanel]").getAttribute("aria-labelledby"),
    aktiverReiter.id, "Einstellungsreiter und Tabpanel sind nicht verbunden");
  assert.strictEqual(Array.from(fd.querySelectorAll(".einst-reiter-knopf"))
    .filter((button) => button.tabIndex === 0).length, 1,
  "die Einstellungsreiter besitzen keinen eindeutigen roving Fokus");
  fd.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "Escape", bubbles: true, cancelable: true }));
  assert.strictEqual(fd.activeElement, einstellungenAusloeser,
    "nach den Einstellungen kehrt der Fokus nicht zum Auslöser zurück");

  fT.wechsel("kalender");
  fd.querySelector("#ansicht-umschalter [data-ansicht='week']").click();
  let wochenFokus = fd.querySelector("[data-fokus^='kalender-woche:'][tabindex='0']");
  assert.ok(wochenFokus && fd.querySelector(".wochen-spalte[role=grid]"),
    "die Wochenansicht besitzt kein roving Raster");
  const wochenMarke = wochenFokus.dataset.fokus;
  wochenFokus.focus();
  wochenFokus.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "ArrowDown", bubbles: true, cancelable: true }));
  assert.notStrictEqual(fd.activeElement.dataset.fokus, wochenMarke,
    "Pfeil abwärts blättert den Wochenfokus nicht weiter");

  fd.querySelector("#ansicht-umschalter [data-ansicht='day']").click();
  let stundenFokus = fd.querySelector("[data-fokus^='kalender-stunde:'][tabindex='0']");
  assert.ok(stundenFokus && stundenFokus.getAttribute("role") === "gridcell",
    "die Tagesstunden besitzen keinen roving Fokus");
  const stundenMarke = stundenFokus.dataset.fokus;
  stundenFokus.focus();
  stundenFokus.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "ArrowDown", bubbles: true, cancelable: true }));
  assert.notStrictEqual(fd.activeElement.dataset.fokus, stundenMarke,
    "Pfeil abwärts verschiebt den Fokus nicht zur nächsten Stunde");

  fT.wechsel("planer");
  let planerFokus = fd.querySelector("[data-fokus^='planer-tag:'][tabindex='0']");
  assert.ok(planerFokus && planerFokus.getAttribute("role") === "gridcell",
    "der Jahresplaner besitzt keinen roving Fokus");
  const planerMarke = planerFokus.dataset.fokus;
  planerFokus.focus();
  planerFokus.dispatchEvent(new fw.KeyboardEvent("keydown",
    { key: "ArrowRight", bubbles: true, cancelable: true }));
  assert.notStrictEqual(fd.activeElement.dataset.fokus, planerMarke,
    "Pfeil rechts verschiebt den Fokus im Jahresplaner nicht");
  fokusDom.window.close();

  assert.ok(/body\[data-hilfsrahmen="an"\][\s\S]{0,80}outline:\s*2px solid/.test(css) &&
    !/outline:\s*2px dashed/.test(css),
  "der optionale Hilfsrahmen ist nicht durchgezogen");
  assert.ok(/#tb-notiz:focus-visible\s*\{[\s\S]{0,120}outline-offset:\s*-2px/.test(css) &&
    /#tb-notiz:focus-visible\s*\{[\s\S]{0,180}box-shadow:\s*inset/.test(css),
  "der Hilfsrahmen des Termin-Notizfeldes liegt nicht innerhalb des Scrollrahmens");
  assert.ok(/\.tb-links\s+:focus-visible,[\s\S]{0,180}outline-offset:\s*-2px/.test(css) &&
    /\.ods-feldliste\s*\{[\s\S]{0,100}flex-direction:\s*column/.test(css),
  "Fokusrahmen in Rollflächen oder vertikale ODS-Spaltenliste fehlen");
  assert.ok(/\.kontakt-form-inhalt\s+:focus-visible\s*\{[\s\S]{0,100}outline-offset:\s*-2px/.test(css),
  "der Hilfsrahmen im rollenden Kontaktformular liegt nicht innerhalb der Fläche");
  assert.ok(/\.notiz-editor\s+:focus-visible\s*\{[\s\S]{0,100}outline-offset:\s*-2px/.test(css),
  "Hilfsrahmen im Notizeditor liegen nicht vollständig innerhalb ihrer Felder");

  assert.ok(/#einstellungen-blatt\s*\{[\s\S]{0,140}height:\s*min\(820px,\s*96vh\)/.test(css) &&
    /#einstellungen-blatt\s*\{[\s\S]{0,220}overflow:\s*hidden/.test(css),
    "das Einstellungsblatt besitzt keine feste, bildschirmbegrenzte Höhe");
  assert.ok(/#einstellungen-inhalt\s*\{[\s\S]{0,100}min-height:\s*0/.test(css) &&
    /\.einst-seite\s*\{[\s\S]{0,100}flex:\s*1/.test(css) &&
    /\.einst-seite\s*\{[\s\S]{0,140}overflow-y:\s*auto/.test(css),
    "die Einstellungsseite ist nicht der einzige flexible Rollbereich");
  assert.ok(/\.einst-seite\s*\{[\s\S]{0,180}padding-inline:\s*4px 5px/.test(css),
    "der linke Rahmen der Einstellungsseiten hat keinen geschützten Innenabstand");
  assert.ok(/\.seiten-inhalt\.notizen-rechts\s*\{\s*overflow:\s*hidden/.test(css) &&
    /\.notiz-einfuegen\s*\{[\s\S]{0,260}justify-content:\s*flex-start/.test(css) &&
    /\.baum-notiz-stand\s*\{[\s\S]{0,180}white-space:\s*normal/.test(css),
  "die Notizwerkzeuge sind nicht überlaufsicher innerhalb der rechten Seite angeordnet");

  const katalogDateien = fs.readdirSync(path.join(WEB, "i18n"))
    .filter((name) => name.endsWith(".js")).sort();
  assert.strictEqual(katalogDateien.length, 19,
    "die JS/DOM-Prüfung findet nicht alle 19 zusätzlichen Sprachkataloge");
  const sprachenDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://sprachen-layout.test/", pretendToBeVisual: true });
  sprachenDom.window.eval(i18nJs);
  for (const name of katalogDateien) {
    sprachenDom.window.eval(fs.readFileSync(path.join(WEB, "i18n", name), "utf8"));
  }
  sprachenDom.window.eval(js);
  sprachenDom.window.document.dispatchEvent(new sprachenDom.window.Event(
    "DOMContentLoaded", { bubbles: true }));
  for (const sprache of ["en", ...katalogDateien.map((name) => path.basename(name, ".js"))]) {
    const sprachDaten = sprachenDom.window.OrganizerTest.leereDaten();
    sprachDaten.notizen.push({ id: "sprach-notiz", titel: "Layout", text: "Text",
      html: "<p>Text</p>", anhaenge: [], notizbuchId: sprachDaten.notizbuecher[0].id });
    sprachenDom.window.App.init({ daten: sprachDaten, neu: false,
      regional: { language: sprache } });
    sprachenDom.window.OrganizerTest.zustand().notizen.auswahlId = "sprach-notiz";
    for (const bereich of ["kalender", "aufgaben", "adressen", "notizen", "jahrestage",
      "planer", "gesundheit"]) {
      sprachenDom.window.OrganizerTest.wechsel(bereich);
      assert.ok(sprachenDom.window.document.querySelector("#inhalt-rechts").children.length,
        "rechte DOM-Seite fehlt für " + sprache + "/" + bereich);
    }
    sprachenDom.window.OrganizerTest.wechsel("notizen");
    assert.ok(sprachenDom.window.document.querySelector(".notizen-rechts .notiz-einfuegen"),
      "Notizlayout fehlt in Sprache " + sprache);
  }
  sprachenDom.window.close();

  const kontaktAktionenDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://contact-actions.test/", pretendToBeVisual: true });
  const kontaktAktionenNachrichten = [];
  kontaktAktionenDom.window.__MAGNOLIE_BRUECKE__ = "contact_actions_bridge";
  kontaktAktionenDom.window.webkit = { messageHandlers: { contact_actions_bridge: {
    postMessage: (text) => kontaktAktionenNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(kontaktAktionenDom.window, "de");
  const kontaktW = kontaktAktionenDom.window;
  const kontaktD = kontaktW.document;
  const kontaktT = kontaktW.OrganizerTest;
  const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  const fallbackRef = kontaktT.anrufClientRef({ getRandomValues: (bytes) => {
    for (let i = 0; i < bytes.length; i++) bytes[i] = i * 17;
    return bytes;
  } });
  assert.match(fallbackRef, uuidV4,
    "der getRandomValues-Rückfall erzeugt keine kanonische UUID v4");
  assert.strictEqual(fallbackRef, "00112233-4455-4677-8899-aabbccddeeff",
    "der UUID-Rückfall setzt Version oder RFC-4122-Variante nicht korrekt");
  const smsTelefonStand = { peers: [{ device_id: "telefon-1", display_name: "Mobiltelefon",
    state: "online_wifi",
    capabilities: { items: { sms_send: { available: true, versions: [1] },
      dial_request: { available: true, versions: [1] } } },
    grants: { grants: { sms_send: true, dial_request: true } } }],
    bluetooth: { available: true, devices: [
      { address: "AA:BB:CC:DD:EE:FF", name: "Mobiltelefon HFP" } ] } };
  const zeichneKontaktAktionen = (telefone, sozialeMedien = [], stand = smsTelefonStand) => {
    kontaktW.App.init({ daten: { kontakte: [{ id: "kontakt-aktionen", uid: "kontakt-aktionen",
      vorname: "Ada", nachname: "Lovelace", telefone: telefone,
      sozialeMedien: sozialeMedien }] }, neu: false, regional: { language: "de" } });
    kontaktW.App.telefonStand(stand);
    kontaktT.zustand().adressen.auswahlId = "kontakt-aktionen";
    kontaktT.wechsel("adressen");
    return kontaktD.querySelector("#inhalt-rechts");
  };

  let kontaktKarte = zeichneKontaktAktionen([
    { wert: "0203 111111", typen: ["HOME", "VOICE"] }
  ]);
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-anruf").length, 1,
    "Festnetz zeigt nicht genau eine Anrufaktion");
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-sms").length, 0,
    "Festnetz bietet trotz fehlender Mobilnummer SMS an");
  kontaktKarte.querySelector(".kontakt-anruf").click();
  const ersterWaehlauftrag = kontaktAktionenNachrichten.find((nachricht) =>
    nachricht.cmd === "telefon_waehlen" && nachricht.nummer === "0203 111111");
  assert.ok(ersterWaehlauftrag && uuidV4.test(ersterWaehlauftrag.clientRef),
  "eine einzelne Rufnummer verwendet nicht den authentisierten Wählauftrag");
  assert.strictEqual(ersterWaehlauftrag.kennung, "telefon-1",
    "der Wählauftrag ist nicht an das ausgewählte Magnolie-Notes-Telefon gebunden");

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "0171 222222", typen: ["CELL"] }
  ]);
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-anruf").length, 1,
    "Mobilnummer zeigt keine einzelne Anrufaktion");
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-sms").length, 1,
    "Mobilnummer zeigt keine einzelne SMS-Aktion");
  const ersterKontext = new kontaktW.Event("contextmenu", { bubbles: true, cancelable: true });
  kontaktKarte.querySelector(".kontakt-sms").dispatchEvent(ersterKontext);
  assert.ok(ersterKontext.defaultPrevented && kontaktD.querySelector(".kommunikation-belegung-dialog"),
    "SMS-Rechtsklick verhindert Browsermenü nicht oder öffnet keinen Belegungsdialog");
  const smsBelegungText = kontaktD.querySelector(".kommunikation-belegung-dialog").textContent;
  assert.ok(smsBelegungText.includes("Programmbefehl") &&
    smsBelegungText.includes("Der Befehl wird sicher ohne Shell gestartet.") &&
    !smsBelegungText.includes("eingehende Anrufe") &&
    !smsBelegungText.includes("Magnolie-Datenverbindung"),
  "deutscher SMS-Belegungsdialog übersetzt Befehl/Hilfe nicht oder zeigt Anrufoptionen");
  kontaktD.querySelector(".kommunikation-belegung-dialog .dialog-knoepfe button:last-child").click();
  kontaktKarte.querySelector(".kontakt-sms").click();
  assert.deepStrictEqual(Array.from(kontaktD.querySelectorAll(".sms-dialog .sms-nummer option"),
    (option) => option.value), ["0171 222222"],
  "SMS-Dialog bietet bei einer Mobilnummer nicht ausschließlich diese vorausgewählt an");
  kontaktD.querySelector(".sms-dialog .sms-schliessen").click();

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "0203 333333", typen: ["WORK", "VOICE"] },
    { wert: "0172 444444", typen: ["MOBILE"] },
    { wert: "0203 555555", typen: ["FAX"] },
    { wert: "0160 666666", typen: ["PAGER"] }
  ]);
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-anruf").length, 1,
    "gemischte Rufnummern erzeugen mehr als eine Anrufaktion");
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-sms").length, 1,
    "gemischte Rufnummern erzeugen nicht genau eine SMS-Aktion");
  kontaktKarte.querySelector(".kontakt-sms").click();
  assert.deepStrictEqual(Array.from(kontaktD.querySelectorAll(".sms-dialog .sms-nummer option"),
    (option) => option.value), ["0172 444444"],
  "SMS-Dialog enthält Festnetz-, Fax- oder Pagernummern");
  kontaktD.querySelector(".sms-dialog .sms-schliessen").click();

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "0203 777777", typen: ["HOME", "VOICE"] },
    { wert: "0173 888888", typen: ["CELL"] }
  ], [{ dienst: "phone", wert: "0203 777777" },
    { dienst: "sms", wert: "0173 888888" },
    { dienst: "signal", wert: "0173 888888" }]);
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-anruf").length, 1,
    "mehrere Rufnummern erzeugen mehr als ein Anrufsymbol");
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-sms").length, 1,
    "mehrere Rufnummern erzeugen mehr als ein SMS-Symbol");
  assert.strictEqual(kontaktKarte.querySelectorAll(".sozial-phone,.sozial-sms").length, 0,
    "soziale phone-/sms-Einträge verdoppeln die einheitlichen Kontaktaktionen");
  assert.strictEqual(kontaktKarte.querySelectorAll(".sozial-signal").length, 1,
    "andere Messenger werden zusammen mit phone/sms ausgeblendet");
  kontaktKarte.querySelector(".kontakt-anruf").click();
  const anrufDialog = kontaktD.querySelector(".anruf-dialog");
  const anrufAuswahlTexte = anrufDialog && Array.from(
    anrufDialog.querySelectorAll(".anruf-auswahl button"), (button) => button.textContent);
  assert.ok(anrufAuswahlTexte && anrufAuswahlTexte.some((text) =>
    text.includes(": 0203 777777")) && anrufAuswahlTexte.some((text) =>
    text.includes(": 0173 888888")),
  "Anrufauswahl zeigt nicht Bezeichnung und Nummer aller anrufbaren Nummern");
  assert.strictEqual(anrufDialog.querySelectorAll(".anruf-auswahl button").length, 2,
    "Anrufauswahl enthält nicht genau die anrufbaren Nummern");
  anrufDialog.querySelectorAll(".anruf-auswahl button")[1].click();
  assert.ok(kontaktAktionenNachrichten.some((nachricht) =>
    nachricht.cmd === "telefon_waehlen" && nachricht.nummer === "0173 888888"),
  "die ausgewählte Nummer wird nicht über den sicheren Wählauftrag gesendet");

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "0174 111111", typen: ["CELL"] }
  ], [], { peers: [] });
  kontaktKarte.querySelector(".kontakt-anruf").click();
  const nichtVerfuegbarDialog = kontaktD.querySelector(".anruf-dialog");
  assert.ok(nichtVerfuegbarDialog &&
    nichtVerfuegbarDialog.querySelector(".dialog-knoepfe > button") &&
    nichtVerfuegbarDialog.querySelector(".dialog-knoepfe > button").textContent === "Schließen" &&
    !nichtVerfuegbarDialog.textContent.includes("[object HTML"),
  "Anrufdialog enthält keinen echten Schließen-Button oder zeigt einen DOM-Knoten als Text");
  nichtVerfuegbarDialog.querySelector(".dialog-knoepfe > button").click();
  assert.strictEqual(kontaktKarte.querySelectorAll(".kontakt-sms").length, 1,
    "Mobilnummer verliert ohne Telefonverbindung die SMS-Aktion");
  kontaktKarte.querySelector(".kontakt-sms").click();
  let eigenerSmsDialog = kontaktD.querySelector(".sms-dialog");
  assert.ok(eigenerSmsDialog && eigenerSmsDialog.querySelector(".sms-schreibblatt") &&
    eigenerSmsDialog.querySelector(".sms-komponist button").disabled,
    "ohne Telefonverbindung öffnet sich nicht der eigene erklärende SMS-Dialog");
  assert.ok(!kontaktAktionenNachrichten.some((nachricht) =>
    nachricht.cmd === "sozial" && nachricht.dienst === "sms"),
  "ohne Telefonverbindung wird unerwartet Valent oder der SMS-Systemweg geöffnet");
  eigenerSmsDialog.querySelector(".sms-schliessen").click();

  const grantDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://call-grants.test/", pretendToBeVisual: true });
  const grantNachrichten = [];
  grantDom.window.__MAGNOLIE_BRUECKE__ = "call_grants_bridge";
  grantDom.window.webkit = { messageHandlers: { call_grants_bridge: {
    postMessage: (text) => grantNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(grantDom.window, "de");
  const grantDaten = grantDom.window.OrganizerTest.leereDaten();
  grantDaten.einstellungen.adressen.kommunikation.anruf = { art: "magnolie", programm: "",
    eingehendBenachrichtigen: true, computerTelefonie: true, klingeltonLeiser: false };
  grantDom.window.App.init({ daten: grantDaten, neu: false, regional: { language: "de" } });
  grantNachrichten.length = 0;
  const grantPeer = { device_id: "telefon-grants", state: "online_wifi",
    grants: { grants: {} }, local_grants: { grants: { incoming_call_state: false,
      incoming_call_number: false, answer_call: false, end_call: false } }, capabilities: { items: {} } };
  grantDom.window.App.telefonStand({ peers: [grantPeer] });
  const grantBefehle = grantNachrichten.filter((nachricht) => nachricht.cmd === "telefon_freigabe");
  assert.deepStrictEqual(grantBefehle.map((nachricht) => [nachricht.kennung, nachricht.name, nachricht.an]), [
    ["telefon-grants", "incoming_call_state", true],
    ["telefon-grants", "incoming_call_number", true],
    ["telefon-grants", "answer_call", true],
    ["telefon-grants", "end_call", true]
  ], "gespeicherte Anrufoptionen werden beim Start nicht in Telefonfreigaben übernommen");
  assert.strictEqual(grantDom.window.OrganizerTest.daten().einstellungen.adressen.kommunikation.anruf.telefonId,
    "telefon-grants", "alte Anrufoptionen werden nicht sicher an das vorhandene Telefon gebunden");
  grantDom.window.App.telefonStand({ peers: [grantPeer] });
  assert.strictEqual(grantNachrichten.filter((nachricht) => nachricht.cmd === "telefon_freigabe").length, 4,
    "unveränderter Telefonstand erzeugt eine Freigabeschleife");
  grantDom.window.App.telefonStand({ peers: [Object.assign({}, grantPeer, {
    device_id: "anderes-telefon", local_grants: { grants: {
      incoming_call_state: true, incoming_call_number: true, answer_call: true, end_call: true } }
  })] });
  assert.deepStrictEqual(grantNachrichten.filter((nachricht) => nachricht.cmd === "telefon_freigabe")
    .slice(-4).map((nachricht) => [nachricht.kennung, nachricht.name, nachricht.an]), [
      ["anderes-telefon", "incoming_call_state", false],
      ["anderes-telefon", "incoming_call_number", false],
      ["anderes-telefon", "answer_call", false],
      ["anderes-telefon", "end_call", false]
    ], "alte Anrufrechte eines nicht gebundenen Telefons werden nicht widerrufen");
  grantDom.window.OrganizerTest.daten().einstellungen.adressen.kommunikation.anruf.art = "system";
  grantDom.window.App.telefonStand({ peers: [Object.assign({}, grantPeer, { local_grants: { grants: {
    incoming_call_state: true, incoming_call_number: true, answer_call: true, end_call: true } } })] });
  assert.deepStrictEqual(grantNachrichten.filter((nachricht) => nachricht.cmd === "telefon_freigabe")
    .slice(-4).map((nachricht) => [nachricht.name, nachricht.an]), [
      ["incoming_call_state", false], ["incoming_call_number", false],
      ["answer_call", false], ["end_call", false]
    ], "ein anderer Anrufweg widerruft die nicht mehr benötigten Telefonfreigaben nicht");
  grantDom.window.close();

  const ausgehendDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://outgoing-call-grants.test/", pretendToBeVisual: true });
  const ausgehendNachrichten = [];
  ausgehendDom.window.__MAGNOLIE_BRUECKE__ = "outgoing_call_grants_bridge";
  ausgehendDom.window.webkit = { messageHandlers: { outgoing_call_grants_bridge: {
    postMessage: (text) => ausgehendNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(ausgehendDom.window, "de");
  const ausgehendDaten = ausgehendDom.window.OrganizerTest.leereDaten();
  ausgehendDaten.einstellungen.adressen.kommunikation.anruf = { art: "magnolie", programm: "",
    telefonId: "telefon-ausgehend", eingehendBenachrichtigen: false,
    computerTelefonie: false, klingeltonLeiser: false };
  ausgehendDom.window.App.init({ daten: ausgehendDaten, neu: false, regional: { language: "de" } });
  ausgehendNachrichten.length = 0;
  const ausgehendPeer = { device_id: "telefon-ausgehend", display_name: "Telefon",
    state: "online_wifi", grants: { grants: {} }, local_grants: { grants: {
      incoming_call_state: true, incoming_call_number: false, answer_call: false, end_call: true } },
    capabilities: { items: { incoming_call_state: { available: true, versions: [2] } } } };
  const ausgehendRef = "12345678-1234-4234-9234-123456789abc";
  ausgehendDom.window.OrganizerTest.zeigeAnrufDialog({ call_ref: ausgehendRef,
    client_ref: ausgehendRef, revision: 0, state: "ringing", direction: "outgoing",
    control_origin: "desktop", number: "+49170123456", number_status: "available",
    started_ms: Date.now(), offhook_ms: 0, ended_ms: 0, occurred_ms: Date.now(),
    spam_status: "unknown", battery_percent: -1, battery_captured_ms: 0 }, ausgehendPeer);
  ausgehendDom.window.App.telefonStand({ peers: [ausgehendPeer] });
  assert.ok(!ausgehendNachrichten.some((nachricht) => nachricht.cmd === "telefon_freigabe" &&
    ["incoming_call_state", "end_call"].includes(nachricht.name) && nachricht.an === false),
  "temporäre Status- und Auflegerechte werden während eines ausgehenden Anrufs widerrufen");
  ausgehendDom.window.OrganizerTest.daten().einstellungen.adressen.kommunikation.anruf.art = "system";
  ausgehendDom.window.App.telefonStand({ peers: [ausgehendPeer] });
  assert.ok(!ausgehendNachrichten.some((nachricht) => nachricht.cmd === "telefon_freigabe" &&
    ["incoming_call_state", "end_call"].includes(nachricht.name) && nachricht.an === false),
  "eine geänderte Anrufzuweisung entzieht einem laufenden Anruf seine temporären Rechte");
  ausgehendDom.window.App.telefonEingehenderAnruf(Object.assign({ device_id: "telefon-ausgehend" }, {
    call_ref: ausgehendRef, revision: 1, state: "idle", direction: "outgoing",
    control_origin: "desktop", number: "+49170123456", number_status: "available",
    started_ms: Date.now() - 1000, offhook_ms: 0, ended_ms: Date.now(), occurred_ms: Date.now(),
    spam_status: "unknown", battery_percent: -1, battery_captured_ms: 0 }));
  assert.deepStrictEqual(ausgehendNachrichten.filter((nachricht) => nachricht.cmd === "telefon_freigabe")
    .slice(-2).map((nachricht) => [nachricht.name, nachricht.an]), [
      ["incoming_call_state", false], ["end_call", false]
    ], "temporäre Anrufrechte werden nach dem ausgehenden Anruf nicht widerrufen");
  ausgehendDom.window.close();

  const anrufHerkunftDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://call-origin.test/", pretendToBeVisual: true });
  const anrufHerkunftNachrichten = [];
  anrufHerkunftDom.window.__MAGNOLIE_BRUECKE__ = "call_origin_bridge";
  anrufHerkunftDom.window.webkit = { messageHandlers: { call_origin_bridge: {
    postMessage: (text) => anrufHerkunftNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(anrufHerkunftDom.window, "de");
  const herkunftW = anrufHerkunftDom.window;
  const herkunftD = herkunftW.document;
  const herkunftDaten = herkunftW.OrganizerTest.leereDaten();
  herkunftDaten.einstellungen.adressen.kommunikation.anruf = { art: "magnolie", programm: "",
    eingehendBenachrichtigen: true, computerTelefonie: true, klingeltonLeiser: false };
  herkunftW.App.init({ daten: herkunftDaten, neu: false, regional: { language: "de" } });
  const notizenVorher = herkunftW.OrganizerTest.daten().notizen.length;
  const herkunftPeer = { device_id: "telefon-herkunft", display_name: "Telefon",
    state: "online_wifi", capabilities: { items: {
      incoming_call_state: { available: true, versions: [2] },
      answer_call: { available: true, versions: [1] }, end_call: { available: true, versions: [1] } } },
    grants: { grants: { answer_call: true, end_call: true } },
    local_grants: { grants: { incoming_call_state: true, answer_call: true, end_call: true } } };
  herkunftW.App.telefonStand({ peers: [herkunftPeer] });
  const callEvent = (state, origin, revision, times = {}) => Object.assign({
    device_id: "telefon-herkunft", call_ref: "123e4567-e89b-42d3-a456-426614174010",
    revision: revision, state: state, direction: "incoming", control_origin: origin,
    number: "", number_status: "withheld", started_ms: 1_000, offhook_ms: 0, ended_ms: 0,
    occurred_ms: 1_000 + revision, spam_status: "unknown", battery_percent: -1,
    battery_captured_ms: 0 }, times);
  herkunftW.App.telefonEingehenderAnruf(callEvent("ringing", "unknown", 1));
  const nachKlingeln = anrufHerkunftNachrichten.length;
  herkunftW.App.telefonEingehenderAnruf(callEvent("offhook", "phone", 2, { offhook_ms: 1_002 }));
  assert.strictEqual(herkunftD.querySelector("#anruf-schleier"), null,
    "lokal angenommener eingehender Call oeffnet den persistenten Dialog");
  assert.ok(anrufHerkunftNachrichten.slice(nachKlingeln).every((nachricht) =>
    nachricht.cmd !== "telefon_anruf_anzeigen"),
  "lokal angenommener Call fordert ein natives Anzeigen oder Vorholen an");
  assert.ok(anrufHerkunftNachrichten.slice(nachKlingeln).some((nachricht) =>
    nachricht.cmd === "telefon_anruf_lautstaerke_wiederherstellen"),
  "lokal angenommener Call stellt eine abgesenkte Lautstaerke nicht wieder her");
  herkunftW.App.telefonEingehenderAnruf(callEvent("idle", "phone", 3,
    { offhook_ms: 1_002, ended_ms: 1_003 }));
  assert.strictEqual(herkunftW.OrganizerTest.daten().notizen.length, notizenVorher,
    "finales idle eines Telefon-Calls legt eine Notizsitzung an");
  herkunftW.App.telefonEingehenderAnruf(callEvent("ringing", "unknown", 4));
  herkunftW.App.telefonEingehenderAnruf(callEvent("offhook", "desktop", 5, { offhook_ms: 1_005 }));
  assert.ok(herkunftD.querySelector("#anruf-schleier .anruf-auflegen"),
    "per Desktop angenommener Call oeffnet Dialog und Auflegekontrolle nicht");
  herkunftW.App.telefonEingehenderAnruf(callEvent("idle", "desktop", 6,
    { offhook_ms: 1_005, ended_ms: 1_006 }));
  anrufHerkunftDom.window.close();

  const direktDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://direct-call.test/", pretendToBeVisual: true });
  const direktNachrichten = [];
  direktDom.window.__MAGNOLIE_BRUECKE__ = "direct_call_bridge";
  direktDom.window.webkit = { messageHandlers: { direct_call_bridge: {
    postMessage: (text) => direktNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(direktDom.window, "de");
  const direktW = direktDom.window; const direktD = direktW.document;
  const direktT = direktW.OrganizerTest; const direktDaten = direktT.leereDaten();
  direktDaten.kontakte = [{ id: "direkt-kontakt", uid: "direkt-kontakt", vorname: "Ada",
    nachname: "Lovelace", foto: "data:image/png;base64,iVBORw0KGgo=",
    telefone: [{ wert: "+491701234567", typen: ["CELL"] }] }];
  direktDaten.einstellungen.adressen.kommunikation.anruf = { art: "magnolie", programm: "",
    hfpAdresse: "AA:BB:CC:DD:EE:FF", eingehendBenachrichtigen: false,
    computerTelefonie: false, klingeltonLeiser: false };
  direktW.App.init({ daten: direktDaten, neu: false, regional: { language: "de" } });
  const direktPeer = { device_id: "direkt-telefon", display_name: "Direkt-Telefon", state: "online_wifi",
    capabilities: { items: { dial_request: { available: true, versions: [1] },
      incoming_call_state: { available: true, versions: [2] }, end_call: { available: true, versions: [1] } } },
    grants: { grants: { dial_request: true, incoming_call_state: true, end_call: true } },
    local_grants: { grants: { incoming_call_state: true, end_call: true } } };
  direktW.App.telefonStand({ peers: [direktPeer] });
  direktT.zustand().adressen.auswahlId = "direkt-kontakt"; direktT.wechsel("adressen");
  direktD.querySelector(".kontakt-anruf").click();
  const waehlen = direktNachrichten.find((nachricht) => nachricht.cmd === "telefon_waehlen");
  assert.ok(waehlen && uuidV4.test(waehlen.clientRef) && waehlen.kennung === "direkt-telefon" &&
    waehlen.hfpAdresse === "AA:BB:CC:DD:EE:FF",
  "direkter Anruf übergibt client_ref, Telefonbindung oder unabhängige HFP-Adresse nicht");
  let auflegen = direktD.querySelector("#anruf-schleier .anruf-auflegen");
  const pendingStatus = direktD.querySelector(".anruf-status").textContent;
  assert.ok(auflegen && auflegen.disabled && pendingStatus.trim(),
    "ausstehender Wählauftrag erklärt oder sperrt das Auflegen nicht");
  const kopfName = direktD.querySelector("#anruf-schleier h2").textContent;
  assert.ok(!direktD.querySelector("#anruf-schleier").textContent.includes("[object HTML") &&
    kopfName.includes("Ada") && kopfName.includes("Lovelace"),
    "Anrufkopf enthält keinen echten h2-Namen oder serialisiert einen DOM-Knoten");
  const direktEvent = (ref, revision) => ({ device_id: "direkt-telefon", call_ref: ref,
    revision: revision, state: "offhook", direction: "outgoing", control_origin: "desktop",
    number: "+491701234567", number_status: "available", started_ms: Date.now() - 4_000,
    offhook_ms: Date.now() - 2_500, ended_ms: 0, occurred_ms: Date.now(), spam_status: "unknown",
    battery_percent: -1, battery_captured_ms: 0 });
  direktW.App.telefonEingehenderAnruf(direktEvent(waehlen.clientRef, 0));
  assert.ok(direktD.querySelector(".anruf-auflegen").disabled,
    "synthetische Revision 0 aktiviert das Auflegen");
  direktW.App.telefonEingehenderAnruf(direktEvent("123e4567-e89b-42d3-a456-426614174099", 1));
  assert.ok(direktD.querySelector(".anruf-auflegen").disabled,
    "fremde call_ref übernimmt den ausstehenden Anruf");
  direktW.App.telefonEingehenderAnruf(direktEvent(waehlen.clientRef, 1));
  auflegen = direktD.querySelector(".anruf-auflegen");
  assert.ok(!auflegen.disabled && direktD.querySelector(".anruf-status").textContent !== pendingStatus &&
    direktD.querySelector(".anruf-dauer").textContent !== "00:00:00",
    "echter Offhook-Zustand aktualisiert Status, Timer oder Auflegefreigabe nicht");
  auflegen.click(); auflegen.click();
  assert.strictEqual(direktNachrichten.filter((nachricht) => nachricht.cmd === "telefon_auflegen").length, 1,
    "Auflegeknopf sendet den destruktiven Befehl mehrfach");
  assert.match(css, /\.anruf-auflegen:disabled\s*\{[^}]*opacity:[^}]*cursor:\s*not-allowed[^}]*filter:/s,
    "deaktiviertes Auflegen ist optisch nicht eindeutig deaktiviert");
  direktW.App.telefonEingehenderAnruf(Object.assign(direktEvent(waehlen.clientRef, 2), {
    state: "idle", ended_ms: Date.now() }));
  direktW.App.telefonEingehenderAnruf(Object.assign(direktEvent(
    "123e4567-e89b-42d3-a456-426614174098", 1), { direction: "incoming", control_origin: "phone" }));
  assert.strictEqual(direktD.querySelector("#anruf-schleier"), null,
    "eingehender Telefon-Call öffnet bei deaktivierter PC-Telefonie einen Dialog");
  const anrufMeldungDaten = direktT.leereDaten();
  anrufMeldungDaten.kontakte = [{ id: "anruf-meldung", uid: "anruf-meldung", vorname: "Ada",
    nachname: "Lovelace", foto: "data:image/png;base64,iVBORw0KGgo=",
    telefone: [{ wert: "+491701234567", typen: ["CELL"] }] }];
  anrufMeldungDaten.einstellungen.erinnerung.stil = "magnolie";
  anrufMeldungDaten.einstellungen.adressen.kommunikation.anruf = { art: "magnolie", programm: "",
    eingehendBenachrichtigen: true, computerTelefonie: false, klingeltonLeiser: false };
  direktW.App.init({ daten: anrufMeldungDaten, neu: false, regional: { language: "de" } });
  direktW.App.telefonStand({ peers: [direktPeer] });
  direktW.App.telefonEingehenderAnruf(Object.assign(direktEvent(
    "123e4567-e89b-42d3-a456-426614174097", 1), { direction: "incoming", state: "ringing",
    control_origin: "unknown" }));
  const anrufMeldung = direktNachrichten.filter((nachricht) =>
    nachricht.cmd === "telefon_anruf_anzeigen").at(-1);
  assert.ok(anrufMeldung && anrufMeldung.stil === "magnolie" && anrufMeldung.dauer === 60 &&
    anrufMeldung.foto === "data:image/png;base64,iVBORw0KGgo=",
  "eingehender Anruf übergibt Stil, 60 Sekunden und das eindeutige sichere Kontaktfoto nicht");
  direktDom.window.close();

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "0175 222222", typen: ["MOBILE", "HOME"] },
    { wert: "0176 333333", typen: ["CELL", "WORK"] }
  ], [], { peers: [] });
  kontaktKarte.querySelector(".kontakt-sms").click();
  eigenerSmsDialog = kontaktD.querySelector(".sms-dialog");
  assert.deepStrictEqual(Array.from(eigenerSmsDialog.querySelectorAll(".sms-nummer option"),
    (option) => option.value), ["0175 222222", "0176 333333"],
  "mehrere Mobilnummern stehen nicht im eigenen SMS-Editor zur Auswahl");
  eigenerSmsDialog.querySelector(".sms-schliessen").click();

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "+49 177 333333", typen: ["CELL"] }
  ], [], { peers: [], kdeconnect: { available: false, paired: 1, device_count: 0 } });
  kontaktKarte.querySelector(".kontakt-sms").click();
  const offlineKdeDialog = kontaktD.querySelector(".sms-dialog");
  assert.deepStrictEqual(Array.from(offlineKdeDialog.querySelectorAll("select:not(.sms-nummer) option"),
    (option) => option.value), ["kde"],
  "eine gespeicherte KDE-Kopplung erscheint nicht als einziger eigener Versandweg");
  assert.ok(offlineKdeDialog.textContent.includes("KDE Connect") &&
    offlineKdeDialog.textContent.includes("Offline"),
  "eine offline KDE-Kopplung wird nicht verständlich gekennzeichnet");
  offlineKdeDialog.querySelector(".sms-schliessen").click();

  kontaktKarte = zeichneKontaktAktionen([
    { wert: "+49 177 444444", typen: ["CELL"] }
  ], [], { peers: [], kdeconnect: { available: true, device_count: 1 } });
  kontaktKarte.querySelector(".kontakt-sms").click();
  const kdeDialog = kontaktD.querySelector(".sms-dialog");
  assert.ok(kdeDialog && kdeDialog.textContent.includes("KDE Connect"),
    "ein eindeutiges KDE-Gerät öffnet keinen SMS-Textdialog");
  const smsKopfknopf = kdeDialog.querySelector("button.sms-praegung");
  assert.ok(smsKopfknopf && smsKopfknopf.getAttribute("aria-label"),
    "das sichtbare Wort SMS ist kein zugänglicher Einstellungsbutton");
  smsKopfknopf.click();
  const smsEinstellungen = kontaktD.querySelector(".sms-einstellungen-dialog");
  assert.ok(smsEinstellungen && smsEinstellungen.textContent.includes("Alle SMS-Verläufe löschen"),
    "der SMS-Kopfbutton öffnet nicht die kompakten Verlaufseinstellungen");
  assert.ok(smsKopfknopf.textContent.includes("SMS-Einstellungen"),
    "der SMS-Kopfknopf erklärt seine Einstellungsfunktion nicht sichtbar");
  Array.from(smsEinstellungen.querySelectorAll("button"))
    .find((button) => button.textContent === "Alle SMS-Verläufe löschen").click();
  assert.ok(!kontaktD.querySelector("#dialog-schleier").classList.contains("verborgen") &&
    /#dialog-schleier\s*\{\s*z-index:\s*180/.test(css),
  "die Löschbestätigung bleibt unter den SMS-Einstellungen verborgen");
  kontaktD.querySelector("#dialog-nein").click();
  smsEinstellungen.querySelector("select").value = "120";
  smsEinstellungen.querySelector("select").dispatchEvent(new kontaktW.Event("change"));
  assert.strictEqual(kontaktT.daten().einstellungen.adressen.smsBenachrichtigungDauer, 120,
    "die SMS-Ausblenddauer wird nicht strikt unter Adressen gespeichert");
  smsEinstellungen.querySelector(".dialog-knoepfe button").click();
  setze(kdeDialog.querySelector("textarea"), "KDE Test");
  Array.from(kdeDialog.querySelectorAll("button"))
    .find((button) => button.textContent === "SMS senden").click();
  const kdeBefehl = kontaktAktionenNachrichten.find((nachricht) =>
    nachricht.cmd === "kde_sms_senden" && nachricht.nummer === "+49 177 444444" &&
    nachricht.text === "KDE Test");
  assert.ok(kdeBefehl && kdeBefehl.clientRef,
  "KDE-SMS wird nicht mit ausgewählter Nummer und Text an die native Bridge übergeben");
  assert.ok(kdeDialog.querySelector(".sms-kopf .kontakt-foto,.sms-kopf .sms-initialen") &&
    kdeDialog.querySelector(".sms-verlauf") && kdeDialog.querySelector(".sms-komponist textarea") &&
    kdeDialog.querySelector(".sms-komponist button"),
  "interner SMS-Dialog besitzt nicht die Messenger-Struktur mit Kopf, Verlauf und Komponist");
  assert.strictEqual(kontaktT.daten().smsVerlauf.at(-1).status, "queued",
    "ausgehende SMS wird nicht sofort queued persistiert");
  assert.ok(kdeDialog.querySelector(".sms-tag") && kdeDialog.querySelector(".sms-nachricht.ausgang"),
    "SMS-Verlauf zeigt keinen Tagestrenner oder keine ausgehende Blase");
  kontaktW.App.kdeSmsStatus({ ok: true, state: "queued", client_ref: kdeBefehl.clientRef });
  assert.strictEqual(kontaktT.daten().smsVerlauf.at(-1).status, "queued",
    "lokale KDE-Warteschlange wird fälschlich als Versandbestätigung persistiert");
  assert.strictEqual(kdeDialog.querySelector("textarea").value, "",
    "Text wird nach erfolgreicher lokaler Einreihung nicht geleert");
  assert.ok(!kdeDialog.querySelector(".sms-komponist button").disabled,
    "Komponist bleibt nach erfolgreicher lokaler Einreihung gesperrt");
  const blase = kdeDialog.querySelector(".sms-blase");
  blase.dispatchEvent(new kontaktW.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
  const detail = kontaktD.querySelector(".sms-detail-dialog");
  assert.ok(detail && detail.querySelector(".sms-detail-text").textContent === "KDE Test" &&
    detail.textContent.includes("KDE Connect") && detail.querySelector(".sms-detail-liste"),
  "Rechtsklick auf SMS-Blase zeigt keine sicheren vollständigen Details");
  const statusZeichen = kdeDialog.querySelector(".sms-status.queued");
  assert.ok(statusZeichen && statusZeichen.textContent === "◷" && statusZeichen.title &&
    statusZeichen.getAttribute("aria-label") === statusZeichen.title,
  "lokal eingereihter SMS-Status besitzt keine ehrliche sichtbare und zugängliche Legende");
  detail.querySelector(".dialog-knoepfe button").click();
  kontaktW.App.telefonSmsEmpfangen({ device_id: "telefon-1", sms_id: "eingang-1",
    from: "+49 177 444444", text: "Antwort", timestamp_ms: Date.now(), notify: true });
  kontaktW.App.telefonSmsEmpfangen({ device_id: "telefon-1", sms_id: "eingang-1",
    from: "+49 177 444444", text: "Antwort", timestamp_ms: Date.now() });
  assert.strictEqual(kontaktT.daten().smsVerlauf.filter((x) =>
    x.id === "kde:telefon-1::eingang-1").length, 1,
  "eingehende SMS wird nicht mit Geräte- und SMS-Kennung dedupliziert");
  assert.ok(kdeDialog.querySelector(".sms-nachricht.eingang") &&
    kontaktAktionenNachrichten.some((x) => x.cmd === "telefon_sms_benachrichtigen"),
  "eingehende SMS aktualisiert den offenen Chat oder die bestehende Benachrichtigung nicht");
  kontaktW.App.telefonSmsEmpfangen({ device_id: "telefon-1", sms_id: "ausgang-1",
    from: "+49 177 444444", text: "Vom Telefon", timestamp_ms: Date.now(),
    incoming: false, notify: true });
  assert.ok(kontaktT.daten().smsVerlauf.some((x) => x.text === "Vom Telefon" &&
    x.richtung === "ausgang" && x.status === "sent"),
  "ausgehende KDE-Historie wird nicht rechts als gesendet importiert");
  kdeDialog.querySelector(".sms-schliessen").click();
  kontaktW.App.telefonAntwort({ nummer: "+49 170 9999999" });
  const unbekanntDialog = kontaktD.querySelector(".sms-dialog");
  assert.ok(unbekanntDialog && unbekanntDialog.textContent.includes("+49 170 9999999"),
    "eine unbekannte Nummer öffnet keinen antwortbaren nummernbasierten KDE-Chat");
  unbekanntDialog.querySelector(".sms-schliessen").click();

  kontaktKarte = zeichneKontaktAktionen([{ wert: "0178 555555", typen: ["CELL"] }]);
  kontaktKarte.querySelector(".kontakt-sms").dispatchEvent(
    new kontaktW.Event("contextmenu", { bubbles: true, cancelable: true }));
  const belegung = kontaktD.querySelector(".kommunikation-belegung-dialog");
  belegung.querySelector('[value="system"]').click();
  Array.from(belegung.querySelectorAll("button")).find((x) => x.textContent === "Speichern").click();
  kontaktD.querySelector(".kontakt-sms").click();
  assert.ok(kontaktAktionenNachrichten.some((nachricht) => nachricht.cmd === "sozial" &&
    nachricht.dienst === "sms" && nachricht.wert === "0178 555555" && !nachricht.aktionArt),
  "Systembelegung leitet Linksklick nicht ohne Custom-Ziel an die sichere Sozial-Bridge");
  kontaktKarte.querySelector(".kontakt-anruf").dispatchEvent(
    new kontaktW.Event("contextmenu", { bubbles: true, cancelable: true }));
  const anrufBelegung = kontaktD.querySelector(".kommunikation-belegung-dialog");
  const hfpAuswahl = anrufBelegung.querySelector(".kommunikation-hfp-auswahl");
  assert.ok(hfpAuswahl && Array.from(hfpAuswahl.options).some((option) =>
    option.value === "AA:BB:CC:DD:EE:FF" && option.textContent === "Mobiltelefon HFP"),
  "Anrufzuweisung bietet die systemgekoppelten Bluetooth-HFP-Geräte nicht an");
  const anrufBelegungText = anrufBelegung.textContent;
  assert.ok(anrufBelegungText.includes("Programmbefehl") &&
    anrufBelegungText.includes("Der Befehl wird sicher ohne Shell gestartet.") &&
    anrufBelegungText.includes("Über eingehende Anrufe benachrichtigen") &&
    anrufBelegungText.includes("Anrufe am Computer annehmen und sprechen") &&
    anrufBelegungText.includes("Andere Töne während des Klingelns leiser stellen") &&
    anrufBelegungText.includes("entsprechenden Berechtigungen in Magnolie Notes") &&
    !/Application command|Notify me|Answer calls|Lower other sounds|matching permissions/.test(
      anrufBelegungText),
  "deutscher Anruf-Belegungsdialog enthält englische Beschriftungen oder Hilfen");
  const standardKnopf = Array.from(anrufBelegung.querySelectorAll("button")).find(
    (x) => x.textContent === "Voreinstellungen wiederherstellen");
  const anrufOptionen = Array.from(anrufBelegung.querySelectorAll(
    ".kommunikation-anruf-optionen input[type=checkbox]"));
  anrufBelegung.querySelector('[value="program"]').click();
  anrufBelegung.querySelector('input[type="text"]').value = "dialer {nummer}";
  for (const feld of anrufOptionen) feld.checked = true;
  hfpAuswahl.value = "AA:BB:CC:DD:EE:FF";
  standardKnopf.click();
  assert.ok(standardKnopf && anrufBelegung.querySelector('[value="magnolie"]').checked &&
    !anrufBelegung.querySelector('input[type="text"]').value &&
    anrufOptionen.every((feld) => !feld.checked) && !hfpAuswahl.value,
  "Voreinstellungen stellen nicht die vollständige Anrufbelegung wieder her");
  hfpAuswahl.value = "AA:BB:CC:DD:EE:FF";
  Array.from(anrufBelegung.querySelectorAll("button")).find((x) => x.textContent === "Speichern").click();
  assert.strictEqual(kontaktT.daten().einstellungen.adressen.kommunikation.anruf.hfpAdresse,
    "AA:BB:CC:DD:EE:FF", "HFP-Auswahl wird nicht unabhängig gespeichert");
  kontaktKarte.querySelector(".kontakt-anruf").dispatchEvent(
    new kontaktW.Event("contextmenu", { bubbles: true, cancelable: true }));
  const programmBelegung = kontaktD.querySelector(".kommunikation-belegung-dialog");
  programmBelegung.querySelector('[value="program"]').click();
  programmBelegung.querySelector('input[type="text"]').value = "dialer --number {nummer}";
  Array.from(programmBelegung.querySelectorAll("button")).find((x) => x.textContent === "Speichern").click();
  kontaktD.querySelector(".kontakt-anruf").click();
  assert.ok(kontaktAktionenNachrichten.some((nachricht) => nachricht.cmd === "sozial" &&
    nachricht.dienst === "phone" && nachricht.aktionArt === "program" &&
    nachricht.aktionZiel === "dialer --number {nummer}"),
  "eigene Anrufbelegung erreicht die sichere program-Implementierung nicht");
  assert.ok(!programmBelegung || !programmBelegung.querySelector('[value="kde"]'),
    "KDE erscheint unzulässig als Anrufweg");
  assert.ok(!kontaktD.body.textContent.includes("Valent"),
    "Kontaktaktion oder Hilfetext nennt weiterhin Valent");
  kontaktAktionenDom.window.close();

  const geraetDom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://device.test/", pretendToBeVisual: true });
  const geraetNachrichten = [];
  geraetDom.window.__MAGNOLIE_BRUECKE__ = "device_bridge";
  Object.defineProperty(geraetDom.window, "crypto", { value: require("crypto").webcrypto });
  geraetDom.window.webkit = { messageHandlers: { device_bridge: {
    postMessage: (text) => geraetNachrichten.push(JSON.parse(text))
  } } };
  ladeAnwendung(geraetDom.window, "de");
  const geraetW = geraetDom.window, geraetD = geraetW.document;
  geraetW.App.init({ daten: {}, neu: false, regional: { language: "de" } });
  const personalPeer = { device_id: "partner-intern-1", own_device: false,
    remote_own_device: false, auto_wifi: false, transport: "wifi",
    local_grants: { grants: { personal_notes_sync: false, personal_tasks_sync: false } },
    grants: { grants: { personal_notes_sync: false, personal_tasks_sync: false } } };
  geraetW.App.telefonStand({ peers: [personalPeer] });
  geraetW.App.geraetOeffnen({ kennung: "partner-intern-1", name: "Annas Telefon",
    status: {} });
  assert.strictEqual(geraetD.querySelector("#geraet-titel").textContent,
    "Magnolie Notes-Gerätestatus");
  assert.ok(geraetD.querySelector("#geraet-dialog").textContent.includes(
    "Dieser Status stammt aus Magnolie Notes, nicht aus KDE Connect."));
  assert.ok(!geraetD.querySelector("#geraet-dialog").textContent.includes("partner-intern-1") &&
    geraetD.querySelector(".geraet-telefon") && geraetD.querySelector(".geraet-akku"),
  "Gerätedialog zeigt keine Partnerkennung und besitzt Telefon- und Akkusilhouette");
  geraetW.App.geraetStatus({ kennung: "partner-intern-1", status: {
    request_id: "4ae28097-1229-4e22-b3de-a86af0491f35",
    model: "Pixel 9a", manufacturer: "Google", os_name: "Android",
    os_version: "16", app_version: "1.0.7", battery_percent: 73, charging: "charging", online: true,
    battery_temperature_deci_c: 339, power_source: "none", network_transport: "wifi",
    uptime_ms: 1311966668,
    last_contact_ms: 1786617000000, captured_ms: 1786617000000 } });
  assert.ok(geraetD.querySelector("#geraet-dialog").textContent.includes("Pixel 9a") &&
    geraetD.querySelector("#geraet-dialog").textContent.includes("73 %") &&
    geraetD.querySelector("#geraet-dialog").textContent.includes("1.0.7") &&
    geraetD.querySelector("#geraet-dialog").textContent.includes("WLAN") &&
    !geraetD.querySelector("#geraet-dialog").textContent.includes("339") &&
    geraetD.querySelector(".geraet-online").classList.contains("online"),
  "eine Statusantwort aktualisiert oder formatiert den Gerätedialog nicht korrekt");
  Array.from(geraetD.querySelectorAll("#geraet-dialog button"))
    .find((button) => button.textContent === "Aktualisieren").click();
  assert.ok(geraetNachrichten.some((nachricht) =>
    nachricht.cmd === "telefon_status_anfordern" &&
    nachricht.kennung === "partner-intern-1"),
  "Aktualisieren fordert den Status über die native Bridge erneut an");
  assert.ok(!geraetD.querySelector("#geraet-dialog").textContent.match(
    /IMEI|Seriennummer|Telefonnummer|IP|MAC|SSID/i),
  "der Gerätedialog enthält keine verbotenen Identifikatoren oder Netzdaten");
  const personalHaken = Array.from(geraetD.querySelectorAll(".telefon-freigaben input"));
  const personalBereich = geraetD.querySelector("details.telefon-personal-sync");
  assert.ok(personalBereich && !personalBereich.open && personalBereich.querySelector("summary"),
    "persönliche Synchronisierung ist nicht standardmäßig eingeklappt");
  personalHaken.at(-4).click();
  personalHaken.at(-3).click();
  const wartenderPersonalStand = geraetD.querySelector("[data-personal-sync-peer]").textContent;
  assert.ok(wartenderPersonalStand,
    "lokale Personal-Sync-Freigabe zeigt nicht den ausstehenden Fernstand");
  geraetW.App.telefonStand({ peers: [{ ...personalPeer, own_device: true,
    remote_own_device: true, local_grants: { grants: { personal_notes_sync: true,
      personal_tasks_sync: false } }, grants: { grants: { personal_notes_sync: true,
      personal_tasks_sync: false } } }] });
  assert.notStrictEqual(geraetD.querySelector("[data-personal-sync-peer]").textContent,
    wartenderPersonalStand,
    "aktueller Peer-Stand aktualisiert den offenen Personal-Sync-Dialog nicht");
  const geraetFuss = geraetD.querySelector(".geraet-dialog-knoepfe");
  assert.ok(geraetFuss && geraetD.querySelector(".geraet-dialog-inhalt"),
    "Geräteinhalt und dauerhaft sichtbare Aktionsleiste sind nicht getrennt");
  Array.from(geraetFuss.querySelectorAll("button"))
    .find((button) => button.textContent === "Jetzt synchronisieren").click();
  await Promise.resolve();
  assert.ok(geraetNachrichten.some((nachricht) =>
    (nachricht.cmd === "personal_sync_senden" && nachricht.art === "personal_sync.request") ||
    (nachricht.cmd === "personal_sync_lauf_senden" && nachricht.request && nachricht.request.format === 2)),
  "Sync jetzt verwendet trotz aktuellem Peer-Stand weiterhin die veraltete Dialogfreigabe");
  geraetW.App.geraetStatus({ kennung: "partner-intern-1", status: { online: false } });
  assert.ok(geraetD.querySelector(".geraet-details").classList.contains("verborgen") &&
    geraetD.querySelector("#geraet-dialog").textContent.includes("Offline"),
  "offline zeigt der Magnolie-Notes-Gerätestatus weiterhin die lange Leertabelle");

  const personalT = geraetW.OrganizerTest, contract = JSON.parse(fs.readFileSync(
    path.join(__dirname, "personal-sync-contract.json"), "utf8"));
  const autoBasis = { secureWifi: true, secureWifiTransition: true, autoWifi: true,
    ownDevice: true, remoteOwnDevice: true, bilateralGrant: true, active: false,
    nowMs: 1_000_000, lastAutoMs: 940_000, remoteUnknown: false, localDirty: false };
  assert.ok(personalT.personalSyncAutoEntscheidung({ ...autoBasis, localDirty: true }),
    "lokal geaendert nach Abwesenheit startet nicht sofort im sicheren WLAN");
  assert.ok(!personalT.personalSyncAutoEntscheidung(autoBasis),
    "unveraenderter Reconnect innerhalb 15 Minuten wiederholt Auto-Sync");
  assert.ok(personalT.personalSyncAutoEntscheidung({ ...autoBasis, lastAutoMs: 100_000 }),
    "unveraenderter Reconnect nach 15 Minuten zieht keine entfernten Aenderungen");
  assert.ok(!personalT.personalSyncAutoEntscheidung({ ...autoBasis, secureWifi: false,
    localDirty: true }), "Bluetooth oder ein unsicherer Transport startet Auto-Sync");
  assert.ok(personalT.personalSyncAutoEntscheidung({ ...autoBasis, lastAutoMs: 0,
    remoteUnknown: true }), "spaeter authentisierter Organizer im selben WLAN startet nicht");
  for (const sperre of [{ active: true }, { ownDevice: false }, { remoteOwnDevice: false },
      { bilateralGrant: false }, { secureWifiTransition: false }])
    assert.ok(!personalT.personalSyncAutoEntscheidung({ ...autoBasis, ...sperre, localDirty: true }),
      "Auto-Sync ignoriert Sitzungs-, Grant- oder Anti-Loop-Sperre");
  assert.strictEqual(personalT.personalSyncKanonisch(contract.unicode_order.value),
    contract.unicode_order.canonical, "Personal-Sync sortiert Unicode nicht binär nach UTF-8");
  const daten = personalT.daten();
  daten.notizbuecher = [{ id: "book-1", gruppeId: daten.notizgruppen[0].id, name: "Buch" }];
  daten.notizen = [{ id: "own", titel: "Own", text: "", html: "", notizbuchId: "book-1",
    symbol: "idee", angelegt: 11, personalGeaendert: 12, geaendert: "2026-08-14", anhaenge: [],
    baumQuelle: "", baumVersion: 0 }, { id: "foreign", titel: "Foreign", text: "", html: "",
    notizbuchId: "book-1", symbol: "notiz", angelegt: 1, personalGeaendert: 2,
    anhaenge: [], baumQuelle: "zweig" }];
  daten.aufgaben = [{ id: "task-own", titel: "Own", notiz: "", faellig: "", prio: 2,
    erledigt: false, erinnern: true, vorlaufTage: 0, individuelleErinnerungTage: 3,
    erinnerungsMinute: 777, angelegt: 21,
    personalGeaendert: 22, personen: ["p"], kontaktId: "k", vonTermin: "cal", herkunft: "",
    vonZweig: "", fremdId: "", delegiertAn: "" }, { id: "task-foreign", titel: "Foreign",
    herkunft: "zweig", vonZweig: "", fremdId: "", delegiertAn: "" }];
  daten.personalSync = { format: 1, actor_id: "11111111-1111-4111-8111-111111111111",
    counter: 0, entities: {}, last_reports: [], applied_batches: [] };
  const entscheidungsUhr = [{ actor_id: "11111111-1111-4111-8111-111111111111", counter: 4 }];
  daten.personalSync.entities = {
    "note\u0000atomic-a": { proposal_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      clock: entscheidungsUhr, status: "pending" },
    "note\u0000atomic-b": { proposal_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      clock: entscheidungsUhr, status: "pending" }
  };
  daten.personalSync.applied_decisions = [];
  const atomar = [{ proposal_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", decision: "delete",
    expected_clock: entscheidungsUhr }, { proposal_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    decision: "delete", expected_clock: [{ ...entscheidungsUhr[0], counter: 5 }] }];
  assert.strictEqual(personalT.personalSyncEingehendeEntscheidungen(atomar), "conflict");
  assert.deepStrictEqual(Object.values(daten.personalSync.entities).map((x) => x.status), ["pending", "pending"],
    "mehrere Loeschentscheidungen werden vor exakter Clock-Pruefung teilweise angewendet");
  atomar[1].expected_clock = entscheidungsUhr;
  assert.strictEqual(personalT.personalSyncEingehendeEntscheidungen(atomar), "applied");
  const proofCount = daten.personalSync.applied_decisions.length;
  atomar[0].expected_clock = [{ ...entscheidungsUhr[0], counter: 9 }];
  assert.strictEqual(personalT.personalSyncEingehendeEntscheidungen(atomar), "conflict");
  assert.strictEqual(daten.personalSync.applied_decisions.length, proofCount,
    "veraenderter Replay wird als bereits angewendet akzeptiert");
  atomar[0].expected_clock = entscheidungsUhr; atomar[0].decision = "restore";
  assert.strictEqual(personalT.personalSyncEingehendeEntscheidungen(atomar), "conflict",
    "entgegengesetzte Entscheidung wird als idempotenter Replay akzeptiert");
  daten.personalSync.entities = {}; daten.personalSync.applied_decisions = [];
  const legacyProofData = personalT.normalisiere({ ...daten, personalSync: {
    ...daten.personalSync, applied_decisions: ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:delete"] } });
  assert.deepStrictEqual(legacyProofData.personalSync.applied_decisions, [],
    "altes unvollstaendiges Loesch-Proof wird nicht fail-closed verworfen");
  const projection = await personalT.personalSyncSnapshot(["notes", "tasks"]);
  assert.ok(projection.some((x) => x.id === "own") && projection.some((x) => x.id === "task-own") &&
    !projection.some((x) => x.id === "foreign" || x.id === "task-foreign"),
  "Personal-Sync-Projektion trennt fremde Baumdaten nicht fail-closed");
  assert.strictEqual(projection.find((x) => x.id === "task-own").value.lead_days, 3,
    "Personal Sync verwirft den im Aufgabenblatt gewählten Erinnerungsvorlauf");
  const begrenztePakete = personalT.personalSyncPakete([projection.find((x) => x.id === "own"),
    { ...projection.find((x) => x.id === "own"), id: "é".repeat(81) }],
    "11111111-1111-4111-8111-111111111111", false);
  assert.strictEqual(begrenztePakete.flat().length, 1);
  assert.strictEqual(begrenztePakete.oversizedSkipped, 1,
    "lokale UTF-8-Grenzverletzung verfälscht Sent-/Oversize-Bericht");
  const roundtrip = personalT.normalisiere(JSON.parse(JSON.stringify(daten)));
  assert.strictEqual(roundtrip.notizen[0].angelegt, 11);
  assert.strictEqual(roundtrip.notizen[0].symbol, "idee");
  assert.strictEqual(roundtrip.notizen[0].personalGeaendert, daten.notizen[0].personalGeaendert);
  assert.strictEqual(roundtrip.aufgaben[0].vorlaufTage, 0);
  assert.strictEqual(roundtrip.aufgaben[0].individuelleErinnerungTage, 3);
  assert.strictEqual(roundtrip.aufgaben[0].erinnerungsMinute, 777);
  assert.deepStrictEqual(roundtrip.aufgaben[0].personen, ["p"]);
  const ownRecord = projection.find((x) => x.kind === "note" && x.id === "own");
  const sameRecord = { ...ownRecord, clock: [{ actor_id:
    "22222222-2222-4222-8222-222222222222", counter: 1 }] };
  let applyResult = await personalT.personalSyncAnwenden([sameRecord]);
  assert.strictEqual(applyResult.conflicts, 0);
  assert.strictEqual(daten.notizen.filter((x) => x.id === "own").length, 1);
  assert.strictEqual(daten.personalSync.entities["note\u0000own"].clock.length, 2,
    "gleicher konkurrierender Inhalt vereinigt den Vektor nicht");
  const anhang = { id: "a", name: "a.png", art: "image", daten: "data:image/png;base64,AA==" };
  daten.notizen.find((x) => x.id === "own").anhaenge = [anhang];
  const andererWert = { ...ownRecord.value, title: "Remote conflict" };
  const andererHash = await personalT.personalSyncHash(andererWert);
  const konfliktRecord = { ...ownRecord, value: andererWert, hash: andererHash,
    modified_ms: andererWert.modified_ms, clock: [{ actor_id:
      "33333333-3333-4333-8333-333333333333", counter: 1 }] };
  applyResult = await personalT.personalSyncAnwenden([konfliktRecord]);
  assert.strictEqual(applyResult.conflicts, 1);
  assert.strictEqual(daten.notizen.reduce((sum, x) => sum + (x.anhaenge || []).length, 0), 1,
    "Konflikt dupliziert oder verliert lokale Anhänge");
  const loeschNote = daten.notizen.find((x) => x.id === "own");
  const loeschMeta = daten.personalSync.entities["note\u0000own"];
  const vorschlag = { proposal_id: "44444444-4444-4444-8444-444444444444",
    kind: "note", id: "own", parent_id: "", clock: loeschMeta.clock,
    prior_hash: loeschMeta.hash, deleted_ms: Date.now(), label: "Own",
    run_id: "55555555-5555-4555-8555-555555555555", source_device: "peer" };
  daten.personalSync.pending_proposals = [vorschlag];
  const andereUhr = { ...vorschlag, clock: vorschlag.clock.map((x) => ({ ...x, counter: x.counter + 1 })) };
  assert.strictEqual(personalT.personalSyncEntscheidungAnwenden(andereUhr, "delete"), "conflict");
  assert.ok(daten.notizen.includes(loeschNote) && daten.personalSync.pending_proposals.length === 1,
    "gleicher Hash mit veraenderter Vektoruhr wird bestaetigt oder entfernt den offenen Vorschlag");
  assert.strictEqual(personalT.personalSyncEntscheidungAnwenden(vorschlag, "delete"), "applied");
  assert.ok(!daten.notizen.includes(loeschNote) && daten.papierkorb.some((x) =>
    x.art === "note" && x.eintrag.id === "own"),
  "bestätigte Personal-Löschung verschiebt den exakten Stand nicht in den Papierkorb");
  const loeschKorb = daten.papierkorb.find((x) => x.art === "note" && x.eintrag.id === "own");
  assert.ok(personalT.ausDemPapierkorb(loeschKorb));
  assert.strictEqual(daten.personalSync.entities["note\u0000own"].state, "live",
    "manuelle Papierkorb-Wiederherstellung lässt den Tombstone gesperrt");
  const anzahlNachKonflikt = daten.notizen.length;
  applyResult = await personalT.personalSyncAnwenden([konfliktRecord]);
  assert.strictEqual(daten.notizen.length, anzahlNachKonflikt,
    "wiederholter Konfliktaustausch legt weitere Kopien an");
  assert.strictEqual(applyResult.conflicts, 0);
  geraetD.querySelector("#telefon-pairing-dialog")?.remove();
  geraetW.App.telefonPairingCode({ attempt_id: "probe", code: "123 456",
    display_name: "Magnolie Notes", fingerprint: "AAAA-BBBB" });
  assert.ok(geraetD.querySelector("#telefon-pairing-dialog")?.textContent.includes("123 456"),
    "automatische Telefonpaarung zeigt ohne vorherigen Wartedialog keinen Code");
  geraetDom.window.close();

  /* ---- Suchen in allen sieben Karteien und am Heute-Knopf ---- */
  const suchDom = new JSDOM(html, { runScripts: "dangerously", url: "https://suche.test/",
    pretendToBeVisual: true });
  const suchW = suchDom.window, suchD = suchW.document;
  ladeAnwendung(suchW);
  await tick();
  const suchJahr = new Date().getFullYear();
  suchW.App.init({ daten: {
    termine: [{ id: "such-termin", titel: "Alpha Beratung", notiz: "vertrauliche Notiz",
      datum: suchJahr + "-06-12", endDatum: "", zeit: "09:30", endZeit: "10:30",
      kategorien: "Kunde", kunde: "Beta", kostenstelle: "K-17", kontaktId: "such-kontakt",
      wiederholung: { art: "weekly", bis: "" } },
      { id: "such-feiertag", titel: "Tag der Arbeit " + suchJahr, notiz: "",
        datum: suchJahr + "-05-01", zeit: "", endZeit: "", kategorien: "Public",
        sync: true, wiederholung: { art: "none", bis: "" } }],
    aufgaben: [{ id: "such-aufgabe", titel: "Gamma erledigen", notiz: "Delta Notiz",
      faellig: suchJahr + "-06-13", prio: 1, erledigt: false,
      personen: ["such-person"], kontaktId: "such-kontakt" },
      { id: "such-erledigt", titel: "Omega abgeschlossen", notiz: "",
        faellig: suchJahr + "-06-14", prio: 2, erledigt: true, personen: [] }],
    personen: [{ id: "such-person", name: "Erika Person" }],
    kontakte: [{ id: "such-kontakt", nachname: "Muster", vorname: "Mia",
      notiz: "Epsilon Kontaktvermerk", geburtstag: "1980-04-03" }],
    notizen: [{ id: "such-notiz", titel: "Zeta Blatt", text: "Eta Inhalt",
      notizbuchId: "notizbuch-lose-notizen", anhaenge: [] }],
    jahrestage: [{ id: "such-jt", name: "Theta Feier", datum: "2000-07-14",
      typ: "birthday", kontaktId: "such-kontakt" }],
    gesundheit: { vitalwerte: [{ id: "such-vital", datum: suchJahr + "-01-02",
      zeit: "08:00", puls: 71, temperatur: 36.5, notiz: "Iota lokal",
      seite: 987, interneKennung: "gesund-geheim" }], blutzucker: [],
      medikamente: [{ id: "such-medikament", name: "Wochenmittel", seite: 0,
        wochenplan: [{ tag: 1, morgens: "Nadelkern", mittags: "", abends: "", nachts: "" }] }],
      insulinschema: {} }
  }, neu: false, regional: { language: "de" } });
  const suchT = suchW.OrganizerTest;
  assert.ok(suchT.daten().termine.some((eintrag) => eintrag.id === "such-termin"),
    "Suchfixture verliert den Kalendertermin");
  assert.ok(suchT.suchTrefferFuer("kalender").some((eintrag) =>
    eintrag.text.includes("alpha") && eintrag.text.includes("k-17")),
  "Kalendersuchindex enthält Titel und Kostenstelle nicht");
  assert.ok(suchT.suchPasst(suchT.suchTrefferFuer("kalender")
    .find((eintrag) => eintrag.titel === "Alpha Beratung").text, "Alpha K-17"),
  "Mehrwort-UND-Vergleich passt nicht zum Kalenderindex");
  const offeneAufgabe = suchT.suchTrefferFuer("aufgaben")
    .find((eintrag) => eintrag.titel === "Gamma erledigen");
  const erledigteAufgabe = suchT.suchTrefferFuer("aufgaben")
    .find((eintrag) => eintrag.titel === "Omega abgeschlossen");
  assert.ok(offeneAufgabe.text.includes("13.06." + suchJahr) &&
    offeneAufgabe.text.includes("offen") && !offeneAufgabe.text.includes("erledigt"),
  "offene Aufgabe hat nicht Datum und tatsächlichen lokalisierten Status im Index");
  assert.ok(erledigteAufgabe.text.includes("erledigt") &&
    !erledigteAufgabe.text.includes("als erledigt"),
  "erledigte Aufgabe indiziert eine Aktion statt des Status");
  const gesundIndex = suchT.suchTrefferFuer("gesundheit")[0];
  assert.ok(gesundIndex.text.includes("02.01." + suchJahr) &&
    gesundIndex.text.includes("36,5") && gesundIndex.meta.includes("36,5"),
  "Gesundheit indiziert/zeigt lokalisierte Datums- und Dezimalwerte nicht: " +
    JSON.stringify({ text: gesundIndex.text, meta: gesundIndex.meta }));
  assert.ok(!gesundIndex.text.includes("gesund-geheim") && !gesundIndex.text.includes("987") &&
    !gesundIndex.text.includes("such-vital"),
  "Gesundheit indiziert interne Kennungen oder Seitennummern");
  suchT.zustand().gesundheit.ansicht = "medikamente";
  assert.ok(suchT.suchTrefferFuer("gesundheit").some((eintrag) =>
    eintrag.text.includes("nadelkern")),
  "abweichende Wochendosen eines Medikaments fehlen im Suchindex");
  suchT.zustand().gesundheit.ansicht = "vital";
  for (const gebiet of ["de-DE", "en-US", "fr-FR", "ar-EG"]) {
    const sprache = gebiet.slice(0, 2);
    if (sprache === "fr" || sprache === "ar") suchW.eval(
      fs.readFileSync(WEB + "/i18n/" + sprache + ".js", "utf8"));
    suchW.MagnolieI18n.setLocale(sprache);
    suchT.daten().einstellungen.regional.formatLocale = gebiet;
    const lokal = suchT.suchTrefferFuer("gesundheit")[0].text;
    const datum = new Intl.DateTimeFormat(gebiet,
      { day: "2-digit", month: "2-digit", year: "numeric" })
      .format(new Date(suchJahr, 0, 2)).toLocaleLowerCase(gebiet);
    const dezimal = new Intl.NumberFormat(gebiet, { maximumFractionDigits: 2 })
      .format(36.5).toLocaleLowerCase(gebiet);
    assert.ok(lokal.includes(datum) && lokal.includes(dezimal),
      "lokalisierter Suchindex fehlt für " + gebiet + ": " +
        JSON.stringify({ lokal: lokal, datum: datum, dezimal: dezimal,
          sprache: suchW.MagnolieI18n.locale() }));
  }
  suchW.MagnolieI18n.setLocale("de");
  suchT.daten().einstellungen.regional.formatLocale = "de-DE";
  const ctrlF = () => {
    const ereignis = new suchW.KeyboardEvent("keydown", { key: "f", ctrlKey: true,
      bubbles: true, cancelable: true });
    suchD.dispatchEvent(ereignis);
    assert.ok(ereignis.defaultPrevented, "Strg+F verhindert die Browser-Suche nicht");
    return ereignis;
  };
  const schliesseSuche = () => {
    suchD.dispatchEvent(new suchW.KeyboardEvent("keydown", { key: "Escape", bubbles: true,
      cancelable: true }));
  };
  for (const sektion of ["kalender", "aufgaben", "jahrestage", "planer", "gesundheit"]) {
    await suchT.wechsel(sektion);
    if (sektion === "kalender" || sektion === "planer") {
      const einstieg = suchD.querySelector(".kalender-suchknopf");
      assert.ok(einstieg && einstieg.querySelector("svg") && einstieg.title === "Suche",
        "sichtbare Suchlupe fehlt in " + sektion);
    }
    const rueckkehr = suchD.querySelector('.registerknopf[aria-current="page"]');
    rueckkehr.focus();
    ctrlF();
    await tick();
    const feld = suchD.querySelector("#globale-suche");
    assert.ok(feld && suchD.activeElement === feld, "Suchdialog fehlt für " + sektion);
    assert.strictEqual(suchD.querySelectorAll("#such-schleier").length, 1,
      "Suchdialog wurde mehrfach geöffnet");
    feld.value = sektion === "kalender" ? "Alpha K-17" : sektion === "aufgaben"
      ? "Gamma Erika" : sektion === "jahrestage" ? "Theta Muster"
        : sektion === "planer" ? "Alpha Beratung" : "Iota 71";
    feld.dispatchEvent(new suchW.Event("input", { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 180));
    assert.ok(suchD.querySelector(".such-treffer-knopf"),
      "Mehrwortsuche findet nichts in " + sektion);
    const suchWeiter = suchD.querySelector(".such-weiter");
    const suchZurueck = suchD.querySelector(".such-zurueck");
    assert.ok(suchWeiter && suchZurueck && !suchWeiter.disabled && !suchZurueck.disabled,
      "Treffernavigation fehlt in " + sektion);
    suchWeiter.click();
    assert.ok(suchD.activeElement.classList.contains("such-treffer-knopf") &&
      suchD.activeElement.classList.contains("aktiv") &&
      /^1 \/ /.test(suchD.querySelector(".such-position").textContent),
    "Nächster Treffer wird nicht fokussiert in " + sektion);
    suchZurueck.click();
    assert.ok(suchD.activeElement.classList.contains("aktiv"),
      "Vorheriger Treffer wird nicht fokussiert in " + sektion);
    ctrlF();
    assert.strictEqual(suchD.activeElement, feld, "Strg+F fokussiert offenen Suchdialog nicht");
    schliesseSuche();
    assert.ok(!suchD.querySelector("#such-schleier"), "Escape schließt Suche nicht");
    assert.strictEqual(suchD.activeElement, rueckkehr, "Fokus kehrt nach Suche nicht zurück");
    ctrlF();
    assert.strictEqual(suchD.querySelector("#globale-suche").value, feld.value,
      "Suchfeld wird beim Wiederöffnen geleert");
    schliesseSuche();
  }
  await suchT.wechsel("adressen");
  ctrlF();
  const kontaktSuche = suchD.querySelector("#kopf-links input[type=search]");
  assert.strictEqual(suchD.activeElement, kontaktSuche, "Kontaktsuche wird nicht fokussiert");
  kontaktSuche.value = "Epsilon 03.04.1980";
  kontaktSuche.dispatchEvent(new suchW.Event("input", { bubbles: true }));
  assert.ok(suchD.querySelector('[data-fokus="kontakt:such-kontakt"]'),
    "Kontakt-Notiz und Geburtstag sind nicht gemeinsam suchbar");
  await suchT.wechsel("notizen");
  ctrlF();
  assert.strictEqual(suchD.activeElement, suchD.querySelector("#notiz-suche"),
    "Notizsuche wird nicht fokussiert");
  const notizSuche = suchD.querySelector("#notiz-suche");
  notizSuche.value = "Eta Zeta";
  notizSuche.dispatchEvent(new suchW.Event("input", { bubbles: true }));
  assert.ok(suchD.querySelector('[data-fokus="notiz:such-notiz"]'),
    "Notizsuche verwendet nicht dieselbe Mehrwort-UND-Normalisierung");
  await suchT.wechsel("kalender");
  for (const ansicht of ["month", "week", "day"]) {
    suchT.zustand().kalender.ansicht = ansicht;
    await suchT.wechsel("aufgaben"); await suchT.wechsel("kalender");
    const heute = Array.from(suchD.querySelectorAll("button"))
      .find((button) => button.textContent.trim() === "Heute");
    const suchEinstieg = suchD.querySelector(".kalender-suchknopf");
    assert.ok(suchEinstieg && suchEinstieg.querySelector("svg"),
      "Suchlupe fehlt in Kalenderansicht " + ansicht);
    suchEinstieg.click();
    assert.ok(suchD.querySelector("#such-schleier"),
      "Suchlupe öffnet die Suche nicht in " + ansicht);
    schliesseSuche();
    const rechtsklick = new suchW.MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    heute.dispatchEvent(rechtsklick);
    assert.ok(rechtsklick.defaultPrevented && suchD.querySelector("#such-schleier"),
      "Heute-Rechtsklick fehlt in " + ansicht);
    schliesseSuche();
  }
  const fokusVorher = Array.from(suchD.querySelectorAll("button"))
    .find((button) => button.textContent.trim() === "Heute");
  fokusVorher.focus(); ctrlF();
  const suchFeld = suchD.querySelector("#globale-suche");
  suchFeld.value = "Alpha";
  suchFeld.dispatchEvent(new suchW.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 180));
  suchD.querySelector(".such-treffer-knopf").click();
  assert.ok(suchD.querySelector("#termin-schleier"), "Kalendertreffer öffnet den Termin nicht");
  ctrlF();
  assert.ok(!suchD.querySelector("#such-schleier"),
    "Strg+F öffnet Suche hinter einem fremden Modal");
  suchD.dispatchEvent(new suchW.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  assert.ok(!String(js).includes("console.log(such") && !String(js).includes("console.debug(such"),
    "Suchpfad protokolliert möglicherweise sensible Werte");
  assert.doesNotThrow(() => suchT.suchTrefferFuer("gesundheit"),
    "lokale Gesundheitssuche ist nicht ausführbar");
  ctrlF();
  const raceFeld = suchD.querySelector("#globale-suche");
  raceFeld.value = "Alpha";
  raceFeld.dispatchEvent(new suchW.Event("input", { bubbles: true }));
  raceFeld.value = "KeinTrefferNeuesterStand";
  raceFeld.dispatchEvent(new suchW.Event("input", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 180));
  assert.ok(!suchD.querySelector(".such-treffer-knopf") &&
    suchD.querySelector("#such-stand").textContent.includes("Nichts gefunden"),
  "abgebrochener älterer Suchlauf überschreibt den neuesten Stand");
  schliesseSuche();

  const alteTermine = suchT.daten().termine;
  const alteKontakte = suchT.daten().kontakte;
  suchT.daten().kontakte = Array.from({ length: 10000 }, (_, index) => ({
    id: "last-kontakt-" + index, nachname: "Kontakt " + index
  }));
  suchT.daten().termine = Array.from({ length: 10000 }, (_, index) => ({
    id: "last-termin-" + index, titel: index === 9999 ? "Nadelkern" : "Termin " + index,
    datum: "2026-06-12", zeit: "09:00", endZeit: "10:00",
    kontaktId: "last-kontakt-" + index, wiederholung: { art: "none", bis: "" }
  }));
  const suchStart = performance.now();
  const lastTreffer = suchT.suchTrefferFuer("kalender", ["nadelkern"], 101);
  const suchDauer = performance.now() - suchStart;
  assert.strictEqual(lastTreffer.length, 1, "Kernsuche verliert Treffer im 10.000er-Bestand");
  assert.ok(suchDauer < 150, "10.000er-Kernsuche dauert " + suchDauer.toFixed(1) + " ms");
  suchT.daten().termine = alteTermine;
  suchT.daten().kontakte = alteKontakte;
  suchDom.window.close();

  console.log("ALLE TESTS BESTANDEN ✓");
  process.exit(0);
})().catch((f) => {
  console.error("TEST FEHLGESCHLAGEN:", f && f.stack ? f.stack : f);
  if (process.env.MAGNOLIE_SPUR) console.error(f && f.stack);
  process.exit(1);
});
