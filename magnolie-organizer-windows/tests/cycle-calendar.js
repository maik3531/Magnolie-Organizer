"use strict";
const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path");
const { JSDOM } = require("jsdom");
for (const web of require("./web-test-roots")) {
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    url: "https://app.magnolie.invalid/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.setTimeout = w.setInterval = () => 0;
  w.__MAGNOLIE_BRUECKE__ = "test"; w.webkit = { messageHandlers: { test: { postMessage() {} } } };
  try {
    w.eval(fs.readFileSync(path.join(web, "i18n.js"), "utf8"));
    w.eval(fs.readFileSync(path.join(web, "anwendung.js"), "utf8"));
    w.App.init({ neu: false, daten: { zyklusmarker: [{ id: "light", art: "bleeding-light", name: "Renamed" },
      { id: "other", art: "ovulation", name: "Bleeding" }],
      tagmarken: ["2026-01-01", "2026-01-02", "2026-01-29", "2026-02-26"].map(datum => ({ datum, zyklusIds: ["light"] })),
      einstellungen: { kalender: { zykluskalenderAn: true } } } });
    const t = w.OrganizerTest, data = t.daten();
    assert.equal(t.zyklusStatistik().predicted, "2026-03-26");
    assert.equal(t.zyklusTermineFuerErinnerung().length, 0, "Notifications must be off by default");
    Object.assign(data.einstellungen.kalender.zyklusErinnerungen, { prognose: true, abweichung: true, vorlauf: 2 });
    assert.equal(t.zyklusTermineFuerErinnerung().length, 1);
    data.tagmarken.push({ datum: "2026-04-09", zyklusIds: ["light"] });
    assert.equal(t.zyklusStatistik().predicted, "2026-05-07");
    assert.equal(t.zyklusStatistik().baseline, 28);
    assert.equal(t.zyklusTermineFuerErinnerung().length, 2);
    data.tagmarken.forEach(mark => { mark.zyklusIds = ["other"]; });
    assert.equal(t.zyklusStatistik().predicted, null, "A renamed ovulation marker must not be treated as bleeding");
  } finally { w.close(); }
}
console.log("CYCLE CALENDAR UI PASSED: explicit types, estimates, opt-ins and unusual intervals");
