"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve)), plain = value => JSON.parse(JSON.stringify(value));
const watchdog = setTimeout(() => { console.error("Entry time-zone UI timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "linked-ny", vorname: "Owned NY", vcardRoundtrip: ["TZ:America/New_York"] }, { id: "linked-unknown", vorname: "Unknown zone", land: "US" }],
      termine: [{ id: "entry-event", uid: "keep-event-uid", kontaktId: "linked-ny", titel: "Owned event", datum: "2026-10-22", zeit: "01:30", endZeit: "02:30", geaendert: 1234, icsAnzeigeZeitzone: "Europe/Berlin",
        icsRoundtrip: ["UID:keep-event-uid", "DTSTART:20261021T233047Z", "DTEND:20261022T003047Z", "X-OWNED:keep"] }],
      aufgaben: [{ id: "entry-due", uid: "keep-due-uid", kontaktId: "linked-unknown", titel: "Owned due", faellig: "2026-10-22", faelligZeit: "01:30", icsAnzeigeZeitzone: "Europe/Berlin", icsRoundtrip: ["DUE:20261021T233047Z"] }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin", timeZoneManual: "Europe/Berlin", timeZoneManagement: "manual" });
      const native = plain(b.t.daten().einstellungen.regional), event = b.t.daten().termine[0], task = b.t.daten().aufgaben[0];
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "regional_einstellungen_status") queueMicrotask(() => b.w.App.regionalStand({ requestId: message.requestId, ok: true, regional: plain(native), time_zone_preview_version: 1, book_source: "e".repeat(64) }));
        if (message.cmd === "regional_einstellungen" || message.cmd === "zeitzone_erkennen") throw new Error("An entry timing action queried location or changed global preferences");
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
      };
      const field = id => { const value = b.w.document.getElementById(id); assert.ok(value, id); return value; };
      const choose = (id, value) => { const element = field(id); element.value = element.dataset.datumText === "ja" ? value.split("-").reverse().join(".") : value; element.dispatchEvent(new b.w.Event("input", { bubbles: true })); element.dispatchEvent(new b.w.Event("change", { bubbles: true })); };
      async function until(condition, label) { for (let n = 0; n < 500 && !condition(); n++) await tick(); assert.ok(condition(), label || b.w.document.querySelector("#zettel")?.textContent); }
      const cancel = id => field(id).dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      async function manager() {
        b.t.oeffneEinstellungen(); field("einst-tab-ort").click(); field("ort-zeitzonenmanagement").click(); await until(() => b.w.document.getElementById("zeitzonenverwaltung"), "Manager did not open");
      }
      async function open(kind, id) {
        await manager(); choose("zeitzonen-bereich", kind === "task" ? "tasks" : "calendar"); choose("zeitzonen-eintrag", id);
        assert.equal(field("zeitzonen-eintrag-oeffnen").disabled, false); field("zeitzonen-eintrag-oeffnen").click();
        await until(() => b.w.document.getElementById("eintrags-zeitzone"), "Entry dialog did not open");
      }
      const original = JSON.stringify(event);
      await open("appointment", event.id); choose("eintrags-zeitzone-kontakt", "linked-ny");
      await until(() => field("eintrags-zeitzone-zone").value === "America/New_York" && !field("eintrags-zeitzone-zone").disabled);
      assert.equal(field("eintrags-zeitzone-von-datum").dataset.datumIso || field("eintrags-zeitzone-von-datum").value, "2026-10-21"); assert.equal(field("eintrags-zeitzone-von-zeit").value, "19:30:47");
      assert.equal(field("eintrags-zeitzone-von-zeit").disabled, true); assert.equal(JSON.stringify(event), original);
      cancel("eintrags-zeitzone"); assert.equal(JSON.stringify(event), original);
      await open("appointment", event.id); choose("eintrags-zeitzone-kontakt", "linked-ny");
      await until(() => field("eintrags-zeitzone-zone").value === "America/New_York" && !field("eintrags-zeitzone-zone").disabled);
      choose("eintrags-zeitzone-modus", "plan");
      choose("eintrags-zeitzone-von-datum", "2026-11-01"); choose("eintrags-zeitzone-von-zeit", "01:30:47");
      choose("eintrags-zeitzone-bis-datum", "2026-11-01"); choose("eintrags-zeitzone-bis-zeit", "02:00:47");
      assert.equal(field("eintrags-zeitzone-anwenden").disabled, true, "Ambiguous local time needs an explicit fold choice");
      choose("eintrags-zeitzone-von-fold", "later"); assert.equal(field("eintrags-zeitzone-anwenden").disabled, false);
      field("eintrags-zeitzone-anwenden").click();
      await until(() => event.icsRoundtrip.includes("DTSTART:20261101T063047Z"), "Later fold was not stored as the chosen UTC point");
      assert.equal(event.uid, "keep-event-uid"); assert.ok(event.icsRoundtrip.includes("X-OWNED:keep"));
      assert.equal(b.w.document.getElementById("eintrags-zeitzone"), null); await tick();
      await open("appointment", event.id); choose("eintrags-zeitzone-kontakt", "linked-ny");
      await until(() => field("eintrags-zeitzone-zone").value === "America/New_York" && !field("eintrags-zeitzone-zone").disabled);
      const priorConflict = JSON.stringify(event); b.t.daten().kontakte.find(value => value.id === "linked-ny").vcardRoundtrip = ["TZ:Asia/Tokyo"];
      field("eintrags-zeitzone-anwenden").click();
      await until(() => field("eintrags-zeitzone").textContent.includes("changed before planning"));
      assert.equal(field("eintrags-zeitzone-anwenden").disabled, true); assert.equal(JSON.stringify(event), priorConflict); cancel("eintrags-zeitzone");
      b.t.daten().kontakte.find(value => value.id === "linked-ny").vcardRoundtrip = ["TZ:America/New_York"];
      await open("task", task.id); choose("eintrags-zeitzone-kontakt", "linked-unknown");
      await until(() => field("eintrags-zeitzone").textContent.includes("unavailable"));
      assert.equal(field("eintrags-zeitzone-anwenden").disabled, true, "A country-only contact must not silently choose the own zone");
      cancel("eintrags-zeitzone"); task.kontaktId = "linked-ny"; await open("task", task.id);
      choose("eintrags-zeitzone-kontakt", "linked-ny"); await until(() => field("eintrags-zeitzone-zone").value === "America/New_York" && !field("eintrags-zeitzone-zone").disabled);
      choose("eintrags-zeitzone-modus", "plan"); assert.equal(field("eintrags-zeitzone-von-zeit").disabled, true); assert.equal(field("eintrags-zeitzone-bis-zeit").disabled, false);
      field("eintrags-zeitzone-anwenden").click(); await until(() => task.icsRoundtrip.includes("DUE:20261022T053047Z"));
      assert.equal(task.startDatum, ""); assert.equal(task.startZeit, ""); assert.ok(!task.icsRoundtrip.some(line => /^DTSTART[;:]/.test(line))); await tick();
      await manager(); choose("zeitzonen-bereich", "calendar"); choose("zeitzonen-kalender", "contact"); choose("zeitzonen-eintrag", event.id);
      assert.equal(field("zeitzonen-eintrag-oeffnen").disabled, true, "Opening an entry action must not discard a changed management draft"); cancel("zeitzonenverwaltung");
      assert.equal(b.t.daten().einstellungen.regional.timeZone, "Europe/Berlin");
      console.log("ENTRY ZONE UI PASS: manager navigation, same-point preview/cancel, deliberate contact clock, fold choice, stale-contact fence, unknown-zone rejection and due-only shape " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
