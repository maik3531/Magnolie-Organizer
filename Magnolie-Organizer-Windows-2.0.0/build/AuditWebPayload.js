#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const fail = message => { throw new Error(`Web-Artefaktaudit: ${message}`); };
const file = value => fs.statSync(value, { throwIfNoEntry: false })?.isFile();
const same = (left, right) => file(left) && file(right) && fs.readFileSync(left).equals(fs.readFileSync(right));

function requiredPayload(root, publish) {
  const sourceWeb = path.join(root, "app", "web");
  const publishedWeb = path.join(publish, "web");
  const sourceApplication = path.join(sourceWeb, "anwendung.js");
  const publishedApplication = path.join(publishedWeb, "anwendung.js");
  if (!file(publishedApplication)) fail("Publizierte Weboberfläche fehlt: web/anwendung.js");
  if (!same(sourceApplication, publishedApplication)) fail("web/anwendung.js ist nicht bytegleich mit der Quelle");
  const application = fs.readFileSync(publishedApplication, "utf8");
  for (const marker of ["oeffneSuche", "nextcloud"]) {
    if (!application.includes(marker)) fail(`Pflichtmarker fehlt in web/anwendung.js: ${marker}`);
  }
  const languages = fs.readFileSync(path.join(root, "app", "po", "LINGUAS"), "utf8").trim().split(/\s+/);
  for (const language of languages) {
    const relative = path.join("i18n", `${language}.js`);
    if (!same(path.join(sourceWeb, relative), path.join(publishedWeb, relative))) {
      fail(`Webkatalog fehlt oder ist veraltet: web/${relative.replaceAll(path.sep, "/")}`);
    }
  }
  for (const relative of ["schriften/Z003-MediumItalic.otf", "schriften/Z003-LIZENZ.txt"]) {
    if (!same(path.join(sourceWeb, relative), path.join(publishedWeb, relative))) {
      fail(`Handschriftdatei fehlt oder ist veraltet: web/${relative}`);
    }
  }
  if (!same(path.join(root, "app", "native-i18n.json"), path.join(publish, "native-i18n.json"))) {
    fail("native-i18n.json fehlt oder ist veraltet");
  }
  for (const relative of ["index.html", "stil.css", "inhalt.js", "handbuch.js", "platform.js",
    "version.json", "i18n/de.js", "01.jpg", "02.jpg", "03.jpg", "02-woche.png",
    "03-aufgaben.png", "06-jahrestage.png", "10-pin-abfrage.png", "11-stand.png",
    "14-karteikarte.png", "15-rechtsklick-anrufen.png", "19-karte-mit-sms.png",
    "21-sms-getippt.png", "maik-walter-FOTO-NUTZUNG.txt",
    "schriften/DejaVuSans.ttf", "schriften/DejaVuSans-Bold.ttf",
    "schriften/DejaVuSans-Oblique.ttf", "schriften/DejaVuSans-BoldOblique.ttf",
    "schriften/NotoSerif-Regular.ttf", "schriften/NotoSerif-Bold.ttf",
    "schriften/NotoSerif-Italic.ttf", "schriften/NotoSerif-BoldItalic.ttf",
    "schriften/DejaVu-LIZENZ.txt", "schriften/Noto-LIZENZ.txt"]) {
    if (!file(path.join(publish, "handbuch", relative))) fail(`Handbuchdatei fehlt: handbuch/${relative}`);
  }
}

function walk(root) {
  return fs.readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const full = path.join(root, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

function artifactPayload(publish, artifact) {
  if (!fs.statSync(artifact, { throwIfNoEntry: false })?.isDirectory()) fail("extrahierter Artefaktbaum fehlt");
  for (const source of walk(publish).filter(item => path.extname(item).toLowerCase() !== ".pdb")) {
    const relative = path.relative(publish, source);
    const target = path.join(artifact, relative);
    if (!file(target)) fail(`Publishdatei fehlt im Artefakt: ${relative}`);
    if (!same(source, target)) fail(`Artefaktdatei ist nicht bytegleich: ${relative}`);
  }
}

if (require.main === module) {
  const [mode, first, second] = process.argv.slice(2);
  if (mode === "--publish" && first && second) requiredPayload(path.resolve(first), path.resolve(second));
  else if (mode === "--artifact" && first && second) artifactPayload(path.resolve(first), path.resolve(second));
  else fail("Aufruf: AuditWebPayload.js --publish <Quellwurzel> <Publishpfad> | --artifact <Publishpfad> <extrahierter Baum>");
  console.log(`Web-Artefaktaudit bestanden: ${path.resolve(second)}`);
}

module.exports = { artifactPayload, requiredPayload };
