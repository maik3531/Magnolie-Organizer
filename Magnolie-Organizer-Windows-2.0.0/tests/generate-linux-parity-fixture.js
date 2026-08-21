#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { generate } = require("./linux-parity-fixture");

const linuxRoot = path.resolve(process.argv[2] || "");
if (!process.argv[2] || !fs.statSync(linuxRoot, { throwIfNoEntry: false })?.isDirectory()) {
  throw new Error("Aufruf: generate-linux-parity-fixture.js <Linux-Quellbaum> [Zieldatei]");
}
const output = `${JSON.stringify(generate(linuxRoot), null, 2)}\n`;
if (process.argv[3]) fs.writeFileSync(path.resolve(process.argv[3]), output, "utf8");
else process.stdout.write(output);
