"use strict";
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), assert = require("node:assert/strict");
const vm = require("node:vm");
const file = path.join(__dirname, "desktop-state-regressions.js");
const harness = new Module(file, module); harness.filename = file; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(file, "utf8").split("async function run(web)")[0] + "\nmodule.exports={boot,roots};", file);
(async () => {
  for (const web of harness.exports.roots) {
    const catalogs = fs.readdirSync(path.join(web, "i18n")).filter(name => name.endsWith(".js"));
    for (const name of catalogs) {
      let messages;
      vm.runInNewContext(fs.readFileSync(path.join(web, "i18n", name), "utf8"), { window: { MagnolieI18n: { registerCatalog: (_language, value) => { messages = value.messages; } } } });
      for (const label of ["Fax printer", "Network fax server", "Online fax service", "Save as PDF", "Website"])
        assert.ok(messages[label], name + ": missing fax option label " + label);
    }
    const b = await harness.exports.boot(web, { notizen: [
      { id: "selected", titel: "Selected", text: "SELECTED FAX CONTENT", html: "SELECTED FAX CONTENT" },
      { id: "other", titel: "Other", text: "UNSELECTED FAX CONTENT", html: "UNSELECTED FAX CONTENT" }] });
    try {
      if (b.saves().length) b.ack();
      const preview = b.t.oeffneDruckvorschau(b.t.daten().notizen[0], "notizen");
      const before = b.messages.length;
      preview.querySelector("#auswahl-fax-wege").click();
      const dialog = b.w.document.querySelector("#fax-wege"), route = dialog.querySelector("#fax-weg");
      assert.deepEqual(Array.from(route.options, value => value.value), ["local", "server", "online"]);
      assert.ok(!b.messages.slice(before).some(value => ["drucken", "notiz_versand"].includes(value.cmd)), "Opening fax routes must not print or send");
      route.value = "server"; route.dispatchEvent(new b.w.Event("change"));
      assert.ok(dialog.querySelector("#notiz-versand-faxserver"), "Network fax configuration must be offered even without a configured fax client");
      assert.equal(dialog.querySelector("#notiz-versand-aktiv").checked, false);
      route.value = "online"; route.dispatchEvent(new b.w.Event("change"));
      const url = dialog.querySelector("#fax-online-url"), link = dialog.querySelector("a");
      for (const value of ["javascript:alert(1)", "file:///tmp/owned", "https://user:password@example.test/"]) {
        url.value = value; url.dispatchEvent(new b.w.Event("input")); assert.equal(link.hidden, true);
      }
      url.value = "https://fax.example.test/upload"; url.dispatchEvent(new b.w.Event("input"));
      assert.equal(link.hidden, false); assert.equal(link.href, "https://fax.example.test/upload");
      assert.ok(!b.messages.slice(before).some(value => value.cmd === "notiz_versand"), "Selecting an online provider must not transmit a document");
      [...dialog.querySelectorAll("button")].find(button => button.textContent === "Save as PDF").click();
      const print = b.messages.findLast(value => value.cmd === "drucken");
      assert.ok(print.html.includes("SELECTED FAX CONTENT") && !print.html.includes("UNSELECTED FAX CONTENT"));
      [...dialog.querySelectorAll("button")].find(button => button.textContent === "Close").click();
      assert.ok(!b.w.document.querySelector("#fax-wege"));
      [...preview.querySelectorAll(".druck-fuss button")].find(button => button.textContent === "Cancel").click();
      for (const section of ["planer", "gesundheit"]) {
        const document = b.t.oeffneDruckvorschau(null, section), start = b.messages.length;
        const fax = document.querySelector("#auswahl-fax-wege");
        assert.ok(fax && !fax.disabled, section + ": independent selection-options view must also offer fax routes");
        fax.click();
        const choices = b.w.document.querySelector("#fax-wege");
        assert.equal(choices.querySelector("#fax-weg").options.length, 3);
        assert.ok(!b.messages.slice(start).some(message => ["drucken", "notiz_versand"].includes(message.cmd)), section + ": opening fax choices must not print or send");
        [...choices.querySelectorAll("button")].find(button => button.textContent === "Close").click();
        if (section === "planer") {
          const layout = document.querySelector("#planer-druck-art"); layout.value = "time"; layout.dispatchEvent(new b.w.Event("change"));
          const allDays = document.querySelector("#zeit-druck-alle-tage"); allDays.checked = false; allDays.dispatchEvent(new b.w.Event("change"));
          assert.equal(fax.disabled, true, "No selected time-report days must not produce an empty fax document");
        }
        [...document.querySelectorAll(".druck-fuss button")].find(button => button.textContent === "Cancel").click();
      }
      console.log("FAX OPTIONS PASS: discoverable local/network/online routes, explicit preparation only and selected document " + web);
    } finally { b.close(); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
