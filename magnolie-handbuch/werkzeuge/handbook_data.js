"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function handbookData(web) {
  const i18n = { registerBook() {}, gettext: text => text, locale: () => "en" };
  const context = { window: { MagnolieI18n: i18n }, MagnolieI18n: i18n,
    document: { addEventListener() {} } };
  vm.createContext(context);
  for (const file of ["mobile-downloads.js", "inhalt.js", "platform.js"])
    vm.runInContext(fs.readFileSync(path.join(web, file), "utf8"), context, { filename: file });
  return JSON.parse(JSON.stringify({ pages: context.window.HANDBUCH_SEITEN,
    variants: context.window.HANDBUCH_WINDOWS_VARIANTEN }));
}

module.exports = { handbookData };
if (require.main === module)
  process.stdout.write(JSON.stringify(handbookData(process.argv[2] || path.resolve(__dirname, "../web"))));
