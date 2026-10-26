"use strict";
const assert = require("assert");
const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { handbookData } = require("../werkzeuge/handbook_data.js");

const root = path.resolve(__dirname, "..");
const archive = process.argv[2];
const sourceArchive = process.argv[3];
if (!archive || !sourceArchive) {
  throw new Error("usage: node pruefungen/paket_inhalt_test.js PACKAGE.deb SOURCE.tar.xz");
}
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-handbook-package-"));
const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const pages = (file) => {
  const data = handbookData(path.dirname(file)).pages;
  return { count: data.length, slugs: data.map((page) => page.id || page.titel.toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")) };
};

try {
  childProcess.execFileSync("dpkg-deb", ["-x", archive, temporary]);
  const source = path.join(root, "web", "inhalt.js");
  const installed = path.join(temporary, "usr", "share", "magnolie-handbuch", "web", "inhalt.js");
  assert.ok(fs.existsSync(installed), "built package does not contain web/inhalt.js");
  assert.strictEqual(digest(installed), digest(source), "built package contains stale handbook content");
  const reporter = path.join(temporary, "usr", "lib", "magnolie-handbuch", "magnolie_crash.py");
  assert.ok(fs.existsSync(reporter), "built package does not contain its private crash reporter");
  assert.ok(!fs.existsSync(path.join(temporary, "usr", "bin", "magnolie_crash.py")),
    "built handbook package must not own the organizer crash reporter path");
  const privateRuntime = path.join(temporary, "usr", "lib", "magnolie-handbuch");
  const printModules = ["magnolie_print_pdf.py", "magnolie_print_gtk.py", "magnolie_print_process.py",
    "magnolie_print_operation.py", "magnolie_print_portal.py", "pdf-runtime-lock.json"];
  for (const name of printModules) {
    assert.strictEqual(digest(path.join(privateRuntime, name)), digest(path.join(root, "bin", name)),
      `built package contains missing or stale PDF module ${name}`);
  }
  childProcess.execFileSync("python3", ["-B", "-c",
    "import sys;sys.path.insert(0,sys.argv[1]);from magnolie_print_pdf import verify_runtime;verify_runtime()", privateRuntime],
    { env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" }, stdio: "pipe" });
  childProcess.execFileSync(path.join(temporary, "usr", "bin", "magnolie-handbuch"), ["--help"],
    { env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" }, stdio: "pipe" });
  for (const relative of ["stil.css", "01.jpg", "02.jpg", "03.jpg",
    "02-woche.png", "03-aufgaben.png", "06-jahrestage.png", "10-pin-abfrage.png",
    "11-stand.png", "14-karteikarte.png", "15-rechtsklick-anrufen.png",
    "19-karte-mit-sms.png", "21-sms-getippt.png", "kaffee-qr.mga", "maik-walter.mga",
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
  for (const forbidden of ["kaffee-qr.png", "maik-walter.jpg"]) {
    assert.ok(!fs.existsSync(path.join(temporary, "usr", "share", "magnolie-handbuch", "web", forbidden)),
      `built package contains plaintext personal asset ${forbidden}`);
  }
  const sourcePages = pages(source);
  const installedPages = pages(installed);
  assert.strictEqual(sourcePages.count, 170, "source package does not contain exactly 170 pages");
  for (const id of ["command-line-and-man-page", "reminder-command-modes",
    "linux-diagnostic-reminder-logs", "windows-diagnostic-logs",
    "supported-environment-variables", "glossary-a-m", "glossary-n-z", "sending-selected-notes"]) {
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
  for (const relative of [...printModules.map(name => "bin/" + name), "werkzeuge/pdf_runtime.py",
    "bin/pdf-runtime/runtime-manifest.json", "bin/pdf-runtime/typing_extensions.py", ...["weasyprint", "pydyf", "tinyhtml5", "tinycss2",
      "cssselect2", "fontTools", "pypdf", "pyphen", "webencodings"].map(name => `bin/pdf-runtime/${name}/__init__.py`)]) {
    assert.ok(sourceEntries.some(entry => entry.endsWith("/" + relative)),
      `source archive lacks offline PDF rebuild input ${relative}`);
  }
  for (const relative of [...printModules.map(name => "bin/" + name), "werkzeuge/pdf_runtime.py",
    "pruefungen/paket_inhalt_test.js"]) {
    const member = sourceEntries.find(entry => entry.endsWith("/" + relative));
    assert.ok(member, `source archive lacks current check or PDF source ${relative}`);
    const content = childProcess.execFileSync("tar", ["-xOf", sourceArchive, member]);
    assert.strictEqual(crypto.createHash("sha256").update(content).digest("hex"), digest(path.join(root, relative)),
      `source archive contains stale PDF/check source ${relative}`);
  }
  assert.ok(sourceEntries.some((entry) => entry.endsWith("/web/kaffee-qr.mga")) &&
    sourceEntries.some((entry) => entry.endsWith("/web/maik-walter.mga")),
  "source archive is missing protected asset containers");
  assert.ok(!sourceEntries.some((entry) => /\/web\/(?:kaffee-qr\.png|maik-walter\.jpg)$/.test(entry)),
  "source archive contains plaintext personal assets");
  assert.ok(!sourceEntries.some((entry) => path.basename(entry) ===
    "Magnolie-Handbuch-PRUEFSUMMEN.sha256"),
  "source archive contains the external release checksum file");
  console.log(`PACKAGE CONTENT PASSED (${sourcePages.count} pages; ${languages.length} MO catalogs; ${digest(source)})`);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
