"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

async function main() {
  const dom = new JSDOM("");
  const requests = [];
  const base = "https://dav.example/book/";
  let incomplete = false;
  const response = text => ({ status: 207, text, dom: new dom.window.DOMParser().parseFromString(text, "text/xml") });
  const multi = inner => `<d:multistatus xmlns:d="DAV:" xmlns:a="urn:ietf:params:xml:ns:carddav">${inner}</d:multistatus>`;
  const row = (href, props) => `<d:response><d:href>${href}</d:href><d:propstat><d:prop>${props}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>`;
  const book = { _serverURL: base, async _makeRequest(url, details) {
    requests.push({ url, ...details });
    if (details.method === "PROPFIND") return response(multi(row(base + "a.vcf", '<d:resourcetype/><d:getetag>"v1"</d:getetag>')));
    if (details.method === "REPORT") return response(multi(incomplete ? "" : row(base + "a.vcf",
      '<d:getetag>"v1"</d:getetag><a:address-data>BEGIN:VCARD\nVERSION:3.0\nUID:a\nFN:Example\nEND:VCARD\n</a:address-data>')));
    return { status: details.method === "DELETE" ? 204 : 201, text: "" };
  } };
  const modules = {
    "XPCOMUtils.sys.mjs": { XPCOMUtils: { defineLazyGlobalGetters() {} } },
    "ExtensionCommon.sys.mjs": { ExtensionCommon: { ExtensionAPI: class {} } },
    "MailServices.sys.mjs": { MailServices: { ab: { directories: [{ dirType: 102, readOnly: false, fileName: "test.sqlite", UID: "book", dirName: "Test" }] } } },
    "CardDAVDirectory.sys.mjs": { CardDAVDirectory: { forFile: () => book } },
    "calUtils.sys.mjs": { cal: { manager: { getCalendars: () => [] } } },
    "CalDavRequest.sys.mjs": { CalDavGenericRequest: class {} }
  };
  const context = vm.createContext({ URL, TextEncoder, Services: { prefs: { getStringPref: () => "profile-one", getBoolPref: () => false } },
    Ci: { nsIAbManager: { CARDDAV_DIRECTORY_TYPE: 102 } }, ChromeUtils: {
      importESModule: uri => modules[uri.split("/").at(-1)], importGlobalProperties() {}
    } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app/thunderbird/api.js"), "utf8"), context);
  const api = new context.magnolie().getAPI().magnolie;
  const id = "a".repeat(32);
  const sources = (await api.request({ version: 1, id, op: "sources" })).sources;
  assert.equal(sources[0].uid, "thunderbird-addressbook:profile-one:book");
  assert.deepEqual(Object.keys(sources[0]).sort(), ["kind", "name", "tasks", "uid", "url"]);
  const request = { version: 1, id, op: "http", source: sources[0].uid, url: base, method: "REPORT", body: "", headers: {} };
  const result = await api.request(request);
  assert.equal(result.status, 207);
  assert.match(result.body, /BEGIN:VCARD/);
  assert.deepEqual(requests.map(item => item.method), ["PROPFIND", "REPORT"]);
  assert.match(requests[1].body, /addressbook-multiget/);
  assert.ok(requests.every(item => !item.headers.Authorization));
  incomplete = true;
  await assert.rejects(api.request(request), /incomplete/);
  incomplete = false;
  const count = requests.length;
  for (const invalid of [
    { url: "https://foreign.example/a.vcf" }, { url: "https://dav.example/other/a.vcf" },
    { url: "http://dav.example/book/a.vcf" }, { source: "thunderbird-addressbook:other-profile:book" },
    { method: "DELETE", url: base + "a.vcf" }, { method: "PUT", url: base + "a.vcf" },
    { method: "DELETE", headers: { "If-Match": '"v1"' } },
    { headers: { Authorization: "secret" } }, { headers: { Depth: "1\r\nInjected: x" } },
    { op: "read-token" }, { version: 2 }
  ]) await assert.rejects(api.request({ ...request, ...invalid }));
  assert.equal(requests.length, count, "invalid bridge input reached a provider");
  await api.request({ ...request, method: "DELETE", url: base + "a.vcf", headers: { "If-Match": '"v1"' } });
  assert.equal(requests.at(-1).headers["If-Match"], '"v1"');
  dom.window.close();
  console.log("Thunderbird bridge: source binding, complete snapshots, multiget, conditional writes and credential isolation passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
