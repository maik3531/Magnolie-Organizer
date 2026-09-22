/* GPL-3.0-or-later. Thunderbird performs all account authentication itself. */
"use strict";

var { ExtensionCommon } = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
var { XPCOMUtils } = ChromeUtils.importESModule("resource://gre/modules/XPCOMUtils.sys.mjs");
XPCOMUtils.defineLazyGlobalGetters(this, ["URL", "TextEncoder"]);
var { MailServices } = ChromeUtils.importESModule("resource:///modules/MailServices.sys.mjs");
var { CardDAVDirectory } = ChromeUtils.importESModule("resource:///modules/CardDAVDirectory.sys.mjs");
var { cal } = ChromeUtils.importESModule("resource:///modules/calendar/calUtils.sys.mjs");
var { CalDavGenericRequest } = ChromeUtils.importESModule("resource:///modules/caldav/CalDavRequest.sys.mjs");

const D = "DAV:", A = "urn:ietf:params:xml:ns:carddav";
const limit = 16 * 1024 * 1024;
function bounded(text) {
  if (typeof text !== "string" || new TextEncoder().encode(text).length > limit) throw new Error("size");
  return text;
}
function xmlEscape(text) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
function child(node, ns, name) {
  return Array.from(node.children).find(item => item.namespaceURI === ns && item.localName === name);
}
function scope(base, target) {
  const root = new URL(base), url = new URL(target, base);
  if (url.protocol !== "https:" || root.origin !== url.origin || url.username || url.password || url.search || url.hash ||
      (url.pathname.replace(/\/$/, "") !== root.pathname.replace(/\/$/, "") &&
       !url.pathname.startsWith(root.pathname.replace(/\/$/, "") + "/"))) throw new Error("scope");
  return url.href;
}
function properties(response) {
  const direct = child(response, D, "status");
  if (direct && !/^HTTP\/\S+ 2\d\d(?: |$)/.test(direct.textContent)) throw new Error("response-status");
  const props = [];
  for (const stat of Array.from(response.children).filter(item => item.namespaceURI === D && item.localName === "propstat")) {
    const status = child(stat, D, "status")?.textContent || "";
    if (!/^HTTP\/\S+ 2\d\d(?: |$)/.test(status)) throw new Error("property-status");
    const prop = child(stat, D, "prop");
    if (!prop) throw new Error("properties");
    props.push(...prop.children);
  }
  if (!props.length) throw new Error("properties");
  return props;
}
function multiStatus(response) {
  if (response.status !== 207) throw new Error("status");
  bounded(response.text);
  if (/<!DOCTYPE/i.test(response.text)) throw new Error("doctype");
  const document = response.dom;
  if (document?.documentElement?.namespaceURI !== D || document.documentElement.localName !== "multistatus") throw new Error("xml");
  return Array.from(document.documentElement.children).filter(item => item.namespaceURI === D && item.localName === "response");
}

function sources() {
  const pref = "extensions.magnolie.profileId";
  let profile = Services.prefs.getStringPref(pref, "");
  if (!profile) {
    profile = Services.uuid.generateUUID().toString().replace(/[{}]/g, "");
    Services.prefs.setStringPref(pref, profile);
    Services.prefs.savePrefFile(null);
  }
  const result = [];
  for (const directory of MailServices.ab.directories) {
    if (directory.dirType !== Ci.nsIAbManager.CARDDAV_DIRECTORY_TYPE || directory.readOnly) continue;
    const book = CardDAVDirectory.forFile(directory.fileName);
    if (!book || !book._serverURL?.startsWith("https://")) continue;
    result.push({ uid: `thunderbird-addressbook:${profile}:${directory.UID}`, kind: "addressbook",
      name: directory.dirName, url: book._serverURL, tasks: false, book });
  }
  for (const calendar of cal.manager.getCalendars()) {
    if (calendar.type !== "caldav" || calendar.readOnly || calendar.getProperty("disabled")) continue;
    const object = calendar.wrappedJSObject;
    const provider = object?.mUncachedCalendar?.wrappedJSObject || object;
    if (!provider?.session || !calendar.uri?.spec.startsWith("https://")) continue;
    result.push({ uid: `thunderbird-calendar:${profile}:${calendar.id}`, kind: "calendar",
      name: calendar.name, url: calendar.uri.spec, tasks: calendar.getProperty("capabilities.tasks.supported") !== false,
      calendar: provider });
  }
  return result;
}

