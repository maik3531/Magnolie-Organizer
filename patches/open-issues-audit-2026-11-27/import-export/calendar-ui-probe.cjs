"use strict";
// Actual desktop import callback, normalization, form display and save payload.
// This is a JSDOM contract test; it is not a native GTK/WebView test.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const [checkout, inputFile, outputDirectory] = process.argv.slice(2);
if (!outputDirectory) throw new Error("checkout imported.json output-directory");
const harnessPath = path.resolve(checkout, "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] +
  "\nmodule.exports={boot,roots};", harnessPath);
const cases = JSON.parse(fs.readFileSync(inputFile, "utf8"));
const plain = value => JSON.parse(JSON.stringify(value));
fs.mkdirSync(outputDirectory, { recursive: true });
(async () => {
  for (const web of harness.exports.roots) {
    const platform = web.includes("magnolie-organizer-windows") ? "windows" : "linux";
    const results = [];
    for (const item of cases) {
      const b = await harness.exports.boot(web);
      try {
        await b.w.App.importErgebnis(plain(item.payload));
        const data = b.t.daten(), kind = ["termine", "aufgaben", "jahrestage"].find(key => data[key]?.length);
        const observation = { counts: Object.fromEntries(["termine", "aufgaben", "jahrestage"].map(key => [key, data[key].length])) };
        if (kind === "termine") {
          b.t.oeffneTerminBlatt(data.termine[0], data.termine[0].datum);
          observation.custom_color_checked = b.w.document.getElementById("tb-eigene-farbe").checked;
          observation.color_picker = b.w.document.getElementById("tb-farbe").value;
          b.w.document.querySelector("#termin-schleier header > button").click();
        } else if (kind === "aufgaben") {
          await b.t.wechsel("aufgaben"); b.w.document.querySelector("#inhalt-links li.zeile").click();
          observation.custom_color_checked = b.w.document.getElementById("aufgabe-eigene-farbe").checked;
          observation.color_picker = b.w.document.getElementById("aufgabe-farbe").value;
          // No changes are made by observing the current form.
        } else if (kind === "jahrestage") {
          await b.t.wechsel("jahrestage");
          observation.anniversary_rows = b.w.document.querySelectorAll(".jahrestage-liste .zeile").length;
          observation.type = data.jahrestage[0].typ;
        }
        b.t.speichereJetzt();
        const save = b.saves().at(-1); if (!save) throw new Error("No actual save request for " + item.id);
        const book = JSON.parse(save.text); b.ack();
        results.push({ id: item.id, book, observation });
      } finally { b.close(); }
    }
    fs.writeFileSync(path.join(outputDirectory, platform + ".json"), JSON.stringify(results, null, 2) + "\n");
    console.log(JSON.stringify({ platform, cases: results.length, path: path.join(outputDirectory, platform + ".json") }));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
