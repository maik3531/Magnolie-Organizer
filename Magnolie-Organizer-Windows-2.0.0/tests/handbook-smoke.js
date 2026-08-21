"use strict";

const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const expectedVersion = process.argv[2];
const expectedInstaller = process.argv[3];
assert.ok(/^\d+\.\d+\.\d+$/.test(expectedVersion || ""), "Kanonische Testversion fehlt");
assert.strictEqual(expectedInstaller,
  `Magnolie-Organizer-Windows-${expectedVersion}-Setup-x64.exe`,
  "Unerlaubter Test-Installername");
const handbook = [process.env.MAGNOLIE_HANDBUCH_WEB,
  path.resolve(root, "..", "magnolie-handbuch-stamm", "web"),
  path.join(root, "shared", "magnolie-handbuch-stamm", "web")]
  .filter(Boolean).find((candidate) => fs.existsSync(path.join(candidate, "inhalt.js")));
assert.ok(handbook, "Gemeinsame Handbuchquelle fehlt");
const html = fs.readFileSync(path.join(handbook, "index.html"), "utf8");
const content = fs.readFileSync(path.join(handbook, "inhalt.js"), "utf8");
const runtime = fs.readFileSync(path.join(handbook, "handbuch.js"), "utf8");
const i18n = fs.readFileSync(path.join(handbook, "i18n.js"), "utf8");
const deCatalog = fs.readFileSync(path.join(handbook, "i18n", "de.js"), "utf8");
const localeStart = fs.readFileSync(path.join(handbook, "i18n-start.js"), "utf8");
const platform = fs.readFileSync(path.join(handbook, "platform.js"), "utf8");
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
window.__MAGNOLIE_PLATFORM__ = "windows";
window.eval(i18n);
window.eval(deCatalog);
window.__MAGNOLIE_SPRACHE__ = "de";
window.eval(localeStart);
window.eval(content);
window.eval(platform);
window.eval(runtime);
if (!window.Handbuch) window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

const pages = window.Handbuch.seiten();
const completeText = pages.map((page) => `${page.titel} ${page.inhalt}`).join("\n");
const platformPage = pages.find((page) =>
  page.inhalt.includes("Desktop-Anwendung für Linux und Windows"));
const protectedClosingIds = new Set(["license-and-acknowledgments", "in-closing",
  "support-with-a-coffee", "about-maik-walter"]);
const sharedPlatformFacts = new Set([
  "kde-sms", "personal-sync", "external-backups", "android-apk-transfer"
]);
const platformNeutralText = pages.filter((page) => page !== platformPage &&
  !protectedClosingIds.has(page.id) &&
  !sharedPlatformFacts.has(page.id) &&
  !(page.inhalt.includes("Magnolie-Gesamtarchiv") && page.inhalt.includes("Linux") &&
    page.inhalt.includes("Windows")) &&
  !(page.inhalt.includes("Magnolie Notes für Android 1.0.5") &&
    page.inhalt.includes("Linux 2.0.0") && page.inhalt.includes("Windows 2.0.0")))
  .map((page) => `${page.titel} ${page.inhalt}`).join("\n");
const blocked = /Linux|Debian|Ubuntu|Fedora|AppImage|WebKitGTK|GNOME|Wayland|X11|\bsystemd\b|\bUFW\b|BlueZ|sudo\s|\/usr\/|~\/\.local|\.deb\b|\.rpm\b/i;
const blockedPage = pages.find((page) => page !== platformPage &&
  !protectedClosingIds.has(page.id) &&
  !sharedPlatformFacts.has(page.id) &&
  !(page.inhalt.includes("Magnolie-Gesamtarchiv") && page.inhalt.includes("Linux") &&
    page.inhalt.includes("Windows")) &&
  !(page.inhalt.includes("Magnolie Notes für Android 1.0.5") &&
    page.inhalt.includes("Linux 2.0.0") && page.inhalt.includes("Windows 2.0.0")) &&
  blocked.test(`${page.titel} ${page.inhalt}`));

