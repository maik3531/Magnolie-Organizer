"use strict";
(() => {
  const MAX_POINTS = 200000, MAX_STROKES = 2000;
  const finite = (value, min, max) => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
  const TOOLS = ["pen", "quill", "brush", "highlighter", "eraser", "fill", "rectangle", "ellipse", "triangle", "line"];
  const SHAPES = ["rectangle", "ellipse", "triangle", "line"];
  let drawingClipboard = [];
  const create = () => ({ version: 2, width: 1200, height: 800, strokes: [] });
  function valid(sheet) {
    if (!sheet || ![1, 2, 3].includes(sheet.version) || !Number.isInteger(sheet.width) || !Number.isInteger(sheet.height) ||
        !finite(sheet.width, 1, 4096) || !finite(sheet.height, 1, 4096) || !Array.isArray(sheet.strokes) ||
        sheet.strokes.length > MAX_STROKES) return false;
    let points = 0;
    for (const stroke of sheet.strokes) {
      if (!stroke || !(sheet.version === 1 ? ["pen", "eraser"] : TOOLS).includes(stroke.tool) || !/^#[0-9a-f]{6}$/i.test(stroke.color || "") ||
          !finite(stroke.width, 0.5, 80) || !Array.isArray(stroke.points) || !stroke.points.length) return false;
      if (stroke.gradient !== undefined && (!Array.isArray(stroke.gradient) || stroke.gradient.length !== 2 || stroke.gradient.some(value => !/^#[0-9a-f]{6}$/i.test(value)))) return false;
      if (stroke.renderVersion !== undefined && stroke.renderVersion !== 3) return false;
      if (stroke.nibAngle !== undefined && !finite(stroke.nibAngle, 0, 360)) return false;
      if (stroke.space !== undefined && (sheet.version < 2 || !Array.isArray(stroke.space) || stroke.space.length !== 2 ||
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
    if (stroke.tool === "fill") {
      const a = stroke.points[0], b = stroke.points[1];
      if (stroke.gradient) { const gradient = context.createLinearGradient(a[0] * space[0], a[1] * space[1], b[0] * space[0], b[1] * space[1]);
        gradient.addColorStop(0, stroke.gradient[0]); gradient.addColorStop(1, stroke.gradient[1]); context.fillStyle = gradient; }
      const polygon = stroke.points.length === 2 ? [a, [b[0], a[1]], b, [a[0], b[1]]] : stroke.points;
      context.beginPath(); polygon.forEach((point, index) => index ? context.lineTo(point[0] * space[0], point[1] * space[1]) : context.moveTo(point[0] * space[0], point[1] * space[1]));
      context.closePath(); context.fill();
      context.restore(); return;
    }
    if (SHAPES.includes(stroke.tool)) {
      const a = stroke.points[0], b = stroke.points[stroke.points.length - 1], x = a[0] * space[0], y = a[1] * space[1], right = b[0] * space[0], bottom = b[1] * space[1];
      context.lineWidth = stroke.width; context.beginPath();
      if (stroke.tool === "ellipse") {
        const cx = (x + right) / 2, cy = (y + bottom) / 2, rx = (right - x) / 2, ry = (bottom - y) / 2, k = .55228475;
        context.moveTo(cx + rx, cy); context.bezierCurveTo(cx + rx, cy + ry * k, cx + rx * k, cy + ry, cx, cy + ry);
        context.bezierCurveTo(cx - rx * k, cy + ry, cx - rx, cy + ry * k, cx - rx, cy);
        context.bezierCurveTo(cx - rx, cy - ry * k, cx - rx * k, cy - ry, cx, cy - ry);
        context.bezierCurveTo(cx + rx * k, cy - ry, cx + rx, cy - ry * k, cx + rx, cy); context.closePath();
      } else if (stroke.tool === "line") { context.moveTo(x, y); context.lineTo(right, bottom); }
      else if (stroke.tool === "triangle") { context.moveTo((x + right) / 2, y); context.lineTo(right, bottom); context.lineTo(x, bottom); context.closePath(); }
      else { context.moveTo(x, y); context.lineTo(right, y); context.lineTo(right, bottom); context.lineTo(x, bottom); context.closePath(); }
      context.stroke(); context.restore(); return;
    }
    const pressure = stroke.tool === "eraser" || stroke.tool === "highlighter" ? 1 : Math.max(0.08, (before[2] + after[2]) / 2);
    if (stroke.tool === "quill") {
      const tip = point => {
        const radius = stroke.width * (0.2 + 0.8 * point[2]) / 2;
        const x = point[0] * space[0], y = point[1] * space[1];
        const angle = stroke.nibAngle ?? (stroke.renderVersion === 3 ? 76 : 45), narrow = stroke.renderVersion === 3 ? .06 : .14;
        const dx = radius * Math.cos(angle * Math.PI / 180), dy = radius * Math.sin(angle * Math.PI / 180);
        const tx = -dy * narrow, ty = dx * narrow;
        return [[x - dx - tx, y - dy - ty], [x + dx - tx, y + dy - ty],
          [x + dx + tx, y + dy + ty], [x - dx + tx, y - dy + ty]];
      };
      const a = tip(before), b = tip(after);
      const polygon = points => { context.beginPath(); context.moveTo(...points[0]); points.slice(1).forEach(p => context.lineTo(...p)); context.closePath(); context.fill(); };
      polygon(a); polygon(b);
      for (let n = 0; n < 4; n++) polygon([a[n], a[(n + 1) % 4], b[(n + 1) % 4], b[n]]);
      context.restore(); return;
    }
    context.lineWidth = stroke.width * (stroke.tool === "brush" ? stroke.renderVersion === 3 ? 0.04 + 1.6 * pressure * pressure : .06 + .94 * pressure * pressure : pressure);
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
    if (stroke.tool === "fill" || SHAPES.includes(stroke.tool)) { segment(context, sheet, stroke, stroke.points[0], stroke.points[stroke.points.length - 1]); return; }
    if (stroke.tool === "brush" && stroke.renderVersion === 3 && stroke.points.length > 1) {
      const space = stroke.space || [sheet.width, sheet.height];
      const distances = [0];
      for (let index = 1; index < stroke.points.length; index++) distances.push(distances[index - 1] + Math.hypot(
        (stroke.points[index][0] - stroke.points[index - 1][0]) * space[0], (stroke.points[index][1] - stroke.points[index - 1][1]) * space[1]));
      const length = distances[distances.length - 1], taper = Math.min(stroke.width * 2.5, length / 2);
      const shaped = (point, distance) => [point[0], point[1], point[2] * Math.max(.04, Math.min(1, distance / (taper || 1), (length - distance) / (taper || 1)))];
      for (let index = 1; index < stroke.points.length; index++) {
        const a = stroke.points[index - 1], b = stroke.points[index], run = distances[index] - distances[index - 1];
        const steps = Math.max(1, Math.min(64, Math.ceil(run / 3)));
        let previous = shaped(a, distances[index - 1]);
        for (let n = 1; n <= steps; n++) {
          const t = n / steps, next = shaped(a.map((v, axis) => v + (b[axis] - v) * t), distances[index - 1] + run * t);
          segment(context, sheet, stroke, previous, next); previous = next;
        }
      }
      return;
    }
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
      if (stroke.gradient) { const space = stroke.space || [sheet.width, sheet.height], a = stroke.points[0], b = stroke.points[1];
        definitions += `<linearGradient id="gradient${index}" gradientUnits="userSpaceOnUse" x1="${number(a[0] * space[0])}" y1="${number(a[1] * space[1])}" x2="${number(b[0] * space[0])}" y2="${number(b[1] * space[1])}"><stop offset="0" stop-color="${stroke.gradient[0]}"/><stop offset="1" stop-color="${stroke.gradient[1]}"/></linearGradient>`; }
      const context = { save() {}, restore() {}, beginPath() { path = ""; },
        moveTo(x, y) { path += `M${number(x)} ${number(y)}`; }, lineTo(x, y) { path += `L${number(x)} ${number(y)}`; },
        closePath() { path += "Z"; },
        bezierCurveTo(...values) { path += "C" + values.map(number).join(" "); },
        createLinearGradient() { return { addColorStop() {}, toString: () => `url(#gradient${index})` }; },
        arc(x, y, radius) { path += `M${number(x + radius)} ${number(y)}A${number(radius)} ${number(radius)} 0 1 0 ${number(x - radius)} ${number(y)}A${number(radius)} ${number(radius)} 0 1 0 ${number(x + radius)} ${number(y)}Z`; },
        fill() { shapes += `<path d="${path}" fill="${stroke.tool === "eraser" ? color : this.fillStyle || color}"/>`; },
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
    let selection = null, selecting = false, moving = null, zoom = 1;
    let count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
    const base = document.createElement("canvas"), layer = document.createElement("canvas");
    let viewHeight = sheet.height;
    const resetLayers = () => { base.width = layer.width = canvas.width; base.height = layer.height = canvas.height; base.getContext("2d").drawImage(canvas, 0, 0); };
    resetLayers();
    const paintSelection = () => {
      if (!selection) return;
      const [a, b] = selection, x = Math.min(a[0], b[0]) * sheet.width, y = Math.min(a[1], b[1]) * sheet.height;
      const right = Math.max(a[0], b[0]) * sheet.width, bottom = Math.max(a[1], b[1]) * sheet.height;
      context.save(); context.strokeStyle = "#7a5f38"; context.lineWidth = 2; context.setLineDash?.([7, 4]);
      context.beginPath(); context.moveTo(x, y); context.lineTo(right, y); context.lineTo(right, bottom); context.lineTo(x, bottom); context.closePath(); context.stroke(); context.restore();
    };
    const present = () => {
      context.clearRect(0, 0, canvas.width, canvas.height); context.drawImage(base, 0, 0);
      context.save(); context.globalAlpha = active?.tool === "highlighter" ? 0.25 : 1;
      context.globalCompositeOperation = active?.tool === "eraser" ? "destination-out" : "source-over";
      context.drawImage(layer, 0, 0); context.restore();
      paintSelection();
    };
    const redraw = () => { render(canvas, sheet, viewHeight); resetLayers(); paintSelection(); };
    const prune = () => {
      const weight = action => action.type === "replace" ? action.before.concat(action.after).reduce((total, stroke) => total + stroke.points.length, 0) :
        action.type === "clear" ? action.strokes.reduce((total, stroke) => total + stroke.points.length, 0) : action.stroke.points.length;
      let retained = undo.reduce((total, action) => total + weight(action), 0);
      while (undo.length > 100 || undo.length > 1 && retained > 2 * MAX_POINTS) retained -= weight(undo.shift());
    };
    prune();
    const notify = () => { if (!disposed) changed(); };
    const finish = () => { const brush = active?.tool === "brush"; if (active) { const saved = base.getContext("2d"); saved.clearRect(0, 0, base.width, base.height); saved.drawImage(canvas, 0, 0); } active = null; pointer = null;
      selecting = false;
      if (moving) { if (moving.changed) { undo.push({ type: "replace", before: moving.before, after: sheet.strokes.slice() }); redo.length = 0; prune(); notify(); }
        moving = null; }
      if (brush) redraw(); };
    const resize = () => {
      if (!viewport || disposed) return;
      const box = viewport.getBoundingClientRect(); if (box.width <= 0 || box.height <= 0) return;
      finish();
      const scale = zoom * Math.min(Math.max(1, (viewport.clientWidth || box.width) - 2) / sheet.width,
        Math.max(1, (viewport.clientHeight || box.height) - 2) / sheet.height);
      viewHeight = sheet.height;
      canvas.style.width = (sheet.width * scale) + "px"; canvas.style.height = (viewHeight * scale) + "px";
      canvas.style.marginInline = "auto";
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
      if (selectedTool === "select") { finish(); selection = [[x, y], [x, y]]; selecting = true; redraw(); return true; }
      if (selectedTool === "move") {
        finish(); if (!selection) return false;
        const [a, b] = selection;
        const indices = sheet.strokes.map((stroke, index) => { const space = stroke.space || [sheet.width, sheet.height];
          return stroke.points.every(p => p[0] * space[0] >= Math.min(a[0], b[0]) * sheet.width && p[0] * space[0] <= Math.max(a[0], b[0]) * sheet.width &&
            p[1] * space[1] >= Math.min(a[1], b[1]) * sheet.height && p[1] * space[1] <= Math.max(a[1], b[1]) * sheet.height) ? index : -1; }).filter(index => index >= 0);
        if (!indices.length) return false;
        moving = { origin: [x, y], before: sheet.strokes.slice(), selection: selection.map(p => p.slice()), indices: new Set(indices), changed: false }; return true;
      }
      if (sheet.strokes.length >= MAX_STROKES || count >= MAX_POINTS) { failed("drawing_limit"); return false; }
      finish(); redo.length = 0;
      grow();
      if (["quill", "brush", "fill", ...SHAPES].includes(selectedTool)) sheet.version = 3;
      else if (!["pen", "eraser"].includes(selectedTool)) sheet.version = Math.max(2, sheet.version);
      active = { tool: TOOLS.includes(selectedTool) ? selectedTool : "pen", color, width: selectedTool === "eraser" ? Math.max(16, width) : width,
        points: [point(x, y, pressure)], renderVersion: 3 };
      sheet.strokes.push(active); undo.push({ type: "stroke", stroke: active }); count++; prune();
      layer.getContext("2d").clearRect(0, 0, layer.width, layer.height);
      segment(layer.getContext("2d"), sheet, active, active.points[0], active.points[0], true);
      present(); notify(); return true;
    }
    function move(x, y, pressure) {
      if (moving) {
        const [a, b] = moving.selection, dx = Math.max(-Math.min(a[0], b[0]), Math.min(1 - Math.max(a[0], b[0]), x - moving.origin[0])),
          dy = Math.max(-Math.min(a[1], b[1]), Math.min(1 - Math.max(a[1], b[1]), y - moving.origin[1]));
        sheet.strokes = moving.before.map((stroke, index) => {
          if (!moving.indices.has(index)) return stroke; const space = stroke.space || [sheet.width, sheet.height];
          return { ...stroke, space: [sheet.width, sheet.height], points: stroke.points.map(p =>
            [Math.max(0, Math.min(1, p[0] * space[0] / sheet.width + dx)), Math.max(0, Math.min(1, p[1] * space[1] / sheet.height + dy)), p[2]]) };
        });
        selection = moving.selection.map(p => [p[0] + dx, p[1] + dy]); moving.changed = dx !== 0 || dy !== 0; sheet.version = 3; redraw(); return;
      }
      if (selecting && selection) { selection[1] = [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))]; redraw(); return; }
      if (!active || disposed || ![x, y, pressure].every(Number.isFinite)) return;
      if (count >= MAX_POINTS) { finish(); failed("drawing_limit"); return; }
      const next = point(x, y, pressure), last = active.points[active.points.length - 1];
      if (SHAPES.includes(active.tool)) {
        if (active.points.length === 1) { active.points.push(next); count++; } else active.points[1] = next;
        layer.getContext("2d").clearRect(0, 0, layer.width, layer.height);
        segment(layer.getContext("2d"), sheet, active, active.points[0], next); present(); notify(); return;
      }
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
       if (!active && !selecting && !moving) begin(x, y, sample.pressure, selectedTool);
        else move(x, y, sample.pressure);
      },
      setTool(value) { finish(); tool = ["select", "move"].includes(value) || TOOLS.includes(value) ? value : "pen";
        if (!["select", "move"].includes(tool)) selection = null; redraw(); },
      setColor(value) { if (/^#[0-9a-f]{6}$/i.test(value)) color = value; },
      setWidth(value) { if (finite(value, 0.5, 80)) width = value; },
      setSize(w, h) {
        if (!Number.isInteger(w) || !Number.isInteger(h) || !finite(w, 200, 4096) || !finite(h, 200, 4096)) return false;
        finish(); const old = [sheet.width, sheet.height];
        for (const stroke of sheet.strokes) if (!stroke.space) stroke.space = old.slice();
        for (const action of undo.concat(redo)) for (const stroke of action.type === "replace" ? action.before.concat(action.after) : action.type === "clear" ? action.strokes : [action.stroke])
          if (!stroke.space) stroke.space = old.slice();
        sheet.width = w; sheet.height = h; sheet.version = Math.max(2, sheet.version); viewHeight = h;
        redraw(); if (viewport) resize(); notify(); return true;
      },
      cut() {
        if (!selection) return false;
        const [a, b] = selection, left = Math.min(a[0], b[0]) * sheet.width, right = Math.max(a[0], b[0]) * sheet.width,
          top = Math.min(a[1], b[1]) * sheet.height, bottom = Math.max(a[1], b[1]) * sheet.height;
        const chosen = sheet.strokes.filter(stroke => { const space = stroke.space || [sheet.width, sheet.height];
          return stroke.points.some(p => p[0] * space[0] >= left && p[0] * space[0] <= right && p[1] * space[1] >= top && p[1] * space[1] <= bottom); });
        if (!chosen.length) return false;
        drawingClipboard = chosen.map(stroke => ({ ...JSON.parse(JSON.stringify(stroke)), space: (stroke.space || [sheet.width, sheet.height]).slice() }));
        const before = sheet.strokes.slice(); sheet.strokes = sheet.strokes.filter(stroke => !chosen.includes(stroke));
        undo.push({ type: "replace", before, after: sheet.strokes.slice() }); redo.length = 0; count = sheet.strokes.reduce((sum, stroke) => sum + stroke.points.length, 0);
        redraw(); prune(); notify(); return true;
      },
      paste() {
        if (!drawingClipboard.length || sheet.strokes.length + drawingClipboard.length > MAX_STROKES || count + drawingClipboard.reduce((sum, stroke) => sum + stroke.points.length, 0) > MAX_POINTS) return false;
        const before = sheet.strokes.slice(); sheet.strokes.push(...JSON.parse(JSON.stringify(drawingClipboard))); sheet.version = 3;
        undo.push({ type: "replace", before, after: sheet.strokes.slice() }); redo.length = 0; selection = null;
        count = sheet.strokes.reduce((sum, stroke) => sum + stroke.points.length, 0); redraw(); prune(); notify(); return true;
      },
      fillSelection(secondColor = null) {
        if (!selection || sheet.strokes.length >= MAX_STROKES || count + 4 > MAX_POINTS) return false;
        const [a, b] = selection;
        if (a[0] === b[0] || a[1] === b[1]) return false;
        const stroke = { tool: "fill", color, width: 1, points: [point(...a, 1), point(b[0], a[1], 1), point(...b, 1), point(a[0], b[1], 1)] };
        if (secondColor && /^#[0-9a-f]{6}$/i.test(secondColor)) stroke.gradient = [color, secondColor];
        sheet.version = 3; sheet.strokes.push(stroke); undo.push({ type: "stroke", stroke }); redo.length = 0; count += 4;
        redraw(); prune(); notify(); return true;
      },
      transformSelection(angle = 0, dx = 0, dy = 0) {
        if (!selection || ![angle, dx, dy].every(Number.isFinite)) return false;
        finish(); const [a, b] = selection, left = Math.min(a[0], b[0]) * sheet.width, right = Math.max(a[0], b[0]) * sheet.width,
          top = Math.min(a[1], b[1]) * sheet.height, bottom = Math.max(a[1], b[1]) * sheet.height;
        const cx = (left + right) / 2, cy = (top + bottom) / 2, cosine = Math.cos(angle * Math.PI / 180), sine = Math.sin(angle * Math.PI / 180);
        const before = sheet.strokes.slice(), after = sheet.strokes.map(stroke => {
          const space = stroke.space || [sheet.width, sheet.height];
          if (!stroke.points.every(p => p[0] * space[0] >= left && p[0] * space[0] <= right && p[1] * space[1] >= top && p[1] * space[1] <= bottom)) return stroke;
          let points = stroke.points, type = stroke.tool;
          if (SHAPES.includes(type) && angle !== 0) {
            const a = stroke.points[0], b = stroke.points[stroke.points.length - 1];
            if (type === "rectangle") points = [a, [b[0], a[1], 1], b, [a[0], b[1], 1], a];
            else if (type === "triangle") points = [[(a[0] + b[0]) / 2, a[1], 1], b, [a[0], b[1], 1], [(a[0] + b[0]) / 2, a[1], 1]];
            else if (type === "ellipse") points = Array.from({ length: 65 }, (_, i) => [(a[0] + b[0]) / 2 + (b[0] - a[0]) / 2 * Math.cos(i * Math.PI / 32),
              (a[1] + b[1]) / 2 + (b[1] - a[1]) / 2 * Math.sin(i * Math.PI / 32), 1]);
            type = "pen";
          }
          return { ...stroke, tool: type, ...(stroke.tool === "quill" ? { nibAngle: ((stroke.nibAngle ?? (stroke.renderVersion === 3 ? 76 : 45)) + angle + 3600) % 360 } : {}),
            space: [sheet.width, sheet.height], points: points.map(p => {
            const x = p[0] * space[0] - cx, y = p[1] * space[1] - cy;
            return [(x * cosine - y * sine + cx + dx) / sheet.width, (x * sine + y * cosine + cy + dy) / sheet.height, p[2]];
          }) };
        });
        if (!valid({ ...sheet, strokes: after }) || after.every((stroke, i) => stroke === before[i])) return false;
        sheet.strokes = after; sheet.version = 3; count = after.reduce((sum, stroke) => sum + stroke.points.length, 0);
        undo.push({ type: "replace", before, after: after.slice() }); redo.length = 0; selection = null;
        redraw(); prune(); notify(); return true;
      },
      setZoom(value) { if (!finite(value, .25, 4)) return false; zoom = value; resize(); return true; },
      getZoom: () => zoom,
      undo() {
        finish(); const action = undo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = action.strokes;
        else if (action.type === "replace") sheet.strokes = action.before.slice();
        else sheet.strokes = sheet.strokes.filter(stroke => stroke !== action.stroke);
        redo.push(action); count = sheet.strokes.reduce((total, stroke) => total + stroke.points.length, 0);
        redraw(); notify();
      },
      redo() {
        finish(); const action = redo.pop(); if (!action) return;
        if (action.type === "clear") sheet.strokes = [];
        else if (action.type === "replace") sheet.strokes = action.after.slice();
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
      exportPng: () => { finish(); const image = document.createElement("canvas"); render(image, sheet); return image.toDataURL("image/png"); },
      exportSvg: () => { finish(); return svg(sheet); },
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
