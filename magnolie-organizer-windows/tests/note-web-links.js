"use strict";
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const { JSDOM } = require("jsdom"), { webcrypto } = require("node:crypto");
let completed = 0;
const watchdog = setTimeout(() => { console.error("Note web-link test stalled after", completed); process.exit(1); }, 40000);
(async () => {
  for (const web of require("./web-test-roots")) {
    const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
      runScripts: "outside-only", url: "https://notes.test.invalid/", pretendToBeVisual: true });
    const w = dom.window, sent = [], opened = []; let network = 0;
    try {
      Object.defineProperty(w, "crypto", { value: webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
      w.fetch = () => { network++; throw Error("Recognition must not fetch"); };
      w.XMLHttpRequest = class { constructor() { network++; throw Error("Recognition must not request"); } };
      w.__MAGNOLIE_BRUECKE__ = "test";
      w.webkit = { messageHandlers: { test: { postMessage(raw) { sent.push(JSON.parse(raw)); } } } };
      w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
      w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("window.OrganizerTest = {", "window.OrganizerTest = { webLinkZiel, webLinksImText, notizWebLinks,"));
      if (w.document.readyState === "loading") await new Promise(resolve => w.document.addEventListener("DOMContentLoaded", resolve, { once: true }));
      await new Promise(resolve => setTimeout(resolve, 0));
      const T = w.OrganizerTest;
      const urls = text => Array.from(T.webLinksImText(text), value => value.ziel);
      assert.deepEqual(urls("See (https://Example.test/path), HTTP://example.test/next. End."), ["https://example.test/path", "http://example.test/next"]);
      assert.deepEqual(urls("https://example.test/wiki/Thing_(part). [https://example.test/end]."), ["https://example.test/wiki/Thing_(part)", "https://example.test/end"]);
      assert.deepEqual(urls("https://example.test/?a=1&b=two#part"), ["https://example.test/?a=1&b=two#part"]);
      assert.deepEqual(urls("http://[::1]:8080/path."), ["http://[::1]:8080/path"]);
      for (const text of ["javascript:https://example.test", "file:https://example.test", "xhttps://example.test", "www.example.test", "//example.test", "https://user:pass@example.test", "https://example.test\\evil", "https://", "https://example.test/\u202Eevil", "https://example.test/" + "x".repeat(4096)])
        assert.deepEqual(urls(text), [], "Unsafe/ambiguous URL guessed: " + text.slice(0, 90));
      assert.equal(T.webLinksImText(Array.from({ length: 50 }, (_, n) => "https://example.test/" + n).join(" ")).length, 32);
      for (const text of ["https:////example.test", "https://example.test/\u200Fhidden", "https://example.test/\u061Crtl"])
        assert.deepEqual(urls(text), []);
      assert.equal(T.webLinkZiel("https://example.test/path!"), "https://example.test/path!", "Explicit HTML targets must not be punctuation-trimmed");
      const html = '<p>Visit (https://example.test/path), then <a href="https://example.test/path">https://wrong-label.test</a> and <a href="https://other.test/target">Documentation</a>.</p>';
      const text = "Visit (https://example.test/path), then https://wrong-label.test and Documentation.";
      w.App.init({ neu: false, daten: { notizen: [{ id: "web-note", titel: "Synthetic links", text, html }] } });
      const note = T.daten().notizen.find(value => value.id === "web-note"), before = JSON.stringify(note);
      await T.wechsel("notizen"); w.document.querySelector('[data-notiz-id="web-note"]')?.click();
      assert.equal(JSON.stringify(note), before, "Opening recognition changed saved note/revision");
      const editor = w.document.querySelector("#notiz-text"), editorBefore = editor.innerHTML;
      const actions = [...w.document.querySelectorAll(".notiz-web-aktionen a")];
      assert.deepEqual(actions.map(link => link.href), ["https://example.test/path", "https://other.test/target"]);
      assert.ok(actions.every(link => !editor.contains(link) && link.rel === "noopener noreferrer"));
      assert.equal(network, 0); assert.equal(opened.length, 0);
      w.document.addEventListener("click", event => {
        const link = event.target.closest(".notiz-web-aktionen a");
        if (link) { event.preventDefault(); opened.push(link.href); }
      });
      actions[0].click();
      assert.deepEqual(opened, ["https://example.test/path"]);
      assert.equal(JSON.stringify(note), before, "Explicit open action rewrote stored note/revision");
      assert.equal(editor.innerHTML, editorBefore, "Recognition/open rewrote editor or undo content");
      const detached = w.document.createElement("div");
      detached.innerHTML = '<a href="javascript:alert(1)">https://example.test/hidden</a><a href="https://user:pw@example.test">bad</a><p>https://new.test/plain</p>';
      const untouched = detached.innerHTML;
      assert.deepEqual(Array.from(T.notizWebLinks(detached), value => value.ziel), ["https://new.test/plain"]);
      assert.equal(detached.innerHTML, untouched);
      editor.innerHTML = "https://new.test/plain"; editor.dispatchEvent(new w.Event("input", { bubbles: true }));
      assert.deepEqual([...w.document.querySelectorAll(".notiz-web-aktionen a")].map(link => link.href), ["https://new.test/plain"]);
      await new Promise(resolve => setTimeout(resolve, 120));
      assert.equal(note.text, "https://new.test/plain"); assert.equal(note.html, "https://new.test/plain");
      assert.equal(editor.querySelector("a"), null, "Typing added generated hyperlinks to saved content");
      assert.equal(network, 0); assert.equal(sent.some(value => /extern|browser|url/.test(value.cmd || "")), false);
      console.log("NOTE WEB LINKS PASSED:", web, "HTTP(S), boundaries, unsafe schemes, existing targets, dedup, click-only action, unchanged stored content and typing"); completed++;
    } finally { w.close(); }
  }
  assert.equal(completed, require("./web-test-roots").length);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
