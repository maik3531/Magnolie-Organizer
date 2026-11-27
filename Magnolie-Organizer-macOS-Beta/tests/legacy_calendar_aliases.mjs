import assert from "node:assert/strict";
import fs from "node:fs";
import { boot, tick } from "./ui_harness.mjs";

const [root, fixturePath] = process.argv.slice(2), fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const probe = process.argv.includes("--probe"), clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
let checks = 0;
const equal = (actual, expected, label) => { assert.deepEqual(clone(actual), clone(expected), label); checks++; };
const ok = (value, label) => { assert.ok(value, label); checks++; };
const b = await boot(root), { w, t, messages, timers } = b;
const incoming = fixture.base, alias = incoming.legacyAndroidAliases.entries[0];
const localFields = ["futureMetadata", "alarme", "teilnehmer", "kalenderAnhaenge", "providerMetadaten"];
const old = { termine: clone(incoming.termine), aufgaben: [{ id: "task-reference", titel: "Keep link", terminId: "legacy-instance-local", notiz: "Keep" }],
  kontakte: [], notizen: [], jahrestage: [], futureRoot: { keep: true },
  einstellungen: { allgemein: { handbuchHinweisGezeigt: true } } };
for (const [index, row] of old.termine.entries()) row.id = "record-" + index;
const legacy = old.termine[alias.appointmentIndex];
Object.assign(legacy, { id: "legacy-instance-local", uid: alias.legacyUID, titel: "Old retained row", geaendert: 1,
  futureMetadata: { nested: ["keep", 1] },
  alarme: [{ id: "local-alarm", offsetMinuten: 5, aktion: "display", aktiviert: true, related: "START", quelle: "magnolie", bearbeitbar: true }],
  teilnehmer: [{ id: "local-person", uri: "mailto:old@example.invalid", name: "Keep", status: "accepted" }],
  kalenderAnhaenge: [{ id: "local-file", uri: "https://example.invalid/keep", name: "Keep.txt", mimeType: "text/plain", groesse: 3 }],
  providerMetadaten: { legacy: { id: "keep" } } });
