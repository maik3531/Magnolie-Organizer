"use strict";
// Refs #462: full desktop frontends with actual Python codec result or captured
// native Windows DTO. Save ACKs are synthetic; no native persistence/GUI claim.
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const { execFileSync } = require("node:child_process");
const windows = path.resolve(__dirname, ".."), root = path.dirname(windows);
const linux = process.env.MAGNOLIE_LINUX_SOURCE || path.join(root, "magnolie-organizer");
if (!fs.existsSync(path.join(linux, "bin", "magnolie-organizer"))) {
  console.log("NOT APPLICABLE legacy Android cross-codec UI probe: canonical Linux source is not available"); process.exit(0);
}
const harnessPath = path.join(__dirname, "save-custom-regressions.js"), harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(harnessPath, "utf8").split("const cases = [")[0] + "\nmodule.exports = { boot };", harnessPath);
const plain = value => JSON.parse(JSON.stringify(value));
const codec = JSON.parse(execFileSync(process.env.MAGNOLIE_PYTHON || "python3", ["-c", `
import importlib.machinery,importlib.util,json,sys
from pathlib import Path
root=Path(sys.argv[1]);p=root/'bin/magnolie-organizer'
loader=importlib.machinery.SourceFileLoader('legacy462',str(p));spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)
text=(root/'pruefungen/fixtures/caldav-series-resource.ics').read_text()
def parse(value,source='ics:'+'a'*64):
 return dict(m.ics_lesen(value,quellenname='Synthetic ICS',quellen_id=source),art='ics',abgebrochen=False)
rid='RECURRENCE-ID;TZID=Europe/Berlin:20261102T100000'
variants=dict(source=parse(text,'ics:'+'b'*64),rid=parse(text.replace(rid,'RECURRENCE-ID;TZID=Europe/Berlin:20261109T100000')),
 tzid=parse(text.replace(rid,'RECURRENCE-ID;TZID=Europe/Paris:20261102T100000')),
 range=parse(text.replace(rid,'RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=Europe/Berlin:20261102T100000')),
 value=parse(text.replace(rid,'RECURRENCE-ID;VALUE=DATE-TIME;TZID=Europe/Berlin:20261102T100000')),
 wire=parse(text.replace('UID:caldav-series-1','UID:other-series-462')))
print(json.dumps(dict(base=parse(text),variants=variants),ensure_ascii=False))
`, linux], { encoding: "utf8", timeout: 15000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } }));
const nativePayload = process.env.MAGNOLIE_462_NATIVE_IMPORT;
const payload = nativePayload ? JSON.parse(fs.readFileSync(nativePayload, "utf8")) : codec.base;

