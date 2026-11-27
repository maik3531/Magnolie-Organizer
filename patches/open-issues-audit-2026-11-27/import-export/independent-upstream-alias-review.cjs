"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const crypto = require("node:crypto"), { execFileSync } = require("node:child_process");
const root = path.resolve(process.argv[2]), baseline = path.resolve(process.argv[3]);
const python = process.argv[4], output = path.resolve(process.argv[5]);
const fixture = path.join(root, "magnolie-organizer/pruefungen/fixtures/caldav-series-resource.ics");
function payload(checkout) {
  return JSON.parse(execFileSync(python, ["-c", `
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'magnolie-organizer/pruefungen'));sys.modules['gi']=None
from modul_laden import quellmodul_laden
m=quellmodul_laden('independent844alias',root/'magnolie-organizer/bin/magnolie-organizer')
value=m.ics_lesen(Path(sys.argv[2]).read_text(),quellenname='Synthetic ICS',quellen_id='ics:'+'a'*64)
value.update(art='ics',abgebrochen=False)
print(json.dumps(value))
`, checkout, fixture], { encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } }));
}
const payloads = [{ label: "actual-pre-844-codec-payload", value: payload(baseline) },
  { label: "actual-upstream-844-codec-payload", value: payload(root) }];
const harnessPath = path.join(root, "magnolie-organizer-windows/tests/save-custom-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("const cases = [")[0] + "\nmodule.exports={boot};", harnessPath);
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  const results = [];
  for (const edition of ["magnolie-organizer/web", "magnolie-organizer-windows/app/web"]) {
    for (const incoming of payloads) {
      const b = await harness.exports.boot(path.join(root, edition));
      try {
        const book = plain(b.t.daten()); book.termine = plain(incoming.value.termine);
        const legacy = book.termine.find(item => item.uid.endsWith("-1201680171431eb3"));
        if (!legacy) throw new Error("Actual fixture exception missing");
        legacy.id = "independent-legacy-844"; legacy.uid = "caldav-series-1-magnolie-instanz-7f5e24178d89f683";
        legacy.geaendert = 1; legacy.titel = "Original before update";
        b.w.App.init({ daten: book, neu: false, regional: { language: "en", timeZone: "UTC" } });
        let thrown = null;
        try { await Promise.resolve(b.w.App.importErgebnis(plain(incoming.value))); }
        catch (error) { thrown = String(error); }
        const current = b.t.daten().termine.find(item => item.id === legacy.id);
        results.push({ edition, payload: incoming.label,
          incoming_has_icsCalendarColor: Object.prototype.hasOwnProperty.call(incoming.value.termine[0], "icsCalendarColor"),
          count: b.t.daten().termine.length, title: current?.titel, changed: current?.geaendert,
          original_identity_preserved: current?.uid === legacy.uid,
          import_failed_ui: b.w.document.body.textContent.includes("Import failed"), thrown,
          passed: !thrown && b.t.daten().termine.length === 2 && current?.geaendert > 1 && current?.uid === legacy.uid });
      } finally { b.close(); }
    }
  }
  const sources = Object.fromEntries(["magnolie-organizer/web/anwendung.js", "magnolie-organizer-windows/app/web/anwendung.js"]
    .map(file => [file, crypto.createHash("sha256").update(fs.readFileSync(path.join(root, file))).digest("hex")]));
  const report = { root, baseline, head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim(),
    sources, results, boundary_de: "Vier enge tatsächliche DOM-Importfälle mit realen alten bzw. aktuellen Python-Codec-Payloads; vorhandener Save-Harness mit synthetischer Bridge, kein natives Dateisystem-/Notes-Gerät." };
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  for (const row of results) console.log(JSON.stringify(row));
})().catch(error => { console.error(error); process.exitCode = 1; });
