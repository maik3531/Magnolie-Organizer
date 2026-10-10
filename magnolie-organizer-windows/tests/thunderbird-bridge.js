"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { JSDOM } = require("jsdom");

async function main() {
  const dom = new JSDOM("");
  const requests = [];
  const calendarFixtures = [];
  let calendarStatus = 207;
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
    "calUtils.sys.mjs": { cal: { manager: { getCalendars: () => calendarFixtures } } },
    "CalDavRequest.sys.mjs": { CalDavGenericRequest: class {
      constructor(session, calendar, method, uri, headers, body, contentType) {
        assert.equal(session, calendar.session);
        this.request = { url: uri.spec, method, headers, body, contentType };
      }
      async commit() {
        requests.push(this.request);
        return { status: calendarStatus, text: "synthetic provider response", getHeader: () => '"calendar-v1"' };
      }
    } }
  };
  const context = vm.createContext({ URL, TextEncoder, Services: { io: { newURI: spec => ({ spec }) }, prefs: { getStringPref: () => "profile-one", getBoolPref: () => false } },
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
  const calendarBase = "https://dav.example/calendar/";
  const calendarFixture = { id: "calendar", type: "caldav", name: "Synthetic calendar", readOnly: false,
    uri: { spec: calendarBase }, disabled: false, wrappedJSObject: { session: {} },
    getProperty(key) { return key === "disabled" ? this.disabled : true; } };
  calendarFixtures.push(calendarFixture);
  const calendarSource = (await api.request({ version: 1, id, op: "sources" })).sources.find(item => item.kind === "calendar");
  assert.equal(calendarSource.uid, "thunderbird-calendar:profile-one:calendar");
  const calendarRequest = { version: 1, id, op: "http", source: calendarSource.uid,
    method: "REPORT", url: calendarBase, headers: { Depth: "1" }, body: "<calendar-query/>" };
  assert.equal((await api.request(calendarRequest)).body, "synthetic provider response");
  calendarStatus = 204;
  const deletion = { ...calendarRequest, method: "DELETE", url: calendarBase + "duplicate.ics", body: "", headers: { "If-Match": '"calendar-v1"' } };
  assert.equal((await api.request(deletion)).status, 204);
  assert.equal(requests.at(-1).headers["If-Match"], '"calendar-v1"');
  const calendarCalls = requests.length;
  for (const invalid of [{ source: "thunderbird-calendar:other-profile:calendar" },
    { url: "https://dav.example/other/duplicate.ics" }, { url: calendarBase }, { headers: {} }])
    await assert.rejects(api.request({ ...deletion, ...invalid }));
  calendarFixture.disabled = true;
  await assert.rejects(api.request(deletion), /missing-source/);
  calendarFixture.disabled = false;
  calendarFixture.readOnly = true;
  await assert.rejects(api.request(deletion), /missing-source/);
  calendarFixture.readOnly = false;
  assert.equal(requests.length, calendarCalls);
  calendarStatus = 412;
  assert.equal((await api.request(deletion)).status, 412, "revision conflict must reach the organizer unchanged");
  calendarStatus = 503;
  assert.equal((await api.request(calendarRequest)).status, 503, "failed REPORT is not an empty calendar");
  const prefs=new Map();
  const makeBook=email=>({dirType:102,URI:email,
    getStringValue:key=>key==="carddav.username"?email:"https://www.googleapis.com/carddav/v1/principals/"+email});
  const makeCalendar=email=>({type:"caldav",uri:{spec:"https://apidata.googleusercontent.com/caldav/v2/"+email},
    disabled:false,getProperty(key){return key==="disabled"?this.disabled:email;}});
  const books=[makeBook("one@example.invalid"),makeBook("two@example.invalid")];
  const calendars=[makeCalendar("one@example.invalid"),makeCalendar("two@example.invalid"),makeCalendar("calendar-only@example.invalid")];
  const ab=modules["MailServices.sys.mjs"].MailServices.ab;
  ab.directories=books;ab.deleteAddressBook=uri=>books.splice(books.findIndex(b=>b.URI===uri),1);
  const manager=modules["calUtils.sys.mjs"].cal.manager;
  manager.getCalendars=()=>calendars;
  manager.unregisterCalendar=calendar=>calendars.splice(calendars.indexOf(calendar),1);
  context.Services.prefs={getBoolPref:()=>true,getStringPref:(key,fallback)=>prefs.get(key)||fallback,
    setStringPref:(key,value)=>prefs.set(key,value),clearUserPref:key=>prefs.delete(key),savePrefFile(){}};
  const manage={version:1,id,op:"manage-account",provider:"google",accountId:"one@example.invalid"};
  await api.request({...manage,action:"rename",name:"Renamed Google"});
  const renamed=await api.request({version:1,id,op:"status"});
  assert.equal(renamed.google.details.find(a=>a.id===manage.accountId).name,"Renamed Google");
  assert.ok(renamed.google.accounts.includes("calendar-only@example.invalid"),"calendar-only account must survive restart discovery");
  assert.ok(renamed.google.details.every(account=>account.enabled===true));
  assert.equal(renamed.google.tasks.available,false,"Google Tasks is not the CalDAV calendar bridge");
  calendars[2].disabled=true;
  const disabled=await api.request({version:1,id,op:"status"});
  assert.equal(disabled.google.details.find(account=>account.id==="calendar-only@example.invalid").enabled,false);
  calendars[2].disabled=false;
  await assert.rejects(api.request({...manage,accountId:"missing",action:"remove"}));
  await api.request({...manage,action:"remove"});
  assert.equal(books.length,1);assert.equal(books[0].URI,"two@example.invalid");
  assert.equal(calendars.length,2);assert.ok(!calendars.some(c=>c.getProperty()===manage.accountId));
  assert.ok(!(await api.request({version:1,id,op:"status"})).google.accounts.includes(manage.accountId));
  dom.window.close();
  console.log("Thunderbird bridge: source binding, complete snapshots, multiget, conditional writes and credential isolation passed.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
