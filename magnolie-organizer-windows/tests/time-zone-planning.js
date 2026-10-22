"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "zeitOrtszeitpunkt, zeitOrtsanzeige, zeitzonenVerankerungsPlan, icsExpansion, icsQuelle, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {});
    try {
      const instant = b.t.zeitOrtszeitpunkt("2026-10-21", "19:30:47", "America/New_York");
      assert.equal(new Date(instant).toISOString(), "2026-10-21T23:30:47.000Z");
      const berlin = b.t.zeitOrtsanzeige(instant, "Europe/Berlin");
      assert.equal(berlin.datum, "2026-10-22"); assert.equal(berlin.zeit, "01:30:47");
      assert.equal(b.t.zeitOrtszeitpunkt(berlin.datum, berlin.zeit, berlin.zone, instant), instant, "Display-zone conversion preserves the instant and seconds");
      assert.notEqual(b.t.zeitOrtszeitpunkt("2026-10-21", "19:30:47", "Europe/Berlin"), instant, "Planning the same wall clock in a different place deliberately changes the instant");
      assert.throws(() => b.t.zeitOrtszeitpunkt("2026-03-29", "02:30", "Europe/Berlin"), "A DST gap is not silently shifted");
      const early = b.t.zeitOrtszeitpunkt("2026-10-25", "02:30:47", "Europe/Berlin");
      const lateReference = Date.parse("2026-10-25T01:30:47Z");
      const late = b.t.zeitOrtszeitpunkt("2026-10-25", "02:30:47", "Europe/Berlin", lateReference);
      assert.equal(new Date(early).toISOString(), "2026-10-25T00:30:47.000Z"); assert.equal(late, lateReference);
      for (const [date, time, zone] of [["2026-02-30", "12:00", "UTC"], ["2026-10-21", "25:00", "UTC"], ["2026-10-21", "12:00:60", "UTC"], ["2026-10-21", "12:00", "Mars/Olympus"]])
        assert.throws(() => b.t.zeitOrtszeitpunkt(date, time, zone));
      const kathmandu = b.t.zeitOrtszeitpunkt("2026-10-22", "05:15:09", "Asia/Kathmandu");
      assert.equal(new Date(kathmandu).toISOString(), "2026-10-21T23:30:09.000Z");
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin" });
      const due = { id: "due-only", faellig: "2026-10-21", faelligZeit: "23:30", icsRoundtrip: ["UID:due-fixture", "DUE:20261021T233047Z"] };
      assert.equal(b.t.icsQuelle(due), true);
      const occurrences = b.t.icsExpansion(due, Date.parse("2026-10-21T00:00Z"), Date.parse("2026-10-23T00:00Z"), true);
      assert.equal(occurrences.length, 1); assert.equal(occurrences[0].faellig, "2026-10-22"); assert.equal(occurrences[0].faelligZeit, "01:30:47");
      assert.equal(occurrences[0].startDatum, ""); assert.equal(occurrences[0].startZeit, "", "A DUE-only task is not a start/end window");
      assert.equal(occurrences[0].icsEndUtc, Date.parse("2026-10-21T23:30:47Z"));
      const legacy = { id: "legacy", uid: "unchanged-uid", datum: "2026-01-31", zeit: "23:30", endZeit: "23:45", wiederholung: { art: "monthly", intervall: 1, bis: "2026-04-30" }, geaendert: 1234,
        syncQuellen: { fixture: { etag: "keep-etag", revision: "keep-revision" } }, icsRoundtrip: ["UID:unchanged-uid", "SEQUENCE:7", "X-PROVIDER:keep"],
        icsAusnahmen: ["2026-02-28"], icsZusatzTermine: [{ datum: "2026-02-15", zeit: "22:10" }] };
      const sourceBook = { termine: [legacy,
        { id: "floating", datum: "2026-01-01", zeit: "12:00", icsRoundtrip: ["DTSTART:20260101T120059"] },
        { id: "date-only", datum: "2026-01-01", zeit: "", icsRoundtrip: [] }],
        aufgaben: [{ id: "legacy-due", faellig: "2026-10-21", faelligZeit: "23:30", icsRoundtrip: [] }] };
      const beforePlan = JSON.stringify(sourceBook);
      const plan = b.t.zeitzonenVerankerungsPlan(sourceBook, "Europe/Berlin");
      assert.equal(JSON.stringify(sourceBook), beforePlan, "Preparing a zone change must not mutate the book");
      assert.equal(plan.length, 2, "Floating and all-day entries retain their original semantics");
      const anchored = plan.find(item => item.entry.id === "legacy").next;
      assert.equal(anchored.uid, legacy.uid); assert.equal(anchored.geaendert, legacy.geaendert);
      assert.equal(JSON.stringify(anchored.syncQuellen), JSON.stringify(legacy.syncQuellen));
      for (const line of legacy.icsRoundtrip) assert.ok(anchored.icsRoundtrip.includes(line));
      const expand = entry => b.t.icsExpansion(entry, Date.parse("2026-01-01T00:00Z"), Date.parse("2026-05-02T00:00Z"));
      assert.deepEqual(Array.from(expand(anchored), item => item.datum), ["2026-01-31", "2026-02-15", "2026-03-31", "2026-04-30"], "Month-end clamping, additions and exclusions survive anchoring");
      const absoluteBefore = Array.from(expand(anchored), item => item.icsStartUtc);
      b.t.daten().einstellungen.regional.timeZone = "Asia/Tokyo";
      assert.deepEqual(Array.from(expand(anchored), item => item.icsStartUtc), absoluteBefore, "A display-zone change cannot move a series or its exceptions");
      assert.deepEqual(Array.from(expand(anchored), item => item.datum), ["2026-02-01", "2026-02-16", "2026-04-01", "2026-05-01"]);
      const leap = b.t.zeitzonenVerankerungsPlan({ termine: [{ datum: "2024-02-29", zeit: "12:00", wiederholung: { art: "yearly", bis: "2028-12-31" } }] }, "Europe/Berlin")[0].next;
      assert.deepEqual(Array.from(b.t.icsExpansion(leap, Date.parse("2024-01-01Z"), Date.parse("2029-01-01Z")), item => item.datum), ["2024-02-29", "2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29"]);
      assert.equal(b.t.zeitzonenVerankerungsPlan({ termine: [anchored], aufgaben: [plan.find(item => item.entry.id === "legacy-due").next] }, "Asia/Tokyo").length, 0, "Anchoring is idempotent");
      console.log("TIME ZONE PLANNING PASS: display versus planning, midnight, seconds, DST gap/fold and quarter-hour zone " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
