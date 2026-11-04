"use strict";

const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath; harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] +
  "\nmodule.exports = {boot, roots};", harnessPath);
const id = "11111111-1111-4111-8111-111111111111";
const styles = [], layouts = [];
for (const web of harness.exports.roots) {
  const css = fs.readFileSync(path.join(web, "stil.css"), "utf8");
  const start = css.indexOf(".geraet-dialog { width: min(500px");
  assert.ok(start >= 0);
  styles.push(css.slice(start, css.indexOf(".notiz-anpassen-dialog", start))
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\s+/g, " ").trim());
  const js = fs.readFileSync(path.join(web, "anwendung.js"), "utf8");
  layouts.push(js.slice(js.indexOf("  function baueGeraeteStatusKoerper("), js.indexOf("  function baueTelefonPersonalSync(")));
}
assert.equal(styles[0], styles[1], "Linux/Windows device-status CSS drifted");
assert.equal(layouts[0], layouts[1], "Linux/Windows device-status DOM layout drifted");

(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) for (const locale of ["en", "de"]) for (const mode of ["legacy", "shared", "offline"]) {
    const b = await harness.exports.boot(web, { notizen: [{ id: "keep", titel: "Keep", text: "Unchanged", html: "Unchanged" }],
      einstellungen: { adressen: { kommunikation: { anruf: { telefonId: id } } } } });
    try {
      if (locale === "de") {
        b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8")); b.w.MagnolieI18n.setLocale("de");
      }
      const before = JSON.stringify(b.t.daten());
      b.t.oeffneEinstellungen(); b.w.document.querySelector("#einst-tab-baum").click();
      const peer = { device_id: id, display_name: "Notes fixture", fingerprint: "AAAA-BBBB", own_device: true,
        remote_own_device: true, auto_wifi: false, state: mode === "offline" ? "offline" : "online_wifi",
        transport: mode === "offline" ? "" : "wifi", local_grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } },
        grants: { grants: { personal_notes_sync: true, personal_tasks_sync: true } } };
      if (mode === "shared") peer.shared_sync = { supported: true, initialized: true, ready: true,
        values: { content_mode: "phone_import", auto_mode: "manual", skip_deletions: true, custom_enabled: false,
          time_enabled: false, time_mode: "phone_import" } };
      b.w.App.telefonStand({ enabled: true, listening: true, peers: [peer], bluetooth: { available: false, devices: [] },
        kdeconnect: { available: false, paired: false, reason: "no_device" } });
      const d = b.w.document, personal = d.querySelector('.telefon-karte .telefon-liste .telefon-personal-sync');
      assert.ok(personal && !personal.open && personal.querySelector("summary"));
      assert.equal(d.querySelector('.telefon-kde-karte .telefon-personal-sync'), null);
      assert.ok(personal.querySelector(mode === "shared" ? '[data-shared-sync-start]' : '[data-personal-sync-action]'));
      if (mode === "shared") assert.ok(personal.querySelector('[data-shared-sync-field="auto_mode"]'));
      else assert.ok(personal.querySelector('[data-personal-auto-peer]'));
      b.w.App.geraetOeffnen({ kennung: id, status: { online: mode !== "offline", model: "Pixel fixture", battery_percent: 73 } });
      const dialog = d.querySelector("#geraet-dialog");
      assert.equal(dialog.querySelector(".telefon-personal-sync"), null);
      assert.equal(dialog.querySelector("[data-personal-sync-action]"), null);
      assert.ok(dialog.querySelector(".geraet-koerper > .geraet-details"));
      assert.ok(dialog.querySelector(".geraet-koerper > .geraet-seite > .geraet-telefon"));
      assert.ok(dialog.querySelector(".geraet-seite > .geraet-akku-zeile"));
      assert.equal(dialog.querySelectorAll(".geraet-dialog-knoepfe button").length, 2);
      assert.equal(JSON.stringify(b.t.daten()), before, "opening connection/status changed saved user data or grants");
      // Existing startup capability advertisement is not a grant/settings/run.
      assert.deepEqual(b.messages.filter(message => message.cmd !== "personal_sync_desktop_features" &&
        /^personal_sync_|^telefon_ein$|^telefon_entfernen$/.test(message.cmd))
        .map(message => message.cmd), [], `${mode}/${locale}: rendering started synchronization or changed native preferences`);
      passed++;
    } finally { b.close(); }
  }
  console.log(`Personal-sync placement/device-status parity: ${passed} cases passed (source-host DOM/CSS, not installed native GUI).`);
})().catch(error => { console.error(error); process.exitCode = 1; });
