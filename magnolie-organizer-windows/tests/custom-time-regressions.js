"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
const roots = [path.resolve(__dirname, "../app/web")];
const linuxRoot = process.env.MAGNOLIE_LINUX_SOURCE || path.resolve(__dirname, "../../magnolie-organizer");
if (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linuxRoot)) roots.push(path.join(linuxRoot, "web"));
const invalid = "Enter both hours and minutes, or leave the time completely empty.";
const wheelHint = "Use the mouse wheel to change the time in 5-minute steps (hold Shift for whole hours)";
let cases = 0;
for (const web of roots) {
  const source = fs.readFileSync(path.join(web, "anwendung.js"), "utf8");
  const custom = source.slice(source.indexOf("  function oeffneCustomEintrag("), source.indexOf("  function zeichneCustomModul("));
  assert.ok(!custom.includes("reportValidity") && !custom.includes(".blur()"));
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://time.invalid/", pretendToBeVisual: true
  });
  const w = dom.window, d = w.document;
  w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "timeTest";
  const saves = [];
  w.webkit = { messageHandlers: { timeTest: { postMessage(text) {
    const message = JSON.parse(text);
    if (message.cmd === "speichern") saves.push(JSON.parse(message.text));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  const locales = fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"));
  assert.equal(locales.length, 19, "19 translated locales plus English source");
  for (const locale of locales) w.eval(fs.readFileSync(path.join(web, "i18n", locale), "utf8"));
  w.eval(source.replace("window.OrganizerTest = {", "window.OrganizerTest = { oeffneCustomEintrag, bindeZeitRad, eingabe, beendeModal,"));
  w.App.init({ daten: {}, neu: false, regional: { language: "de", timeZone: "UTC" } });
  const t = w.OrganizerTest;
  const plain = value => JSON.parse(JSON.stringify(value));
  const wheel = (f, deltaY = -1, shiftKey = false, consumed = true) => {
    const event = new w.WheelEvent("wheel", { deltaY, shiftKey, bubbles: true, cancelable: true });
    f.dispatchEvent(event);
    assert.equal(event.defaultPrevented, consumed);
  };
  const open = (type, time, edit = true) => {
    const old = d.querySelector("#custom-eintrag-schleier");
    if (old) { t.beendeModal(old); old.remove(); }
    const item = { id: "item", title: "Synthetic", time, date: "2026-09-13", due: "2026-09-13", note: "" };
    const module = { id: "time", type, title: "Synthetic", items: edit ? [item] : [] };
    t.daten().customOrganizer.modules = [module];
    t.oeffneCustomEintrag(module, edit ? item : null);
    return { module, item, field: d.querySelector('#custom-eintrag-schleier input[type="time"]'),
      apply: d.querySelector(".custom-eintrag-aktionen .haupt") };
  };
  for (const type of ["appointments", "tasks"]) {
    for (const edit of [false, true]) {
      for (const [start, delta, shift, direction, expected] of [
        ["09:30", -1, false, "up-earlier", "09:25"],
        ["09:30", 1, false, "up-earlier", "09:35"],
        ["09:30", -1, true, "up-earlier", "08:30"],
        ["09:30", 1, true, "up-earlier", "10:30"],
        ["09:30", -1, false, "up-later", "09:35"],
        ["00:00", -1, false, "up-earlier", "00:00"],
        ["23:55", 1, false, "up-earlier", "23:55"],
        ["", -1, false, "up-earlier", ""]
      ]) {
        const b = open(type, start, edit);
        assert.equal(b.field.value, edit ? start : t.vorgabeZeiten().zeit);
        b.field.value = start;
        t.daten().einstellungen.schrift.radRichtung = direction;
        b.field.focus(); wheel(b.field, delta, shift);
        assert.equal(b.field.value, expected);
        assert.equal(d.activeElement, b.field, "wheel preserves focus");
        b.apply.click();
        assert.ok(!b.field.isConnected);
        assert.equal(b.module.items[0].time, expected);
        if (edit) assert.equal(b.module.items[0][type === "appointments" ? "date" : "due"], "2026-09-13");
        cases++;
      }
    }
    for (const locale of ["en", ...locales.map(name => name.slice(0, -3))]) {
      w.MagnolieI18n.setLocale(locale);
      const b = open(type, "09:30"), before = plain(b.module.items);
      assert.equal(b.field.labels[0].textContent, w.MagnolieI18n.gettext("Time"));
      b.field.value = "";
      // jsdom cannot represent a native partial segment; real X11 tests cover that.
      Object.defineProperty(b.field, "validity", { configurable: true, value: { valid: false, badInput: true } });
      b.field.reportValidity = () => { throw new Error("Browser feedback is forbidden"); };
      b.field.focus(); wheel(b.field);
      assert.equal(b.field.value, "", "wheel must not invent missing segments");
      b.apply.click();
      assert.ok(b.field.isConnected);
      assert.deepEqual(plain(b.module.items), before);
      assert.equal(d.activeElement, b.field);
      const translated = w.MagnolieI18n.gettext(invalid);
      assert.equal(d.querySelector("#custom-zeit-fehler").textContent, translated);
      assert.ok(!d.querySelector("#custom-zeit-fehler").classList.contains("verborgen"));
      assert.equal(b.field.getAttribute("aria-invalid"), "true");
      if (locale !== "en") {
        assert.notEqual(translated, invalid, locale);
        assert.notEqual(w.MagnolieI18n.gettext(wheelHint), wheelHint, locale);
      }
      delete b.field.validity;
      b.field.value = "10:30";
      b.field.dispatchEvent(new w.Event("input", { bubbles: true }));
      assert.ok(d.querySelector("#custom-zeit-fehler").classList.contains("verborgen"));
      assert.ok(!b.field.hasAttribute("aria-invalid"));
      b.apply.click();
      assert.equal(b.module.items[0].time, "10:30", "correcting invalid input allows saving");
      cases++;
    }
    const b = open(type, "09:30");
    b.field.focus(); b.field.value = "10:30";
    b.field.dispatchEvent(new w.Event("input", { bubbles: true }));
    let blurred = false;
    b.field.addEventListener("blur", () => { blurred = true; });
    b.apply.click();
    assert.equal(b.module.items[0].time, "10:30");
    assert.equal(blurred, false, "Apply reads current value without depending on blur");
    t.speichereJetzt();
    assert.equal(saves.at(-1).customOrganizer.modules[0].items[0].time, "10:30");
    cases++;
  }
  // Existing four-argument calendar/old time-control contracts are unchanged.
  const field = value => {
    const f = t.eingabe("time", value);
    d.body.append(f); f.focus();
    return f;
  };
  for (const multiDay of [false, true]) {
    const start = field("09:30"), end = field("10:00");
    t.daten().einstellungen.schrift.radRichtung = "up-earlier";
    t.bindeZeitRad(start, end, null, () => multiDay);
    t.bindeZeitRad(end, null, start, () => multiDay);
    start.focus();
    wheel(start, 1, true);
    assert.equal(start.value, "10:30");
    assert.equal(end.value, multiDay ? "10:00" : "11:00");
    end.value = "08:00"; end.dispatchEvent(new w.Event("change"));
    assert.equal(end.value, multiDay ? "08:00" : "10:30");
    start.value = "11:00"; start.dispatchEvent(new w.Event("input"));
    assert.equal(end.value, multiDay ? "08:00" : "11:00");
    start.disabled = true; wheel(start, -1, false, false);
    assert.equal(start.value, "11:00");
    cases++;
  }
  const empty = field(""); t.bindeZeitRad(empty); wheel(empty);
  assert.equal(empty.value, t.vorgabeZeiten().zeit, "legacy empty wheel still supplies calendar default");
  cases++;
  for (const direction of ["up-earlier", "up-later"]) {
    t.daten().einstellungen.schrift.radRichtung = direction;
    const f = field("09:30"); t.bindeZeitRad(f);
    f.dispatchEvent(new w.WheelEvent("wheel", { deltaX: -89, deltaY: 0, shiftKey: true, cancelable: true }));
    assert.equal(f.value, direction === "up-earlier" ? "08:30" : "10:30", "native WebKit Shift axis");
    const unchanged = f.value;
    f.dispatchEvent(new w.WheelEvent("wheel", { deltaX: -89, deltaY: 0 }));
    f.dispatchEvent(new w.WheelEvent("wheel", { deltaX: 0, deltaY: 0 }));
    assert.equal(f.value, unchanged, "unmodified horizontal and zero wheel do not change time");
    cases++;
  }
  for (const type of ["appointments", "tasks"]) {
    const b = open(type, "09:30");
    b.apply.focus(); wheel(b.field, -1, false, false);
    wheel(b.field, -1, true, false);
    assert.equal(b.field.value, "09:30", "hover-only scrolling cannot edit custom time");
    b.field.focus(); b.field.readOnly = true;
    wheel(b.field, -1, false, false);
    assert.equal(b.field.value, "09:30", "read-only time cannot consume scrolling");
    cases++;
  }
  const unfocused = field("09:30"); t.bindeZeitRad(unfocused);
  field("12:00"); wheel(unfocused, -1, false, false);
  assert.equal(unfocused.value, "09:30", "shared calendar handler also requires focus");
  cases++;
  dom.window.close();
  console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": custom time and legacy contracts passed");
}
console.log(`${cases} cases passed (including feedback in all 20 app languages).`);
