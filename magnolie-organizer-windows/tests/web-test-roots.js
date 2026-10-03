"use strict";
const fs = require("node:fs"), path = require("node:path");
const primary = process.env.MAGNOLIE_WEB || path.resolve(__dirname, "../app/web");
if (!fs.existsSync(path.join(primary, "index.html"))) throw new Error("The frontend under test is missing: " + primary);
const linux = path.resolve(__dirname, "../../magnolie-organizer/web");
module.exports = process.env.MAGNOLIE_WEB ? [primary] :
  [primary, ...(fs.existsSync(path.join(linux, "index.html")) ? [linux] : [])];
