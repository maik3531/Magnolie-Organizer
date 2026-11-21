/* Read-only decorative appearance. No connection, grant, sync or book writes. Refs #432. */
(() => {
  "use strict";
  // Set to true to bring back the developer-only visual preview panel (#432).
  const SHOW_DEVELOPER_PREVIEW = false;
  const ns = "http://www.w3.org/2000/svg";
  const colors = Object.freeze({ none: "#d8b25c", notes: "#ffffff", kde: "#f7d777", both: "#ee9846" });
  const petals = ["M32 34C26 26 26 16 32 9C38 16 38 26 32 34Z", "M32 34C23 32 15 26 13 17C22 17 30 24 32 34Z",
    "M32 34C41 32 49 26 51 17C42 17 34 24 32 34Z", "M32 34C24 40 21 47 22 54C28 51 32 44 32 34Z",
    "M32 34C40 40 43 47 42 54C36 51 32 44 32 34Z"];
  const shapes = Object.freeze({
    boots: [
      { d: "M48 21L51 13L53 16L56 8L58 12L63 5L63 14L68 12L65 19L70 18L67 21", fill: "none", "data-motif-part": "fir-sprig" },
      { d: "M46 22H65Q68 22 68 25V29Q65 33 61 31Q58 35 54 32Q50 34 46 31Q43 31 43 28V25Q43 22 46 22Z", fill: "none", "data-motif-part": "fur-cuff" },
      { d: "M47 32L46 58Q46 61 49 61H70Q77 61 77 55Q77 49 70 47L65 45L64 32M47 55H75", fill: "none", "data-motif-part": "boot" },
      { d: "M25 22V18A6 6 0 0 1 37 18V30H33V18A2 2 0 0 0 29 18V22ZM33 23L37 26M25 18L29 20", fill: "none", "data-motif-part": "candy-cane" },
      { d: "M20 30H39Q42 30 42 33V37Q39 41 35 39Q31 43 27 40Q23 43 20 40Q17 40 17 37V33Q17 30 20 30Z", fill: "none", "data-motif-part": "fur-cuff" },
      { d: "M21 41L20 53L12 56Q4 59 4 65Q4 71 11 71H37Q40 71 40 68L38 41M5 65H39M33 44L34 59", fill: "none", "data-motif-part": "boot" }
    ],
    santa: [
      { d: "M18 26C20 9 35 4 47 9Q57 12 64 22M51 18Q56 18 59 24", fill: "none", "data-motif-part": "winter-hat" },
      { d: "M72 26A5 5 0 1 1 62 26A5 5 0 1 1 72 26Z", "data-motif-part": "pom-pom" },
      { d: "M16 29Q36 18 57 27Q61 30 58 34Q56 37 52 35Q38 30 22 36Q16 39 14 34Q13 31 16 29Z", fill: "none", "data-motif-part": "fur-brim" },
      { d: "M19 37Q15 42 19 48Q14 55 20 60Q19 66 27 68Q30 74 38 74Q46 76 51 69Q59 68 60 61Q66 57 61 50Q63 42 57 36", fill: "none", "data-motif-part": "beard" },
      { d: "M26 42Q29 39 32 42M43 42Q46 39 49 42M34 47Q38 45 41 47Q40 51 36 50M33 58Q38 63 43 58", fill: "none", "data-motif-part": "smile" },
      { d: "M37 52Q30 47 25 55Q31 58 37 54Q44 58 51 55Q45 47 38 52Z", "data-motif-part": "moustache" },
      { d: "M22 66Q12 68 9 75M58 66Q68 68 71 75", fill: "none", "data-motif-part": "coat" }
    ],
    rocket: [
      { d: "M26 24L39 7L52 24Z", "data-motif-part": "paper-cap" },
      { d: "M29 25H49V47H29Z", fill: "none", "data-motif-part": "firework-body" },
      { d: "M30 29L48 37M30 37L48 45", fill: "none" },
      { d: "M39 48V74", fill: "none", "stroke-width": 2.8, "data-motif-part": "guide-stick" },
      { d: "M29 45C19 48 25 55 16 57", fill: "none", "data-motif-part": "fuse" },
      { d: "M12 53L9 50M11 58H6M14 62L12 66M19 61L22 64", fill: "none", "data-motif-part": "sparks" }
    ],
    glass: [
      { d: "M17 12H32L31 30C30 40 20 40 19 30Z", fill: "none", transform: "rotate(22 25 40)", "data-motif-part": "flute" },
      { d: "M25 39V63M16 65H34M20 27H30", fill: "none", transform: "rotate(22 25 40)" },
      { d: "M48 12H63L61 30C60 40 50 40 49 30Z", fill: "none", transform: "rotate(-22 55 40)", "data-motif-part": "flute" },
      { d: "M55 39V63M46 65H64M50 27H60", fill: "none", transform: "rotate(-22 55 40)" },
      { d: "M36 8L32 4M44 8L48 4M40 7V2", fill: "none", "data-motif-part": "clink" },
      { d: "M8 9L12 13M68 7L65 12M7 35L4 31L8 27M72 28L76 31L72 35M12 49L8 52M68 52L72 56", fill: "none", "data-motif-part": "confetti" },
      { d: "M18 3H21V6H18ZM60 2H63V5H60ZM3 18H6V21H3ZM74 16H77V19H74Z", "data-motif-part": "confetti" }
    ],
    eggs: [
      { d: "M25 14C18 14 11 33 11 43C11 60 39 60 39 43C39 33 32 14 25 14Z", fill: "none", "data-motif-part": "painted-egg" },
      { d: "M13 35L19 31L25 35L31 31L37 35M12 44C18 39 22 49 28 44S35 42 38 44", fill: "none", "data-motif-part": "egg-pattern" },
      { d: "M54 5C46 5 39 24 39 35C39 53 69 53 69 35C69 24 62 5 54 5Z", fill: "none", "data-motif-part": "painted-egg" },
      { d: "M42 24C48 20 60 29 66 24M40 34L47 30L54 34L61 30L68 34M44 43C50 39 58 47 64 43", fill: "none", "data-motif-part": "egg-pattern" },
      { d: "M5 67Q40 58 75 67M11 66L7 57M18 64L17 55M65 64L68 55M72 66L77 59", fill: "none", "data-motif-part": "spring-grass" },
      { d: "M38 63C25 49 21 61 38 65C55 51 59 63 41 65M38 65L30 74M41 65L49 73", fill: "none", "data-motif-part": "ribbon" }
    ]
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
    for (const shape of shapes[kind]) svg.append(element("path", { fill: "currentColor", stroke: "currentColor", "stroke-width": 2,
      "stroke-linecap": "round", "stroke-linejoin": "round", ...(kind === "rocket" ? { transform: "rotate(20 40 40)" } : {}),
      ...(typeof shape === "string" ? { d: shape } : shape) }));
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
    const t = text => window.MagnolieI18n?.gettext(text) || text;
    if (panel?.status) panel.status.textContent = result?.ok === false ? "TEST · " +
      t("Saved developer mode is required.") : nativeActive ? "TEST · " + t("OS tray icon (60 s)") : "";
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
    if (!SHOW_DEVELOPER_PREVIEW || !context.developer || context.locked) return;
    const t = translate;
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
      test.textContent = "TEST · " + t("OS tray icon (60 s)");
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
