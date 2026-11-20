#!/usr/bin/env node
"use strict";

// Refs #713. Exercise the generated production file without a browser or DOM.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { URL } = require("node:url");

const scriptPath = path.resolve(__dirname, "../assets/language.js");
const context = vm.createContext({ module: { exports: {} }, URL });
new vm.Script(fs.readFileSync(scriptPath, "utf8"), { filename: scriptPath })
  .runInContext(context, { timeout: 1000 });
const language = context.module.exports;

// These paths are the public URL contract, not values read back from routes.
const expectedRoutes = {
  ar: "intl/ar/",
  be: "intl/be/",
  cs: "intl/cs/",
  da: "intl/da/",
  de: "de/",
  en: "en/",
  es: "intl/es/",
  fr: "intl/fr/",
  hi: "intl/hi/",
  hsb: "intl/hsb/",
  it: "intl/it/",
  ja: "intl/ja/",
  nb: "intl/nb/",
  nl: "intl/nl/",
  pl: "intl/pl/",
  pt: "intl/pt/",
  ru: "intl/ru/",
  tr: "intl/tr/",
  uk: "intl/uk/",
  "zh-CN": "intl/zh-CN/",
};
const hostingBases = [
  "https://example.test/",
  "https://maik3531.github.io/Magnolie-Organizer/",
  "https://example.test/nested%20site/releases/magnolie/",
];
let passed = 0;
const failures = [];

function check(name, assertion) {
  try {
    assertion();
    passed += 1;
  } catch (error) {
    failures.push(`${name}\n${error.stack || error}`);
  }
}

function redirects(name, current, preferences, expected) {
  for (const base of hostingBases) {
    check(`${name} [${base}]`, () => {
      const script = `${base}assets/language.js`;
      const actual = language.destination(`${base}${current}`, script, preferences);
      assert.equal(actual, `${base}${expected}`);
      assert.equal(new URL(actual).origin, new URL(base).origin);
      assert.equal(language.destination(actual, script, preferences), null,
        "a fixed language destination must not redirect again");
    });
  }
}

function stays(name, current, preferences = ["fr", "en"]) {
  for (const base of hostingBases) {
    check(`${name} [${base}]`, () => {
      assert.equal(language.destination(`${base}${current}`,
        `${base}assets/language.js`, preferences), null);
    });
  }
}

check("exactly 20 published language routes", () => {
  assert.deepEqual(Object.keys(language.routes).sort(), Object.keys(expectedRoutes).sort());
  for (const [code, route] of Object.entries(expectedRoutes)) {
    assert.equal(language.routes[code], route, code);
  }
});

for (const [code, route] of Object.entries(expectedRoutes)) {
  redirects(`general root chooses ${code}`, "", [code], route);
  redirects(`index.html chooses ${code}`, "index.html", [code], route);
  stays(`direct ${code} directory remains fixed`, `${route}?lang=fr#download`);
  stays(`direct ${code} index remains fixed`, `${route}index.html?lang=en`);
}

const regionalCases = [
  ["de-CH", "de", "de/"],
  ["en-GB", "en", "en/"],
  ["pt-BR", "pt", "intl/pt/"],
  ["no-NO", "nb", "intl/nb/"],
  ["zh-Hant", "zh-CN", "intl/zh-CN/"],
  ["hsb-DE", "hsb", "intl/hsb/"],
];
for (const [tag, code, route] of regionalCases) {
  check(`recognises regional preference ${tag}`, () => {
    assert.equal(language.supported(tag), code);
    assert.equal(language.negotiate([tag]), code);
  });
  redirects(`regional browser preference ${tag}`, "", [tag], route);
}

for (const [preferences, code, route] of [
  [["sv-SE", "fr-CA", "en-GB"], "fr", "intl/fr/"],
  [["es-MX", "fr-FR"], "es", "intl/es/"],
  [["de-CH", "en-GB"], "de", "de/"],
  [[null, "", "xx", "hsb-DE", "en"], "hsb", "intl/hsb/"],
]) {
  check(`first supported preference: ${JSON.stringify(preferences)}`, () => {
    assert.equal(language.negotiate(preferences), code);
  });
  redirects(`ordered browser preferences ${JSON.stringify(preferences)}`, "", preferences, route);
}