(async () => {
  let failed = false;
  for (const web of [path.join(linux, "web"), path.join(windows, "app/web")]) {
    const b = await harness.exports.boot(web);
    try {
      const incoming = plain(payload);
      assert.equal(incoming.termine.length, 2);
      const exception = incoming.termine.find(item => (item.icsRoundtrip || []).some(line => /^RECURRENCE-ID[;:]/i.test(line)));
      assert(exception, "Actual current codec did not return the canonical fixture exception");
      if (!nativePayload) assert(exception.uid.endsWith("-1201680171431eb3"));
      const old = plain(b.t.daten()); old.termine = plain(incoming.termine);
      const legacy = old.termine.find(item => item.uid === exception.uid);
      legacy.id = "legacy-instance-local"; legacy.uid = "caldav-series-1-magnolie-instanz-7f5e24178d89f683";
      legacy.geaendert = 1; legacy.futureMetadata = { nested: ["keep", 1] };
      legacy.alarme = [{ id: "local-alarm", offsetMinuten: 5, aktion: "display", aktiviert: true,
        related: "START", quelle: "magnolie", bearbeitbar: true }];
      legacy.teilnehmer = [{ id: "local-person", uri: "mailto:old@example.invalid", name: "Keep", status: "accepted" }];
      legacy.kalenderAnhaenge = [{ id: "local-file", uri: "https://example.invalid/keep", name: "Keep.txt", mimeType: "text/plain", groesse: 3 }];
      legacy.providerMetadaten = { legacy: { id: "keep" } };
      old.aufgaben = [{ id: "task-reference", titel: "Keep link", terminId: legacy.id, notiz: "Keep" }];
      b.w.App.init({ daten: old, neu: false, regional: { language: "en", timeZone: "UTC" } });
      assert.equal(b.t.daten().termine.length, 2, "Old fixture was not valid before import");
      const preserved = plain(b.t.daten().termine.find(item => item.id === legacy.id));
      assert.equal(preserved.alarme.length, 1); assert.equal(preserved.teilnehmer.length, 1);
      for (let pass = 0; pass < 2; pass++) {
        await Promise.resolve(b.w.App.importErgebnis(plain(incoming)));
        b.t.speichereJetzt(); const save = b.saves().at(-1); b.ack(save);
        const stored = JSON.parse(save.text);
        assert.equal(stored.termine.length, 2, "Reimport saved duplicate old-Android exception (expected 2 records)");
        const current = b.t.daten().termine.find(item => item.id === legacy.id);
        assert.equal(current.uid, legacy.uid); assert.equal(stored.aufgaben.find(item => item.id === "task-reference").terminId, legacy.id);
        for (const field of ["futureMetadata", "alarme", "teilnehmer", "kalenderAnhaenge", "providerMetadaten"])
          assert.deepEqual(plain(current[field]), preserved[field], "Alias import erased old local data: " + field);
        b.w.App.init({ daten: stored, neu: false, regional: { language: "en", timeZone: "UTC" } });
        assert.equal(b.t.daten().termine.length, 2, "Saved alias import changed count on frontend reopen");
      }
      for (const [name, variant] of Object.entries(codec.variants)) {
        b.w.App.init({ daten: plain(old), neu: false, regional: { language: "en", timeZone: "UTC" } });
        await Promise.resolve(b.w.App.importErgebnis(plain(variant)));
        const count = ["source", "wire"].includes(name) ? 4 : 3;
        assert.equal(b.t.daten().termine.length, count, "Alias merged a different qualified identity: " + name + " " +
          JSON.stringify(b.t.daten().termine.map(t => [t.uid, t.icsQuelleId, t.icsSerienUid])));
        b.t.speichereJetzt(); const save = b.saves().at(-1); b.ack(save); const stored = JSON.parse(save.text);
        assert.equal(stored.termine.length, count, "Save folded a distinct identity: " + name);
        b.w.App.init({ daten: stored, neu: false, regional: { language: "en", timeZone: "UTC" } });
        assert.equal(b.t.daten().termine.length, count, "Frontend reopen folded a distinct full RID identity: " + name);
      }
      for (const ambiguity of ["two_old", "old_and_canonical", "old_and_unknown", "unknown_hash", "two_incoming"]) {
        b.w.App.init({ daten: plain(old), neu: false, regional: { language: "en", timeZone: "UTC" } });
        const attempt = plain(incoming), current = b.t.daten().termine.find(item => item.id === legacy.id);
        if (ambiguity === "two_old") b.t.daten().termine.push({ ...plain(current), id: "second-old-local" });
        if (ambiguity === "old_and_canonical") b.t.daten().termine.push({ ...plain(exception), id: "already-canonical" });
        if (ambiguity === "old_and_unknown") b.t.daten().termine.push({ ...plain(current), id: "unknown-second-local", uid: "unknown-instance" });
        if (ambiguity === "unknown_hash") current.uid = "caldav-series-1-magnolie-instanz-0000000000000000";
        if (ambiguity === "two_incoming") attempt.termine.push({ ...plain(exception), uid: exception.uid + "-other" });
        attempt.notizen = [{ titel: "Must not import", text: "Ambiguous alias" }];
        attempt.aufgaben = [{ uid: "must-not-import", titel: "Ambiguous alias" }];
        attempt.kontakte = [{ uid: "must-not-import", vorname: "Keep out" }];
        const before = JSON.stringify(b.t.daten()), saves = b.saves().length;
        await Promise.resolve(b.w.App.importErgebnis(attempt));
        assert.equal(JSON.stringify(b.t.daten()), before, "Ambiguous alias mutated any collection: " + ambiguity);
        assert.equal(b.saves().length, saves, "Ambiguous alias queued a save: " + ambiguity);
        assert(b.w.document.body.textContent.includes("Import failed"), "Ambiguous alias did not report failure: " + ambiguity);
      }
      b.w.App.init({ daten: plain(old), neu: false, regional: { language: "en", timeZone: "UTC" } });
      const subtle = b.w.crypto.subtle, digest = subtle.digest;
      const legacyText = JSON.stringify([{ TZID: "Europe/Berlin" }, "20261102T100000"]).replace(/\//g, "\\/");
      let release, reached = false; const gate = new Promise(resolve => { release = resolve; });
      subtle.digest = function(algorithm, data) {
        if (new TextDecoder().decode(data) === legacyText) { reached = true; return gate.then(() => digest.call(this, algorithm, data)); }
        return digest.call(this, algorithm, data);
      };
      try {
        const importing = b.w.App.importErgebnis(plain(incoming));
        assert(reached, "Alias preflight did not use the actual legacy digest");
        b.t.daten().aufgaben[0].notiz = "Concurrent book edit"; release();
        await Promise.resolve(importing);
        assert.equal(b.t.daten().termine.length, 2);
        assert.equal(b.t.daten().termine.find(item => item.id === legacy.id).geaendert, 1, "Import committed against a changed book");
        assert.equal(b.t.daten().aufgaben[0].notiz, "Concurrent book edit", "Async alias check lost a current edit");
      } finally { release(); subtle.digest = digest; }
      console.log("PASS " + path.relative(root, web) + ": " + (nativePayload ? "actual native Windows codec" : "actual Python codec") +
        ", old alias reimport/save/frontend reopen, full source/RID boundaries, ambiguous inputs and concurrent book edit");
    } catch (error) {
      failed = true; console.error("FAIL " + path.relative(root, web) + ": " + error.message);
    } finally { b.close(); }
  }
  if (failed) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
