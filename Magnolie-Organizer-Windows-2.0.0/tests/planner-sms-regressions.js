"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/", pretendToBeVisual: true
  });
  const w = dom.window, d = w.document, messages = [];
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage: text => messages.push(JSON.parse(text)) } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  await new Promise(resolve => setTimeout(resolve, 0));
  const T = w.OrganizerTest;
  const sent = () => messages.filter(m => m.cmd === "kde_sms_senden");
  const input = value => {
    const field = d.querySelector(".sms-eingabe");
    field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
  };
  try {
    w.App.init({ daten: { einstellungen: { allgemein: { handbuchHinweisGezeigt: true } }, termine: Array.from({ length: 19 }, (_, i) => ({
      id: "ordinary-" + i, titel: "Ordinary appointment " + i, datum: "2026-09-12", zeit: "09:00"
    })), jahrestage: [{ id: "birthday", name: "Birthday marker", datum: "--09-12", typ: "birthday" }],
    feiertage: [{ id: "holiday", name: "Public holiday", von: "2026-09-12", bis: "2026-09-12", art: "public-holiday" }] },
    neu: false, regional: { language: "en", timeZone: "Europe/Berlin" } });
    d.querySelector("#deckel").click();
    await new Promise(resolve => setTimeout(resolve, 1600));
    T.zustand().planer.jahr = 2026;
    const before = JSON.stringify(T.daten());
    let workers = 0;
    w.Worker = class { constructor() { workers++; throw new Error("Unexpected ordinary Planner worker"); } };
    await T.wechsel("planer");
    const deadline = Date.now() + 3000;
    while (d.querySelector('.planer-raster[aria-busy="true"]')) {
      assert.ok(Date.now() < deadline, "Planner did not finish deferred rendering");
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    assert.equal(d.querySelectorAll(".mini-monat").length, 12,
      JSON.stringify({ state: T.zustand(), registers: [...d.querySelectorAll('.registerknopf')].map(n => n.textContent) }));
    assert.equal(d.querySelectorAll(".mm-tag.hat").length, 0);
    assert.ok(d.querySelector('[data-fokus="planer-tag:2026-09-12"]').classList.contains("jt"));
    assert.equal(T.suchTrefferFuer("planer", ["ordinary"]).length, 0);
    assert.ok(T.suchTrefferFuer("planer", ["birthday"]).length);
    assert.equal(T.planerKalenderModell(2026).icsIncomplete, false);
    assert.equal(workers, 0);
    const month = T.planerMonatsModell(2026, 8);
    assert.equal(month.icsIncomplete, false);
    const day = month.wochen.flatMap(week => week.tage).find(day => day.iso === "2026-09-12");
    assert.equal(day.eintraege.filter(entry => entry.art === "termin").length, 19);
    const ods = T.planerOdsNutzlast(month);
    const html = new JSDOM(T.planerDruckSeite(month));
    try {
      const cell = html.window.document.querySelector("td.voll");
      assert.equal(cell.querySelectorAll(".eintrag:not(.mehr)").length, 5);
      assert.equal(cell.querySelector(".mehr").textContent, "+" + (day.eintraege.length - 5));
      assert.ok(cell.querySelector(".tag-inhalt"));
      assert.ok(ods.zeilen.flat().some(text => text.includes("Ordinary appointment 18")));
      assert.equal(JSON.stringify(T.daten()), before, "Planner/export changed persisted data");
    } finally { html.window.close(); }
    console.log("PASS normal Planner and complete month payload: " + web);

    await T.wechsel("notizen");
    for (const available of [false, true]) {
      w.App.telefonStand({ peers: [], kdeconnect: { available, device_count: 1, device_id: "synthetic-phone-000000000000000001" } });
      w.App.telefonAntwort({ nummer: "+12025550123", device_id: "synthetic-phone-000000000000000001" });
      input("Synthetic SMS \u2014 test \ud83d\ude42");
      const row = d.querySelector(".sms-komponist");
      const [content, send, schedule] = row.children;
      assert.ok(content.classList.contains("sms-komponist-text"));
      assert.equal(send.textContent, "Send SMS"); assert.equal(schedule.textContent, "Schedule");
      const preview = content.querySelector(".sms-anpassung");
      const [confirm, cancel] = preview.querySelectorAll("button");
      assert.equal(confirm.textContent, "Send adjusted text"); assert.equal(cancel.textContent, "Cancel");
      assert.ok(!preview.textContent.includes("[object HTMLButtonElement]"));
      const count = sent().length;
      cancel.click(); assert.ok(preview.classList.contains("verborgen"));
      assert.equal(sent().length, count);
      input("Synthetic SMS \u2014 test \ud83d\ude42");
      assert.equal(confirm.disabled, !available, "Adjusted send must honor offline state");
      confirm.click(); confirm.click();
      assert.equal(sent().length, count + Number(available), "Repeated confirmation must not dispatch twice");
      if (available) {
        assert.ok(send.disabled && confirm.disabled);
        input("Edited draft \u2014 while pending");
        confirm.click(); send.click();
        assert.equal(sent().length, count + 1, "Editing must not bypass pending dispatch");
        w.App.kdeSmsStatus({ ok: true, state: "queued", client_ref: sent().at(-1).clientRef });
        assert.equal(T.daten().smsVerlauf.at(-1).status, "queued");
        w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: sent().at(-1).clientRef });
        assert.equal(T.daten().smsVerlauf.at(-1).status, "submitted");
        assert.equal(d.querySelector(".sms-eingabe").value, "Edited draft \u2014 while pending",
          "Acknowledging the previous SMS must not discard a new draft");
        assert.ok(!send.disabled && !confirm.disabled);
      }
      d.querySelector(".sms-schliessen").click();
    }
    console.log("PASS actual SMS confirmation buttons, offline and pending: " + web);
  } finally { w.close(); }
}

(async () => {
  const roots = [path.resolve(__dirname, "../app/web")];
  const linux = path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web");
  if (fs.existsSync(linux)) roots.push(linux);
  for (const web of roots) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
