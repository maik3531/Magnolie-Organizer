/* Belastungstest der Oberfläche mit je 30.000 Lotus-Einträgen aus allen
   fünf Bereichen. */
"use strict";
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const WEB = process.env.MAGNOLIE_WEB ||
  path.resolve(__dirname, "..", "web");
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
const js = fs.readFileSync(path.join(WEB, "anwendung.js"), "utf8");
const i18nJs = fs.readFileSync(path.join(WEB, "i18n.js"), "utf8");
const deJs = fs.readFileSync(path.join(WEB, "i18n", "de.js"), "utf8");

const ANZAHL = Number(process.env.MAGNOLIE_ANZAHL || 30000);
let fehler = 0;

function messe(name, arbeit, grenzeMs) {
  const beginn = process.hrtime.bigint();
  const ergebnis = arbeit();
  const dauer = Number(process.hrtime.bigint() - beginn) / 1e6;
  const ok = dauer <= grenzeMs;
  if (!ok) fehler++;
  console.log("  %s %s ms   (Grenze %s ms) %s",
    name.padEnd(46), dauer.toFixed(0).padStart(6),
    String(grenzeMs).padStart(5), ok ? "ok" : "ZU LANGSAM");
  return ergebnis;
}

function pruefe(bedingung, text) {
  if (!bedingung) fehler++;
  console.log("  %s – %s", bedingung ? "ok  " : "FEHLT", text);
}

/* Termine über dreißig Jahre verteilt, wie sie aus Lotus kämen */
function baueTermine(anzahl) {
  const liste = [];
  const titel = ["Besprechung mit Herrn Müller", "Zahnarzt Dr. Schröder",
    "Jahreshauptversammlung", "Kundentermin Weißenfels", "Betriebsausflug"];
  let tag = new Date(1996, 0, 2);
  let i = 0;
  while (i < anzahl) {
    if (tag.getDay() !== 0 && tag.getDay() !== 6) {
      const proTag = 1 + (i % 3);
      for (let k = 0; k < proTag && i < anzahl; k++, i++) {
        const stunde = 7 + (i % 11);
        liste.push({
          id: "t" + i, uid: "mag-" + i + "@magnolie-organizer",
          datum: tag.getFullYear() + "-" +
            String(tag.getMonth() + 1).padStart(2, "0") + "-" +
            String(tag.getDate()).padStart(2, "0"),
          endDatum: "",
          zeit: String(stunde).padStart(2, "0") + ":" +
            ["00", "15", "30", "45"][i % 4],
          endZeit: String(stunde + 1).padStart(2, "0") + ":00",
          titel: titel[i % titel.length], notiz: i % 7 === 0 ? "Unterlagen mitbringen." : "",
          kategorien: i % 5 === 0 ? "Geschäftlich" : "",
          vertraulich: i % 17 === 0, vorlaeufig: i % 11 === 0,
          kostenstelle: "", kunde: "", geaendert: 1600000000000, sync: false
        });
      }
    }
    tag = new Date(tag.getTime() + 86400000);
  }
  return liste;
}

