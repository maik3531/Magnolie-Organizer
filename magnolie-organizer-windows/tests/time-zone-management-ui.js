"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "baueSeiteRegional, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value)), tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Time-zone management UI timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "owned-zone-contact", vorname: "Owned", nachname: "Fixture", land: "US", vcardRoundtrip: ["X-OWNED:retained"] }],
      termine: [{ id: "owned-all-day", titel: "Owned all day", datum: "2026-10-22", zeit: "" }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin", timeZoneManagement: "off", timeZoneManual: "Europe/Berlin", timeZoneDetection: "phone" });
      let native = plain(b.t.daten().einstellungen.regional), version = 1, detectedZone = "Asia/Tokyo", writes = 0, detections = 0, savedImage = null;
      const owner = "c".repeat(64), contact = b.t.daten().kontakte[0], allDay = JSON.stringify(b.t.daten().termine[0]);
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "regional_einstellungen_status") queueMicrotask(() => b.w.App.regionalStand({ requestId: message.requestId, ok: true, regional: plain(native), time_zone_preview_version: version, book_source: owner }));
        if (message.cmd === "regional_einstellungen") {
          writes++; assert.deepEqual(message.expectedRegional, native); assert.equal(message.expectedBookSource, owner);
          native = plain(message.regional); queueMicrotask(() => b.w.App.regionalErgebnis({ requestId: message.requestId, ok: true, regional: plain(native) }));
        }
        if (message.cmd === "speichern") queueMicrotask(() => { savedImage = JSON.parse(message.text); b.w.App.gespeichert({ id: message.id, ok: true }); });
        if (message.cmd === "zeitzone_erkennen") {
          detections++; assert.equal(native.timeZoneManagement, "automatic"); assert.equal(message.expectedBookSource, owner);
          assert.equal(savedImage?.einstellungen.regional.timeZoneManagement, "automatic", "Detection began before opt-in was durably saved");
          const now = Date.now(); queueMicrotask(() => b.w.App.zeitzonenErgebnis({ requestId: message.requestId, ok: true, book_source: owner, regional: plain(native), native_changed: false,
            automatic: true, time_zone: detectedZone, source: native.timeZoneDetection, captured_ms: now, checked_at_ms: now, fallback: false }));
        }
      };
      const field = id => { const value = b.w.document.getElementById(id); assert.ok(value, id); return value; };
      const choose = (id, value) => { const select = field(id); select.value = value; assert.equal(select.value, value); select.dispatchEvent(new b.w.Event("change", { bubbles: true })); };
      const enabled = () => { field("zeitzonen-aktiv").checked = true; field("zeitzonen-aktiv").dispatchEvent(new b.w.Event("change", { bubbles: true })); };
      async function until(condition, label = "Expected UI state") { for (let index = 0; index < 500 && !condition(); index++) await tick(); assert.ok(condition(), label + ": " + (b.w.document.querySelector("#zettel")?.textContent || "")); }
      async function open() {
        b.t.oeffneEinstellungen(); field("einst-tab-ort").click(); field("ort-zeitzonenmanagement").focus(); field("ort-zeitzonenmanagement").click();
        await until(() => b.w.document.getElementById("zeitzonenverwaltung"), "Time-zone management dialog did not open");
      }
      const cancel = () => field("zeitzonenverwaltung").dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      const before = JSON.stringify(b.t.daten());
      await open();
      assert.equal(field("zeitzonen-aktiv").checked, false); assert.equal(field("zeitzonen-manuell").disabled, true); assert.equal(field("zeitzonen-erkennen").disabled, true);
      assert.equal(field("zeitzonenverwaltung").querySelector('label[for="zeitzonen-manuell"]').control, field("zeitzonen-manuell"), "Zone picker label must address the actual control");
      enabled();
      const zone = field("zeitzonen-manuell");
      assert.ok(Array.from(zone.options).find(option => option.value === "America/New_York").textContent.includes("New York"));
      choose("zeitzonen-bereich", "contacts"); choose("zeitzonen-kontakt", contact.id);
      await until(() => b.w.document.getElementById("zeitzonen-kontakt-zone"));
      assert.equal(field("zeitzonen-kontakt-zone").value, "", "A US country value must not invent one contact zone");
      choose("zeitzonen-kontakt-zone", "America/New_York");
      choose("zeitzonen-bereich", "calendar"); choose("zeitzonen-kalender", "contact");
      choose("zeitzonen-bereich", "tasks"); choose("zeitzonen-aufgaben", "source");
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(writes, 0); assert.equal(detections, 0);
      cancel(); assert.equal(b.w.document.getElementById("zeitzonenverwaltung"), null); assert.equal(JSON.stringify(b.t.daten()), before);
      await open(); enabled(); choose("zeitzonen-modus", "automatic"); choose("zeitzonen-quelle", "ip"); choose("zeitzonen-manuell", "America/New_York");
      assert.equal(field("zeitzonen-erkennen").disabled, true, "An unsaved automatic draft cannot query a location source");
      choose("zeitzonen-bereich", "contacts"); choose("zeitzonen-kontakt", contact.id);
      await until(() => b.w.document.getElementById("zeitzonen-kontakt-zone")); choose("zeitzonen-kontakt-zone", "America/New_York");
      choose("zeitzonen-bereich", "sync"); choose("zeitzonen-kalender", "contact"); choose("zeitzonen-aufgaben", "source");
      field("zeitzonen-speichern").click();
      await until(() => b.t.daten().einstellungen.regional.timeZone === "Asia/Tokyo");
      assert.equal(native.timeZoneManagement, "automatic"); assert.equal(native.timeZoneManual, "America/New_York");
      assert.equal(native.timeZoneCalendarDisplay, "contact"); assert.equal(native.timeZoneTaskDisplay, "source"); assert.equal(detections, 1);
      assert.ok(contact.vcardRoundtrip.includes("TZ:America/New_York") && contact.vcardRoundtrip.includes("X-OWNED:retained"));
      assert.equal(JSON.stringify(b.t.daten().termine[0]), allDay, "A timezone preference moved or rewrote an all-day record");
      assert.equal(b.w.document.getElementById("zeitzonenverwaltung"), null);
      await tick();
      detectedZone = "Europe/London";
      await open(); assert.equal(field("zeitzonen-erkennen").disabled, false);
      const beforePreview = JSON.stringify(b.t.daten()), writesBefore = writes;
      field("zeitzonen-erkennen").click(); await until(() => field("zeitzonenverwaltung").textContent.includes("London"));
      assert.equal(JSON.stringify(b.t.daten()), beforePreview); assert.equal(writes, writesBefore); assert.equal(native.timeZone, "Asia/Tokyo");
      cancel();
      version = 0; await open(); assert.equal(field("zeitzonen-speichern").disabled, true); assert.equal(field("zeitzonen-erkennen").disabled, true); cancel();
      assert.equal(JSON.stringify(b.t.daten()), beforePreview);
      version = 1; b.t.oeffneEinstellungen();
      const regionalForm = b.w.document.createElement("div"); field("einstellungen-blatt").append(regionalForm); b.t.baueSeiteRegional(regionalForm);
      assert.equal(field("regional-zeitzone").tagName, "SELECT"); assert.equal(field("regional-zeitzone").disabled, true);
      const detectionsBeforeRegionalSave = detections;
      choose("regional-stunden", "h12"); field("regional-speichern").click();
      await until(() => b.t.daten().einstellungen.regional.hourCycle === "h12", "Regional form Save was blocked by its own Settings modal");
      assert.equal(native.hourCycle, "h12"); assert.equal(native.timeZoneManagement, "automatic"); assert.equal(detections, detectionsBeforeRegionalSave);
      assert.equal(JSON.stringify(b.t.daten().termine[0]), allDay);
      console.log("TIME ZONE MANAGEMENT UI PASS: Country page entry, scopes, readable IANA choices, labels, draft/cancel, saved opt-in, contact TZ, source preview and all-day retention " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
