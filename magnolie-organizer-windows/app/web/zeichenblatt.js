"use strict";
(() => {
  const MAX_POINTS = 200000, MAX_STROKES = 2000;
  const finite = (value, min, max) => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
  const TOOLS = ["pen", "quill", "brush", "highlighter", "eraser"];
  const create = () => ({ version: 2, width: 1200, height: 800, strokes: [] });
  function valid(sheet) {
    if (!sheet || ![1, 2].includes(sheet.version) || !Number.isInteger(sheet.width) || !Number.isInteger(sheet.height) ||
        !finite(sheet.width, 1, 4096) || !finite(sheet.height, 1, 4096) || !Array.isArray(sheet.strokes) ||
        sheet.strokes.length > MAX_STROKES) return false;
    let points = 0;
    for (const stroke of sheet.strokes) {
      if (!stroke || !(sheet.version === 1 ? ["pen", "eraser"] : TOOLS).includes(stroke.tool) || !/^#[0-9a-f]{6}$/i.test(stroke.color || "") ||
          !finite(stroke.width, 0.5, 80) || !Array.isArray(stroke.points) || !stroke.points.length) return false;
      if (stroke.space !== undefined && (sheet.version !== 2 || !Array.isArray(stroke.space) || stroke.space.length !== 2 ||
          stroke.space.some(value => !Number.isInteger(value) || !finite(value, 1, 4096)))) return false;
      points += stroke.points.length;
      if (points > MAX_POINTS || stroke.points.some(point => !Array.isArray(point) || point.length !== 3 ||
          !finite(point[0], 0, 1) || !finite(point[1], 0, 1) || !finite(point[2], 0, 1))) return false;
    }
    return true;
  }
  function segment(context, sheet, stroke, before, after, mask = false) {
    context.save();
    context.globalCompositeOperation = stroke.tool === "eraser" && !mask ? "destination-out" : "source-over";
    context.strokeStyle = context.fillStyle = stroke.color;
    context.lineCap = context.lineJoin = "round";
    const space = stroke.space || [sheet.width, sheet.height];
    const pressure = stroke.tool === "eraser" || stroke.tool === "highlighter" ? 1 : Math.max(0.08, (before[2] + after[2]) / 2);
    if (stroke.tool === "quill") {
      const tip = point => {
        const radius = stroke.width * (0.2 + 0.8 * point[2]) / 2;
        const x = point[0] * space[0], y = point[1] * space[1], axis = radius / Math.sqrt(2), thin = axis * 0.14;
        return [[x - axis + thin, y - axis - thin], [x + axis + thin, y + axis - thin],
          [x + axis - thin, y + axis + thin], [x - axis - thin, y - axis + thin]];
      };
      const a = tip(before), b = tip(after);
      const polygon = points => { context.beginPath(); context.moveTo(...points[0]); points.slice(1).forEach(p => context.lineTo(...p)); context.closePath(); context.fill(); };
      polygon(a); polygon(b);
      for (let n = 0; n < 4; n++) polygon([a[n], a[(n + 1) % 4], b[(n + 1) % 4], b[n]]);
      context.restore(); return;
    }
    context.lineWidth = stroke.width * (stroke.tool === "brush" ? 0.06 + 0.94 * pressure * pressure : pressure);
    context.beginPath();
    if (before === after) {
      context.arc(after[0] * space[0], after[1] * space[1], context.lineWidth / 2, 0, 2 * Math.PI);
      context.fill();
    } else {
      context.moveTo(before[0] * space[0], before[1] * space[1]);
      context.lineTo(after[0] * space[0], after[1] * space[1]); context.stroke();
    }
    context.restore();
  }
  function paint(context, sheet, stroke) {
    segment(context, sheet, stroke, stroke.points[0], stroke.points[0]);
    for (let index = 1; index < stroke.points.length; index++) segment(context, sheet, stroke, stroke.points[index - 1], stroke.points[index]);
  }
  function render(canvas, sheet, height = sheet.height) {
    if (!valid(sheet)) throw new Error("invalid_drawing");
    canvas.width = sheet.width; canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("drawing_unavailable");
    context.clearRect(0, 0, canvas.width, canvas.height);
    let markerLayer = null;
    for (const stroke of sheet.strokes) {
      if (stroke.tool === "highlighter") {
        const layer = markerLayer ||= document.createElement("canvas"); layer.width = canvas.width; layer.height = canvas.height;
        paint(layer.getContext("2d"), sheet, stroke);
        context.save(); context.globalAlpha = 0.25; context.drawImage(layer, 0, 0); context.restore();
      } else paint(context, sheet, stroke);
    }
    return context;
  }
  function svg(sheet) {
    if (!valid(sheet)) throw new Error("invalid_drawing");
    const number = value => String(Number(value.toFixed(4)));
    let content = "", definitions = "";
    sheet.strokes.forEach((stroke, index) => {
      let path = "", shapes = "";
      const color = stroke.tool === "eraser" ? "#000000" : stroke.color;
      const context = { save() {}, restore() {}, beginPath() { path = ""; },
        moveTo(x, y) { path += `M${number(x)} ${number(y)}`; }, lineTo(x, y) { path += `L${number(x)} ${number(y)}`; },
        closePath() { path += "Z"; },
        arc(x, y, radius) { path += `M${number(x + radius)} ${number(y)}A${number(radius)} ${number(radius)} 0 1 0 ${number(x - radius)} ${number(y)}A${number(radius)} ${number(radius)} 0 1 0 ${number(x + radius)} ${number(y)}Z`; },
        fill() { shapes += `<path d="${path}" fill="${color}"/>`; },
        stroke() { shapes += `<path d="${path}" fill="none" stroke="${color}" stroke-width="${number(this.lineWidth)}" stroke-linecap="round" stroke-linejoin="round"/>`; }
      };
      paint(context, sheet, stroke);
      if (stroke.tool === "eraser") {
        definitions += `<mask id="erase${index}" maskUnits="userSpaceOnUse" x="0" y="0" width="${sheet.width}" height="${sheet.height}"><rect width="100%" height="100%" fill="white"/>${shapes}</mask>`;
        content = `<g mask="url(#erase${index})">${content}</g>`;
      } else content += `<g${stroke.tool === "highlighter" ? ' opacity="0.25"' : ""}>${shapes}</g>`;
    });
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${sheet.width}" height="${sheet.height}" viewBox="0 0 ${sheet.width} ${sheet.height}"><defs>${definitions}</defs>${content}</svg>`;
  }

  function attach(canvas, sheet, changed, failed = () => {}, viewport = null) {
    const context = render(canvas, sheet), undo = sheet.strokes.map(stroke => ({ type: "stroke", stroke })), redo = [];
    let active = null, pointer = null, disposed = false, tool = "pen", color = "#1d2433", width = 4;
    let count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
    const base = document.createElement("canvas"), layer = document.createElement("canvas");
    let viewHeight = sheet.height;
    const resetLayers = () => { base.width = layer.width = canvas.width; base.height = layer.height = canvas.height; base.getContext("2d").drawImage(canvas, 0, 0); };
    resetLayers();
    const present = () => {
      context.clearRect(0, 0, canvas.width, canvas.height); context.drawImage(base, 0, 0);
      context.save(); context.globalAlpha = active?.tool === "highlighter" ? 0.25 : 1;
      context.globalCompositeOperation = active?.tool === "eraser" ? "destination-out" : "source-over";
      context.drawImage(layer, 0, 0); context.restore();
    };
    const redraw = () => { render(canvas, sheet, viewHeight); resetLayers(); };
    const prune = () => {
      const weight = action => action.type === "clear" ? action.strokes.reduce((total, stroke) => total + stroke.points.length, 0) : action.stroke.points.length;
      let retained = undo.reduce((total, action) => total + weight(action), 0);
      while (undo.length > 100 || undo.length > 1 && retained > 2 * MAX_POINTS) retained -= weight(undo.shift());
    };
    prune();
    const notify = () => { if (!disposed) changed(); };
    const finish = () => { if (active) { const saved = base.getContext("2d"); saved.clearRect(0, 0, base.width, base.height); saved.drawImage(canvas, 0, 0); } active = null; pointer = null; };
    const resize = () => {
      if (!viewport || disposed) return;
      const box = viewport.getBoundingClientRect(); if (box.width <= 0 || box.height <= 0) return;
      finish();
      const scale = Math.max((viewport.clientWidth || box.width) / sheet.width, box.height / 4096);
      viewHeight = Math.max(sheet.height, Math.min(4096, Math.ceil(box.height / scale)));
      canvas.style.width = (sheet.width * scale) + "px"; canvas.style.height = (viewHeight * scale) + "px";
      redraw();
    };
    const grow = () => {
      if (viewHeight <= sheet.height) return;
      const old = [sheet.width, sheet.height];
      const freeze = stroke => { if (!stroke.space) stroke.space = old.slice(); };
      sheet.strokes.forEach(freeze);
      for (const action of undo.concat(redo)) (action.type === "clear" ? action.strokes : [action.stroke]).forEach(freeze);
      sheet.height = viewHeight; sheet.version = 2;
    };
    const point = (x, y, pressure) => [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y)), Math.max(0, Math.min(1, pressure))];
    function begin(x, y, pressure, selectedTool = tool) {
      if (disposed || ![x, y, pressure].every(Number.isFinite)) return false;
      if (sheet.strokes.length >= MAX_STROKES || count >= MAX_POINTS) { failed("drawing_limit"); return false; }
      finish(); redo.length = 0;
      grow();
      if (!["pen", "eraser"].includes(selectedTool)) sheet.version = 2;
      active = { tool: TOOLS.includes(selectedTool) ? selectedTool : "pen", color, width: selectedTool === "eraser" ? Math.max(16, width) : width,
        points: [point(x, y, pressure)] };
      sheet.strokes.push(active); undo.push({ type: "stroke", stroke: active }); count++; prune();
      layer.getContext("2d").clearRect(0, 0, layer.width, layer.height);
      segment(layer.getContext("2d"), sheet, active, active.points[0], active.points[0], true);
      present(); notify(); return true;
    }
    function move(x, y, pressure) {
      if (!active || disposed || ![x, y, pressure].every(Number.isFinite)) return;
      if (count >= MAX_POINTS) { finish(); failed("drawing_limit"); return; }
      const next = point(x, y, pressure), last = active.points[active.points.length - 1];
      if (next.every((value, index) => value === last[index])) return;
      active.points.push(next); count++;
      segment(layer.getContext("2d"), sheet, active, last, next, true);
      present(); notify();
    }
    const fromEvent = event => {
      const rectangle = canvas.getBoundingClientRect();
      if (rectangle.width <= 0 || rectangle.height <= 0) return null;
      const style = window.getComputedStyle?.(canvas);
      const left = parseFloat(style?.borderLeftWidth) || 0, top = parseFloat(style?.borderTopWidth) || 0;
      const right = parseFloat(style?.borderRightWidth) || 0, bottom = parseFloat(style?.borderBottomWidth) || 0;
      return [(event.clientX - rectangle.left - left) / Math.max(1, rectangle.width - left - right),
        (event.clientY - rectangle.top - top) / Math.max(1, rectangle.height - top - bottom),
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
    const observer = viewport && typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    observer?.observe(viewport);
    if (viewport) requestAnimationFrame(resize);
    return {
      begin, move, finish,
      remote(sample) {
        if (disposed || pointer !== null) return;
        if (!sample || !sample.active || !sample.touching) { finish(); return; }
        if (![sample.x, sample.y, sample.pressure].every(Number.isFinite) ||
            sample.x < 0 || sample.x > 1 || sample.y < 0 || sample.y > 1) { finish(); return; }
        const selectedTool = sample.tool === "Rubber" ? "eraser" : tool;
        let x = sample.x, y = sample.y;
        if (viewport) {
          const box = viewport.getBoundingClientRect();
          const mapped = fromEvent({ clientX: box.left + x * viewport.clientWidth,
            clientY: box.top + y * viewport.clientHeight, pointerType: "pen", pressure: sample.pressure });
          if (!mapped) return;
          [x, y] = mapped;
        }
        if (active && active.tool !== selectedTool) finish();
        if (!active) begin(x, y, sample.pressure, selectedTool);
        else move(x, y, sample.pressure);
      },
      setTool(value) { finish(); tool = TOOLS.includes(value) ? value : "pen"; },
      setColor(value) { if (/^#[0-9a-f]{6}$/i.test(value)) color = value; },
      setWidth(value) { if (finite(value, 0.5, 80)) width = value; },
      undo() {
        finish(); const action = undo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = action.strokes;
        else sheet.strokes = sheet.strokes.filter(stroke => stroke !== action.stroke);
        redo.push(action); count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
        redraw(); notify();
      },
      redo() {
        finish(); const action = redo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = [];
        else sheet.strokes.push(action.stroke);
        undo.push(action); count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
        redraw(); notify();
      },
      clear() {
        finish(); if (!sheet.strokes.length) return;
        undo.push({ type: "clear", strokes: sheet.strokes }); redo.length = 0; sheet.strokes = []; count = 0; prune();
        redraw(); notify();
      },
      canUndo: () => undo.length > 0,
      canRedo: () => redo.length > 0,
      exportPng: () => { const image = document.createElement("canvas"); render(image, sheet); return image.toDataURL("image/png"); },
      exportSvg: () => svg(sheet),
      resize,
      destroy() {
        finish(); disposed = true;
        for (const [name, handler] of Object.entries(handlers)) canvas.removeEventListener(name, handler);
        window.removeEventListener?.("blur", finish);
        observer?.disconnect();
      }
    };
  }
  window.MagnolieZeichnen = Object.freeze({ create, valid, render, svg, attach, MAX_POINTS, MAX_STROKES });
})();
