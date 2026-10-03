"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
const roots = [path.resolve(__dirname, "../app/web")];
const linux = path.resolve(__dirname, "../../magnolie-organizer/web");
if (fs.existsSync(linux)) roots.push(linux);
for (const web of roots) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://clock.invalid/", pretendToBeVisual: true
  });
  const w = dom.window;
  w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "clockTest";
  w.webkit = { messageHandlers: { clockTest: { postMessage() {} } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  for (const file of fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js")))
    w.eval(fs.readFileSync(path.join(web, "i18n", file), "utf8"));
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")
    .replace("window.OrganizerTest = {", "window.OrganizerTest = { eingabe, oeffneCustomEintrag,"));
  w.App.init({ daten: {}, neu: false, regional: { language: "en", formatLocale: "en-US", hourCycle: "h12" } });
  const t = w.OrganizerTest;
  const native = Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype, "value");
  const locales = ["en-US", "de-DE", "fr-FR", "es-ES", "it-IT", "nl-NL", "pt-PT", "ru-RU", "cs-CZ", "pl-PL",
    "hsb-DE", "da-DK", "nb-NO", "hi-IN", "zh-CN", "ja-JP", "ar-EG", "uk-UA", "be-BY", "tr-TR"];
  for (const locale of locales) {
    w.MagnolieI18n.setLocale(locale);
    Object.assign(t.daten().einstellungen.regional, { formatLocale: locale, hourCycle: "h12" });
    const formatter = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", hourCycle: "h12" });
    for (const time of ["00:00", "00:35", "11:59", "12:00", "14:35", "23:59"]) {
      const field = t.eingabe("time", time);
      const shown = formatter.format(new Date(2000, 0, 1, Number(time.slice(0, 2)), Number(time.slice(3))));
      assert.equal(native.get.call(field), shown, locale + " visible clock");
      assert.equal(field.value, time, locale + " canonical clock");
      assert.ok(field.checkValidity());
      native.set.call(field, shown); field.dispatchEvent(new w.Event("input"));
      assert.equal(field.value, time, locale + " typed clock roundtrip");
      native.set.call(field, "02:35"); field.dispatchEvent(new w.Event("input"));
      assert.equal(field.checkValidity(), false, "missing AM/PM is not a valid 24h fallback");
      assert.ok(!/^\d{2}:\d{2}$/.test(field.value));
      field.value = ""; assert.equal(field.value, ""); assert.ok(field.checkValidity());
    }
  }
  Object.assign(t.daten().einstellungen.regional, { formatLocale: "en-US", hourCycle: "h12" });
  w.MagnolieI18n.setLocale("en");
  for (const type of ["appointments", "tasks"]) {
    const item = { id: "item", title: "Synthetic", time: "14:35", date: "2026-10-04", due: "2026-10-04", note: "" };
    const module = { id: "module", type, title: "Synthetic", items: [item] };
    t.daten().customOrganizer.modules = [module];
    t.oeffneCustomEintrag(module, item);
    const field = w.document.querySelector("#custom-eintrag-schleier .zeitfeld");
    assert.match(native.get.call(field), /PM/);
    native.set.call(field, "12:05 AM"); field.dispatchEvent(new w.Event("input", { bubbles: true }));
    w.document.querySelector(".custom-eintrag-aktionen .haupt").click();
    assert.equal(module.items[0].time, "00:05", "save uses midnight, not noon");
    assert.ok(!field.isConnected);
  }
  Object.assign(t.daten().einstellungen.regional, { hourCycle: "h23" });
  const military = t.eingabe("time", "14:35");
  assert.equal(native.get.call(military), "14:35");
  dom.window.close();
  console.log(path.relative(path.resolve(__dirname, "../.."), web) + ": 20-locale time editing passed");
}
