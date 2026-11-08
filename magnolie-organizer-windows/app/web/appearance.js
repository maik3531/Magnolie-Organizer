/* Read-only decorative appearance. No connection, grant, sync or book writes. Refs #432. */
(() => {
  "use strict";
  const ns = "http://www.w3.org/2000/svg";
  const colors = Object.freeze({ none: "#d8b25c", notes: "#ffffff", kde: "#f7d777", both: "#ee9846" });
  const petals = ["M32 34C26 26 26 16 32 9C38 16 38 26 32 34Z", "M32 34C23 32 15 26 13 17C22 17 30 24 32 34Z",
    "M32 34C41 32 49 26 51 17C42 17 34 24 32 34Z", "M32 34C24 40 21 47 22 54C28 51 32 44 32 34Z",
    "M32 34C40 40 43 47 42 54C36 51 32 44 32 34Z"];
  const shapes = Object.freeze({
    boots: ["M12 9H29L28 37C31 41 43 42 44 49V55H10V44L14 36Z", "M44 7H61L60 35C63 39 75 40 76 47V53H42V42L46 34Z"],
    santa: ["M19 26Q24 3 48 8L66 24L56 28Q32 17 19 26Z", "M19 29Q36 22 57 29L60 39L53 49L40 68L24 52L17 40Z", "M60 20A6 6 0 1 0 72 20A6 6 0 1 0 60 20"],
    rocket: ["M36 8Q57 22 56 45L40 56L24 45Q23 23 36 8Z", "M24 33L13 49L24 47M56 33L67 49L56 47", "M31 55L31 71L40 63L47 73L49 55"],
    glass: ["M24 8H56L52 34Q40 49 28 34ZM40 43V65M27 69H53", "M28 25H52"],
    eggs: ["M26 22C9 26 6 54 22 60C40 65 44 35 26 22Z", "M53 8C34 14 34 43 51 45C70 46 72 16 53 8Z", "M59 40C40 45 42 70 60 71C78 69 78 46 59 40Z"]
  });
  function element(name, attrs = {}) {
    const result = document.createElementNS(ns, name);
    for (const [key, value] of Object.entries(attrs)) result.setAttribute(key, String(value));
    return result;
  }
  function dateParts(iso) {
    if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
    const [year, month, day] = iso.split("-").map(Number);
    if (year < 1583 || year > 9999) return null;
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? { year, month, day, date } : null;
  }
  function easter(year) {
    const a = year % 19, b = Math.floor(year / 100), c = year % 100, d = Math.floor(b / 4), e = b % 4;
    const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
    const n = h + l - 7 * m + 114;
    return new Date(Date.UTC(year, Math.floor(n / 31) - 1, n % 31 + 1));
  }
  function season(iso) {
    const value = dateParts(iso); if (!value) return "none";
    if (value.month === 12 && value.day >= 30 || value.month === 1 && value.day === 1) return "stars";
    return value.month === 12 && value.day >= 6 ? "crystals" : "none";
  }
  function holiday(iso) {
    const value = dateParts(iso); if (!value) return "none";
    const key = value.month + "-" + value.day;
    const fixed = { "12-6": "boots", "12-24": "santa", "12-31": "rocket", "1-1": "glass" }[key];
    if (fixed) return fixed;
    const delta = value.date.getTime() - easter(value.year).getTime();
    return delta === 0 || delta === 86400000 ? "eggs" : "none";
  }
  function connection(notes, kde) {
    return notes === true ? kde === true ? "both" : "notes" : kde === true ? "kde" : "none";
  }
  function tray({ connected = "none", sync = false, mode = "flower" } = {}) {
    if (!Object.hasOwn(colors, connected) || !["flower", "camera", "phone"].includes(mode) || typeof sync !== "boolean") throw new TypeError("invalid_appearance_preview");
    const svg = element("svg", { viewBox: "0 0 256 256", width: 128, height: 128, "aria-hidden": "true", focusable: "false" });
    const color = colors[connected];
    if (mode === "phone") {
      svg.append(element("rect", { x: 57, y: 10, width: 142, height: 236, rx: 23, fill: "#55291c", stroke: "#d8b25c", "stroke-width": 6 }),
        element("rect", { x: 68, y: 34, width: 120, height: 183, rx: 6, fill: "#e9ddbd" }),
        element("path", { d: "M108 23H148M119 232H137", fill: "none", stroke: "#d8b25c", "stroke-width": 5, "stroke-linecap": "round" }));
    } else {
      svg.append(element("rect", { x: 40, y: 28, width: 196, height: 202, rx: 12, fill: "#e9ddbd", stroke: "#b8a87f", "stroke-width": 2 }),
        element("rect", { x: 20, y: 16, width: 200, height: 222, rx: 16, fill: "#55291c", stroke: "#2b140c", "stroke-width": 3 }),
        element("rect", { x: 42, y: 36, width: 158, height: 182, rx: 9, fill: "none", stroke: "#d8b25c", "stroke-width": 4 }));
    }
    if (mode === "camera") {
      const group = element("g", { "data-appearance-shape": "camera", stroke: color, "stroke-width": 6, fill: "none", "stroke-linejoin": "round" });
      group.append(element("path", { d: "M72 104H98L108 87H140L150 104H174V163H72Z" }), element("circle", { cx: 123, cy: 132, r: 19 })); svg.append(group);
    } else {
      const group = element("g", { "data-appearance-shape": "flower", transform: "translate(121,127.5) scale(1.9) translate(-32,-32)", fill: "none", stroke: color,
        "stroke-width": 2.6, "stroke-linejoin": "round", "stroke-linecap": "round" });
      for (const d of petals) group.append(element("path", { d })); svg.append(group);
    }
    if (sync) svg.append(element("path", { "data-appearance-shape": "sync", d: "M59 114A67 67 0 0 1 176 82M176 65V95L149 85M183 143A67 67 0 0 1 66 175M66 193V163L93 173",
      fill: "none", stroke: "#f7d777", "stroke-width": 9, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    svg.dataset.connection = connected; svg.dataset.mode = mode; return svg;
  }
  function stamp(kind) {
    if (!Object.hasOwn(shapes, kind)) return null;
    const svg = element("svg", { viewBox: "0 0 80 80", "aria-hidden": "true", focusable: "false" });
    svg.dataset.appearanceWatermark = kind;
    for (const d of shapes[kind]) svg.append(element("path", { d, fill: "currentColor", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    return svg;
  }
  function crystal() {
    const svg = element("svg", { viewBox: "0 0 80 80", "aria-hidden": "true", focusable: "false" });
    for (let angle = 0; angle < 360; angle += 60) svg.append(element("path", { d: "M40 40V6M40 16L30 9M40 16L50 9M40 27L26 17M40 27L54 17",
      transform: "rotate(" + angle + " 40 40)", fill: "none", stroke: "currentColor", "stroke-width": 2.2, "stroke-linecap": "round" }));
    return svg;
  }
  function star() {
    const svg = element("svg", { viewBox: "0 0 80 80", "aria-hidden": "true", focusable: "false" });
    svg.append(element("path", { d: "M40 5L49 29L75 30L55 47L62 73L40 58L18 73L25 47L5 30L31 29Z", fill: "currentColor" })); return svg;
  }
  let context = { today: "", developer: false, locked: true };
  const defaults = () => ({ connected: "auto", mode: "auto", sync: false, season: "auto", holiday: "auto", date: "" });
  let preview = defaults(), panel = null, backgroundKey = "", nativeActive = false, nativeSender = null;
  function stopNative() { if (nativeActive) nativeSender?.(null); nativeActive = false; }
  function nativeResult(result) {
    nativeActive = context.developer && !context.locked && result?.ok === true && result?.active === true;
    if (panel?.status) panel.status.textContent = result?.ok === false ? "TEST · " +
      (document.documentElement.lang.startsWith("de") ? "Nur mit gespeichertem Entwicklermodus verfügbar." : "Saved developer mode is required.") : nativeActive ? "TEST · OS tray · 60 s" : "";
    apply();
  }
  function simulated() { return context.developer && !context.locked && (nativeActive || Object.keys(preview).some(key => preview[key] !== defaults()[key])); }
  function day(node, iso) {
    node.dataset.appearanceDate = iso;
    node.querySelectorAll(":scope > [data-appearance-watermark]").forEach(old => old.remove());
    if (context.locked) return;
    const kind = simulated() && preview.holiday !== "auto" ? preview.holiday : holiday(iso);
    const image = stamp(kind);
    if (image) { image.classList.add("magnolie-feiertags-schatten"); node.append(image); }
  }
  function apply() {
    const test = simulated(), date = test && preview.date || context.today;
    const backdrop = context.locked ? "none" : test && preview.season !== "auto" ? preview.season : season(date);
    const desktop = document.querySelector("#schreibtisch");
    const key = backdrop + ":" + test;
    if (desktop && (key !== backgroundKey || backdrop !== "none" && !desktop.querySelector("#magnolie-saison"))) {
      desktop.querySelector("#magnolie-saison")?.remove(); backgroundKey = key;
      if (backdrop !== "none") {
        const layer = document.createElement("div"); layer.id = "magnolie-saison"; layer.setAttribute("aria-hidden", "true"); layer.dataset.season = backdrop;
        for (let index = 0; index < 28; index++) {
          const image = backdrop === "stars" ? star() : crystal();
          image.style.left = (index * 37 % 97) + "%"; image.style.top = (index * 53 % 95) + "%";
          image.style.width = [12, 18, 23, 29, 35][index % 5] + "px"; image.style.transform = "rotate(" + (index * 29 % 60) + "deg)";
          layer.append(image);
        }
        desktop.prepend(layer);
      }
    }
    document.body.toggleAttribute("data-appearance-test", test);
    let badge = document.querySelector("#magnolie-test-hinweis");
    if (test && !badge) {
      badge = document.createElement("span"); badge.id = "magnolie-test-hinweis"; badge.setAttribute("role", "status");
      badge.textContent = "TEST · " + (window.MagnolieI18n?.gettext("Preview") || "Preview"); document.body.append(badge);
    } else if (!test) badge?.remove();
    for (const node of document.querySelectorAll(".wo-tag[data-appearance-date]")) day(node, node.dataset.appearanceDate);
    if (panel && (!panel.attached || panel.root.isConnected)) {
      panel.attached ||= panel.root.isConnected;
      panel.icon.replaceChildren(tray({ connected: preview.connected === "auto" ? "none" : preview.connected,
        mode: preview.mode === "auto" ? "flower" : preview.mode, sync: preview.sync }));
      panel.sample.replaceChildren();
      const image = stamp(preview.holiday === "auto" ? holiday(date) : preview.holiday);
      if (image) panel.sample.append(image);
    } else panel = null;
  }
  function update({ today, developer, locked }) {
    context = { today: dateParts(today) ? today : "", developer: developer === true, locked: locked !== false };
    if (!context.developer || context.locked) { stopNative(); nativeSender = null; preview = defaults(); panel = null; }
    apply();
  }
  function mountDeveloper(root, translate, sendNative = null) {
    if (!context.developer || context.locked) return;
    const german = { "Visual test only; no connections or permissions are changed.": "Nur ein Darstellungstest; Verbindungen und Berechtigungen bleiben unverändert.",
      "Tray preview": "Tray-Vorschau", "Seasonal background": "Saisonaler Hintergrund", "Holiday watermark": "Feiertags-Wasserzeichen",
      "Both connected": "Beide verbunden", "Camera": "Kamera", "Snowflakes": "Eiskristalle", "Stars": "Sterne", "Boots": "Stiefel",
      "Santa Claus": "Weihnachtsmann", "Rocket": "Rakete", "Champagne glass": "Sektglas", "Easter eggs": "Ostereier", "Reset preview": "Vorschau zurücksetzen" };
    const t = text => { const value = translate(text); return value !== text ? value : document.documentElement.lang.startsWith("de") ? german[text] || text : text; };
    const section = document.createElement("section"); section.className = "magnolie-darstellungstest"; section.id = "entwickler-darstellung";
    const heading = document.createElement("h3"); heading.textContent = "TEST · " + t("Preview");
    const hint = document.createElement("p"); hint.className = "einst-hinweis"; hint.textContent = t("Visual test only; no connections or permissions are changed.");
    section.append(heading, hint);
    function changed() { if (section.isConnected && context.developer && !context.locked) apply(); }
    function select(key, title, choices) {
      const label = document.createElement("label"), input = document.createElement("select");
      label.className = "formzeile"; label.append(document.createTextNode(t(title))); input.className = "feld"; input.dataset.appearanceTest = key;
      for (const [value, text] of choices) { const option = document.createElement("option"); option.value = value; option.textContent = t(text); input.append(option); }
      input.value = preview[key]; input.addEventListener("change", () => {
        if (!section.isConnected || !context.developer || context.locked || !choices.some(([value]) => value === input.value)) return;
        preview[key] = input.value; changed();
      }); label.append(input); section.append(label);
    }
    select("connected", "Tray preview", [["auto", "Automatic"], ["none", "None"], ["notes", "Notes"], ["kde", "KDE Connect"], ["both", "Both connected"]]);
    select("mode", "Phone", [["auto", "Automatic"], ["flower", "Magnolie"], ["camera", "Camera"], ["phone", "Phone"]]);
    const syncRow = document.createElement("label"), sync = document.createElement("input"); sync.type = "checkbox"; sync.checked = preview.sync;
    sync.dataset.appearanceTest = "sync"; syncRow.className = "hak"; syncRow.append(sync, document.createTextNode(" " + t("Synchronization")));
    sync.addEventListener("change", () => { if (section.isConnected && context.developer && !context.locked) { preview.sync = sync.checked; changed(); } }); section.append(syncRow);
    select("season", "Seasonal background", [["auto", "Automatic"], ["none", "None"], ["crystals", "Snowflakes"], ["stars", "Stars"]]);
    select("holiday", "Holiday watermark", [["auto", "Automatic"], ["none", "None"], ["boots", "Boots"], ["santa", "Santa Claus"], ["rocket", "Rocket"], ["glass", "Champagne glass"], ["eggs", "Easter eggs"]]);
    const dateRow = document.createElement("label"), date = document.createElement("input"); date.type = "date"; date.className = "feld"; date.value = preview.date;
    date.dataset.appearanceTest = "date"; dateRow.className = "formzeile"; dateRow.append(document.createTextNode(t("Date")), date); section.append(dateRow);
    date.addEventListener("change", () => {
      if (!section.isConnected || !context.developer || context.locked || date.value && !dateParts(date.value)) return;
      preview.date = date.value; changed();
    });
    const samples = document.createElement("div"), icon = document.createElement("div"), sample = document.createElement("div");
    samples.className = "magnolie-testmuster"; icon.dataset.appearanceSample = "tray"; sample.dataset.appearanceSample = "watermark";
    samples.append(icon, sample); section.append(samples);
    const reset = document.createElement("button"); reset.type = "button"; reset.className = "knopf klein"; reset.textContent = t("Reset preview");
    reset.addEventListener("click", () => {
      if (!section.isConnected || !context.developer || context.locked) return;
      stopNative(); preview = defaults();
      for (const input of section.querySelectorAll("[data-appearance-test]")) {
        if (input.type === "checkbox") input.checked = false; else input.value = preview[input.dataset.appearanceTest];
      }
      changed();
    }); section.append(reset);
    const status = document.createElement("p"); status.className = "einst-hinweis"; status.dataset.appearanceNativeStatus = "true"; status.setAttribute("role", "status");
    if (typeof sendNative === "function") {
      nativeSender = sendNative;
      const test = document.createElement("button"); test.type = "button"; test.className = "knopf klein"; test.dataset.appearanceNative = "true";
      test.textContent = document.documentElement.lang.startsWith("de") ? "TEST · OS-Tray-Symbol (60 s)" : "TEST · OS tray icon (60 s)";
      test.addEventListener("click", () => {
        if (!section.isConnected || !context.developer || context.locked) return;
        nativeActive = true;
        sendNative({ connection: preview.connected === "auto" ? "none" : preview.connected,
          mode: preview.mode === "auto" ? "flower" : preview.mode, sync: preview.sync });
        changed();
      }); section.append(test, status);
    }
    root.append(section); panel = { root: section, icon, sample, status, attached: false }; apply();
  }
  // Only the explicit OS-test button calls a supplied visual-only bridge callback.
  // Ordinary preview selectors never call native APIs or persist anything.
  window.MagnolieAppearance = Object.freeze({ connection, season, holiday, tray, stamp, crystal, star, update, day, mountDeveloper, nativeResult });
})();
