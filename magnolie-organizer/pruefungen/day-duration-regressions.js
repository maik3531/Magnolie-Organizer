"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const sources = ["magnolie-organizer/web/anwendung.js",
  "magnolie-organizer-windows/app/web/anwendung.js"];
for (const relative of sources) {
  const source = fs.readFileSync(path.join(root, relative), "utf8");
  const extract = name => {
    const match = source.match(new RegExp("  function " + name + "\\([^]*?\\n  \\}"));
    assert.ok(match, name);
    return match[0];
  };
  const minutes = Function("return (" + extract("zeitZuMinuten") + ");")();
  const intervals = Function("zeitZuMinuten", "return (" + extract("stundenBelegungen") + ");")(minutes);
  const day = "2026-09-17";
  const four = { datum: day, zeit: "09:00", endZeit: "13:00" };
  assert.deepEqual(Array.from({ length: 24 }, (_, h) => intervals([four], day, h).length ? h : null)
    .filter(h => h !== null), [9, 10, 11, 12], relative + ": four hours must occupy four slots");
  const partial = { datum: day, zeit: "09:30", endZeit: "10:15" };
  assert.deepEqual(intervals([partial], day, 9), [[30, 60, 1]]);
  assert.deepEqual(intervals([partial], day, 10), [[0, 15, 1]]);
  assert.deepEqual(intervals([partial, { ...partial, zeit: "09:45", endZeit: "10:30" }], day, 10), [[0, 15, 2], [15, 30, 1]]);
  assert.deepEqual(intervals([{ ...four, endZeit: "10:00" }, { ...four, zeit: "10:00", endZeit: "11:00" }], day, 10), [[0, 60, 1]]);
  const overnight = { datum: "2026-09-16", zeit: "21:00", endDatum: day, endZeit: "08:00" };
  assert.deepEqual(intervals([overnight], day, 6), [[0, 60, 1]]);
  assert.deepEqual(intervals([overnight], day, 8), []);
  assert.deepEqual(intervals([{ ...overnight, endZeit: "00:00" }], day, 0), []);
  assert.deepEqual(intervals([{ datum: day, zeit: "" }], day, 9), []);
  const anniversary = { datum: day, zeit: "", titel: "Ganztägiger Jahrestag" };
  for (let hour = 0; hour < 24; hour++) {
    assert.deepEqual(intervals([anniversary], day, hour), []);
    assert.deepEqual(intervals([anniversary, four], day, hour), intervals([four], day, hour));
  }
  assert.deepEqual(intervals([{ datum: day, zeit: "09:00" }], day, 9), [[0, 60, 1]]);
}
console.log("Day-view durations: both desktop sources passed (four hours, partial hours, overlap, midnight).");
