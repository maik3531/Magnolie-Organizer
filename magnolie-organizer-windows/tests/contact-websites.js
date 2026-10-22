"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
const source = fs.readFileSync(file, "utf8").split("async function run(web)")[0].replace(
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));',
  'w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8").replace("speichereJetzt: speichereJetzt,", "kontaktFormular, kontaktWebseiten, speichereJetzt: speichereJetzt,"));');
harness._compile(source + "\nmodule.exports={boot,roots};", file);
const watchdog = setTimeout(() => { console.error("Contact website test timed out"); process.exit(1); }, 30000);
(async () => {
  for (const web of harness.exports.roots) {
    const lines = ["item1.URL;TYPE=WORK:https://example.test/company", "item1.X-ABLABEL:Office", "URL;TYPE=HOME:http://example.test/private", "X-OWNED:preserved"];
    const b = await harness.exports.boot(web, { kontakte: [{ id: "website", vorname: "Website", nachname: "Fixture", email: "owned@example.test", vcardRoundtrip: lines }] });
    try {
      const contact = b.t.daten().kontakte.find(value => value.id === "website");
      let card = b.t.kontaktKarte(contact);
      assert.deepEqual([...card.querySelectorAll(".kontakt-web")].map(node => node.href), ["https://example.test/company", "http://example.test/private"]);
      assert.ok([...card.querySelectorAll(".kontakt-web")].every(node => node.textContent === "Web" && node.querySelector("svg")), "Web action must include the globe and Web label");
      assert.ok([...card.querySelectorAll("button")].some(node => node.textContent === "Email"));
      assert.ok(![...card.querySelectorAll("button")].some(node => node.textContent === "Message"));
      let form = b.t.kontaktFormular(contact); b.w.document.body.append(form);
      const fields = [...form.querySelectorAll(".kontakt-webseite")];
      assert.deepEqual(fields.map(node => node.value), ["https://example.test/company", "http://example.test/private"], "Imported vCard URL properties must be available in the editor");
      assert.ok(fields.every(node => node.closest(".kontakt-weitere")));
      const save = () => [...form.querySelectorAll("button")].find(node => ["Save", "Save changes"].includes(node.textContent)).click();
      save();
      assert.deepEqual(Array.from(contact.vcardRoundtrip), lines, "Unedited imported website parameters and other vCard metadata must survive saving");
      form.remove();
      form = b.t.kontaktFormular(contact); b.w.document.body.append(form);
      const first = form.querySelector(".kontakt-webseite"); first.value = "https://example.test/new";
      first.dispatchEvent(new b.w.Event("input", { bubbles: true }));
      assert.ok(contact.vcardRoundtrip.includes(lines[0]), "Website edits must remain a draft before saving");
      save();
      assert.deepEqual(Array.from(b.t.kontaktWebseiten(contact)), ["http://example.test/private", "https://example.test/new"]);
      assert.ok(contact.vcardRoundtrip.includes(lines[1]) && contact.vcardRoundtrip.includes(lines[3]));
      const reloaded = await harness.exports.boot(web, JSON.parse(JSON.stringify(b.t.daten())));
      try {
        assert.equal(reloaded.t.kontaktKarte(reloaded.t.daten().kontakte.find(value => value.id === "website")).querySelectorAll(".kontakt-web").length, 2);
      } finally { reloaded.close(); }
      card = b.t.kontaktKarte({ vorname: "No site", vcardRoundtrip: ["URL:javascript:alert(1)", "URL:file:///tmp/owned", "URL:https://user:password@example.test"] });
      assert.equal(card.querySelectorAll(".kontakt-web").length, 0);
      assert.equal(b.t.kontaktKarte({ vorname: "Unqualified", vcardRoundtrip: ["URL:www.example.test"] }).querySelector(".kontakt-web").href, "https://www.example.test/", "An imported www address must not open as a relative application link");
      form.remove();
      [...b.w.document.querySelectorAll("#kontakt-formular button")].find(node => node.textContent === "Cancel")?.click();
      if (b.saves().length) b.ack();
      b.w.eval(fs.readFileSync(path.join(web, "mcp-protocol.js"), "utf8"));
      const post = b.w.webkit.messageHandlers.regression.postMessage;
      b.w.webkit.messageHandlers.regression.postMessage = text => {
        post(text); const message = JSON.parse(text);
        if (message.cmd === "speichern") queueMicrotask(() => b.w.App.gespeichert({ id: message.id, ok: true }));
      };
      let sequence = 0;
      const rpc = async (method, params) => {
        const invocation = (++sequence).toString(16).padStart(48, "0");
        await b.w.App.mcpRequest({ session: "b".repeat(48), invocation, message: { jsonrpc: "2.0", method, ...(!method.startsWith("notifications/") ? { id: sequence } : {}), params } });
        return b.messages.find(message => message.cmd === "mcp_antwort" && message.invocation === invocation)?.response;
      };
      await rpc("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "website-fixture", version: "1" } });
      await rpc("notifications/initialized", {});
      const read = await rpc("tools/call", { name: "organizer_contact_read", arguments: { id: contact.id } });
      assert.ok(read.result, JSON.stringify(read));
      const before = read.result.structuredContent;
      const changed = (await rpc("tools/call", { name: "organizer_contact_update", arguments: { id: contact.id, expected_revision: before.revision, websites: ["https://example.test/mcp"] } })).result;
      assert.equal(changed.isError, false, JSON.stringify(changed));
      assert.deepEqual(Array.from(b.t.kontaktWebseiten(contact)), ["https://example.test/mcp"]);
      assert.ok(contact.vcardRoundtrip.includes("X-OWNED:preserved"));
      console.log("CONTACT WEBSITES PASS: imported URLs, advanced editor, preserved metadata, draft/save/reopen, globe/Web and Email " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
