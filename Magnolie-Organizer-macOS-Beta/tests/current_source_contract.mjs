// Refs #783: current local UI fixes do not grant unimplemented native capabilities.
import assert from "node:assert/strict";
import fs from "node:fs";
import { boot, tick } from "./ui_harness.mjs";

const contract = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const allowed = new Set(contract.allowed);
const clone = value => JSON.parse(JSON.stringify(value));
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const b = await boot(process.argv[2]);
const { w, t, messages } = b;
try {
  w.MacBeta.receive("init", { daten: {}, neu: false, regional: { language: "en", timeZone: "UTC" } });
  // Reuse the actual shared #720 search probe, including local-zone date edges.
  const probe = fs.readFileSync(new URL("../../magnolie-organizer/pruefungen/notes-date-search-probe.js", import.meta.url), "utf8");
  const searched = JSON.parse(w.eval(probe + "\nJSON.stringify(notesDateSearchProbe());"));
  equal(searched.checks, 30, "Current shared date-search assertions run in the generated Mac UI");
  equal(searched.errors, [], "Current note-search behavior survives Mac projection");

  // #744: the new shared keyboard handler must also be present and active.
  w.MacBeta.receive("init", { daten: {}, neu: false, regional: { language: "en", timeZone: "UTC" } });
  t.oeffneBuch();
  await t.wechsel("aufgaben");
  Object.assign(t.zustand().kalender, { ansicht: "month", jahr: 2026, monat: 11, tag: "2026-12-31" });
  await t.wechsel("kalender");
  const key = (target, options = {}) => {
    const event = new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true, ...options });
    target.dispatchEvent(event); return event.defaultPrevented;
  };
  equal(key(w.document.body), true, "Current calendar spread navigation handles the arrow");
  equal([t.zustand().kalender.jahr, t.zustand().kalender.monat], [2027, 0], "Calendar advances across the year");
  const input = w.document.createElement("input"); input.value = "Local text"; w.document.body.append(input);
  equal(key(input), false, "An editable field keeps its arrow key"); input.remove();
  equal(key(w.document.body, { metaKey: true }), false, "Command shortcuts are not consumed by spread navigation");

  // These are stored provenance-shaped values, not native permissions. Existing
  // import suites separately execute each actual reviewed-copy transaction.
  const data = t.leereDaten();
  const provenance = { version: 1, sourceUID: "synthetic-source", identifier: "synthetic-record", permission: "full", readOnly: false };
  data.notizen = [{ id: "note-copy", titel: "Local note", text: "Keep", nativeAppleNotesImport: clone(provenance) }];
  data.kontakte = [{ id: "contact-copy", vorname: "Local", nativeContactImport: clone(provenance) }];
  data.aufgaben = [{ id: "task-copy", uid: "task-copy-uid", titel: "Local task", nativeReminderImport: clone(provenance) }];
  data.termine = [{ id: "event-copy", uid: "event-copy-uid", titel: "Local event", datum: "2026-12-01", nativeCalendarImport: clone(provenance) }];
  data.einstellungen.sync.automatisch = true;
  w.MacBeta.receive("init", { daten: data, neu: false, regional: { language: "en", timeZone: "UTC" } });
  await tick();
  for (const key of ["notizen", "kontakte", "aufgaben", "termine"])
    equal(t.daten()[key][0].sync === true, false, key + ": provenance does not enable source synchronization");
  const before = JSON.stringify(t.daten()), sent = messages.length;
  t.starteSync(false); t.starteSync(true);
  equal(messages.length, sent, "Current shared sync entry point retains the Mac limitation");
  for (const cmd of contract.unavailable) {
    if (cmd === "sync") continue;
    assert.ok(!allowed.has(cmd));
    w.MacBeta.send({ cmd }, "hostTest");
  }
  await tick();
  equal(messages.length, sent, "Unimplemented desktop commands never reach the native Mac handler");
  equal(JSON.stringify(t.daten()), before, "Negative capability replies preserve the whole local document");
  // A directly rejected legacy sync request intentionally records diagnostics.
  // This existing local error record is neither a sync ACK nor native authority.
  assert.ok(contract.unavailable.includes("sync"));
  w.MacBeta.send({ cmd: "sync" }, "hostTest"); await tick();
  const afterSync = clone(t.daten()), beforeSync = JSON.parse(before);
  equal(afterSync.syncStatus.letzterFehler.includes("Not implemented"), true, "Rejected sync records an explicit limitation");
  equal(afterSync.syncStatus.letzterVersuch > 0, true, "Rejected sync records the local attempt time");
  delete afterSync.syncStatus; delete beforeSync.syncStatus;
  equal(afterSync, beforeSync, "Sync diagnostics grant no other data or permissions");
  equal(messages.length, sent, "Rejected sync never reaches the native handler");
  for (const method of ["notesOriginalSpeichern", "notesSetupVorbereiten", "telefonStand", "originalKontaktFreigabe"]) {
    assert.throws(() => w.MacBeta.receive(method, {}), /Invalid native callback/); checks++;
  }
  // Explicit local copy requests remain supported. Availability of an external
  // KDE Connect client is independent of this current Organizer adapter list.
  for (const cmd of ["notiz_dateien_importieren", "macos_kalender_importieren", "macos_apple_notizen_importieren",
                     "macos_kontakte_importieren", "macos_erinnerungen_importieren"]) {
    assert.ok(allowed.has(cmd)); w.MacBeta.send({ cmd }, "hostTest");
    equal(messages.at(-1), { cmd }, "Existing Mac local-copy request remains available");
  }
  equal(messages.every(message => allowed.has(message.cmd)), true, "All observed native traffic uses the actual Swift allowlist");
  console.log(JSON.stringify({ issue: 783, assertions: checks, sharedDateSearchAssertions: searched.checks,
    unavailableDesktopCommands: contract.unavailable.length, currentSharedUI: true,
    syntheticNativeTransport: true, nativeExecution: false }));
} finally { b.close(); }
