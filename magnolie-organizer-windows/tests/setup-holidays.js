"use strict";
// Both real desktop scripts, a recording bridge, isolated JSON restart snapshots.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "../..");
const key = "Show school holidays for %(state)s in the calendar?";
const unavailable = "School holidays are not available for this region.";
const plain = x => JSON.parse(JSON.stringify(x));
const locales = ["en", ...fs.readdirSync(path.join(root, "magnolie-organizer/po"))
  .filter(p => p.endsWith(".po")).map(p => p.slice(0, -3))];
let count = 0;
function boot(web, data = {}, setup, language = "en") {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://setup-test.invalid/", pretendToBeVisual: true });
  const w = dom.window, messages = [], timers = [];
  w.setTimeout = (fn, delay) => { const timer = { fn, delay }; timers.push(timer); return timer; };
  w.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "setupTest";
  w.webkit = { messageHandlers: { setupTest: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  if (language !== "en") w.eval(fs.readFileSync(path.join(web, "i18n", language + ".js"), "utf8"));
  w.MagnolieI18n.setLocale(language);
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.App.init({ daten: data, neu: false, setupSelections: setup, regional: { language, timeZone: "UTC" } });
  const t = w.OrganizerTest;
  const saves = () => messages.filter(m => m.cmd === "speichern");
  return { w, t, messages, saves, close: () => w.close(),
    start() { for (const timer of timers.splice(0).filter(t => t.delay === 0 && !t.cancelled)) timer.fn(); },
    ack(ok = true) { const save = saves().at(-1); assert.ok(save); w.App.gespeichert({ id: save.id, ok }); },
    holidays: () => messages.filter(m => m.cmd === "feiertage"),
    save() { t.speichereJetzt(); const save = saves().at(-1); this.ack(); return save.text; }
  };
}
const address = { firstName: "Ada", lastName: "Example", street: "Example 1", postalCode: "01067",
  city: "Dresden", country: "DE", state: "DE-SN" };
const selection = (more = {}) => ({ address, addressChanged: true, schoolHolidays: false, schoolHolidayRegion: "", ...more });
for (const web of [path.join(root, "magnolie-organizer/web"), path.join(root, "magnolie-organizer-windows/app/web")]) {
  for (const language of locales) {
    const b = boot(web, {}, selection({ schoolHolidays: true, schoolHolidayRegion: "DE-SN" }), language);
    try {
      assert.equal(b.t.daten().einstellungen.adressen.route, true);
      assert.equal(b.t.daten().einstellungen.ort.region, "DE-SN");
      const catalog = language === "en" ? null : JSON.parse(fs.readFileSync(path.join(root,
        "magnolie-organizer-windows/app/native-i18n.json"))).locales[language];
      if (catalog) {
        assert.notEqual(catalog[key], key); assert.notEqual(catalog[unavailable], unavailable);
        assert.ok(catalog[key].includes("%(state)s"));
      }
      assert.equal(b.holidays().length, 0, "No request before durable Finish settings");
      b.start(); assert.equal(b.holidays().length, 0);
      b.ack(); assert.equal(b.holidays().length, 1);
      assert.deepEqual(plain(b.holidays()[0].regionen), []);
      assert.equal(b.holidays()[0].region, "DE-SN");
      assert.equal(b.holidays()[0].ferien, true);
      // Repeated delivery in the same web session cannot apply/import twice.
      if (b.t.uebernehmeSetupAbsichten) b.t.uebernehmeSetupAbsichten({ setupSelections: selection() });
      assert.equal(b.t.daten().einstellungen.ort.ferien, true);
      assert.equal(b.holidays().length, 1);
      count++;
    } finally { b.close(); }
  }
  for (const [country, state, bound, expected] of [
    ["DE", "DE-SN", "DE-SN", true], ["AT", "AT-9", "AT-9", true], ["CH", "CH-ZH", "CH-ZH", true],
    ["DE", "Sachsen", "DE-SN", true], ["AT", "DE-SN", "DE-SN", false],
    ["DE", "DE-BY", "DE-SN", false], ["DE", "Unknown", "Unknown", false],
    ["US", "California", "California", false], ["FR", "Paris", "Paris", false], ["", "", "", false]
  ]) {
    const b = boot(web, {}, selection({ address: { ...address, country, state }, schoolHolidays: true, schoolHolidayRegion: bound }));
    try { b.start(); if (expected) b.ack(); assert.equal(b.holidays().length, expected ? 1 : 0); count++; }
    finally { b.close(); }
  }
  for (const partial of [{}, { firstName: "Ada", lastName: "Example 2" }, { street: "Example", city: "City" }, { country: "DE", state: "DE-SN" }]) {
    const b = boot(web, {}, selection({ address: partial }));
    try { assert.equal(b.t.daten().einstellungen.adressen.route, false); b.start(); assert.equal(b.holidays().length, 0); count++; }
    finally { b.close(); }
  }
  const existing = { einstellungen: { adressen: { absender: "Existing 2\n8000 Zürich", route: false,
    land: "CH", landCode: "CH", karten: "openstreetmap" }, ort: { land: "CH", region: "CH-ZH", ferien: true } } };
  for (const setup of [undefined, selection({ setupSkipped: true }), selection({ address: { country: "DE" }, addressChanged: false })]) {
    const b = boot(web, existing, setup);
    try { const e = b.t.daten().einstellungen;
      assert.equal(e.adressen.absender, existing.einstellungen.adressen.absender);
      assert.equal(e.adressen.route, false); assert.equal(e.adressen.landCode, "CH");
      assert.equal(e.adressen.karten, "openstreetmap"); assert.equal(e.ort.land, "CH");
      b.start(); assert.equal(b.holidays().length, 0); count++;
    } finally { b.close(); }
  }
  for (const route of [false, true]) {
    const b = boot(web, { einstellungen: { adressen: { route } } }, selection());
    try { assert.equal(b.t.daten().einstellungen.adressen.route, route); count++; } finally { b.close(); }
  }
  const b = boot(web, {}, selection({ schoolHolidays: true, schoolHolidayRegion: "DE-SN" }));
  try {
    b.start(); b.ack();
    const result = { jahre: [2026], feiertage: [{ von: "2026-10-12", bis: "2026-10-24", name: "Herbstferien", art: "school-holiday", region: "DE-SN" }] };
    b.w.App.feiertageErgebnis(result); b.w.App.feiertageErgebnis(result);
    assert.equal(b.t.daten().feiertage.length, 1, "Repeated result replaces the year, no duplicate cache");
    assert.equal(b.t.daten().termine.length, 0, "Holidays never become appointments or recurrence jobs");
    assert.equal(b.t.feiertageAm("2026-10-12", true).length, 1);
    const dir = fs.mkdtempSync("/tmp/opencode/setup-holiday-restart-");
    try {
      fs.writeFileSync(path.join(dir, "daten.json"), b.save());
      const restartData = JSON.parse(fs.readFileSync(path.join(dir, "daten.json")));
      restartData.termine = [{ id: "ics-school", uid: "ics-school", sync: true, titel: "Herbstferien (SN)",
        datum: "2026-10-12", endDatum: "2026-10-24" }, { id: "ordinary", titel: "Ordinary series", datum: "2026-10-12",
        zeit: "09:00", wiederholung: { art: "weekly" } }];
      const restarted = boot(web, restartData);
      try {
        restarted.start(); assert.equal(restarted.holidays().length, 0);
        assert.equal(restarted.t.daten().feiertage.length, 1);
        assert.equal(restarted.t.daten().einstellungen.ort.ferien, true);
        assert.equal(restarted.t.feiertageAm("2026-10-12", true).length, 1);
        const appointments = restarted.t.termineAm("2026-10-12", true);
        assert.ok(appointments.length > 0 && appointments.every(t => t.id === "ordinary"),
          "An imported holiday stays out of ordinary appointments");
        const ordinary = JSON.stringify(restarted.t.daten().termine);
        restarted.t.oeffneEinstellungen();
        restarted.w.document.querySelector("#einst-tab-ort").click();
        const check = restarted.w.document.querySelector("#ort-ferien");
        assert.equal(check.checked, true); check.click();
        assert.equal(restarted.t.feiertageAm("2026-10-12", true).length, 0);
        assert.equal(restarted.t.daten().feiertage.length, 1, "View filter preserves cache");
        assert.equal(JSON.stringify(restarted.t.daten().termine), ordinary, "View filter does not change ordinary Planner series");
        const disabled = boot(web, JSON.parse(restarted.save()));
        try { disabled.start(); assert.equal(disabled.holidays().length, 0);
          assert.equal(disabled.t.feiertageAm("2026-10-12", true).length, 0); }
        finally { disabled.close(); }
        count++;
      } finally { restarted.close(); }
    } finally { fs.rmSync(dir, { recursive: true }); }
  } finally { b.close(); }
  for (const failedSave of [true, false]) {
    const b = boot(web, {}, selection({ schoolHolidays: true, schoolHolidayRegion: "DE-SN" }));
    try {
      b.start(); b.ack(!failedSave);
      if (failedSave) assert.equal(b.holidays().length, 0);
      else {
        b.w.App.feiertageErgebnis({ fehler: "Offline fixture" });
        assert.equal(b.t.daten().einstellungen.ort.setupFerienAbruf, true);
        const retry = boot(web, JSON.parse(b.save()));
        try { retry.start(); retry.ack(); assert.equal(retry.holidays().length, 1); }
        finally { retry.close(); }
      }
      count++;
    } finally { b.close(); }
  }
  for (const beforeAck of [true, false]) {
    const b = boot(web, {}, selection({ schoolHolidays: true, schoolHolidayRegion: "DE-SN" }));
    try {
      b.start();
      if (!beforeAck) b.ack();
      b.t.daten().einstellungen.ort.region = "DE-BY";
      if (beforeAck) { b.ack(); assert.equal(b.holidays().length, 0); }
      else { b.w.App.feiertageErgebnis({ jahre: [2026], feiertage: [{ von: "2026-10-12", name: "old", art: "school-holiday" }] });
        assert.equal(b.t.daten().feiertage.length, 0); }
      count++;
    } finally { b.close(); }
  }
}
console.log(`Setup holidays: ${count} cross-desktop cases passed; ${locales.length} languages.`);
