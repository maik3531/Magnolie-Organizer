"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { selectHandbookWeb } = require("./handbook-source");

// Refs #832: use real files and the actual source selector. Only diagnostics
// are bounded; a difference at the very end must still reject the source.
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-handbook-source-"));
const root = path.join(temporary, "magnolie-organizer-windows");
const canonical = path.join(temporary, "magnolie-handbuch", "web");
const bundled = path.join(root, "shared", "magnolie-handbuch", "web");
const configured = process.env.MAGNOLIE_HANDBOOK_WEB;
try {
  delete process.env.MAGNOLIE_HANDBOOK_WEB;
  for (const directory of [canonical, bundled]) {
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "index.html"), "<!doctype html><title>Fixture</title>");
  }
  const bytes = Buffer.alloc(1024 * 1024, 65);
  for (const directory of [canonical, bundled]) fs.writeFileSync(path.join(directory, "payload.bin"), bytes);
  assert.equal(selectHandbookWeb(root, ["index.html"]).directory, canonical,
    "Identical complete source bytes must remain accepted");

  const changed = Buffer.from(bytes);
  changed[changed.length - 1] = 66;
  fs.writeFileSync(path.join(bundled, "payload.bin"), changed);
  assert.throws(() => selectHandbookWeb(root, ["index.html"]), error => {
    assert.equal(error.code, "ERR_ASSERTION");
    assert.equal(error.message,
      "Gebündelte Handbuchquelle ist gegenüber der kanonischen Quelle veraltet: payload.bin");
    assert.ok(error.message.length < 256, "Byte mismatch diagnostics must not dump either complete file");
    return true;
  });

  fs.unlinkSync(path.join(bundled, "payload.bin"));
  assert.throws(() => selectHandbookWeb(root, ["index.html"]), error => {
    assert.equal(error.code, "ERR_ASSERTION");
    assert.equal(error.message, "Gebündelte Handbuchquelle ist unvollständig: payload.bin");
    assert.ok(error.message.length < 256);
    return true;
  });
} finally {
  if (configured === undefined) delete process.env.MAGNOLIE_HANDBOOK_WEB;
  else process.env.MAGNOLIE_HANDBOOK_WEB = configured;
  fs.rmSync(temporary, { recursive: true, force: true });
}
console.log("Handbook source diagnostics PASS: identical 1 MiB, final-byte mismatch, missing file; exact equality and bounded errors.");
