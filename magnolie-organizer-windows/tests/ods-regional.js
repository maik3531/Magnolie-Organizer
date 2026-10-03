"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
const roots = [path.resolve(__dirname, "../app/web")];
const linux = path.resolve(__dirname, "../../magnolie-organizer/web");
if (fs.existsSync(linux)) roots.push(linux);
for (const web of roots) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://ods.invalid/", pretendToBeVisual: true
  });
  const w = dom.window;
  w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "odsTest";
  w.webkit = { messageHandlers: { odsTest: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  const catalogs = new Map(), register = w.MagnolieI18n.registerCatalog;
  w.MagnolieI18n.registerCatalog = (language, catalog) => {
    catalogs.set(language, catalog.messages); register(language, catalog);
  };
  const locales = fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"));
  for (const locale of locales) w.eval(fs.readFileSync(path.join(web, "i18n", locale), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.App.init({ daten: {}, neu: false, regional: { language: "en", formatLocale: "en-US" } });
  const t = w.OrganizerTest;
  const entry = { id: "synthetic", _gesundheitArt: "vital", datum: "2026-10-04", zeit: "14:35",
    puls: 65, systolisch: 120, diastolisch: 80, temperatur: 36.5, gewicht: 70.5, groesse: 175 };
  t.daten().gesundheit.vitalwerte = [entry];
  for (const [language, region, cycle] of [["en", "en-US", "h12"], ["de", "de-DE", "h23"],
    ["fr", "fr-FR", "h23"], ["ar", "ar-EG", "h12"], ["en", "en-US", "h23"]]) {
    w.MagnolieI18n.setLocale(language);
    Object.assign(t.daten().einstellungen.regional, { language, formatLocale: region, hourCycle: cycle });
    const payload = t.gesundheitOdsNutzlast({ vital: true }, [entry]);
    const row = payload.tabellen[0].zeilen[0];
    const date = new Date(2026, 9, 4, 14, 35);
    assert.equal(row[0], new Intl.DateTimeFormat(region, { day: "2-digit", month: "2-digit", year: "numeric" }).format(date));
    assert.equal(row[1], new Intl.DateTimeFormat(region, { hour: "2-digit", minute: "2-digit", hourCycle: cycle }).format(date));
    assert.equal(row[4], new Intl.NumberFormat(region, { maximumFractionDigits: 2 }).format(region === "en-US" ? 97.7 : 36.5));
    assert.equal(payload.tabellen[0].links[4], w.MagnolieI18n.gettext("Temperature") + (region === "en-US" ? " °F" : " °C"));
    const glucose = t.gesundheitOdsNutzlast({ blutzucker: true }, [{ ...entry, _gesundheitArt: "blutzucker", wert: 6.5, ie: 1.5, einheit: "mmol/L", kontext: "Personal text" }]);
    assert.equal(glucose.tabellen[0].zeilen[0][2], new Intl.NumberFormat(region).format(6.5));
    assert.equal(glucose.tabellen[0].zeilen[0][5], "Personal text");
    const charts = t.gesundheitOdsNutzlast({ verlauf: "all" }, []);
    assert.ok(charts.tabellen[0].diagramme.some(chart => chart.zeilen.length > 0));
    for (const chart of charts.tabellen[0].diagramme) {
      assert.equal(chart.spalten[0], w.MagnolieI18n.gettext("Date"));
      for (const series of chart.serien) for (const point of series.punkte) {
        assert.match(point[0], /^\d{4}-\d{2}-\d{2}$/);
        assert.equal(typeof point[1], "number", "geometry retains numeric values");
      }
      if (chart.zeilen.length) assert.equal(chart.zeilen[0][0], row[0]);
    }
    const addresses = t.adressenOdsNutzlast([{ id: "synthetic-contact", vorname: "Example",
      geburtstag: "2026-10-04" }], ["geburtstag"]);
    assert.equal(addresses.zeilen[0][0], row[0]);
  }
  for (const language of ["en", ...locales.map(name => name.slice(0, -3))]) {
    w.MagnolieI18n.setLocale(language);
    for (const key of ["Date", "Time", "Temperature", "Blood glucose", "Weight"]) {
      const translated = w.MagnolieI18n.gettext(key);
      assert.ok(translated, language + ": " + key);
      if (language !== "en") assert.ok(catalogs.get(language)[key], language + ": missing " + key);
    }
  }
  dom.window.close();
  console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": regional ODS payloads passed");
}
