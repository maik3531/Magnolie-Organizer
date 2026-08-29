/* English/German integration checks for the handbook. */
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const assert = require("assert");
const childProcess = require("child_process");
const crypto = require("crypto");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const WEB = process.env.MAGNOLIE_HANDBUCH_WEB || path.join(ROOT, "web");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-handbook-test-"));
const catalogJs = path.join(temporary, "de.js");
childProcess.execFileSync("python3", [path.join(ROOT, "werkzeuge", "po_zu_js.py"), "de",
  path.join(ROOT, "po", "de.po"), catalogJs]);

const sources = {
  html: fs.readFileSync(path.join(WEB, "index.html"), "utf8"),
  i18n: fs.readFileSync(path.join(WEB, "i18n.js"), "utf8"),
  catalog: fs.readFileSync(catalogJs, "utf8"),
  content: fs.readFileSync(path.join(WEB, "inhalt.js"), "utf8"),
  handbook: fs.readFileSync(path.join(WEB, "handbuch.js"), "utf8"),
  css: fs.readFileSync(path.join(WEB, "stil.css"), "utf8"),
};
const fontDigest = (name) => crypto.createHash("sha256")
  .update(fs.readFileSync(path.join(WEB, "schriften", name))).digest("hex");
assert.match(sources.css, /--serif:\s*"Noto Serif",\s*serif;/,
  "handbook must use bundled Noto Serif on every platform");
assert.match(sources.css, /figure svg \[font-family\^="Georgia"\][^}]*"Noto Serif"/,
  "inline handbook diagrams must not retain the platform Georgia font");
assert.strictEqual(fontDigest("DejaVuSans.ttf"),
  "ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280");
assert.strictEqual(fontDigest("DejaVuSans-Bold.ttf"),
  "5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895");
assert.strictEqual(fontDigest("DejaVuSans-Oblique.ttf"),
  "2d7b524ce7d51db78591b4e19c8185b89f3af0aa6534c5e524cf0c6f4ea673de");
assert.strictEqual(fontDigest("DejaVuSans-BoldOblique.ttf"),
  "58d78a24ddff9ab30427550d68f0b9b7dd28d6690f9f4b3e4ebac7105252e9b2");
assert.strictEqual(fontDigest("NotoSerif-Regular.ttf"),
  "9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f");
assert.strictEqual(fontDigest("NotoSerif-Bold.ttf"),
  "0af0ff2be8f84910fb21ec5fe1b6b7395e3073250502a334baf6ca2f860c88fe");
assert.strictEqual(fontDigest("NotoSerif-Italic.ttf"),
  "bc25600aa27cd409e1e5b3d86340df3a329bb860fcfbe57a03a95070b229e1b0");
assert.strictEqual(fontDigest("NotoSerif-BoldItalic.ttf"),
  "78a6d685e5690b7dcda0f336b689193afc03b6bab5cf18fc1a9ecc3aa0600059");
assert.match(sources.handbook,
  /document\.fonts\?\.ready[\s\S]*document\.fonts\.ready\.then\(umbruchPlanen\)/,
  "handbook must repaginate after its bundled fonts load");
assert.strictEqual((sources.content.match(/window\.HANDBUCH_SEITEN\s*=/g) || []).length, 1,
  "handbook content must contain exactly one page-array declaration");
assert.ok(!sources.content.includes("Object.assign"),
  "handbook content must not contain page overrides");
assert.ok(!sources.content.includes("1.28.0") && !sources.content.includes("1.31.37") &&
  !sources.content.includes("1.31.69") && !sources.content.includes("1.31.80") &&
  !sources.content.includes("1.31.87") && !sources.content.includes("1.9.19"),
  "handbook content must not contain stale versions");

let catalogData;
{
  const dom = new JSDOM("<!doctype html><html><body></body></html>",
    { runScripts: "outside-only" });
  dom.window.MagnolieI18n = { registerCatalog: (_code, data) => { catalogData = data; } };
  dom.window.eval(sources.catalog);
}
assert.ok(catalogData && Object.keys(catalogData.messages).length >= 140,
  "the complete German catalog is required");
const contentDom = new JSDOM("<!doctype html><html><body></body></html>",
  { runScripts: "outside-only" });
contentDom.window.MagnolieI18n = { registerBook() {}, locale: () => "en" };
contentDom.window.eval(sources.content);
const sourcePages = JSON.parse(JSON.stringify(contentDom.window.HANDBUCH_SEITEN));
contentDom.window.close();
assert.strictEqual(sourcePages.length, 156, "the release handbook must contain exactly 156 pages");
const protectedIds = new Set(["license-and-acknowledgments", "in-closing",
  "support-with-a-coffee", "about-maik-walter"]);
assert.deepStrictEqual(sourcePages.slice(-2).map((page) => page.id),
  ["support-with-a-coffee", "about-maik-walter"],
  "the two protected closing pages must remain last and unchanged");
for (const id of ["support-with-a-coffee", "about-maik-walter"]) {
  assert.ok(sourcePages.find((page) => page.id === id).imInhalt,
    `${id} must appear in the table of contents`);
}
const digest = (values) => crypto.createHash("sha256").update(JSON.stringify(values)).digest("hex");
const protectedSource = sourcePages.filter((page) => protectedIds.has(page.id))
  .flatMap((page) => [page.titel, page.inhalt]);
assert.strictEqual(digest(protectedSource),
  "e0c106cbf5cb046030451b18169be441acbac624f91d1dd704689664a7847260",
  "license, closing, coffee, and author pages must remain byte-for-byte unchanged");
