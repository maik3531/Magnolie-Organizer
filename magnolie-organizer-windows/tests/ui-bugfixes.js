"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const root = path.resolve(__dirname, "../..");
const harnessPath = path.join(__dirname, "save-custom-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(__dirname);
harness._compile(fs.readFileSync(harnessPath, "utf8").split("const cases = [")[0] + "\nmodule.exports = { boot };", harnessPath);
const contracts = fs.existsSync(path.join(root, "contracts")) ? path.join(root, "contracts") : path.join(__dirname, "../contracts");
const contract = JSON.parse(fs.readFileSync(path.join(contracts, "ui-bugfixes.json")));
const probe = fs.readFileSync(path.join(__dirname, "ui-bugfix-probe.js"), "utf8");

(async () => {
  let count = 0;
  const roots = [path.resolve(__dirname, "../app/web")];
  const linux = path.join(root, "magnolie-organizer/web");
  if (fs.existsSync(linux)) roots.push(linux);
  for (const web of roots) {
    const relative = path.relative(root, web), b = await harness.exports.boot(web);
    try {
      for (const name of fs.readdirSync(path.join(web, "i18n"))) b.w.eval(fs.readFileSync(path.join(web, "i18n", name), "utf8"));
      b.w.eval(probe);
      assert.equal(b.t.daten().einstellungen.adressen.smsSchedulingEnabled, false);
      for (const [locale, values] of Object.entries(contract.translations)) {
        b.w.MagnolieI18n.setLocale(locale);
        for (const i of [0, 1, 2, 3, 5, 6, 7]) assert.equal(b.w.MagnolieI18n.gettext(contract.translations.en[i]), values[i]);
        for (const screen of ["sms-off", "settings", "sms-on", "plans", "designer", "device"]) {
          assert.equal(b.w.uiBugfixPrepare(locale, screen), true); count++;
        }
      }
      assert.equal(b.messages.filter(m => m.cmd === "kde_sms_senden").length, 0, "UI checks must never dispatch SMS");
       assert.equal(b.messages.filter(m => (m.cmd === "telefon_freigabe" && m.an === true) ||
        (m.cmd === "personal_sync_senden" && m.art === "personal_sync.custom_settings" && m.inhalt.enabled === true)).length, 0,
         "Scheduling preference must never grant transport or personal-sync permissions");
       const notifications = b.messages.filter(m => m.cmd === "telefon_freigabe" &&
         m.name === "selected_notifications_readonly");
       assert.equal(notifications.length, 0, "Unconfirmed pairing must not receive notification defaults through status rendering");
      console.log("PASS " + relative + ": 20 locales, toggle/review/designer/live tab label");
    } finally { b.close(); }
  }
  console.log(count + " UI/locale scenarios passed; capture-only bridge, no SMS transport");
})().catch(error => { console.error(error); process.exitCode = 1; });
