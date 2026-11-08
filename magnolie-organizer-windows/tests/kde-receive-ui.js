"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");
const web = path.resolve(__dirname, "../app/web");

(async () => {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", pretendToBeVisual: true, url: "https://app.magnolie.invalid/" });
  const w = dom.window, sent = [];
  try {
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = "fixture";
    w.webkit = { messageHandlers: { fixture: { postMessage: value => sent.push(JSON.parse(value)) } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    await new Promise(resolve => w.document.readyState === "loading" ?
      w.document.addEventListener("DOMContentLoaded", resolve, { once: true }) : resolve());
    const init = data => w.App.init({ daten: data, neu: false, gesperrt: false, kennwort: false });
    const settle = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };
    const commands = () => sent.filter(x => /^kde_receive_/.test(x.cmd));
    init({});
    assert.equal(w.OrganizerTest.daten().einstellungen.sync.kdeEmpfang.dateien, false);
    const id = "a".repeat(32), later = "b".repeat(32);
    w.App.kdeEmpfangAngebot({ id: "invalid" }); assert.equal(commands().length, 0);
    w.App.kdeEmpfangAngebot({ id }); w.App.kdeEmpfangAngebot({ id });
    assert.equal(commands().length, 1); assert.equal(commands()[0].cmd, "kde_receive_angebot");
    assert.ok(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"));
    w.App.kdeEmpfangGeprueft({ id, live: true,
      files: [{ name: "<img src=x>.txt", size: 1 }, { name: "Second.txt", size: 2 }] });
    const hint = w.document.querySelector("#dialog-hinweis");
    assert.ok(hint.textContent.includes("<img src=x>.txt") && hint.textContent.includes("Second.txt"));
    assert.ok(!hint.querySelector("img") && hint.classList.contains("kde-dateiliste"));
    w.App.kdeEmpfangGeprueft({ id, live: true, files: [{ name: "duplicate response", size: 1 }] });
    assert.ok(hint.textContent.includes("Second.txt"), "Duplicate validation reply replaced the list being reviewed");
    w.document.querySelector("#dialog-ja").click(); await settle();
    const choices = commands().filter(x => x.cmd === "kde_receive_ziel_waehlen");
    assert.equal(choices.length, 1); assert.equal(choices[0].id, id);
    assert.ok(!choices[0].path && !choices[0].directory);
    w.App.kdeEmpfangAngebot({ id: later }); w.App.kdeEmpfangBeendet({ id: later });
    w.App.kdeEmpfangGeprueft({ id: later, live: true, files: [{ name: "expired", size: 1 }] });
    assert.ok(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"));
    w.App.kdeEmpfangAngebot({ id: later });
    w.App.kdeEmpfangGeprueft({ id: later, live: true, destination_fixed: true, files: [{ name: "remaining", size: 1 }] });
    w.document.querySelector("#dialog-nein").click(); await settle();
    assert.deepEqual(JSON.parse(JSON.stringify(commands().at(-1))), { cmd: "kde_receive_decide", id: later, accept: false });
    const before = commands().length;
    w.App.kdeEmpfangAngebot({ id });
    w.App.kdeEmpfangGeprueft({ id, live: true, files: [{ name: "revoked", size: 1 }] });
    w.App.kdeEmpfangBeendet({ id }); await settle();
    assert.equal(commands().length, before + 1, "Expired/revoked modal emitted an acceptance or duplicate rejection");
    w.App.kdeEmpfangAngebot({ id }); init({});
    w.App.kdeEmpfangGeprueft({ id, live: true, files: [{ name: "old owner", size: 1 }] });
    assert.ok(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"));

    const textId = "c".repeat(32);
    w.App.kdeEmpfangAngebot({ id: textId });
    w.App.kdeEmpfangGeprueft({ id: textId, live: true, kind: "clipboard", text: "<img src=x> received text", automatic: false });
    assert(w.document.querySelector("#dialog-hinweis").textContent.includes("<img src=x> received text"));
    assert.equal(w.document.querySelector("#dialog-hinweis img"), null);
    assert.equal(commands().at(-1).cmd, "kde_receive_angebot", "Clipboard applied before confirmation");
    w.document.querySelector("#dialog-ja").click(); await settle();
    assert.deepEqual(commands().at(-1), { cmd: "kde_receive_decide", id: textId, accept: true });
    w.App.kdeEmpfangBeendet({ id: textId });
    w.App.kdeEmpfangAngebot({ id: later });
    w.App.kdeEmpfangGeprueft({ id: later, live: true, kind: "clipboard", text: "explicit automatic mode", automatic: true });
    assert.deepEqual(commands().at(-1), { cmd: "kde_receive_decide", id: later, accept: true });
    assert(w.document.querySelector("#dialog-schleier").classList.contains("verborgen"));

    init({ einstellungen: { sync: { kdeEmpfang: { dateien: false, geraetId: "phone",
      ordner: "/home/phone/LinuxDownload", zwischenablage: true, zwischenablageAutomatisch: true } } } });
    const prefs = w.OrganizerTest.daten().einstellungen.sync.kdeEmpfang;
    assert.equal(prefs.ordner, "/home/phone/LinuxDownload"); assert.equal(prefs.zwischenablage, true);
    assert.equal(prefs.zwischenablageAutomatisch, true);
    assert.ok(!commands().some(x => x.directory === prefs.ordner || x.path === prefs.ordner),
      "A preserved Linux folder became a Windows receive destination");
    w.App.telefonStand({ peers: [], kdeconnect: { paired: true, available: true, device_id: "paired-fixture" } });
    w.document.querySelector("#einstellungen-schleier").classList.remove("verborgen");
    w.OrganizerTest.baueEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    const option = w.document.querySelector(".kde-empfang-option");
    assert.ok(option && option.querySelectorAll('input[type="checkbox"]').length === 1,
      "File reception must remain a separate setting");
    assert.equal(option.closest("#kde-erweiterte-funktionen"), null, "Basic receive settings were hidden inside advanced functions");
    const checkbox = option.querySelector("input"); assert.equal(checkbox.disabled, false);
    checkbox.checked = true; checkbox.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).deviceId, "paired-fixture");
    assert.equal(commands().at(-1).files, true);
    const chooseEach = w.document.querySelector("#kde-empfang-ordner-bei-annahme");
    chooseEach.checked = true; chooseEach.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).chooseEach, true);
    chooseEach.checked = false; chooseEach.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).chooseEach, false);
    const folderRow = w.document.querySelector(".kde-empfangsordner");
    folderRow.querySelector("button").click(); const folderRequest = commands().at(-1);
    assert.equal(folderRequest.cmd, "kde_receive_directory"); assert(folderRequest.requestId);
    w.App.kdeEmpfangsordner({ requestId: "foreign", pfad: "C:\\Ignored" });
    assert.equal(prefs.ordner, "/home/phone/LinuxDownload");
    w.App.kdeEmpfangsordner({ requestId: folderRequest.requestId, pfad: "C:\\Chosen-Receive" });
    assert.equal(prefs.ordner, "C:\\Chosen-Receive");
    assert.equal(commands().at(-1).directory, prefs.ordner);
    folderRow.querySelectorAll("button")[1].click();
    assert.equal(prefs.ordner, ""); assert.equal(commands().at(-1).directory, "");
    const textEnabled = w.document.querySelector("#kde-zwischenablage-an");
    const automaticText = w.document.querySelector("#kde-zwischenablage-automatisch");
    assert(textEnabled.checked && automaticText.checked, "Explicit existing clipboard choices were discarded");
    automaticText.checked = false; automaticText.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).clipboard, true); assert.equal(commands().at(-1).automaticClipboard, false);
    textEnabled.checked = false; textEnabled.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).clipboard, false); assert.equal(automaticText.disabled, true);
    assert.equal(prefs.zwischenablageAutomatisch, false);
    w.App.telefonStand({ peers: [], kdeconnect: { paired: false, available: false } });
    w.OrganizerTest.baueEinstellungen(); w.document.querySelector("#einst-tab-baum").click();
    const disable = w.document.querySelector(".kde-empfang-option input");
    assert.equal(disable.disabled, false, "Losing a paired device prevented revoking existing receive consent");
    disable.checked = false; disable.dispatchEvent(new w.Event("change"));
    assert.equal(commands().at(-1).files, false); assert.equal(commands().at(-1).deviceId, "");
    console.log("PASS Windows KDE complete-list confirmation / native liveness / one chooser / revocation / cross-platform preferences");
  } finally { dom.window.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