const englishLicense = sourcePages.find((page) => page.id === "license-and-acknowledgments").inhalt;
assert.ok(englishLicense.includes("Contributor-Key") &&
  englishLicense.includes("maik3531@gmail.com") &&
  englishLicense.includes("An email address remains optional") &&
  !englishLicense.includes("Anyone who buys or donates"),
"English license page lacks the coffee Contributor-Key delivery requirement");
const explicitIds = new Set(sourcePages.map((page) => page.id || page.titel.toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")));
const plannerPages = sourcePages.filter((page) => page.kapitel === "Planner");
assert.deepStrictEqual(plannerPages.map((page) => page.id || page.titel.toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")), [
  "the-year-at-a-glance", "planner-shift-planner",
  "planner-vacation-planner", "planner-waste-calendar"
], "the five auxiliary planners must be documented on exactly four pages");
const dayMarkerPage = sourcePages.find((page) => page.id === "planner-shift-planner");
assert.ok(dayMarkerPage.inhalt.includes("Shift planner") &&
  dayMarkerPage.inhalt.includes("Cycle calendar") &&
  !explicitIds.has("planner-cycle-calendar"),
"shift and cycle day markers must share their canonical handbook page");
const hardcodedPage = /\bpages?\s+(?:\d+\b|<b(?:\s[^>]*)?>\d+<\/b>)/i;
for (const page of sourcePages) {
  assert.ok(!hardcodedPage.test(page.inhalt),
    `hardcoded numeric page reference remains on ${page.titel}`);
  for (const match of page.inhalt.matchAll(/data-page=['\"]([^'\"]+)['\"]/g)) {
    assert.ok(explicitIds.has(match[1]), `${page.titel}: unknown data-page target ${match[1]}`);
  }
}
const newPageIds = new Set([
  "nextcloud-overview", "nextcloud-account", "nextcloud-caldav-carddav",
  "nextcloud-mailbox", "nextcloud-troubleshooting", "baum-eigener-zweig",
  "baum-netzsuche", "baum-code-vergleichen", "baum-paarungsdatei-erzeugen",
  "baum-paarungsdatei-einlesen", "baum-internet-verbindung", "baum-zweig-entfernen",
  "wiederherstellungspunkte-was", "sms-mobile-only", "sms-sheet",
  "sms-adjusted-send", "sms-spelling", "sms-message-details", "sms-settings-sheet",
  "sms-delete-histories", "phone-pair-wlan-steps", "phone-pair-code-compare",
  "phone-pair-remove", "kde-pair-steps", "kde-reconnect-renew",
  "phone-call-assignment", "phone-answer-hangup", "phone-call-window-notes",
  "phone-dial-number-choice", "planner-shift-planner",
  "planner-vacation-planner", "planner-waste-calendar", "calendar-monthly-weekday",
  "calendar-show-more", "android-apk-transfer",
  "android-apk-install-update", "my-projects", "the-appimage",
  "settings-language-format-region", "settings-time-week-region",
  "android-notes-navigation", "android-notes-notebooks", "android-notes-edit-save-delete",
  "android-tasks-reminders", "android-note-symbols-formatting",
  "android-import-files-folders", "android-import-formats",
  "android-share-into-notes", "android-import-results-limits",
  "android-tree-pairing", "android-tree-sharing-inbox", "android-phone-bluetooth",
  "android-personal-sync-controls", "android-personal-deletion-review", "android-recovery-journal",
  "phone-call-getting-started", "phone-call-control", "sms-getting-started", "sms-kde-connect-setup",
  "technical-connection-map", "technical-ports-firewall", "technical-local-encryption",
  "technical-tree-security-routing", "technical-phone-transport-security",
  "command-line-and-man-page", "reminder-command-modes",
  "linux-diagnostic-reminder-logs", "windows-diagnostic-logs",
  "supported-environment-variables", "technical-file-limits",
  "technical-recurring-series", "technical-reminder-time-limits",
  "technical-update-trust", "technical-update-platforms", "technical-weather-privacy",
  "glossary-a-m", "glossary-n-z"
]);
/* Every shipped language is complete; English fallback is no longer allowed. */
const pendingBodyIds = new Set([
  "settings-pages-overview", "settings-language-format-region", "settings-time-week-region"
]);
const pendingPageIds = new Set([
  "settings-pages-overview", "settings-language-format-region"
]);
const pendingMessages = (language) => {
  const offen = new Set();
  if (language === "de") return offen;
  for (const page of sourcePages) {
    if (pendingPageIds.has(page.id)) {
      for (const key of ["titel", "inhalt"]) if (page[key]) offen.add(page[key]);
    } else if (pendingBodyIds.has(page.id) && page.inhalt) {
      offen.add(page.inhalt);
    }
  }
  return offen;
};
const germanPending = pendingMessages("de");
const catalogCurrent = sourcePages.every((page) => ["kapitel", "titel", "inhalt"]
  .filter((key) => page[key])
  .every((key) => germanPending.has(page[key]) ||
    Object.prototype.hasOwnProperty.call(catalogData.messages, page[key])));
for (const id of ["android-apk-transfer", "android-apk-install-update", "my-projects",
  "android-notes-navigation", "android-notes-notebooks", "android-notes-edit-save-delete",
  "android-tasks-reminders", "android-note-symbols-formatting",
  "android-import-files-folders", "android-import-formats",
  "android-share-into-notes", "android-import-results-limits",
  "android-tree-pairing", "android-tree-sharing-inbox", "android-phone-bluetooth",
  "android-personal-sync-controls", "android-personal-deletion-review", "android-recovery-journal",
  "phone-call-getting-started", "phone-call-control", "sms-getting-started", "sms-kde-connect-setup",
  "technical-connection-map", "technical-ports-firewall", "technical-local-encryption",
  "technical-tree-security-routing", "technical-phone-transport-security",
  "command-line-and-man-page", "reminder-command-modes",
  "linux-diagnostic-reminder-logs", "windows-diagnostic-logs",
  "supported-environment-variables", "technical-file-limits",
  "technical-recurring-series", "technical-reminder-time-limits",
  "technical-update-trust", "technical-update-platforms", "technical-weather-privacy",
  "glossary-a-m", "glossary-n-z"]) {
  assert.ok(explicitIds.has(id), `new shared page is missing: ${id}`);
}
const route17Ids = ["phone-call-getting-started", "phone-call-control",
  "sms-getting-started", "sms-kde-connect-setup"];
assert.deepStrictEqual(sourcePages.slice(sourcePages.findIndex((page) =>
  page.id === "android-recovery-journal") + 1, sourcePages.findIndex((page) =>
  page.id === "technical-connection-map")).map((page) => page.id), route17Ids,
"route 17 pages must be between Android recovery and the technical pages");
const route17Text = Object.fromEntries(route17Ids.map((id) =>
  [id, sourcePages.find((page) => page.id === id)?.inhalt || ""]));
assert.ok(route17Text["phone-call-getting-started"].includes("TelecomManager.placeCall") &&
  route17Text["phone-call-getting-started"].includes("Choose a phone number to call") &&
  route17Text["phone-call-control"].includes("Share incoming call status") &&
  route17Text["phone-call-control"].includes("Bluetooth HFP") &&
  route17Text["sms-getting-started"].includes("supported only by the Linux backend") &&
  route17Text["sms-getting-started"].includes("only an <b>sms:</b> address") &&
  route17Text["sms-kde-connect-setup"].includes("<b>5,000 characters</b>") &&
  route17Text["sms-kde-connect-setup"].includes("not proof of delivery"),
"route 17 call and SMS contracts are incomplete");
const glossaryIds = ["glossary-a-m", "glossary-n-z"];
assert.deepStrictEqual(sourcePages.slice(sourcePages.findIndex((page) => page.id === "my-projects") + 1,
  sourcePages.findIndex((page) => page.id === "technical-file-limits")).map((page) => page.id),
glossaryIds, "route 18 glossary pages must follow My projects and precede the technical pages");
const glossaryText = glossaryIds.map((id) => sourcePages.find((page) => page.id === id).inhalt).join("\n");
for (const term of ["AES-256-GCM", "APK", "AppImage", "Backup", "Bluetooth", "Cache", "CalDAV",
  "CardDAV", "Checksum", "DEB", "Desktop", "DPAPI", "Ed25519", "End-to-end encryption",
  "Fingerprint", "Firewall", "HFP", "HKDF", "HMAC", "HTTPS", "ICS", "IPv4", "IPv6",
  "KDE Connect", "Local IP address", "Local network", "Magnolienbaum", "mDNS", "Nextcloud",
  "Notification", "Pairing", "PDF", "Personal Sync", "Port", "Recovery snapshot", "Recycle bin",
  "RFCOMM", "SHA-256", "SMS", "Synchronization", "Time zone", "TLS", "Tray", "UFW", "URI",
  "vCard", "VPN", "Wayland", "WebDAV", "Wi-Fi", "X11", "XDG", "ZIP"]) {
  assert.ok(glossaryText.includes(`<h3>${term}</h3><p>`), `route 18 glossary term is missing: ${term}`);
}
assert.ok(glossaryText.includes("it is not a backup against disk or device loss") &&
  glossaryText.includes("uses KDE Connect rather than Magnolie Notes or Personal Sync") &&
  glossaryText.includes("it uses no IP firewall port") &&
  glossaryText.includes("Magnolie does not create one automatically"),
"route 18 glossary definitions lack required Magnolie context");
assert.ok(sourcePages.find((page) => page.id === "phone-calls").inhalt
  .includes("TelecomManager.placeCall") &&
  sourcePages.find((page) => page.id === "phone-dial-number-choice").inhalt
    .includes("TelecomManager.placeCall") &&
  !sources.content.includes("the call must be confirmed there"),
"the handbook must describe direct Android placeCall behavior consistently");
const route15Text = Object.fromEntries([
  "command-line-and-man-page", "reminder-command-modes",
  "linux-diagnostic-reminder-logs", "windows-diagnostic-logs",
  "supported-environment-variables"
].map((id) => [id, sourcePages.find((page) => page.id === id)?.inhalt || ""]));
assert.ok(route15Text["command-line-and-man-page"].includes("ar, be, cs, da, de, en, es, fr, hi, hsb, it, ja, nb, nl, pl, pt, ru, tr, uk, zh_CN") &&
  route15Text["command-line-and-man-page"].includes("--pot-template") &&
  route15Text["reminder-command-modes"].includes("--erinnerung") &&
  route15Text["reminder-command-modes"].includes("--wecker") &&
  route15Text["reminder-command-modes"].includes("--probe") &&
  route15Text["linux-diagnostic-reminder-logs"].includes("debug.log.2") &&
  route15Text["linux-diagnostic-reminder-logs"].includes("200 lines") &&
  route15Text["windows-diagnostic-logs"].includes("kde-connect-debug.log") &&
  route15Text["windows-diagnostic-logs"].includes("5 MiB") &&
  route15Text["supported-environment-variables"].includes("MAGNOLIE_ORGANIZER_WEB") &&
  route15Text["supported-environment-variables"].includes("Build and test variables are not runtime settings"),
"route 15 command, log, and environment contracts are incomplete");
const route16Text = Object.fromEntries([
  "technical-file-limits", "technical-recurring-series", "technical-reminder-time-limits",
  "technical-update-trust", "technical-update-platforms", "technical-weather-privacy"
].map((id) => [id, sourcePages.find((page) => page.id === id)?.inhalt || ""]));
assert.ok(route16Text["technical-file-limits"].includes("200:1") &&
  route16Text["technical-file-limits"].includes("not a storage limit") &&
  route16Text["technical-recurring-series"].includes("inclusive") &&
  route16Text["technical-recurring-series"].includes("No native recurring tasks") &&
  route16Text["technical-reminder-time-limits"].includes("525,600 minutes") &&
  route16Text["technical-reminder-time-limits"].includes("once per minute") &&
  route16Text["technical-update-trust"].includes("does <b>not</b> currently verify") &&
  route16Text["technical-update-platforms"].includes("128 MiB") &&
  route16Text["technical-update-platforms"].includes("512 MiB") &&
  route16Text["technical-weather-privacy"].includes("format=j1") &&
  route16Text["technical-weather-privacy"].includes("no analogous response-size limit"),
"route 16 limits, recurrence, update, and weather contracts are incomplete");
assert.deepStrictEqual(sourcePages.slice(-8, -2).map((page) => page.id), [
  "technical-file-limits", "technical-recurring-series", "technical-reminder-time-limits",
  "technical-update-trust", "technical-update-platforms", "technical-weather-privacy"
], "route 16 pages must immediately precede the two protected closing pages");
const transferPage = sourcePages.find((page) => page.id === "android-apk-transfer");
const installPage = sourcePages.find((page) => page.id === "android-apk-install-update");
const projectsPage = sourcePages.find((page) => page.id === "my-projects");
assert.ok(transferPage.inhalt.includes("data-image-manifest='android-apk-transfer-methods'"),
  "missing Android transfer images must remain an explicit manifest requirement");
assert.strictEqual(installPage.entferneBildManifest, "android-apk-install-anyway",
  "fulfilled Android installation image manifest must be removed at rendering time");
for (const image of ["01.jpg", "02.jpg", "03.jpg"]) {
  assert.ok(installPage.inhaltAnhang.en.includes(`src='${image}'`),
    `Android installation page does not reference ${image}`);
}
const screenshotPages = {
  "02-woche.png": "the-week-view",
  "03-aufgaben.png": "the-task-list",
  "06-jahrestage.png": "birthdays-and-special-occasions",
  "10-pin-abfrage.png": "phone-pair-code-compare",
  "11-stand.png": "phone-pair-remove",
  "14-karteikarte.png": "creating-a-contact",
  "15-rechtsklick-anrufen.png": "phone-call-assignment",
  "19-karte-mit-sms.png": "sms-mobile-only",
  "21-sms-getippt.png": "sms-spelling",
};
for (const [image, pageId] of Object.entries(screenshotPages)) {
  const page = sourcePages.find((candidate) => candidate.id === pageId);
  assert.ok(fs.existsSync(path.join(WEB, image)), `handbook screenshot is missing: ${image}`);
  assert.ok(page?.inhaltAnhang?.en.includes(`src='${image}'`),
    `${pageId} does not reference ${image}`);
}
assert.ok(sourcePages.find((page) => page.id === "kde-sms").inhaltAnhang.de.includes("seit 2019") &&
  sourcePages.find((page) => page.id === "sms-kde-connect-setup").inhaltAnhang.de
    .includes("KDE Connect auf Android installieren") &&
  sourcePages.find((page) => page.id === "sms-kde-connect-setup").inhaltAnhang.de
    .includes("Eingereiht ist nicht gesendet") &&
  sourcePages.find((page) => page.id === "sms-delete-histories").inhaltAnhang.de
    .includes("SMS-Einstellungen") &&
  sourcePages.find((page) => page.id === "sms-delete-histories").inhaltAnhang.de
    .includes("Alle SMS-Verläufe löschen") &&
  sourcePages.find((page) => page.id === "phone-call-assignment").inhaltAnhang.de
    .includes("Gesprächston über Bluetooth") &&
  sourcePages.find((page) => page.id === "phone-call-assignment").inhaltAnhang.de
    .includes("Anrufsteuerung Schritt für Schritt") &&
  sourcePages.find((page) => page.id === "phone-call-assignment").inhaltAnhang.de
    .includes("Bluetooth-Datenfallback") &&
  sourcePages.find((page) => page.id === "phone-call-assignment").inhaltAnhang.de
    .includes("Android-Systemberechtigungen"),
"German SMS rationale or Bluetooth audio explanation is missing");
const liabilityAppendix = sourcePages.find((page) =>
  page.id === "license-and-acknowledgments").inhaltAnhang;
assert.ok(liabilityAppendix.en.includes("Disclaimer and limitation of liability") &&
  liabilityAppendix.de.includes("Haftungsausschluss und Haftungsbegrenzung") &&
  liabilityAppendix.de.includes("Zwingende gesetzliche Rechte"),
"detailed liability disclaimer is missing");
assert.ok(projectsPage.inhalt.includes("href='https://gitlab.com/users/maik3531/projects'") &&
  projectsPage.inhalt.includes(">https://gitlab.com/users/maik3531/projects</a>"),
"My projects must contain the visible canonical GitLab link");
for (const page of [transferPage, installPage, projectsPage]) {
  for (const key of ["kapitel", "titel", "inhalt"]) {
    assert.ok(catalogData.messages[page[key]], `German catalog lacks ${key} for ${page.id}`);
  }
}

const languages = fs.readFileSync(path.join(ROOT, "po", "LINGUAS"), "utf8").trim().split(/\s+/);
assert.strictEqual(languages.length, 19, "exactly 19 handbook translations are required");
const reviewedPages = new Set(["Connecting over a network or the Internet",
  "SMS with KDE Connect", "Calls from the desktop",
  "Deletion proposals and synchronized trash", "Platform and security matrix",
  "Password protection and encryption", "Backing up and restoring",
  "External backups", "Exporting data to other programs"]);
const protectedCatalogDigests = {
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
  tr: "70cdfc9a3a329b742b19345d509a2901ac9cb9353b4857733b96744514385300",
};
for (const language of languages) {
  const generated = path.join(temporary, `${language}.js`);
  childProcess.execFileSync("python3", [path.join(ROOT, "werkzeuge", "po_zu_js.py"), language,
    path.join(ROOT, "po", `${language}.po`), generated]);
  let data;
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { runScripts: "outside-only" });
  dom.window.MagnolieI18n = { registerCatalog: (_code, value) => { data = value; } };
  dom.window.eval(fs.readFileSync(generated, "utf8"));
  const allowedPending = pendingMessages(language);
  assert.strictEqual(fs.readFileSync(generated, "utf8"),
    fs.readFileSync(path.join(WEB, "i18n", `${language}.js`), "utf8"),
    `${language}: checked-in JS catalog differs from PO output`);
  const protectedTranslations = protectedSource.map((message) => data.messages[message]);
  const protectedTranslationText = protectedTranslations.join("\n");
  assert.ok(protectedTranslationText.includes("No valid coffee allowance") &&
    !protectedTranslationText.includes("No valid subscription"),
  `${language}: contributor branding was translated or is stale`);
  assert.strictEqual(digest(protectedTranslations), protectedCatalogDigests[language],
    `${language}: protected license/closing/coffee/author translation changed`);
  for (const page of sourcePages) {
    for (const key of ["kapitel", "titel", "inhalt"]) {
      if (!page[key]) continue;
      if (allowedPending.has(page[key]) &&
          !Object.prototype.hasOwnProperty.call(data.messages, page[key])) {
        continue;
      }
      assert.ok(Object.prototype.hasOwnProperty.call(data.messages, page[key]),
        `${language}: catalog lacks ${key} ${page.titel}`);
      assert.ok(data.messages[page[key]], `${language}: empty translation for ${page.titel}`);
      if (key === "inhalt") {
        assert.ok(isBalancedHtml(data.messages[page[key]]),
          `${language}: unbalanced HTML on ${page.titel}`);
        if (!["ar", "ja", "zh_CN"].includes(language) &&
            !["License and acknowledgments", "In closing",
              "Support Magnolie with a coffee",
              "About the programmer and author of this book"].includes(page.titel)) {
          assert.ok(!missingInlineSpacing(data.messages[page[key]]),
          `${language}: missing whitespace around inline HTML on ${page.titel}`);
        }
        for (const match of data.messages[page[key]].matchAll(/data-page=['"]([^'"]+)['"]/g)) {
          assert.ok(explicitIds.has(match[1]),
            `${language}: unknown data-page target ${match[1]} on ${page.titel}`);
        }
        if (reviewedPages.has(page.titel)) {
          assert.deepStrictEqual(tags(data.messages[page[key]]), tags(page[key]),
            `${language}: HTML structure changed on ${page.titel}`);
        }
        const sourceWords = page[key].replace(/<[^>]+>/g, "").length;
        const translatedWords = data.messages[page[key]].replace(/<[^>]+>/g, "").length;
        assert.ok(translatedWords >= sourceWords * .2,
          `${language}: translation is unexpectedly truncated on ${page.titel}`);
        if (page.titel !== "Version and updates" && !protectedIds.has(page.id)) {
          assert.notStrictEqual(data.messages[page[key]], page[key],
            `${language}: English page fallback remains on ${page.titel}`);
        }
        if (page.titel === "Sharing entries securely") {
          for (const tag of ["<h3>", "<p>", "<b>", "<span class='knopfwort'>",
            "<div class='achtung'>", "<div class='merke'>"]) {
            assert.ok(data.messages[page[key]].includes(tag),
              `${language}: required HTML structure ${tag} missing on ${page.titel}`);
          }
          const digits = data.messages[page[key]].replace(/\D/g, "");
          for (const value of ["2800000", "12000000", "24000000", "256", "512",
            "10", "50"]) {
            assert.ok(digits.includes(value),
              `${language}: synchronization limit ${value} changed on ${page.titel}`);
          }
          assert.ok(data.messages[page[key]].includes("2.0.10") &&
            data.messages[page[key]].includes("1.0.9"),
          `${language}: supported version changed on ${page.titel}`);
        }
        const protectedByPage = {
          "Connecting over a network or the Internet": ["magnolie-phone/1", "RFCOMM",
            "os_restricted"],
          "SMS with KDE Connect": ["magnolie-phone/1", "10", "READ_SMS"],
          "Calls from the desktop": ["answer_call", "end_call"],
          "Synchronizing your own notes and tasks": ["own_device", "personal_notes_sync",
            "personal_tasks_sync", "personal_deletions_sync", "15"],
          "Conflicts and attachments": ["JPEG", "PNG", "WebP", "GIF", "PDF",
            "8", "64", "SHA-256", "RFCOMM"],
          "Deletion proposals and synchronized trash": ["restore_unavailable",
            "personal_deletions_sync"],
          "Platform and security matrix": ["magnolie-phone/1", "RFCOMM", "not_implemented",
            "phone.db"]
        };
        for (const token of protectedByPage[page.titel] || []) {
          assert.ok(data.messages[page[key]].includes(token),
            `${language}: protected token ${token} changed on ${page.titel}`);
        }
      }
    }
  }
  const license = data.messages[sourcePages.find((page) =>
    page.titel === "License and acknowledgments").inhalt];
  assert.ok(license.includes("maik3531@gmail.com"),
    `${language}: coffee email address is missing`);
  const coffee = data.messages[sourcePages.find((page) =>
    page.id === "support-with-a-coffee").inhalt];
  const notice = (markup) => markup.match(/<div class='achtung'>[\s\S]*?<\/div>/)?.[0];
  assert.ok(notice(license), `${language}: localized Contributor-Key notice is missing`);
  assert.strictEqual(notice(license), notice(coffee),
    `${language}: license notice differs from the voluntary coffee-page wording`);
  if (language === "ar") {
    assert.ok(!/[\uFB50-\uFDFF\uFE70-\uFEFF]/u.test(JSON.stringify(data.messages)),
      "ar: Arabic presentation-form characters are forbidden");
  }
  if (language === "es") {
    const spanish = JSON.stringify(data.messages);
    assert.ok(!spanish.includes("Configuración ▸ General") &&
      !spanish.includes("Configuración ▸ Contactos") && !spanish.includes("Verificar ahora"),
      "es: stale Organizer UI terms remain");
    assert.ok(spanish.includes("Ajustes"),
      "es: confirmed Organizer UI term is missing");
  }
  dom.window.close();
}

function createBook(locale) {
  const dom = new JSDOM(sources.html, { url: "https://handbook.test/",
    pretendToBeVisual: true, runScripts: "outside-only" });
  const w = dom.window;
  w.eval(sources.i18n);
  w.eval(sources.catalog);
  w.MagnolieI18n.setLocale(locale);
  w.eval(sources.content);
  w.eval(sources.handbook);
  if (!w.Handbuch) w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  return { dom, w, d: w.document, H: w.Handbuch };
}

function tags(markup) {
  return (markup.match(/<[^>]+>/g) || [])
    .map((tag) => tag.replace(/\s+alt=(['"]).*?\1/g, ""));
}

function isBalancedHtml(markup) {
  const stack = [];
  const voidTags = new Set(["br", "hr", "img", "input", "meta", "link"]);
  for (const match of markup.matchAll(/<\/?([a-z][a-z0-9]*)\b[^>]*>/gi)) {
    const tag = match[1].toLowerCase();
    if (voidTags.has(tag) || match[0].endsWith("/>")) continue;
    if (match[0][1] === "/") {
      if (stack.pop() !== tag) return false;
    } else {
      stack.push(tag);
    }
  }
  return stack.length === 0;
}

function missingInlineSpacing(markup) {
  for (const match of markup.matchAll(/<(?:p|li)\b[^>]*>.*?<\/(?:p|li)>/gs)) {
    if (/(?:[A-Za-zÀ-žА-я]<(?:b|i|kbd|span|a)\b|<\/(?:b|i|kbd|span|a)>[A-Za-zÀ-žА-я])/
      .test(match[0])) return true;
  }
  return false;
}

function technicalValues(markup) {
  return (markup.replace(/[\s\u00a0](?=\d{3}(?:\D|$))/g, "")
    .match(/(?:https?:\/\/[^\s<'"]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d+(?:[.,]\d+){1,3}\b|sudo apt install[^<]+|magnolie-organizer --[\w-]+)/g) || [])
    .map((value) => value.replace(/hunspell-(?:de-de|en-(?:us|gb))/, "hunspell-DICTIONARY"))
    .map((value) => /^\d{1,3}(?:[.,]\d{3})+$/.test(value)
      ? value.replace(/[.,]/g, "") : value);
}

function checkLocale(locale, expected) {
  const { dom, w, d, H } = createBook(locale);
  const $ = (selector) => d.querySelector(selector);
  assert.ok(H, `${locale}: handbook runtime missing`);
  assert.strictEqual(d.documentElement.lang, locale);
  assert.strictEqual(d.documentElement.dir, locale === "ar" ? "rtl" : "ltr");
  assert.strictEqual(d.title, expected.documentTitle);
  const pages = H.seiten();
  assert.ok(pages.length >= 71, `${locale}: handbook pages are incomplete`);
  assert.ok(pages.every((page) => page.titel && page.inhalt !== undefined));
  assert.ok(pages.every((page) => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(page.id)),
    `${locale}: every page needs a stable slug`);
  assert.strictEqual(new Set(pages.map((page) => page.id)).size, pages.length,
    `${locale}: page slugs must be unique`);
  assert.strictEqual(pages.filter((page) => page.platzhalter === "inhalt").length, 2);
  assert.ok(pages.filter((page) => page.imInhalt).length >= 50);

  for (const page of pages) {
    for (const key of ["kapitel", "titel", "inhalt"]) {
      const source = page._source[key];
      if (!source) continue;
      const translated = Object.prototype.hasOwnProperty.call(catalogData.messages, source);
      if (catalogCurrent && !germanPending.has(source)) {
        assert.ok(translated, `${locale}: catalog lacks ${key} ${page._source.titel}`);
      }
      if (locale === "de" && translated && key !== "inhalt") {
        assert.strictEqual(page[key], catalogData.messages[source]);
      } else if (locale === "de" && !translated && key !== "inhalt") {
        assert.strictEqual(page[key], source);
      } else {
        assert.ok(page[key]);
      }
    }
    if (page.platzhalter !== "inhalt" && !page.inhaltAnhang && !newPageIds.has(page.id) &&
        !protectedIds.has(page.id)) {
      assert.deepStrictEqual(tags(page.inhalt), tags(page._source.inhalt),
        `${locale}: HTML structure changed on ${page._source.titel}`);
      assert.deepStrictEqual([...new Set(technicalValues(page.inhalt))],
        [...new Set(technicalValues(page._source.inhalt))],
        `${locale}: technical data changed on ${page._source.titel}`);
    }
  }

  assert.strictEqual($("#knopf-inhalt").textContent, expected.contents);
  assert.strictEqual($("#knopf-suche").textContent, expected.search);
  assert.strictEqual($("#handbuch-suchfeld").placeholder, expected.searchHandbook);
  assert.strictEqual($("#handbuch-suche-schliessen").getAttribute("aria-label"),
    expected.closeSearch);
  assert.strictEqual($("#knopf-drucken").textContent, expected.print);
  assert.strictEqual($("#deckel").title, expected.openTitle);
  assert.strictEqual($("#ecke-links").title, expected.backTitle);
  assert.strictEqual($("#ecke-rechts").title, expected.forwardTitle);
  assert.ok(!$("#buch").classList.contains("offen"));
  $("#deckel").click();
  assert.ok($("#buch").classList.contains("offen"));
  $("#ecke-rechts").click();
  assert.strictEqual(H.bogen(), 1);
  $("#ecke-links").click();
  assert.strictEqual(H.bogen(), 0);

  H.blaettereZu(1);
  const tocEntry = $(".inhalt-eintrag");
  assert.ok(tocEntry, `${locale}: table of contents is empty`);
  const target = H.anzeige().findIndex((page) =>
    page.quellId === tocEntry.dataset.handbookTarget);
  tocEntry.click();
  assert.strictEqual(H.bogen(), Math.floor((target + 1) / 2));
  assert.ok(H.blaettereZuId("contents-continued"),
    `${locale}: stable ID of the continued contents page is not navigable`);

  $("#knopf-suche").focus();
  const searchEvent = new w.KeyboardEvent("keydown", { key: "f", ctrlKey: true,
    bubbles: true, cancelable: true });
  d.dispatchEvent(searchEvent);
  assert.ok(searchEvent.defaultPrevented, `${locale}: Ctrl+F is not handled by the handbook`);
  assert.ok(!$("#handbuch-suche").hidden && d.activeElement === $("#handbuch-suchfeld"),
    `${locale}: handbook search does not open and focus`);
  const spreadBeforeInputKey = H.bogen();
  const inputArrow = new w.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true,
    cancelable: true });
  $("#handbuch-suchfeld").dispatchEvent(inputArrow);
  assert.ok(!inputArrow.defaultPrevented && H.bogen() === spreadBeforeInputKey,
    `${locale}: handbook page navigation captures keys in the search field`);
  $("#handbuch-suchfeld").value = "SMS";
  $("#handbuch-suchfeld").dispatchEvent(new w.Event("input", { bubbles: true }));
  const smsIds = H.suche("SMS");
  for (const id of ["kde-sms", "sms-sheet", "sms-spelling", "sms-delete-histories"]) {
    assert.ok(smsIds.includes(id), `${locale}: SMS search omits ${id}`);
  }
  assert.strictEqual(new Set(smsIds).size, smsIds.length,
    `${locale}: search lists a logical page more than once`);
  const smsTarget = $(".handbuch-suchtreffer[data-page='kde-sms']");
  assert.ok(smsTarget, `${locale}: clickable KDE SMS search result is missing`);
  assert.strictEqual(smsTarget.getAttribute("role"), null);
  assert.strictEqual(smsTarget.parentElement.getAttribute("role"), "listitem");
  const smsIndex = H.anzeige().findIndex((page) => page.quellId === "kde-sms");
  smsTarget.click();
  assert.strictEqual(H.bogen(), Math.floor((smsIndex + 1) / 2),
    `${locale}: search result uses a stale page index`);
  assert.ok($("#handbuch-suche").hidden, `${locale}: search does not close after navigation`);
  assert.strictEqual(d.activeElement, $("#knopf-suche"),
    `${locale}: search does not restore focus after navigation`);
  H.sucheOeffnen();
  $("#handbuch-suchfeld").value = "definitely-no-handbook-result";
  $("#handbuch-suchfeld").dispatchEvent(new w.Event("input", { bubbles: true }));
  assert.strictEqual($(".handbuch-suche-leer").textContent, expected.noResults);
  d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true,
    cancelable: true }));
  assert.ok($("#handbuch-suche").hidden, `${locale}: Escape does not close search`);
  assert.strictEqual(d.activeElement, $("#knopf-suche"),
    `${locale}: Escape does not restore search focus`);
  const metaSearch = new w.KeyboardEvent("keydown", { key: "f", metaKey: true,
    bubbles: true, cancelable: true });
  d.dispatchEvent(metaSearch);
  assert.ok(metaSearch.defaultPrevented && !$("#handbuch-suche").hidden,
    `${locale}: Cmd+F is not handled by the handbook`);
  $("#handbuch-suche-schliessen").click();

  H.blaettereZu(1);
  const generatedTrigger = $(".inhalt-eintrag");
  generatedTrigger.focus();
  H.sucheOeffnen();
  $("#handbuch-suchfeld").value = "SMS";
  $("#handbuch-suchfeld").dispatchEvent(new w.Event("input", { bubbles: true }));
  $(".handbuch-suchtreffer[data-page='kde-sms']").click();
  assert.strictEqual(d.activeElement, $("#knopf-suche"),
    `${locale}: search leaves focus hidden after replacing its trigger page`);

  H.blaettereZu(H.anzeige().length - 1);
  const renderedPages = H.anzeige();
  assert.ok($("#ecke-rechts").classList.contains("aus"));
  assert.ok($("#stand").textContent.startsWith(expected.page));
  assert.ok($("#stand").textContent.includes(String(pages.length)),
    `${locale}: unexpected final page status: ${$("#stand").textContent}`);

  const print = H.druckFassung();
  assert.ok(print.startsWith("<!DOCTYPE html"));
  assert.ok(print.includes(`<html lang='${locale}'>`));
  assert.ok(print.includes(`<title>${expected.printTitle}</title>`));
  const gedruckteSeiten = H.anzeige().length;
  assert.strictEqual((print.match(/class="blatt(?: kompakt)?"/g) || []).length,
    gedruckteSeiten);
  assert.strictEqual((print.match(/class="blatt-inhalt"/g) || []).length,
    gedruckteSeiten);
  /* Ein Bogen traegt zwei Seiten; eine ungerade Zahl endet mit einem Leerblatt. */
  assert.strictEqual((print.match(/class="bogen"/g) || []).length,
    Math.ceil(gedruckteSeiten / 2));
  assert.strictEqual((print.match(/class="leerblatt"/g) || []).length,
    gedruckteSeiten % 2);
  assert.strictEqual((print.match(/class="bindung"/g) || []).length,
    Math.ceil(gedruckteSeiten / 2));
  assert.ok(print.includes(expected.footer));
  assert.ok(print.includes("size: A4 landscape") && print.includes("font: 11.5pt/1.45"));
  assert.ok(print.includes("width: 297mm") && print.includes("height: 210mm"),
    `${locale}: printed sheet is not an A4 spread`);
  assert.ok(!print.includes("height: 267mm") && !print.includes("height: 297mm"));
  assert.ok(!print.includes("handbuch-suche"), `${locale}: search UI leaked into print output`);

  for (const text of expected.completeText) {
    assert.ok(print.includes(text), `${locale}: missing complete-book marker: ${text}`);
  }
  for (const preserved of ["backing-up-and-restoring", "magnolie-organizer_2.0.10_all.deb",
    "sudo apt install ./magnolie-organizer_2.0.10_all.deb", "wttr.in",
    "maik3531@gmail.com", "2.0.10"]) {
    assert.ok(print.includes(preserved), `${locale}: technical value changed: ${preserved}`);
  }
  assert.ok(!print.includes("1.28.0") && !print.includes("1.31.37") &&
    !print.includes("1.31.69") && !print.includes("1.31.80") &&
    !print.includes("1.31.87") && !print.includes("1.9.19"),
    `${locale}: stale Organizer version remains`);
  dom.window.close();
}

function checkLocaleTransition() {
  const { dom, w, d, H } = createBook("en");
  const $ = (selector) => d.querySelector(selector);
  $("#deckel").click();
  H.blaettereZuId("appointment-reminders");

  assert.ok([...d.querySelectorAll("#kopf-links h2, #kopf-rechts h2")]
    .some((heading) => heading.textContent === "Appointment reminders"));
  assert.ok([...d.querySelectorAll("#inhalt-links, #inhalt-rechts")]
    .some((content) => content.textContent.includes("notify you before an appointment begins")));
  assert.ok($("#stand").textContent.startsWith("Page "));

  w.MagnolieI18n.setLocale("de");
  assert.strictEqual(d.documentElement.lang, "de");
  assert.strictEqual(d.title, "Magnolie Organizer – Handbuch");
  assert.ok([...d.querySelectorAll("#kopf-links h2, #kopf-rechts h2")]
    .some((heading) => heading.textContent === "An Termine erinnern lassen"));
  assert.ok([...d.querySelectorAll("#inhalt-links, #inhalt-rechts")]
    .some((content) => content.textContent.includes("bevor ein Termin beginnt")));
  assert.ok($("#stand").textContent.startsWith("Seite "));
  assert.strictEqual($("#knopf-inhalt").textContent, "Inhalt");
  H.blaettereZu(1);
  assert.ok($(".inhalt-eintrag").textContent.includes("Was der Organizer für Sie tut"));
  let print = H.druckFassung();
  assert.ok(print.includes("<html lang='de'>"));
  assert.ok(print.includes("<title>Magnolie Organizer – Handbuch</title>"));
  assert.ok(print.includes("Magnolie Organizer · Handbuch"));

  w.MagnolieI18n.setLocale("en");
  assert.strictEqual(d.documentElement.lang, "en");
  assert.strictEqual(d.title, "Magnolie Organizer - Handbook");
  assert.ok($("#stand").textContent.startsWith("Page "));
  assert.strictEqual($("#knopf-inhalt").textContent, "Contents");
  assert.ok($(".inhalt-eintrag").textContent.includes("What the Organizer can do for you"));
  print = H.druckFassung();
  assert.ok(print.includes("<html lang='en'>"));
  assert.ok(print.includes("<title>Magnolie Organizer - Handbook</title>"));
  assert.ok(print.includes("Magnolie Organizer · Handbook"));
  dom.window.close();
}

try {
  checkLocale("en", {
    documentTitle: "Magnolie Organizer - Handbook", contents: "Contents", search: "Search",
    searchHandbook: "Search handbook", closeSearch: "Close search",
    noResults: "No matching handbook pages.",
    print: "Print / PDF", openTitle: "Click to open", backTitle: "Back one spread",
    forwardTitle: "Forward one spread", page: "Page ",
    printTitle: "Magnolie Organizer - Handbook", footer: "Magnolie Organizer · Handbook",
    completeText: ["Welcome", "Recurring appointments", "Magnolienbaum", "Recycle bin",
      "Password", "Backup", "License", "Individual notification", "Emergency contacts",
      "DIN 5008", "Claws Mail", "Wayland", "GNU General Public License"]
  });
  checkLocale("de", {
    documentTitle: "Magnolie Organizer – Handbuch", contents: "Inhalt", search: "Suchen",
    searchHandbook: "Handbuch durchsuchen", closeSearch: "Suche schließen",
    noResults: "Keine passenden Handbuchseiten gefunden.",
    print: "Drucken / PDF", openTitle: "Zum Öffnen anklicken", backTitle: "Zurückblättern",
    forwardTitle: "Weiterblättern", page: "Seite ",
    printTitle: "Magnolie Organizer – Handbuch", footer: "Magnolie Organizer · Handbuch",
    completeText: ["Willkommen", "Wiederkehrende Termine", "Magnolienbaum", "Papierkorb",
      "Kennwort", "Sicherung", "Lizenz", "Individuelle Benachrichtigung",
      "Notfallkontakte", "DIN 5008", "Claws Mail", "Wayland",
      "GNU General Public License"]
  });
  checkLocaleTransition();

  const english = createBook("en");
  const german = createBook("de");
  const englishText = english.H.seiten().map((page) => `${page.titel}\n${page.inhalt}`).join("\n");
  const germanText = german.H.seiten().map((page) => `${page.titel}\n${page.inhalt}`).join("\n");
  assert.ok(germanText.includes("unter Linux und unter Windows dasselbe Programm") &&
    germanText.includes("Magnolie Notes") && germanText.includes("Android"),
  "German platform overview is missing");
  assert.ok(germanText.includes("No valid coffee allowance") &&
    !germanText.includes("No valid subscription") &&
    germanText.includes("uneingeschränkt nutzen") &&
    germanText.includes("kein regulärer Supportanspruch") &&
    germanText.includes("selbstverständlich geprüft und nicht ignoriert") &&
    germanText.includes("GPL einen Eigenbau ohne Branding erstellen"),
  "German branding and self-build note is missing");
  assert.ok(englishText.includes("<kbd>Ctrl</kbd>+<kbd>D</kbd> for strikethrough"));
  assert.ok(!englishText.includes("<kbd>Ctrl</kbd>+<kbd>S</kbd>"));
  assert.ok(germanText.includes("<kbd>Strg</kbd>+<kbd>D</kbd> durchgestrichen"));
  assert.ok(!germanText.includes("<kbd>Strg</kbd>+<kbd>S</kbd>"));
  assert.ok(!englishText.includes("Addresses"), "English UI terminology must use Contacts");
  for (const phrase of ["The <b>Contacts</b> section", "Click the <b>Contacts</b> tab",
    "Settings ▸ Contacts", "<b>Contacts (.vcf)</b>", "<i>appointments.csv</i>"]) {
    assert.ok(englishText.includes(phrase), `English Contacts regression phrase missing: ${phrase}`);
  }
  assert.ok(!englishText.includes("<i>termine.csv</i>"));
  assert.ok(germanText.includes("<i>termine.csv</i>"));
  assert.ok(!germanText.includes("<i>appointments.csv</i>"));
  assert.ok(germanText.includes("Adressen"), "canonical German UI terminology must remain");
  for (const phrase of ["Teams, Snapchat, TikTok, YouTube, Telegram, X, LinkedIn, Reddit",
    "custom service", "Twitch, IRC, Discord, Matrix, Slack, or GitHub",
    "requires a secure HTTPS address"]) {
    assert.ok(englishText.includes(phrase), `English social-media paragraph missing: ${phrase}`);
  }
  for (const phrase of ["Teams, Snapchat, TikTok, YouTube, Telegram, X, LinkedIn, Reddit",
    "eigenen Dienst", "Twitch, IRC, Discord, Matrix, Slack oder GitHub",
    "verlangt eine sichere HTTPS-Adresse"]) {
    assert.ok(germanText.includes(phrase), `German social-media paragraph missing: ${phrase}`);
  }
  for (const phrase of ["Selection options", "Delete selection", "Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>H",
    "accessibility helper frame", "uppermost dialog", "Focus then returns",
    "WebKitGTK 2.38", "move between dates"]) {
    assert.ok(englishText.includes(phrase), `English handbook phrase missing: ${phrase}`);
  }
  for (const phrase of ["Auswahloptionen", "Auswahl löschen", "Strg</kbd>+<kbd>Alt</kbd>+<kbd>H",
    "Barrierefreiheits-Hilfsrahmen", "obersten Dialog", "Fokus zum Auslöser oder",
    "WebKitGTK 2.38", "einen Tag", "zwischen den Daten"]) {
    assert.ok(germanText.includes(phrase), `German handbook phrase missing: ${phrase}`);
  }
  assert.ok(!englishText.includes("A second print button on the contact card") &&
    !germanText.includes("zweiter Druckknopf nötig"),
  "stale contact-card print-button claim remains");
  for (const phrase of ["Exporting selected Contacts to ODS",
    "primary street and house number", "landline, mobile number and email addresses",
    "without repeated standard labels", "initially collapsed", "one vertical list",
    "one per line without labels", "linked by name only", "dedicated additional columns",
    "configured as an A4 landscape table"]) {
    assert.ok(englishText.includes(phrase), `English ODS paragraph missing: ${phrase}`);
  }
  for (const phrase of ["Ausgewählte Adressen als ODS exportieren",
    "Hauptstraße und Hausnummer", "Festnetz, Mobilnummer und E-Mail-Adressen",
    "ohne wiederholte Standardbezeichnungen", "zunächst eingeklappt", "senkrechten Liste",
    "ohne Bezeichnung einzeln untereinander", "nur über den Namen zugeordnet",
    "eigenen Zusatzspalten",
    "als A4-Querformat eingerichtet"]) {
    assert.ok(germanText.includes(phrase), `German ODS paragraph missing: ${phrase}`);
  }
  assert.ok(englishText.includes(
    "removes checked Contacts, Tasks, appointments, Notes or Anniversaries") &&
    germanText.includes(
      "entfernt markierte Adressen, Aufgaben, Termine, Notizen oder Jahrestage") &&
    !englishText.includes("do not offer bulk deletion") &&
    !germanText.includes("kein Sammellöschen"),
  "bulk deletion for Notes and Anniversaries is not documented consistently");
  for (const phrase of ["Print and ODS", "Year calendar", "Month calendar",
    "five entry bars", "Early shift", "Late shift", "Night shift",
    "three bleeding intensities", "Vacation planner", "Waste collection calendar",
    "Residual waste", "Packaging / Yellow bin", "fortnightly", "not a bin symbol",
    "initially switched off", "without confirmation or a recycle-bin copy",
  ]) {
    assert.ok(englishText.toLowerCase().includes(phrase.toLowerCase()),
      `English planner print paragraph missing: ${phrase}`);
  }
  for (const phrase of ["Settings ▸ General ▸ Tabs", "Nothing is deleted",
    "hidden section may disappear", "four subviews", "double-page table",
    "Systolic", "Diastolic", "Measurement situation", "mmol/L", "mg/dL",
    "Tablet", "Drops", "Powder", "Spray", "Pen", "fixed index number",
    "Long-acting", "Short-acting", "several documented rules", "matching rule is highlighted",
    "no permanent spinner arrows", "point or a comma", "0.1", "0.5 IE",
    "converts the entered and saved", "3.5–5.5", "at least 13.9",
    "90–129", "60–84", "130–139", "85–89", "begins at 140", "90 diastolic",
    "general adult", "not a diagnosis", "Personal targets can differ",
    "Recheck an unexpected value", "local emergency service",
    "Never dose insulin according to", "actually injected", "closed frame on all four sides",
    "Today marker", "Vital readings", "optional blood-sugar", "Medication plan",
    "Single progress report", "table and graph", "All six graphs",
    "three on the left and three on the right", "Blank template", "with recorded values",
    "From", "Through", "A4 landscape", "ODS", "Delete"]) {
    assert.ok(englishText.toLowerCase().includes(phrase.toLowerCase()),
      `English health documentation missing: ${phrase}`);
  }
  for (const phrase of ["magnolie-phone/1", "exactly one pinned own phone", "Wi-Fi is available",
    "use RFCOMM manually", "os_restricted", "granular", "KDE Connect is the only SMS path",
    "incoming and outgoing", "deduplicate", "10 segments", "does not claim <b>READ_SMS</b>",
    "answer_call", "end_call", "changing revision", "offhook", "Audio stays on the phone",
    "own_device", "personal_notes_sync", "personal_tasks_sync", "personal_deletions_sync",
    "Shared Magnolienbaum notes", "delegated tasks", "Wi-Fi only", "15 minute", "not a schedule",
    "change vectors", "deterministic conflict-copy", "format 2", "8 MiB", "<b>64</b>",
    "SHA-256", "encrypted chunks", "proposal", "nonempty notebooks", "Tombstones",
    "restore_unavailable", "Platform and security matrix", "outside the main password transaction",
    "Cloud backup is disabled", "not a backup", "clearing app data", "recovery journal", "phone.db",
    "not_implemented", "conversation requests", "Delete all", "Restore all",
    "%LOCALAPPDATA%\\Magnolie Organizer\\daten.json", "Documents\\Magnolie Organizer\\Sicherungen",
    "PBKDF2-HMAC-SHA-256", "240,000 rounds", "offline", ".magnolie"]) {
    assert.ok(englishText.includes(phrase), `English phone/sync/security documentation missing: ${phrase}`);
  }
  for (const stale of ["WRITE_SMS", "new SMS", "call_control",
    "No call control at present"]) {
    assert.ok(!englishText.includes(stale), `stale native phone claim remains: ${stale}`);
    assert.ok(!germanText.includes(stale), `stale translated phone claim remains: ${stale}`);
  }
  for (const id of ["phone-pairing", "kde-sms", "phone-calls", "tree-delegation",
    "tree-contact-sync", "personal-sync", "personal-conflicts-attachments",
    "personal-deletions-trash", "platform-security-matrix"]) {
    assert.ok(english.H.seiten().some((page) => page.id === id), `missing page id: ${id}`);
  }
  assert.ok(english.H.blaettereZuId("kde-sms") &&
    english.H.seiten()[english.H.seiten().findIndex((page) => page.id === "kde-sms")].titel,
  "slug navigation failed");
  assert.ok(englishText.includes("sudo dnf install ./magnolie-organizer-2.0.10-1.noarch.rpm"));
  assert.ok(englishText.includes("rpmbuild --rebuild magnolie-organizer-2.0.10-1.src.rpm"));
  assert.ok(englishText.includes("sudo dnf upgrade ./magnolie-organizer-2.0.10-1.noarch.rpm"));
  assert.ok(englishText.includes("Only one <i>Magnolie Organizer</i> entry remains"));
  assert.ok(englishText.includes("Update manual …") &&
    englishText.includes("verifies SHA-256") && englishText.includes("never runs sudo or dpkg"));
  assert.ok(englishText.includes("LC_ALL=C magnolie-organizer"));
  for (const phrase of ["Druck und ODS", "Jahreskalender", "Monatskalender",
    "fünf Eintragsbalken", "Frühdienst", "Spätdienst", "Nachtschicht",
    "drei Blutungsstärken", "Urlaubsplaner", "Müllkalender", "Restmüll",
    "Grüner Punkt / Gelbe Tonne", "vierzehntäglich", "kein Tonnensymbol",
    "zunächst ausgeschaltet", "ohne Rückfrage oder Papierkorbkopie",
  ]) {
    assert.ok(germanText.includes(phrase), `German planner print paragraph missing: ${phrase}`);
  }
  const reminderIds = ["appointment-reminders", "getting-timely-anniversary-reminders",
    "reminders-with-password-protection"];
  assert.strictEqual(sourcePages.filter((page) => reminderIds.includes(page.id)).length, 3,
    "the reminder route must contain exactly three retained pages");
  assert.ok(!sourcePages.some((page) => ["individual-notifications",
    "appearance-sound-and-anniversaries"].includes(page.id)),
  "superseded reminder pages remain in the handbook");
  for (const phrase of ["All-day appointments are treated as starting at 8 a.m.",
    "there is no snooze function", "Browser-only use", "Windows do not schedule a wake-up",
    "up to 32 display reminders", "unsupported alarms stay visible as read-only",
    "Personal Sync preserves the custom lead time", "scheduled for 8 a.m.",
    "anniversary type and scheduler settings", "does not contain contacts"])
    assert.ok(englishText.includes(phrase), `English reminder documentation missing: ${phrase}`);
  for (const phrase of ["Ganztägige Termine gelten als Beginn um 8 Uhr",
    "eine Schlummerfunktion gibt es nicht", "reine Browserfassung", "keinen Weckruf",
    "bis zu 32 Bildschirmmeldungen", "Personal Sync bewahrt den individuellen Vorlauf",
    "für 8 Uhr geplant", "einschließlich Jahrestagsart", "keine Adressen"])
    assert.ok(germanText.includes(phrase), `German reminder documentation missing: ${phrase}`);
  const recoveryIds = ["the-recycle-bin", "backing-up-and-restoring",
    "wiederherstellungspunkte-was"];
  assert.strictEqual(sourcePages.filter((page) => recoveryIds.includes(page.id)).length, 3,
    "the recycle-bin and recovery route must contain exactly three retained pages");
  assert.ok(!sourcePages.some((page) => ["external-backups",
    "wiederherstellungspunkt-erstellen", "wiederherstellungspunkt-zurueckholen"].includes(page.id)),
  "superseded backup or recovery-snapshot pages remain in the handbook");
  for (const phrase of ["not by a continuously running countdown", "at most 3,000 entries",
    "Settings ▸ Security ▸ Backups", "Windows writes a password-encrypted",
    "The preview does not list individual names", "checks again every 15 minutes",
    "re-encrypted when that password is changed", "up to eight weekly points"])
    assert.ok(englishText.includes(phrase), `English recovery documentation missing: ${phrase}`);
  for (const phrase of ["nicht durch einen ständig laufenden Countdown", "höchstens 3.000 Einträge",
    "Einstellungen ▸ Sicherheit ▸ Sicherungen", "Windows schreibt bei jedem ausdrücklich",
    "Einzelne Namen oder Einträge", "alle 15 Minuten", "neu verschlüsselt",
    "bis zu acht Wochenpunkte"])
    assert.ok(germanText.includes(phrase), `German recovery documentation missing: ${phrase}`);
  const holidayIds = ["country-region-holiday-display", "fetching-public-and-school-holidays"];
  assert.strictEqual(sourcePages.filter((page) => holidayIds.includes(page.id)).length, 2,
    "the country, region, and holiday route must contain exactly two pages");
  for (const phrase of ["The Organizer never guesses one", "All cantons",
    "replaces only entries whose date range touches one of the requested years",
    "At most three years and 26 regions", "Your appointments, contacts, notes"])
    assert.ok(englishText.includes(phrase), `English holiday documentation missing: ${phrase}`);
  for (const phrase of ["niemals ein Bundesland oder einen Kanton", "Alle Kantone",
    "nur Einträge, deren Zeitraum eines der angefragten Jahre berührt",
    "höchstens drei Jahre und 26 Regionen", "Termine, Kontakte, Notizen"])
    assert.ok(germanText.includes(phrase), `German holiday documentation missing: ${phrase}`);
  const regionalIds = ["settings-language-format-region", "settings-time-week-region"];
  assert.strictEqual(sourcePages.filter((page) => regionalIds.includes(page.id)).length, 2,
    "the language and regional display route must contain exactly two pages");
  for (const phrase of ["automatically follows the language and format region",
    "no Language &amp; region tab", "magnolie-organizer --language CODE",
    "Regional display is automatic", "Other regional conventions continue to follow the system"])
    assert.ok(englishText.includes(phrase), `English regional documentation missing: ${phrase}`);
  for (const phrase of ["folgt automatisch der Sprache und Formatregion", "keinen Reiter Sprache &amp; Region",
    "magnolie-organizer --language CODE", "Regionale Darstellung erfolgt automatisch",
    "Andere regionale Konventionen folgen weiterhin dem System"])
    assert.ok(germanText.includes(phrase), `German regional documentation missing: ${phrase}`);
  const androidNotesIds = ["android-notes-navigation", "android-notes-notebooks",
    "android-notes-edit-save-delete", "android-tasks-reminders", "android-note-symbols-formatting"];
  assert.strictEqual(sourcePages.filter((page) => androidNotesIds.includes(page.id)).length, 5,
    "the Magnolie Notes route must contain exactly five pages");
  for (const phrase of ["five tabs along the bottom", "Loose Notes", "system Back action does not save",
    "zero through fourteen", "no bold, italic, underline, list, heading, Markdown or rich-text toolbar"])
    assert.ok(englishText.includes(phrase), `English Magnolie Notes documentation missing: ${phrase}`);
  for (const phrase of ["fünf Reitern am unteren Rand", "Lose Notizen", "System-Zurück-Aktion speichert nicht",
    "null bis vierzehn", "keine Werkzeugleiste für Fett, Kursiv, Unterstreichen, Listen, Überschriften, Markdown oder Rich Text"])
    assert.ok(germanText.includes(phrase), `German Magnolie Notes documentation missing: ${phrase}`);
  const androidImportIds = ["android-import-files-folders", "android-import-formats",
    "android-share-into-notes", "android-import-results-limits"];
  assert.strictEqual(sourcePages.filter((page) => androidImportIds.includes(page.id)).length, 4,
    "the Magnolie Notes import route must contain exactly four pages");
  for (const phrase of ["cannot simply look inside Samsung Notes", "Markdown-directory export",
    "single PDF", "normalized <b>title and text</b>", "5,000 entries"])
    assert.ok(englishText.includes(phrase), `English Android import documentation missing: ${phrase}`);
  for (const phrase of ["nicht einfach in Samsung Notes", "Markdown-Verzeichnisausgabe",
    "einzelne PDF", "normalisierten Verbindung von <b>Überschrift und Text</b>", "5.000 Einträge"])
    assert.ok(germanText.includes(phrase), `German Android import documentation missing: ${phrase}`);
  const androidTransferIds = ["android-tree-pairing", "android-tree-sharing-inbox",
    "android-phone-bluetooth", "android-personal-sync-controls",
    "android-personal-deletion-review", "android-recovery-journal"];
  assert.strictEqual(sourcePages.filter((page) => androidTransferIds.includes(page.id)).length, 6,
    "the Android transfer and recovery route must contain exactly six pages");
  for (const phrase of ["QR pairing requires confirmation", "Outbox: … waiting", "Bluetooth data fallback",
    "Automatic synchronization is <b>Wi-Fi only</b>", "only a proposal",
    "This is not an external backup"])
    assert.ok(englishText.includes(phrase), `English Android transfer documentation missing: ${phrase}`);
  for (const phrase of ["QR-Paarung erfordert", "Postfach: … wartend", "Bluetooth-Datenfallback",
    "Automatischer Abgleich erfolgt <b>nur über WLAN</b>", "nur ein Vorschlag",
    "keine externe Sicherung"])
    assert.ok(germanText.includes(phrase), `German Android transfer documentation missing: ${phrase}`);
  const technicalSecurityIds = ["technical-connection-map", "technical-ports-firewall",
    "technical-local-encryption", "technical-tree-security-routing",
    "technical-phone-transport-security"];
  assert.strictEqual(sourcePages.filter((page) => technicalSecurityIds.includes(page.id)).length, 5,
    "the ports, firewall, and encryption route must contain exactly five pages");
  for (const phrase of ["8737 TCP", "8741 TCP", "Without password protection",
    "HTTP framing rather than HTTPS", "rejected over RFCOMM"])
    assert.ok(englishText.includes(phrase), `English security technology documentation missing: ${phrase}`);
  for (const phrase of ["8737 TCP", "8741 TCP", "Ohne Kennwortschutz",
    "HTTP-Rahmung statt HTTPS", "über RFCOMM abgewiesen"])
    assert.ok(germanText.includes(phrase), `German security technology documentation missing: ${phrase}`);
  for (const phrase of ["notify you before an appointment begins", "Importing data from other programs",
    "Exporting data to other programs", "Checking for a new Organizer version", "on your computer",
    "sudo apt install hunspell-en-us", "B</span> <span class='knopfwort'>I",
    "Bold, italic, underline, and strikethrough"]) {
    assert.ok(englishText.includes(phrase), `English regression phrase missing: ${phrase}`);
  }
  for (const phrase of ["bevor ein Termin beginnt", "Daten aus anderen Programmen",
    "Daten an andere Programme geben", "auf Ihrem Rechner"]) {
    assert.ok(germanText.includes(phrase), `German regression phrase missing: ${phrase}`);
  }
  if (catalogCurrent) {
    assert.ok(germanText.includes("Update manual") ||
      germanText.includes("Handbuch aktualisieren"));
    assert.ok(germanText.includes("sudo apt install hunspell-de-de"));
  }
  english.dom.window.close();
  german.dom.window.close();
  const python = fs.readFileSync(path.join(ROOT, "bin", "magnolie-handbuch"), "utf8");
  assert.ok(python.includes("gettext.translation") && python.includes("/usr/share/locale"));
  assert.ok(python.includes("window.MAGNOLIE_LOCALE") && python.includes("get_is_remote"));
  assert.ok(python.includes('PROGRAMM_FASSUNG = "2.0.10"') && python.includes('"--version"'));
  const changelog = fs.readFileSync(path.join(ROOT, "debian", "changelog"), "utf8");
  const pot = fs.readFileSync(path.join(ROOT, "po", "magnolie-handbuch.pot"), "utf8");
  assert.ok(changelog.startsWith("magnolie-handbuch (2.0.10)"));
  assert.ok(pot.includes('"Project-Id-Version: Magnolie Handbook 2.0.10'));
  assert.ok(!sources.i18n.includes("pageReferenceUpdates") &&
    !sources.content.includes("data-seite="), "brittle page-number migration remains");
  const pageCount = english.H.seiten().length;
  const catalogStatus = catalogCurrent ? "current German catalog" : "German catalog update pending";
  console.log(`ALL HANDBOOK CHECKS PASSED (${pageCount} English + ${pageCount} German pages; ${catalogStatus})`);
} finally {
  fs.rmSync(temporary, { recursive: true, force: true });
}
