"use strict";

const fs = require("node:fs");
const path = require("node:path");

const source = path.resolve(process.argv[2] || "");
const version = process.argv[3];
const installerName = process.argv[4];
const output = path.resolve(process.argv[5] || "");
const sourceWeb = fs.existsSync(path.join(source, "inhalt.js")) ? source : path.join(source, "web");

if (!/^\d+\.\d+\.\d+$/.test(version || "")) throw new Error("Kanonische Windows-Version fehlt.");
if (installerName !== `Magnolie-Organizer-Windows-${version}-Setup-x64.exe`) {
  throw new Error("Installername entspricht nicht der erlaubten Windows-Ausgabe.");
}
if (!fs.existsSync(path.join(sourceWeb, "index.html")) ||
    !fs.existsSync(path.join(sourceWeb, "platform.js"))) {
  throw new Error(`Gemeinsame Handbuchquelle fehlt: ${sourceWeb}`);
}
if (sourceWeb === output) throw new Error("Handbuchquelle und Buildziel müssen getrennt sein.");

fs.rmSync(output, { recursive: true, force: true });
fs.cpSync(sourceWeb, output, { recursive: true });
for (const name of ["inhalt.js", "platform.js"]) {
  const file = path.join(output, name);
  const content = fs.readFileSync(file, "utf8")
    .replace(/Magnolie-Organizer-Windows-\d+\.\d+\.\d+-Setup-x64\.exe/g, installerName)
    .replace(/Windows \d+\.\d+\.\d+/g, `Windows ${version}`);
  fs.writeFileSync(file, content, "utf8");
}
fs.writeFileSync(path.join(output, "version.json"), `${JSON.stringify({ version })}\n`, "utf8");
console.log(`Gemeinsames Handbuch für Windows erzeugt: ${output}`);
