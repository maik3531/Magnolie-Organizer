"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const repo = path.resolve(process.argv[2] || "$REVIEW_WORKSPACE/round2-ui");
const file = path.join(repo, "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(path.dirname(file));
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  const results = [];
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
    try {
      const errors = [];
      b.w.addEventListener("error", event => { errors.push(String(event.error)); event.preventDefault(); });
      const reads = [];
      const originalReadAsText = b.w.FileReader.prototype.readAsText;
      b.w.FileReader.prototype.readAsText = function (file) {
        reads.push({ name: file.name, size: file.size });
        // jsdom silently discards FileReader listener exceptions (the reader
        // has no ownerDocument). Observe the unchanged application callback.
        const onload = this.onload;
        this.onload = (...args) => { try { return onload.apply(this, args); } catch (error) { errors.push(String(error)); } };
        this.addEventListener("load", () => reads.push({ result: this.result }));
        return originalReadAsText.call(this, file);
      };
      b.w.HTMLCanvasElement.prototype.getContext = function () {
        return { save() {}, restore() {}, clearRect() {}, drawImage() {}, beginPath() {}, closePath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {},
          bezierCurveTo() {}, createLinearGradient() { return { addColorStop() {} }; } };
      };
      b.w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 800 });
      b.w.HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,iVBORw0KGgo=";
      b.t.daten().einstellungen.allgemein.customTab.enabled = true;
      b.t.daten().customOrganizer.modules = [];
      await b.t.wechsel("custom");
      [...b.w.document.querySelectorAll("#kopf-links button")].find(button => button.textContent === "Customize").click();
      const designer = b.w.document.querySelector("#custom-designer-schleier");
      designer.querySelector(".custom-designer-werkzeuge select").value = "drawing";
      [...designer.querySelectorAll(".custom-designer-werkzeuge button")].find(button => button.textContent === "Add").click();
      designer.querySelector('[aria-label="Close"]').click();
      const drawing = b.t.daten().customOrganizer.modules[0];
      assert.equal(drawing.type, "drawing");
      const before = JSON.stringify(drawing), saves = b.saves().length;
      const input = b.w.document.querySelector('.custom-modul-drawing input[type="file"][accept^=".json,.svg"]');
      assert.ok(input);
      Object.defineProperty(input, "files", { configurable: true, value: [new b.w.File(['{"version":'], "broken-drawing.json", { type: "application/json" })] });
      input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
      for (let i = 0; i < 10; i++) await tick();
      const status = [...b.w.document.querySelectorAll('.custom-modul-drawing > .einst-hinweis')].map(node => node.textContent);
      assert.equal(errors.length, 1);
      assert.match(errors[0], /TypeError: _ is not a function/);
      assert.ok(!status.includes("This drawing cannot be edited in this version."));
      assert.equal(JSON.stringify(drawing), before);
      assert.equal(b.saves().length, saves);
      results.push({ web, scenario: "Real FileReader + malformed JSON selected in drawing Open control", errors, status, reads, drawingUnchanged: true, savesUnchanged: true });
    } finally { b.close(); }
  }
  console.log(JSON.stringify({ baseline: "1543858e251d7e29ebeafb67d2605991c1d442d5", nativeAcceptance: false, results }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
