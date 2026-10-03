"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { webcrypto, createHash } = require("node:crypto"), { JSDOM } = require("jsdom");

async function check(web) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://app.magnolie.invalid/index.html", pretendToBeVisual: true });
  const w = dom.window, commands = [];
  try {
    Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
    w.__MAGNOLIE_BRUECKE__ = "test";
    w.webkit = { messageHandlers: { test: { postMessage(message) {
      const command = typeof message === "string" ? JSON.parse(message) : message;
      commands.push(command);
      if (command.cmd === "speichern") queueMicrotask(() => w.App.gespeichert({ id: command.id, ok: true,
        standSha256: createHash("sha256").update(command.text).digest("hex") }));
    } } } };
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8")); w.MagnolieI18n.setLocale("en");
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8")); w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
    for (const validSource of [true, false]) {
      w.App.init({ neu: false, daten: {
        notizen: [{ id: "shared", titel: "Shared with laptop", text: "Shared content", angelegt: 1,
          baumFreigabe: { id: "home:shared", partner: ["laptop"], anhangPartner: [] } },
          { id: "private", titel: "Private home note", text: "Never shared", angelegt: 2 }],
        aufgaben: [{ id: "delegated", titel: "Delegated task", delegiertAn: "laptop" },
          { id: "private-task", titel: "Private home task" }] } });
      await new Promise((resolve, reject) => w.OrganizerTest.nachDauerhaftemSpeichern(resolve, reject));
      commands.length = 0;
      w.App.baumStand({ an: true, kennung: "home", partner: [
        { kennung: "laptop", name: "Laptop", bestaetigt: true, vertraut: true },
        { kennung: "office", name: "Office", bestaetigt: true, vertraut: true,
          weitergabeVon: "laptop", weitergabeQuelle: validSource ? "laptop" : "" }],
        eingang: [{ id: "request-" + validSource, von: "office", art: "sync_anfrage", inhalt: { art: "sync_anfrage" } }] });
      await new Promise(resolve => setTimeout(resolve, 30));
      const outgoing = commands.filter(value => ["baum_teilen", "baum_delegieren"].includes(value.cmd));
      assert(!JSON.stringify(outgoing).includes("Private home"), "delegation must not disclose an unshared home note or task");
      if (validSource) {
        assert(outgoing.some(value => value.inhalt?.titel === "Shared with laptop"), "the previously shared note was not offered to the office device");
        assert(outgoing.some(value => value.aufgabe?.titel === "Delegated task"), "the explicitly delegated task was not offered");
      } else assert.equal(outgoing.length, 0, "a removed or rekeyed sponsor must not unlock the complete home collection");
    }
    commands.length = 0;
    w.App.baumPaarungsdatei({ ok: true, art: "importiert", weitergabe: true, kennung: "home", name: "Home" });
    const request = commands.find(value => value.cmd === "baum_teilen");
    assert.equal(request?.art, "sync_anfrage");
    assert.equal(request?.kennung, "home");
    assert.equal(commands.filter(value => value.cmd === "baum_delegieren").length, 0,
      "accepting a connection must not upload the office collection");
  } finally { w.close(); }
}

(async () => {
  for (const web of [path.resolve(__dirname, "../app/web"), path.resolve(__dirname, "../../magnolie-organizer/web")]) await check(web);
  console.log("Three-device sharing: existing data scope and request-only acceptance passed on both desktops.");
})().catch(error => { console.error(error); process.exitCode = 1; });
