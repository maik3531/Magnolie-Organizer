"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM, ResourceLoader, VirtualConsole } = require("jsdom");

const root = path.resolve(__dirname, "..");
const handbook = [process.env.MAGNOLIE_HANDBUCH_WEB,
  path.resolve(root, "..", "magnolie-handbuch-stamm", "web"),
  path.join(root, "shared", "magnolie-handbuch-stamm", "web")]
  .filter(Boolean).find((candidate) => fs.existsSync(path.join(candidate, "platform.js")));
assert.ok(handbook, "Gemeinsame Handbuchquelle fehlt");
const platformPath = path.join(handbook, "platform.js");
const platformSource = fs.readFileSync(platformPath, "utf8");
const installerName = "Magnolie-Organizer-Windows-2.0.0-Setup-x64.exe";
const pageIds = [
  "what-your-computer-needs",
  "installing-the-organizer",
  "starting-for-the-first-time",
  "all-day-appointments",
  "writing-letters",
  "maps-routes-and-messages",
  "appointment-reminders",
  "appearance-sound-and-anniversaries",
  "importing-data-from-other-programs",
  "moving-from-lotus-organizer",
  "exporting-data-to-other-programs",
  "synchronizing-with-online-accounts",
  "font-size-and-color",
  "version-and-updates",
  "backing-up-and-restoring",
  "troubleshooting",
  "phone-pairing",
  "platform-security-matrix"
];
const locales = ["en", "de", "ar", "be", "cs", "da", "es", "fr", "hi", "hsb",
  "it", "ja", "nb", "nl", "pl", "pt", "ru", "tr", "uk", "zh-cn"];
const importedLocales = {
  cs: ["db76c7964eb5ce755ee3fdfa0afc505361398500d777dbb672a404c59b589eed", "49d4cfeef3ef5d94635fa772441238d3f5b7b433583672865227f65c5843ee6a"],
  pl: ["ac97bb4756754028fd44b9fe6af3e9097331a711872550be55cceff678843f6d", "35812426496f34f673c3b586828535c20e36ed4f1bdd1835fd683868271df74b"],
  ru: ["8a167a6ed92f31782088bc4d4948ffd0c3a771a05e70e0e40d2233d25434063f", "5a4a7b2fd57be04882ad40c3e8f2c2411ed082aa8973e5e973ab01d30e748dd6"],
  uk: ["3ae83faf2ab0bf8cca1f78fcd4ad52634e7689646000b455e8eef0cbdb36b030", "e287460f58d99899c3384a169fbc3d031e7f395107cd350ccb65d056d63aae89"],
  be: ["4c8b2a2b34308ea425bdb6819a8150efc639d2168dbf1124d9ea568508e87f9c", "b32e016cd4f555e868394a53aafd0fe74f55998036c1c679bf09334eeb433463"],
  hsb: ["e6101744d64258ab7119f1b22f7b57cbd9d81c0270c4dbb2d5cb75793edf063e", "36b0f42b2eb1723bdae9a50e80c861807ac90297f1cf801b833d3fff36612fd9"],
  tr: ["de7253784e76eaf2854cd387d20aaab7e207ed1f2559fd5dacd7c4fdf6b0d95d", "5824b4e71f58d2d289389d1f4bacd8866f6131dd2ea57bb2f71f5332b23218d0"],
  hi: ["576944e00e70cf57d2a9806b8d581475c618c3d4d22d15d05728310f03d3188a", "d19f4012fe11d768d109a6617146e75b33bed9d7fe3ca0fffef3eb25b5db4a9e"],
  ja: ["cabe4f0f222f8c60ee9e664bd0ee0f1064a7f47ba4a19ece889dd32f54282667", "bba605b0965cc8659f6d7f5cc519b4676fa3ec06bcca528502a20ea4c8c1c949"],
  ar: ["836bbe8cc26acb1570a82b406b35740dec8a276e1e5c44b713f27c8ec2f6ecaa", "00559a364d62bd56d4019ba356432f10dad43bf5fad8e9f8e98201724ac5c1c6"],
  zh_CN: ["23b8d33fc4b701f0db4fb291db440535a9823a1d59a24bac1e8da010f1b81cb8", "e17043c908b92bec78431518b25286862a021a294b5c29e93d34b3fda5af01c1"],
  es: ["10b4735d36c0620df5f186f6ce2763f298f5825978009b3f7a7f48404bf518ce", "1f3fd50a201700f9cbb454b6ded4cf8b402f914e3d50a6e6cde6f8312badb160"],
  it: ["a8a672969d32b44dda583297d75f4f5e9eb5ae5005bb710ba1ad49e987bfdd69", "ddc402294887d18932d03c365885c8c58db380ddacbd5747424560e60fefab1e"]
};
const preservedLocaleHashes = {
  nb: "884a7ac523b39cf11b8af8535260beafa7264fc05b4549b42941d6b5a134f012"
};
const approvedSourceLocales = ["fr", "es", "it", "pt", "nl", "da"];
const importedPageIds = pageIds.filter((pageId) => pageId !== "phone-pairing");

