"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js"), harness = new Module(file, module);
harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("MCP entry-zone test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { kontakte: [{ id: "owned-linked", vorname: "Owned", vcardRoundtrip: ["TZ:America/New_York"] }, { id: "owned-unrelated", vorname: "Other", land: "US" }],
      termine: [{ id: "owned-point", uid: "stable-point-uid", kontaktId: "owned-linked", titel: "Private title must not enter timing preview", datum: "2026-10-22", zeit: "01:30", endZeit: "02:30", geaendert: 1234, icsAnzeigeZeitzone: "Europe/Berlin",
        icsRoundtrip: ["UID:stable-point-uid", "DTSTART:20261021T233047Z", "DTEND:20261022T003047Z", "X-OWNED:retained"] },
        { id: "owned-series", uid: "stable-series-uid", datum: "2026-10-22", zeit: "01:30", icsRoundtrip: ["DTSTART:20261021T233047Z", "RRULE:FREQ=DAILY", "EXDATE:20261023T233047Z"] }],
      aufgaben: [{ id: "owned-due", uid: "stable-due-uid", kontaktId: "owned-linked", titel: "Owned due", faellig: "2026-10-22", faelligZeit: "01:30", icsAnzeigeZeitzone: "Europe/Berlin", icsRoundtrip: ["DUE:20261021T233047Z"] }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      Object.assign(b.t.daten().einstellungen.regional, { timeZone: "Europe/Berlin", timeZoneManagement: "manual" });
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => { post(text); const message = JSON.parse(text); if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true })); };
      let sequence = 0;
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "b".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(value => value.cmd === "mcp_antwort" && value.invocation === invocation)?.response;
      }
      const call = async (name, args) => (await rpc("tools/call", { name, arguments: args })).result;
      const ok = value => { assert.equal(value?.isError, false, JSON.stringify(value)); return value.structuredContent; };
      const fail = (value, code) => { assert.equal(value.isError, true, JSON.stringify(value)); assert.equal(value.structuredContent.code, code); };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-entry-zone", version: "1" } }); await rpc("notifications/initialized", {});
      const read = async (id = "owned-point", task = false) => ok(await call(task ? "organizer_task_read" : "organizer_appointment_read", { id }));
      const contact = ok(await call("organizer_contact_read", { id: "owned-linked", fields: ["id"] }));
      let current = await read();
      const args = { entry_type: "appointment", id: "owned-point", expected_revision: current.revision, mode: "display", contact_id: "owned-linked", expected_contact_revision: contact.revision };
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
      const preview = ok(await call("organizer_entry_time_zone_preview", args));
      assert.equal(preview.start_time, "19:30:47"); assert.equal(preview.start_date, "2026-10-21"); assert.equal(preview.persisted, false); assert.equal(preview.instant_changed, false);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); assert.ok(!JSON.stringify(preview).includes("Private title"));
      fail(await call("organizer_entry_time_zone_apply", { ...args, expected_contact_revision: "0".repeat(64) }), "conflict");
      fail(await call("organizer_entry_time_zone_apply", { ...args, contact_id: "owned-unrelated" }), "invalid_selection");
      const shown = ok(await call("organizer_entry_time_zone_apply", args)); assert.equal(shown.persisted, true);
      const event = b.t.daten().termine.find(value => value.id === "owned-point");
      assert.equal(event.uid, "stable-point-uid"); assert.equal(event.geaendert, 1234); assert.equal(event.zeit, "19:30"); assert.ok(event.icsRoundtrip.includes("DTSTART:20261021T233047Z"));
      fail(await call("organizer_entry_time_zone_apply", args), "conflict");
      current = await read();
      const local = { ...args, expected_revision: current.revision, mode: "plan", start_date: "2026-11-01", start_time: "01:30:47", end_date: "2026-11-01", end_time: "02:00:47" };
      const preFold = JSON.stringify(event);
      fail(await call("organizer_entry_time_zone_apply", local), "invalid_settings"); assert.equal(JSON.stringify(event), preFold);
      const planned = ok(await call("organizer_entry_time_zone_apply", { ...local, start_fold: "later" }));
      assert.equal(planned.start_utc_ms, Date.parse("2026-11-01T06:30:47Z")); assert.equal(planned.instant_changed, true);
      assert.ok(event.icsRoundtrip.includes("DTSTART:20261101T063047Z") && event.icsRoundtrip.includes("X-MAGNOLIE-PLANNING-TZID:America/New_York"));
      assert.equal(event.uid, "stable-point-uid"); assert.ok(event.icsRoundtrip.includes("X-OWNED:retained"));
      const series = await read("owned-series"), seriesImage = JSON.stringify(b.t.daten().termine.find(value => value.id === "owned-series"));
      fail(await call("organizer_entry_time_zone_apply", { entry_type: "appointment", id: "owned-series", expected_revision: series.revision, mode: "plan", time_zone: "Asia/Tokyo" }), "unsupported_feature");
      assert.equal(JSON.stringify(b.t.daten().termine.find(value => value.id === "owned-series")), seriesImage);
      const due = await read("owned-due", true);
      const taskPlan = ok(await call("organizer_entry_time_zone_apply", { entry_type: "task", id: "owned-due", expected_revision: due.revision, mode: "plan", contact_id: "owned-linked", expected_contact_revision: contact.revision }));
      assert.equal(taskPlan.start_utc_ms, null); assert.equal(taskPlan.end_utc_ms, Date.parse("2026-10-22T05:30:47Z"));
      const task = b.t.daten().aufgaben.find(value => value.id === "owned-due"); assert.equal(task.startZeit, ""); assert.ok(!task.icsRoundtrip.some(line => /^DTSTART[;:]/.test(line)));
      current = await read();
      ok(await call("organizer_appointment_update", { id: event.id, expected_revision: current.revision, end_time: "03:00" }));
      assert.ok(event.icsRoundtrip.includes("DTSTART:20261101T063047Z") && event.icsRoundtrip.includes("DTEND:20261101T080000Z"), "Ordinary MCP editing lost the saved context or unchanged fold/seconds");
      current = await read(); const beforeGap = JSON.stringify(event);
      fail(await call("organizer_appointment_update", { id: event.id, expected_revision: current.revision, start_date: "2026-03-08", start_time: "02:30", end_time: "04:00" }), "invalid_settings");
      assert.equal(JSON.stringify(event), beforeGap, "Rejected ordinary MCP local-clock edit mutated the record");
      current = await read(); b.t.oeffneTerminBlatt(null, "2026-10-24"); b.input("#tb-titel", "Owned entry-zone draft");
      const dirtyArgs = { entry_type: "appointment", id: "owned-point", expected_revision: current.revision, mode: "display", time_zone: "Asia/Tokyo" };
      fail(await call("organizer_entry_time_zone_apply", dirtyArgs), "editor_busy"); ok(await call("organizer_entry_time_zone_preview", dirtyArgs));
      assert.equal(b.w.document.querySelector("#tb-titel").value, "Owned entry-zone draft");
      console.log("MCP ENTRY ZONES PASS: record/contact CAS, explicit association, private timing preview, same instant versus planning, fold wire, series retention, due-only shape and draft guards " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