const init = () => w.MacBeta.receive("init", { daten: clone(old), neu: false, regional: { language: "en", timeZone: "UTC" } });
const saved = () => messages.filter(message => message.cmd === "speichern");
async function finish(result) {
  let settled = false, failure;
  Promise.resolve(result).then(() => { settled = true; }, error => { settled = true; failure = error; });
  for (let attempt = 0; attempt < 100 && !settled; attempt++) {
    for (const timer of timers) if (!timer.cancelled && !timer.fired && timer.delay === 0) { timer.fired = true; timer.fn(); }
    await tick();
  }
  assert.ok(settled, "Calendar callback did not finish");
  if (failure) throw failure;
  await tick();
}
async function receive(payload) { await finish(w.MacBeta.receive("importErgebnis", payload)); }
function saveAndReopen() {
  t.speichereJetzt(); const save = saved().at(-1);
  ok(save && typeof save.text === "string", "Actual save envelope is available");
  const stored = JSON.parse(save.text);
  ok(!save.text.includes('"legacyAndroidAliases"'), "Native alias proof must never be persisted");
  w.MacBeta.receive("gespeichert", { id: save.id, ok: true });
  w.MacBeta.receive("init", { daten: stored, neu: false, regional: { language: "en", timeZone: "UTC" } });
  return stored;
}
try {
  // This deliberately excludes WebCrypto. It proves native evidence adoption,
  // not a claim that any particular installed WebKit lacks crypto.subtle.
  equal(w.crypto.subtle, undefined, "Use the existing harness without injected WebCrypto");
  init();
  const preserved = clone(t.daten().termine.find(row => row.id === legacy.id));
  for (let pass = 0; pass < 2; pass++) {
    await receive(clone(incoming));
    const current = t.daten().termine.find(row => row.id === legacy.id);
    equal(current.titel, incoming.termine[alias.appointmentIndex].titel, "Native evidence must update the exact old alias without WebCrypto");
    equal(t.daten().termine.length, 2, "Reimport must not append an exception duplicate");
    equal(current.uid, alias.legacyUID, "Keep the old primary UID");
    for (const key of localFields) equal(current[key], preserved[key], "Retain local/unknown field " + key);
    equal(t.daten().aufgaben[0].terminId, legacy.id, "Keep existing local reference");
    equal(saveAndReopen().termine.length, 2, "Save and frontend reopen retain the pair");
  }
  if (probe) process.exit(0);

  for (const [name, variant] of Object.entries(fixture.variants)) {
    init(); await receive(clone(variant));
    const count = ["source", "wire"].includes(name) ? 4 : 3;
    equal(t.daten().termine.length, count, "Do not alias a different complete native identity: " + name);
    equal(saveAndReopen().termine.length, count, "Save/reopen keeps distinct identity: " + name);
  }
  for (const kind of ["two_old", "old_and_canonical", "old_and_unknown", "unknown_hash", "two_incoming"]) {
    init(); const attempt = clone(incoming), current = t.daten().termine.find(row => row.id === legacy.id);
    if (kind === "two_old") t.daten().termine.push({ ...clone(current), id: "second-old-local" });
    if (kind === "old_and_canonical") t.daten().termine.push({ ...clone(incoming.termine[alias.appointmentIndex]), id: "already-canonical" });
    if (kind === "old_and_unknown") t.daten().termine.push({ ...clone(current), id: "unknown-second-local", uid: "unknown-instance" });
    if (kind === "unknown_hash") current.uid = "caldav-series-1-magnolie-instanz-0000000000000000";
    if (kind === "two_incoming") {
      attempt.termine.push({ ...clone(attempt.termine[alias.appointmentIndex]), uid: alias.canonicalUID + "-other" });
      attempt.legacyAndroidAliases.appointmentCount++;
    }
    attempt.notizen = [{ titel: "Must not import", text: "Ambiguous alias" }];
    attempt.aufgaben = [{ uid: "must-not-import", titel: "Ambiguous alias" }];
    attempt.kontakte = [{ uid: "must-not-import", vorname: "Keep out" }];
    const before = JSON.stringify(t.daten()), saves = saved().length;
    await receive(attempt);
    equal(JSON.stringify(t.daten()), before, "Ambiguous evidence must not mutate any collection: " + kind);
    equal(saved().length, saves, "Ambiguous evidence must not queue a save: " + kind);
    ok(w.document.body.textContent.includes("Import failed"), "Report ambiguous import: " + kind);
  }
  const corruptions = {
    sourceHash: value => { value.legacyAndroidAliases.sourceSHA256 = "0".repeat(64); },
    count: value => { value.legacyAndroidAliases.appointmentCount++; },
    index: value => { value.legacyAndroidAliases.entries[0].appointmentIndex = 0; },
    canonical: value => { value.legacyAndroidAliases.entries[0].canonicalUID = "wrong-magnolie-instanz-" + "0".repeat(16); },
    legacy: value => { value.legacyAndroidAliases.entries[0].legacyUID = "caldav-series-1-magnolie-instanz-" + "0".repeat(16); },
    source: value => { value.legacyAndroidAliases.entries[0].sourceID = "ics:" + "c".repeat(64); },
    wire: value => { value.legacyAndroidAliases.entries[0].wireUID += "-other"; },
    rid: value => { value.legacyAndroidAliases.entries[0].recurrenceLine += "Z"; },
    algorithm: value => { value.legacyAndroidAliases.algorithm = "other"; },
    duplicateEntry: value => { value.legacyAndroidAliases.entries.push(clone(value.legacyAndroidAliases.entries[0])); },
    absentEntry: value => { value.legacyAndroidAliases.entries = []; },
    extraKey: value => { value.legacyAndroidAliases.authorization = true; },
    rowIdentity: value => { value.termine[alias.appointmentIndex].icsQuelleId += "-other"; },
    duplicateRID: value => { value.termine[alias.appointmentIndex].icsRoundtrip.push(alias.recurrenceLine); }
  };
  for (const [name, corrupt] of Object.entries(corruptions)) {
    init(); const attempt = clone(incoming); corrupt(attempt);
    const before = JSON.stringify(t.daten()), saves = saved().length;
    await receive(attempt);
    equal(JSON.stringify(t.daten()), before, "Reject corrupt native binding before mutation: " + name);
    equal(saved().length, saves, "Reject corrupt native binding before save: " + name);
  }
  init();
  const directBefore = JSON.stringify(t.daten());
  await finish(w.App.importErgebnis(clone(incoming)));
  equal(JSON.stringify(t.daten()), directBefore, "A sidecar without native callback registration is not proof");

  const large = clone(incoming);
  for (let index = 0; index < 999; index++) large.termine.push({ uid: "ordinary-" + index,
    titel: "Ordinary " + index, datum: "2030-01-01", zeit: "10:00", geaendert: 1,
    icsQuelleId: alias.sourceID, icsSerienUid: "", icsRoundtrip: ["UID:ordinary-" + index, "DTSTART:20300101T100000"] });
  large.legacyAndroidAliases.appointmentCount = large.termine.length;
  init(); await receive(clone(large));
  equal(t.daten().termine.length, 1001, "Chunked normalization retains transient native proof");
  equal(t.daten().termine.find(row => row.id === legacy.id).uid, alias.legacyUID, "Chunked import preserves the old UID");
  equal(saveAndReopen().termine.length, 1001, "Chunked saved result reopens without alias proof");

  init(); const ongoing = w.MacBeta.receive("importErgebnis", clone(large));
  t.daten().aufgaben[0].notiz = "Concurrent book edit";
  const changed = JSON.stringify(t.daten());
  await finish(ongoing);
  equal(JSON.stringify(t.daten()), changed, "Changed book invalidates evidence before any collection mutation");

  init(); const detached = clone(incoming), pending = w.MacBeta.receive("importErgebnis", detached);
  detached.legacyAndroidAliases.entries[0].legacyUID = "tampered";
  detached.termine[alias.appointmentIndex].titel = "Caller mutation";
  await finish(pending);
  equal(t.daten().termine.find(row => row.id === legacy.id).titel, incoming.termine[alias.appointmentIndex].titel,
    "Native callback owns its input snapshot");

  init();
  const replacement = w.MacBeta.receive("importErgebnis", clone(large));
  init(); const reopened = JSON.stringify(t.daten());
  await finish(replacement);
  equal(JSON.stringify(t.daten()), reopened, "Document replacement rejects a pending older alias receipt");
  console.log(`Mac legacy calendar aliases: ${checks} checks passed; ${fixture.nativeEnvelope ? "actual Swift base DTO" : "synthetic native sidecar over actual Python codec"}, actual projected UI, synthetic Save ACK/frontend reopen; no native AppKit/disk evidence.`);
} finally { b.close(); }
