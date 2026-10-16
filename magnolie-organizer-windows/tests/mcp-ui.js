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
      muelltermine: [{ id: "owned-imported-waste", name: "Owned import", von: "2028-04-01", intervallTage: 0, farbe: "#aabbcc", art: "custom",
        importQuelle: "waste:ics:" + "a".repeat(64), importName: "Owned import.ics", importTyp: "Owned fixture",
        importierteTermine: [{ id: "owned-waste-date", uid: "owned-waste-uid", datum: "2028-04-01", titel: "Owned waste date" }] }],
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
      async function call(message, actualSession = session) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: actualSession, invocation, message });
        const reply = b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation);
        assert.ok(reply, "Every accepted native invocation must settle");
        assert.equal(reply.session, actualSession);
        return reply.response;
      }
      const request = (id, method, params) => ({ jsonrpc: "2.0", id, method, ...(params === undefined ? {} : { params }) });
      assert.equal((await call(request(1, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fixture", version: "1" } }))).result.serverInfo.name, "magnolie-organizer");
      assert.equal(await call({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
      const descriptors = [], cursors = new Set();
      let toolCursor;
      do {
        const page = (await call(request(2, "tools/list", toolCursor === undefined ? undefined : { cursor: toolCursor }))).result;
        assert.ok(page.tools.length <= 100); descriptors.push(...page.tools);
        toolCursor = page.nextCursor;
        if (toolCursor !== undefined) { assert.ok(!cursors.has(toolCursor)); cursors.add(toolCursor); }
      } while (toolCursor !== undefined);
      assert.ok(cursors.size >= 1, "Exercise schema parity across multiple tool-list pages");
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
      const projectedNote = await call(request(130, "tools/call", { name: "organizer_data_read", arguments: {
        section: "notizen", id: "fixture-note", fields: ["id", "titel"] } }));
      assert.equal(projectedNote.result.structuredContent.entry.titel, "Fixture");
      assert.equal(projectedNote.result.structuredContent.entry.text, undefined);
      const nestedModules = await call(request(131, "tools/call", { name: "organizer_data_read", arguments: {
        section: "customOrganizer", path: ["modules"] } }));
      assert.equal(nestedModules.result.structuredContent.total, 0);
      const indexedTitle = await call(request(132, "tools/call", { name: "organizer_data_read", arguments: {
        section: "notizen", path: [0, "titel"] } }));
      assert.equal(indexedTitle.result.structuredContent.value, "Fixture");
      const traversal = await call(request(133, "tools/call", { name: "organizer_data_read", arguments: {
        section: "notizen", id: "fixture-note", path: ["constructor"] } }));
      assert.equal(traversal.result.structuredContent.code, "invalid_path");
      const ownNote = b.t.daten().notizen.find(note => note.id === "fixture-note"), originalText = ownNote.text;
      const longText = "🌸é\n".repeat(100000);
      ownNote.text = longText;
      const firstChunk = await call(request(134, "tools/call", { name: "organizer_content_read", arguments: {
        section: "notizen", id: "fixture-note", path: ["text"], limit: 5 } }));
      const chunk = firstChunk.result.structuredContent, bytes = Buffer.from(longText, "utf8");
      assert.equal(chunk.total_bytes, bytes.length);
      assert.equal(Buffer.from(chunk.data, "base64").compare(bytes.subarray(0, 5)), 0);
      const secondChunk = await call(request(135, "tools/call", { name: "organizer_content_read", arguments: {
        section: "notizen", id: "fixture-note", path: ["text"], offset: chunk.next_offset, limit: 5, expected_revision: chunk.revision } }));
      assert.equal(Buffer.from(secondChunk.result.structuredContent.data, "base64").compare(bytes.subarray(5, 10)), 0);
      const largeChunk = await call(request(136, "tools/call", { name: "organizer_content_read", arguments: {
        section: "notizen", id: "fixture-note", path: ["text"], limit: 65536, expected_revision: chunk.revision } }));
      assert.ok(Buffer.byteLength(JSON.stringify(largeChunk), "utf8") < 1024 * 1024);
      ownNote.text += "changed";
      const staleChunk = await call(request(137, "tools/call", { name: "organizer_content_read", arguments: {
        section: "notizen", id: "fixture-note", path: ["text"], offset: 10, expected_revision: chunk.revision } }));
      assert.equal(staleChunk.result.structuredContent.code, "conflict");
      ownNote.text = originalText;
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
      let onSave, onSnapshot, onRecovery, onBackup, onArchive, onArchiveExport;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text);
        const message = JSON.parse(text);
        if (message.cmd === "speichern" && onSave) { const resolve = onSave; onSave = null; resolve(); }
        if (message.cmd === "mutations_snapshot" && onSnapshot) { const resolve = onSnapshot; onSnapshot = null; resolve(message); }
        if (message.cmd.startsWith("journal_") && message.requestId && onRecovery) onRecovery(message);
        if (message.cmd === "sicherung" && message.requestId && onBackup) onBackup(message);
        if (message.cmd === "gesamtarchiv_pruefen" && message.requestId && onArchive) onArchive(message);
        if (message.cmd === "gesamtarchiv_exportieren" && message.requestId && onArchiveExport) onArchiveExport(message);
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
      const groupAId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", bookId = "ffffffff-ffff-4fff-8fff-ffffffffffff";
      const groupA = await persisted(140, "organizer_notebook_group_create", { id: groupAId, name: "Owned group A" });
      assert.ok(b.t.daten().notizen.some(note => note.id === groupA.note_id && note.notizbuchId === groupA.notebook_id));
      const duplicateGroup = await call(request(141, "tools/call", { name: "organizer_notebook_group_create", arguments: { name: "OWNED GROUP A" } }));
      assert.equal(duplicateGroup.result.structuredContent.code, "name_conflict");
      const groupRead = (await call(request(142, "tools/call", { name: "organizer_notebook_group_read", arguments: { id: groupAId } }))).result.structuredContent;
      await persisted(143, "organizer_notebook_group_update", { id: groupAId, expected_revision: groupRead.revision, name: "Owned renamed group", position: 0 });
      assert.equal(b.t.daten().notizgruppen[0].id, groupAId);
      await persisted(144, "organizer_notebook_create", { id: bookId, group_id: groupAId, name: "Owned notebook" });
      const structureNote = await persisted(145, "organizer_note_create", { title: "Owned structure page", text: "Preserve when moving", notebook_id: bookId });
      const groupB = await persisted(146, "organizer_notebook_group_create", { name: "Owned group B" });
      const bookRead = (await call(request(147, "tools/call", { name: "organizer_notebook_read", arguments: { id: bookId } }))).result.structuredContent;
      await persisted(148, "organizer_notebook_update", { id: bookId, expected_revision: bookRead.revision, group_id: groupB.id, name: "Owned moved notebook", position: 0 });
      assert.equal(b.t.daten().notizbuecher.filter(book => book.gruppeId === groupB.id)[0].id, bookId);
      assert.equal(b.t.daten().notizen.find(note => note.id === structureNote.id).notizbuchId, bookId);
      const movedBook = (await call(request(149, "tools/call", { name: "organizer_notebook_read", arguments: { id: bookId } }))).result.structuredContent;
      const removedBook = await persisted(150, "organizer_notebook_delete", { id: bookId, expected_revision: movedBook.revision });
      assert.equal(removedBook.target_notebook_id, groupB.notebook_id);
      assert.equal(b.t.daten().notizen.find(note => note.id === structureNote.id).notizbuchId, groupB.notebook_id);
      await persisted(151, "organizer_trash_restore", { id: removedBook.trash_id });
      assert.equal(b.t.daten().notizen.find(note => note.id === structureNote.id).notizbuchId, bookId);
      const groupBRead = (await call(request(152, "tools/call", { name: "organizer_notebook_group_read", arguments: { id: groupB.id } }))).result.structuredContent;
      await persisted(153, "organizer_notebook_group_delete", { id: groupB.id, expected_revision: groupBRead.revision });
      assert.ok(b.t.daten().notizen.some(note => note.id === structureNote.id));
      assert.ok(b.t.daten().notizbuecher.some(book => book.id === b.t.daten().notizen.find(note => note.id === structureNote.id).notizbuchId));
      const groupARemove = (await call(request(154, "tools/call", { name: "organizer_notebook_group_read", arguments: { id: groupAId } }))).result.structuredContent;
      await persisted(155, "organizer_notebook_group_delete", { id: groupAId, expected_revision: groupARemove.revision });
      const lastGroup = b.t.daten().notizgruppen[0].id;
      const lastRead = (await call(request(156, "tools/call", { name: "organizer_notebook_group_read", arguments: { id: lastGroup } }))).result.structuredContent;
      const cannotRemove = await call(request(157, "tools/call", { name: "organizer_notebook_group_delete", arguments: { id: lastGroup, expected_revision: lastRead.revision } }));
      assert.equal(cannotRemove.result.structuredContent.code, "structure_required");
      const personId = "12121212-1212-4212-8212-121212121212";
      await persisted(190, "organizer_person_create", { id: personId, name: "Owned person", note: "Own fixture" });
      const personRead = (await call(request(191, "tools/call", { name: "organizer_person_read", arguments: { id: personId } }))).result.structuredContent;
      await persisted(192, "organizer_person_update", { id: personId, expected_revision: personRead.revision, name: "Revised person", abbreviation: "RP" });
      assert.equal(b.t.daten().personen.find(person => person.id === personId).kuerzel, "RP");
      await persisted(193, "organizer_task_create", { title: "Owned assigned fixture", persons: [personId] });
      const personRemove = (await call(request(194, "tools/call", { name: "organizer_person_read", arguments: { id: personId } }))).result.structuredContent;
      const unassigned = await persisted(195, "organizer_person_delete", { id: personId, expected_revision: personRemove.revision });
      assert.equal(unassigned.unassigned_tasks.length, 1);
      assert.ok(b.t.daten().aufgaben.some(task => task.id === unassigned.unassigned_tasks[0] && !task.personen.includes(personId)));
      const anniversaryId = "13131313-1313-4313-8313-131313131313";
      await persisted(200, "organizer_anniversary_create", { id: anniversaryId, name: "Owned linked birthday", date: "--12-31", type: "birthday", contact_id: "fixture-contact" });
      assert.equal(b.t.daten().kontakte.find(contact => contact.id === "fixture-contact").geburtstag, "--12-31");
      const anniversaryRead = (await call(request(201, "tools/call", { name: "organizer_anniversary_read", arguments: { id: anniversaryId } }))).result.structuredContent;
      await persisted(202, "organizer_anniversary_update", { id: anniversaryId, expected_revision: anniversaryRead.revision, date: "--01-01" });
      assert.equal(b.t.daten().kontakte.find(contact => contact.id === "fixture-contact").geburtstag, "--01-01");
      const anniversaryRemove = (await call(request(203, "tools/call", { name: "organizer_anniversary_read", arguments: { id: anniversaryId } }))).result.structuredContent;
      const anniversaryDeleted = await persisted(204, "organizer_anniversary_delete", { id: anniversaryId, expected_revision: anniversaryRemove.revision });
      assert.equal(b.t.daten().kontakte.find(contact => contact.id === "fixture-contact").geburtstag, "");
      await persisted(205, "organizer_trash_restore", { id: anniversaryDeleted.trash_id });
      assert.ok(b.t.daten().jahrestage.some(entry => entry.id === anniversaryId));
      const vacationId = "14141414-1414-4414-8414-141414141414";
      const vacationVisibility = b.t.daten().einstellungen.kalender.urlaubsplanerAn;
      for (const dates of [{ from: "2027-02-29", through: "2027-03-01" }, { from: "2028-03-01", through: "2028-02-29" }]) {
        const invalid = await call(request(210, "tools/call", { name: "organizer_vacation_create", arguments: dates }));
        assert.equal(invalid.result.structuredContent.code, "invalid_date");
      }
      await persisted(211, "organizer_vacation_create", { id: vacationId, from: "2028-02-29", through: "2028-03-02", symbol: "snowman" });
      assert.equal(b.t.daten().einstellungen.kalender.urlaubsplanerAn, vacationVisibility);
      const vacationRead = (await call(request(212, "tools/call", { name: "organizer_vacation_read", arguments: { id: vacationId } }))).result.structuredContent;
      assert.equal(vacationRead.vacation.von, "2028-02-29");
      const vacationReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try { assert.equal(vacationReload.t.daten().urlaube.find(entry => entry.id === vacationId).symbol, "snowman"); }
      finally { vacationReload.close(); }
      await persisted(213, "organizer_vacation_update", { id: vacationId, expected_revision: vacationRead.revision, display: "symbol", through: "2028-03-03" });
      const staleVacation = await call(request(214, "tools/call", { name: "organizer_vacation_delete", arguments: { id: vacationId, expected_revision: vacationRead.revision } }));
      assert.equal(staleVacation.result.structuredContent.code, "conflict");
      const vacationRemove = (await call(request(215, "tools/call", { name: "organizer_vacation_read", arguments: { id: vacationId } }))).result.structuredContent;
      assert.equal(vacationRemove.vacation.symbol, "snowman");
      assert.equal(vacationRemove.vacation.darstellung, "symbol");
      await persisted(216, "organizer_vacation_delete", { id: vacationId, expected_revision: vacationRemove.revision });
      assert.ok(!b.t.daten().urlaube.some(entry => entry.id === vacationId));
      const shiftId = "15151515-1515-4515-8515-151515151515", cycleId = "16161616-1616-4616-8616-161616161616";
      const invalidShift = await call(request(220, "tools/call", { name: "organizer_shift_create", arguments: { name: "Invalid", from: "25:00" } }));
      assert.equal(invalidShift.error.code, -32602);
      await persisted(221, "organizer_shift_create", { id: shiftId, name: "Owned night shift", type: "night", from: "22:00", through: "06:00", color: "#AABBCC" });
      await persisted(222, "organizer_cycle_marker_create", { id: cycleId, name: "Owned cycle fixture", type: "custom", symbol: "🌱" });
      const definitionReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try {
        assert.equal(definitionReload.t.daten().schichten.find(entry => entry.id === shiftId).bis, "06:00");
        assert.equal(definitionReload.t.daten().zyklusmarker.find(entry => entry.id === cycleId).symbol, "🌱");
      } finally { definitionReload.close(); }
      const readDay = async date => (await call(request(230, "tools/call", { name: "organizer_day_marker_read", arguments: { date } }))).result.structuredContent;
      const emptyDay = await readDay("2028-04-01");
      assert.equal(emptyDay.marker, null);
      const wrongDay = await call(request(231, "tools/call", { name: "organizer_day_marker_set", arguments: { date: "2028-04-02", expected_revision: emptyDay.revision, shift_id: shiftId } }));
      assert.equal(wrongDay.result.structuredContent.code, "conflict");
      const missingDefinition = await call(request(232, "tools/call", { name: "organizer_day_marker_set", arguments: { date: "2028-04-01", expected_revision: emptyDay.revision, shift_id: "missing-owned-fixture" } }));
      assert.equal(missingDefinition.result.structuredContent.code, "not_found");
      for (const date of ["2028-04-01", "2028-04-02", "2028-04-03"]) {
        const day = await readDay(date);
        await persisted(233, "organizer_day_marker_set", { date, expected_revision: day.revision, shift_id: shiftId, cycle_marker_ids: date === "2028-04-02" ? [] : [cycleId, cycleId] });
      }
      const mixedDay = await readDay("2028-04-03");
      assert.equal(mixedDay.marker.zyklusIds.length, 1);
      await persisted(234, "organizer_day_marker_set", { date: "2028-04-03", expected_revision: mixedDay.revision, shift_id: "" });
      const partialDay = await readDay("2028-04-03");
      assert.equal(partialDay.marker.zyklusIds[0], cycleId);
      const staleDay = await call(request(235, "tools/call", { name: "organizer_day_marker_set", arguments: { date: "2028-04-03", expected_revision: mixedDay.revision, cycle_marker_ids: [] } }));
      assert.equal(staleDay.result.structuredContent.code, "conflict");
      await persisted(236, "organizer_day_marker_set", { date: "2028-04-03", expected_revision: partialDay.revision, cycle_marker_ids: [] });
      assert.equal((await readDay("2028-04-03")).marker, null);
      for (const [kind, id] of [["shift", shiftId], ["cycle_marker", cycleId]]) {
        const read = (await call(request(223, "tools/call", { name: `organizer_${kind}_read`, arguments: { id } }))).result.structuredContent;
        await persisted(224, `organizer_${kind}_update`, { id, expected_revision: read.revision, name: "Updated owned definition" });
        const stale = await call(request(225, "tools/call", { name: `organizer_${kind}_delete`, arguments: { id, expected_revision: read.revision } }));
        assert.equal(stale.result.structuredContent.code, "conflict");
        const updated = (await call(request(226, "tools/call", { name: `organizer_${kind}_read`, arguments: { id } }))).result.structuredContent;
        if (kind === "shift") { assert.equal(updated.definition.von, "22:00"); assert.equal(updated.definition.bis, "06:00"); assert.equal(updated.definition.farbe, "#aabbcc"); }
        const removed = await persisted(227, `organizer_${kind}_delete`, { id, expected_revision: updated.revision });
        assert.deepEqual(Array.from(removed.affected_dates), kind === "shift" ? ["2028-04-01", "2028-04-02"] : ["2028-04-01"]);
        if (kind === "shift") {
          assert.equal(b.t.daten().tagmarken.find(mark => mark.datum === "2028-04-01").zyklusIds[0], cycleId);
          assert.ok(!b.t.daten().tagmarken.some(mark => mark.datum === "2028-04-02"));
        }
      }
      assert.ok(!b.t.daten().tagmarken.some(mark => mark.datum === "2028-04-01"));
      const wasteId = "17171717-1717-4717-8717-171717171717";
      await persisted(240, "organizer_waste_create", { id: wasteId, name: "Owned collection", first_date: "2028-02-29", interval_days: 14, color: "#AABBCC", type: "packaging" });
      const wasteRead = (await call(request(241, "tools/call", { name: "organizer_waste_read", arguments: { id: wasteId } }))).result.structuredContent;
      assert.equal(wasteRead.waste.farbe, "#aabbcc");
      const wasteReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try { assert.equal(wasteReload.t.daten().muelltermine.find(entry => entry.id === wasteId).intervallTage, 14); }
      finally { wasteReload.close(); }
      await persisted(242, "organizer_waste_update", { id: wasteId, expected_revision: wasteRead.revision, interval_days: 0 });
      const wasteUpdated = (await call(request(243, "tools/call", { name: "organizer_waste_read", arguments: { id: wasteId } }))).result.structuredContent;
      assert.equal(wasteUpdated.waste.intervallTage, 0);
      const wasteStale = await call(request(244, "tools/call", { name: "organizer_waste_delete", arguments: { id: wasteId, expected_revision: wasteRead.revision } }));
      assert.equal(wasteStale.result.structuredContent.code, "conflict");
      await persisted(245, "organizer_waste_delete", { id: wasteId, expected_revision: wasteUpdated.revision });
      const importedBefore = JSON.stringify(b.t.daten().muelltermine.find(entry => entry.id === "owned-imported-waste").importierteTermine);
      const importedWaste = (await call(request(246, "tools/call", { name: "organizer_waste_read", arguments: { id: "owned-imported-waste", fields: ["id", "name"] } }))).result.structuredContent;
      assert.equal(importedWaste.waste.importierteTermine, undefined);
      const importedSchedule = await call(request(247, "tools/call", { name: "organizer_waste_update", arguments: { id: "owned-imported-waste", expected_revision: importedWaste.revision, interval_days: 7 } }));
      assert.equal(importedSchedule.result.structuredContent.code, "read_only_schedule");
      await persisted(248, "organizer_waste_update", { id: "owned-imported-waste", expected_revision: importedWaste.revision, name: "Renamed owned import" });
      assert.equal(JSON.stringify(b.t.daten().muelltermine.find(entry => entry.id === "owned-imported-waste").importierteTermine), importedBefore);
      for (const [kind, section, maximum, fields] of [["shift", "schichten", 64, {}], ["cycle_marker", "zyklusmarker", 32, {}],
        ["waste", "muelltermine", 64, { first_date: "2028-04-01" }], ["vacation", "urlaube", 256, { from: "2028-04-01", through: "2028-04-02" }]]) {
        const saved = b.t.daten()[section];
        b.t.daten()[section] = Array.from({ length: maximum }, (_, i) => ({ id: "owned-limit-" + i }));
        const bounded = await call(request(249, "tools/call", { name: `organizer_${kind}_create`, arguments: { ...(kind === "vacation" ? {} : { name: "Owned limit" }), ...fields } }));
        assert.equal(bounded.result.structuredContent.code, "limit_reached");
        b.t.daten()[section] = saved;
      }
      for (const kind of ["shift", "cycle_marker", "waste"]) {
        const empty = await call(request(250, "tools/call", { name: `organizer_${kind}_create`, arguments: { name: "   ", ...(kind === "waste" ? { first_date: "2028-04-01" } : {}) } }));
        assert.equal(empty.error.code, -32602);
      }
      for (const [kind, key, id, fields] of [["vital", "vitalwerte", "18181818-1818-4818-8818-181818181818", { pulse: 72, weight_kg: 70, temperature_c: 36.7 }],
        ["blood_glucose", "blutzucker", "19191919-1919-4919-8919-191919191919", { value: 108, unit: "mg/dL", insulin_units: 2 }]]) {
        await persisted(260, `organizer_${kind}_create`, { id, date: "2028-02-29", time: "08:00", page: 2, ...fields });
        const read = (await call(request(261, "tools/call", { name: `organizer_${kind}_read`, arguments: { id } }))).result.structuredContent;
        assert.equal(read.record.seite, 2);
        await persisted(262, `organizer_${kind}_update`, { id, expected_revision: read.revision, ...(kind === "vital" ? { pulse: 80, height_cm: 0 } : { unit: "mmol/L" }) });
        let updated = (await call(request(263, "tools/call", { name: `organizer_${kind}_read`, arguments: { id } }))).result.structuredContent;
        if (kind === "vital") { assert.equal(updated.record.puls, 80); assert.equal(updated.record.gewicht, 70); }
        else {
          assert.equal(updated.record.wert, 6); assert.equal(updated.record.einheit, "mmol/L"); assert.equal(updated.record.ie, 2);
          await persisted(270, "organizer_blood_glucose_update", { id, expected_revision: updated.revision, unit: "mg/dL", value: 99 });
          updated = (await call(request(271, "tools/call", { name: "organizer_blood_glucose_read", arguments: { id } }))).result.structuredContent;
          assert.equal(updated.record.wert, 99); assert.equal(updated.record.einheit, "mg/dL");
        }
        const healthReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
        try { assert.equal(healthReload.t.daten().gesundheit[key].find(entry => entry.id === id).datum, "2028-02-29"); }
        finally { healthReload.close(); }
        const stale = await call(request(264, "tools/call", { name: `organizer_${kind}_delete`, arguments: { id, expected_revision: read.revision } }));
        assert.equal(stale.result.structuredContent.code, "conflict");
        await persisted(265, `organizer_${kind}_delete`, { id, expected_revision: updated.revision });
        assert.ok(!b.t.daten().gesundheit[key].some(entry => entry.id === id));
      }
      const invalidGlucose = await call(request(266, "tools/call", { name: "organizer_blood_glucose_create", arguments: { date: "2028-02-29", value: 51, unit: "mmol/L" } }));
      const medicationId = "20202020-2020-4020-8020-202020202020";
      await persisted(280, "organizer_medication_create", { id: medicationId, name: "Owned synthetic medication", from: "2028-02-29", through: "2028-03-02",
        weekdays: [1, 1, 3], weekly_plan: [{ day: 1, morning: "fixture" }, { day: 2 }] });
      const medicationRead = (await call(request(281, "tools/call", { name: "organizer_medication_read", arguments: { id: medicationId } }))).result.structuredContent;
      assert.deepEqual(Array.from(medicationRead.record.wochentage), [1, 3]); assert.equal(medicationRead.record.wochenplan.length, 1);
      const duplicateSchedule = await call(request(282, "tools/call", { name: "organizer_medication_update", arguments: { id: medicationId, expected_revision: medicationRead.revision, weekly_plan: [{ day: 1 }, { day: 1 }] } }));
      assert.equal(duplicateSchedule.result.structuredContent.code, "invalid_schedule");
      const invalidMedicationDate = await call(request(283, "tools/call", { name: "organizer_medication_update", arguments: { id: medicationId, expected_revision: medicationRead.revision, through: "2028-02-28" } }));
      assert.equal(invalidMedicationDate.result.structuredContent.code, "invalid_date");
      await persisted(284, "organizer_medication_update", { id: medicationId, expected_revision: medicationRead.revision, active: false });
      const medicationUpdated = (await call(request(285, "tools/call", { name: "organizer_medication_read", arguments: { id: medicationId } }))).result.structuredContent;
      assert.equal(medicationUpdated.record.aktiv, false);
      const schemeRead = (await call(request(286, "tools/call", { name: "organizer_insulin_scheme_read" }))).result.structuredContent;
      await persisted(287, "organizer_insulin_scheme_update", { expected_revision: schemeRead.revision, changes: { hinweis: "Owned synthetic configuration", langzeitRegeln: [{ vergleich: "<", wert: 6, operator: "=", ie: 0 }] } });
      const schemeStale = await call(request(288, "tools/call", { name: "organizer_insulin_scheme_update", arguments: { expected_revision: schemeRead.revision, changes: { hinweis: "Stale fixture" } } }));
      assert.equal(schemeStale.result.structuredContent.code, "conflict");
      const schemeUpdated = (await call(request(289, "tools/call", { name: "organizer_insulin_scheme_read" }))).result.structuredContent;
      const invalidScheme = await call(request(291, "tools/call", { name: "organizer_insulin_scheme_update", arguments: { expected_revision: schemeUpdated.revision, changes: { kurzzeitRegeln: [{ vergleich: "<", wert: 0.5, operator: "=", ie: 0 }] } } }));
      assert.equal(invalidScheme.error.code, -32602);
      const medicationList = b.t.daten().gesundheit.medikamente;
      b.t.daten().gesundheit.medikamente = Array.from({ length: 1000 }, (_, i) => ({ id: "owned-medication-limit-" + i }));
      const medicationLimit = await call(request(292, "tools/call", { name: "organizer_medication_create", arguments: { name: "Owned overflow" } }));
      assert.equal(medicationLimit.result.structuredContent.code, "limit_reached");
      b.t.daten().gesundheit.medikamente = medicationList;
      assert.equal(schemeUpdated.scheme.kurzzeitModus, schemeRead.scheme.kurzzeitModus);
      const medicationReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try {
        assert.equal(medicationReload.t.daten().gesundheit.medikamente.find(entry => entry.id === medicationId).wochenplan[0].morgens, "fixture");
        assert.equal(medicationReload.t.daten().gesundheit.insulinschema.hinweis, "Owned synthetic configuration");
      } finally { medicationReload.close(); }
      await persisted(290, "organizer_medication_delete", { id: medicationId, expected_revision: medicationUpdated.revision });
      const timeId = "21212121-2121-4121-8121-212121212121", startMinute = Date.UTC(2028, 1, 29, 8) / 60000;
      const disabledTime = await call(request(300, "tools/call", { name: "organizer_time_record_create", arguments: { start_minute: startMinute, end_minute: startMinute + 60 } }));
      assert.equal(disabledTime.result.structuredContent.code, "feature_disabled");
      const timeSettings = (await call(request(311, "tools/call", { name: "organizer_time_settings_read" }))).result.structuredContent;
      await persisted(312, "organizer_time_settings_update", { expected_revision: timeSettings.revision, enabled: true, report_name: "Owned report" });
      const staleTimeSettings = await call(request(313, "tools/call", { name: "organizer_time_settings_update", arguments: { expected_revision: timeSettings.revision, report_name: "Stale report" } }));
      assert.equal(staleTimeSettings.result.structuredContent.code, "conflict");
      const invalidTimeRecord = await call(request(301, "tools/call", { name: "organizer_time_record_create", arguments: { start_minute: startMinute, end_minute: startMinute - 1 } }));
      assert.equal(invalidTimeRecord.result.structuredContent.code, "invalid_time_record");
      await persisted(302, "organizer_time_record_create", { id: timeId, start_minute: startMinute, end_minute: startMinute + 60, pause_minutes: 15, zone: "UTC", type: "Owned manual time" });
      const timeRead = (await call(request(303, "tools/call", { name: "organizer_time_record_read", arguments: { id: timeId } }))).result.structuredContent;
      const actor = b.t.daten().zeiterfassung.actor;
      assert.equal(timeRead.record.clock[actor], 1);
      await persisted(304, "organizer_time_record_update", { id: timeId, expected_revision: timeRead.revision, note: "Owned changed note" });
      const timeUpdated = (await call(request(305, "tools/call", { name: "organizer_time_record_read", arguments: { id: timeId } }))).result.structuredContent;
      assert.equal(timeUpdated.record.clock[actor], 2); assert.equal(timeUpdated.record.pauseMinutes, 15);
      const invalidRunning = await call(request(306, "tools/call", { name: "organizer_time_record_update", arguments: { id: timeId, expected_revision: timeUpdated.revision, end_minute: null } }));
      assert.equal(invalidRunning.result.structuredContent.code, "invalid_time_record");
      const timeReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try { assert.equal(timeReload.t.daten().zeiterfassung.entries.find(entry => entry.id === timeId).clock[actor], 2); }
      finally { timeReload.close(); }
      const staleTime = await call(request(307, "tools/call", { name: "organizer_time_record_delete", arguments: { id: timeId, expected_revision: timeRead.revision } }));
      assert.equal(staleTime.result.structuredContent.code, "conflict");
      const deletedTime = await persisted(308, "organizer_time_record_delete", { id: timeId, expected_revision: timeUpdated.revision });
      const timeTombstone = b.t.daten().zeiterfassung.entries.find(entry => entry.id === timeId);
      assert.equal(timeTombstone.deleted, true); assert.equal(timeTombstone.clock[actor], 3);
      const duplicateTime = await call(request(309, "tools/call", { name: "organizer_time_record_create", arguments: { id: timeId, start_minute: startMinute, end_minute: startMinute + 60 } }));
      assert.equal(duplicateTime.result.structuredContent.code, "already_exists");
      await persisted(310, "organizer_trash_restore", { id: deletedTime.trash_id });
      assert.equal(b.t.daten().zeiterfassung.entries.find(entry => entry.id === timeId).deleted, false);
      const restoredTime = b.t.daten().zeiterfassung.entries.find(entry => entry.id === timeId), remoteTimeActor = "22222222-2222-4222-8222-222222222222";
      b.t.daten().zeiterfassung.conflicts[timeId] = [{ ...JSON.parse(JSON.stringify(restoredTime)), note: "Owned competing version", clock: { [remoteTimeActor]: 1 } }];
      const timeConflict = (await call(request(314, "tools/call", { name: "organizer_time_conflict_read", arguments: { id: timeId } }))).result.structuredContent;
      assert.equal(timeConflict.versions.length, 1);
      await persisted(315, "organizer_time_conflict_resolve", { id: timeId, expected_revision: timeConflict.revision, choice: 1 });
      const resolvedTime = b.t.daten().zeiterfassung.entries.find(entry => entry.id === timeId);
      assert.equal(resolvedTime.note, "Owned competing version"); assert.equal(resolvedTime.clock[remoteTimeActor], 1);
      assert.ok(resolvedTime.clock[actor] > restoredTime.clock[actor]);
      assert.equal(b.t.daten().zeiterfassung.conflicts[timeId], undefined);
      const staleTimeConflict = await call(request(316, "tools/call", { name: "organizer_time_conflict_resolve", arguments: { id: timeId, expected_revision: timeConflict.revision, choice: 0 } }));
      assert.equal(staleTimeConflict.result.structuredContent.code, "conflict");
      const customNotesId = "24242424-2424-4424-8424-242424242424", customTasksId = "25252525-2525-4525-8525-252525252525";
      await persisted(320, "organizer_custom_module_create", { id: customNotesId, type: "notes", page: "left", title: "Owned text block", lines: "on" });
      await persisted(321, "organizer_custom_module_create", { id: customTasksId, type: "tasks", page: "right", reminders: true });
      await persisted(322, "organizer_custom_module_create", { type: "notes", page: "right" });
      const duplicateModule = await call(request(323, "tools/call", { name: "organizer_custom_module_create", arguments: { type: "tasks" } }));
      assert.equal(duplicateModule.result.structuredContent.code, "layout_full");
      const customRead = (await call(request(324, "tools/call", { name: "organizer_custom_module_read", arguments: { id: customNotesId, fields: ["id", "title"] } }))).result.structuredContent;
      assert.equal(customRead.module.items, undefined);
      const layoutFull = await call(request(325, "tools/call", { name: "organizer_custom_module_update", arguments: { id: customNotesId, expected_revision: customRead.revision, page: "right", title: "Must not apply" } }));
      assert.equal(layoutFull.result.structuredContent.code, "layout_full");
      await persisted(326, "organizer_custom_module_update", { id: customNotesId, expected_revision: customRead.revision, title: "Updated owned block", lines: "off" });
      const drawingModule = await persisted(327, "organizer_custom_module_create", { type: "drawing", page: "left" });
      const drawingRead = (await call(request(328, "tools/call", { name: "organizer_custom_module_read", arguments: { id: drawingModule.id } }))).result.structuredContent;
      assert.equal(b.w.MagnolieZeichnen.valid(drawingRead.module.drawing), true);
      const ownedSheet = { version: 4, width: 400, height: 300, autoSize: false, strokes: [{ tool: "pen", color: "#123456", width: 2, points: [[0.1, 0.2, 0.3], [0.8, 0.9, 1]] }] };
      await persisted(360, "organizer_drawing_replace", { id: drawingModule.id, expected_revision: drawingRead.revision, sheet: ownedSheet });
      const drawingChunk = (await call(request(361, "tools/call", { name: "organizer_drawing_read", arguments: { id: drawingModule.id, limit: 7 } }))).result.structuredContent;
      const drawingTail = (await call(request(362, "tools/call", { name: "organizer_drawing_read", arguments: { id: drawingModule.id, offset: drawingChunk.next_offset, expected_revision: drawingChunk.revision } }))).result.structuredContent;
      assert.deepEqual(JSON.parse(Buffer.concat([Buffer.from(drawingChunk.data, "base64"), Buffer.from(drawingTail.data, "base64")]).toString("utf8")), ownedSheet);
      const staleDrawing = await call(request(363, "tools/call", { name: "organizer_drawing_replace", arguments: { id: drawingModule.id, expected_revision: drawingRead.revision, sheet: ownedSheet } }));
      assert.equal(staleDrawing.result.structuredContent.code, "conflict");
      const invalidGradient = await call(request(364, "tools/call", { name: "organizer_drawing_replace", arguments: { id: drawingModule.id, expected_revision: drawingChunk.revision,
        sheet: { ...ownedSheet, strokes: [{ tool: "fill", color: "#123456", gradient: ["#123456", "#654321"], width: 2, points: [[0.1, 0.2, 0.3]] }] } } }));
      assert.equal(invalidGradient.result.structuredContent.code, "invalid_drawing");
      const drawingBytes = Buffer.from(JSON.stringify({ ...ownedSheet, width: 401 }), "utf8");
      const drawingBegin = { id: drawingModule.id, expected_revision: drawingChunk.revision, size: drawingBytes.length, sha256: createHash("sha256").update(drawingBytes).digest("hex") };
      const drawingUpload = (await call(request(370, "tools/call", { name: "organizer_drawing_upload_begin", arguments: drawingBegin }))).result.structuredContent;
      const drawingOwner = "c".repeat(48);
      await call(request(371, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-drawing-session", version: "1" } }), drawingOwner);
      await call({ jsonrpc: "2.0", method: "notifications/initialized" }, drawingOwner);
      const stolenDrawing = await call(request(372, "tools/call", { name: "organizer_drawing_upload_status", arguments: { token: drawingUpload.token } }), drawingOwner);
      assert.equal(stolenDrawing.result.structuredContent.code, "not_found");
      await call(request(373, "tools/call", { name: "organizer_drawing_upload_begin", arguments: drawingBegin }), drawingOwner);
      const drawingLimit = await call(request(374, "tools/call", { name: "organizer_drawing_upload_begin", arguments: drawingBegin }));
      assert.equal(drawingLimit.result.structuredContent.code, "upload_limit");
      b.w.App.mcpClose(drawingOwner);
      const expiringDrawing = (await call(request(375, "tools/call", { name: "organizer_drawing_upload_begin", arguments: drawingBegin }))).result.structuredContent;
      b.timers.filter(timer => timer.delay === 300000 && !timer.cancelled).at(-1).fn();
      const expiredDrawing = await call(request(376, "tools/call", { name: "organizer_drawing_upload_status", arguments: { token: expiringDrawing.token } }));
      assert.equal(expiredDrawing.result.structuredContent.code, "not_found");
      const drawingGap = await call(request(377, "tools/call", { name: "organizer_drawing_upload_append", arguments: { token: drawingUpload.token, offset: 1, data: drawingBytes.subarray(0, 10).toString("base64") } }));
      assert.equal(drawingGap.result.structuredContent.code, "invalid_offset");
      for (const offset of [0, 0, 10]) {
        const bytes = offset === 0 ? drawingBytes.subarray(0, 10) : drawingBytes.subarray(10);
        const appended = await call(request(378, "tools/call", { name: "organizer_drawing_upload_append", arguments: { token: drawingUpload.token, offset, data: bytes.toString("base64") } }));
        assert.equal(appended.result.isError, false);
      }
      const completeDrawing = (await call(request(379, "tools/call", { name: "organizer_drawing_upload_status", arguments: { token: drawingUpload.token } }))).result.structuredContent;
      assert.equal(completeDrawing.received_bytes, drawingBytes.length);
      const badDrawingUpload = (await call(request(380, "tools/call", { name: "organizer_drawing_upload_begin", arguments: { ...drawingBegin, sha256: "0".repeat(64) } }))).result.structuredContent;
      await call(request(381, "tools/call", { name: "organizer_drawing_upload_append", arguments: { token: badDrawingUpload.token, offset: 0, data: drawingBytes.toString("base64") } }));
      const wrongDrawingHash = await call(request(382, "tools/call", { name: "organizer_drawing_upload_finalize", arguments: { token: badDrawingUpload.token } }));
      assert.equal(wrongDrawingHash.result.structuredContent.code, "hash_mismatch");
      const invalidUtf8 = Buffer.from([255]);
      const invalidDrawingUpload = (await call(request(387, "tools/call", { name: "organizer_drawing_upload_begin", arguments: { ...drawingBegin, size: 1, sha256: createHash("sha256").update(invalidUtf8).digest("hex") } }))).result.structuredContent;
      await call(request(388, "tools/call", { name: "organizer_drawing_upload_append", arguments: { token: invalidDrawingUpload.token, offset: 0, data: invalidUtf8.toString("base64") } }));
      const invalidDrawingJson = await call(request(389, "tools/call", { name: "organizer_drawing_upload_finalize", arguments: { token: invalidDrawingUpload.token } }));
      assert.equal(invalidDrawingJson.result.structuredContent.code, "invalid_drawing");
      const cancelledDrawing = (await call(request(383, "tools/call", { name: "organizer_drawing_upload_begin", arguments: drawingBegin }))).result.structuredContent;
      await call(request(384, "tools/call", { name: "organizer_drawing_upload_cancel", arguments: { token: cancelledDrawing.token } }));
      await persisted(385, "organizer_drawing_upload_finalize", { token: drawingUpload.token });
      const finalDrawing = (await call(request(386, "tools/call", { name: "organizer_drawing_read", arguments: { id: drawingModule.id } }))).result.structuredContent;
      assert.equal(JSON.parse(Buffer.from(finalDrawing.data, "base64").toString("utf8")).width, 401);
      await persisted(329, "organizer_custom_module_delete", { id: drawingModule.id, expected_revision: finalDrawing.revision });
      const customTextId = "26262626-2626-4626-8626-262626262626", customTaskId = "27272727-2727-4727-8727-272727272727";
      await persisted(340, "organizer_custom_item_create", { module_id: customNotesId, id: customTextId, title: "Owned text", html: "<p>Owned text</p><script>bad()</script>" });
      const customText = (await call(request(341, "tools/call", { name: "organizer_custom_item_read", arguments: { module_id: customNotesId, id: customTextId } }))).result.structuredContent;
      assert.ok(!customText.item.html.includes("script")); assert.ok(customText.item.text.includes("Owned text"));
      await persisted(342, "organizer_custom_item_update", { module_id: customNotesId, id: customTextId, expected_revision: customText.revision, text: "Revised owned text" });
      const staleCustomText = await call(request(343, "tools/call", { name: "organizer_custom_item_delete", arguments: { module_id: customNotesId, id: customTextId, expected_revision: customText.revision } }));
      assert.equal(staleCustomText.result.structuredContent.code, "conflict");
      await persisted(344, "organizer_custom_item_create", { module_id: customTasksId, id: customTaskId, title: "Owned linked task", date: "2028-02-29", text_item_id: customTextId });
      const customTask = (await call(request(345, "tools/call", { name: "organizer_custom_item_read", arguments: { module_id: customTasksId, id: customTaskId } }))).result.structuredContent;
      await persisted(346, "organizer_custom_item_update", { module_id: customTasksId, id: customTaskId, expected_revision: customTask.revision, done: true });
      const unsupportedCustom = await call(request(347, "tools/call", { name: "organizer_custom_item_create", arguments: { module_id: customTasksId, text: "Unsupported fixture" } }));
      assert.equal(unsupportedCustom.result.structuredContent.code, "unsupported_field");
      const customAppointments = await persisted(348, "organizer_custom_module_create", { type: "appointments", page: "left" });
      const customAppointment = await persisted(349, "organizer_custom_item_create", { module_id: customAppointments.id, date: "2028-02-29", recurrence: { frequency: "weekly", until: "2028-03-31" } });
      const appointmentItem = (await call(request(350, "tools/call", { name: "organizer_custom_item_read", arguments: { module_id: customAppointments.id, id: customAppointment.id } }))).result.structuredContent;
      assert.equal(appointmentItem.item.wiederholung.art, "weekly");
      const appointmentRemoved = await persisted(351, "organizer_custom_item_delete", { module_id: customAppointments.id, id: customAppointment.id, expected_revision: appointmentItem.revision });
      await persisted(352, "organizer_trash_restore", { id: appointmentRemoved.trash_id });
      const customRemove = (await call(request(330, "tools/call", { name: "organizer_custom_module_read", arguments: { id: customNotesId } }))).result.structuredContent;
      const customDeleted = await persisted(331, "organizer_custom_module_delete", { id: customNotesId, expected_revision: customRemove.revision });
      assert.equal(b.t.daten().customOrganizer.modules.find(module => module.id === customTasksId).items[0].textItemId, "");
      await persisted(332, "organizer_trash_restore", { id: customDeleted.trash_id });
      assert.equal(b.t.daten().customOrganizer.modules.find(module => module.id === customTasksId).items[0].textItemId, customTextId);
      const recoveryId = "28282828-2828-4828-8828-282828282828";
      const recoverySnapshot = { snapshotId: recoveryId, createdAt: "2028-02-29T08:00:00Z", reason: "manual", integrity: "ok", summary: { notizen: 1 },
        payload: { size: 100, file: "private-payload", sha256: "a".repeat(64) }, path: "/private/owned-recovery-fixture", encrypted: false, pinned: false };
      let recoveryRequest, recoverySettled = false;
      onRecovery = message => { recoveryRequest = message; };
      const recoveryPending = call(request(400, "tools/call", { name: "organizer_recovery_list", arguments: { limit: 1 } })).then(value => { recoverySettled = true; return value; });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(recoveryRequest.cmd, "journal_liste");
      b.w.App.journalStand({ requestId: "wrong-request", ok: true, snapshots: [] });
      b.w.App.journalVorschau({ requestId: recoveryRequest.requestId, ok: true, snapshot: recoverySnapshot });
      await new Promise(resolve => setImmediate(resolve)); assert.equal(recoverySettled, false);
      b.w.App.journalStand({ requestId: recoveryRequest.requestId, ok: true, snapshots: [recoverySnapshot, { ...recoverySnapshot, snapshotId: "29292929-2929-4929-8929-292929292929" }],
        intervall: "weekly", mode: "count", maximum: 20, days: 14, letzte: null, naechste: null });
      const recoveryList = (await recoveryPending).result.structuredContent;
      assert.equal(recoveryList.total, 2); assert.equal(recoveryList.next_offset, 1); assert.equal(recoveryList.settings.interval, "weekly");
      assert.equal(recoveryList.snapshots[0].id, recoveryId); assert.equal(recoveryList.snapshots[0].path, undefined);
      onRecovery = message => b.w.App.journalVorschau({ requestId: message.requestId, ok: true, snapshot: recoverySnapshot, summary: recoverySnapshot.summary, verified: message.verify !== false, revision: "c".repeat(64) });
      const recoveryPreview = await call(request(401, "tools/call", { name: "organizer_recovery_snapshot_preview", arguments: { id: recoveryId } }));
      assert.equal(recoveryPreview.result.structuredContent.confirmed, true);
      assert.equal(recoveryPreview.result.structuredContent.verified, true);
      const recoveryInspection = await call(request(404, "tools/call", { name: "organizer_recovery_snapshot_preview", arguments: { id: recoveryId, verify: false } }));
      assert.equal(recoveryInspection.result.structuredContent.verified, false);
      const recoveryRevision = recoveryInspection.result.structuredContent.revision;
      const duplicateRecoveryDelete = await call(request(405, "tools/call", { name: "organizer_recovery_snapshots_delete", arguments: { snapshots: [{ id: recoveryId, expected_revision: recoveryRevision }, { id: recoveryId, expected_revision: recoveryRevision }] } }));
      assert.equal(duplicateRecoveryDelete.result.structuredContent.code, "invalid_selection");
      onRecovery = message => {
        assert.equal(message.expectedRevisions[recoveryId], recoveryRevision);
        b.w.App.journalErgebnis({ requestId: message.requestId, ok: false, code: "conflict", fehler: "Owned stale snapshot" });
      };
      const staleRecoveryDelete = await call(request(406, "tools/call", { name: "organizer_recovery_snapshots_delete", arguments: { snapshots: [{ id: recoveryId, expected_revision: recoveryRevision }] } }));
      assert.equal(staleRecoveryDelete.result.structuredContent.code, "conflict");
      onRecovery = message => b.w.App.journalErgebnis({ requestId: message.requestId, ok: true, deleted: true, anzahl: 1 });
      const confirmedRecoveryDelete = await call(request(407, "tools/call", { name: "organizer_recovery_snapshots_delete", arguments: { snapshots: [{ id: recoveryId, expected_revision: recoveryRevision }] } }));
      assert.equal(confirmedRecoveryDelete.result.structuredContent.deleted_count, 1);
      onRecovery = message => b.w.App.journalVorschau({ requestId: message.requestId, ok: false, fehler: "/private/owned-native-error" });
      const recoveryFailure = await call(request(402, "tools/call", { name: "organizer_recovery_snapshot_preview", arguments: { id: recoveryId } }));
      assert.equal(recoveryFailure.result.structuredContent.code, "native_operation_failed");
      assert.ok(!JSON.stringify(recoveryFailure).includes("owned-native-error"));
      const pendingRecoveryNote = b.t.daten().notizen.find(note => note.id === "fixture-note"), oldRecoveryTitle = pendingRecoveryNote.titel;
      pendingRecoveryNote.titel = "Owned pending recovery save";
      onRecovery = message => b.w.App.journalErgebnis({ requestId: message.requestId, ok: true, snapshot: recoverySnapshot });
      const recoverySave = new Promise(resolve => { onSave = resolve; });
      let recoveryCreated = false;
      const recoveryCreating = call(request(403, "tools/call", { name: "organizer_recovery_snapshot_create" })).then(value => { recoveryCreated = true; return value; });
      await recoverySave; assert.equal(recoveryCreated, false); b.ack();
      assert.equal((await recoveryCreating).result.structuredContent.snapshot.id, recoveryId);
      b.t.daten().notizen.find(note => note.id === "fixture-note").titel = oldRecoveryTitle;
      onRecovery = null;
      const creationPolicy = (await call(request(420, "tools/call", { name: "organizer_recovery_creation_policy_read" }))).result.structuredContent;
      await persisted(421, "organizer_recovery_creation_policy_update", { expected_revision: creationPolicy.revision, creation_mode: "interval", interval_minutes: 73 });
      const stalePolicy = await call(request(422, "tools/call", { name: "organizer_recovery_creation_policy_update", arguments: { expected_revision: creationPolicy.revision, creation_mode: "startup" } }));
      assert.equal(stalePolicy.result.structuredContent.code, "conflict");
      const creationReload = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try { assert.equal(creationReload.t.daten().einstellungen.allgemein.wiederherstellungsminuten, 73); }
      finally { creationReload.close(); }
      const runtimePolicy = { interval: "weekly", mode: "days", maximum: 20, days: 3650 };
      onRecovery = message => {
        if (message.cmd === "journal_einstellungen_setzen") Object.assign(runtimePolicy, { interval: message.intervall, mode: message.modus, maximum: message.maximum, days: message.tage });
        b.w.App.journalStand({ ...runtimePolicy, ok: true, requestId: message.requestId, snapshots: [] });
      };
      const runtimeRead = (await call(request(430, "tools/call", { name: "organizer_recovery_runtime_policy_read" }))).result.structuredContent;
      const runtimeUpdated = await persisted(431, "organizer_recovery_runtime_policy_update", { expected_revision: runtimeRead.revision, interval: "off", maximum: 50 });
      assert.equal(runtimeUpdated.native_applied, true);
      assert.equal(b.t.daten().einstellungen.allgemein.wiederherstellungsintervall, "off");
      const runtimeStale = await call(request(432, "tools/call", { name: "organizer_recovery_runtime_policy_update", arguments: { expected_revision: runtimeRead.revision, days: 20 } }));
      assert.equal(runtimeStale.result.structuredContent.code, "conflict");
      onRecovery = null;
      b.t.daten().notizen.find(note => note.id === "fixture-note").titel = "Owned pending native backup";
      let backupRequest;
      const backupDispatched = new Promise(resolve => { onBackup = message => { backupRequest = message; resolve(); }; });
      const backupSaving = new Promise(resolve => { onSave = resolve; });
      let backupConfirmed = false;
      const backupPending = call(request(440, "tools/call", { name: "organizer_backup_create" })).then(value => { backupConfirmed = true; return value; });
      await backupSaving; assert.equal(backupConfirmed, false); b.ack(); await backupDispatched;
      b.w.App.sicherungFertig({ requestId: "wrong-backup-request", ok: true, pfad: "ignore" });
      await new Promise(resolve => setImmediate(resolve)); assert.equal(backupConfirmed, false);
      b.w.App.sicherungFertig({ requestId: backupRequest.requestId, ok: true, pfad: "/owned/native-backup.json" });
      assert.equal((await backupPending).result.structuredContent.path, "/owned/native-backup.json");
      onBackup = null;
      onArchive = message => b.w.App.gesamtarchivAusgewaehlt({ requestId: message.requestId, ok: true, geprueft: true, pfad: message.pfad,
        verschluesselt: true, erstellt: "2028-02-29T08:00:00Z", plattform: "owned-fixture", appversion: "1", anzahlen: { notizen: 2 }, fotos: 0, anhaenge: 1 });
      const archivePreview = await call(request(450, "tools/call", { name: "organizer_archive_preview", arguments: { path: "/owned/archive.magnolie", password: "owned-fixture-password" } }));
      assert.equal(archivePreview.result.structuredContent.verified, true);
      assert.equal(archivePreview.result.structuredContent.counts.notizen, 2);
      onArchive = message => b.w.App.gesamtarchivAusgewaehlt({ requestId: message.requestId, ok: false, fehler: "owned-private-archive-error" });
      const archiveRejected = await call(request(451, "tools/call", { name: "organizer_archive_preview", arguments: { path: "/owned/archive.magnolie", password: "wrong" } }));
      assert.equal(archiveRejected.result.structuredContent.code, "archive_verification_failed");
      assert.ok(!JSON.stringify(archiveRejected).includes("owned-private-archive-error"));
      onArchive = null;
      b.t.daten().notizen.find(note => note.id === "fixture-note").titel = "Owned pending archive export";
      let exportRequest, exportConfirmed = false;
      const exportDispatched = new Promise(resolve => { onArchiveExport = message => { exportRequest = message; resolve(); }; });
      const exportSaving = new Promise(resolve => { onSave = resolve; });
      const exportPending = call(request(452, "tools/call", { name: "organizer_archive_export", arguments: { path: "/owned/export.magnolie", password: "owned-password", overwrite: true } })).then(value => { exportConfirmed = true; return value; });
      await exportSaving; assert.equal(exportRequest, undefined); b.ack(); await exportDispatched;
      assert.equal(exportRequest.overwrite, true); assert.equal(exportRequest.kennwort, "owned-password");
      b.w.App.gesamtarchivExportiert({ requestId: "wrong-export-request", ok: true, pfad: "ignore" });
      b.w.App.sicherungFertig({ requestId: exportRequest.requestId, ok: true, pfad: "ignore" });
      await new Promise(resolve => setImmediate(resolve)); assert.equal(exportConfirmed, false);
      b.w.App.gesamtarchivExportiert({ requestId: exportRequest.requestId, ok: true, pfad: "/owned/actual-export.magnolie", verschluesselt: true });
      assert.deepEqual((await exportPending).result.structuredContent, { path: "/owned/actual-export.magnolie", confirmed: true, encrypted: true });
      onArchiveExport = message => b.w.App.gesamtarchivExportiert({ requestId: message.requestId, ok: false, fehler: "owned-private-export-error" });
      const exportRejected = await call(request(453, "tools/call", { name: "organizer_archive_export", arguments: { path: "/owned/export.magnolie" } }));
      assert.equal(exportRejected.result.structuredContent.code, "archive_export_failed");
      assert.ok(!JSON.stringify(exportRejected).includes("owned-private-export-error"));
      onArchiveExport = null;
      assert.equal(invalidGlucose.result.structuredContent.code, "invalid_value");
      const invalidVital = await call(request(267, "tools/call", { name: "organizer_vital_create", arguments: { date: "2028-02-29", pulse: 20 } }));
      assert.equal(invalidVital.error.code, -32602);
      for (const [kind, key, maximum, fields] of [["vital", "vitalwerte", 36, {}], ["blood_glucose", "blutzucker", 18, { value: 6, unit: "mmol/L" }]]) {
        const saved = b.t.daten().gesundheit[key];
        b.t.daten().gesundheit[key] = Array.from({ length: maximum }, (_, i) => ({ id: "owned-page-fixture-" + i, seite: 0, datum: "2028-02-29" }));
        const full = await call(request(268, "tools/call", { name: `organizer_${kind}_create`, arguments: { date: "2028-02-29", page: 0, ...fields } }));
        assert.equal(full.result.structuredContent.code, "page_full");
        const allocated = await persisted(269, `organizer_${kind}_create`, { date: "2028-02-29", ...fields });
        assert.equal(b.t.daten().gesundheit[key].find(entry => entry.id === allocated.id).seite, 1);
        b.t.daten().gesundheit[key] = saved;
      }
      const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXb8AAAAASUVORK5CYII=", "base64");
      const attachmentNote = (await call(request(160, "tools/call", { name: "organizer_note_read", arguments: { id: noteId, fields: ["id", "titel"] } }))).result.structuredContent;
      const beginArgs = { note_id: noteId, expected_revision: attachmentNote.revision, name: "owned-fixture.png", kind: "image", size: png.length,
        sha256: createHash("sha256").update(png).digest("hex") };
      const upload = (await call(request(161, "tools/call", { name: "organizer_attachment_upload_begin", arguments: beginArgs }))).result.structuredContent;
      const otherSession = "b".repeat(48);
      await call(request(162, "initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-other-session", version: "1" } }), otherSession);
      await call({ jsonrpc: "2.0", method: "notifications/initialized" }, otherSession);
      const stolenUpload = await call(request(163, "tools/call", { name: "organizer_attachment_upload_status", arguments: { token: upload.token } }), otherSession);
      assert.equal(stolenUpload.result.structuredContent.code, "not_found");
      const uploaded = await call(request(164, "tools/call", { name: "organizer_attachment_upload_append", arguments: { token: upload.token, offset: 0, data: png.toString("base64") } }));
      assert.equal(uploaded.result.structuredContent.received_bytes, png.length);
      const retryUpload = await call(request(165, "tools/call", { name: "organizer_attachment_upload_append", arguments: { token: upload.token, offset: 0, data: png.toString("base64") } }));
      assert.equal(retryUpload.result.structuredContent.received_bytes, png.length);
      const attached = await persisted(166, "organizer_attachment_upload_finalize", { token: upload.token });
      const embedded = b.t.daten().notizen.find(note => note.id === noteId).anhaenge.find(item => item.id === attached.attachment_id);
      assert.ok(embedded.daten.startsWith("data:image/png;base64,"));
      assert.equal(Buffer.from(embedded.daten.split(",")[1], "base64").compare(png), 0);
      const beforeDetach = (await call(request(167, "tools/call", { name: "organizer_note_read", arguments: { id: noteId, fields: ["id"] } }))).result.structuredContent;
      const detached = await persisted(168, "organizer_attachment_remove", { note_id: noteId, attachment_id: attached.attachment_id, expected_revision: beforeDetach.revision });
      assert.equal(b.t.daten().notizen.find(note => note.id === noteId).anhaenge.some(item => item.id === attached.attachment_id), false);
      await persisted(169, "organizer_trash_restore", { id: detached.trash_id });
      assert.ok(b.t.daten().notizen.find(note => note.id === noteId).anhaenge.some(item => item.id === attached.attachment_id));
      const latestAttachmentNote = (await call(request(170, "tools/call", { name: "organizer_note_read", arguments: { id: noteId, fields: ["id"] } }))).result.structuredContent;
      beginArgs.expected_revision = latestAttachmentNote.revision;
      const badHash = (await call(request(171, "tools/call", { name: "organizer_attachment_upload_begin", arguments: { ...beginArgs, sha256: "0".repeat(64) } }))).result.structuredContent;
      await call(request(172, "tools/call", { name: "organizer_attachment_upload_append", arguments: { token: badHash.token, offset: 0, data: png.toString("base64") } }));
      const hashRejected = await call(request(173, "tools/call", { name: "organizer_attachment_upload_finalize", arguments: { token: badHash.token } }));
      assert.equal(hashRejected.result.structuredContent.code, "hash_mismatch");
      const badBytes = Buffer.from("not an image");
      const badMagic = (await call(request(174, "tools/call", { name: "organizer_attachment_upload_begin", arguments: {
        ...beginArgs, size: badBytes.length, sha256: createHash("sha256").update(badBytes).digest("hex") } }))).result.structuredContent;
      await call(request(175, "tools/call", { name: "organizer_attachment_upload_append", arguments: { token: badMagic.token, offset: 0, data: badBytes.toString("base64") } }));
      const magicRejected = await call(request(176, "tools/call", { name: "organizer_attachment_upload_finalize", arguments: { token: badMagic.token } }));
      assert.equal(magicRejected.result.structuredContent.code, "invalid_attachment");
      const ownerUpload = (await call(request(177, "tools/call", { name: "organizer_attachment_upload_begin", arguments: beginArgs }), otherSession)).result.structuredContent;
      const slotUpload = (await call(request(179, "tools/call", { name: "organizer_attachment_upload_begin", arguments: beginArgs }))).result.structuredContent;
      const slotExceeded = await call(request(180, "tools/call", { name: "organizer_attachment_upload_begin", arguments: beginArgs }));
      assert.equal(slotExceeded.result.structuredContent.code, "upload_limit");
      const gap = await call(request(181, "tools/call", { name: "organizer_attachment_upload_append", arguments: { token: slotUpload.token, offset: 1, data: png.subarray(0, 4).toString("base64") } }));
      assert.equal(gap.result.structuredContent.code, "invalid_offset");
      await call(request(182, "tools/call", { name: "organizer_attachment_upload_cancel", arguments: { token: slotUpload.token } }));
      b.w.App.mcpClose(otherSession);
      const ownerRevoked = await call(request(178, "tools/call", { name: "organizer_attachment_upload_status", arguments: { token: ownerUpload.token } }));
      assert.equal(ownerRevoked.result.structuredContent.code, "not_found");
      const expiring = (await call(request(183, "tools/call", { name: "organizer_attachment_upload_begin", arguments: beginArgs }))).result.structuredContent;
      b.timers.filter(timer => timer.delay === 300000 && !timer.cancelled).at(-1).fn();
      const expired = await call(request(184, "tools/call", { name: "organizer_attachment_upload_status", arguments: { token: expiring.token } }));
      assert.equal(expired.result.structuredContent.code, "not_found");
      const oversized = await call(request(185, "tools/call", { name: "organizer_attachment_upload_begin", arguments: { ...beginArgs, size: 8 * 1024 * 1024 + 1 } }));
      assert.equal(oversized.error.code, -32602);
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
      let sourcesSettled = false;
      const sources = call(request(120, "tools/call", { name: "organizer_sync_sources_read" })).then(value => { sourcesSettled = true; return value; });
      await new Promise(resolve => setImmediate(resolve));
      const nativeSources = b.messages.filter(message => message.cmd === "eds_status" && message.requestId).at(-1);
      assert.ok(nativeSources);
      b.w.App.telefonEntwicklerDiagnose({ requestId: nativeSources.requestId, kennung: "wrong callback", ok: true, diagnose: {} });
      b.w.App.edsStatus({ requestId: "wrong-request", verfuegbar: true, kalender: [], adressbuecher: [] });
      await new Promise(resolve => setImmediate(resolve));
      assert.equal(sourcesSettled, false, "A different callback or request completed the native source query");
      b.w.App.edsStatus({ requestId: nativeSources.requestId, verfuegbar: true,
        kalender: [{ uid: "owned-old-calendar", name: "Owned old source" }, { uid: "owned-new-calendar", name: "Owned new source" }], adressbuecher: [] });
      const sourceResult = await sources;
      assert.equal(sourceResult.result.structuredContent.status.kalender[1].uid, "owned-new-calendar");
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
      const restoreArgs = { id: recoveryId, expected_revision: "c".repeat(64), areas: ["notes"], mode: "replace" };
      const staleRestore = await call(request(410, "tools/call", { name: "organizer_recovery_snapshot_restore", arguments: { ...restoreArgs, expected_book_revision: "0".repeat(64) } }));
      assert.equal(staleRestore.result.structuredContent.code, "conflict");
      b.t.daten().notizen.find(note => note.id === "fixture-note").titel = "Owned restore preparation";
      const bookRevision = (await call(request(411, "tools/call", { name: "organizer_book_revision_read" }))).result.structuredContent.revision;
      let restoreRequest;
      const restoreDispatched = new Promise(resolve => { onRecovery = message => { restoreRequest = message; resolve(); }; });
      const restoreSaving = new Promise(resolve => { onSave = resolve; });
      const restoring = call(request(412, "tools/call", { name: "organizer_recovery_snapshot_restore", arguments: { ...restoreArgs, expected_book_revision: bookRevision } }));
      await restoreSaving; b.ack(); await restoreDispatched;
      assert.equal(restoreRequest.expectedRevision, restoreArgs.expected_revision);
      const restoreBusy = await call(request(413, "tools/call", { name: "organizer_note_create", arguments: { title: "Blocked during restore", text: "Owned" } }));
      assert.equal(restoreBusy.result.structuredContent.code, "native_busy");
      const restoredDocument = JSON.parse(JSON.stringify(b.t.daten()));
      restoredDocument.notizen.find(note => note.id === "fixture-note").text = "Owned committed restore";
      b.w.App.journalWiederhergestellt({ requestId: restoreRequest.requestId, ok: true, committed: true, repairPending: true,
        vorher: recoveryId, fehler: "Owned repair warning", daten: restoredDocument });
      const restoredResponse = (await restoring).result.structuredContent;
      assert.equal(restoredResponse.committed, true); assert.equal(restoredResponse.repair_pending, true);
      assert.ok(restoredResponse.book_revision !== bookRevision);
      assert.equal(b.t.daten().notizen.find(note => note.id === "fixture-note").text, "Owned committed restore");
      b.t.daten().notizen.find(note => note.id === "fixture-note").titel = "Owned cancelled restore preparation";
      const cancelledRevision = (await call(request(414, "tools/call", { name: "organizer_book_revision_read" }))).result.structuredContent.revision;
      let cancelledRequest;
      const cancelledDispatched = new Promise(resolve => { onRecovery = message => { cancelledRequest = message; resolve(); }; });
      const cancelledSaving = new Promise(resolve => { onSave = resolve; });
      const cancelledRestore = call(request(415, "tools/call", { name: "organizer_recovery_snapshot_restore", arguments: { ...restoreArgs, expected_book_revision: cancelledRevision } }));
      await cancelledSaving; b.ack(); await cancelledDispatched;
      await call({ jsonrpc: "2.0", method: "notifications/cancelled", params: { requestId: 415 } });
      assert.equal((await cancelledRestore).result.structuredContent.code, "cancelled");
      const lateDocument = JSON.parse(JSON.stringify(b.t.daten()));
      lateDocument.notizen.find(note => note.id === "fixture-note").text = "Owned late committed restore";
      b.w.App.journalWiederhergestellt({ requestId: cancelledRequest.requestId, ok: true, committed: true, vorher: recoveryId, daten: lateDocument });
      assert.equal(b.t.daten().notizen.find(note => note.id === "fixture-note").text, "Owned late committed restore");
      onRecovery = null;
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
