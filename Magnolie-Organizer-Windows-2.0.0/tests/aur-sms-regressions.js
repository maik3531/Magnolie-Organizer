"use strict";
// No resource loader or native bridge: all outgoing commands terminate here.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { webcrypto } = require("node:crypto");
const { JSDOM } = require("jsdom");

async function check(web, scenario) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://sms-test.invalid/", pretendToBeVisual: true
  });
  const w = dom.window, d = w.document, commands = [];
  let reject = false;
  Object.defineProperty(w, "crypto", { value: webcrypto });
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.fetch = () => { throw new Error("network forbidden"); };
  w.XMLHttpRequest = w.WebSocket = class { constructor() { throw new Error("network forbidden"); } };
  w.__MAGNOLIE_BRUECKE__ = "capture";
  w.webkit = { messageHandlers: { capture: { postMessage(raw) {
    const value = JSON.parse(raw);
    if (value.cmd === "kde_sms_senden" && reject) throw new Error("local non-acceptance");
    commands.push(value);
    if (value.cmd === "kde_sms_senden" && scenario === "synchronous")
      w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: value.clientRef });
  } } } };
  w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
  w.MagnolieI18n.setLocale("en");
  w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace(
    "window.OrganizerTest = {", "window.OrganizerTest = { telefonSchluessel, telefonListe, telefonHeimatland, oeffneSmsDialog,"));
  await new Promise(resolve => setTimeout(resolve, 0));
  const T = w.OrganizerTest;
  const input = value => {
    const field = d.querySelector(".sms-eingabe");
    field.value = value; field.dispatchEvent(new w.Event("input", { bubbles: true }));
  };
  const sent = () => commands.filter(value => value.cmd === "kde_sms_senden");
  const open = () => {
    w.App.telefonStand({ peers: [], kdeconnect: { available: true, device_count: 1, device_id: "a".repeat(32), device_fingerprint: "1".repeat(64) } });
    T.oeffneSmsDialog({ id: "synthetic", mobil: "07700 900123", vorname: "Fixture" }, "07700 900123");
  };
  try {
    w.App.init({ daten: { einstellungen: { allgemein: { handbuchHinweisGezeigt: true },
      regional: { homeCountry: "GB" }, adressen: { landCode: "GB" } } }, neu: false,
      regional: { language: "en", homeCountry: "GB", timeZone: "Europe/London" } });
    if (scenario === "region") {
      for (const [country, national, international] of [
        ["GB", "07700 900123", "+447700900123"], ["DE", "0170 1234567", "+491701234567"],
        ["AT", "0664 1234567", "+436641234567"], ["CH", "079 1234567", "+41791234567"],
        ["FR", "06 12 34 56 78", "+33612345678"], ["IT", "02 12345678", "+390212345678"],
        ["US", "202 555 0123", "+12025550123"], ["AU", "0412 345 678", "+61412345678"]]) {
        T.daten().einstellungen.regional.homeCountry = country;
        assert.equal(T.telefonSchluessel(national), international, country);
        assert.equal(T.telefonSchluessel(international, "ZZ"), international);
        assert.equal(T.telefonListe({ telefone: [{ wert: national, typen: ["CELL"] },
          { wert: international, typen: ["CELL"] }] }).length, 1, country + " dedup");
        const raw = { einstellungen: { regional: { homeCountry: country } },
          smsPlanung: [{ id: "p", nummer: national, text: "Synthetic", zeit: 1, status: "planned" }],
          smsVerlauf: [{ id: "h", nummer: national, text: "Synthetic", zeit: 1, richtung: "ausgang" }] };
        T.daten().einstellungen.regional.homeCountry = "DE";
        const normalized = T.normalisiere(raw);
        assert.equal(normalized.smsPlanung[0].nummer, international, country + " restored plan");
        assert.equal(normalized.smsPlanung[0].land, country, country + " stable plan country");
        assert.equal(normalized.smsVerlauf[0].nummer, international, country + " restored history");
        normalized.einstellungen.regional.homeCountry = "DE";
        assert.equal(T.normalisiere(normalized).smsPlanung[0].land, country, country + " plan survives region change");
      }
      assert.ok(!T.telefonSchluessel("07700900123", "ZZ").startsWith("+49"));
      const unknown = T.normalisiere({ einstellungen: { regional: { homeCountry: "ZZ" } },
        smsPlanung: [{ id: "unknown", nummer: "07700900123", text: "Synthetic", zeit: 1, status: "planned" }] });
      assert.equal(T.telefonHeimatland(unknown), "");
      assert.equal(unknown.smsPlanung[0].nummer, "07700900123", "unknown country must not drop archived SMS");
      T.daten().einstellungen.regional.homeCountry = "GB";
      open(); input("Synthetic"); d.querySelector(".sms-komponist > .hauptknopf").click();
      assert.equal(sent().at(-1).land, "GB");
      if (web.includes("Windows")) {
        assert.equal(sent().at(-1).device_id, "a".repeat(32));
        assert.equal(sent().at(-1).device_fingerprint, "1".repeat(64));
      }
      assert.equal(T.daten().smsVerlauf.at(-1).nummer, "+447700900123");
    } else {
      open(); input("Draft A");
      const send = d.querySelector(".sms-komponist > .hauptknopf");
      reject = scenario === "local-failure";
      send.click(); send.click();
      if (reject) {
        assert.equal(sent().length, 0);
        assert.equal(T.daten().smsVerlauf.at(-1).status, "failed");
        assert.equal(d.querySelector(".sms-eingabe").value, "Draft A");
        assert.equal(send.disabled, false);
        reject = false; send.click(); assert.equal(sent().length, 1);
      } else {
        assert.equal(sent().length, 1);
        const ref = sent()[0].clientRef;
        if (scenario === "synchronous") {
          assert.equal(d.querySelector(".sms-eingabe").value, "");
          console.log("PASS " + scenario + " " + web); return;
        }
        if (scenario === "revision") { input("Draft B"); input("Draft A"); }
        if (scenario === "changed") input("Draft B");
        if (scenario === "recipient") d.querySelector(".sms-nummer").dispatchEvent(new w.Event("change"));
        if (scenario === "queued") {
          w.App.kdeSmsStatus({ ok: true, state: "queued", client_ref: ref });
          assert.equal(d.querySelector(".sms-eingabe").value, "Draft A");
          assert.equal(send.disabled, true);
        }
        w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: "unrelated" });
        assert.equal(send.disabled, true);
        const failure = ["uncertain", "failed"].includes(scenario);
        w.App.kdeSmsStatus({ ok: !failure, state: failure ? scenario : "submitted", client_ref: ref });
        const expected = ["unchanged", "queued"].includes(scenario) ? "" : scenario === "changed" ? "Draft B" : "Draft A";
        assert.equal(d.querySelector(".sms-eingabe").value, expected, "ACK must match both snapshot and revision");
        input("New draft");
        w.App.kdeSmsStatus({ ok: true, state: "submitted", client_ref: ref });
        assert.equal(d.querySelector(".sms-eingabe").value, "New draft", "duplicate old ACK");
      }
    }
    console.log("PASS " + scenario + " " + web);
  } finally { w.close(); }
}

(async () => {
  let failed = false;
  const roots = [path.resolve(__dirname, "../app/web")];
  const linux = path.resolve(__dirname, "../../magnolie-organizer-2.0.0/web");
  if (fs.existsSync(linux)) roots.push(linux);
  const known = ["region", "revision", "recipient", "changed", "unchanged", "queued", "synchronous", "uncertain", "failed", "local-failure"];
  const scenarios = process.argv.slice(2).length ? process.argv.slice(2) : known;
  assert.ok(scenarios.every(name => known.includes(name)), "Unknown SMS scenario");
  for (const web of roots)
    for (const scenario of scenarios)
      try { await check(web, scenario); } catch (error) { failed = true; console.error("FAIL " + scenario + " " + web, error.message); }
  process.exitCode = Number(failed);
})().catch(error => { console.error(error); process.exitCode = 1; });