assert.strictEqual(window.document.documentElement.lang, "de");
assert.strictEqual(window.document.title, "Magnolie Organizer – Handbuch");
assert.strictEqual(pages.length, 118);
assert.ok(pages.every((page) => page.titel && page.inhalt !== undefined));
assert.ok(platformPage && platformPage.inhalt.includes("Magnolie Notes") &&
  platformPage.inhalt.includes("Android"), "Die Plattformübersicht fehlt");
assert.ok(!blocked.test(platformNeutralText),
  `Das Windows-Handbuch enthält Linux-spezifische Anweisungen auf ${blockedPage?.id}`);
assert.ok(completeText.includes("%LOCALAPPDATA%\\Magnolie Organizer\\daten.json"));
assert.ok(completeText.includes("Dokumente\\Magnolie Organizer\\Sicherungen"));
assert.ok(completeText.includes(expectedInstaller));
assert.ok(completeText.includes("Microsoft Edge WebView2 Runtime"));
assert.ok(completeText.includes("Organizer und Handbuch aktualisieren") &&
  completeText.includes("Jetzt prüfen") &&
  completeText.includes("SHA-256-Prüfsumme") && completeText.includes("Benutzerhandbuch"));
assert.ok(completeText.includes("No valid coffee allowance") &&
  !completeText.includes("No valid subscription") &&
  completeText.includes("uneingeschränkt nutzen") &&
  completeText.includes("kein regulärer Supportanspruch") &&
  completeText.includes("selbstverständlich geprüft und nicht ignoriert") &&
  completeText.includes("GPL einen Eigenbau ohne Branding erstellen"));
assert.ok(completeText.includes("genau einem Telefon") &&
  completeText.includes("Einstellungen ▸ Magnolienbaum") &&
  completeText.includes("Magnolie Notes-Telefonverbindung einschalten") &&
  completeText.includes("Telefon über WLAN verbinden") &&
  completeText.includes("Windows-Sicherheitsabfrage") &&
  completeText.includes("sechsstelligen Code") &&
  completeText.includes("Codes stimmen nicht überein") &&
  completeText.includes("Codes stimmen überein") &&
  completeText.includes("Bluetooth-Daten als Ausweichverbindung") &&
  completeText.includes("Einstellungen ▸ Bluetooth und Geräte") &&
  completeText.includes("keinen HFP-Ton") && completeText.includes("keine SMS") &&
  completeText.includes("os_restricted"));
assert.ok(completeText.includes("Kontaktfotos") && completeText.includes("PDF-Anhänge") &&
  completeText.includes("Contacts.ReadWrite") && completeText.includes("Windows-DPAPI"));
assert.ok(pages.some((page) => page.id === "support-with-a-coffee") &&
  pages.some((page) => page.id === "about-maik-walter"));
for (const id of ["kde-sms", "phone-calls", "tree-delegation", "tree-contact-sync",
  "personal-sync", "personal-conflicts-attachments", "personal-deletions-trash"]) {
  assert.ok(pages.some((page) => page.id === id), `Gemeinsame Handbuchseite fehlt: ${id}`);
}
for (const image of ["kaffee-qr.png", "maik-walter.jpg", "01.jpg", "02.jpg", "03.jpg",
  "02-woche.png", "03-aufgaben.png", "06-jahrestage.png", "10-pin-abfrage.png",
  "11-stand.png", "14-karteikarte.png", "15-rechtsklick-anrufen.png",
  "19-karte-mit-sms.png", "21-sms-getippt.png"]) {
  assert.ok(fs.existsSync(path.join(handbook, image)), `Handbuchbild fehlt: ${image}`);
}
assert.ok(fs.existsSync(path.join(handbook, "maik-walter-FOTO-NUTZUNG.txt")));
for (const marker of [`Windows ${expectedVersion}`, "Magnolie Notes für Android 1.0.5",
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
console.log(`HANDBOOK SMOKE TEST PASSED (${pages.length} Windows pages)`);