(async () => {
  console.log("Belastungstest der Oberfläche mit je %d Lotus-Einträgen\n", ANZAHL);
  const termine = messe("Termine erzeugen", () => baueTermine(ANZAHL), 4000);
  const heute = new Date();
  /* ein paar Termine auf heute legen, damit das Tagesblatt zu tun hat */
  for (let k = 0; k < 12; k++) {
    termine[k].datum = heute.getFullYear() + "-" +
      String(heute.getMonth() + 1).padStart(2, "0") + "-" +
      String(heute.getDate()).padStart(2, "0");
  }

  const dom = new JSDOM(html, { runScripts: "dangerously",
    url: "https://organizer.test/", pretendToBeVisual: true });
  const w = dom.window, d = w.document;
  w.eval(i18nJs);
  w.eval(deJs);
  w.MagnolieI18n.setLocale("de");
  w.eval(js);
  for (let i = 0; i < 80 && !w.OrganizerTest; i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  const T = w.OrganizerTest;

  console.log("\nÖffnen des Buches");
  messe("App.init mit dem ganzen Bestand", () => {
    w.App.init({ daten: { version: 1, termine: termine, aufgaben: [],
      kontakte: [], notizen: [], jahrestage: [] }, neu: false, datenPfad: "/heim" });
  }, 8000);
  pruefe(T.daten().termine.length === ANZAHL,
    "alle Termine übernommen (" + T.daten().termine.length + ")");

  /* Die übrigen Bereiche: Adressen, Aufgaben, Notizen, Jahrestage */
  const nachnamen = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber",
    "Meyer", "Wagner", "Becker", "Schulz", "Hoffmann", "Schäfer", "Koch"];
  const vornamen = ["Hans", "Käthe", "Jürgen", "Ursula", "Günther", "Änne"];
  const kontakte = [];
  for (let i = 0; i < ANZAHL; i++) {
    const nach = nachnamen[i % nachnamen.length];
    const kontakt = { id: "k" + i, uid: "mag-k" + i + "@x",
      nachname: nach, vorname: vornamen[i % vornamen.length],
      firma: i % 3 === 0 ? nach + " GmbH" : "",
      strasse: "Hauptstraße " + (1 + (i % 199)),
      plz: "47051", ort: "Duisburg",
      telefon: "0203 " + (100000 + i), mobil: "0171 " + (1000000 + i),
      email: "k" + i + "@example.de",
      notiz: i % 9 === 0 ? "Stammkunde seit 1998" : "",
      geaendert: 1600000000000, sync: false };
    if (i % 10 === 0) {
      kontakt.telefone = [
        { wert: kontakt.telefon, typen: ["VOICE"] },
        { wert: kontakt.mobil, typen: ["CELL"] },
        { wert: "0203 " + (200000 + i), typen: ["WORK"] },
        { wert: "0203 " + (300000 + i), typen: ["FAX"] }
      ];
      kontakt.anschriften = [
        { strasse: kontakt.strasse, plz: kontakt.plz, ort: kontakt.ort, typen: ["HOME"] },
        { strasse: "Zweigweg " + (1 + i % 99), plz: "47441", ort: "Moers",
          typen: ["WORK", "X-ZWEITSITZ"] }
      ];
    }
    kontakte.push(kontakt);
  }
  const aufgaben = [];
  for (let i = 0; i < ANZAHL; i++) {
    aufgaben.push({ id: "a" + i, uid: "lotus-a" + i,
      titel: "Rechnung " + i + " prüfen",
      prio: 1 + (i % 3), faellig: "2026-0" + (1 + (i % 9)) + "-1" + (i % 9),
      erledigt: i % 4 === 0, notiz: "" });
  }
  const notizen = [];
  for (let i = 0; i < ANZAHL; i++) {
    notizen.push({ id: "n" + i, titel: "Notiz " + i,
      text: "Milch, Brot, Käse besorgen.", html: "", geaendert: "2026-07-01" });
  }
  const jahrestage = [];
  for (let i = 0; i < ANZAHL; i++) {
    jahrestage.push({ id: "j" + i, uid: "mag-j" + i + "@x",
      name: vornamen[i % vornamen.length] + " " +
        nachnamen[i % nachnamen.length] + " " + i,
      datum: "19" + (50 + (i % 49)) + "-0" + (1 + (i % 9)) + "-1" + (i % 9),
      typ: i % 3 === 0 ? "Hochzeitstag" : "Geburtstag" });
  }

  console.log("\nDie übrigen Bereiche (je %d Einträge)", ANZAHL);
  messe("alles übernehmen und zeichnen", () => {
    w.App.importErgebnis({ art: "lotus", abgebrochen: false,
      kontakte: kontakte, aufgaben: aufgaben, notizen: notizen,
      jahrestage: jahrestage });
    T.wechsel("adressen");
  }, 20000);
  pruefe(T.daten().kontakte.length === ANZAHL,
    "alle Adressen im Buch (" + T.daten().kontakte.length + ")");
  pruefe(T.daten().kontakte[0].telefone.length === 4 &&
    T.daten().kontakte[0].anschriften.length === 2,
  "mehrfache Rufnummern und Anschriften bleiben im großen Bestand erhalten");
  pruefe(T.daten().aufgaben.length === ANZAHL,
    "alle Aufgaben im Buch (" + T.daten().aufgaben.length + ")");
  pruefe(T.daten().notizen.length === ANZAHL,
    "alle Notizen im Buch (" + T.daten().notizen.length + ")");
  pruefe(T.daten().jahrestage.length === ANZAHL,
    "alle Jahrestage im Buch (" + T.daten().jahrestage.length + ")");
  messe("Adressbuch zeichnen", () => { T.wechsel("kalender"); T.wechsel("adressen"); }, 4000);
  const suchfeld = d.querySelector("#inhalt-links input[type=search], " +
    "#inhalt-links input[type=text]");
  if (suchfeld) {
    messe("im Adressbuch suchen (Schäfer)", () => {
      suchfeld.value = "Schäfer";
      suchfeld.dispatchEvent(new w.Event("input", { bubbles: true }));
    }, 4000);
    messe("Suche wieder leeren", () => {
      suchfeld.value = "";
      suchfeld.dispatchEvent(new w.Event("input", { bubbles: true }));
    }, 4000);
  }
  messe("Aufgabenliste zeichnen", () => T.wechsel("aufgaben"), 4000);
  messe("Notizbuch zeichnen", () => T.wechsel("notizen"), 4000);
  messe("Jahrestage zeichnen", () => T.wechsel("jahrestage"), 4000);
  T.wechsel("kalender");

  console.log("\nDie drei Ansichten mit vollem Bestand");
  Array.from(d.querySelectorAll("#ansicht-umschalter .u-knopf"))
    .find((b) => b.dataset.ansicht === "month").click();
  messe("Terminübersicht (Monat) zeichnen", () => {
    T.wechsel("notizen"); T.wechsel("kalender");
  }, 5000);
  pruefe(!!d.querySelector(".termin-uebersicht"),
    "die Terminübersicht steht rechts");
  messe("in die Tagesansicht wechseln", () => {
    const knopf = Array.from(d.querySelectorAll("#ansicht-umschalter .u-knopf"))
      .find((b) => b.dataset.ansicht === "day");
    knopf.click();
  }, 3000);
  pruefe(d.querySelectorAll(".tages-spalte").length === 2,
    "zwei Tagesspalten");
  messe("zehnmal zwei Tage weiterblättern", () => {
    for (let i = 0; i < 10; i++) d.querySelector("#ecke-rechts").click();
  }, 6000);
  messe("Terminblatt öffnen und schließen", () => {
    for (let i = 0; i < 5; i++) {
      T.oeffneTerminBlatt(null, T.zustand().kalender.tag);
      d.getElementById("termin-schleier").remove();
    }
  }, 4000);
  Array.from(d.querySelectorAll("#ansicht-umschalter .u-knopf"))
    .find((b) => b.dataset.ansicht === "month").click();

  console.log("\nBlättern und Ansichten");
  messe("Monatsblatt zeichnen", () => T.wechsel("kalender"), 1500);
  const monatKnopf = Array.from(d.querySelectorAll(".pfeil"))
    .find((b) => b.textContent === "›");
  messe("zehnmal einen Monat weiterblättern", () => {
    for (let i = 0; i < 10; i++) monatKnopf.click();
  }, 4000);
  const wocheKnopf = Array.from(d.querySelectorAll(".u-knopf"))
    .find((b) => b.textContent === "Woche");
  messe("auf das Wochenblatt umschalten", () => wocheKnopf.click(), 1500);
  messe("zehnmal eine Woche weiterblättern", () => {
    const vor = Array.from(d.querySelectorAll(".pfeil"))
      .find((b) => b.textContent === "›");
    for (let i = 0; i < 10; i++) vor.click();
  }, 4000);
  const monatUm = Array.from(d.querySelectorAll(".u-knopf"))
    .find((b) => b.textContent === "Monat");
  monatUm.click();
  messe("Jahresplaner zeichnen", () => T.wechsel("planer"), 3000);
  messe("Aufgaben, Adressen, Notizen, Jahrestage", () => {
    T.wechsel("aufgaben"); T.wechsel("adressen");
    T.wechsel("notizen"); T.wechsel("jahrestage");
  }, 8000);
  T.wechsel("kalender");

  console.log("\nEintragen und Speichern");
  messe("einen Termin anlegen und zeichnen", () => {
    T.daten().termine.push({ id: "neu1", uid: "mag-neu@x", datum: "2026-08-03",
      zeit: "09:00", endZeit: "10:00", titel: "Neuer Termin", notiz: "",
      kategorien: "", vertraulich: false, vorlaeufig: false,
      kostenstelle: "", kunde: "", geaendert: Date.now(), sync: false });
    T.wechsel("kalender");
  }, 1500);
  const roh = messe("Daten in Text verwandeln (Speichern)",
    () => JSON.stringify(T.daten()), 3000);
  console.log("    Die Datei wäre %s MB groß",
    (Buffer.byteLength(roh, "utf8") / 1048576).toFixed(1));
  messe("Daten wieder einlesen", () => JSON.parse(roh), 3000);

  console.log("\nÜbernahme aus Lotus (Zusammenführen)");
  const nachschub = baueTermine(5000).map((t, i) => ({
    ...t, id: "n" + i, uid: "lotus-" + i, datum: "2030-0" +
      (1 + (i % 9)) + "-" + String(1 + (i % 28)).padStart(2, "0")
  }));
  messe("5.000 neue Termine zusammenführen", () => {
    w.App.importErgebnis({ art: "lotus", abgebrochen: false,
      termine: nachschub });
  }, 15000);
  const nachErstem = T.daten().termine.length;
  pruefe(nachErstem > ANZAHL + 4000,
    "Bestand deutlich gewachsen (" + nachErstem + ")");
  messe("dieselben 5.000 noch einmal (alles doppelt)", () => {
    w.App.importErgebnis({ art: "lotus", abgebrochen: false,
      termine: nachschub });
  }, 15000);
  pruefe(T.daten().termine.length === nachErstem,
    "nichts doppelt angelegt (" + T.daten().termine.length + ")");

  console.log("\nWeitergeben (Export) über die Oberfläche");
  /* Die Druckseite ist der aufwendigste Weg aus der Oberfläche heraus */
  const alleKontakte = T.daten().kontakte;
  const druckSeite = messe("Druckseite für 30.000 Adressen bauen",
    () => T.druckSeite(alleKontakte), 15000);
  console.log("    Die Druckseite wäre %s MB groß",
    (Buffer.byteLength(druckSeite, "utf8") / 1048576).toFixed(1));
  pruefe(druckSeite.includes("<!DOCTYPE html"), "Druckseite ist vollständig");
  pruefe((druckSeite.match(/class="karte"/g) || []).length === alleKontakte.length,
    "jede Karteikarte steht auf der Seite");

  const druckTermine = messe("Druckseite für die Termine eines Monats bauen",
    () => {
    T.wechsel("kalender");
    const schleier = T.oeffneDruckvorschau(null, "kalender");
    const html = T.druckSeite(T.daten().termine.slice(0, 200));
    schleier.remove();
    return html;
  }, 8000);
  pruefe(druckTermine.includes("Magnolie Organizer"), "Kopfzeile vorhanden");

  console.log("\nSpeicher: %s MB belegt",
    (process.memoryUsage().heapUsed / 1048576).toFixed(0));

  if (fehler) {
    console.log("\n%d PRÜFUNGEN FEHLGESCHLAGEN", fehler);
    process.exit(1);
  }
  console.log("\nBELASTUNGSTEST DER OBERFLÄCHE BESTANDEN ✓");
  process.exit(0);
})().catch((f) => {
  console.error("BELASTUNGSTEST FEHLGESCHLAGEN:", f && f.message ? f.message : f);
  if (process.env.MAGNOLIE_SPUR) console.error(f && f.stack);
  process.exit(1);
});
