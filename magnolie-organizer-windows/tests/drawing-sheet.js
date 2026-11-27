"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
   'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "drawingRedraw: zeichneAlles, embedDrawing: fuegeZeichenblattInNotiz, drawingController: id => aktiveZeichenblaetter.get(id)?.editor, drawingTrash: sichereCustomPapierkorb, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const plain = value => JSON.parse(JSON.stringify(value));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function openDrawing(b) {
  const { w, t } = b;
  w.HTMLCanvasElement.prototype.getContext = function () {
    return { save() {}, restore() {}, clearRect() {}, drawImage() {}, beginPath() {}, closePath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {}, stroke() {},
      bezierCurveTo() {}, createLinearGradient() { return { addColorStop() {} }; } };
  };
  w.HTMLCanvasElement.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 800 });
  w.HTMLCanvasElement.prototype.toDataURL = () => "data:image/png;base64,iVBORw0KGgo=";
  t.daten().einstellungen.allgemein.customTab.enabled = true;
  t.daten().customOrganizer.modules = [];
  await t.wechsel("custom");
  const text = w.MagnolieI18n.gettext;
  [...w.document.querySelectorAll("#kopf-links button")].find(button => button.textContent === text("Customize")).click();
  const designer = w.document.querySelector("#custom-designer-schleier");
  designer.querySelector(".custom-designer-werkzeuge select").value = "drawing";
  [...designer.querySelectorAll(".custom-designer-werkzeuge button")].find(button => button.textContent === text("Add")).click();
  designer.querySelector(`[aria-label="${text("Close")}"]`).click();
  return t.daten().customOrganizer.modules[0];
}

async function drawingErrors(web, language, expected) {
  const b = await harness.exports.boot(web, {}, false);
  const { w, t } = b;
  const jsErrors = [];
  const onError = error => jsErrors.push(String(error));
  process.on("unhandledRejection", onError);
  w.addEventListener("error", event => { onError(event.error); event.preventDefault(); });
  try {
    if (language !== "en") w.eval(fs.readFileSync(path.join(web, "i18n", `${language}.js`), "utf8"));
    w.App.init({ daten: {}, neu: false, regional: { language, timeZone: "UTC" } });
    const module = await openDrawing(b);
    const text = w.MagnolieI18n.gettext;
    const sheet = w.document.querySelector(".custom-modul-drawing");
    const status = sheet.querySelector(".einst-hinweis");
    const button = (root, label) => [...root.querySelectorAll("button")].find(element =>
      element.getAttribute("aria-label") === text(label) || element.textContent === text(label));

    const FileReader = w.FileReader;
    let readDone;
    w.FileReader = class extends FileReader {
      constructor() {
        super();
        readDone = new Promise(resolve => this.addEventListener("loadend", resolve, { once: true }));
      }
      set onload(callback) {
        super.onload = event => {
          try { callback(event); } catch (error) { onError(error); }
        };
      }
    };
    const input = sheet.querySelector('input[type="file"]');
    async function open(contents, filename) {
      button(sheet, "Open").click();
      Object.defineProperty(input, "files", { configurable: true, value: [new w.File([contents], filename)] });
      input.dispatchEvent(new w.Event("change", { bubbles: true }));
      assert.ok(readDone, "Open must use the real FileReader");
      await readDone;
      readDone = null;
    }

    const before = plain(module.drawing);
    const saves = b.saves().length;
    await open('{"version":', "broken-drawing.json");
    const importMessage = status.textContent;
    assert.deepEqual(plain(module.drawing), before);
    assert.equal(b.saves().length, saves);
    const valid = { ...before, width: 1234, autoSize: false };
    await open(JSON.stringify(valid), "loaded-drawing.json");
    assert.deepEqual(plain(module.drawing), valid, "A valid retry must replace the sheet");
    assert.equal(status.textContent, "loaded-drawing.json", "A valid retry must replace the earlier error status");

    // A PNG header can pass sheet validation even if the browser cannot decode it.
    w.Image = class extends w.EventTarget {
      get complete() { return true; }
      get naturalWidth() { return 0; }
    };
    module.drawing.background = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC";
    assert.ok(w.MagnolieZeichnen.valid(module.drawing));
    const withBackground = plain(module.drawing);

    status.textContent = "";
    button(sheet, "Save as…").click();
    await tick();
    const exportMessage = status.textContent;
    assert.ok(!b.messages.some(message => message.cmd === "zeichenblatt_exportieren"));

    button(sheet, "Rotate selection").click();
    const rotation = w.document.querySelector(".eingabe-dialog");
    button(rotation, "Apply").click();
    await tick();
    const rotationMessage = rotation.querySelector(".einst-warnung").textContent;
    button(rotation, "Cancel").click();

    const note = { id: "drawing-errors-note", titel: "Drawing errors", anhaenge: [] };
    t.daten().notizen.push(note);
    t.embedDrawing(note);
    const embed = w.document.querySelector(".eingabe-dialog");
    button(embed, "Embed").click();
    await tick();
    assert.equal(note.anhaenge.length, 0);
    assert.deepEqual(plain(module.drawing), withBackground);
    assert.equal(b.saves().length, saves);
    assert.deepEqual({
      messages: [importMessage, exportMessage, rotationMessage, embed.querySelector(":scope > .einst-warnung").textContent],
      jsErrors,
    }, { messages: expected, jsErrors: [] });
  } finally {
    process.off("unhandledRejection", onError);
    b.close();
  }
}

