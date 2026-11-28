"use strict";
// Replays freshly captured native responses through actual complete desktop scripts.
const fs = require("node:fs"), path = require("node:path"), assert = require("node:assert/strict");
const crypto = require("node:crypto"), Module = require("node:module");
const root = process.argv[2];
const evidence = process.argv[3];
if (!root || !evidence) throw new Error("Usage: node frontend_live.js SOURCE_ROOT EVIDENCE_DIR");
const fixturePath = path.join(root, "magnolie-organizer-windows/tests/holiday-cache.js");
const fixtureSource = fs.readFileSync(fixturePath, "utf8");
const boundary = "const cases = [];";
assert.equal(fixtureSource.split(boundary).length, 2);
const harness = new Module(fixturePath, module);
harness.filename = fixturePath;
harness.paths = Module._nodeModulePaths(path.dirname(fixturePath));
harness._compile(fixtureSource.slice(0, fixtureSource.indexOf(boundary)) + "\nmodule.exports = { boot, plain };\n", fixturePath);
const { boot, plain } = harness.exports;
const live = JSON.parse(fs.readFileSync(path.join(evidence, "capture/live-results.json")));
const scenes = Object.fromEntries(live.scenes.map(s => [s.scene, s]));
const mode = process.argv[4] || "before";
const afterPath = ["after", "final"].includes(mode) ? path.join(evidence, mode === "final" ? "final-capture/live-results.json" : "after-capture/live-results.json") : null;
if (afterPath) {
  const after = JSON.parse(fs.readFileSync(afterPath));
  for (const s of after.scenes) scenes[s.scene] = s;
}
const actualVienna = JSON.parse(fs.readFileSync(path.join(evidence, "capture/at-wi-school-2026.json")));
const missingVienna = actualVienna.filter(r => !r.nationwide);
const hash = value => crypto.createHash("sha256").update(value).digest("hex");
const results = [];
function test(web, name, fn) {
  try { fn(); results.push({ web, name, passed: true }); }
  catch (error) { results.push({ web, name, passed: false, error: error.message }); }
}
for (const web of ["magnolie-organizer/web", "magnolie-organizer-windows/app/web"]) {
  test(web, "DE/SN 2026 live response imports all 18 parsed rows and complete cross-year dates", () => {
    const b = boot(web, []);
    try {
      b.start(); b.reply(scenes["de-sn-2026"].response);
      assert.equal(b.entries().length, 18);
      for (const raw of scenes["de-sn-2026"].response.feiertage) {
        assert.ok(b.entries().some(r => r.country === raw.country && r.art === raw.art && r.name === raw.name && r.von === raw.von && r.bis === raw.bis));
      }
      const before = b.entries();
      b.start(); b.reply(scenes["de-sn-2026"].response);
      assert.equal(b.entries().length, before.length);
      for (const raw of scenes["de-sn-2026"].response.feiertage) {
        const matches = b.entries().filter(r => r.country === raw.country && r.art === raw.art && r.von === raw.von && r.bis === raw.bis
          && (r.name === raw.name || r.name.startsWith(raw.name + " (")));
        assert.equal(matches.length, 1, "Repeat keeps one semantic row; display order and region labels can normalize");
        assert.deepEqual(matches[0].regions.slice().sort(), raw.regions.slice().sort());
      }
    } finally { b.close(); }
  });
  test(web, "DE live refresh preserves the complete AT and CH live cache", () => {
    const rows = [...scenes["at-9-2026"].response.feiertage, ...scenes["ch-zh-2026"].response.feiertage]
      .map((r, n) => ({ ...r, id: `live-foreign-${n}` }));
    const b = boot(web, rows);
    try {
      const original = b.entries(); b.start(); b.reply(scenes["de-sn-2026"].response);
      assert.deepEqual(b.entries().filter(r => r.country !== "DE"), original);
    } finally { b.close(); }
  });
  test(web, "school opt-out preserves captured Saxony school periods", () => {
    const old = scenes["de-sn-2026"].response.feiertage.filter(r => r.art === "school-holiday").map((r, n) => ({ ...r, id: `school-${n}` }));
    const b = boot(web, old, { ferien: false });
    try {
      const original = b.entries(); const request = b.start(); assert.equal(request.ferien, false);
      b.reply({ ...scenes["de-sn-2026"].response,
        feiertage: scenes["de-sn-2026"].response.feiertage.filter(r => r.art === "public-holiday"),
        abrufbereiche: scenes["de-sn-2026"].response.abrufbereiche.filter(r => r.art === "public-holiday") });
      assert.deepEqual(b.entries().filter(r => r.art === "school-holiday"), original);
    } finally { b.close(); }
  });
  for (const expected of missingVienna) {
    test(web, `AT-9 live request contains provider-confirmed Vienna ${expected.name[0].text} ${expected.startDate}`, () => {
      const b = boot(web, [], { land: "AT", region: "AT-9" });
      try {
        const request = b.start(); assert.equal(request.land, "AT"); assert.equal(request.region, "AT-9");
        b.reply(scenes["at-9-2026"].response);
        assert.ok(b.entries().some(r => r.country === "AT" && r.art === "school-holiday" && r.von === expected.startDate && r.bis === expected.endDate),
          `Provider-confirmed Vienna school period absent from actual desktop cache: ${expected.startDate} to ${expected.endDate}`);
      } finally { b.close(); }
    });
  }
  test(web, "AT-9 partial live answer preserves a seeded canonical Vienna semester cache", () => {
    const raw = missingVienna.find(r => r.name[0].text === "Semester Holidays");
    assert.ok(raw);
    // Existing canonical cache fixture, dates/name from real provider response.
    const old = { id: "previous-vienna-semester", country: "AT", region: "AT-9", regions: ["AT-9"],
      art: "school-holiday", von: raw.startDate, bis: raw.endDate, name: raw.name[0].text, nationwide: false };
    const b = boot(web, [old], { land: "AT", region: "AT-9" });
    try {
      assert.equal(b.entries().length, 1); b.start(); b.reply(scenes["at-9-2026"].response);
      assert.ok(b.entries().some(r => r.von === old.von && r.bis === old.bis && r.art === old.art),
        "Live partial response with false AT-9 coverage removed the seeded prior Vienna semester period");
    } finally { b.close(); }
  });
}
const report = {
  mode: "Full desktop scripts in JSDOM; real captured native responses, not live native GUI",
  runtime: { node: process.version, jsdom: require("jsdom/package.json").version },
  source_base: live.source_base,
  candidate_tree: live.candidate_tree,
  native_reply_revision: afterPath ? `#855 plus #856; source hashes in ${path.relative(evidence, afterPath)}` : "#855 original",
  source_sha256: Object.fromEntries([fixturePath, ...["magnolie-organizer/web/anwendung.js", "magnolie-organizer-windows/app/web/anwendung.js"].map(p => path.join(root,p))]
    .map(p => [path.relative(root,p),hash(fs.readFileSync(p))])),
  live_receipt_sha256: hash(fs.readFileSync(path.join(evidence,"capture/live-results.json"))),
  after_live_receipt_sha256: afterPath ? hash(fs.readFileSync(afterPath)) : null,
  passed: results.filter(r => r.passed).length, total: results.length, results,
};
fs.writeFileSync(path.join(evidence, mode === "final" ? "frontend-live-final-results.json" : afterPath ? "frontend-live-after-results.json" : "frontend-live-results.json"), JSON.stringify(report,null,2)+"\n");
console.log(JSON.stringify(report,null,2));
if (report.passed !== report.total) process.exitCode = 1;
