"use strict";
const assert = require("assert");
const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

const root = path.resolve(__dirname, "..");
const archive = process.argv[2];
const sourceArchive = process.argv[3];
if (!archive || !sourceArchive) {
  throw new Error("usage: node pruefungen/paket_inhalt_test.js PACKAGE.deb SOURCE.tar.xz");
}
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-handbook-package-"));
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const pages = (file) => {
  const text = fs.readFileSync(file, "utf8");
  const data = JSON.parse(text.slice(text.indexOf("["), text.indexOf("];" ) + 1));
  const marker = "window.HANDBUCH_SEITEN.push(";
  if (text.includes(marker)) {
    const start = text.indexOf(marker) + marker.length;
    const end = text.indexOf("\n);", start);
    data.push(...JSON.parse("[" + text.slice(start, end) + "]"));
  }
  return { count: data.length, slugs: data.map((page) => page.id || page.titel.toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")) };
};

try {
  childProcess.execFileSync("dpkg-deb", ["-x", archive, temporary]);
  const source = path.join(root, "web", "inhalt.js");
  const installed = path.join(temporary, "usr", "share", "magnolie-handbuch", "web", "inhalt.js");
  assert.ok(fs.existsSync(installed), "built package does not contain web/inhalt.js");
  assert.strictEqual(digest(installed), digest(source), "built package contains stale handbook content");
  for (const relative of ["stil.css", "01.jpg", "02.jpg", "03.jpg",
    "02-woche.png", "03-aufgaben.png", "06-jahrestage.png", "10-pin-abfrage.png",
    "11-stand.png", "14-karteikarte.png", "15-rechtsklick-anrufen.png",
    "19-karte-mit-sms.png", "21-sms-getippt.png", "kaffee-qr.png", "maik-walter.jpg",
    "maik-walter-FOTO-NUTZUNG.txt", "schriften/DejaVuSans.ttf",
    "schriften/DejaVuSans-Bold.ttf", "schriften/DejaVuSans-Oblique.ttf",
    "schriften/DejaVuSans-BoldOblique.ttf", "schriften/NotoSerif-Regular.ttf",
    "schriften/NotoSerif-Bold.ttf", "schriften/NotoSerif-Italic.ttf",
    "schriften/NotoSerif-BoldItalic.ttf", "schriften/DejaVu-LIZENZ.txt",
    "schriften/Noto-LIZENZ.txt"]) {
    const sourceFile = path.join(root, "web", relative);
    const installedFile = path.join(temporary, "usr", "share", "magnolie-handbuch", "web", relative);
    assert.ok(fs.existsSync(installedFile), `built package does not contain web/${relative}`);
    assert.strictEqual(digest(installedFile), digest(sourceFile),
      `built package contains stale web/${relative}`);
  }
  const sourcePages = pages(source);
  const installedPages = pages(installed);
  assert.strictEqual(sourcePages.count, 154, "source package does not contain exactly 154 pages");
  for (const id of ["command-line-and-man-page", "reminder-command-modes",
    "linux-diagnostic-reminder-logs", "windows-diagnostic-logs",
    "supported-environment-variables", "glossary-a-m", "glossary-n-z"]) {
    assert.ok(sourcePages.slugs.includes(id), `source package is missing required page: ${id}`);
  }
  assert.deepStrictEqual(installedPages, sourcePages, "built package slug list differs from source");

  const languages = fs.readFileSync(path.join(root, "po", "LINGUAS"), "utf8").trim().split(/\s+/);
  for (const language of languages) {
    const expected = path.join(temporary, `${language}.mo`);
    childProcess.execFileSync("msgfmt", ["--check", "--check-format", "-o", expected,
      path.join(root, "po", `${language}.po`)]);
    const installedMo = path.join(temporary, "usr", "share", "locale", language,
      "LC_MESSAGES", "magnolie-handbuch.mo");
    assert.ok(fs.existsSync(installedMo), `built package does not contain ${language} MO catalog`);
    assert.strictEqual(digest(installedMo), digest(expected),
      `built package contains stale ${language} MO catalog`);
  }

  const sourceEntries = childProcess.execFileSync("tar", ["-tf", sourceArchive],
    { encoding: "utf8" }).trim().split("\n");
  assert.ok(!sourceEntries.some((entry) => path.basename(entry) ===
    "Magnolie-Handbuch-PRUEFSUMMEN.sha256"),
  "source archive contains the external release checksum file");
  console.log(`PACKAGE CONTENT PASSED (${sourcePages.count} pages; ${languages.length} MO catalogs; ${digest(source)})`);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
