"use strict";
// Actual Python imports reach the unchanged desktop App import/save/display
// code through the existing JSDOM harness. No native window or server claim.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict"), crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
if (process.argv.length !== 6) {
  console.error("Usage: node independent-birthday-display.cjs CHECKOUT PYTHON FIXTURES OUTPUT");
  process.exit(2);
}
const checkout = path.resolve(process.argv[2]), python = process.argv[3];
const fixtures = path.resolve(process.argv[4]), output = path.resolve(process.argv[5]);
const cases = JSON.parse(execFileSync(python, ["-c", `
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'magnolie-organizer/pruefungen'));sys.modules['gi']=None
from modul_laden import quellmodul_laden
m=quellmodul_laden('independent_845_display',root/'magnolie-organizer/bin/magnolie-organizer')
result=[]
for case in json.loads(Path(sys.argv[2]).read_text())['cases']:
    if case['id'] not in ('known-leap','yearless-leap'):continue
    payload=m.ics_lesen(case['ics']);payload.update(art='ics',abgebrochen=False)
    result.append({'id':case['id'],'expected_date':case['date'],'payload':payload})
print(json.dumps(result))
`, checkout, fixtures], { encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } }));
assert.equal(cases.length, 2);
const harnessPath = path.join(checkout, "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot};", harnessPath);
const plain = value => JSON.parse(JSON.stringify(value));
const digest = file => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
(async () => {
  const results = [];
  for (const edition of ["magnolie-organizer/web", "magnolie-organizer-windows/app/web"]) {
    for (const test of cases) {
      const result = { edition, id: test.id, expected_date: test.expected_date, projections: [] };
      let b;
      try {
        b = await harness.exports.boot(path.join(checkout, edition));
        await b.w.App.importErgebnis(plain(test.payload));
        assert.equal(b.t.daten().termine.length, 0, "Explicit Nextcloud BDAY remained an ordinary appointment");
        assert.equal(b.t.daten().jahrestage.length, 1);
        const item = b.t.daten().jahrestage[0];
        assert.equal(item.datum, test.expected_date); assert.equal(item.typ, "birthday");
        assert.equal(item.akzentFarbe, "#ff0000");
        for (const [day, absent] of [["2027-02-28", "2027-03-01"], ["2028-02-29", "2028-02-28"]]) {
          assert.equal(b.t.jahrestageAm(day, true).length, 1, "Missing last-February-day projection");
          assert.equal(b.t.jahrestageAm(absent, true).length, 0, "Birthday projected on the wrong day");
          Object.assign(b.t.zustand().kalender, { jahr: Number(day.slice(0, 4)), monat: 1, tag: day, ansicht: "day" });
          await b.t.wechsel("planer"); await b.t.wechsel("kalender");
          const marker = b.w.document.querySelector(".jt-kasten");
          assert.ok(marker, "Actual day view has no annual-entry banner");
          assert.equal(marker.querySelector("[data-akzent-farbe]")?.dataset.akzentFarbe, "#ff0000");
          assert.ok(marker.textContent.includes(item.name));
          if (test.id === "yearless-leap") assert.ok(!/1972|years|Jahre/.test(marker.textContent), "Unknown year produced an invented age");
          result.projections.push({ day, absent, text: marker.textContent, accent: "#ff0000" });
        }
        b.t.speichereJetzt(); const save = b.saves().at(-1); assert.ok(save);
        const book = JSON.parse(save.text); b.ack(); b.close(); b = undefined;
        b = await harness.exports.boot(path.join(checkout, edition), book);
        assert.equal(b.t.daten().jahrestage[0].datum, test.expected_date);
        assert.equal(b.t.daten().jahrestage[0].akzentFarbe, "#ff0000");
        assert.equal(b.t.jahrestageAm("2027-02-28", true).length, 1);
        result.saved_reload_pass = true; result.passed = true;
      } catch (error) {
        result.passed = false; result.error = error.message;
      } finally { b?.close(); }
      results.push(result); console.log(JSON.stringify(result));
    }
  }
  const paths = ["magnolie-organizer/bin/magnolie-organizer", "magnolie-organizer/web/anwendung.js",
    "magnolie-organizer-windows/app/web/anwendung.js", "magnolie-organizer-windows/tests/desktop-state-regressions.js"];
  const report = { checkout, head: execFileSync("git", ["rev-parse", "HEAD"], { cwd: checkout, encoding: "utf8" }).trim(),
    fixture: fixtures, fixture_sha256: digest(fixtures), source_sha256: Object.fromEntries(paths.map(file => [file, digest(path.join(checkout, file))])),
    cases: results, passed: results.filter(result => result.passed).length,
    boundary_de: "Vier tatsächliche App-Import-/Anzeige-/Save-Reload-Fälle in JSDOM mit echten Python-Codec-Payloads. Beide Desktop-JavaScript-Ausgaben, keine Ausführung des C#-Codecs durch diese Probe. Bridge simuliert, keine native GTK-/WebView-, Datei-/Server- oder Geräteabnahme." };
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
  if (report.passed !== results.length) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
