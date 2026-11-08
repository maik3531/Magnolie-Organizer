"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const dom = new JSDOM("<!doctype html><body></body>", { runScripts: "outside-only" });
try {
  assert.equal(fs.readFileSync(path.join(__dirname, "../web/appearance.js"), "utf8"),
    fs.readFileSync(path.join(__dirname, "../../magnolie-organizer-windows/app/web/appearance.js"), "utf8"), "Both desktop platforms must use the same appearance model");
  dom.window.eval(fs.readFileSync(path.join(__dirname, "../web/appearance.js"), "utf8"));
  const appearance = dom.window.MagnolieAppearance;
  assert.deepEqual([appearance.connection(false, false), appearance.connection(true, false), appearance.connection(false, true), appearance.connection(true, true)], ["none", "notes", "kde", "both"]);
  assert.equal(appearance.connection("paired", 1), "none", "Pairing/truthy values must never count as a native connection");
  for (const [date, expected] of [["2026-12-05", "none"], ["2026-12-06", "crystals"], ["2026-12-29", "crystals"], ["2026-12-30", "stars"], ["2026-12-31", "stars"], ["2027-01-01", "stars"], ["2027-01-02", "none"], ["2026-02-30", "none"]]) assert.equal(appearance.season(date), expected, date);
  for (const [date, expected] of [["2026-12-06", "boots"], ["2026-12-24", "santa"], ["2026-12-31", "rocket"], ["2027-01-01", "glass"], ["2026-04-05", "eggs"], ["2026-04-06", "eggs"], ["2027-03-28", "eggs"], ["2027-03-29", "eggs"], ["2026-04-07", "none"]]) assert.equal(appearance.holiday(date), expected, date);
  for (const connected of ["none", "notes", "kde", "both"]) for (const mode of ["flower", "camera", "phone"]) for (const sync of [false, true]) {
    const svg = appearance.tray({ connected, mode, sync });
    assert.equal(!!svg.querySelector('[data-appearance-shape="sync"]'), sync);
    assert.equal(!!svg.querySelector('[data-appearance-shape="camera"]'), mode === "camera");
    assert.equal(!!svg.querySelector('[data-appearance-shape="flower"]'), mode !== "camera", "A camera replaces, not overlaps, the flower");
    assert.equal(svg.querySelectorAll("image,script,foreignObject,a").length, 0);
    assert.equal(svg.getAttribute("aria-hidden"), "true");
  }
  for (const kind of ["boots", "santa", "rocket", "glass", "eggs"]) assert.equal(appearance.stamp(kind).dataset.appearanceWatermark, kind);
  assert.equal(appearance.stamp("<svg>"), null);
  assert.throws(() => appearance.tray({ connected: "paired" }));
  assert.throws(() => appearance.tray({ sync: "true" }));
  assert.equal(appearance.crystal().querySelectorAll("path").length, 6);
  assert(appearance.star().querySelector("path"));
  const desktop = dom.window.document.createElement("main"); desktop.id = "schreibtisch";
  const draft = dom.window.document.createElement("textarea"); draft.value = "Unsaved original"; desktop.append(draft); dom.window.document.body.append(desktop);
  for (const [today, expected] of [["2026-12-05", null], ["2026-12-06", "crystals"], ["2026-12-30", "stars"], ["2027-01-01", "stars"], ["2027-01-02", null]]) {
    appearance.update({ today, developer: false, locked: false });
    assert.equal(desktop.querySelector("#magnolie-saison")?.dataset.season || null, expected);
    assert.equal(draft.value, "Unsaved original", "Date rollover may not replace an unsaved editor");
    assert.equal(dom.window.document.body.hasAttribute("data-appearance-test"), false);
  }
  console.log("Appearance model PASS: actual-boolean color matrix, seasonal boundaries, Gregorian Easter, 24 isolated icon variants and passive original vector shapes.");
} finally { dom.window.close(); }
