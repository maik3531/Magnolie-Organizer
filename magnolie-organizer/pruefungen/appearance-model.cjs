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
  for (const [date, expected] of [["2026-12-05", "none"], ["2026-12-06", "crystals"], ["2026-12-29", "crystals"], ["2026-12-30", "stars"], ["2026-12-31", "stars"], ["2027-01-01", "stars"], ["2027-01-02", "none"], ["2026-02-30", "none"]]) assert.equal(appearance.season(date, "DE"), expected, date);
  for (const country of ["", "ES", "FR", "IT", "AU", "CN", "ZZ"]) assert.equal(appearance.season("2026-12-10", country), "none", country);
  for (const [date, expected] of [["2026-12-06", "boots"], ["2026-12-24", "santa"], ["2026-12-31", "rocket"], ["2027-01-01", "glass"], ["2026-04-05", "eggs"], ["2026-04-06", "eggs"], ["2027-03-28", "eggs"], ["2027-03-29", "eggs"], ["2026-04-07", "none"]]) assert.equal(appearance.holiday(date, "DE"), expected, date);
  for (const [date, country, expected] of [
    ["2026-08-01", "CH", "swiss-lantern"], ["2026-08-01", "DE", "none"],
    ["2026-07-14", "FR", "french-rosette"], ["2026-07-14", "BE", "none"],
    ["2025-04-26", "NL", "kings-crown"], ["2025-04-27", "NL", "none"],
    ["2026-04-27", "NL", "kings-crown"], ["2026-04-26", "NL", "none"],
    ["2013-04-27", "NL", "none"], ["2026-12-06", "", "none"],
    ["2026-04-05", "CN", "none"], ["2026-01-01", "ZZ", "none"]
  ]) assert.equal(appearance.holiday(date, country), expected, date + " " + country);
  for (const kind of ["swiss-lantern", "french-rosette", "kings-crown"]) {
    const svg = appearance.stamp(kind);
    assert.equal(svg.dataset.appearanceWatermark, kind);
    assert.equal(svg.getAttribute("aria-hidden"), "true");
    assert.equal(svg.getAttribute("focusable"), "false");
    assert(svg.querySelectorAll("path").length >= 5);
    assert.equal(svg.querySelectorAll("image,script,foreignObject,a,animate,animateTransform").length, 0);
  }
  for (const connected of ["none", "notes", "kde", "both"]) for (const mode of ["flower", "camera", "phone"]) for (const sync of [false, true]) {
    const svg = appearance.tray({ connected, mode, sync });
    assert.equal(!!svg.querySelector('[data-appearance-shape="sync"]'), sync);
    assert.equal(!!svg.querySelector('[data-appearance-shape="camera"]'), mode === "camera");
    assert.equal(!!svg.querySelector('[data-appearance-shape="flower"]'), mode !== "camera", "A camera replaces, not overlaps, the flower");
    assert.equal(svg.querySelectorAll("image,script,foreignObject,a").length, 0);
    assert.equal(svg.getAttribute("aria-hidden"), "true");
  }
  for (const kind of ["boots", "santa", "rocket", "glass", "eggs"]) assert.equal(appearance.stamp(kind).dataset.appearanceWatermark, kind);
  const boots = appearance.stamp("boots"), santa = appearance.stamp("santa");
  assert.equal(boots.querySelectorAll('[data-motif-part="boot"]').length, 2);
  assert.equal(boots.querySelectorAll('[data-motif-part="fur-cuff"]').length, 2);
  for (const part of ["fir-sprig", "candy-cane"]) assert(boots.querySelector(`[data-motif-part="${part}"]`));
  for (const part of ["winter-hat", "pom-pom", "fur-brim", "beard", "smile", "moustache"]) assert(santa.querySelector(`[data-motif-part="${part}"]`));
  const rocket = appearance.stamp("rocket"), glasses = appearance.stamp("glass"), eggs = appearance.stamp("eggs");
  for (const part of ["paper-cap", "firework-body", "guide-stick", "fuse", "sparks"]) assert(rocket.querySelector(`[data-motif-part="${part}"]`), "A firework needs its paper body, stick and fuse, not spacecraft fins");
  const flutes = [...glasses.querySelectorAll('[data-motif-part="flute"]')];
  assert.equal(flutes.length, 2); assert.notEqual(flutes[0].getAttribute("transform"), flutes[1].getAttribute("transform"));
  assert(glasses.querySelector('[data-motif-part="clink"]')); assert(glasses.querySelectorAll('[data-motif-part="confetti"]').length >= 2);
  assert.equal(eggs.querySelectorAll('[data-motif-part="painted-egg"]').length, 2);
  assert.equal(eggs.querySelectorAll('[data-motif-part="egg-pattern"]').length, 2);
  assert(eggs.querySelector('[data-motif-part="spring-grass"]')); assert(eggs.querySelector('[data-motif-part="ribbon"]'));
  for (const svg of [boots, santa, rocket, glasses, eggs]) {
    assert.equal(svg.getAttribute("aria-hidden"), "true"); assert.equal(svg.getAttribute("focusable"), "false");
    assert.equal(svg.querySelectorAll("image,script,foreignObject,a,animate,animateTransform").length, 0);
    assert(svg.querySelector('path[fill="none"]'), "Outlined detail must not be swallowed by a solid silhouette");
  }
  const seasonalRules = [];
  for (const file of ["../web/stil.css", "../../magnolie-organizer-windows/app/web/stil.css"]) {
    const css = fs.readFileSync(path.join(__dirname, file), "utf8"), rule = css.match(/#magnolie-saison \{([^}]+)\}/)[1];
    const opacity = selector => Number(css.match(selector)[1]);
    const base = opacity(/#magnolie-saison svg \{[^}]*opacity:\s*([\d.]+)/);
    const soft = opacity(/#magnolie-saison svg\[data-season-accent="soft"\] \{\s*opacity:\s*([\d.]+)/);
    const bright = opacity(/#magnolie-saison svg\[data-season-accent="bright"\] \{\s*opacity:\s*([\d.]+)/);
    assert.equal(base, .22); assert(soft > base && bright > soft && bright <= .28, "Only a modest increase for the new accents");
    assert(!rule.includes("opacity:"), "The parent must not flatten the three opacity levels");
    seasonalRules.push([base, soft, bright]);
    assert(rule.includes("pointer-events: none"));
    assert(css.includes("@media print { #magnolie-saison, .magnolie-feiertags-schatten, #magnolie-test-hinweis { display: none !important; } }"));
  }
  assert.deepEqual(...seasonalRules);
  assert.equal(appearance.stamp("<svg>"), null);
  assert.throws(() => appearance.tray({ connected: "paired" }));
  assert.throws(() => appearance.tray({ sync: "true" }));
  assert.equal(appearance.crystal().querySelectorAll("path").length, 6);
  assert(appearance.star().querySelector("path"));
  const desktop = dom.window.document.createElement("main"); desktop.id = "schreibtisch";
  const draft = dom.window.document.createElement("textarea"); draft.value = "Unsaved original"; desktop.append(draft); dom.window.document.body.append(desktop);
  for (const [today, expected] of [["2026-12-05", null], ["2026-12-06", "crystals"], ["2026-12-30", "stars"], ["2027-01-01", "stars"], ["2027-01-02", null]]) {
    appearance.update({ today, country: "DE", developer: false, locked: false });
    const layer = desktop.querySelector("#magnolie-saison");
    assert.equal(layer?.dataset.season || null, expected);
    if (layer) {
      const motifs = [...layer.children];
      assert.equal(motifs.length, 34);
      motifs.slice(0, 28).forEach((motif, index) => {
        assert.equal(motif.dataset.seasonAccent, undefined);
        assert.equal(motif.style.left, (index * 37 % 97) + "%");
        assert.equal(motif.style.top, (index * 53 % 95) + "%");
        assert.equal(motif.style.width, [12, 18, 23, 29, 35][index % 5] + "px");
        assert.equal(motif.style.transform, "rotate(" + (index * 29 % 60) + "deg)");
      });
      assert.equal(layer.querySelectorAll('[data-season-accent="soft"]').length, 4);
      assert.equal(layer.querySelectorAll('[data-season-accent="bright"]').length, 2);
      assert.equal(new Set(motifs.map(motif => motif.style.left + ":" + motif.style.top)).size, 34);
      appearance.update({ today, country: "DE", developer: false, locked: false });
      assert.equal(desktop.querySelector("#magnolie-saison"), layer, "Repeated status updates must not redraw motifs");
    }
    assert.equal(draft.value, "Unsaved original", "Date rollover may not replace an unsaved editor");
    assert.equal(dom.window.document.body.hasAttribute("data-appearance-test"), false);
  }
  appearance.update({ today: "2026-12-10", country: "DE", developer: false, locked: false });
  assert.equal(desktop.querySelector("#magnolie-saison")?.dataset.season, "crystals");
  appearance.update({ today: "2026-12-10", country: "ES", developer: false, locked: false });
  assert.equal(desktop.querySelector("#magnolie-saison"), null);
  appearance.update({ today: "2026-12-10", country: "DE", developer: false, locked: false });
  assert.equal(desktop.querySelector("#magnolie-saison")?.dataset.season, "crystals");
  appearance.update({ today: "2026-12-10", country: "DE", developer: false, locked: true });
  assert.equal(desktop.querySelector("#magnolie-saison"), null);
  appearance.update({ today: "2026-12-10", country: "DE", developer: false, locked: false });
  assert.equal(draft.value, "Unsaved original");
  const day = dom.window.document.createElement("div");
  appearance.day(day, "2026-12-06");
  assert(day.querySelector('.magnolie-feiertags-schatten[data-appearance-watermark="boots"] [data-motif-part="candy-cane"]'));
  appearance.day(day, "2026-12-24");
  assert(day.querySelector('.magnolie-feiertags-schatten[data-appearance-watermark="santa"] [data-motif-part="smile"]'));
  assert.equal(day.querySelectorAll("[data-appearance-watermark]").length, 1);
  day.className = "wo-tag"; desktop.append(day);
  appearance.update({ today: "2025-04-26", country: "NL", developer: false, locked: false });
  appearance.day(day, "2025-04-26");
  assert(day.querySelector('[data-appearance-watermark="kings-crown"]'));
  appearance.update({ today: "2025-04-26", country: "DE", developer: false, locked: false });
  assert.equal(day.querySelectorAll("[data-appearance-watermark]").length, 0);
  appearance.update({ today: "2025-04-26", country: "NL", developer: false, locked: false });
  assert.equal(day.querySelectorAll('[data-appearance-watermark="kings-crown"]').length, 1);
  appearance.update({ today: "2025-04-26", country: "NL", developer: false, locked: true });
  assert.equal(day.querySelectorAll("[data-appearance-watermark]").length, 0);
  console.log("Appearance model PASS: actual-boolean color matrix, seasonal boundaries, Gregorian Easter, 24 isolated icon variants and passive original vector shapes.");
} finally { dom.window.close(); }
