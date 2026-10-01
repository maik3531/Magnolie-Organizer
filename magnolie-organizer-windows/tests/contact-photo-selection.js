"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto"), { JSDOM } = require("jsdom");
const photo = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAARUlEQVR4nO3OsQEAEADAMPz/M7slI0NzQeYef1mvA7dCUkgKSSEpJIWkkBSSQlJICkkhKSSFpJAUkkJSSApJISkkhaSQHEnhAV+0eRpfAAAAAElFTkSuQmCC";
const other = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAARklEQVR4nO3OsQEAEADAMFzudLulI0NyQebY4yvrdeAmVISKUBEqQkWoCBWhIlSEilARKkJFqAgVoSJUhIpQESpCRagIlQPMPgDgNw6LvQAAAABJRU5ErkJggg==";
const third = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAADYYG7QAAAASElEQVR4nO3OoQHAIBAAsYf9d249JhLEZYKsmW9esm8HToWkkBSSQlJICkkhKSSFpJAUkkJSSApJISkkhaSQFJJCUkgKSSH5AUfjAV8gKmuXAAAAAElFTkSuQmCC";
const plain = value => JSON.parse(JSON.stringify(value));
async function until(test) { for (let i = 0; i < 4000; i++) { if (test()) return; await new Promise(r => setTimeout(r, 1)); } throw Error("Photo selection timeout"); }
async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window, messages = []; let snapshotOk = true;
  Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.__MAGNOLIE_BRUECKE__ = "test";
  w.webkit = { messageHandlers: { test: { postMessage(text) {
    const m = JSON.parse(text); messages.push(m);
    if (m.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: m.id, ok: true }));
    if (m.cmd === "mutations_snapshot") queueMicrotask(() => w.App.mutationsSnapshot({ token: m.token, ok: snapshotOk }));
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  const T = w.OrganizerTest;
  const options = () => [...w.document.querySelectorAll(".kontakt-foto-option")];
  const choose = data => { const button = options().find(b => b.querySelector("img").getAttribute("src") === data); assert.ok(button); button.click(); };
  const open = k => { const card = T.kontaktKarte(k); w.document.body.append(card); card.querySelector(".kontakt-foto-auswahl").click(); card.remove(); };
  try {
    const legacy = T.normalisiere({ kontakte: [{ id: "legacy", vorname: "Old", foto: photo }] }).kontakte[0];
    assert.equal(legacy.fotoAlternativen, undefined, "loading a legacy photo created an empty gallery migration");
    assert.equal(legacy.fotoQuellen, undefined);
    w.App.init({ daten: { kontakte: [{ id: "person", vorname: "Person", foto: photo,
      fotoAlternativen: [{ foto: other, quellen: ["KDE Connect"] }, { foto: photo, quellen: ["Magnolienbaum"] },
        { foto: other, quellen: ["system"] }, { foto: "https://example.org/unrequested.png", quellen: ["bad"] }] }],
      einstellungen: { adressen: { foto: true } } }, neu: false });
    let k = T.daten().kontakte[0];
    assert.equal(k.fotoAlternativen.length, 1, "duplicates or external URLs remained in the gallery");
    assert.equal(T.kontaktFotoVarianten(k).length, 2);
    open(k); assert.equal(options().length, 2);
    assert.equal(options()[0].getAttribute("aria-pressed"), "true");
    choose(other); await until(() => !w.document.querySelector(".kontakt-foto-dialog"));
    assert.equal(k.foto, other); assert.equal(k.fotoManuell, true);
    assert.equal(k.fotoAlternativen.length, 1); assert.equal(k.fotoAlternativen[0].foto, photo);
    const saved = messages.filter(m => m.cmd === "speichern").map(m => JSON.parse(m.text)).findLast(d => d.kontakte[0].foto === other);
    assert.ok(saved, "selected image never reached the save payload");
    w.App.init({ daten: saved, neu: false }); k = T.daten().kontakte[0];
    assert.equal(k.foto, other); assert.equal(k.fotoManuell, true);
    k.baumKontakt = { freigabeId: "photo-share", version: 1, quelle: "peer", partner: ["peer"] };
    w.App.baumStand({ an: true, moeglich: true, kennung: "local",
      partner: [{ kennung: "peer", bestaetigt: true }], eingang: [{ id: "photo-update", von: "peer", inhalt: {
        art: "kontakt_sync", fassung: 2, freigabeId: "photo-share", version: 2, quelle: "peer",
        kontakt: { vorname: "Person", foto: third, telefone: [], emailEintraege: [], anschriften: [] }
      } }] });
    const photoUpdate = await T.uebernehmeBaumKontakte();
    assert.equal(photoUpdate.konflikte, 0, "a pinned photo-only source update asked for a contact conflict decision");
    k = T.daten().kontakte[0];
    assert.equal(k.foto, other, "a new source image replaced the explicit selection");
    assert.equal(T.kontaktFotoVarianten(k).length, 3);
    assert.equal(T.uebernehmeKontaktFoto(k, third, "Magnolienbaum", true), false);
    open(k); assert.equal(options().length, 3);
    snapshotOk = false; choose(photo);
    await until(() => w.document.querySelector(".kontakt-foto-dialog .einst-warnung").textContent);
    assert.equal(k.foto, other, "failed recovery snapshot still changed the chosen image");
    [...w.document.querySelectorAll(".kontakt-foto-dialog button")].find(b => b.textContent === "Cancel").click();
    snapshotOk = true;
    open(k);
    const old = k;
    w.App.init({ daten: { kontakte: [{ id: "different", vorname: "Other" }] }, neu: false });
    assert.equal(w.document.querySelector(".kontakt-foto-dialog"), null, "profile switch retained private gallery");
    assert.equal(old.foto, other);
    w.App.init({ daten: saved, neu: false }); k = T.daten().kontakte[0];
    open(k); T.zeigeSperrbildschirm(false);
    assert.equal(w.document.querySelector(".kontakt-foto-dialog"), null, "locked profile retained private gallery");
    w.App.init({ daten: saved, neu: false }); k = T.daten().kontakte[0];
    open(k);
    [...w.document.querySelectorAll(".kontakt-foto-dialog button")].find(b => b.textContent === "Remove photo").click();
    await until(() => !w.document.querySelector(".kontakt-foto-dialog"));
    assert.equal(k.foto, ""); assert.equal(k.fotoManuell, true);
    assert.equal(k.fotoAlternativen.length, 1, "removing the displayed photo removed unrelated alternatives");
    assert.equal(k.fotoAlternativen[0].foto, photo);
    // jsdom has no image decoder/canvas: retain the real FileReader path and
    // substitute only rendering. Native probes cover actual decoding.
    w.Image = class { constructor() { this.width = this.height = 1; } set src(value) { if (value) queueMicrotask(() => this.onload?.()); } };
    w.HTMLCanvasElement.prototype.getContext = () => ({ fillRect() {}, drawImage() {} });
    w.HTMLCanvasElement.prototype.toDataURL = () => photo;
    open(k);
    const fileInput = w.document.querySelector('.kontakt-foto-dialog input[type="file"]');
    Object.defineProperty(fileInput, "files", { value: [new w.File([Buffer.from(photo.split(",")[1], "base64")], "own.png", { type: "image/png" })] });
    fileInput.dispatchEvent(new w.Event("change"));
    await until(() => !w.document.querySelector(".kontakt-foto-dialog"));
    assert.equal(k.foto, photo); assert.ok(k.fotoQuellen.includes("local"));
    assert.equal(k.fotoAlternativen.length, 0, "own file duplicated the already available image");
    const merged = T.fuehreZusammen(T.normalisiere({ kontakte: [
      { id: "full", vorname: "Person", nachname: "Example", firma: "Company", email: "p@example.test", foto: photo,
        fotoAlternativen: [{ foto: third, quellen: ["system"] }] },
      { id: "picked", vorname: "Person", foto: other, fotoManuell: true }
    ] }).kontakte).bleibt;
    assert.equal(merged.foto, other, "merging a fuller card replaced the existing explicit photo choice");
    assert.equal(T.kontaktFotoVarianten(merged).length, 3, "duplicate merge discarded photo alternatives");
    w.App.baumStand({ an: true, moeglich: true, kennung: "local", eingang: [],
      partner: [{ kennung: "peer", name: "Peer", bestaetigt: true, kontaktFaehigkeiten: { kontakt_sync: [2] } }] });
    const sharedCard = T.kontaktKarte(k); w.document.body.append(sharedCard);
    const originalAlternatives = k.fotoAlternativen, originalSources = k.fotoQuellen;
    Object.defineProperty(k, "fotoAlternativen", { configurable: true, enumerable: true, get() { throw Error("Private gallery read during sharing"); } });
    Object.defineProperty(k, "fotoQuellen", { configurable: true, enumerable: true, get() { throw Error("Private source list read during sharing"); } });
    sharedCard.querySelector(".baum-freigabe button").click();
    const confirm = w.document.querySelector("#dialog-ja");
    assert.equal(confirm.textContent, "Share"); confirm.click();
    await until(() => messages.some(m => m.cmd === "baum_teilen" && m.art === "kontakt"));
    const shared = messages.findLast(m => m.cmd === "baum_teilen" && m.art === "kontakt").inhalt;
    assert.equal(shared.fotoAlternativen, undefined); assert.equal(shared.fotoQuellen, undefined); assert.equal(shared.baumKontakt, undefined);
    delete k.fotoAlternativen; delete k.fotoQuellen; k.fotoAlternativen = originalAlternatives; k.fotoQuellen = originalSources;
    sharedCard.remove();
    console.log("CONTACT PHOTO SELECTION PASSED: " + web);
  } finally { w.close(); }
}
(async () => {
  for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) await check(web);
})().catch(error => { console.error(error); process.exitCode = 1; });
