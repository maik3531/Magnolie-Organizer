"use strict";
// Behavioral/generative/real-DOM checks for the optional forecast (Refs #803).
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict"), { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "../..");
const windows = path.resolve(__dirname, "..");
const embeddedVectors = path.join(windows, "contracts/cycle-forecast-vectors.json");
const standalone = fs.existsSync(embeddedVectors);
const vectorsPath = standalone ? embeddedVectors : path.join(root, "contracts/cycle-forecast-vectors.json");
const pythonSource = standalone
  ? path.join(windows, "shared/magnolie-organizer/werkzeuge/magnolie_cycle.py")
  : path.join(root, "magnolie-organizer/bin/magnolie_cycle.py");
const harnessFile = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(harnessFile, module);
harness.filename = harnessFile; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(harnessFile, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", harnessFile);
const plain = value => JSON.parse(JSON.stringify(value));
const vectors = JSON.parse(fs.readFileSync(vectorsPath, "utf8")).cases;
const dates = ["2026-01-01", "2026-01-29", "2026-02-26"];
const profile = (days = dates, options = {}) => ({
  zyklusmarker: [{ id: "light", art: "bleeding-light", name: "Renamed light", symbol: "💧" },
    { id: "medium", art: "bleeding-medium", name: "Renamed medium", symbol: "💧💧" },
    { id: "other", art: "custom", name: "Synthetic other", symbol: "○" }],
  tagmarken: days.map(datum => ({ datum, zyklusIds: ["light"] })),
  einstellungen: { kalender: { zykluskalenderAn: true, zyklusErinnerungen: options } }
});
let count = 0;
const check = (a, b, message) => { assert.deepEqual(plain(a), plain(b), message); count++; };
async function boot(web, data, now = "2026-03-26T12:00:00Z") {
  const b = await harness.exports.boot(web, {}, false), RealDate = b.w.Date;
  b.clock = { value: now };
  b.w.Date = class extends RealDate {
    constructor(...args) { super(...(args.length ? args : [b.clock.value])); }
    static now() { return +new RealDate(b.clock.value); }
  };
  b.w.App.init({ daten: data, neu: false, regional: { language: "en", timeZone: "UTC" } });
  b.redraw = () => b.t.aendereTagmarkenBereich("2020-01-01", "2020-01-01", null, null);
  b.toggle = (id, value) => {
    const input = b.w.document.getElementById(id); assert.ok(input, id);
    input.checked = value; input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
  };
  b.settings = () => { b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-kalender").click(); };
  return b;
}
let seed = 803;
function random(n) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed % n; }
function syntheticCases() {
  const cases = [];
  for (let i = 0; i < 1000; i++) {
    let day = Date.parse("2020-01-01T00:00:00Z"), days = [];
    for (let j = 0, n = 3 + random(28); j < n; j++) {
      day += (j && random(15) === 0 ? 4 + random(150) : 14 + random(47)) * 86400000;
      days.push(new Date(day).toISOString().slice(0, 10));
    }
    const asOf = new Date(day + random(160) * 86400000).toISOString().slice(0, 10);
    cases.push({ name: "seed803_" + i, data: profile(days), asOf });
  }
  return cases;
}
(async () => {
  const generated = syntheticCases(), all = vectors.concat(generated), results = [];
  for (const web of harness.exports.roots) {
    const b = await boot(web, profile());
    try {
      const output = [];
      for (const vector of all) {
        const before = JSON.stringify(vector.data), stats = plain(b.t.zyklusStatistik(vector.data, vector.asOf));
        for (const [key, value] of Object.entries(vector.expected || {})) check(stats[key], value, vector.name + ":" + key);
        check(JSON.stringify(vector.data), before, "Statistics must not mutate " + vector.name);
        if (stats.predicted) {
          assert.ok(stats.windowStart <= stats.predicted && stats.predicted <= stats.windowEnd, vector.name); count++;
          assert.ok(stats.predicted > stats.starts.at(-1), vector.name); count++;
        }
        const noisy = plain(vector.data);
        if (Array.isArray(noisy.tagmarken)) {
          noisy.tagmarken = noisy.tagmarken.concat(noisy.tagmarken).reverse();
          check(b.t.zyklusStatistik(noisy, vector.asOf), stats, "Duplicate/order invariance " + vector.name);
        }
        output.push(stats);
      }
      for (const bad of [null, {}, 0, "", "0000-01-01", "2026-02-30", "2026-1-01", "20260301", "2026-03-01T00:00:00Z"])
        { assert.throws(() => b.t.zyklusStatistik({}, bad)); count++; }
      for (const bad of [null, 1, "text", [], { zyklusmarker: null, tagmarken: null }])
        check(b.t.zyklusStatistik(bad, "2026-03-01").starts, [], "Damaged root");
      results.push(output);
      console.log(path.relative(root, web) + `: ${vectors.length} golden + 1000 seeded histories and invariants passed`);
    } finally { b.close(); }
  }
  check(results[0], results[1], "Both JavaScript frontends must agree completely");
  const python = process.env.MAGNOLIE_PYTHON || "python3";
  const py = spawnSync(python, ["-B", "-c", "import sys,json,importlib.util; s=importlib.util.spec_from_file_location('cycle',sys.argv[1]); m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps([m.estimate_cycle(v['data'],v['asOf']) for v in json.load(sys.stdin)]))", pythonSource],
    { input: JSON.stringify(all), encoding: "utf8", maxBuffer: 16 * 1024 * 1024, timeout: 30000 });
  assert.equal(py.status, 0, py.stderr);
  check(results[0], JSON.parse(py.stdout), "JavaScript/Python complete cross-engine parity");
  for (const web of harness.exports.roots) {
    const b = await boot(web, profile());
    try {
      const t = b.t, d = b.w.document, data = t.daten();
      check(data.einstellungen.kalender.zyklusErinnerungen.anzeige, false, "Old books default off");
      assert.equal(d.querySelector(".zyklus-prognose-kasten"), null); count++;
      const before = JSON.stringify([data.tagmarken, data.termine]);
      b.settings(); b.toggle("kalender-zyklus-prognose-anzeige", true);
      assert.ok(d.querySelector(".zyklus-prognose-kasten")); count++;
      check(t.zyklusTermineFuerErinnerung(), [], "Display does not opt in to notifications");
      check(JSON.stringify([data.tagmarken, data.termine]), before, "Display preserves real records");
      b.t.schliesseEinstellungen();
      const ghost = d.querySelector('[data-cycle-confirm="2026-03-26"]'); assert.ok(ghost); count++;
      assert.match(ghost.title, /Estimated start window.*24.*28/s); count++;
      assert.equal(ghost.querySelector("path").getAttribute("fill-opacity"), ".32"); count++;
      ghost.click();
      assert.ok(d.querySelector("#zyklus-bestaetigung")); count++;
      assert.equal(d.querySelector("#zyklus-bestaetigung-speichern").disabled, true); count++;
      d.querySelector("#zyklus-bestaetigung .dialog-knoepfe button").click();
      check(JSON.stringify([data.tagmarken, data.termine]), before, "Cancel preserves all observations");
      t.bestaetigeZyklusTag("2026-03-28");
      assert.equal(d.querySelector("#zyklus-bestaetigung"), null); count++;
      check(JSON.stringify([data.tagmarken, data.termine]), before, "Future estimates cannot become observations");
      // Confirm precisely one elapsed/current day; preserve unrelated markers.
      t.aendereTagmarkenBereich("2026-03-26", "2026-03-26", null, ["other"]);
      d.querySelector('[data-cycle-confirm="2026-03-26"]').click();
      const choice = d.querySelector("#zyklus-bestaetigung-intensitaet");
      choice.value = "medium"; choice.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      d.querySelector("#zyklus-bestaetigung-speichern").click();
      check(data.tagmarken.find(mark => mark.datum === "2026-03-26").zyklusIds, ["other", "medium"], "Confirm one actual day with selected intensity");
      check(data.termine, [], "Confirmation never creates an ordinary appointment");
      check(t.zyklusStatistik().predicted, "2026-04-23", "Only confirmed day affects the next forecast");
      assert.equal(d.querySelector('[data-cycle-estimate="2026-03-26"]'), null); count++;
      b.t.speichereJetzt();
      const saved = JSON.parse(b.saves().at(-1).text);
      check(saved.tagmarken, data.tagmarken, "Durable save contains observations only");
      assert.ok(!/cycleEstimate|windowStart|windowEnd|recordedRun/.test(JSON.stringify(saved))); count++;
      check(t.normalisiere(saved).einstellungen.kalender.zyklusErinnerungen.anzeige, true, "Opt-in survives reload");
      // Invalid unrelated numbers cannot block opt-out.
      b.settings(); d.querySelectorAll("#kalender-gruppe-zykluskalender input[type=number]")[1].value = "";
      b.toggle("kalender-zyklus-prognose-anzeige", false);
      check(data.einstellungen.kalender.zyklusErinnerungen.anzeige, false, "Invalid threshold must not block off");
      assert.equal(d.querySelector(".zyklus-prognose-kasten"), null); count++;
      b.t.schliesseEinstellungen();
      // A book replacement invalidates both summaries and markers.
      b.w.App.init({ daten: profile([], { anzeige: true }), neu: false, regional: { language: "en", timeZone: "UTC" } });
      assert.match(d.querySelector(".zyklus-prognose-kasten").textContent, /Not enough recent data/); count++;
      assert.equal(d.querySelector("[data-cycle-estimate]"), null); count++;
    } finally { b.close(); }
    const expired = await boot(web, profile(dates, { anzeige: true, abweichung: true }), "2026-03-29T12:00:00Z");
    try {
      const d = expired.w.document, before = JSON.stringify(expired.t.daten().tagmarken);
      assert.equal(d.querySelector("[data-cycle-estimate]"), null, "Unconfirmed active predictions expire"); count++;
      const hint = d.querySelector('[data-cycle-hint="2026-03-26"]'); assert.ok(hint); count++;
      assert.match(hint.title, /ended 1 days ago.*No new start is recorded/s); count++;
      assert.equal(hint.querySelector("path").getAttribute("stroke-dasharray"), "2 2"); count++;
      hint.click(); assert.equal(d.querySelector("#zyklus-bestaetigung"), null); count++;
      assert.ok(d.querySelector("#zyklus-pause")); count++;
      d.querySelector("#zyklus-pause .dialog-knoepfe button").click();
      check(JSON.stringify(expired.t.daten().tagmarken), before, "Expired hint is never an observation");
      expired.settings(); expired.toggle("kalender-zyklus-abweichung", false);
      assert.equal(d.querySelector("[data-cycle-hint]"), null); count++;
      expired.toggle("kalender-zykluskalender", false);
      assert.equal(d.querySelector(".zyklus-prognose-kasten"), null); count++;
    } finally { expired.close(); }
    const removed = await boot(web, profile(dates, { anzeige: true }));
    try {
      removed.settings();
      const d = removed.w.document;
      d.querySelector("#kalender-gruppe-zykluskalender .zyklus-definition button").click();
      removed.t.schliesseEinstellungen();
      assert.equal(d.querySelector("[data-cycle-estimate]"), null); count++;
      assert.match(d.querySelector(".zyklus-prognose-kasten").textContent, /Not enough recent data/); count++;
    } finally { removed.close(); }
    for (const action of ["book", "lock", "restore"]) {
      const sensitive = await boot(web, profile(dates, { anzeige: true }));
      try {
        sensitive.t.bestaetigeZyklusTag("2026-03-26");
        assert.ok(sensitive.w.document.querySelector("#zyklus-bestaetigung")); count++;
        if (action === "book") sensitive.w.App.init({ daten: profile([]), neu: false });
        if (action === "lock") sensitive.w.App.init({ gesperrt: true });
        if (action === "restore") sensitive.w.App.journalWiederhergestellt({ ok: true, daten: profile([]) });
        assert.equal(sensitive.w.document.querySelector("#zyklus-bestaetigung"), null, action + " removes old sensitive dialog"); count++;
        assert.equal(sensitive.w.document.querySelector("[data-cycle-estimate]"), null); count++;
      } finally { sensitive.close(); }
    }
    const paused = await boot(web, profile(dates, { anzeige: true, prognose: true, abweichung: true }), "2026-03-29T12:00:00Z");
    try {
      const t = paused.t, d = paused.w.document;
      for (const [date, expected] of [["2026-05-31", "2027-02-28"], ["2027-05-31", "2028-02-29"],
          ["2026-03-29", "2026-12-29"], ["2026-01-01", "2026-10-01"], ["9999-12-31", null], ["bad", null]])
        check(t.zyklusNeunMonate(date), expected, "Nine calendar months with month-end clamping");
      const realBefore = JSON.stringify([t.daten().tagmarken, t.daten().termine]);
      const select = (id, value) => { const field = d.getElementById(id); field.value = value; field.dispatchEvent(new paused.w.Event("change")); };
      const setEnd = value => {
        const field = d.getElementById("zyklus-pause-bis");
        if (field.dataset.datumText === "ja") { field.dataset.datumIso = value; field.value = value.split("-").reverse().join("."); }
        else field.value = value;
        field.dispatchEvent(new paused.w.Event("change"));
      };
      d.querySelector('[data-cycle-hint="2026-03-26"]').click();
      assert.ok(d.querySelector("#zyklus-pause-speichern").disabled); count++;
      select("zyklus-pause-grund", "pregnancy");
      const end = d.getElementById("zyklus-pause-bis");
      check(end.dataset.datumIso || end.value, "2026-12-29", "Pregnancy defaults to editable nine months");
      assert.equal(d.getElementById("zyklus-pause-unbefristet").checked, false); count++;
      const dismissedSave = d.getElementById("zyklus-pause-speichern");
      d.querySelector("#zyklus-pause .dialog-knoepfe button").click(); dismissedSave.click();
      check(t.daten().einstellungen.kalender.zyklusErinnerungen.pause || null, null, "Canceled pause and old button cannot save");
      t.oeffneZyklusPauseDialog(); select("zyklus-pause-grund", "pregnancy");
      setEnd("2026-03-28"); d.getElementById("zyklus-pause-speichern").click();
      assert.ok(d.querySelector('#zyklus-pause [role="alert"]').textContent); count++;
      assert.equal(t.zyklusStatistik().paused, false); count++;
      setEnd("2026-12-29"); d.getElementById("zyklus-pause-speichern").click();
      check(t.daten().einstellungen.kalender.zyklusErinnerungen.pause,
        { reason: "pregnancy", startedOn: "2026-03-29", until: "2026-12-29", resumedOn: null }, "Explicit pause persisted");
      check(JSON.stringify([t.daten().tagmarken, t.daten().termine]), realBefore, "Pause preserves observations and appointments");
      check(t.zyklusTermineFuerErinnerung(), [], "Pause suppresses both reminder kinds");
      assert.equal(d.querySelector("[data-cycle-estimate], [data-cycle-hint]"), null); count++;
      assert.match(d.querySelector(".zyklus-prognose-kasten").textContent, /Pregnancy/); count++;
      const saved = plain(t.daten()); paused.w.App.init({ daten: saved, neu: false });
      check(t.daten().einstellungen.kalender.zyklusErinnerungen.pause, saved.einstellungen.kalender.zyklusErinnerungen.pause, "Pause survives book serialization/reload");
      paused.clock.value = "2026-03-30T12:00:00Z";
      t.aendereTagmarkenBereich("2026-03-30", "2026-03-30", null, ["light", "other"]);
      assert.ok(d.querySelector("#zyklus-wiederaufnahme")); count++;
      assert.equal(t.zyklusStatistik().paused, true, "Bleeding alone is not interpreted as a returning period"); count++;
      const oldConfirm = d.getElementById("zyklus-wiederaufnahme-bestaetigen");
      d.getElementById("zyklus-wiederaufnahme-behalten").click(); oldConfirm.click();
      assert.equal(t.zyklusStatistik().paused, true, "Keep pause also rejects dismissed confirmation"); count++;
      check(t.daten().tagmarken.find(mark => mark.datum === "2026-03-30").zyklusIds, ["light", "other"], "Observed bleeding remains recorded");
      t.aendereTagmarkenBereich("2026-03-30", "2026-03-30", null, ["other"]);
      t.aendereTagmarkenBereich("2026-03-30", "2026-03-30", null, ["light", "other"]);
      const confirm = d.getElementById("zyklus-wiederaufnahme-bestaetigen"); confirm.click(); confirm.click();
      check(t.zyklusStatistik().resumedOn, "2026-03-30", "Explicit new period ends pause early");
      check(t.zyklusStatistik().starts, ["2026-03-30"], "History before the pause is excluded");
      check(t.zyklusStatistik().reason, "restart", "First resumed period cannot reuse an old baseline");
      check(t.zyklusTermineFuerErinnerung(), [], "No old late or deviation reminders after resumption");
      paused.clock.value = "2026-05-25T12:00:00Z";
      t.aendereTagmarkenBereich("2026-04-27", "2026-04-27", null, ["light"]);
      t.aendereTagmarkenBereich("2026-05-25", "2026-05-25", null, ["light"]);
      check(t.zyklusStatistik().predicted, "2026-06-22", "Three new starts create a fresh estimate");
      paused.settings();
      for (const reason of ["medication", "menopause", "breastfeeding", "other"]) {
        t.oeffneZyklusPauseDialog(); select("zyklus-pause-grund", reason);
        assert.equal(d.getElementById("zyklus-pause-unbefristet").checked, true); count++;
        d.getElementById("zyklus-pause-speichern").click();
        check(t.zyklusStatistik().pauseReason, reason, "Self-reported reason is stored without inference");
        check(t.zyklusStatistik().pauseUntil, null, "Other reasons default to no fixed end");
        assert.equal(d.getElementById("kalender-zyklus-pause-status").hidden, false); count++;
        assert.match(d.getElementById("kalender-zyklus-pause-status").textContent, /Period predictions paused/); count++;
      }
      const marksBeforeEnd = JSON.stringify(t.daten().tagmarken);
      t.oeffneZyklusPauseDialog(); d.getElementById("zyklus-pause-beenden").click();
      check(t.zyklusStatistik().paused, false, "Manual end resumes planning");
      check(JSON.stringify(t.daten().tagmarken), marksBeforeEnd, "Ending a pause creates no bleeding");
      assert.equal(d.getElementById("kalender-zyklus-pause-status").hidden, true, "Open settings immediately reflect ending a pause"); count++;
      assert.equal(d.getElementById("kalender-zyklus-pause-status").textContent, ""); count++;
    } finally { paused.close(); }
    for (const modal of ["pause", "resume"]) for (const action of ["book", "lock", "restore"]) {
      const data = profile(dates, { anzeige: true, pause: { reason: "medication", startedOn: "2026-03-26", until: null } });
      const b = await boot(web, data);
      try {
        if (modal === "pause") b.t.oeffneZyklusPauseDialog();
        else b.t.aendereTagmarkenBereich("2026-03-26", "2026-03-26", null, ["light"]);
        const id = modal === "pause" ? "zyklus-pause" : "zyklus-wiederaufnahme";
        assert.ok(b.w.document.getElementById(id)); count++;
        if (action === "book") b.w.App.init({ daten: profile([]), neu: false });
        if (action === "lock") b.w.App.init({ gesperrt: true });
        if (action === "restore") b.w.App.journalWiederhergestellt({ ok: true, daten: profile([]) });
        assert.equal(b.w.document.getElementById(id), null, action + " removes sensitive " + modal + " dialog"); count++;
      } finally { b.close(); }
    }
    console.log(path.relative(root, web) + ": opt-in, confirmation, expiry, persistence, pause reasons, fresh history, cancellation and book-switch UI passed");
  }
  console.log(`CYCLE FORECAST PASSED: ${count} assertions; no clinical accuracy claim`);
})().catch(error => { console.error(error); process.exitCode = 1; });
