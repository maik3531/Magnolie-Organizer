"use strict";

const assert = require("node:assert");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const handbook = [process.env.MAGNOLIE_HANDBOOK_WEB,
  path.resolve(root, "..", "magnolie-handbuch-stamm", "web"),
  path.join(root, "shared", "magnolie-handbuch-stamm", "web")]
  .filter(Boolean).find((candidate) => fs.existsSync(path.join(candidate, "inhalt.js")));
assert.ok(handbook, "Gemeinsame Handbuchquelle fehlt");
const protectedIds = ["license-and-acknowledgments", "in-closing",
  "support-with-a-coffee", "about-maik-walter"];
const requiredIds = ["kde-sms", "phone-calls", "tree-delegation", "tree-contact-sync",
  "personal-sync", "personal-conflicts-attachments", "personal-deletions-trash",
  "android-apk-transfer", "android-apk-install-update", "my-projects"];
const newlySharedIds = new Set([...requiredIds, "contacts-for-claws-mail"]);
const newPageIds = new Set([
  "nextcloud-overview", "nextcloud-account", "nextcloud-caldav-carddav",
  "nextcloud-mailbox", "nextcloud-troubleshooting", "baum-eigener-zweig",
  "baum-netzsuche", "baum-code-vergleichen", "baum-paarungsdatei-erzeugen",
  "baum-paarungsdatei-einlesen", "baum-internet-verbindung", "baum-zweig-entfernen",
  "wiederherstellungspunkte-was", "wiederherstellungspunkt-erstellen",
  "wiederherstellungspunkt-zurueckholen", "sms-mobile-only", "sms-sheet",
  "sms-adjusted-send", "sms-spelling", "sms-message-details", "sms-settings-sheet",
  "sms-delete-histories", "phone-pair-wlan-steps", "phone-pair-code-compare",
  "phone-pair-remove", "kde-pair-steps", "kde-reconnect-renew",
  "phone-call-assignment", "phone-answer-hangup", "phone-call-window-notes",
  "phone-dial-number-choice", "health-weight-height-bmi", "health-color-guide",
  "health-units", "planner-shift-planner", "planner-cycle-calendar",
  "planner-vacation-planner", "planner-waste-calendar", "calendar-monthly-weekday",
  "calendar-show-more", "recurring-appointments",
  "android-apk-transfer", "android-apk-install-update", "my-projects"
]);
const existingPendingIds = new Set([
  "the-appointment-overview", "synchronizing-with-online-accounts"
]);
const protectedDigests = {
  en: "e0c106cbf5cb046030451b18169be441acbac624f91d1dd704689664a7847260",
  de: "e46c6dafe853bedd2e9bf1161b4cc0c5cccb4fad2eaecf7f6721d22ba74c61c8",
  fr: "c70198397ccb5c3dc92cd4d3aa357e490a4eddbf86f4f7369fc99d89eca67da4",
  es: "d634a5bd2f74c9b31cbd065aa213855cb84ebc94d41b66513d7f7e0918999bd5",
  it: "b89ae576809be4a4844716758a8b75d81f0e6ad48571f96c6b3728698497fc65",
  nl: "426b073af45504b3bce2daed0b04c900f9b26b36ea4d7e475da538989c8eb15b",
  pt: "f2af4c09a60b218bfcc57ad58140879a306287c4347e67a42f29a5b86d349a9e",
  ru: "484a76e4f96cfbb74841e0988d97d01e2c8328c947e4d74634ce000e8d957aaf",
  cs: "e95f0ea025d3c16ae2a26c8f26ef938da5cbfdc6d5b0f06e39896077b596f2be",
  pl: "ae773be14d9ca4b7d8d5ec3a7cb671a91960650ea3612cc5535771f260afdd94",
  hsb: "f89323b3f01a88a625426bcfd779b52b191e0c9f04a965eedbeaea94b545040e",
  da: "8093bc2e2eeeb50b302c725651489b10890bc543a29134ef7dc9582657b6ff7b",
  nb: "9f90c6e7f639627eec3b3dc07e607f251804c0fea2e42a38fc3dfa34c49e4946",
  hi: "55bebb46f43152e164d1079012ab6acab22821d94319f59ca9fc321d3d76e35b",
  zh_CN: "123b8b3e0187563e6f08ff7bc973e87892c7601cb12c0a46a817812f50d3855c",
  ja: "3bdbddeffeaa32be3da03b1c4ffd3015d5d080039bfb6cbf94bf24a23d83ff33",
  ar: "e1fa46c4712cb50ff4c39c1aed55f489a35b76ad46852f95710b3bf0d501ab20",
  uk: "a7400edfa04b78bf868e166fce2be68bbb3e87d831de502edbe3a2d049c23ba9",
  be: "fc9547945078f0a44c69db81012dc84152c83a8fa4b2a5642f6566026ea5df88",
  tr: "70cdfc9a3a329b742b19345d509a2901ac9cb9353b4857733b96744514385300"
};
const imageDigests = {
  "01.jpg": "12dca20a3c71d34e8cbcdbe9e2a6156c8457299fb6fa3936093b1d45137050c2",
  "02.jpg": "173582bf5def28f07a374b284acb24f1245c45c412a81358d56b1074b506bdcf",
  "03.jpg": "87ae2d34ab31dd87d19619ec9c1069b07c6b04626e8cf5848d4258dc349ce56d",
  "02-woche.png": "b093e9fbea4e0c01d73edbbdbf4f0363b630399249fd27f32b48187c5df65c4f",
  "03-aufgaben.png": "878a93735d8817e4e51dbcda255cbc6e4731a2cb5fc25dff10229473a7515da3",
  "06-jahrestage.png": "c1910b7b775841f175b18a5e6790b34a0869f50bc22ab42e42e66fd25868f734",
  "10-pin-abfrage.png": "971c8dddb08f8334f164c8edc76cdabcd2c3d143f8fe59b696d13c5be1a04aa1",
  "11-stand.png": "bffd991991b6e5ac7e788d39acc3197b8119b518ccfe9411015281646e7df869",
  "14-karteikarte.png": "b4473e167b7d4ab798d1b3fa87045b29f2bbf7ffb2b28f6c69a8e65426998b18",
  "15-rechtsklick-anrufen.png": "6929566b97f55217580349ca5aa75eab2fe9ebba8b6e9ead80bbb8e8a31303e5",
  "19-karte-mit-sms.png": "2760e3e5089ac7d937e3a7c025f1cc4087ed7482ba6ac753d9598beced1d5538",
  "21-sms-getippt.png": "0429b755aabe489d831e098997640de84f7eff9cf32bca03f2498cf28fc55ea7",
  "kaffee-qr.png": "223be6adfc2aa5e6332e9802f395d66e03f01c6b0c850d46e38dfbfc1c714925",
  "maik-walter.jpg": "835a69e450c7ba1d5ae6aa59bc61b6fd5613563cfff19449b2839b53dda77fe6"
};

