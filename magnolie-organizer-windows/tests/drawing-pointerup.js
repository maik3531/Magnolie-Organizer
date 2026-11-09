"use strict";
// Refs #467: actual product attach()/DOM handlers and stroke model, no native
// renderer/pixel proof. Canvas drawing calls are deliberately stubbed.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const roots = [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]
  .filter(root => fs.existsSync(path.join(root, "zeichenblatt.js")));
const plain = value => JSON.parse(JSON.stringify(value));
const close = (actual, expected) => assert(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);

function fixture(web, viewport = false, points = null) {
  const dom = new JSDOM("<!doctype html><div><canvas tabindex='0'></canvas></div>", { runScripts: "outside-only" });
  const w = dom.window, canvas = w.document.querySelector("canvas");
  w.HTMLCanvasElement.prototype.getContext = () => ({ save() {}, restore() {}, clearRect() {}, drawImage() {}, setTransform() {},
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {}, fill() {}, bezierCurveTo() {}, setLineDash() {},
    createLinearGradient() { return { addColorStop() {} }; } });
  canvas.getBoundingClientRect = () => ({ left: 175, top: 25, width: 397, height: 118 });
  canvas.setPointerCapture = () => {};
  w.requestAnimationFrame = () => 0;
  w.eval(fs.readFileSync(path.join(web, "zeichenblatt.js"), "utf8"));
  const drawing = { version: 4, width: 794, height: 236, autoSize: false, strokes: points
    ? [{ tool: "pen", color: "#1d2433", width: 4, renderVersion: 4, points }] : [] };
  const view = viewport ? canvas.parentElement : null;
  if (view) {
    Object.defineProperty(view, "clientWidth", { value: 700 }); Object.defineProperty(view, "clientHeight", { value: 200 });
  }
  const failures = [], editor = w.MagnolieZeichnen.attach(canvas, drawing, () => {}, error => failures.push(error), view);
  function event(type, x, y = .5, extra = {}) {
    const e = new w.Event(type, { bubbles: true, cancelable: true });
    Object.assign(e, { pointerId: 7, pointerType: "mouse", button: 0, buttons: type === "pointerup" ? 0 : 1,
      clientX: 175 + x * 397, clientY: 25 + y * 118, pressure: 1 }, extra);
    canvas.dispatchEvent(e); return e;
  }
  return { w, drawing, editor, failures, canvas, event, close() { try { editor.destroy(); } finally { w.close(); } } };
}

