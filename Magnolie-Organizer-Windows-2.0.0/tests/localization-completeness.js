"use strict";

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const os = require("node:os");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const poDir = path.join(root, "app", "po");
const generatedDir = path.join(root, "app", "web", "i18n");
const nativeCatalogFile = path.join(root, "app", "native-i18n.json");
const python = process.env.MAGNOLIE_PYTHON;
assert.ok(python, "MAGNOLIE_PYTHON was not passed by the test runner");
const protectedTokens = ["Magnolienbaum", "KDE Connect", "Magnolie Notes", "Bluetooth",
  "WebDAV", "CalDAV", "CardDAV", "HTTPS", "JSON", "CSV", "ODS", "PDF",
  "SMS", "UID"];
const englishEqualAllowlist = new Set(protectedTokens);
const placeholderPattern = /%\([A-Za-z_][A-Za-z0-9_]*\)[#0 +\-]*\d*(?:\.\d+)?[diouxXeEfFgGcrs]|%(?:\d+\$)?[#0 +\-]*\d*(?:\.\d+)?[diouxXeEfFgGcrs]|\{[A-Za-z_][A-Za-z0-9_]*\}/g;
const identifierPattern = /https?:\/\/(?:[^\s"'<>…。，、；：！？）】}]*[A-Za-z0-9/#?=&_%~-])?|\.(?:magnolie|json|ics|vcf|ldif|csv|ods|pdf|jpe?g|png|webp|gif|deb|rpm|xml|contact|db)\b/g;

function poValue(lines, start, field) {
  if (!lines[start].startsWith(field + " ")) return null;
  let value = JSON.parse(lines[start].slice(field.length + 1));
  for (let index = start + 1; index < lines.length && lines[index].startsWith('"'); index++)
    value += JSON.parse(lines[index]);
  return value;
}

function poEntries(text) {
  const entries = new Map();
  for (const block of text.split(/\n\s*\n/)) {
    const lines = block.split("\n");
    if (lines.some((line) => line.startsWith("#~"))) continue;
    const idIndex = lines.findIndex((line) => line.startsWith("msgid "));
    if (idIndex < 0) continue;
    const id = poValue(lines, idIndex, "msgid");
    if (!id) continue;
    const contextIndex = lines.findIndex((line) => line.startsWith("msgctxt "));
    const pluralIndex = lines.findIndex((line) => line.startsWith("msgid_plural "));
    const values = [];
    for (let index = 0; index < lines.length; index++) {
      if (/^msgstr(?:\[\d+\])? /.test(lines[index]))
        values.push(poValue(lines, index, lines[index].split(" ", 1)[0]));
    }
    const context = contextIndex < 0 ? null : poValue(lines, contextIndex, "msgctxt");
    entries.set(context ? context + "\u0004" + id : id, {
      id, plural: pluralIndex < 0 ? null : poValue(lines, pluralIndex, "msgid_plural"),
      values, fuzzy: lines.some((line) => /^#,.*\bfuzzy\b/.test(line))
    });
  }
  return entries;
}

function multiset(text, pattern) {
  const result = new Map();
  for (const token of text.match(pattern) || []) result.set(token, (result.get(token) || 0) + 1);
  return JSON.stringify(Array.from(result).sort(([a], [b]) => a.localeCompare(b)));
}

function generatedCatalog(locale) {
  let registered;
  vm.runInNewContext(fs.readFileSync(path.join(generatedDir, locale + ".js"), "utf8"), {
    window: { MagnolieI18n: { registerCatalog: (name, catalog) => { registered = { name, catalog }; } } }
  });
  assert.strictEqual(registered.name, locale, `${locale}.js registers the wrong locale`);
  return registered.catalog.messages;
}

const template = poEntries(fs.readFileSync(path.join(poDir, "magnolie-organizer.pot"), "utf8"));
const locales = fs.readFileSync(path.join(poDir, "LINGUAS"), "utf8").trim().split(/\s+/);
assert.deepStrictEqual(fs.readdirSync(poDir).filter((file) => file.endsWith(".po"))
  .map((file) => path.basename(file, ".po")).sort(), [...locales].sort(), "LINGUAS and PO files differ");

for (const locale of locales) {
  const entries = poEntries(fs.readFileSync(path.join(poDir, locale + ".po"), "utf8"));
  assert.deepStrictEqual([...entries.keys()].sort(), [...template.keys()].sort(),
    `${locale}: key set differs from POT`);
  for (const [key, source] of template) {
    const entry = entries.get(key);
    assert.ok(!entry.fuzzy, `${locale}: fuzzy translation: ${source.id}`);
    assert.ok(entry.values.length && entry.values.every((value) => value.trim()),
      `${locale}: empty translation: ${source.id}`);
    const sourceTexts = [source.id, source.plural].filter(Boolean);
    const sourceJoined = sourceTexts.join(" ");
    for (const [index, value] of entry.values.entries()) {
      const sourceForm = sourceTexts[Math.min(index, sourceTexts.length - 1)];
      assert.strictEqual(multiset(value, placeholderPattern), multiset(sourceForm, placeholderPattern),
        `${locale}: placeholder mismatch: ${source.id}`);
      assert.strictEqual(multiset(value, identifierPattern), multiset(sourceForm, identifierPattern),
        `${locale}: technical identifier mismatch: ${source.id}`);
      for (const token of protectedTokens.filter((item) => sourceJoined.includes(item)))
        assert.ok(value.includes(token), `${locale}: ${source.id} must preserve ${token}`);
      const words = sourceForm.replace(placeholderPattern, "").replace(identifierPattern, "")
        .match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || [];
      assert.ok(value !== sourceForm || words.length < 4 || englishEqualAllowlist.has(sourceForm),
        `${locale}: sentence is still English: ${source.id}`);
    }
  }
  const delivered = entries.get("Delivered").values[0].toLocaleLowerCase();
  const offline = entries.get("Offline").values[0].toLocaleLowerCase();
  assert.ok(delivered !== "offline" && delivered !== offline && offline !== "delivered",
    `${locale}: Delivered/Offline state translations are inverted`);
  assert.deepStrictEqual(entries.get("recovery snapshot reason\u0004Manual").values,
    entries.get("Custom").values, `${locale}: manual recovery reason does not reuse Custom`);

  const expected = {};
  for (const [key, entry] of entries)
    expected[key] = entry.plural ? entry.values : entry.values[0];
  assert.deepStrictEqual(generatedCatalog(locale), expected, `${locale}: generated JS is stale`);
}
const germanEntries = poEntries(fs.readFileSync(path.join(poDir, "de.po"), "utf8"));
assert.strictEqual(germanEntries.get("Manual").values[0], "Handbuch");
assert.strictEqual(germanEntries.get("recovery snapshot reason\u0004Manual").values[0],
  "Benutzerdefiniert");
const webSource = fs.readFileSync(path.join(root, "app", "web", "anwendung.js"), "utf8");
assert.ok(webSource.includes('manual: pgettext("recovery snapshot reason", "Manual")'));
assert.ok(webSource.includes('"pre-contact": _("Before synchronization")'));
assert.strictEqual((webSource.match(/const CONTRIBUTOR_BRANDING = "No valid coffee allowance";/g) || []).length, 1,
  "contributor branding does not have one fixed source constant");
assert.doesNotMatch(webSource, /_\("No valid coffee allowance"\)|No valid subscription/,
  "contributor branding still enters gettext or uses the obsolete wording");
for (const branding of ["No valid coffee allowance", "No valid subscription"]) {
  assert.ok(!template.has(branding), `${branding} must not be in the organizer POT`);
  for (const locale of locales) {
    const entries = poEntries(fs.readFileSync(path.join(poDir, locale + ".po"), "utf8"));
    assert.ok(!entries.has(branding), `${locale}: ${branding} must not be translatable`);
  }
}

const nativeCatalogs = JSON.parse(fs.readFileSync(nativeCatalogFile, "utf8")).locales;
assert.deepStrictEqual(Object.keys(nativeCatalogs).sort(), [...locales].sort(),
  "native catalog does not contain exactly the 19 translated locales");
for (const locale of locales) {
  const entries = poEntries(fs.readFileSync(path.join(poDir, locale + ".po"), "utf8"));
  const expected = {};
  for (const [key, entry] of entries) if (!entry.plural) expected[key] = entry.values[0];
  assert.deepStrictEqual(nativeCatalogs[locale], expected, `${locale}: generated native catalog is stale`);
}

const nativeSourceFiles = fs.readdirSync(root)
  .filter((name) => name.endsWith(".cs"))
  .sort();
const nativeSources = nativeSourceFiles
  .map((name) => fs.readFileSync(path.join(root, name), "utf8"));
const localizedNativeSources = nativeSources.filter((source, index) =>
  source.includes("NativeLocalization.Gettext") ||
    (/^BridgeDispatcher(?:\.|$)/.test(nativeSourceFiles[index]) &&
      nativeSourceFiles[index] !== "BridgeDispatcherContract.cs"));
const nativeKeys = new Set();
for (const source of localizedNativeSources)
  for (const match of source.matchAll(/(?:\bT|NativeLocalization\.Gettext)\("((?:[^"\\]|\\.)*)"\)/g))
    nativeKeys.add(JSON.parse(`"${match[1]}"`));
for (const key of nativeKeys) assert.ok(template.has(key), `native msgid is missing from POT: ${key}`);

for (const [index, source] of nativeSources.entries()) {
  assert.doesNotMatch(source, /(?:Title|Description)\s*=\s*"[^"\r\n]+"/,
    `hard native dialog title in ${nativeSourceFiles[index]}`);
  assert.doesNotMatch(source, /(?:menu\.Items\.Add|new ToolStripMenuItem)\(\s*"/,
    `hard tray menu text in ${nativeSourceFiles[index]}`);
  assert.doesNotMatch(source, /MessageBox\.Show\(\s*(?:"|[^,\r\n]+,\s*")/,
    `hard native message box text in ${nativeSourceFiles[index]}`);
}

for (const name of ["BridgeDispatcher.cs", "BridgeDispatcher.Sync.cs", "TelefonCoordinator.cs"]) {
  const source = fs.readFileSync(path.join(root, name), "utf8");
  assert.doesNotMatch(source, /\b(?:fehler|error)\s*=\s*"[^"\r\n]*[A-ZÄÖÜ][^"\r\n]*[ .!?]"/,
    `hard user-visible error in ${name}`);
}

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-native-i18n-"));
try {
  const argumentsFor = (target) => [path.join(root, "werkzeuge", "po_zu_native.py"), target,
    ...locales.flatMap((locale) => [locale, path.join(poDir, locale + ".po")])];
  const first = path.join(temporary, "first.json");
  const second = path.join(temporary, "second.json");
  for (const target of [first, second]) {
    const generated = spawnSync(python, argumentsFor(target), { encoding: "utf8" });
    assert.strictEqual(generated.status, 0, generated.stderr || "native catalog generator failed");
  }
  assert.deepStrictEqual(fs.readFileSync(first), fs.readFileSync(second),
    "native catalog generator is not deterministic");
  assert.deepStrictEqual(fs.readFileSync(first), fs.readFileSync(nativeCatalogFile),
    "checked-in native catalog is stale");
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}

for (const file of [path.join(poDir, "magnolie-organizer.pot"),
  ...locales.map((locale) => path.join(poDir, locale + ".po")),
  ...locales.map((locale) => path.join(generatedDir, locale + ".js"))]) {
  assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\b(?:BlueZ|bluetoothctl|D-Bus|DBus)\b/i,
    `Windows localization contains Linux Bluetooth text: ${path.relative(root, file)}`);
}

console.log("LOCALIZATION COMPLETENESS TEST PASSED");