for (const preferences of [
  undefined, null, "en", 42, {}, [],
  [null, false, 42, {}, []],
  ["", "   ", "zz-ZZ", "not a locale", "../en/", "https://evil.example/"],
  ["en--GB"],
]) {
  check(`empty or invalid preferences fall back to German: ${JSON.stringify(preferences)}`, () => {
    assert.equal(language.negotiate(preferences), "de");
  });
  redirects(`German fallback for ${JSON.stringify(preferences)}`, "", preferences, "de/");
}

redirects("explicit language precedes browser preferences", "?lang=fr", ["en"], "intl/fr/");
redirects("explicit regional language is supported", "?lang=pt-BR", ["de"], "intl/pt/");
redirects("explicit German remains German", "?lang=de-CH", ["en"], "de/");
redirects("explicit language works at index.html", "index.html?lang=hsb-DE", ["fr"], "intl/hsb/");
redirects("other query parameters survive", "?ref=press&lang=fr&utm_source=release", ["en"],
  "intl/fr/?ref=press&utm_source=release");

for (const invalid of [
  "", "xx", "https://evil.example/", "//evil.example/", "../../en/",
  "javascript:alert(1)", "__proto__", "constructor",
]) {
  redirects(`invalid lang cannot select an external URL: ${JSON.stringify(invalid)}`,
    `?lang=${encodeURIComponent(invalid)}&ref=kept`, ["en"], "en/?ref=kept");
}

for (const base of hostingBases) {
  check(`encoded and repeated query values survive [${base}]`, () => {
    const actual = language.destination(
      `${base}?tag=one&lang=es&tag=two&q=a%20b&literal=%2B&empty=#download`,
      `${base}assets/language.js`, ["en"]);
    const target = new URL(actual);
    assert.equal(target.origin, new URL(base).origin);
    assert.equal(target.pathname, `${new URL(base).pathname}intl/es/`);
    assert.deepEqual([...target.searchParams], [
      ["tag", "one"], ["tag", "two"], ["q", "a b"], ["literal", "+"], ["empty", ""],
    ]);
    assert.equal(target.hash, "#downloads");
    assert.equal(language.destination(actual, `${base}assets/language.js`, ["en"]), null);
  });
}

for (const [code, route] of Object.entries(expectedRoutes)) {
  const expectedFragment = code === "de" || code === "en" ? "#download" : "#downloads";
  redirects(`singular download anchor for ${code}`, "#download", [code], `${route}${expectedFragment}`);
  redirects(`plural download anchor for ${code}`, "#downloads", [code], `${route}${expectedFragment}`);
}
redirects("language-picker anchor survives", "?ref=menu#languages", ["fr"], "intl/fr/?ref=menu#languages");
redirects("main-content anchor survives", "#main", ["en"], "en/#main");

for (const anchor of ["#screenshots", "#einblicke", "#lokal", "#unknown-section"]) {
  stays(`specific anchor remains reachable: ${anchor}`, anchor);
  stays(`specific anchor also wins over an explicit language: ${anchor}`, `?lang=en${anchor}`);
}

for (const direct of [
  "de", "en", "intl", "intl/", "intl/index.html",
  "impressum/", "impressum/index.html", "datenschutz/", "datenschutz/index.html",
  "en/impressum/", "en/datenschutz/index.html",
  "intl/fr/impressum/", "intl/hsb/datenschutz/index.html",
  "presse/", "presse/index.html", "other/index.html",
]) {
  stays(`only the general entry redirects, not ${direct}`, `${direct}?lang=en`);
}

check("a script from another origin cannot choose a redirect", () => {
  assert.equal(language.destination("https://example.test/", "https://evil.example/assets/language.js", ["en"]), null);
});
check("a script for another hosting path cannot choose a redirect", () => {
  assert.equal(language.destination("https://example.test/other/", "https://example.test/site/assets/language.js", ["en"]), null);
});
check("invalid current URL leaves the static entry alone", () => {
  assert.equal(language.destination("not a URL", "https://example.test/assets/language.js", ["en"]), null);
});
check("invalid script URL leaves the static entry alone", () => {
  assert.equal(language.destination("https://example.test/", "not a URL", ["en"]), null);
});
check("script cache query does not change the hosting path", () => {
  assert.equal(language.destination("https://example.test/site/",
    "https://example.test/site/assets/language.js?v=713", ["en"]), "https://example.test/site/en/");
});

if (failures.length) {
  console.error(`Website language routing: ${passed} passed, ${failures.length} failed.\n\n${failures.join("\n\n")}`);
  process.exitCode = 1;
} else {
  console.log(`Website language routing: ${passed} checks passed (20 languages, 3 hosting paths; no browser or DOM).`);
}
