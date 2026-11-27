"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.resolve(process.argv[2], "magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(path.dirname(file));
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const sheet = () => ({ version: 4, width: 900, height: 600, autoSize: false,
  strokes: [{ tool: "pen", color: "#123456", width: 4, points: [[.1, .2, 1], [.8, .7, 1]] }] });
// A plausible PNG header with no image data: structural validation accepts it,
// while a browser decoder cannot load it. The native decoding boundary below
// reports complete + zero naturalWidth; the actual ready() implementation runs.
const pngHeader = Buffer.alloc(24); pngHeader.set([137, 80, 78, 71, 13, 10, 26, 10]);
pngHeader.writeUInt32BE(1, 16); pngHeader.writeUInt32BE(1, 20);
const unreadablePng = "data:image/png;base64," + pngHeader.toString("base64");
const renderedPng = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lN8AAAAASUVORK5CYII=";

async function setup(web, language) {
  const b = await harness.exports.boot(web, {
    einstellungen: { allgemein: { customTab: { enabled: true } } },
    customOrganizer: { modules: [{ id: "owned-drawing-errors", type: "drawing", title: "Owned drawing", page: "right", order: 0, items: [], drawing: sheet() }] },
    notizen: [{ id: "owned-drawing-note", titel: "Owned note", text: "Keep this text", html: "<p>Keep this text</p>", anhaenge: [] }]
  });
  if (language === "de") b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8"));
  assert.equal(b.w.MagnolieI18n.setLocale(language), language);
  const errors = [], reads = [], rejected = error => errors.push(String(error));
  process.on("unhandledRejection", rejected);
  b.w.addEventListener("error", event => { errors.push(String(event.error)); event.preventDefault(); });
  const readAsText = b.w.FileReader.prototype.readAsText;
  b.w.FileReader.prototype.readAsText = function (value) {
    // jsdom discards exceptions from FileReader listeners without an ownerDocument.
    // Observe the real application callback while retaining real FileReader I/O.
    const onload = this.onload;
    this.onload = (...args) => { try { return onload.apply(this, args); } catch (error) { errors.push(String(error)); } };
    reads.push(new Promise(resolve => this.addEventListener("loadend", resolve, { once: true })));
    return readAsText.call(this, value);
  };
  b.w.HTMLCanvasElement.prototype.getContext = () => ({ save() {}, restore() {}, clearRect() {}, drawImage() {}, beginPath() {}, closePath() {},
    arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {}, bezierCurveTo() {}, setTransform() {}, translate() {}, rotate() {},
    createLinearGradient() { return { addColorStop() {} }; } });
  b.w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 800 });
  b.w.HTMLCanvasElement.prototype.toDataURL = () => renderedPng;
  b.w.Image = class extends b.w.EventTarget {
    complete = true;
    naturalWidth = 0;
    set src(value) { assert.equal(value, unreadablePng, "Only the owned failed decode is simulated"); }
  };
  const d = b.w.document, tr = text => b.w.MagnolieI18n.gettext(text);
  const button = (scope, text) => {
    const value = [...scope.querySelectorAll("button")].find(node => node.textContent === tr(text) || node.getAttribute("aria-label") === tr(text));
    assert.ok(value, text); return value;
  };
  const load = async (value, scope = d) => {
    const input = scope.querySelector('input[type="file"][accept^=".json,.svg"]'); assert.ok(input);
    Object.defineProperty(input, "files", { configurable: true, value: [new b.w.File([typeof value === "string" ? value : JSON.stringify(value)], "owned-drawing.json", { type: "application/json" })] });
    input.dispatchEvent(new b.w.Event("change", { bubbles: true }));
    await reads.at(-1); await tick();
    assert.equal(input.value, "", "A failed selection must be selectable again");
  };
  const snapshot = () => ({ data: JSON.stringify(b.t.daten()), saves: b.saves().length,
    saveTimers: b.timers.filter(timer => timer.delay === 400).length,
    exports: b.messages.filter(message => message.cmd === "zeichenblatt_exportieren").length });
  const unchanged = before => {
    assert.deepEqual(snapshot(), before, "A failed action must not change data, schedule a save or export");
    assert.deepEqual(errors, [], "The error path must not throw a translation TypeError");
  };
  await b.t.wechsel("custom");
  const module = b.t.daten().customOrganizer.modules.find(value => value.id === "owned-drawing-errors");
  assert.ok(module && d.querySelector("canvas.custom-zeichenblatt"));
  return { ...b, d, tr, button, load, snapshot, unchanged, errors, module,
    status: () => d.querySelector(".custom-modul-drawing > .einst-hinweis"),
    close() { process.removeListener("unhandledRejection", rejected); b.close(); } };
}


// The optional candidate is applied only to the source string read by the test.
// No product file is modified. All other source reads remain exact main244.
const mode = process.argv[3] || "before";
const base = path.resolve(process.argv[2]);
const sourceFiles = ["magnolie-organizer/web/anwendung.js", "magnolie-organizer-windows/app/web/anwendung.js"].map(name => path.join(base, name));
const sha = value => require("node:crypto").createHash("sha256").update(value).digest("hex");
const hashes = Object.fromEntries(sourceFiles.map(name => [path.relative(base, name), sha(fs.readFileSync(name))]));
const originalRead = fs.readFileSync;
const old = 'if (canvas.isConnected && !gesperrt) canvas.focus(); }\n        catch { status.textContent = _("This drawing cannot be edited in this version."); } }; reader.readAsText(file); }';
const replacement = 'if (canvas.isConnected && !gesperrt) { status.textContent = file.name; canvas.focus(); } }\n        catch { status.textContent = _("This drawing cannot be edited in this version."); } }; reader.readAsText(file); }';
let patchedReads = 0;
if (mode === "after") fs.readFileSync = function(name, ...args) {
  const value = originalRead.call(this, name, ...args);
  if (!sourceFiles.includes(String(name))) return value;
  assert.equal(typeof value, "string");
  assert.equal(value.split(old).length, 2, "Exactly the reviewed retry-success source change is applied");
  patchedReads++;
  return value.replace(old, replacement);
};
(async () => {
  const cases = [];
  for (const web of harness.exports.roots) for (const language of ["en", "de"]) {
    const b = await setup(web, language);
    try {
      const before = b.snapshot();
      await b.load('{"version":');
      b.unchanged(before);
      const afterFailure = b.status().textContent;
      assert.equal(afterFailure, b.tr("This drawing cannot be edited in this version."));
      const drawing = { ...sheet(), width: 1000 };
      await b.load(drawing);
      const drawingReplaced = JSON.stringify(b.module.drawing) === JSON.stringify(drawing);
      assert.equal(drawingReplaced, true);
      assert.deepEqual(b.errors, []);
      cases.push({frontend: path.relative(base, web), language, afterFailure,
        afterSuccessfulImport: b.status().textContent, drawingReplaced,
        statusRecovered: b.status().textContent === "owned-drawing.json", errors: b.errors});
    } finally { b.close(); }
  }
  fs.readFileSync = originalRead;
  assert.equal(patchedReads, mode === "after" ? 4 : 0);
  console.log(JSON.stringify({sourceCommit:"244b1d62aa738ea5cd8fa7fc9449ccf62fb7b99d", mode,
    method: "Real application controls and FileReader I/O under JSDOM; canvas/native boundary simulated; candidate changes source in memory only", hashes, cases}, null, 2));
  assert.equal(cases.every(item => item.statusRecovered), true,
    "Successful JSON retry must replace the old localized error with the loaded filename");
})().catch(error => { console.error(error); process.exitCode = 1; });
