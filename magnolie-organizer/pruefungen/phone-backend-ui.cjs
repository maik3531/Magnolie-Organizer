"use strict";

// Reuse the existing isolated full-frontend jsdom harness; no native service,
// scheduler, pairing, file consent or network worker is started.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module");
const assert = require("node:assert/strict");
const harnessPath = path.resolve(__dirname, "../../magnolie-organizer-windows/tests/desktop-state-regressions.js");
const harness = new Module(harnessPath, module);
harness.filename = harnessPath;
harness.paths = Module._nodeModulePaths(path.dirname(harnessPath));
harness._compile(fs.readFileSync(harnessPath, "utf8").split("async function run(web)")[0] +
  "\nmodule.exports = {boot, roots};", harnessPath);

const notesHint = "Requires Magnolie Notes on Android. KDE Connect is not required.";
const kdeHint = "KDE Connect functions require the KDE Connect app on Android, not Magnolie Notes.";
const changedPaths = (before, after, prefix = "") => {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  if (!before || !after || typeof before !== "object" || typeof after !== "object") return [prefix];
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].flatMap(key =>
    changedPaths(before[key], after[key], prefix ? `${prefix}.${key}` : key));
};
const state = (notes, kde) => ({ enabled: notes, listening: notes, port: 8741,
  peers: notes ? [{ device_id: "11111111-1111-4111-8111-111111111111", display_name: "Notes fixture",
    state: "online_wifi", transport: "wifi", status: {} }] : [], bluetooth: { available: false, devices: [] },
  kdeconnect: { available: kde, paired: kde ? 1 : 0, listening: true, listen_port: 1716,
    peer_id: kde ? "kde-fixture" : "", reason: kde ? "available" : "no_device" } });

const claimed = state(true, true);
claimed.peers[0].capabilities = { revision: 1, items: { device_status: { versions: [21] } } };
const disabledPaired = { ...claimed, enabled: false, listening: false };

(async () => {
  let passed = 0;
  for (const web of harness.exports.roots) {
    for (const [name, status, german] of [["notes-only", state(true, false)], ["kde-only", state(false, true)],
      ["both", state(true, true)], ["neither", state(false, false)], ["loading", null],
      ["german", state(true, true), true], ["organizer-only-upgrade", state(true, false)],
      ["unsupported-system", { ...state(true, true), error: "Unsupported fixture system" }],
      ["claimed-capability-is-not-native-readiness", claimed], ["disabled-paired", disabledPaired]]) {
      const b = await harness.exports.boot(web, { notizen: [{ id: "keep", titel: "Keep", text: "Unchanged", html: "Unchanged" }],
        einstellungen: { adressen: { kommunikation: { anruf: { telefonId: "11111111-1111-4111-8111-111111111111" } } } } });
      try {
        if (german) {
          b.w.eval(fs.readFileSync(path.join(web, "i18n/de.js"), "utf8"));
          b.w.MagnolieI18n.setLocale("de");
        }
        const before = JSON.stringify(b.t.daten());
        b.t.oeffneEinstellungen();
        const tab = b.w.document.querySelector("#einst-tab-baum");
        assert.ok(tab); tab.click();
        if (status) b.w.App.telefonStand(status);
        const d = b.w.document, notes = d.querySelector('.telefon-karte[data-telefon-backend="magnolie-notes"]');
        const kde = d.querySelector('.telefon-kde-karte[data-telefon-backend="kde-connect"]');
        assert.ok(notes && kde, name);
        assert.equal(notes.querySelector("h3, h2").textContent,
          german ? "Magnolie Notes-Telefonverbindung" : "Magnolie Notes phone connection");
        assert.equal(d.querySelector("#telefon-erweiterte-funktionen"), null,
          `${name}: unready Notes advanced section must be absent, not merely disabled`);
        assert.equal(d.querySelector("#telefon-erweiterte-funktionen-status"), null);
        assert.equal(notes.querySelector(".telefon-app-voraussetzung").textContent,
          german ? "Benötigt Magnolie Notes auf Android. KDE Connect wird nicht benötigt." : notesHint);
        assert.equal(kde.querySelector(".kde-app-voraussetzung").textContent,
          german ? "KDE Connect-Funktionen benötigen die KDE Connect-App auf Android, nicht Magnolie Notes." : kdeHint);
        if (status) {
          const kdeAdvanced = kde.querySelector("#kde-erweiterte-funktionen");
          assert.ok(kdeAdvanced && !notes.contains(kdeAdvanced));
          assert.ok(kdeAdvanced.querySelector("#kde-input") && kdeAdvanced.querySelector("#kde-local-players"));
        }
        // Re-rendering after enable/disable/loading/claimed capability changes
        // must not revive a stale advanced section or change stored consent.
        for (const next of [claimed, disabledPaired, null, state(true, false)]) {
          b.w.App.telefonStand(next);
          assert.equal(d.querySelector("#telefon-erweiterte-funktionen"), null);
        }
        assert.deepEqual(changedPaths(JSON.parse(before), JSON.parse(JSON.stringify(b.t.daten()))), [],
          `${name}: backend presentation changed user settings/data`);
        assert.equal(b.messages.some(message => /^(telefon_ein|kde_pairing_start|kde_pairing_complete|.*foto.*|.*photo.*|.*file_transfer.*)$/.test(message.cmd)), false);
        passed++;
      } finally { b.close(); }
    }
  }
  console.log(`Phone backend UI: ${passed} cases passed (Linux/Windows source-host jsdom, not installed GUI).`);
})().catch(error => { console.error(error); process.exitCode = 1; });
