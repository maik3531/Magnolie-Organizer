"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const sha256 = (value) => crypto.createHash("sha256").update(value).digest("hex");
const values = (source, expression) => [...new Set(Array.from(source.matchAll(expression), match => match[1]))].sort();
const commands = source => values(source, /cmd:\s*"([a-z0-9_]+)"/g);
const PLATFORM_ONLY_COMMANDS = new Set([
  "background_settings_get", "background_settings_set", "baum_paarungsqr_erzeugen",
  "debug_startphase", "kde_empfangsordner_waehlen", "kde_receive_decide",
  "kde_receive_settings", "kde_receive_ziel_waehlen", "telefon_anruf_bluetooth"
]);
const PLATFORM_ONLY_CALLBACKS = new Set([
  "baumGefunden", "baumPaarung", "baumPartnerEinstellungen", "baumStand",
  "kdeEmpfangFehler", "kdeEmpfangFertig", "kdeEmpfangsordnerGewaehlt",
  "personalSyncAttachmentIndex", "personalSyncDecisionAccepted", "personalSyncFortschritt",
  "telefonAntwort", "telefonEingehenderAnruf", "telefonMeldung",
  // Linux reports journal readback explicitly; Windows reports commit errors through syncFehler.
  "syncBestaetigt"
]);

function scanJavaScript(source, start, stopAtClosingBrace) {
  const parts = [];
  let partStart = start;
  let braces = 0, brackets = 0, parentheses = 0;
  let quote = "", escaped = false, lineComment = false, blockComment = false;
  for (let index = start; index < source.length; index += 1) {
    const character = source[index], next = source[index + 1];
    if (lineComment) { if (character === "\n") lineComment = false; continue; }
    if (blockComment) { if (character === "*" && next === "/") { blockComment = false; index += 1; } continue; }
    if (quote) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === quote) quote = "";
      continue;
    }
    if (character === "/" && next === "/") { lineComment = true; index += 1; continue; }
    if (character === "/" && next === "*") { blockComment = true; index += 1; continue; }
    if (character === "\"" || character === "'" || character === "`") { quote = character; continue; }
    if (character === "{") braces += 1;
    else if (character === "}") {
      if (stopAtClosingBrace && braces === 0 && brackets === 0 && parentheses === 0) {
        parts.push(source.slice(partStart, index));
        return parts;
      }
      braces -= 1;
    } else if (character === "[") brackets += 1;
    else if (character === "]") brackets -= 1;
    else if (character === "(") parentheses += 1;
    else if (character === ")") parentheses -= 1;
    else if (character === "," && braces === 0 && brackets === 0 && parentheses === 0) {
      parts.push(source.slice(partStart, index));
      partStart = index + 1;
    }
  }
  throw new Error("Unvollstaendiges Bruecke.sende-Objekt");
}

function sendObjects(source) {
  const objects = [];
  for (const match of source.matchAll(/Bruecke\.sende\s*\(\s*\{/g)) {
    const properties = new Map();
    for (const part of scanJavaScript(source, match.index + match[0].length, true)) {
      const property = /^\s*(?:([A-Za-z_$][\w$]*)|"([^"]+)"|'([^']+)')\s*:\s*([\s\S]*)$/.exec(part);
      const shorthand = /^\s*([A-Za-z_$][\w$]*)\s*$/.exec(part);
      if (shorthand) {
        if (properties.has(shorthand[1])) throw new Error("Doppelte Bruecke.sende-Eigenschaft: " + shorthand[1]);
        properties.set(shorthand[1], shorthand[1]);
        continue;
      }
      if (!property) throw new Error(`Bruecke.sende-Eigenschaft kann nicht gelesen werden: ${part.trim().slice(0, 80)}`);
      if (properties.has(property[1] || property[2] || property[3])) throw new Error("Doppelte Bruecke.sende-Eigenschaft");
      properties.set(property[1] || property[2] || property[3], property[4].trim());
    }
    objects.push(properties);
  }
  return objects;
}

const literal = value => {
  const match = /^(?:"([^"]*)"|'([^']*)')$/.exec(value || "");
  return match && (match[1] ?? match[2]);
};
const payloadShape = object => [...object.entries()].map(([key, value]) => [key, value.replace(/\s+/g, " ")]);
const personalSyncPayloads = source => sendObjects(source)
  .filter(object => ["personal_sync_senden", "personal_sync_lauf_senden"].includes(literal(object.get("cmd"))))
  .map(payloadShape);

function canonicalContract(fixture) {
  return JSON.stringify({
    schema: fixture.schema,
    commands: fixture.commands,
    callbacks: fixture.callbacks,
    payloadSchemas: fixture.payloadSchemas,
    personalSyncPayloads: fixture.personalSyncPayloads
  });
}

function generate(linuxRoot) {
  const ui = fs.readFileSync(path.join(linuxRoot, "web", "anwendung.js"), "utf8");
  const dispatcher = fs.readFileSync(path.join(linuxRoot, "bin", "magnolie-organizer"), "utf8");
  const windowsRoot = path.resolve(__dirname, "..");
  const windowsUi = fs.readFileSync(path.join(windowsRoot, "app", "web", "anwendung.js"), "utf8");
  require("node:assert/strict").deepEqual(personalSyncPayloads(windowsUi), personalSyncPayloads(ui),
    "Verify actual Linux/Windows personal sync payload parity before generating the fixture");
  const dispatchedCommands = new Set(values(dispatcher, /befehl\s*==\s*"([a-z0-9_]+)"/g));
  for (const match of dispatcher.matchAll(/befehl\s+in\s+\(([^)]*)\)/g)) {
    for (const command of values(match[1], /"([a-z0-9_]+)"/g)) dispatchedCommands.add(command);
  }
  const callbackHandlers = new Set(values(ui, /\n    ([A-Za-z0-9_]+)\([^)]*\)\s*\{/g));
  const fixture = {
    schema: "magnolie-linux-parity-v1",
    sources: {
      "web/anwendung.js": sha256(ui),
      "bin/magnolie-organizer": sha256(dispatcher)
    },
    commands: commands(ui).filter(command => dispatchedCommands.has(command) && !PLATFORM_ONLY_COMMANDS.has(command)),
    callbacks: values(dispatcher, /self\.antwort\("App\.([A-Za-z0-9_]+)"/g)
      .filter(callback => callbackHandlers.has(callback) && !PLATFORM_ONLY_CALLBACKS.has(callback)),
    payloadSchemas: {
      personal_sync_senden: ["cmd", "kennung", "art", "inhalt"],
      personal_sync_lauf_senden: ["cmd", "kennung", "request", "batches", "sources", "report", "commit"]
    },
    personalSyncPayloads: personalSyncPayloads(ui)
  };
  fixture.contractSha256 = sha256(canonicalContract(fixture));
  return fixture;
}

module.exports = { canonicalContract, generate, personalSyncPayloads, sendObjects, sha256 };