(async () => {
  const failures = [];
  for (const web of harness.exports.roots) {
    for (const [language, messages] of [
      ["en", ["This drawing cannot be edited in this version.", "This image format cannot be used.", "The file could not be read."]],
      ["de", ["Dieses Zeichenblatt kann mit dieser Version nicht bearbeitet werden.", "Dieses Bildformat lässt sich nicht verwenden.", "Die Datei ließ sich nicht lesen."]],
    ]) {
      try {
        await drawingErrors(web, language, [...messages, messages[1]]);
        console.log("Zeichenblatt-Fehlerpfade bestanden:", web, language);
      } catch (error) {
        failures.push(error);
        console.error("Zeichenblatt-Fehlerpfade fehlgeschlagen:", web, language, error);
      }
    }
  }
  assert.equal(failures.length, 0, "Drawing error paths must report their messages on both frontends");
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web);
    try {
      const module = await openDrawing(b);
      assert.equal(module.type, "drawing");
      assert.equal(module.reminders, false);
       const editor = b.t.drawingController(module.id);
       assert.ok(editor && b.w.document.querySelector("canvas.custom-zeichenblatt"));
       const toolbar = b.w.document.querySelector('.zeichen-werkzeuge');
       assert.deepEqual([...toolbar.querySelectorAll('.zeichen-dokument > button')].map(button => button.getAttribute('aria-label')),
         ['New drawing sheet', 'Open', 'Sheet size', 'Save as…', 'Close', 'Clear', 'Undo', 'Redo', 'Paste', 'Zoom in', 'Zoom out']);
       const width = toolbar.querySelector('.zeichen-einstellungen input[type="range"]');
       assert.ok(width && width.isConnected, 'Line width must be directly selectable below the sheet choice');
       width.value = '20'; width.dispatchEvent(new b.w.Event('input'));
        b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
        const session = "d".repeat(48); let invocationSequence = 0;
        const mcp = async message => {
          const invocation = (++invocationSequence).toString(16).padStart(48, "0");
          await b.w.App.mcpRequest({ session, invocation, message });
          return b.messages.find(value => value.cmd === "mcp_antwort" && value.invocation === invocation).response;
        };
        await mcp({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "owned-drawing-fixture", version: "1" } } });
        await mcp({ jsonrpc: "2.0", method: "notifications/initialized" });
        assert.equal(editor.isInteracting(), false);
        editor.begin(0.1, 0.2, 0.3); editor.move(0.5, 0.6, 0.9);
        assert.equal(editor.isInteracting(), true);
        const drawingBusy = await mcp({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "organizer_note_create", arguments: { title: "Owned blocked drawing write", text: "Owned fixture" } } });
        assert.equal(drawingBusy.result.structuredContent.code, "drawing_busy");
        editor.finish(); assert.equal(editor.isInteracting(), false);
       assert.equal(module.drawing.strokes.length, 1);
       assert.equal(module.drawing.strokes[0].width, 20, 'Visible line width must reach the actual drawing controller');
      const saved = plain(b.t.normalisiere(b.t.daten()));
      assert.deepEqual(saved.customOrganizer.modules[0].drawing, plain(module.drawing));
        b.w.document.querySelector('.custom-modul-drawing button[aria-label="Save as…"]').click();
        await new Promise(resolve => setImmediate(resolve));
       assert.ok(b.messages.some(message => message.cmd === "zeichenblatt_exportieren" && message.png.startsWith("data:image/png") && message.svg.startsWith("<svg")));
       assert.equal(b.w.document.querySelector('.custom-modul-drawing button[aria-label="Print"]'), null);
      assert.match(b.t.druckStoff("custom").html(module), /<img[^>]+data:image\/png/,
        "Printed custom sheets must include the drawing, not only its title");
      b.w.App.telefonStand({ peers: [], kdeconnect: { digitizer_available: true, digitizer_device_id: "tablet" } });
      let tablet = b.w.document.querySelector('[data-kde-zeichen-input]');
      assert.equal(tablet.disabled, false);
      assert.equal(tablet.checked, true, "Available tablet must bind automatically without a separate activation");
      const arm = b.messages.findLast(message => message.cmd === "kde_zeichnen" && message.enabled);
      assert.ok(arm && arm.device_id === "tablet");
      const oldTablet = tablet;
      b.t.drawingRedraw();
      tablet = b.w.document.querySelector('[data-kde-zeichen-input]');
      assert.notEqual(tablet, oldTablet, "Redraw must recreate the real controls for this regression");
      assert.equal(tablet.checked, true, "A status redraw must not turn off drawing input");
      assert.equal(b.messages.filter(message => message.cmd === "kde_zeichnen" && !message.enabled && message.token === arm.token).length, 0);
      const points = [{ active: true, touching: true, tool: "Pen", x: 0.3, y: 0.4, pressure: 0.5 },
        { active: true, touching: false, tool: "Pen", x: 0.3, y: 0.4, pressure: 0 }];
      b.w.App.zeichenEingabe({ token: "old-target", device_id: "tablet", events: points });
       assert.equal(module.drawing.strokes.length, 1, "Late input cannot cross target tokens");
       const viewport = b.w.document.querySelector("canvas.custom-zeichenblatt").parentElement;
       Object.defineProperty(viewport, "clientWidth", { configurable: true, value: 1200 });
       Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 800 });
       const hover = viewport.querySelector(".zeichen-stiftzeiger");
       const beforeHover = JSON.stringify(module.drawing);
       b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: [{ active: true, touching: false, tool: "Pen", x: .3, y: .4, pressure: 0 }] });
       assert.equal(hover.hidden, false, "KDE pen proximity must visibly position the pen without making ink");
       assert.equal(hover.style.left, "360px"); assert.equal(hover.style.top, "320px");
       assert.equal(JSON.stringify(module.drawing), beforeHover, "Hover must not change persisted drawing data");
       b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: [{ active: true, touching: false, tool: "Rubber", x: .3, y: .4, pressure: 0 }] });
       assert.equal(hover.dataset.tool, "Rubber");
       b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: [{ active: false, touching: false }] });
       assert.equal(hover.hidden, true);
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
       assert.ok(dialog && dialog.querySelector("canvas"));
       dialog.querySelector("canvas").focus();
       await new Promise(resolve => setImmediate(resolve));
       dialog.getClientRects = () => [{ width: 900, height: 700 }];
       const noteTarget = b.messages.findLast(message => message.cmd === "kde_zeichnen" && message.enabled);
       assert.ok(noteTarget && noteTarget.token !== arm.token, "Opening the note sheet must establish its own tablet target");
       const beforeNoteInput = module.drawing.strokes.length;
       b.w.App.zeichenEingabe({ token: arm.token, device_id: "tablet", events: points });
       assert.equal(module.drawing.strokes.length, beforeNoteInput, "The old custom-tab target must not receive note-sheet input");
       const otherDialog = b.w.document.createElement("section"); otherDialog.setAttribute("aria-modal", "true");
       otherDialog.getClientRects = () => [{ width: 300, height: 200 }]; b.w.document.body.append(otherDialog);
       b.w.App.zeichenEingabe({ token: noteTarget.token, device_id: "tablet", events: points });
       assert.equal(module.drawing.strokes.length, beforeNoteInput, "A different visible dialog must still block tablet drawing");
       otherDialog.remove();
       b.w.App.zeichenEingabe({ token: noteTarget.token, device_id: "tablet", events: points });
       assert.equal(module.drawing.strokes.length, beforeNoteInput + 1, "KDE tablet input must reach the sheet inside its own visible note dialog");
      [...dialog.querySelectorAll("button")].find(button => button.textContent === "Embed").click();
      await new Promise(resolve => setImmediate(resolve));
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
