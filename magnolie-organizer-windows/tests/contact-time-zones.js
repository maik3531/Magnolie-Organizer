"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktFormular, kontaktZeitzone, kontaktOrtszeit, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("Contact timezone test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const lines = ["TZ;TYPE=WORK:America/New_York", "URL:https://example.test", "X-OWNED:preserved"];
    const b = await harness.exports.boot(web, { kontakte: [{ id: "timezone", vorname: "Timezone", nachname: "Fixture", land: "US", vcardRoundtrip: lines }] });
    try {
      const regional = b.t.daten().einstellungen.regional;
      Object.assign(regional, { timeZone: "Europe/Berlin", timeZoneManagement: "manual", hourCycle: "h23", formatLocale: "en-GB" });
      const contact = b.t.daten().kontakte.find(item => item.id === "timezone");
      const point = new b.w.Date("2026-10-21T23:30:00Z");
      const clock = b.t.kontaktOrtszeit(b.t.kontaktZeitzone(contact), point);
      assert.ok(clock.text.includes("21/10/2026") && clock.text.includes("19:30"), "Contact local clock must retain its own date across midnight");
      assert.equal(b.t.kontaktOrtszeit("Europe/Berlin", point), null, "Same zone must not pretend a foreign clock");
      assert.equal(b.t.kontaktZeitzone({ land: "US", vcardRoundtrip: [] }), "", "A multi-zone country is not an unambiguous timezone");
      assert.equal(b.t.kontaktZeitzone({ vcardRoundtrip: ["TZ:America/New_York", "TZ:Asia/Tokyo"] }), "", "Conflicting source zones must remain ambiguous");
      assert.equal(b.t.kontaktZeitzone({ vcardRoundtrip: ["TZ:America/New_York", "TZ:+0900"] }), "", "An unresolved second TZ must not be ignored");
      assert.equal(b.t.kontaktKarte(contact).querySelector(".kontakt-ortszeit").hidden, false);
      regional.timeZoneManagement = "off";
      const disabledForm = b.t.kontaktFormular(contact);
      assert.equal(disabledForm.querySelector("#kontakt-zeitzone"), null, "A disabled timezone manager must not add a timezone editor to contacts");
      assert.equal(b.t.kontaktOrtszeit("America/New_York", point), null);
      assert.equal(b.t.kontaktKarte(contact).querySelector(".kontakt-ortszeit").hidden, true);
      regional.timeZoneManagement = "manual";
      let form = b.t.kontaktFormular(contact); b.w.document.body.append(form);
      assert.equal(form.querySelector("#kontakt-zeitzone").value, "America/New_York");
      const save = () => [...form.querySelectorAll("button")].find(button => ["Save", "Save changes"].includes(button.textContent)).click();
      save(); assert.deepEqual(Array.from(contact.vcardRoundtrip), lines, "An unchanged imported TZ must retain its type and provider metadata");
      form.remove(); form = b.t.kontaktFormular(contact); b.w.document.body.append(form);
      const input = form.querySelector("#kontakt-zeitzone"); input.value = "Mars/Olympus"; input.dispatchEvent(new b.w.Event("input"));
      save(); assert.deepEqual(Array.from(contact.vcardRoundtrip), lines, "An unknown zone must not overwrite the original contact");
      input.value = "Asia/Tokyo"; input.dispatchEvent(new b.w.Event("input")); save();
      assert.equal(b.t.kontaktZeitzone(contact), "Asia/Tokyo");
      assert.ok(contact.vcardRoundtrip.includes("URL:https://example.test") && contact.vcardRoundtrip.includes("X-OWNED:preserved"));
      const tokyo = b.t.kontaktOrtszeit("Asia/Tokyo", point);
      assert.ok(tokyo.text.includes("22/10/2026") && tokyo.text.includes("08:30"));
      form.remove(); if (b.saves().length) b.ack();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
      };
      let sequence = 0;
      const rpc = async (method, params) => {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "c".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "timezone-fixture", version: "1" } });
      await rpc("notifications/initialized", {});
      const read = (await rpc("tools/call", { name: "organizer_contact_read", arguments: { id: contact.id, fields: ["vorname"] } })).result;
      assert.equal(read.isError, false); assert.equal(read.structuredContent.time_zone, "Asia/Tokyo");
      assert.equal(read.structuredContent.local_time.zone, "Asia/Tokyo");
      const updated = (await rpc("tools/call", { name: "organizer_contact_update", arguments: { id: contact.id, expected_revision: read.structuredContent.revision, time_zone: "Europe/London" } })).result;
      assert.equal(updated.isError, false, JSON.stringify(updated)); assert.equal(b.t.kontaktZeitzone(contact), "Europe/London");
      const current = async () => (await rpc("tools/call", { name: "organizer_contact_read", arguments: { id: contact.id } })).result.structuredContent;
      let latest = await current(); const beforeInvalid = JSON.stringify(contact);
      const invalid = (await rpc("tools/call", { name: "organizer_contact_update", arguments: { id: contact.id, expected_revision: latest.revision, time_zone: "Mars/Olympus" } })).result;
      assert.equal(invalid.isError, true); assert.equal(JSON.stringify(contact), beforeInvalid);
      contact.vcardRoundtrip.push("TZ:Asia/Tokyo"); latest = await current();
      assert.equal(latest.time_zone, ""); assert.equal(latest.local_time, null);
      const cleared = (await rpc("tools/call", { name: "organizer_contact_update", arguments: { id: contact.id, expected_revision: latest.revision, time_zone: "" } })).result;
      assert.equal(cleared.isError, false, JSON.stringify(cleared));
      assert.ok(!contact.vcardRoundtrip.some(line => /^TZ[;:]/i.test(line)), "Explicit clearing must remove conflicting source annotations");
      assert.ok(contact.vcardRoundtrip.includes("X-OWNED:preserved"));
      console.log("CONTACT TIME ZONES PASS: explicit IANA, unknown/multiple zones, midnight clock, disabled/same zone, editor/raw metadata and MCP SaveACK " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
