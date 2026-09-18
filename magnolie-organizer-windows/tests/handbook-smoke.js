"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { JSDOM } = require("jsdom");
const { canonicalPageIds, selectHandbookWeb } = require("./handbook-source");

const root = path.resolve(__dirname, "..");
const expectedVersion = process.argv[2];
const expectedInstaller = process.argv[3];
assert.ok(/^\d+\.\d+\.\d+$/.test(expectedVersion || ""), "Kanonische Testversion fehlt");
assert.strictEqual(expectedInstaller,
  `Magnolie-Organizer-Windows-${expectedVersion}-Setup-x64.exe`,
  "Unerlaubter Test-Installername");
const handbookSource = selectHandbookWeb(root, ["index.html", "inhalt.js", "mobile-downloads.js", "i18n/de.js"]);
const selectedHandbook = handbookSource.directory;
const handbook = [process.env.MAGNOLIE_HANDBUCH_WEB,
  path.resolve(root, "..", "magnolie-handbuch", "web"),
  path.join(root, "shared", "magnolie-handbuch", "web")]
  .filter(Boolean).find((candidate) => fs.existsSync(path.join(candidate, "inhalt.js")) &&
    fs.existsSync(path.join(candidate, "i18n", "de.js")));
assert.ok(handbook, "Gemeinsame Handbuchquelle fehlt");
assert.strictEqual(path.resolve(handbook), selectedHandbook,
  "Veraltete Handbuch-Ausweichquelle wurde ausgewählt");
const expectedPageIds = canonicalPageIds(selectedHandbook);
const html = fs.readFileSync(path.join(selectedHandbook, "index.html"), "utf8");
const content = fs.readFileSync(path.join(handbook, "inhalt.js"), "utf8");
const runtime = fs.readFileSync(path.join(handbook, "handbuch.js"), "utf8");
const i18n = fs.readFileSync(path.join(handbook, "i18n.js"), "utf8");
const deCatalog = fs.readFileSync(path.join(handbook, "i18n", "de.js"), "utf8");
const localeStart = fs.readFileSync(path.join(handbook, "i18n-start.js"), "utf8");
const mobileDownloads = fs.readFileSync(path.join(handbook, "mobile-downloads.js"), "utf8");
const style = fs.readFileSync(path.join(handbook, "stil.css"), "utf8");
const fontDigest = (name) => require("node:crypto").createHash("sha256")
  .update(fs.readFileSync(path.join(handbook, "schriften", name))).digest("hex");
assert.match(style, /--serif:\s*"Noto Serif",\s*serif;/,
  "Windows handbook does not use the bundled Linux serif font");
assert.match(style, /--sans:\s*"DejaVu Sans"/,
  "Windows handbook does not use the bundled Linux sans-serif font");
assert.strictEqual(fontDigest("DejaVuSans.ttf"),
  "ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280");
assert.strictEqual(fontDigest("DejaVuSans-Oblique.ttf"),
  "2d7b524ce7d51db78591b4e19c8185b89f3af0aa6534c5e524cf0c6f4ea673de");
assert.strictEqual(fontDigest("NotoSerif-Regular.ttf"),
  "9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f");
assert.strictEqual(fontDigest("NotoSerif-Italic.ttf"),
  "bc25600aa27cd409e1e5b3d86340df3a329bb860fcfbe57a03a95070b229e1b0");

const dom = new JSDOM(html, {
  url: "https://handbuch.magnolie.test/",
  pretendToBeVisual: true,
  runScripts: "outside-only"
});
const window = dom.window;
const bridgeMessages = [];
window.webkit = { messageHandlers: { bruecke: { postMessage(message) { bridgeMessages.push(JSON.parse(message)); } } } };
window.eval(i18n);
window.eval(deCatalog);
window.__MAGNOLIE_SPRACHE__ = "de";
window.eval(localeStart);
window.eval(mobileDownloads);
window.eval(content);
window.eval(runtime);
if (!window.Handbuch) window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

const pages = window.Handbuch.seiten();
const completeText = pages.map((page) => `${page.titel} ${page.inhalt}`).join("\n");
assert.strictEqual(window.document.documentElement.lang, "de");
assert.strictEqual(window.document.title, "Magnolie Organizer – Handbuch");
assert.deepStrictEqual(pages.map((page) => page.id), expectedPageIds,
  "Windows-Handbuchseiten entsprechen nicht der ausgewählten kanonischen Quelle");