function hash(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function localeObject(variants, locale, ids = pageIds) {
  return Object.fromEntries(ids.map((pageId) => [pageId, variants[pageId][locale]]));
}

const context = {
  window: {
    __MAGNOLIE_PLATFORM__: "windows",
    HANDBUCH_SEITEN: [],
    MagnolieI18n: { locale: () => "en" }
  },
  document: { addEventListener() {} }
};
vm.createContext(context);
vm.runInContext(platformSource.replace("const variants =", "window.__windowsVariants ="), context,
  { filename: platformPath });
const variants = JSON.parse(JSON.stringify(context.window.__windowsVariants));

assert.deepStrictEqual(Object.keys(variants), pageIds, "Es müssen exakt 18 Windows-Variantenseiten vorliegen");
assert.ok(!Object.hasOwn(variants, "license-and-acknowledgments"), "Die Lizenzseite darf keine Variante sein");
for (const pageId of pageIds) {
  assert.deepStrictEqual(Object.keys(variants[pageId]).sort(), [...locales].sort(),
    `Locale-Menge ist für ${pageId} unvollständig`);
}
assert.ok(!platformSource.includes("${installerName}"), "Sichtbares installerName-Literal gefunden");
assert.ok(!Object.values(variants).some((translations) =>
  Object.values(translations).some((content) => content.includes(" > "))), "Alter Menütrenner gefunden");
for (const locale of locales) {
  const installing = variants["installing-the-organizer"][locale];
  assert.ok(installing.includes(installerName), `Kanonischer Installer fehlt für ${locale}`);
  assert.ok(!/Magnolie-Organizer-Windows-(?!2\.0\.0)\d+\.\d+\.\d+-Setup-x64\.exe/.test(installing),
    `Abweichender Installer gefunden für ${locale}`);
}

const phoneLabels = ["Enable Magnolie Notes phone connection", "Connect phone via WLAN",
  "Codes differ", "Codes match", "Bluetooth data fallback", "Remove phone connection"];
for (const locale of locales) {
  let messages = {};
  if (locale !== "en") {
    const catalogLocale = locale === "zh-cn" ? "zh_CN" : locale;
    const catalogContext = { window: { MagnolieI18n: {
      registerCatalog(_locale, data) { messages = data.messages; }
    } } };
    vm.createContext(catalogContext);
    vm.runInContext(fs.readFileSync(path.join(root, "app", "web", "i18n", `${catalogLocale}.js`), "utf8"),
      catalogContext);
  }
  const phonePairing = variants["phone-pairing"][locale];
  for (const label of phoneLabels) {
    const visibleLabel = messages[label] || label;
    assert.ok(phonePairing.includes(`class='knopfwort'>${visibleLabel}</`),
      `Tatsächliche App-Bezeichnung fehlt für phone-pairing/${locale}: ${visibleLabel}`);
  }
  assert.ok(phonePairing.includes("8741") === false,
    `phone-pairing/${locale} darf keinen vom Dialog nicht angezeigten Portnamen erfinden`);
}

for (const [sourceLocale, [, expectedContentHash]] of Object.entries(importedLocales)) {
  const locale = sourceLocale === "zh_CN" ? "zh-cn" : sourceLocale;
  assert.strictEqual(hash(JSON.stringify(localeObject(variants, locale))), expectedContentHash,
    `Importinhalt weicht für ${sourceLocale} ab`);
}
for (const [locale, expectedHash] of Object.entries(preservedLocaleHashes)) {
  assert.strictEqual(hash(JSON.stringify(localeObject(variants, locale))), expectedHash,
    `Geschützte Ausgangsbasis weicht für ${locale} ab`);
}

const sourceDir = "/tmp/opencode/handbuch-windows-arbeit";
if (fs.existsSync(sourceDir)) {
  for (const [sourceLocale, [expectedByteHash]] of Object.entries(importedLocales)) {
    const sourceFile = path.join(sourceDir, `${sourceLocale}-alle.json`);
    const bytes = fs.readFileSync(sourceFile);
    assert.strictEqual(hash(bytes), expectedByteHash, `JSON-Quellbytes weichen für ${sourceLocale} ab`);
    const expected = JSON.parse(bytes.toString("utf8"));
    const locale = sourceLocale === "zh_CN" ? "zh-cn" : sourceLocale;
    assert.deepStrictEqual(localeObject(variants, locale, importedPageIds), expected,
      `Integrierter JSON-Inhalt weicht für ${sourceLocale} ab`);
  }
  for (const locale of approvedSourceLocales) {
    const expected = JSON.parse(fs.readFileSync(path.join(sourceDir, `${locale}-alle.json`), "utf8"));
    assert.deepStrictEqual(localeObject(variants, locale, importedPageIds), expected,
      `Integrierter JSON-Inhalt weicht für ${locale} ab`);
  }
}

class HandbookResources extends ResourceLoader {
  fetch(url) {
    const relative = new URL(url).pathname.replace(/^\//, "");
    const file = path.resolve(handbook, relative);
    if (!file.startsWith(handbook + path.sep) || !fs.existsSync(file)) return null;
    return Promise.resolve(fs.readFileSync(file));
  }
}

async function loadHandbook(locale, source) {
  const html = fs.readFileSync(path.join(handbook, "index.html"), "utf8");
  const errors = [];
  const console = new VirtualConsole();
  console.on("jsdomError", (error) => errors.push(error));
  const dom = new JSDOM(html, {
    url: "https://handbuch.magnolie.test/index.html",
    pretendToBeVisual: true,
    runScripts: "dangerously",
    resources: new HandbookResources(),
    virtualConsole: console,
    beforeParse(window) {
      window.__MAGNOLIE_PLATFORM__ = "windows";
      if (source === "app") window.__MAGNOLIE_SPRACHE__ = locale;
      if (source === "stored") window.localStorage.setItem("magnolie-handbook-locale", locale);
      if (source === "browser") {
        Object.defineProperty(window.navigator, "languages", { value: [`${locale}-TEST`] });
        Object.defineProperty(window.navigator, "language", { value: `${locale}-TEST` });
      }
    }
  });
  await new Promise((resolve, reject) => {
    dom.window.addEventListener("load", resolve, { once: true });
    setTimeout(() => reject(new Error(`DOM-Laden für ${locale} dauerte zu lange`)), 5000);
  });
  assert.deepStrictEqual(errors, [], `JSDOM-Ressourcenfehler für ${locale}`);
  return dom;
}

(async () => {
  const html = fs.readFileSync(path.join(handbook, "index.html"), "utf8");
  assert.ok(html.indexOf('src="inhalt.js"') < html.indexOf('src="platform.js"') &&
    html.indexOf('src="platform.js"') < html.indexOf('src="handbuch.js"'),
  "Plattformvarianten müssen nach dem Inhalt und vor der Handbuch-UI laden");

  for (const [index, locale] of locales.entries()) {
    const source = ["app", "browser", "stored"][index % 3];
    const dom = await loadHandbook(locale, source);
    const { window } = dom;
    assert.strictEqual(window.MagnolieI18n.locale(), locale, `Locale aus ${source} fehlt für ${locale}`);
    assert.strictEqual(window.document.documentElement.lang, locale, `HTML-Locale fehlt für ${locale}`);
    assert.ok(window.Handbuch, `Handbuch-UI wurde für ${locale} nicht initialisiert`);
    const pages = window.Handbuch.seiten();
    assert.strictEqual(pages.length, 118, `Gemeinsame Seitenmenge fehlt für ${locale}`);
    assert.strictEqual(pages.find((page) => page.id === "welcome").titel,
      window.MagnolieI18n.gettext("Welcome"), `Allgemeiner Katalog wurde für ${locale} nicht angewendet`);
    for (const pageId of pageIds) {
      assert.strictEqual(pages.find((page) => page.id === pageId).inhalt, variants[pageId][locale],
        `DOM-Variante wurde für ${pageId}/${locale} nicht angewendet`);
    }
    assert.ok(pages.some((page) => page.id === "license-and-acknowledgments"),
      `Geschützte Lizenzseite fehlt für ${locale}`);
    assert.strictEqual(pages.find((page) => page.id === "license-and-acknowledgments").titel,
      window.MagnolieI18n.gettext("License and acknowledgments"),
      `Geschützte Lizenzseite wurde für ${locale} nicht katalogisiert`);
    assert.ok(pages.some((page) => page.id === "support-with-a-coffee") &&
      pages.some((page) => page.id === "about-maik-walter"),
    `Geschützte Schlussseiten fehlen für ${locale}`);
    assert.strictEqual(window.document.title,
      window.MagnolieI18n.gettext("Magnolie Organizer - Handbook"),
      `Lokalisierter Dokumenttitel fehlt für ${locale}`);
    for (const [pageIndex, page] of pages.entries()) {
      const displayIndex = window.Handbuch.anzeige().findIndex(
        (candidate) => candidate.quellId === page.id);
      window.Handbuch.blaettereZu(displayIndex);
      const side = displayIndex % 2 ? "links" : "rechts";
      for (const link of window.document.querySelectorAll(`#inhalt-${side} [data-page]`)) {
        const targetIndex = pages.findIndex((candidate) => candidate.id === link.dataset.page);
        const targetDisplayIndex = window.Handbuch.anzeige().findIndex(
          (candidate) => candidate.quellId === link.dataset.page);
        assert.ok(targetIndex >= 0, `Toter Verweis ${page.id} -> ${link.dataset.page}/${locale}`);
        assert.strictEqual(Number(link.textContent.trim()), targetIndex + 1,
          `Verweisnummer fehlt ${page.id} -> ${link.dataset.page}/${locale}`);
        link.click();
        assert.strictEqual(window.Handbuch.bogen(), Math.floor((targetDisplayIndex + 1) / 2),
          `Verweis ist nicht anklickbar ${page.id} -> ${link.dataset.page}/${locale}`);
        window.Handbuch.blaettereZu(displayIndex);
      }
    }
    dom.window.close();
  }

  console.log(`HANDBOOK WINDOWS DOM VARIANTS PASSED (${pageIds.length} pages, ${locales.length} locales)`);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
