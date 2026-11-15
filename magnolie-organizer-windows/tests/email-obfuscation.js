"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom"), { webcrypto } = require("node:crypto");
(async () => {
  for (const web of require("./web-test-roots")) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      runScripts: "outside-only", url: "https://email.test.invalid/", pretendToBeVisual: true });
    const w = dom.window, sent = [];
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(raw) { sent.push(JSON.parse(raw)); } } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("window.OrganizerTest = {", "window.OrganizerTest = { emailAdressenImText, emailTextElement,"));
      if (w.document.readyState === "loading") await new Promise(resolve => w.document.addEventListener("DOMContentLoaded", resolve, { once: true }));
      await new Promise(resolve => w.setTimeout(resolve, 0));
      const T = w.OrganizerTest;
      for (const field of ["email", "emails", "emailEintraege"]) {
        const value = address => field === "email" ? address : field === "emails" ? [address] : [{ wert: address }];
        for (const spelling of ["Maik3531(at)Gmail.com", "Maik3531[at]Gmail.com", "Maik3531[AT]Gmail.com"]) {
          w.App.init({ neu: false, daten: { kontakte: [] } });
          T.mergeKontakte([{ vorname: "Fixture", [field]: value(spelling) }]);
          assert.equal(T.daten().kontakte[0].email, "maik3531@gmail.com", "Fresh import discarded obfuscated mail");
          w.App.init({ neu: false, daten: { kontakte: [{ id: "mail", vorname: "Fixture", [field]: value("maik3531@gmail.com") }] } });
          T.mergeKontakte([{ vorname: "Fixture", [field]: value(spelling), notiz: "Matched" }]);
          assert.equal(T.daten().kontakte.length, 1, field + " discarded or duplicated an obfuscated address");
          assert.equal(T.daten().kontakte[0].email, "maik3531@gmail.com");
          assert.equal(T.daten().kontakte[0].notiz, "Matched");
        }
      }
      const text = "Mail: Maik3531(at)Gmail.com oder Alex+tag[at]Example.test. <script>unsafe</script>";
      const rendered = T.emailTextElement("sms-text", text);
      assert.equal(rendered.textContent, text); assert.equal(rendered.querySelector("script"), null);
      const links = rendered.querySelectorAll("a"); assert.equal(links.length, 2);
      assert.equal(links[0].textContent, "Maik3531(at)Gmail.com");
      assert.equal(links[0].getAttribute("href"), "mailto:maik3531@gmail.com");
      assert.equal(sent.filter(value => value.cmd === "mail").length, 0, "Recognition sent mail without a click");
      links[0].click(); assert.equal(sent.filter(value => value.cmd === "mail").at(-1).email, "maik3531@gmail.com");
      assert.equal(T.emailAdressenImText("a(at)b(at)example.test a@@example.test").length, 0, "Malformed address was guessed");
      w.App.init({ neu: false, daten: { notizen: [{ id: "note", titel: "Synthetic mail", text, html: "" }] } });
      await T.wechsel("notizen");
      w.document.querySelector('[data-notiz-id="note"]')?.click();
      const note = T.daten().notizen.find(value => value.id === "note");
      const before = JSON.stringify(note);
      const action = w.document.querySelector(".notiz-email-aktionen button");
      assert.ok(action, "Actual note editor did not recognize obfuscated mail");
      action.click();
      assert.equal(JSON.stringify(note), before, "Recognizing/using a note email changed stored note content");
      assert.equal(note.text, text);
      console.log("EMAIL OBFUSCATION PASSED:", web);
    } finally { w.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