assert.ok(pages.every((page) => page.titel && page.inhalt !== undefined));
assert.ok(pages.some((page) => page.id === "the-appimage"), "Die AppImage-Seite fehlt");
const apkPage = pages.find((page) => page.id === "android-apk-transfer");
assert.ok(apkPage.inhalt.includes("Magnolie-Notes.apk") &&
  apkPage.inhalt.includes("Magnolie-Notes-latest-PRUEFSUMMEN.sha256") &&
  !apkPage.inhalt.includes("Magnolie-Notes-1.0.13.apk") &&
  apkPage.inhalt.includes("play.google.com/store/apps/details?id=org.kde.kdeconnect_tp") &&
  (apkPage.inhalt.match(/class='download-qr'/g) || []).length === 2,
"APK-Handbuchseite enthält nicht beide aktuellen QR-Downloads");
assert.ok(completeText.includes("%LOCALAPPDATA%\\Magnolie Organizer\\daten.json"));
assert.ok(completeText.includes("Dokumente\\Magnolie Organizer\\Sicherungen"));
assert.ok(completeText.includes(expectedInstaller));
assert.ok(completeText.includes("WebView2"));
assert.ok(completeText.includes("Einstellungen ▸ Über") &&
  completeText.includes("Jetzt prüfen") &&
  completeText.includes("SHA-256-Prüfsumme") && completeText.includes("Benutzerhandbuch"));
assert.ok(completeText.includes("No valid coffee allowance") &&
  !completeText.includes("No valid subscription") &&
  completeText.includes("uneingeschränkt nutzen") &&
  completeText.includes("kein regulärer Supportanspruch") &&
  completeText.includes("selbstverständlich geprüft und nicht ignoriert") &&
  completeText.includes("GPL einen Eigenbau ohne Branding erstellen"));
assert.ok(completeText.includes("genau einem angehefteten eigenen Telefon") &&
  completeText.includes("Einstellungen ▸ Magnolienbaum") &&
  completeText.includes("Magnolie Notes-Telefonverbindung einschalten") &&
  completeText.includes("Telefon über WLAN verbinden") &&
  completeText.includes("unter Windows die Sicherheitsabfrage") &&
  completeText.includes("sechsstelligen Code") &&
  completeText.includes("Codes stimmen nicht überein") &&
  completeText.includes("Codes stimmen überein") &&
  completeText.includes("Bluetooth als Ausweichweg") &&
  completeText.includes("Einstellungen ▸ Bluetooth und Geräte") &&
  completeText.includes("kein HFP-Ton") && completeText.includes("keine SMS") &&
  completeText.includes("os_restricted"));
assert.ok(completeText.includes("Kontaktfotos") && completeText.includes("PDF-Anhänge") &&
  completeText.includes("Contacts.ReadWrite") && completeText.includes("Windows-DPAPI"));
assert.ok(pages.some((page) => page.id === "support-with-a-coffee") &&
  pages.some((page) => page.id === "about-maik-walter"));