function digest(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function pages(directory) {
  const i18n = { registerBook() {}, locale: () => "en" };
  const context = { window: { MagnolieI18n: i18n }, MagnolieI18n: i18n };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(directory, "inhalt.js"), "utf8"), context);
  return JSON.parse(JSON.stringify(context.window.HANDBUCH_SEITEN));
}

function catalog(directory, locale) {
  if (locale === "en") return {};
  let messages;
  const context = { window: { MagnolieI18n: {
    registerCatalog(_locale, data) { messages = data.messages; }
  } } };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(directory, "i18n", `${locale}.js`), "utf8"), context);
  return messages;
}

function source(page) {
  return page._source || page;
}

const directories = { shared: handbook };
const books = Object.fromEntries(Object.entries(directories)
  .map(([name, directory]) => [name, pages(directory)]));
const reference = books.shared;
const expectedIds = reference.map((page) => page.id);
assert.strictEqual(expectedIds.length, 118, "Die kanonische Basis muss 118 Seiten enthalten");
assert.strictEqual(new Set(expectedIds).size, 118, "Kanonische Seiten-IDs sind nicht eindeutig");
for (const id of requiredIds) assert.ok(expectedIds.includes(id), `Gemeinsame Seite fehlt: ${id}`);
const projects = source(reference.find((page) => page.id === "my-projects"));
assert.ok(projects.inhalt.includes("href='https://gitlab.com/users/maik3531/projects'") &&
  projects.inhalt.includes(">https://gitlab.com/users/maik3531/projects</a>"),
"Meine Projekte muss den sichtbaren GitLab-Link enthalten");
const license = source(reference.find((page) =>
  page.id === "license-and-acknowledgments"));
