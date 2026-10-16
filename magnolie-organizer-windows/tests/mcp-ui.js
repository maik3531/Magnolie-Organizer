"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("MCP UI test timed out"); process.exit(1); }, 15000);
let declaredContracts;
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, {
      notizen: [{ id: "fixture-note", titel: "Fixture", text: "Owned fixture only" }],
      kontakte: [{ id: "fixture-contact", uid: "owned-contact-uid", vorname: "Owned", nachname: "Existing contact", sync: true,
        syncQuellen: { fixture: { marker: "preserve" } }, vcardRoundtrip: ["BEGIN:VCARD", "VERSION:3.0", "UID:owned-contact-uid", "X-OWNED-FIXTURE:preserve", "END:VCARD"] }],
      termine: [{ id: "imported-appointment", uid: "owned-event-uid", datum: "2026-11-20", zeit: "08:00", endZeit: "09:00",
        titel: "Imported appointment fixture", wiederholung: { art: "daily", bis: "" }, sync: true,
        syncKalenderUid: "owned-old-calendar", kalenderQuelle: { id: "owned-old-calendar", name: "Owned old source" },
        syncQuellen: { "owned-old-calendar": { marker: "preserve" } }, providerMetadaten: { fixture: { marker: "preserve" } },
        icsRoundtrip: ["BEGIN:VEVENT", "UID:owned-event-uid", "DTSTART:20261120T080000Z", "DTEND:20261120T090000Z",
          "RRULE:FREQ=DAILY", "X-OWNED-FIXTURE:preserve", "BEGIN:VALARM", "TRIGGER;VALUE=DATE-TIME:20261119T200000Z",
          "ACTION:DISPLAY", "DESCRIPTION:Owned fixture", "END:VALARM", "END:VEVENT"] },
        { id: "readonly-appointment", uid: "owned-readonly-uid", datum: "2026-11-30", titel: "Read-only fixture", icsReadOnly: true },
        { id: "zero-appointment", uid: "owned-zero-uid", datum: "2026-11-21", zeit: "08:00", endZeit: "", titel: "Zero duration fixture",
          icsEndeFehlt: true, icsNullDauer: true, icsRoundtrip: ["BEGIN:VEVENT", "UID:owned-zero-uid", "DTSTART:20261121T080000Z", "END:VEVENT"] }],
      aufgaben: [{ id: "imported-task", uid: "imported-fixture-uid", titel: "Imported fixture",
        faellig: "2026-11-01", startDatum: "2026-11-01", startZeit: "08:00", faelligZeit: "09:00",
        icsElternUid: "unresolved-owned-parent", icsElternQuelleId: "owned-source", icsQuelleId: "owned-source",
        icsRoundtrip: ["BEGIN:VTODO", "UID:imported-fixture-uid", "DTSTART:20261101T080000Z", "DUE:20261101T090000Z",
          "RRULE:FREQ=DAILY", "X-OWNED-FIXTURE:preserve", "END:VTODO"],
        sync: true, syncQuellen: { fixture: { marker: "preserve" } } }]
    });
    try {
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const session = "a".repeat(48);
      let sequence = 0;
      async function call(message) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session, invocation, message });
        const reply = b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation);
        assert.ok(reply, "Every accepted native invocation must settle");
        assert.equal(reply.session, session);
        return reply.response;
      }
      const request = (id, method, params) => ({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
      assert.equal((await call(request(1, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fixture", version: "1" } }))).result.serverInfo.name, "magnolie-organizer");
      assert.equal(await call({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
      const descriptors = (await call(request(2, "tools/list"))).result.tools;
      for (const tool of descriptors) {
        assert.equal(tool.inputSchema.type, "object", tool.name);
        assert.equal(tool.outputSchema.type, "object", tool.name);
        assert.ok(tool.outputSchema.required.length > 0, tool.name + ": untyped result envelope");
      }
      const contracts = JSON.parse(JSON.stringify(descriptors));
      if (declaredContracts) assert.deepEqual(contracts, declaredContracts, "Both native products must expose the same MCP contracts");
      else declaredContracts = contracts;
      const tools = descriptors.map(tool => tool.name);
      assert.ok(tools.includes("organizer_data_read") && tools.includes("organizer_settings_read"));
      const availability = (await call(request(110, "tools/call", { name: "organizer_status" }))).result.structuredContent;
      assert.ok(availability.supportedSocialServices.includes("teams"));
      if (!availability.supportedSocialServices.includes("teams-call")) {
        const before = b.t.daten().kontakte.length;
        const unsupported = await call(request(111, "tools/call", { name: "organizer_contact_create", arguments: {
          first_name: "Unsupported fixture", social: [{ service: "teams-call", value: "owned-fixture" }] } }));
        assert.equal(unsupported.result.structuredContent.code, "unsupported_feature");
        assert.equal(b.t.daten().kontakte.length, before);
      }
      const notes = await call(request(3, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen", limit: 1 } }));
      assert.equal(notes.result.isError, false);
      assert.equal(notes.result.structuredContent.entries[0].id, "fixture-note");
      notes.result.structuredContent.entries[0].titel = "Do not mutate source";
      assert.equal(b.t.daten().notizen[0].titel, "Fixture");
      const item = await call(request(4, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen", id: "fixture-note" } }));
      assert.equal(item.result.structuredContent.entry.text, "Owned fixture only");
      const bad = await call(request(5, "tools/call", { name: "organizer_data_read", arguments: { section: "__proto__" } }));
      assert.equal(bad.error.code, -32602);
      // Settle the normal startup migration save before exercising MCP writes.
      if (b.saves().length) b.ack();
      await new Promise(resolve => setImmediate(resolve));
      const noteId = "33333333-3333-4333-8333-333333333333";
      let createdReplied = false;
      const created = call(request(30, "tools/call", { name: "organizer_note_create", arguments: {
        id: noteId, title: "Created fixture", text: "<img src=x onerror=alert(1)>\nPlain text" } })).then(result => { createdReplied = true; return result; });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(createdReplied, false, "MCP create replied before native save acknowledgement");
      const saved = JSON.parse(b.saves().at(-1).text).notizen.find(note => note.id === noteId);
      assert.ok(saved, "MCP mutation did not use the existing native save queue");
      assert.ok(!saved.html.includes("<img"), "Plain text was treated as executable note markup");
      b.ack();
      assert.equal((await created).result.structuredContent.persisted, true);
      const duplicate = await call(request(31, "tools/call", { name: "organizer_note_create", arguments: {
        id: noteId, title: "Retry", text: "Must not duplicate" } }));
      assert.equal(duplicate.result.structuredContent.code, "already_exists");
      assert.equal(b.t.daten().notizen.filter(note => note.id === noteId).length, 1);
      let onSave, onSnapshot;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text);
        const message = JSON.parse(text);
        if (message.cmd === "speichern" && onSave) { const resolve = onSave; onSave = null; resolve(); }
        if (message.cmd === "mutations_snapshot" && onSnapshot) { const resolve = onSnapshot; onSnapshot = null; resolve(message); }
      };
      async function persisted(id, name, args) {
        const saving = new Promise(resolve => { onSave = resolve; });
        const operation = call(request(id, "tools/call", { name, arguments: args }));
        await Promise.race([saving, operation.then(response => { throw new Error("Write settled before native ACK: " + JSON.stringify(response)); })]);
        b.ack();
        const response = await operation;
        assert.equal(response.result.isError, false, JSON.stringify(response));
        assert.equal(response.result.structuredContent.persisted, true);
        return response.result.structuredContent;
      }
      const beforeUpdate = (await call(request(33, "tools/call", { name: "organizer_note_read", arguments: { id: noteId } }))).result.structuredContent;
      assert.match(beforeUpdate.revision, /^[a-f0-9]{64}$/);
      const conflict = await call(request(34, "tools/call", { name: "organizer_note_update", arguments: {
        id: noteId, expected_revision: "0".repeat(64), title: "Stale overwrite" } }));
      assert.equal(conflict.result.structuredContent.code, "conflict");
      assert.equal(b.t.daten().notizen.find(note => note.id === noteId).titel, "Created fixture");
      await persisted(35, "organizer_note_update", { id: noteId, expected_revision: beforeUpdate.revision,
        title: "Updated fixture", text: "<b>still plain text</b>" });
      const afterUpdate = (await call(request(36, "tools/call", { name: "organizer_note_read", arguments: { id: noteId } }))).result.structuredContent;
      assert.equal(afterUpdate.note.titel, "Updated fixture");
      assert.notEqual(afterUpdate.revision, beforeUpdate.revision);
      const removed = await persisted(37, "organizer_note_delete", { id: noteId, expected_revision: afterUpdate.revision });
      assert.ok(removed.trash_id);
      assert.equal(b.t.daten().notizen.some(note => note.id === noteId), false);
      const restored = await persisted(38, "organizer_trash_restore", { id: removed.trash_id });
      assert.equal(restored.restored_id, noteId);
      assert.equal(b.t.daten().notizen.find(note => note.id === noteId).titel, "Updated fixture");
      const appointmentId = "99999999-9999-4999-8999-999999999999";
      await persisted(70, "organizer_appointment_create", { id: appointmentId, title: "Owned appointment fixture", start_date: "2026-12-01",
        location: "Owned room", recurrence: { frequency: "monthly", interval: 2, ordinal: 2, weekday: "MO", until: "2027-02-28" },
        organizer: { name: "Owned organizer", email: "organizer@example.invalid" },
        attendees: [{ name: "Owned attendee", email: "attendee@example.invalid", role: "OPT-PARTICIPANT", rsvp: true }],
        attachments: [{ uri: "https://example.invalid/owned-fixture.pdf", name: "Owned fixture", mime_type: "application/pdf", size: 42 }],
        alarms: [{ offset_minutes: 15 }] });
      const createdAppointment = b.t.daten().termine.find(item => item.id === appointmentId);
      assert.equal(createdAppointment.zeit, "");
      assert.equal(createdAppointment.wiederholung.ordinal, 2);
      assert.equal(createdAppointment.teilnehmer[0].rolle, "OPT-PARTICIPANT");
      assert.equal(createdAppointment.kalenderAnhaenge[0].groesse, 42);
      const invalidTime = await call(request(71, "tools/call", { name: "organizer_appointment_create", arguments: {
        title: "Invalid clock fixture", start_date: "2026-12-01", start_time: "10:00", end_time: "09:00" } }));
      assert.equal(invalidTime.result.structuredContent.code, "invalid_time_range");
      const invalidRepeat = await call(request(72, "tools/call", { name: "organizer_appointment_create", arguments: {
        title: "Invalid repetition fixture", start_date: "2026-12-01", recurrence: { frequency: "custom", dates: ["2026-11-01"] } } }));
      assert.equal(invalidRepeat.result.structuredContent.code, "invalid_recurrence");
      const zero = (await call(request(73, "tools/call", { name: "organizer_appointment_read", arguments: { id: "zero-appointment" } }))).result.structuredContent;
      await persisted(74, "organizer_appointment_update", { id: "zero-appointment", expected_revision: zero.revision, title: "Preserved zero duration" });
      assert.equal(b.t.daten().termine.find(item => item.id === "zero-appointment").endZeit, "");
      assert.ok(!b.t.daten().termine.find(item => item.id === "zero-appointment").icsRoundtrip.some(line => /^DTEND/.test(line)));
      const readonly = (await call(request(75, "tools/call", { name: "organizer_appointment_read", arguments: { id: "readonly-appointment" } }))).result.structuredContent;
      const deniedReadonly = await call(request(76, "tools/call", { name: "organizer_appointment_delete", arguments: {
        id: "readonly-appointment", expected_revision: readonly.revision } }));
      assert.equal(deniedReadonly.result.structuredContent.code, "read_only");
      const importedAppointment = (await call(request(77, "tools/call", { name: "organizer_appointment_read", arguments: { id: "imported-appointment" } }))).result.structuredContent;
      await persisted(78, "organizer_appointment_update", { id: "imported-appointment", expected_revision: importedAppointment.revision,
        title: "Revised imported appointment", alarms: [{ offset_minutes: 30 }] });
      const appointment = b.t.daten().termine.find(item => item.id === "imported-appointment");
      assert.equal(appointment.providerMetadaten.fixture.marker, "preserve");
      assert.ok(appointment.icsRoundtrip.includes("RRULE:FREQ=DAILY") && appointment.icsRoundtrip.includes("X-OWNED-FIXTURE:preserve"));
      assert.ok(appointment.icsRoundtrip.includes("TRIGGER;VALUE=DATE-TIME:20261119T200000Z"));
      b.w.App.edsStatus({ verfuegbar: true, kalender: [{ uid: "owned-old-calendar", name: "Owned old source" }, { uid: "owned-new-calendar", name: "Owned new source" }], adressbuecher: [] });
      const beforeMove = (await call(request(79, "tools/call", { name: "organizer_appointment_read", arguments: { id: "imported-appointment" } }))).result.structuredContent;
      await persisted(80, "organizer_appointment_update", { id: "imported-appointment", expected_revision: beforeMove.revision, calendar_uid: "owned-new-calendar" });
      assert.equal(appointment.syncKalenderUid, "owned-new-calendar");
      assert.equal(appointment.syncQuellen["owned-old-calendar"], undefined);
      assert.ok(b.t.daten().geloescht.termine.some(item => item.uid === "owned-event-uid" && item.syncKalenderUid === "owned-old-calendar"));
      const toRemoveAppointment = (await call(request(81, "tools/call", { name: "organizer_appointment_read", arguments: { id: appointmentId } }))).result.structuredContent;
      const deletedAppointment = await persisted(82, "organizer_appointment_delete", { id: appointmentId, expected_revision: toRemoveAppointment.revision });
      assert.ok(!b.t.daten().termine.some(item => item.id === appointmentId));
      await persisted(83, "organizer_trash_restore", { id: deletedAppointment.trash_id });
      assert.ok(b.t.daten().termine.some(item => item.id === appointmentId));
      const contactId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
      await persisted(90, "organizer_contact_create", { id: contactId, first_name: "Owned", last_name: "New contact",
        phones: [{ value: "+12025550123", types: ["CELL"] }], emails: [{ value: "owned@example.test", label: "Fixture" }],
        addresses: [{ street: "Owned fixture street", postal_code: "00000", city: "Fixture town", country: "US" }],
        groups: ["Owned fixture group"], birth_date: "--02-29", emergency_contacts: [{ contact_id: "fixture-contact", relationship: "Owned link" }],
        social: [{ service: "custom", value: "Owned fixture", symbol: "github", action_type: "website", action_target: "https://example.test/owned-fixture" }] });
      const newContact = b.t.daten().kontakte.find(item => item.id === contactId);
      assert.equal(newContact.email, "owned@example.test");
      assert.equal(newContact.geburtstag, "--02-29");
      assert.equal(newContact.kontaktpersonen[0].kontaktId, "fixture-contact");
      assert.ok(b.t.daten().jahrestage.some(item => item.kontaktId === contactId && item.datum === "--02-29"));
      const projected = (await call(request(91, "tools/call", { name: "organizer_contact_read", arguments: { id: contactId, fields: ["id", "vorname", "geburtstag"] } }))).result.structuredContent;
      assert.equal(projected.contact.geburtstag, "--02-29");
      assert.equal(projected.contact.email, undefined);
      await persisted(92, "organizer_contact_update", { id: contactId, expected_revision: projected.revision, first_name: "Revised owned" });
      assert.equal(newContact.email, "owned@example.test");
      assert.equal(newContact.geburtstag, "--02-29");
      const existingContact = (await call(request(93, "tools/call", { name: "organizer_contact_read", arguments: { id: "fixture-contact" } }))).result.structuredContent;
      await persisted(94, "organizer_contact_update", { id: "fixture-contact", expected_revision: existingContact.revision, note: "Owned changed note" });
      assert.ok(b.t.daten().kontakte.find(item => item.id === "fixture-contact").vcardRoundtrip.includes("X-OWNED-FIXTURE:preserve"));
      assert.equal(b.t.daten().kontakte.find(item => item.id === "fixture-contact").syncQuellen.fixture.marker, "preserve");
      const contactRead = (await call(request(95, "tools/call", { name: "organizer_contact_read", arguments: { id: contactId } }))).result.structuredContent;
      const failureSnapshot = new Promise(resolve => { onSnapshot = resolve; });
      const failedDelete = call(request(96, "tools/call", { name: "organizer_contact_delete", arguments: { id: contactId, expected_revision: contactRead.revision } }));
      const deniedSnapshot = await failureSnapshot;
      assert.equal(deniedSnapshot.reason, "pre-contact-delete");
      assert.ok(b.t.daten().kontakte.some(item => item.id === contactId), "Contact deleted before snapshot ACK");
      b.w.App.mutationsSnapshot({ token: deniedSnapshot.token, ok: false });
      assert.equal((await failedDelete).result.structuredContent.code, "snapshot_failed");
      assert.ok(b.t.daten().kontakte.some(item => item.id === contactId));
      const successSnapshot = new Promise(resolve => { onSnapshot = resolve; });
      const deletingSave = new Promise(resolve => { onSave = resolve; });
      const deleting = call(request(97, "tools/call", { name: "organizer_contact_delete", arguments: { id: contactId, expected_revision: contactRead.revision } }));
      const confirmedSnapshot = await successSnapshot;
      b.w.App.mutationsSnapshot({ token: "wrong", ok: true });
      assert.ok(b.t.daten().kontakte.some(item => item.id === contactId));
      b.w.App.mutationsSnapshot({ token: confirmedSnapshot.token, ok: true });
      await deletingSave; b.ack();
      const deletedContact = (await deleting).result.structuredContent;
      assert.equal(deletedContact.recovery_snapshot_confirmed, true);
      assert.equal(deletedContact.persisted, true);
      assert.ok(!b.t.daten().kontakte.some(item => item.id === contactId));
      assert.ok(!b.t.daten().jahrestage.some(item => item.kontaktId === contactId));
      await persisted(98, "organizer_trash_restore", { id: deletedContact.trash_id });
      assert.ok(b.t.daten().kontakte.some(item => item.id === contactId));
      const imported = (await call(request(40, "tools/call", { name: "organizer_task_read", arguments: { id: "imported-task" } }))).result.structuredContent;
      await persisted(41, "organizer_task_update", { id: "imported-task", expected_revision: imported.revision, title: "Revised imported task" });
      const preserved = b.t.daten().aufgaben.find(task => task.id === "imported-task");
      assert.equal(preserved.syncQuellen.fixture.marker, "preserve");
      assert.equal(preserved.icsElternUid, "unresolved-owned-parent");
      assert.ok(preserved.icsRoundtrip.includes("DTSTART:20261101T080000Z"));
      const importedNow = (await call(request(42, "tools/call", { name: "organizer_task_read", arguments: { id: "imported-task" } }))).result.structuredContent;
      await persisted(43, "organizer_task_update", { id: "imported-task", expected_revision: importedNow.revision, due_time: "10:00" });
      assert.ok(preserved.icsRoundtrip.includes("RRULE:FREQ=DAILY") && preserved.icsRoundtrip.includes("X-OWNED-FIXTURE:preserve"));
      assert.ok(!preserved.icsRoundtrip.some(line => /^(DTSTART|DUE|DURATION)[;:]/.test(line)));
      const badDate = await call(request(44, "tools/call", { name: "organizer_task_create", arguments: { title: "Invalid fixture", due_date: "2026-02-31" } }));
      assert.equal(badDate.result.structuredContent.code, "invalid_date");
      const parentId = "55555555-5555-4555-8555-555555555555", childId = "66666666-6666-4666-8666-666666666666";
      const parent = await persisted(45, "organizer_task_create", { id: parentId, title: "Owned parent" });
      await persisted(46, "organizer_task_create", { id: childId, title: "Owned child", parent_id: parentId });
      assert.equal(b.t.daten().aufgaben.find(task => task.id === childId).elternUid, parent.uid);
      const parentRead = (await call(request(47, "tools/call", { name: "organizer_task_read", arguments: { id: parentId } }))).result.structuredContent;
      const cycle = await call(request(48, "tools/call", { name: "organizer_task_update", arguments: {
        id: parentId, expected_revision: parentRead.revision, parent_id: childId } }));
      assert.equal(cycle.result.structuredContent.code, "invalid_parent");
      const taskRemoved = await persisted(49, "organizer_task_delete", { id: parentId, expected_revision: parentRead.revision });
      assert.equal(taskRemoved.promoted_children[0], childId);
      assert.equal(b.t.daten().aufgaben.find(task => task.id === childId).elternUid, "");
      await persisted(50, "organizer_trash_restore", { id: taskRemoved.trash_id });
      assert.ok(b.t.daten().aufgaben.some(task => task.id === parentId));
      const toDelete = (await call(request(51, "tools/call", { name: "organizer_task_read", arguments: { id: "imported-task" } }))).result.structuredContent;
      const completion = await persisted(54, "organizer_task_set_completed", { id: "imported-task",
        expected_revision: toDelete.revision, completed: true, as_of: "2026-11-02" });
      assert.equal(completion.recurring, true);
      assert.equal(b.t.daten().aufgaben.find(task => task.id === "imported-task").erledigt, false);
      const instance = b.t.daten().aufgaben.find(task => task.id === completion.completed_id);
      assert.equal(instance.erledigt, true);
      const recurrenceId = instance.icsRoundtrip.find(line => /^RECURRENCE-ID[;:]/.test(line));
      const value = recurrenceId.slice(recurrenceId.lastIndexOf(":") + 1);
      const expected = web === path.resolve(__dirname, "../app/web") ? "imported-fixture-uid#" + value :
        "imported-fixture-uid-magnolie-instanz-" + createHash("sha256").update(JSON.stringify([
          recurrenceId.includes(";VALUE=DATE:") ? { VALUE: "DATE" } : {}, value])).digest("hex").slice(0, 16);
      assert.equal(instance.uid, expected, "MCP detached instance must match the native product identity contract");
      assert.ok(preserved.icsRoundtrip.includes(recurrenceId.replace("RECURRENCE-ID", "EXDATE")));
      const retryCompletion = await call(request(55, "tools/call", { name: "organizer_task_set_completed", arguments: {
        id: "imported-task", expected_revision: toDelete.revision, completed: true, as_of: "2026-11-02" } }));
      assert.equal(retryCompletion.result.structuredContent.code, "conflict");
      const instanceRead = (await call(request(56, "tools/call", { name: "organizer_task_read", arguments: { id: instance.id } }))).result.structuredContent;
      await persisted(57, "organizer_task_set_completed", { id: instance.id, expected_revision: instanceRead.revision, completed: false });
      assert.equal(instance.erledigt, false);
      const completedMaster = (await call(request(58, "tools/call", { name: "organizer_task_read", arguments: { id: "imported-task" } }))).result.structuredContent;
      await persisted(52, "organizer_task_delete", { id: "imported-task", expected_revision: completedMaster.revision });
      assert.ok(b.t.daten().geloescht.aufgaben.some(task => task.uid === "imported-fixture-uid" && task.syncQuellen.fixture.marker === "preserve"));
      await b.t.wechsel("aufgaben");
      b.input("#aufgabe-titel", "Owned unsaved draft");
      const noteCount = b.t.daten().notizen.length;
      const busy = await call(request(53, "tools/call", { name: "organizer_note_create", arguments: { title: "External fixture", text: "Must not overwrite the draft" } }));
      assert.equal(busy.result.structuredContent.code, "editor_busy");
      assert.equal(b.t.daten().notizen.length, noteCount);
      assert.equal(b.w.document.querySelector("#aufgabe-titel").value, "Owned unsaved draft");
      const leaving = b.t.wechsel("kalender"); b.answer("Discard"); await leaving;
      b.t.oeffneTerminBlatt(null, "2026-11-11");
      const dialogStatus = await call(request(59, "tools/call", { name: "organizer_status" }));
      assert.equal(dialogStatus.result.structuredContent.dialogOpen, true);
      assert.equal(dialogStatus.result.structuredContent.editorDirty, false);
      const dialogBusy = await call(request(60, "tools/call", { name: "organizer_note_create", arguments: { title: "External fixture", text: "Must not invalidate the open editor" } }));
      assert.equal(dialogBusy.result.structuredContent.code, "dialog_busy");
      assert.ok(b.w.document.querySelector("#termin-schleier"));
      b.w.document.querySelector("#termin-schleier header button").click();
      assert.equal(b.w.document.querySelector("#termin-schleier"), null);
      const failedSave = call(request(32, "tools/call", { name: "organizer_note_create", arguments: { title: "Failed fixture", text: "Check state" } }));
      await new Promise(resolve => setImmediate(resolve));
      b.ack(false);
      assert.equal((await failedSave).result.structuredContent.code, "save_failed");
      const disabled = await call(request(20, "tools/call", { name: "notes_diagnostics_read" }));
      assert.equal(disabled.result.structuredContent.code, "developer_mode_disabled");
      b.t.daten().einstellungen.allgemein.entwicklermodus = true;
      const peer = { device_id: "22222222-2222-4222-8222-222222222222", fingerprint: "owned-fixture-key",
        state: "online_wifi", own_device: true, remote_own_device: true };
      b.w.App.telefonStand({ peers: [peer] });
      const diagnostic = call(request(21, "tools/call", { name: "notes_diagnostics_read" }));
      await new Promise(resolve => setImmediate(resolve));
      const nativeRead = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      assert.equal(nativeRead.kennung, peer.device_id);
      b.w.App.telefonEntwicklerDiagnose({ requestId: "wrong", kennung: peer.device_id, ok: true, diagnose: { app_version: "ignore" } });
      b.w.App.telefonEntwicklerDiagnose({ requestId: nativeRead.requestId, kennung: peer.device_id, ok: true,
        diagnose: { format: 1, app_version: "owned-diagnostic-fixture", events: [] } });
      assert.equal((await diagnostic).result.structuredContent.diagnostics.app_version, "owned-diagnostic-fixture");
      assert.ok(!JSON.stringify(b.t.daten()).includes("owned-diagnostic-fixture"));
      const revoked = call(request(22, "tools/call", { name: "notes_diagnostics_read" }));
      await new Promise(resolve => setImmediate(resolve));
      const obsoleteRead = b.messages.filter(message => message.cmd === "telefon_entwickler_diagnose").at(-1);
      b.w.App.telefonStand({ peers: [{ ...peer, fingerprint: "replacement-key" }] });
      b.w.App.telefonEntwicklerDiagnose({ requestId: obsoleteRead.requestId, kennung: peer.device_id, ok: true,
        diagnose: { app_version: "must-not-leak" } });
      const rejected = await revoked;
      assert.equal(rejected.result.structuredContent.code, "source_changed");
      assert.ok(!JSON.stringify(rejected).includes("must-not-leak"));
      const filesystem = call(request(23, "tools/call", { name: "kde_filesystem_status" }));
      await new Promise(resolve => setImmediate(resolve));
      const fsRead = b.messages.filter(message => message.cmd === "kde_dateisystem_stand").at(-1);
      b.w.App.kdeMedien({ requestId: fsRead.requestId, ok: true, devices: [] });
      assert.equal((await filesystem).result.isError, false);
      const actionsBefore = b.messages.filter(message => message.cmd === "kde_medien_aktion").length;
      const shell = await call(request(24, "tools/call", { name: "kde_media_action", arguments: {
        device_id: peer.device_id, token: "a".repeat(32), player: "fixture", action: "shell" } }));
      assert.equal(shell.error.code, -32602);
      assert.equal(b.messages.filter(message => message.cmd === "kde_medien_aktion").length, actionsBefore);
      b.w.App.init({ gesperrt: true });
      const locked = await call(request(6, "tools/call", { name: "organizer_data_read", arguments: { section: "notizen" } }));
      assert.equal(locked.result.isError, true);
      assert.equal(locked.result.structuredContent.code, "locked_or_not_ready");
      assert.ok(!JSON.stringify(locked).includes("Owned fixture"));
      const status = await call(request(7, "tools/call", { name: "organizer_status" }));
      assert.equal(status.result.structuredContent.locked, true);
      b.w.App.mcpClose(session);
      assert.equal((await call(request(8, "tools/list"))).error.code, -32002);
      console.log("MCP note/task/appointment/contact CRUD, native snapshot gates, metadata/readonly/hierarchy, modal/draft guards and durable replies PASS " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
