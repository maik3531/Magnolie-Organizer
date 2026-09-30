"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../web/zeichenblatt.js"), "utf8"), sandbox);
const drawing = sandbox.window.MagnolieZeichnen;
const plain = value => JSON.parse(JSON.stringify(value));
const sheet = drawing.create();
const widths = [], handlers = new Map();
const context = { save() {}, restore() {}, clearRect() {}, beginPath() {}, arc() {}, fill() {}, moveTo() {}, lineTo() {},
  stroke() { widths.push(this.lineWidth); } };
const canvas = { width: 0, height: 0, style: {}, getContext: () => context,
  addEventListener: (name, handler) => handlers.set(name, handler),
  removeEventListener: name => handlers.delete(name),
  getBoundingClientRect: () => ({ left: 10, top: 20, width: 600, height: 400 }),
  focus() {}, setPointerCapture() {}, toDataURL: type => type };
let changes = 0;
const editor = drawing.attach(canvas, sheet, () => changes++);
assert.equal(drawing.valid(sheet), true);
editor.begin(0.1, 0.2, 0.25); editor.move(0.2, 0.3, 0.5); editor.finish();
assert.equal(sheet.strokes.length, 1);
assert.equal(widths.at(-1), 1.5, "Stiftdruck beeinflusst die Strichbreite");
const before = plain(sheet);
editor.setTool("eraser"); editor.begin(0.2, 0.3, 1, "eraser"); editor.move(0.3, 0.4, 1); editor.finish();
assert.equal(sheet.strokes[1].tool, "eraser");
editor.undo(); assert.deepEqual(plain(sheet), before);
editor.redo(); assert.equal(sheet.strokes.length, 2);
editor.clear(); assert.equal(sheet.strokes.length, 0);
editor.undo(); assert.equal(sheet.strokes.length, 2);
editor.redo(); assert.equal(sheet.strokes.length, 0);
editor.undo();
const reloaded = JSON.parse(JSON.stringify(sheet));
assert.equal(drawing.valid(reloaded), true, "Speicherung erhält editierbare Zeichenstriche");
drawing.render(canvas, reloaded);
editor.setTool("pen");
const event = (x, y, pressure = 0.5) => ({ button: 0, pointerId: 42, pointerType: "pen", clientX: x, clientY: y, pressure, preventDefault() {} });
handlers.get("pointerdown")(event(70, 100));
handlers.get("pointermove")(event(130, 140));
const localLength = sheet.strokes.length;
editor.remote({ active: true, touching: true, tool: "Rubber", x: 0.5, y: 0.5, pressure: 1 });
assert.equal(sheet.strokes.length, localLength, "Remote-Eingabe mischt sich nicht in einen lokalen Zeigerstrich");
handlers.get("pointerup")(event(130, 140, 0));
editor.remote({ active: true, touching: true, tool: "Rubber", x: 0.5, y: 0.5, pressure: 1 });
assert.equal(sheet.strokes.at(-1).tool, "eraser");
editor.remote({ active: false, touching: false });
assert.ok(changes > 0);
assert.equal(editor.exportPng(), "image/png");
const unchanged = JSON.stringify(sheet);
editor.destroy();
assert.equal(handlers.size, 0);
editor.remote({ active: true, touching: true, x: 0.5, y: 0.5, pressure: 1 });
assert.equal(JSON.stringify(sheet), unchanged);
for (const invalid of [{ ...before, version: 2 }, { ...before, width: 1000000 },
  { ...before, strokes: [{ ...before.strokes[0], points: [[Infinity, 0, 1]] }] },
  { ...before, strokes: [{ ...before.strokes[0], points: new Array(drawing.MAX_POINTS + 1).fill([0, 0, 1]) }] }]) {
  assert.equal(drawing.valid(invalid), false);
  assert.throws(() => drawing.render(canvas, invalid), /invalid_drawing/);
}
console.log("Zeichenmodell: Druck, Radieren, Rückgängig/Wiederholen, Persistenz, Zeigertrennung und Grenzen bestanden.");
