"use strict";
(() => {
  const MAX_POINTS = 200000, MAX_STROKES = 2000;
  const finite = (value, min, max) => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
  const create = () => ({ version: 1, width: 1200, height: 800, strokes: [] });
  function valid(sheet) {
    if (!sheet || sheet.version !== 1 || !Number.isInteger(sheet.width) || !Number.isInteger(sheet.height) ||
        !finite(sheet.width, 1, 4096) || !finite(sheet.height, 1, 4096) || !Array.isArray(sheet.strokes) ||
        sheet.strokes.length > MAX_STROKES) return false;
    let points = 0;
    for (const stroke of sheet.strokes) {
      if (!stroke || !["pen", "eraser"].includes(stroke.tool) || !/^#[0-9a-f]{6}$/i.test(stroke.color || "") ||
          !finite(stroke.width, 0.5, 80) || !Array.isArray(stroke.points) || !stroke.points.length) return false;
      points += stroke.points.length;
      if (points > MAX_POINTS || stroke.points.some(point => !Array.isArray(point) || point.length !== 3 ||
          !finite(point[0], 0, 1) || !finite(point[1], 0, 1) || !finite(point[2], 0, 1))) return false;
    }
    return true;
  }
  function segment(context, sheet, stroke, before, after) {
    context.save();
    context.globalCompositeOperation = stroke.tool === "eraser" ? "destination-out" : "source-over";
    context.strokeStyle = context.fillStyle = stroke.color;
    context.lineCap = context.lineJoin = "round";
    const pressure = stroke.tool === "eraser" ? 1 : Math.max(0.08, (before[2] + after[2]) / 2);
    context.lineWidth = stroke.width * pressure;
    context.beginPath();
    if (before === after) {
      context.arc(after[0] * sheet.width, after[1] * sheet.height, context.lineWidth / 2, 0, 2 * Math.PI);
      context.fill();
    } else {
      context.moveTo(before[0] * sheet.width, before[1] * sheet.height);
      context.lineTo(after[0] * sheet.width, after[1] * sheet.height); context.stroke();
    }
    context.restore();
  }
  function render(canvas, sheet) {
    if (!valid(sheet)) throw new Error("invalid_drawing");
    canvas.width = sheet.width; canvas.height = sheet.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("drawing_unavailable");
    context.clearRect(0, 0, canvas.width, canvas.height);
    for (const stroke of sheet.strokes) {
      segment(context, sheet, stroke, stroke.points[0], stroke.points[0]);
      for (let index = 1; index < stroke.points.length; index++)
        segment(context, sheet, stroke, stroke.points[index - 1], stroke.points[index]);
    }
    return context;
  }
  function attach(canvas, sheet, changed, failed = () => {}) {
    const context = render(canvas, sheet), undo = sheet.strokes.map(stroke => ({ type: "stroke", stroke })), redo = [];
    let active = null, pointer = null, disposed = false, tool = "pen", color = "#1d2433", width = 4;
    let count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
    const prune = () => {
      const weight = action => action.type === "clear" ? action.strokes.reduce((total, stroke) => total + stroke.points.length, 0) : action.stroke.points.length;
      let retained = undo.reduce((total, action) => total + weight(action), 0);
      while (undo.length > 100 || undo.length > 1 && retained > 2 * MAX_POINTS) retained -= weight(undo.shift());
    };
    prune();
    const notify = () => { if (!disposed) changed(); };
    const finish = () => { active = null; pointer = null; };
    const point = (x, y, pressure) => [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y)), Math.max(0, Math.min(1, pressure))];
    function begin(x, y, pressure, selectedTool = tool) {
      if (disposed || ![x, y, pressure].every(Number.isFinite)) return false;
      if (sheet.strokes.length >= MAX_STROKES || count >= MAX_POINTS) { failed("drawing_limit"); return false; }
      finish(); redo.length = 0;
      active = { tool: selectedTool === "eraser" ? "eraser" : "pen", color, width: selectedTool === "eraser" ? Math.max(16, width) : width,
        points: [point(x, y, pressure)] };
      sheet.strokes.push(active); undo.push({ type: "stroke", stroke: active }); count++; prune();
      segment(context, sheet, active, active.points[0], active.points[0]); notify(); return true;
    }
    function move(x, y, pressure) {
      if (!active || disposed || ![x, y, pressure].every(Number.isFinite)) return;
      if (count >= MAX_POINTS) { finish(); failed("drawing_limit"); return; }
      const next = point(x, y, pressure), last = active.points[active.points.length - 1];
      if (next.every((value, index) => value === last[index])) return;
      active.points.push(next); count++; segment(context, sheet, active, last, next); notify();
    }
    const fromEvent = event => {
      const rectangle = canvas.getBoundingClientRect();
      if (rectangle.width <= 0 || rectangle.height <= 0) return null;
      return [(event.clientX - rectangle.left) / rectangle.width, (event.clientY - rectangle.top) / rectangle.height,
        event.pointerType === "pen" ? event.pressure : 1];
    };
    const down = event => {
      if (pointer !== null || event.button !== 0 && !(event.pointerType === "pen" && event.button === 5)) return;
      const position = fromEvent(event); if (!position || !begin(...position, event.button === 5 ? "eraser" : tool)) return;
      pointer = event.pointerId; canvas.focus(); event.preventDefault();
      try { canvas.setPointerCapture(pointer); } catch (_) { /* View may have been removed. */ }
    };
    const motion = event => {
      if (event.pointerId !== pointer) return;
      if (event.buttons === 0) { finish(); return; }
      const events = event.getCoalescedEvents?.() || [];
      for (const sample of events.length ? events : [event]) { const position = fromEvent(sample); if (position) move(...position); }
      event.preventDefault();
    };
    const up = event => { if (event.pointerId === pointer) { motion(event); finish(); } };
    const cancel = event => { if (event.pointerId === pointer) finish(); };
    const handlers = { pointerdown: down, pointermove: motion, pointerup: up, pointercancel: cancel, lostpointercapture: cancel };
    for (const [name, handler] of Object.entries(handlers)) canvas.addEventListener(name, handler);
    window.addEventListener?.("blur", finish);
    canvas.style.touchAction = "none";
    return {
      begin, move, finish,
      remote(sample) {
        if (disposed || pointer !== null) return;
        if (!sample || !sample.active || !sample.touching) { finish(); return; }
        if (![sample.x, sample.y, sample.pressure].every(Number.isFinite) ||
            sample.x < 0 || sample.x > 1 || sample.y < 0 || sample.y > 1) { finish(); return; }
        const selectedTool = sample.tool === "Rubber" || tool === "eraser" ? "eraser" : "pen";
        if (active && active.tool !== selectedTool) finish();
        if (!active) begin(sample.x, sample.y, sample.pressure, selectedTool);
        else move(sample.x, sample.y, sample.pressure);
      },
      setTool(value) { finish(); tool = value === "eraser" ? "eraser" : "pen"; },
      setColor(value) { if (/^#[0-9a-f]{6}$/i.test(value)) color = value; },
      setWidth(value) { if (finite(value, 0.5, 80)) width = value; },
      undo() {
        finish(); const action = undo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = action.strokes;
        else sheet.strokes = sheet.strokes.filter(stroke => stroke !== action.stroke);
        redo.push(action); count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
        render(canvas, sheet); notify();
      },
      redo() {
        finish(); const action = redo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = [];
        else sheet.strokes.push(action.stroke);
        undo.push(action); count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
        render(canvas, sheet); notify();
      },
      clear() {
        finish(); if (!sheet.strokes.length) return;
        undo.push({ type: "clear", strokes: sheet.strokes }); redo.length = 0; sheet.strokes = []; count = 0; prune();
        render(canvas, sheet); notify();
      },
      canUndo: () => undo.length > 0,
      canRedo: () => redo.length > 0,
      exportPng: () => canvas.toDataURL("image/png"),
      destroy() {
        finish(); disposed = true;
        for (const [name, handler] of Object.entries(handlers)) canvas.removeEventListener(name, handler);
        window.removeEventListener?.("blur", finish);
      }
    };
  }
  window.MagnolieZeichnen = Object.freeze({ create, valid, render, attach, MAX_POINTS, MAX_STROKES });
})();
