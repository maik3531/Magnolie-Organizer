"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 1));
async function until(check) {
  for (let i = 0; i < 3000; i++) { if (check()) return; await tick(); }
  throw new Error("Review did not reach its expected state");
}
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/index.html", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = [];
  let snapshotOk = true;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: m.token, ok: snapshotOk }));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest, clean = value => JSON.parse(JSON.stringify(value));
  const person = i => ({ id: "person-" + i, vorname: "Person " + i, nachname: "Example",
    emailEintraege: [{ wert: "person" + i + "@example.test", label: "HOME", typen: [] }],
    telefone: [{ wert: "+4930123456" + i, label: "CELL", typen: ["CELL"] }] });
  const offer = (i, extra = {}, version = 1) => ({ id: "message-" + i + "-" + version, von: "peer", inhalt: {
    art: "kontakt_sync", fassung: 2, freigabeId: "share-" + i, version, quelle: "peer", kontakt: {
      vorname: "Person " + i, nachname: "Changed " + i, geburtstag: "", anschriften: [],
      emailEintraege: [{ wert: "person" + i + "@example.test", art: "HOME" }],
      telefone: [{ wert: "+4930987654" + i, art: "CELL" }], ...extra } } });
  const inbox = rows => w.App.baumStand({ an: true, moeglich: true, kennung: "local", name: "Local", eingang: rows,
    partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, vertraut: false }] });
  const reset = async (people, rows) => {
    snapshotOk = true; w.App.init({ daten: { kontakte: people }, neu: false, regional: { language: "en" } });
    inbox(rows); await tick(); T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    await tick(); messages.length = 0;
  };
  const snapshotCount = () => messages.filter(m => m.cmd === "mutations_snapshot").length;
  const receipts = () => messages.filter(m => m.cmd === "baum_eingang_geleert").flatMap(m => m.ids);
  const choose = (selector, value) => { const el = w.document.querySelector(selector); assert.ok(el); el.value = value; el.dispatchEvent(new w.Event("change")); };
  const action = mode => w.document.querySelector('[data-kontakt-entscheidung="' + mode + '"]').click();
  try {
    const dateTarget = { ...person(1), geburtstag: "--02-29", jubilaeum: "2000-06-07" };
    const incomplete = T.normalisiere({ kontakte: [person(1)] }).kontakte[0];
    const preserved = T.baumKontaktEntwurf(dateTarget, incomplete, {}, "replace");
    assert.equal(preserved.geburtstag, "--02-29"); assert.equal(preserved.jubilaeum, "2000-06-07");
    await reset([person(1), person(2)], [offer(1), offer(2), offer(3, { nachname: "New" })]);
    const before = JSON.stringify(T.daten().kontakte);
    w.document.querySelector("#baum-kontakte-annehmen").click();
    await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    assert.equal(JSON.stringify(T.daten().kontakte), before, "preview already changed live contacts");
    assert.equal(snapshotCount(), 0); assert.equal(receipts().length, 0);
    choose('[data-kontakt-feld="nachname"]', "incoming");
    choose('[data-kontakt-liste="telefone"]', "replace:0"); action("merge");
    await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    assert.equal(JSON.stringify(T.daten().kontakte), before, "individual decision wrote before the complete review");
    assert.equal(snapshotCount(), 0); assert.equal(receipts().length, 0);
    action("keep"); await until(() => receipts().length === 3);
    assert.equal(snapshotCount(), 1, "review created a snapshot per contact instead of per run");
    assert.equal(T.daten().kontakte.length, 3);
    const first = T.daten().kontakte.find(k => k.id === "person-1"), second = T.daten().kontakte.find(k => k.id === "person-2");
    assert.equal(first.nachname, "Changed 1"); assert.equal(first.telefone.length, 1); assert.ok(first.telefone[0].wert.includes("9876541"));
    assert.equal(second.nachname, "Example"); assert.ok(second.telefone[0].wert.includes("1234562"));
    const persisted = clean(T.daten());
    w.App.init({ daten: persisted, neu: false, regional: { language: "en" } }); inbox([offer(1, {}, 2), offer(2, {}, 2)]);
    messages.length = 0;
    const replay = await T.uebernehmeBaumKontakte();
    assert.equal(replay.konflikte, 0); assert.equal(replay.gespeichert, true); assert.equal(snapshotCount(), 0);
    assert.equal(T.daten().kontakte.find(k => k.id === "person-2").nachname, "Example", "unchanged remote data undid the remembered choice");

    await reset([person(1), person(2)], [offer(1), offer(2)]);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    w.document.querySelector('[data-kontakt-rest="true"]').checked = true; action("replace");
    await until(() => receipts().length === 2);
    assert.equal(snapshotCount(), 1);
    for (const i of [1, 2]) { const k = T.daten().kontakte.find(k => k.id === "person-" + i);
      assert.equal(k.nachname, "Changed " + i); assert.equal(k.email, "person" + i + "@example.test"); }

    const home = i => ({ wert: "+4930555555" + i, label: "HOME", typen: ["HOME"] });
    await reset([{ ...person(1), telefone: [home(1), ...person(1).telefone] },
      { ...person(2), telefone: [...person(2).telefone, home(2)] }], [offer(1), offer(2)]);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    choose('[data-kontakt-liste="telefone"]', "replace:1");
    const remaining = w.document.querySelector('[data-kontakt-rest="true"]');
    assert.equal(remaining.disabled, false); remaining.checked = true; action("merge");
    await until(() => receipts().length === 2);
    for (const i of [1, 2]) {
      const k = T.daten().kontakte.find(k => k.id === "person-" + i);
      assert.equal(k.telefone.length, 2);
      assert.ok(k.telefone.some(t => t.wert.includes("555555" + i)), "rest decision replaced the wrong role/index");
      assert.ok(k.telefone.some(t => t.wert.includes("987654" + i)), "rest decision copied another person's number");
    }
    assert.equal(snapshotCount(), 1);

    await reset([person(1), person(2)], [offer(1), offer(2)]);
    const skipped = JSON.stringify(T.daten().kontakte);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    w.document.querySelector('[data-kontakt-rest="true"]').checked = true; action("skip");
    await until(() => receipts().length === 2);
    assert.equal(snapshotCount(), 0); assert.equal(JSON.stringify(T.daten().kontakte), skipped);

    await reset([person(1)], [offer(1)]);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    action("keep"); await until(() => receipts().length === 1);
    assert.equal(snapshotCount(), 0, "keeping existing data created a content snapshot");
    assert.equal(T.daten().kontakte[0].nachname, "Example");

    await reset([person(1)], [offer(1)]);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    action("new"); await until(() => receipts().length === 1);
    assert.equal(T.daten().kontakte.length, 2); assert.equal(snapshotCount(), 1);
    inbox([offer(1, {}, 2)]); messages.length = 0;
    const separateReplay = await T.uebernehmeBaumKontakte();
    assert.equal(separateReplay.konflikte, 0); assert.equal(T.daten().kontakte.length, 2);
    assert.equal(snapshotCount(), 0, "explicit separate-contact choice was lost on replay");

    await reset([person(1)], [offer(1)]);
    const unchanged = JSON.stringify(T.daten().kontakte);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    [...w.document.querySelectorAll(".baum-kontakt-konflikt button")].find(b => b.textContent === "Cancel").click();
    assert.equal(JSON.stringify(T.daten().kontakte), unchanged); assert.equal(snapshotCount(), 0); assert.equal(receipts().length, 0);

    await reset([person(1)], [offer(1)]);
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    T.daten().kontakte[0].notiz = "Concurrent local edit";
    action("replace"); await until(() => w.document.querySelector("#zettel").textContent === "Conflict");
    assert.equal(T.daten().kontakte[0].notiz, "Concurrent local edit");
    assert.equal(T.daten().kontakte[0].nachname, "Example");
    assert.equal(snapshotCount(), 0); assert.equal(receipts().length, 0, "stale review acknowledged an unapplied offer");

    await reset([person(1)], [offer(1)]); snapshotOk = false;
    w.document.querySelector("#baum-kontakte-annehmen").click(); await until(() => w.document.querySelector(".baum-kontakt-konflikt"));
    action("replace"); await until(() => snapshotCount() === 1); await tick();
    assert.equal(T.daten().kontakte[0].nachname, "Example"); assert.equal(receipts().length, 0);
    console.log("BAUM CONTACT REVIEW PASSED: " + web);
  } catch (error) {
    console.error("Review diagnostic:", w.document.querySelector("#zettel")?.textContent, messages.map(m => m.cmd));
    throw error;
  } finally { w.close(); }
}
(async () => {
  const locations = [path.resolve(__dirname, "../app/web")];
  const linux = process.env.MAGNOLIE_LINUX_SOURCE ? path.resolve(process.env.MAGNOLIE_LINUX_SOURCE, "web") : path.resolve(__dirname, "../../magnolie-organizer/web");
  if (!process.argv.includes("--windows-only") && (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linux))) locations.push(linux);
  for (const location of locations) await check(location);
})().catch(error => { console.error(error); process.exitCode = 1; });
