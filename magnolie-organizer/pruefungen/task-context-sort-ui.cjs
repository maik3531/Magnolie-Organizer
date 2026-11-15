"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const canonicalHarness = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harnessPath = fs.existsSync(canonicalHarness) ? canonicalHarness : path.resolve(__dirname, "../../../tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module); harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", harnessPath);
const tick = () => new Promise(resolve => setImmediate(resolve));
const tasks = (done = false) => [
  { id: "a" + done, uid: "a" + done, titel: "A" + done, prio: 3, faellig: "2030-02-01", angelegt: 100, reihenfolge: 0, erledigt: done },
  { id: "b" + done, uid: "b" + done, titel: "B" + done, prio: 1, faellig: "2030-03-01", angelegt: 300, reihenfolge: 1, erledigt: done },
  { id: "c" + done, uid: "c" + done, titel: "C" + done, prio: 2, faellig: "2030-01-01", angelegt: 200, reihenfolge: 2, erledigt: done }
];
(async () => {
  let cases = 0;
  for (const web of harness.exports.roots) {
    const b = await harness.exports.boot(web, { aufgaben: [...tasks(), ...tasks(true)] });
    try {
      await b.t.wechsel("aufgaben"); const d = b.w.document;
      const before = JSON.stringify(b.t.daten()), saves = b.saves().length, messages = b.messages.length;
      const menu = (node = d.querySelector("#aufgaben-uebersicht"), keyboard = false) => {
        node.dispatchEvent(keyboard ? new b.w.KeyboardEvent("keydown", { key: "F10", shiftKey: true, bubbles: true, cancelable: true }) :
          new b.w.MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 30, clientY: 40 }));
        assert(d.querySelector("#vorschlags-menue"));
      };
      const choose = async key => { menu(); d.querySelector(`[data-aufgaben-ansicht="${key}"]`).click(); await tick(); await tick(); };
      const visible = done => [...d.querySelectorAll(`#aufgaben-uebersicht li.zeile${done ? ".erledigt" : ":not(.erledigt)"} .obm`)].map(n => n.textContent);
      const orders = { due_asc: ["C", "A", "B"], due_desc: ["B", "A", "C"], priority_asc: ["B", "C", "A"],
        priority_desc: ["A", "C", "B"], created_asc: ["A", "C", "B"], created_desc: ["B", "C", "A"] };
      for (const includeDone of [true, false]) {
        if (!includeDone) await choose("completed");
        for (const [key, order] of Object.entries(orders)) {
          await choose(key);
          assert.deepEqual(visible(false), order.map(x => x + "false"));
          assert.deepEqual(visible(true), includeDone ? order.map(x => x + "true") : []);
          menu(d.querySelector("#aufgaben-uebersicht li .haupt"), true);
          assert.equal(d.querySelector(`[data-aufgaben-ansicht="${key}"]`).getAttribute("aria-checked"), "true");
          assert.equal(d.querySelector('[data-aufgaben-ansicht="completed"]').getAttribute("aria-checked"), String(includeDone));
          d.querySelector("#vorschlags-menue").dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          cases++;
        }
      }
      await choose("manual"); assert.deepEqual(visible(false), ["Afalse", "Bfalse", "Cfalse"]);
      await choose("completed"); assert.equal(visible(true).length, 3);
      assert.equal(JSON.stringify(b.t.daten()), before); assert.equal(b.saves().length, saves); assert.equal(b.messages.length, messages);
      menu();
      for (const [key, selected] of [["End", "completed"], ["Home", "manual"], ["ArrowUp", "completed"], ["ArrowDown", "manual"]]) {
        d.querySelector("#vorschlags-menue").dispatchEvent(new b.w.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
        assert.equal(d.activeElement.dataset.aufgabenAnsicht, selected);
      }
      d.querySelector("#vorschlags-menue").dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); cases++;
      b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); b.w.MagnolieI18n.setLocale("de"); menu();
      assert(d.querySelector('[data-aufgaben-ansicht="due_asc"]').textContent.includes("Fällig am ↑"));
      assert(d.querySelector('[data-aufgaben-ansicht="priority_desc"]').textContent.includes("Priorität ↓"));
      assert(d.querySelector('[data-aufgaben-ansicht="created_asc"]').textContent.includes("Erstellt ↑"));
      d.querySelector("#vorschlags-menue").dispatchEvent(new b.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); cases++;
      const text = d.querySelector("#aufgaben-uebersicht .obm"), range = d.createRange(); range.selectNodeContents(text);
      b.w.getSelection().removeAllRanges(); b.w.getSelection().addRange(range);
      text.dispatchEvent(new b.w.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
      assert.equal(d.querySelector("[data-aufgaben-ansicht]"), null); b.w.getSelection().removeAllRanges(); cases++;
      // Editing fields must retain their existing edit/spelling context menu.
      const input = d.querySelector("#aufgabe-titel"); input.dispatchEvent(new b.w.MouseEvent("contextmenu", { bubbles: true, cancelable: true }));
      assert.equal(d.querySelector("[data-aufgaben-ansicht]"), null); cases++;
    } finally { b.close(); }
    const h = await harness.exports.boot(web, { aufgaben: [
      { id: "parent", uid: "parent", titel: "Parent", prio: 3, reihenfolge: 0, angelegt: 300 },
      { id: "child-b", uid: "child-b", elternUid: "parent", titel: "Child B", prio: 2, reihenfolge: 0, angelegt: 200 },
      { id: "child-a", uid: "child-a", elternUid: "parent", titel: "Child A", prio: 1, reihenfolge: 1, angelegt: 100 },
      { id: "other", uid: "other", titel: "Other", prio: 1, reihenfolge: 1, angelegt: 200 }
    ] });
    try {
      await h.t.wechsel("aufgaben"); const d = h.w.document, before = JSON.stringify(h.t.daten().aufgaben);
      d.querySelector("#aufgaben-uebersicht").dispatchEvent(new h.w.MouseEvent("contextmenu", { bubbles: true }));
      d.querySelector('[data-aufgaben-ansicht="priority_asc"]').click(); await tick(); await tick();
      assert.deepEqual([...d.querySelectorAll("#aufgaben-uebersicht .obm")].map(n => n.textContent), ["Other", "Parent", "Child A", "Child B"]);
      assert.deepEqual([...d.querySelectorAll("#aufgaben-uebersicht li.zeile")].map(n => n.getAttribute("aria-level")), ["1", "1", "2", "2"]);
      assert.equal(JSON.stringify(h.t.daten().aufgaben), before); cases++;
    } finally { h.close(); }
    const legacy = await harness.exports.boot(web, { aufgaben: [
      { id: "missing", uid: "missing", titel: "Missing", reihenfolge: 0 },
      { id: "known-b", uid: "known-b", titel: "Known B", reihenfolge: 1 },
      { id: "known-a", uid: "known-a", titel: "Known A", reihenfolge: 2 }
    ] });
    try {
      const values = legacy.t.daten().aufgaben;
      for (const task of values) { task.faellig = task.id === "missing" ? "" : "2030-01-01";
        task.angelegt = task.id === "missing" ? 0 : task.id === "known-a" ? 100 : 200; }
      await legacy.t.wechsel("aufgaben"); const d = legacy.w.document, before = JSON.stringify(legacy.t.daten());
      for (const key of ["due_asc", "due_desc", "created_asc", "created_desc"]) {
        d.querySelector("#aufgaben-uebersicht").dispatchEvent(new legacy.w.MouseEvent("contextmenu", { bubbles: true }));
        d.querySelector(`[data-aufgaben-ansicht="${key}"]`).click(); await tick(); await tick();
        const order = [...d.querySelectorAll("#aufgaben-uebersicht .obm")].map(n => n.textContent);
        assert.deepEqual(order, key === "created_desc" ? ["Known B", "Known A", "Missing"] : ["Known A", "Known B", "Missing"]);
        assert.equal(JSON.stringify(legacy.t.daten()), before); cases++;
      }
    } finally { legacy.close(); }
    const empty = await harness.exports.boot(web, {});
    try {
      await empty.t.wechsel("aufgaben"); const d = empty.w.document;
      d.querySelector("#aufgaben-uebersicht").dispatchEvent(new empty.w.KeyboardEvent("keydown", { key: "ContextMenu", bubbles: true }));
      assert.equal(d.querySelectorAll("[data-aufgaben-ansicht]").length, 8);
      d.querySelector('[data-aufgaben-ansicht="completed"]').click(); await tick(); assert.equal(empty.t.daten().aufgaben.length, 0); cases++;
    } finally { empty.close(); }
  }
  console.log(`PASS ${cases} task context sort UI cases across both desktop projections`);
})().catch(error => { console.error(error); process.exitCode = 1; });
