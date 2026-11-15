"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), os = require("node:os"), path = require("node:path");
const { spawnSync } = require("node:child_process");
const root = path.resolve(__dirname, "..");
const source = path.join(__dirname, "background-sms.js");
const sibling = path.resolve(root, "../magnolie-organizer/web/anwendung.js");
const embedded = path.join(root, "shared/magnolie-organizer/web/anwendung.js");
const linux = fs.existsSync(sibling) ? sibling : embedded;
assert.ok(fs.existsSync(linux), "The independent Linux SMS source is required by the path regression");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-sms-source-paths-"));
try {
  for (const layout of ["sibling", "embedded", "override", "missing"]) {
    const base = path.join(temp, layout), windows = path.join(base, "windows");
    const test = path.join(windows, "tests/background-sms.js");
    fs.mkdirSync(path.dirname(test), { recursive: true }); fs.copyFileSync(source, test);
    const winSource = path.join(windows, "app/web/anwendung.js");
    fs.mkdirSync(path.dirname(winSource), { recursive: true });
    fs.copyFileSync(path.join(root, "app/web/anwendung.js"), winSource);
    const target = layout === "sibling" ? path.join(base, "magnolie-organizer/web/anwendung.js") :
      layout === "override" ? path.join(base, "explicit-linux/web/anwendung.js") :
      path.join(windows, "shared/magnolie-organizer/web/anwendung.js");
    if (layout !== "missing") {
      fs.mkdirSync(path.dirname(target), { recursive: true }); fs.copyFileSync(linux, target);
    }
    const env = { ...process.env }; delete env.MAGNOLIE_LINUX_SOURCE;
    if (layout === "override") env.MAGNOLIE_LINUX_SOURCE = path.dirname(path.dirname(target));
    const result = spawnSync(process.execPath, [test], { encoding: "utf8", env, timeout: 15000 });
    assert.ifError(result.error);
    if (layout === "missing") {
      assert.notEqual(result.status, 0, "Missing Linux reference was silently skipped");
      assert.match(`${result.stdout}${result.stderr}`, /Required SMS test target missing:/);
    } else {
      assert.equal(result.status, 0, `${layout}: ${result.stdout}${result.stderr}`);
      assert.equal((result.stdout.match(/PASS durable scheduled SMS:/g) || []).length, 2,
        `${layout}: both GUI sources must execute; a skipped Linux matrix is not a pass`);
    }
  }
  console.log("SMS source-path fixtures passed: sibling, embedded, explicit override and missing-reference rejection.");
} finally { fs.rmSync(temp, { recursive: true, force: true }); }
