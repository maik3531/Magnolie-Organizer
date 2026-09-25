"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const tick = () => new Promise(resolve => setTimeout(resolve, 1));
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window, messages = []; let autoSave = true;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern" && autoSave) queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest;
  const offer = (peer, share, version = 1, extra = {}) => ({ id: peer + "-" + share + "-" + version,
    von: peer, inhalt: { art: "notiz", freigabeId: share, version, quelle: peer, geaendert: version * 10000,
      titel: "Welcome", text: "Same content", html: "Same content", anhaenge: [], ...extra } });
  const stand = (eingang = [], trusted = false) => w.App.baumStand({ an: true, moeglich: true, kennung: "local", name: "Local",
    partner: ["a", "b", "c"].map(kennung => ({ kennung, name: kennung, bestaetigt: true, vertraut: trusted })), eingang });
  const reset = async notes => { w.App.init({ daten: { notizen: notes, einstellungen: { sync: { erfolgsmeldungen: true } } },
    neu: false, regional: { language: "en" } }); stand(); await tick(); messages.length = 0; };
  const receipts = () => messages.filter(m => m.cmd === "baum_eingang_geleert").flatMap(m => m.ids);
  try {
    const welcome = datenPfad => {
      w.App.init({daten: {}, neu: true, datenPfad, regional: {language: "en"}});
      return JSON.parse(JSON.stringify(T.daten().notizen[0]));
    };
    const localWelcome = welcome("/home/fixture/.local/share/magnolie-organizer/daten.json");
    const remoteWelcome = welcome("C:\\Users\\Fixture\\AppData\\Local\\Magnolie Organizer\\daten.json");
    await reset([localWelcome]);
    T.uebernehmeBaumAngebot(offer("a", "generated-welcome", 1, {
      titel: remoteWelcome.titel, text: remoteWelcome.text, html: remoteWelcome.html || ""}));
    await tick();
    assert.equal(T.daten().notizen.length, 1,
      "the same generated welcome page must not duplicate because of its device-local storage path");

    const templateFile = ["../../contracts", "../contracts"].map(dir =>
      path.resolve(__dirname, dir, "note-identity-templates.json")).find(file => fs.existsSync(file));
    const templates = JSON.parse(fs.readFileSync(templateFile, "utf8")).templates;
    for (const template of templates) {
      const original = template.before + "/home/fixture/data.json" + template.after;
      const variants = [
        ["windows", template.title, template.before + "C:\\Users\\Fixture\\data.json" + template.after, "", 1],
        ["no-path", template.title, template.text, "", 1],
        ["crlf", template.title, original.replace(/\n/g, "\r\n"), "", 1],
        ["edited", template.title, original + "User addition", "", 2],
        ["title", template.title + " edited", original, "", 2],
        ["formatting", template.title, original, "<b>Welcome</b>", 2],
        ["relative-path", template.title, template.before + "relative/data.json" + template.after, "", 2],
        ["multiline-path", template.title, template.before + "/home/fixture\nUser addition" + template.after, "", 2]
      ];
      for (const [name, titel, text, html, count] of variants) {
        await reset([{id: "template-local", titel: template.title, text: original, html: ""}]);
        T.uebernehmeBaumAngebot(offer("a", "template-" + name, 1, {titel, text, html}));
        await tick();
        assert.equal(T.daten().notizen.length, count, template.locale + "/" + name);
      }
    }
    await reset([{id: "ordinary-path", titel: "My paths", text: "/home/fixture/data.json", html: ""}]);
    T.uebernehmeBaumAngebot(offer("a", "ordinary-path", 1, {
      titel: "My paths", text: "C:\\Users\\Fixture\\data.json", html: ""}));
    await tick();
    assert.equal(T.daten().notizen.length, 2, "paths in ordinary user notes must remain content");

    await reset([{ id: "local-note", titel: "Welcome", text: "Same content", html: "<p>Same content</p>", angelegt: 1 }]);
    assert.equal(T.uebernehmeBaumAngebot(offer("a", "share-a")), true); await tick();
    assert.equal(T.uebernehmeBaumAngebot(offer("b", "share-b", 9)), true); await tick();
    assert.equal(T.daten().notizen.length, 1, "different creation times/share IDs duplicated Welcome");
    assert.equal(T.daten().notizen[0].id, "local-note"); assert.equal(T.daten().notizen[0].angelegt, 1);
    assert.equal(T.daten().notizen[0].baumFreigabe.quellen.length, 2);
    const saved = JSON.parse(JSON.stringify(T.daten()));
    w.App.init({ daten: saved, neu: false, regional: { language: "en" } }); stand(); await tick(); messages.length = 0;
    stand([offer("a", "share-a", 2, { art: "notiz_sync", text: "New remote content", html: "New remote content" })]); await tick();
    assert.equal(T.daten().notizen.length, 1); assert.equal(T.daten().notizen[0].text, "New remote content",
      "an independent source clock was compared with another source's version");
    messages.length = 0; T.synchronisiereFreigegebeneNotiz(T.daten().notizen[0]);
    const outbound = messages.filter(m => m.cmd === "baum_teilen" && m.art === "notiz_sync");
    assert.ok(outbound.some(m => m.kennung === "a" && m.inhalt.freigabeId === "share-a"));
    assert.ok(outbound.some(m => m.kennung === "b" && m.inhalt.freigabeId === "share-b"));

    const notification = w.document.querySelector("#zettel").textContent;
    const modified = T.daten().notizen[0].geaendert;
    stand([offer("a", "share-a", 3, { art: "notiz_sync", text: "New remote content", html: "New remote content" })]); await tick();
    assert.equal(w.document.querySelector("#zettel").textContent, notification, "metadata-only update produced a changes notification");
    assert.equal(T.daten().notizen[0].geaendert, modified);
    const revision = T.daten().notizen[0].baumInhaltVersion;
    T.markiereGemeinsameNotiz(T.daten().notizen[0], false);
    assert.equal(T.daten().notizen[0].baumInhaltVersion, revision, "extending sharing was treated as a content edit");
    const local = T.daten().notizen[0]; local.text = "Local edit"; local.html = "Local edit"; T.markiereGemeinsameNotiz(local);
    messages.length = 0;
    const conflict = offer("a", "share-a", 4, { art: "notiz_sync", text: "Conflicting edit", html: "Conflicting edit" });
    stand([conflict]); await tick();
    assert.equal(local.text, "Local edit"); assert.ok(!receipts().includes(conflict.id), "conflicting update was discarded instead of left for a decision");
    messages.length = 0;
    const reoffer = offer("a", "share-a", 5, { text: "Conflicting reoffer", html: "Conflicting reoffer" });
    stand([reoffer], true); await tick();
    assert.equal(local.text, "Local edit"); assert.ok(!receipts().includes(reoffer.id), "trusted reoffer silently overwrote a local edit");

    const pdf = "data:application/pdf;base64,JVBERg==";
    await reset([{ id: "attachment", titel: "Welcome", text: "Same content", html: "Same content",
      anhaenge: [{ id: "local-file", name: "a.pdf", art: "pdf", daten: pdf }] }]);
    T.uebernehmeBaumAngebot(offer("a", "files", 1, { anhaenge: [{ id: "remote-file", name: "a.pdf", daten: pdf }] })); await tick();
    assert.equal(T.daten().notizen.length, 1); assert.equal(T.daten().notizen[0].anhaenge[0].id, "local-file");
    stand([offer("a", "files", 2, { art: "notiz_sync", text: "Changed text", html: "Changed text",
      anhaenge: [{ id: "changed-remote-id", name: "a.pdf", daten: pdf }] })]); await tick();
    assert.equal(T.daten().notizen[0].anhaenge[0].id, "local-file", "unchanged attachment bytes lost their local identity");
    T.daten().notizen[0].baumFreigabe.anhangPartner = [];
    stand([offer("a", "files", 3, { art: "notiz_sync", text: "Changed text", html: "Changed text", anhaenge: [] })]); await tick();
    assert.equal(T.daten().notizen[0].anhaenge.length, 1);
    assert.equal(T.daten().notizen[0].baumFreigabe.anhangPartner.length, 0, "an update silently granted attachment access");
    T.uebernehmeBaumAngebot(offer("b", "formatted", 1, { html: "<b>Same content</b>" })); await tick();
    assert.equal(T.daten().notizen.length, 2, "different formatting/attachments were collapsed");

    await reset([{ id: "plain", titel: "Welcome", text: "Same content", html: "Same content" }]);
    T.uebernehmeBaumAngebot(offer("a", "bold", 1, { html: "<b>Same content</b>" })); await tick();
    assert.equal(T.daten().notizen.length, 2, "plain and bold content were treated as identical");
    T.uebernehmeBaumAngebot(offer("b", "attachment-only-difference", 1, { anhaenge: [{ id: "file", name: "a.pdf", daten: pdf }] })); await tick();
    assert.equal(T.daten().notizen.length, 3, "an attachment difference was ignored");

    await reset([{ id: "legacy", titel: "Welcome", text: "Same content", html: "Same content", baumVersion: 1,
      baumQuelle: "a", baumFreigabe: { id: "legacy-share", partner: ["a"], anhangPartner: [] } }]);
    stand([offer("a", "legacy-share", 1, { art: "notiz_sync" })]); await tick();
    assert.equal(T.daten().notizen[0].baumFreigabe.quellen.length, 1, "identical legacy state did not establish a source baseline");
    stand([offer("a", "legacy-share", 2, { art: "notiz_sync", text: "Legacy update", html: "Legacy update" })]); await tick();
    assert.equal(T.daten().notizen[0].text, "Legacy update");
    const revisionBeforePhone = T.daten().notizen[0].baumInhaltVersion;
    T.personalSyncSetze({ kind: "note", value: { title: "Welcome", text: "Phone edit", html: "Phone edit",
      notebook_id: T.daten().notizen[0].notizbuchId, symbol: "notiz", created_ms: 1, modified_ms: 100 } }, "legacy", true);
    assert.ok(T.daten().notizen[0].baumInhaltVersion > revisionBeforePhone, "an APK edit bypassed the tree conflict baseline");
    messages.length = 0;
    const afterPhone = offer("a", "legacy-share", 3, { art: "notiz_sync", text: "Other tree edit", html: "Other tree edit" });
    stand([afterPhone]); await tick();
    assert.equal(T.daten().notizen[0].text, "Phone edit"); assert.ok(!receipts().includes(afterPhone.id));

    await reset([{ id: "phone-attachment", titel: "Welcome", text: "Same content", html: "Same content",
      baumFreigabe: { id: "shared-attachment", partner: ["a"], anhangPartner: ["a"] } }]);
    const prior = T.daten().notizen[0];
    T.personalSyncSetze({ kind: "note", value: { title: prior.titel, text: prior.text, html: prior.html,
      notebook_id: prior.notizbuchId, symbol: prior.symbol, created_ms: prior.angelegt, modified_ms: 100,
      attachments: [{ attachment_id: "phone-file", name: "a.pdf", kind: "pdf", sha256: "fixture" }] } },
      prior.id, false, { fixture: pdf });
    assert.equal(prior.anhaenge.length, 0, "phone import mutated the old attachment array before comparing content");
    assert.equal(T.daten().notizen[0].anhaenge.length, 1);
    assert.ok(T.daten().notizen[0].baumInhaltVersion > prior.baumInhaltVersion,
      "an attachment-only phone edit bypassed the tree conflict baseline");

    await reset([]); autoSave = false;
    const first = offer("a", "pending"); stand([first], true);
    assert.equal(T.daten().notizen.length, 1); assert.equal(receipts().length, 0, "note was acknowledged before saving");
    stand([first], true); assert.equal(T.daten().notizen.length, 1);
    const write = messages.filter(m => m.cmd === "speichern").at(-1);
    assert.ok(write); w.App.gespeichert({ id: write.id, ok: false }); await tick();
    assert.equal(receipts().length, 0, "failed note save acknowledged the offer");
    autoSave = true; stand([first], true); await tick();
    assert.equal(T.daten().notizen.length, 1, "retry after a failed save duplicated the note");
    assert.deepEqual(receipts(), [first.id]);
    autoSave = true;
    messages.length = 0; const unknown = offer("c", "unknown", 2, { art: "notiz_sync" });
    stand([unknown]); await tick(); assert.ok(!receipts().includes(unknown.id));

    const many = Array.from({ length: 1000 }, (_, i) => ({ id: "local-" + i, titel: "Note " + i,
      text: "Text " + i, html: "<p>Text " + i + "</p>", angelegt: i + 1 }));
    await reset(many);
    const offers = many.map((n, i) => offer("a", "remote-" + i, 1, { titel: n.titel, text: n.text, html: n.text, angelegt: i + 10000 }));
    const previousNotice = w.document.querySelector("#zettel").textContent;
    const started = Date.now(); stand(offers, true); await tick();
    assert.equal(T.daten().notizen.length, 1000); assert.equal(receipts().length, 1000);
    assert.ok(T.daten().notizen.every(n => n.id.startsWith("local-")), "bulk import replaced local note identities");
    assert.equal(messages.filter(m => m.cmd === "speichern").length, 1, "bulk note receipt saved each item separately");
    assert.equal(w.document.querySelector("#zettel").textContent, previousNotice);
    console.log("1000 identical note offers: " + (Date.now() - started) + " ms, no duplicate notes");
    console.log("BAUM NOTE IDENTITY PASSED: " + web);
  } finally { w.close(); }
}
(async () => {
  const paths = [path.resolve(__dirname, "../app/web")];
  const linux = process.env.MAGNOLIE_LINUX_SOURCE ? path.resolve(process.env.MAGNOLIE_LINUX_SOURCE, "web") : path.resolve(__dirname, "../../magnolie-organizer/web");
  if (!process.argv.includes("--windows-only") && (process.env.MAGNOLIE_LINUX_SOURCE || fs.existsSync(linux))) paths.push(linux);
  for (const p of paths) await check(p);
})().catch(error => { console.error(error); process.exitCode = 1; });