async function cardMultiget(source, hrefs) {
  const result = [];
  // Keep individual DAV requests small; the native response is checked as a whole.
  for (let offset = 0; offset < hrefs.length; offset += 200) {
    const response = await source.book._makeRequest(source.url, {
      method: "REPORT", headers: { Depth: "1" }, contentType: "application/xml",
      body: `<a:addressbook-multiget xmlns:d="DAV:" xmlns:a="${A}"><d:prop><d:getetag/><a:address-data/></d:prop>` +
        hrefs.slice(offset, offset + 200).map(href => `<d:href>${xmlEscape(new URL(scope(source.url, href)).pathname)}</d:href>`).join("") +
        "</a:addressbook-multiget>"
    });
    const rows = multiStatus(response);
    if (rows.length !== Math.min(200, hrefs.length - offset)) throw new Error("incomplete");
    for (const row of rows) {
      const href = scope(source.url, child(row, D, "href")?.textContent || "");
      const props = properties(row);
      const etag = props.find(item => item.namespaceURI === D && item.localName === "getetag")?.textContent;
      const text = props.find(item => item.namespaceURI === A && item.localName === "address-data")?.textContent;
      if (!etag || !text) throw new Error("incomplete-card");
      result.push({ href, etag, text: text.replace(/\r?\n/g, "\r\n") });
    }
  }
  if (new Set(result.map(item => item.href)).size !== hrefs.length) throw new Error("duplicate-card");
  return result;
}

async function cardRequest(source, message, url, headers) {
  // Google supports multiget, but not the generic addressbook-query used by
  // many other servers. Enumerate complete resources, then fetch their cards.
  if (message.method === "REPORT") {
    const response = await source.book._makeRequest(source.url, { method: "PROPFIND",
      headers: { Depth: "1" }, contentType: "application/xml",
      body: '<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getetag/></d:prop></d:propfind>' });
    const hrefs = [];
    for (const row of multiStatus(response)) {
      const href = scope(source.url, child(row, D, "href")?.textContent || "");
      if (href.replace(/\/$/, "") === source.url.replace(/\/$/, "")) continue;
      const props = properties(row);
      if (!props.some(item => item.namespaceURI === D && item.localName === "getetag" && item.textContent)) throw new Error("etag");
      hrefs.push(href);
    }
    const cards = await cardMultiget(source, hrefs);
    return { status: 207, body: bounded(`<d:multistatus xmlns:d="DAV:" xmlns:a="${A}">` + cards.map(card =>
      `<d:response><d:href>${xmlEscape(card.href)}</d:href><d:propstat><d:prop><d:getetag>${xmlEscape(card.etag)}</d:getetag>` +
      `<a:address-data>${xmlEscape(card.text)}</a:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>`).join("") + "</d:multistatus>") };
  }
  if (message.method === "GET") {
    const [card] = await cardMultiget(source, [url]);
    return { status: 200, body: card.text, etag: card.etag, location: card.href };
  }
  const response = await source.book._makeRequest(url, { method: message.method, headers,
    body: message.method === "PUT" ? message.body : null, contentType: message.contentType });
  const result = { status: response.status, body: bounded(response.text || "") };
  if (message.method === "PUT" && response.status >= 200 && response.status < 300) {
    const [card] = await cardMultiget(source, [url]);
    result.etag = card.etag;
    result.body = card.text;
    result.location = card.href;
  }
  return result;
}

var magnolie = class extends ExtensionCommon.ExtensionAPI {
  getAPI() {
    return { magnolie: { request: async message => {
      if (message.version !== 1 || !/^[a-f0-9]{32}$/.test(message.id || "")) throw new Error("protocol");
      const available = sources();
      if (message.op === "sources") return { sources: available.map(({ book, calendar, ...publicFields }) => publicFields) };
      if (message.op !== "http") throw new Error("operation");
      const source = available.find(item => item.uid === message.source);
      if (!source) throw new Error("missing-source");
      const url = scope(source.url, message.url);
      if (!["GET", "PUT", "DELETE", "REPORT"].includes(message.method)) throw new Error("method");
      bounded(message.body || "");
      const headers = {};
      for (const [key, value] of Object.entries(message.headers || {})) {
        if (!["Depth", "If-Match", "If-None-Match"].includes(key) || typeof value !== "string" || /[\r\n]/.test(value)) throw new Error("header");
        headers[key] = value;
      }
      if (message.method === "DELETE" || message.method === "PUT") {
        if (url.replace(/\/$/, "") === source.url.replace(/\/$/, "")) throw new Error("collection-write");
        if (!headers["If-Match"] && !(message.method === "PUT" && headers["If-None-Match"] === "*")) throw new Error("unconditional-write");
      }
      if (source.kind === "addressbook") return cardRequest(source, message, url, headers);
      const request = new CalDavGenericRequest(source.calendar.session, source.calendar, message.method,
        Services.io.newURI(url), headers, message.body || null, message.contentType);
      const response = await request.commit();
      return { status: response.status, body: bounded(response.text || ""), etag: response.getHeader("ETag") || "" };
    } } };
  }
};
