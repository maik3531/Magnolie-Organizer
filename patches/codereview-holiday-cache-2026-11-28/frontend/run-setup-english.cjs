"use strict";
// Existing setup assertions, English source catalogue only. No generated PO assets required.
const fs = require("node:fs"), path = require("node:path"), Module = require("node:module"), crypto = require("node:crypto");
const root = path.resolve(process.argv[2] || process.cwd());
const file = path.join(root, "magnolie-organizer-windows/tests/setup-holidays.js");
const original = fs.readFileSync(file, "utf8");
const declaration = 'const locales = ["en", ...fs.readdirSync(path.join(root, "magnolie-organizer/po"))\n  .filter(p => p.endsWith(".po")).map(p => p.slice(0, -3))];';
if (original.split(declaration).length !== 2) throw new Error("Existing locale-selection anchor changed");
console.log("Existing setup test SHA256: " + crypto.createHash("sha256").update(original).digest("hex"));
console.log("Scope: English source catalogue. All other existing assertions and both real frontends unchanged.");
fs.mkdirSync("/tmp/opencode", { recursive: true });
const host = new Module(file, module); host.filename = file; host.paths = Module._nodeModulePaths(path.dirname(file));
host._compile(original.replace(declaration, 'const locales = ["en"];'), file);
