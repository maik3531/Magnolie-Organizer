"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const vm = require("node:vm");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
const tick = () => new Promise(resolve => setImmediate(resolve));
const watchdog = setTimeout(() => { console.error("Category colors timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const labels = ["Category", "Category colors", "Custom color",
      "Category colors highlight appointments and tasks. A custom entry color takes precedence; otherwise the first matching category is used.",
      "Changing or removing a category color does not rename or delete categories on saved or imported entries.",
      "Please enter a unique category name without commas or semicolons."];
    for (const file of fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"))) {
      let catalog;
      vm.runInNewContext(fs.readFileSync(path.join(web, "i18n", file), "utf8"), { window: { MagnolieI18n: { registerCatalog: (_locale, value) => { catalog = value.messages; } } } });
      for (const label of labels) assert.ok(catalog[label] && catalog[label] !== label, file + ": missing category-color translation " + label);
    }
    const b = await harness.exports.boot(web, { termine: [{ id: "owned-appointment", datum: "2026-10-18", titel: "Owned appointment", kategorien: "Arzt,Provider", providerMetadaten: { fremd: { label: "preserved" } }, icsRoundtrip: ["X-OWNED:preserved"] }],
      aufgaben: [{ id: "owned-task", titel: "Owned task", faellig: "2026-10-18", kategorien: "Arzt", icsRoundtrip: ["CATEGORIES:Arzt", "X-OWNED:task"] }] });
    try {
      if (b.saves().length) b.ack(); await tick();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      let sequence = 0;
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
      };
      async function rpc(method, params) {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "a".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation).response;
      }
      const call = async (name, args = {}) => (await rpc("tools/call", { name, arguments: args })).result;
      const ok = result => { assert.equal(result?.isError, false, JSON.stringify(result)); return result.structuredContent; };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "owned-category-colors", version: "1" } }); await rpc("notifications/initialized", {});
      const before = JSON.stringify(b.t.daten().termine[0]);
      const initial = ok(await call("organizer_category_colors_read")); assert.equal(initial.colors.length, 0);
      const saved = ok(await call("organizer_category_colors_update", { expected_revision: initial.revision, colors: [{ name: "Arzt", color: "#3366AA" }, { name: "Urlaub", color: "#ff9900" }] }));
      assert.equal(saved.persisted, true); assert.equal(saved.count, 2); assert.equal(JSON.stringify(b.t.daten().termine[0]), before);
      const palette = ok(await call("organizer_category_colors_read")); assert.equal(palette.colors[0].color, "#3366aa");
      Object.assign(b.t.zustand().kalender, { jahr: 2026, monat: 9, tag: "2026-10-18", ansicht: "day" });
      await b.t.wechsel("planer"); await b.t.wechsel("kalender");
      assert.equal(b.w.document.querySelector(".tages-termin").dataset.akzentFarbe, "#3366aa", "category color applies before any explicit override");
      const stale = await call("organizer_category_colors_update", { expected_revision: initial.revision, colors: [] }); assert.equal(stale.structuredContent.code, "conflict");
      const duplicate = await call("organizer_category_colors_update", { expected_revision: palette.revision, colors: [{ name: "Arzt", color: "#000000" }, { name: "ARZT", color: "#ffffff" }] }); assert.equal(duplicate.structuredContent.code, "invalid_selection");
      const task = ok(await call("organizer_task_read", { id: "owned-task" }));
      ok(await call("organizer_task_update", { id: "owned-task", expected_revision: task.revision, categories: "Urlaub", accent_color: "#ff0000" }));
      assert.equal(b.t.daten().aufgaben[0].akzentFarbe, "#ff0000"); assert.equal(b.t.daten().aufgaben[0].kategorien, "Urlaub");
      assert.ok(b.t.daten().aufgaben[0].icsRoundtrip.includes("X-OWNED:task"));
      const appointment = ok(await call("organizer_appointment_read", { id: "owned-appointment" }));
      ok(await call("organizer_appointment_update", { id: "owned-appointment", expected_revision: appointment.revision, accent_color: "#112233" }));
      assert.equal(b.t.daten().termine[0].akzentFarbe, "#112233"); assert.equal(b.t.daten().termine[0].kategorien, "Arzt,Provider");
      assert.equal(b.t.daten().termine[0].providerMetadaten.fremd.label, "preserved");
      const month = b.t.planerMonatsModell(2026, 9);
      const day = month.wochen.flatMap(week => week.tage).find(day => day.iso === "2026-10-18");
      assert.equal(day.eintraege.find(item => item.art === "termin").farbe, "#112233");
      assert.equal(day.eintraege.find(item => item.art === "aufgabe").farbe, "#ff0000");
      const monthHtml = b.t.planerDruckSeite(month);
      assert.match(monthHtml, /background:#112233;color:#ffffff/);
      assert.match(monthHtml, /background:#ff0000;color:#000000/);
      const monthOds = b.t.planerOdsNutzlast(month);
      assert.ok(monthOds.inhalte.flat().some(cell => cell.eintraege.some(item => item.art === "aufgabe" && item.akzent && item.farbe === "#ff0000")));
      const year = b.t.planerKalenderModell(2026);
      assert.equal(year.zeilen[17][9].akzente.length, 2);
      assert.match(b.t.planerDruckSeite(year), /background:#112233;color:#ffffff/);
      assert.ok(b.t.planerOdsNutzlast(year).inhalte[17][9].eintraege.some(item => item.akzent && item.farbe === "#ff0000"));
      for (const [section, color] of [["aufgaben", "#ff0000"], ["kalender", "#112233"]]) {
        const cards = b.t.druckStoff(section, null, { jahr: 2026, monat: 9 });
        assert.ok(cards.liste.length);
        assert.equal(cards.karte(cards.liste[0]).querySelector(".dk-name").dataset.akzentFarbe, color);
        assert.ok(b.t.druckSeite(cards.liste, cards).includes("background-color:" + color));
      }
      for (const view of ["month", "week", "day"]) {
        Object.assign(b.t.zustand().kalender, { jahr: 2026, monat: 9, tag: "2026-10-18", ansicht: view });
        await b.t.wechsel("planer"); await b.t.wechsel("kalender");
        assert.ok(b.w.document.querySelector(view === "day" ? ".tages-spalte" : view === "week" ? ".wo-tag" : ".kal-tag"), view + " must actually be drawn");
        const bar = b.w.document.querySelector('.mini-farbaufgabe[data-aufgabe-id="owned-task"]');
        assert.ok(bar, view + " must render colored tasks");
        assert.equal(bar.style.backgroundColor, "rgb(255, 0, 0)");
        assert.equal(bar.style.color, "rgb(0, 0, 0)");
      }
      const persisted = JSON.parse(b.saves().at(-1).text);
      assert.equal(persisted.einstellungen.kalender.kategorieFarben[0].farbe, "#3366aa");
      const recordsBeforeRemoval = JSON.stringify([b.t.daten().termine, b.t.daten().aufgaben]);
      ok(await call("organizer_category_colors_update", { expected_revision: palette.revision, colors: [] }));
      assert.equal(JSON.stringify([b.t.daten().termine, b.t.daten().aufgaben]), recordsBeforeRemoval, "removing color definitions must retain saved categories and provider data");
      persisted.aufgaben.push({ id: "legacy-category", titel: "Legacy", icsRoundtrip: ["CATEGORIES:Arzt", "X-MAGNOLIE-ACCENT-COLOR:#3366AA"] },
        { id: "cleared-category", titel: "Cleared", kategorien: "", akzentFarbe: "", icsRoundtrip: ["CATEGORIES:Arzt", "X-MAGNOLIE-ACCENT-COLOR:#3366AA"] });
      persisted.termine.push({ id: "readonly-category", datum: "2026-10-19", titel: "Read-only", kategorien: "Arzt", icsReadOnly: true,
        kalenderQuelle: { id: "owned-readonly-source", name: "Owned source", farbe: "#789abc" } });
      const reload = await harness.exports.boot(web, persisted);
      try {
        assert.equal(reload.t.daten().aufgaben[0].kategorien, "Urlaub"); assert.equal(reload.t.daten().termine[0].akzentFarbe, "#112233");
        const legacy = reload.t.daten().aufgaben.find(item => item.id === "legacy-category");
        assert.equal(legacy.kategorien, "Arzt"); assert.equal(legacy.akzentFarbe, "#3366aa");
        const cleared = reload.t.daten().aufgaben.find(item => item.id === "cleared-category");
        assert.equal(cleared.kategorien, ""); assert.equal(cleared.akzentFarbe, "");
        const readonly = reload.t.daten().termine.find(item => item.id === "readonly-category");
        const beforeReadonly = JSON.stringify(readonly);
        Object.assign(reload.t.zustand().kalender, { jahr: 2026, monat: 9, tag: "2026-10-19", ansicht: "day" });
        await reload.t.wechsel("planer"); await reload.t.wechsel("kalender");
        const readonlyBar = reload.w.document.querySelector(".tages-termin");
        assert.equal(readonlyBar.dataset.akzentFarbe, "#3366aa");
        assert.equal(readonlyBar.style.borderLeftColor, "rgb(120, 154, 188)");
        reload.t.oeffneTerminBlatt(readonly, readonly.datum);
        assert.ok(reload.w.document.querySelector("#tb-kategorien").disabled);
        assert.ok(reload.w.document.querySelector("#tb-eigene-farbe").disabled);
        assert.equal(JSON.stringify(readonly), beforeReadonly);
        reload.w.document.querySelector("#tb-fertig").click();
        reload.t.zustand().aufgaben.bearbeiteId = "owned-task"; reload.t.wechsel("aufgaben");
        reload.input("#aufgabe-kategorien", "Arzt");
        const custom = reload.w.document.querySelector("#aufgabe-eigene-farbe");
        custom.checked = false; custom.dispatchEvent(new reload.w.Event("change", { bubbles: true }));
        assert.equal(reload.t.daten().aufgaben[0].kategorien, "Urlaub", "typing must remain a draft");
        [...reload.w.document.querySelectorAll(".form-knoepfe button")].find(button => button.textContent === "Save changes").click();
        assert.equal(reload.t.daten().aufgaben[0].kategorien, "Arzt");
        assert.equal(reload.t.daten().aufgaben[0].akzentFarbe, "");
      } finally { reload.close(); }
      console.log("CATEGORY COLORS PASS: shared palette CAS/native SaveACK, record colors/categories, provider/raw ICS preservation, actual serialized reload " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
