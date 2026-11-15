"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 10));
async function check(web, failure) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window, d = w.document, messages = [];
  let hold = false;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: raw => {
    const m = JSON.parse(raw); messages.push(m);
    if (m.cmd === "speichern" && !hold) queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
  } } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    d.dispatchEvent(new w.Event("DOMContentLoaded"));
    w.App.init({ daten: {}, neu: false, regional: { language: "en" }, handbuchInstalliert: true, handbuchVersion: "2.0.30" });
    d.querySelector("#knopf-einstellungen").click(); d.querySelector("#einst-tab-ueber").click();
    w.App.updateErgebnis({ ok: true, aktuell: false, windows: true, version: "99.0.0",
      url: "https://example.invalid/update.exe", sha256: "a".repeat(64) });
    await tick(); hold = true;
    const originalButton = d.querySelector("#update-herunterladen");
    originalButton.click(); d.querySelector("#dialog-ja").click();
    await tick();
    const busy = () => {
      assert.match(d.querySelector("#update-stand").textContent, /Please wait/);
      assert.equal(d.querySelector("#update-stand").getAttribute("role"), "status");
      assert.equal(d.querySelector("#update-herunterladen").disabled, true);
      assert.equal(d.querySelector("#update-pruefen").disabled, true);
    };
    busy();
    assert.equal(messages.filter(m => m.cmd === "update_herunterladen").length, 0, "Must wait for durable save ACK");
    d.querySelector("#einst-tab-ueber").click(); busy();
    originalButton.click();
    d.querySelector("#update-herunterladen").click();
    assert.ok(d.querySelector("#dialog-schleier").classList.contains("verborgen"), "No second confirmation while busy");
    const save = messages.filter(m => m.cmd === "speichern").at(-1);
    assert.ok(save);
    w.App.gespeichert({ id: save.id, ok: failure !== "save", fehler: "save rejected" });
    for (let i = 0; i < 50 && failure !== "save" && !messages.some(m => m.cmd === "update_herunterladen"); i++) await tick();
    if (failure !== "save") {
      assert.equal(messages.filter(m => m.cmd === "update_herunterladen").length, 1); busy();
      w.App.updateHeruntergeladen({ ok: failure !== "download", bereit: failure !== "download", fehler: "download rejected" });
      if (failure !== "download") {
        busy(); assert.equal(messages.filter(m => m.cmd === "update_installieren").length, 1);
        w.App.updateInstallationVorbereitet({ ok: failure !== "install", bereitZumBeenden: failure !== "install", fehler: "install rejected" });
      }
    }
    if (failure) {
      assert.doesNotMatch(d.querySelector("#update-stand").textContent, /Please wait/);
      assert.equal(d.querySelector("#update-herunterladen").disabled, false);
      assert.equal(messages.filter(m => m.cmd === "beenden").length, 0);
    } else {
      busy(); assert.equal(messages.filter(m => m.cmd === "beenden").length, 1);
    }
    console.log("UPDATE WAITING PASSED", web, failure || "success");
  } finally { w.close(); }
}
(async () => {
  const linux = process.env.MAGNOLIE_LINUX_SOURCE
    ? path.join(process.env.MAGNOLIE_LINUX_SOURCE, "web")
    : [path.resolve(__dirname, "../../magnolie-organizer/web"),
      path.resolve(__dirname, "../shared/magnolie-organizer/web")]
      .find(candidate => fs.existsSync(path.join(candidate, "anwendung.js")));
  assert.ok(linux, "Source-bound Linux frontend is required");
  for (const web of [path.resolve(__dirname, "../app/web"),
    linux]) {
    for (const failure of ["save", "download", "install", ""]) await check(web, failure);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