assert.ok(license.inhalt.includes("Contributor-Key") &&
  license.inhalt.includes("maik3531@gmail.com") &&
  license.inhalt.includes("An email address remains optional") &&
  !license.inhalt.includes("Anyone who buys or donates"),
"Englische Lizenzseite muss E-Mail und Contributor-Key-Zustellung erklaeren");
const transferMarkup = source(reference.find((page) => page.id === "android-apk-transfer")).inhalt;
assert.ok(transferMarkup.includes("IMAGE MISSING - manifest requirement") &&
  transferMarkup.includes("data-image-manifest='android-apk-transfer-methods'"),
"android-apk-transfer: Bild-Manifestbedarf fehlt");
const installPage = reference.find((page) => page.id === "android-apk-install-update");
assert.strictEqual(installPage.entferneBildManifest, "android-apk-install-anyway");
for (const image of ["01.jpg", "02.jpg", "03.jpg"]) {
  assert.ok(installPage.inhaltAnhang.en.includes(`src='${image}'`),
    `android-apk-install-update: ${image} fehlt`);
}
const liability = reference.find((page) => page.id === "license-and-acknowledgments").inhaltAnhang;
assert.ok(liability.en.includes("Disclaimer and limitation of liability") &&
  liability.de.includes("Haftungsausschluss und Haftungsbegrenzung"),
"geschuetzter Haftungsausschluss fehlt");
assert.ok(fs.existsSync(path.join(handbook, "maik-walter-FOTO-NUTZUNG.txt")),
"gesonderter Foto-Nutzungshinweis fehlt");

for (const [locale, expectedDigest] of Object.entries(protectedDigests)) {
  for (const [name, directory] of Object.entries(directories)) {
    const messages = catalog(directory, locale);
    const values = books[name].filter((page) => protectedIds.includes(page.id)).flatMap((page) => {
      const original = source(page);
      return [original.titel, original.inhalt].map((value) => messages[value] || value);
    });
    const protectedText = values.join("\n");
    assert.ok(protectedText.includes("No valid coffee allowance") &&
      !protectedText.includes("No valid subscription"),
    `${name}/${locale}: Contributor-Branding wurde übersetzt oder ist veraltet`);
    assert.strictEqual(digest(JSON.stringify(values)), expectedDigest,
      `${name}/${locale}: geschützte Seiten wurden verändert`);
  }
}

for (const [file, expectedDigest] of Object.entries(imageDigests)) {
  for (const [name, directory] of Object.entries(directories)) {
    assert.strictEqual(digest(fs.readFileSync(path.join(directory, file))), expectedDigest,
      `${name}: geschütztes Bild wurde verändert: ${file}`);
  }
}

for (const [locale] of Object.entries(protectedDigests)) {
  for (const [name, directory] of Object.entries(directories)) {
    const messages = catalog(directory, locale);
    for (const page of books[name]) {
      const original = source(page);
      if (locale !== "en") {
        const pending = existingPendingIds.has(page.id) ||
          (locale !== "de" && newPageIds.has(page.id));
        if (!pending && (name === "shared" || newlySharedIds.has(page.id))) {
          assert.ok(messages[original.titel],
            `${name}/${locale}/${page.id}: leerer oder fehlender Titel`);
          if (original.inhalt) {
            assert.ok(messages[original.inhalt],
              `${name}/${locale}/${page.id}: leerer oder fehlender Seiteninhalt`);
          }
        }
        assert.ok(messages[original.titel] || original.titel,
          `${name}/${locale}/${page.id}: leerer Titel`);
        if (page.platzhalter !== "inhalt") {
          assert.ok(messages[original.inhalt] || original.inhalt,
            `${name}/${locale}/${page.id}: leerer Seiteninhalt`);
        }
      }
      const markup = messages[original.inhalt] || original.inhalt;
      for (const match of markup.matchAll(/data-page=['"]([^'"]*)['"]/g)) {
        assert.ok(match[1], `${name}/${locale}/${page.id}: leerer data-page-Verweis`);
        assert.ok(expectedIds.includes(match[1]),
          `${name}/${locale}/${page.id}: totes data-page-Ziel ${match[1]}`);
      }
    }
  }
}

if (process.argv.includes("--negative-probe")) {
  const protectedSource = reference.filter((page) => protectedIds.includes(page.id))
    .flatMap((page) => [source(page).titel, source(page).inhalt]);
  protectedSource[0] += " veraendert";
  assert.notStrictEqual(digest(JSON.stringify(protectedSource)), protectedDigests.en,
    "Negativprobe muss eine geschützte Textänderung erkennen");
  const changedImage = Buffer.from(fs.readFileSync(path.join(directories[referenceName], "kaffee-qr.png")));
  changedImage[0] ^= 1;
  assert.notStrictEqual(digest(changedImage), imageDigests["kaffee-qr.png"],
    "Negativprobe muss eine geschützte Bildänderung erkennen");
  console.log("HANDBOOK PROTECTION NEGATIVE PROBE PASSED");
}

console.log(`HANDBOOK PROTECTION PASSED (${Object.keys(books).length} tree(s), 118 pages, 20 locales, 4 pages, 14 images)`);
