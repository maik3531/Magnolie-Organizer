"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "embedDrawing: fuegeZeichenblattInNotiz, drawingController: id => aktiveZeichenblaetter.get(id)?.editor, drawingTrash: sichereCustomPapierkorb, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
    try {
      b.w.HTMLCanvasElement.prototype.getContext = function () {
        return { save() {}, restore() {}, clearRect() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {} };
      };
      b.w.HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,iVBORw0KGgo=";
      b.t.daten().einstellungen.allgemein.customTab.enabled = true;
      b.t.daten().customOrganizer.modules = [];
      await b.t.wechsel("custom");
      [...b.w.document.querySelectorAll("#kopf-links button")].find(button => button.textContent === "Customize").click();
      const designer = b.w.document.querySelector("#custom-designer-schleier");
      designer.querySelector(".custom-designer-werkzeuge select").value = "drawing";
      [...designer.querySelectorAll(".custom-designer-werkzeuge button")].find(button => button.textContent === "Add").click();
      designer.querySelector('[aria-label="Close"]').click();
      const module = b.t.daten().customOrganizer.modules[0];
      assert.equal(module.type, "drawing");
      assert.equal(module.reminders, false);
      const editor = b.t.drawingController(module.id);
      assert.ok(editor && b.w.document.querySelector("canvas.custom-zeichenblatt"));
      editor.begin(0.1, 0.2, 0.3); editor.move(0.5, 0.6, 0.9); editor.finish();
      assert.equal(module.drawing.strokes.length, 1);
      const saved = plain(b.t.normalisiere(b.t.daten()));
      assert.deepEqual(saved.customOrganizer.modules[0].drawing, plain(module.drawing));
      [...b.w.document.querySelectorAll(".custom-modul-drawing button")].find(button => button.textContent === "Export PNG").click();
      assert.ok(b.messages.some(message => message.cmd === "notiz_anhang_datei" && Number.isInteger(message.id) && message.id > 0 &&
        message.aktion === (web.includes("windows") ? "speichern" : "save") && message.daten.startsWith("data:image/png")));
      assert.match(b.t.druckStoff("custom").html(module), /<img[^>]+data:image\/png/,
        "Printed custom sheets must include the drawing, not only its title");
      b.w.App.telefonStand({ peers: [], kdeconnect: { digitizer_available: true, digitizer_device_id: "tablet" } });
      const tablet = b.w.document.querySelector('[data-kde-zeichen-input]');
      assert.equal(tablet.disabled, false);
      tablet.checked = true; tablet.dispatchEvent(new b.w.Event("change"));
      const arm = b.messages.findLast(message => message.cmd === "kde_zeichnen" && message.enabled);
      assert.ok(arm && arm.device_id === "tablet");
      const points = [{ active: true, touching: true, tool: "Pen", x: 0.3, y: 0.4, pressure: 0.5 },
        { active: true, touching: false, tool: "Pen", x: 0.3, y: 0.4, pressure: 0 }];
      b.w.App.zeichenEingabe({ token: "old-target", device_id: "tablet", events: points });
      assert.equal(module.drawing.strokes.length, 1, "Late input cannot cross target tokens");
      b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: points });
      assert.equal(module.drawing.strokes.length, 2);
      b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: [], stopped: true });
      assert.equal(tablet.checked, false);
      assert.ok(b.messages.some(message => message.cmd === "kde_zeichnen" && !message.enabled && message.token === arm.token));
      const note = { id: "drawing-note", titel: "Drawing note", text: "", html: "", anhaenge: [] };
      b.t.daten().notizen.push(note);
      b.t.embedDrawing(note);
      const dialog = [...b.w.document.querySelectorAll(".eingabe-dialog")].find(element =>
        [...element.querySelectorAll("button")].some(button => button.textContent === "Embed"));
      assert.ok(dialog && dialog.querySelector("img"));
      [...dialog.querySelectorAll("button")].find(button => button.textContent === "Embed").click();
      assert.equal(note.anhaenge.length, 1);
      assert.equal(note.anhaenge[0].art, "image");
      assert.match(note.anhaenge[0].daten, /^data:image\/png;base64,/);
      const second = { ...plain(module), id: "second-drawing" };
      assert.equal(b.t.normalisiere({ customOrganizer: { modules: [plain(module), second] } }).customOrganizer.modules.length, 2,
        "Separate sheets must not be merged by module type");
      const unsupported = { ...plain(module), drawing: { version: 99, future: "preserve" } };
      assert.deepEqual(plain(b.t.normalisiere({ customOrganizer: { modules: [unsupported] } }).customOrganizer.modules[0].drawing), unsupported.drawing);
      b.t.drawingTrash(module);
      const deleted = b.t.daten().papierkorb.at(-1);
      assert.equal(b.t.ausDemPapierkorb(deleted), true);
      const restored = b.t.daten().customOrganizer.modules;
      assert.equal(restored.length, 2, "Restore must preserve a drawing whose module ID is already present");
      assert.notEqual(restored[0].id, restored[1].id);
      assert.deepEqual(plain(restored[0].drawing), plain(restored[1].drawing));
      const previousCount = module.drawing.strokes.length;
      await b.t.wechsel("kalender");
      editor.remote({ active: true, touching: true, x: 0.5, y: 0.5, pressure: 1 });
      assert.equal(module.drawing.strokes.length, previousCount, "Leaving the sheet disables its old input target");
      console.log("Zeichenblatt-Integration bestanden:", web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