function run(web) {
  let f = fixture(web);
  try {
    f.event("pointerdown", .2); f.event("pointermove", (360.9755859375 - 175) / 397);
    assert(f.event("pointerup", .75).defaultPrevented, "Owned release did not prevent the default event action");
    close(f.drawing.strokes[0].points.at(-1)[0], .75);
    assert.equal(f.editor.isInteracting(), false);
    const model = plain(f.drawing); f.event("pointerup", .9);
    assert.deepEqual(plain(f.drawing), model, "Repeated release changed a completed stroke");
    f.editor.undo(); assert.equal(f.drawing.strokes.length, 0); f.editor.redo(); assert.deepEqual(plain(f.drawing), model);
  } finally { f.close(); }
  for (const tool of ["pen", "quill", "brush", "highlighter", "eraser"]) {
    f = fixture(web);
    try {
      f.editor.setTool(tool); f.event("pointerdown", .2, .5, { pointerType: "pen", pressure: .7 });
      f.event("pointerup", .9, .5, { pointerId: 9 }); assert(f.editor.isInteracting());
      f.event("pointerup", .75, .5, { pointerType: "pen", pressure: 0, getCoalescedEvents: () => [
        { pointerId: 9, pointerType: "pen", clientX: 175 + .9 * 397, clientY: 84, pressure: .5 },
        { pointerId: 7, pointerType: "pen", clientX: 175 + .4 * 397, clientY: 84, pressure: .4 }
      ] });
      const stroke = f.drawing.strokes[0]; assert.equal(stroke.tool, tool);
      assert.equal(stroke.points.length, 3, "Own coalesced sample/current release missing or foreign sample included");
      close(stroke.points[1][0], .4); close(stroke.points.at(-1)[0], .75); assert.equal(stroke.points.at(-1)[2], 0);
      const model = plain(f.drawing); f.editor.undo(); f.editor.redo(); assert.deepEqual(plain(f.drawing), model);
    } finally { f.close(); }
  }
  for (const tool of ["rectangle", "ellipse", "triangle", "line"]) {
    f = fixture(web);
    try {
      f.editor.setTool(tool); f.event("pointerdown", .2); f.event("pointermove", .4); f.event("pointerup", .75);
      assert.equal(f.drawing.strokes[0].points.length, 2); close(f.drawing.strokes[0].points[1][0], .75);
    } finally { f.close(); }
  }
  f = fixture(web);
  try {
    f.event("pointerdown", .2, .5, { pointerType: "pen", button: 5, pressure: .7 });
    f.event("pointerup", .75, .5, { pointerType: "pen", pressure: 0, getCoalescedEvents: () => [
      { pointerId: 7, pointerType: "pen", clientX: 175 + .75 * 397, clientY: 84, pressure: 0 }
    ] });
    assert.equal(f.drawing.strokes[0].tool, "eraser"); assert.equal(f.drawing.strokes[0].points.length, 2,
      "Current release already present in coalesced samples was appended twice");
    close(f.drawing.strokes[0].points.at(-1)[0], .75); assert.equal(f.drawing.strokes[0].points.at(-1)[2], 0);
  } finally { f.close(); }
  for (const terminal of ["pointercancel", "lostpointercapture", "blur", "zero-buttons-motion"]) {
    f = fixture(web);
    try {
      f.event("pointerdown", .2); f.event("pointermove", .4);
      if (terminal === "blur") f.w.dispatchEvent(new f.w.Event("blur"));
      else f.event(terminal === "zero-buttons-motion" ? "pointermove" : terminal, .75, .5, { buttons: 0 });
      f.event("pointerup", .9);
      close(f.drawing.strokes[0].points.at(-1)[0], .4); assert.equal(f.editor.isInteracting(), false);
    } finally { f.close(); }
  }
  f = fixture(web);
  try {
    f.event("pointerdown", .2); f.event("pointerup", .2);
    assert.equal(f.drawing.strokes.length, 1); assert.equal(f.drawing.strokes[0].points.length, 1, "Mouse tap gained a duplicate endpoint");
    f.editor.begin(.3, .3, 1); f.editor.move(.4, .4, 1); f.editor.finish();
    f.editor.setTool("select"); f.event("pointerdown", .25, .25); f.event("pointerup", .6, .6); assert(f.editor.hasSelection());
    f.editor.setTool("move"); f.event("pointerdown", .3, .3); f.event("pointerup", .4, .4);
    close(f.drawing.strokes[1].points[0][0], .4); close(f.drawing.strokes[1].points[1][0], .5);
    f.editor.undo(); close(f.drawing.strokes[1].points[0][0], .3); f.editor.redo(); close(f.drawing.strokes[1].points[0][0], .4);
  } finally { f.close(); }
  f = fixture(web, true);
  try {
    f.editor.setTool("pan"); f.event("pointerdown", .3); f.event("pointermove", .32); f.event("pointerup", .35);
    close(Number(f.canvas.style.transform.match(/\+ ([\d.e-]+)px/)[1]), 39.7); assert.equal(f.drawing.strokes.length, 0);
  } finally { f.close(); }
  f = fixture(web, false, Array(199998).fill([.1, .1, 1]));
  try {
    f.event("pointerdown", .2); f.event("pointerup", .75, .5, { getCoalescedEvents: () => [
      { pointerId: 7, pointerType: "mouse", clientX: 175 + .4 * 397, clientY: 84, pressure: 1 }
    ] });
    assert.equal(f.drawing.strokes.reduce((sum, stroke) => sum + stroke.points.length, 0), f.w.MagnolieZeichnen.MAX_POINTS);
    assert.deepEqual(f.failures, ["drawing_limit"]); assert.equal(f.editor.isInteracting(), false);
  } finally { f.close(); }
}
let failed = false;
for (const web of roots) {
  try { run(web); console.log("DRAWING POINTERUP PASS " + web); }
  catch (error) { failed = true; console.error("DRAWING POINTERUP FAIL " + web + ": " + error.stack); }
}
if (failed) process.exitCode = 1;
