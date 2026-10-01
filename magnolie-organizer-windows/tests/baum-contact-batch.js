"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");
const pause = () => new Promise(resolve => setTimeout(resolve, 1));

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true
  });
  const w = dom.window, messages = [];
  let autoSave = true, saveOk = true;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const message = JSON.parse(text); messages.push(message);
    if (message.cmd === "speichern" && autoSave)
      queueMicrotask(() => w.App.gespeichert({ id: message.id, ok: saveOk }));
    if (message.cmd === "mutations_snapshot")
      queueMicrotask(() => w.App.mutationsSnapshot({ token: message.token, ok: true }));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
  w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest;
  const contact = { id: "existing", vorname: "Mia", nachname: "Muster", geburtstag: "--02-29",
    emailEintraege: [{ wert: "mia@example.test", label: "HOME", typen: [] }] };
  const offer = (id, values = {}, version = 1) => ({ id: "message-" + id, von: "peer", inhalt: {
    art: "kontakt_sync", fassung: 2, freigabeId: "contact-" + id, quelle: "peer", version,
    kontakt: { vorname: "Mia", nachname: "Muster", geburtstag: "1604-02-29", telefone: [],
      emailEintraege: [{ wert: "mia@example.test", art: "HOME" }], anschriften: [], ...values }
  } });
  const inbox = (offers, options = {}) => w.App.baumStand({ an: true, moeglich: true, name: "Test", kennung: "local",
    eingang: offers, partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, vertraut: false, ...options }] });
  const reset = async (contacts = []) => {
    autoSave = true; saveOk = true;
    w.App.init({ daten: { kontakte: contacts }, neu: false, regional: { language: "en" } });
    inbox([]); await pause();
    messages.length = 0;
  };
  const receipts = () => messages.filter(m => m.cmd === "baum_eingang_geleert").flatMap(m => m.ids);
  try {
    await reset([contact]);
    assert.equal(T.baumKontaktPruefung(offer("same")).art, "gleich");
    for (const changed of [
      { nachname: "Married name" },
      { emailEintraege: [{ wert: "new@example.test", art: "HOME" }] },
      { anschriften: [{ strasse: "New street", plz: "12345", ort: "Town", art: "HOME" }] }
    ]) assert.equal(T.baumKontaktPruefung(offer("changed", changed)).art, "konflikt");
    assert.equal(T.baumKontaktPruefung(offer("added-phone", { telefone: [{ wert: "+49301234567", art: "CELL" }] })).art, "ergaenzung");
    assert.equal(T.baumKontaktPruefung(offer("added-mail", { emailEintraege: [
      { wert: "mia@example.test", art: "HOME" }, { wert: "new@example.test", art: "HOME" }
    ] })).art, "ergaenzung");
    const same = offer("same"), changed = offer("changed", { nachname: "Married name" });
    const fresh = offer("fresh", { vorname: "Other", emailEintraege: [{ wert: "other@example.test", art: "HOME" }] });
    inbox([same, changed, fresh]);
    const staged = await T.uebernehmeBaumKontakte();
    assert.equal(staged.konflikte, 1); assert.equal(staged.gespeichert, false);
    assert.equal(T.daten().kontakte.length, 1, "mixed run wrote new contacts before reviewing its conflicts");
    assert.equal(receipts().length, 0);
    staged.lauf.beendet = true;
    inbox([same, fresh]);
    autoSave = false;
    const pending = T.uebernehmeBaumKontakte();
    const flushed = new Set();
    let write;
    for (let i = 0; i < 1000 && !write; i++) {
      for (const m of messages.filter(m => m.cmd === "speichern" && !flushed.has(m.id))) {
        if (JSON.parse(m.text).kontakte.length === 2) { write = m; break; }
        flushed.add(m.id); w.App.gespeichert({ id: m.id, ok: true });
      }
      if (!write) await pause();
    }
    assert.equal(T.daten().kontakte.length, 2, "an identical incoming contact became a second card");
    assert.equal(receipts().length, 0, "inbox was acknowledged before durable saving");
    assert.ok(write, "batch did not request persistence");
    w.App.gespeichert({ id: write.id, ok: true });
    const result = await pending;
    assert.equal(result.angenommen, 2); assert.equal(result.konflikte, 0); assert.equal(result.gespeichert, true);
    assert.deepEqual(receipts().sort(), [same.id, fresh.id].sort());
    assert.equal(T.daten().kontakte.find(k => k.id === "existing").geburtstag, "--02-29");
    assert.equal(T.daten().kontakte.find(k => k.id === "existing").baumKontakt.freigabeId, "contact-same");

    const persisted = JSON.parse(JSON.stringify(T.daten()));
    autoSave = true;
    w.App.init({ daten: persisted, neu: false, regional: { language: "en" } });
    inbox([offer("same", {}, 2), offer("fresh", fresh.inhalt.kontakt, 2)]);
    const replay = await T.uebernehmeBaumKontakte();
    assert.equal(replay.angenommen, 2); assert.equal(T.daten().kontakte.length, 2, "restart lost the source association");

    await reset([{ ...contact, baumKontakt: { freigabeId: "contact-same", version: 5,
      quelle: "prior-peer", partner: ["prior-peer"] } }]);
    const shared = offer("same"); shared.art = "kontakt_sync"; delete shared.inhalt.art;
    inbox([shared]);
    const joined = await T.uebernehmeBaumKontakte();
    assert.equal(joined.angenommen, 1);
    assert.equal(T.daten().kontakte[0].baumKontakt.version, 5);
    assert.ok(T.daten().kontakte[0].baumKontakt.partner.includes("peer"), "a known shared identity from a new partner was acknowledged without saving its binding");
    assert.equal(T.baumKontaktPruefung(offer("different-binding")).art, "gleich");
    inbox([offer("different-binding")]);
    const aliasRun = await T.uebernehmeBaumKontakte();
    assert.equal(aliasRun.konflikte, 0); assert.equal(aliasRun.gespeichert, true);
    assert.equal(T.daten().kontakte.length, 1);
    let binding = T.daten().kontakte[0].baumKontakt;
    assert.equal(binding.freigabeId, "contact-same", "independent share overwrote the original binding");
    assert.equal(binding.version, 5, "another share's version replaced the original version");
    assert.equal(binding.weitere[0].freigabeId, "contact-different-binding");
    assert.equal(binding.weitere[0].version, 1);
    w.App.init({ daten: JSON.parse(JSON.stringify(T.daten())), neu: false, regional: { language: "en" } });
    inbox([offer("different-binding", {}, 2)]);
    assert.equal((await T.uebernehmeBaumKontakte()).konflikte, 0);
    binding = T.daten().kontakte[0].baumKontakt;
    assert.equal(binding.version, 5); assert.equal(binding.weitere[0].version, 2);
    messages.length = 0;
    assert.equal(await T.synchronisiereKontakteMit("peer"), true);
    const sent = messages.filter(m => m.cmd === "baum_teilen" && m.art === "kontakt_sync").map(m => m.inhalt);
    assert.deepEqual(sent.map(m => m.freigabeId).sort(), ["contact-different-binding", "contact-same"]);
    assert.equal(sent.find(m => m.freigabeId === "contact-same").version, 6);
    assert.equal(sent.find(m => m.freigabeId === "contact-different-binding").version, 3);
    assert.ok(sent.every(m => !JSON.stringify(m).includes("weitere")), "local binding metadata leaked onto the wire");
    const deletion = { id: "delete-alias", von: "peer", inhalt: { art: "kontakt_loeschen",
      freigabeId: "contact-different-binding", quelle: "peer", version: 4 } };
    T.merkeGeloescht("kontakte", T.daten().kontakte[0]);
    assert.deepEqual(Array.from(T.daten().baumKontaktGeloescht, m => m.freigabeId).sort(), ["contact-different-binding", "contact-same"]);
    const localMarks = T.daten().baumKontaktGeloescht;
    assert.equal(localMarks.find(m => m.freigabeId === "contact-same").version, 7);
    assert.equal(localMarks.find(m => m.freigabeId === "contact-different-binding").version, 4);
    inbox([deletion], { kontaktLoeschen: true }); await pause();
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    assert.ok([...w.document.querySelectorAll(".baum-eingang button")].some(b => b.textContent === "Delete"), "secondary binding's deletion offer is hidden");
    assert.equal(T.daten().kontakte.length, 1, "a deletion offer was applied without confirmation");
    assert.equal(T.uebernehmeBaumAngebot(deletion, {}, { aufschieben: true }), true);
    assert.equal(T.daten().kontakte.length, 0, "confirmed deletion did not find the secondary binding");

    await reset([contact, { ...contact, id: "other-person" }]);
    assert.equal(T.baumKontaktPruefung(same).art, "konflikt", "ambiguous matches were silently merged");
    await reset([{ id: "only-name", vorname: "Mia", nachname: "Muster" }]);
    assert.equal(T.baumKontaktPruefung(offer("name", { geburtstag: "", emailEintraege: [] })).art, "konflikt");

    await reset([
      { id: "a", vorname: "First", email: "shared@example.test", telefon: "+493012345678" },
      { id: "b", vorname: "Other", email: "shared@example.test", telefon: "+493012345678" },
      { id: "c", vorname: "Ada", firma: "Company" },
      { id: "d", vorname: "Ada", firma: "Company" }
    ].map(k => ({ ...k, baumKontakt: { freigabeId: k.id, partner: ["peer"] } })));
    assert.deepEqual(JSON.parse(JSON.stringify(T.baumKontaktDubletten("peer").map(pair => pair.map(k => k.id)))),
      [["a", "b"], ["c", "d"]], "indexed duplicate candidates changed order or repeated the same pair");

    await reset(); inbox([fresh]); saveOk = false;
    const failed = await T.uebernehmeBaumKontakte().catch(() => ({ gespeichert: false }));
    assert.equal(failed.gespeichert, false); assert.equal(receipts().length, 0, "failed save removed the pending offer");
    saveOk = true;
    const retried = await T.uebernehmeBaumKontakte();
    assert.equal(retried.gespeichert, true); assert.equal(T.daten().kontakte.length, 1, "retry duplicated the unsaved contact");

    await reset(); inbox([fresh]);
    T.oeffneEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    const button = w.document.querySelector("#baum-kontakte-annehmen");
    assert.ok(button, "the actual incoming-contact list has no batch action");
    button.click();
    for (let i = 0; i < 1000 && !receipts().length; i++) await pause();
    assert.equal(T.daten().kontakte.length, 1);
    assert.deepEqual(receipts(), [fresh.id]);
    assert.equal(messages.filter(m => m.cmd === "mutations_snapshot").length, 1,
      "batch acceptance did not use one recovery boundary");
    assert.ok(messages.findIndex(m => m.cmd === "mutations_snapshot") <
      messages.findIndex(m => m.cmd === "baum_eingang_geleert"));

    await reset(); inbox([fresh]);
    const single = w.document.querySelector(".baum-eingang .baum-zeile button");
    assert.ok(single); single.click();
    assert.equal(w.document.querySelectorAll(".eingabe-schleier").length, 0,
      "a conflict-free individual contact still asks for a second confirmation");
    for (let i = 0; i < 1000 && !receipts().length; i++) await pause();
    assert.deepEqual(receipts(), [fresh.id]);
    assert.equal(T.daten().kontakte.length, 1);

    await reset(); inbox([{ ...fresh, von: "not-paired" }]);
    const unpaired = await T.uebernehmeBaumKontakte();
    assert.equal(unpaired.angenommen, 0); assert.equal(T.daten().kontakte.length, 0);
    assert.equal(receipts().length, 0, "an unconfirmed sender was acknowledged");

    await reset();
    inbox(Array.from({ length: 50 }, (_, i) => offer("switch-" + i, {
      vorname: "Switch " + i, emailEintraege: [{ wert: "switch" + i + "@example.test", art: "HOME" }]
    })));
    const interrupted = T.uebernehmeBaumKontakte();
    w.App.init({ daten: { kontakte: [{ id: "after-switch", vorname: "Different profile" }] }, neu: false });
    const stopped = await interrupted;
    assert.equal(stopped.gespeichert, false); assert.equal(receipts().length, 0);
    assert.equal(T.daten().kontakte.length, 1); assert.equal(T.daten().kontakte[0].id, "after-switch",
      "the interrupted batch modified the replacement profile");

    await reset();
    const many = Array.from({ length: 500 }, (_, i) => offer("batch-" + i, {
      vorname: "Person " + i, emailEintraege: [{ wert: "person" + i + "@example.test", art: "HOME" }]
    }));
    inbox(many);
    let ticks = 0; const clock = setInterval(() => ticks++, 1), started = Date.now();
    const bulk = await T.uebernehmeBaumKontakte(); clearInterval(clock);
    assert.equal(bulk.angenommen, 500); assert.equal(bulk.konflikte, 0);
    assert.equal(T.daten().kontakte.length, 500); assert.equal(new Set(receipts()).size, 500);
    assert.equal(messages.filter(m => m.cmd === "speichern" && JSON.parse(m.text).kontakte.length === 500).length, 1, "batch saved each contact separately");
    assert.ok(ticks > 0, "batch blocked the event loop for the whole import");
    assert.equal(w.document.querySelectorAll(".eingabe-schleier").length, 0, "conflict-free contacts opened confirmation dialogs");
    console.log("BAUM CONTACT BATCH PASSED: 500 contacts in " + (Date.now() - started) + " ms: " + web);
  } finally { w.close(); }
}
(async () => {
  for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")])
    if (fs.existsSync(web)) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