for (const id of ["kde-sms", "phone-calls", "tree-delegation", "tree-contact-sync",
  "personal-sync", "personal-conflicts-attachments", "personal-deletions-trash",
  "country-region-holiday-display", "fetching-public-and-school-holidays",
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
  "glossary-a-m", "glossary-n-z"]) {
  assert.ok(pages.some((page) => page.id === id), `Gemeinsame Handbuchseite fehlt: ${id}`);
}
assert.ok(completeText.includes("--erinnerung") && completeText.includes("--wecker") &&
  completeText.includes("--probe") && completeText.includes("debug.log.2") &&
  completeText.includes("kde-connect-debug.log") && completeText.includes("MAGNOLIE_ORGANIZER_WEB") &&
  completeText.includes("Build- und Testvariablen sind keine Laufzeiteinstellungen"),
"Die Strecke-15-Fachphrasen zu CLI, Protokollen und Umgebung fehlen");
assert.ok(completeText.includes("200:1") && completeText.includes("keine Speicherobergrenze") &&
  completeText.includes("525.600 Minuten") && completeText.includes("einmal pro Minute") &&
  completeText.includes("Ed25519") && completeText.includes("Unmittelbar vor der Übergabe an Windows") && completeText.includes("128 MiB") &&
  completeText.includes("512 MiB") && completeText.includes("format=j1") &&
  completeText.includes("keine entsprechende Begrenzung der Antwortgröße"),
"Die Strecke-16-Fachphrasen fehlen");
assert.ok(completeText.includes("Aktuelles SMS-Verhalten") &&
  completeText.includes("SMS-Aktion zuweisen") &&
  completeText.includes("TelecomManager.placeCall") &&
  completeText.includes("Status eingehender Anrufe freigeben") &&
  completeText.includes("Anrufernummer freigeben, wenn verfügbar") &&
  completeText.includes("Annehmen vom Computer erlauben") &&
  completeText.includes("nur unter Linux verfügbar") &&
  completeText.includes("nur eine <b>sms:</b>-Adresse") &&
  completeText.includes("auf dem gekoppelten Telefon ungelesen") &&
  completeText.includes("RCS ist separat") && completeText.includes("5.000 Zeichen"),
"Die Strecke-17-Fachphrasen fehlen");
assert.ok(completeText.includes("Glossar: A–M") && completeText.includes("Glossar: N–Z") &&
  completeText.includes("kurzfristige, integritätsgeprüfte Kopie") &&
  completeText.includes("verwendet zum Lesen und Senden von SMS KDE Connect statt Magnolie Notes oder Personal Sync"),
"Die Strecke-18-Glossare oder ihre deutschen Fachdefinitionen fehlen");
assert.ok(completeText.includes("folgt automatisch der Sprache und Formatregion") &&
  completeText.includes("keinen Reiter Sprache &amp; Region") &&
  completeText.includes("magnolie-organizer --language CODE") &&
  completeText.includes("Andere regionale Konventionen folgen weiterhin dem System"),
"Die gemeinsame Regionaldokumentation ist unter Windows unvollständig");
for (const image of ["kaffee-qr.mga", "maik-walter.mga", "01.jpg", "02.jpg", "03.jpg",
  "02-woche.png", "03-aufgaben.png", "06-jahrestage.png", "10-pin-abfrage.png",
  "11-stand.png", "14-karteikarte.png", "15-rechtsklick-anrufen.png",
  "19-karte-mit-sms.png", "21-sms-getippt.png"]) {
  assert.ok(fs.existsSync(path.join(handbook, image)), `Handbuchbild fehlt: ${image}`);
}
assert.ok(!fs.existsSync(path.join(handbook, "kaffee-qr.png")) &&
  !fs.existsSync(path.join(handbook, "maik-walter.jpg")),
"Handbuch darf keine Klartext-Personenassets enthalten");
assert.ok(fs.existsSync(path.join(handbook, "maik-walter-FOTO-NUTZUNG.txt")));
for (const marker of [`Windows ${expectedVersion}`, "Magnolie Notes für Android 1.0.13",
  "Kontakte synchronisieren", "2.800.000", "stabile technische Bindung",
  "12.000.000", "24.000.000", "FileProvider", "256 MiB", "512 MiB",
  "Freiwilliger Löschabgleich", "höchstens 10 Löschungen", "höchstens 10 %",
  "unter 50 %", "Papierkorb", "Dubletten bleiben unter Ihrer Kontrolle"]) {
  assert.ok(completeText.includes(marker), `Windows-Handbuchmarker fehlt: ${marker}`);
}
assert.ok(!completeText.includes("Sending from Organizer to Android currently continues to use the network"));

window.Handbuch.oeffneBuch();
assert.ok(window.document.querySelector("#buch").classList.contains("offen"));
window.Handbuch.blaettereZu(pages.length - 1);
assert.ok(window.document.querySelector("#ecke-rechts").classList.contains("aus"));
assert.ok(window.Handbuch.druckFassung().includes("Magnolie Organizer · Handbuch"));
assert.strictEqual(window.Handbuch.drucken(), true);
assert.strictEqual(bridgeMessages.length, 1);
assert.strictEqual(bridgeMessages[0].cmd, "drucken");
assert.ok(bridgeMessages[0].html.includes("Magnolie Organizer · Handbuch"));

dom.window.close();
console.log(`HANDBOOK SMOKE TEST PASSED (${pages.length} shared pages; source: ${handbookSource.label})`);
