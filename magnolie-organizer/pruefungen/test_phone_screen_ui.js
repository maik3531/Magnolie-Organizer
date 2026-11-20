/* Exact Advanced browser control, no profiles or phone access. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const source = fs.readFileSync(path.join(__dirname, "../web/anwendung.js"), "utf8");
const begin = source.indexOf("  function baueTelefonBildschirm(");
const end = source.indexOf("  function baueTelefonWebcam(", begin);
assert(begin > 0 && end > begin);
const dom = new JSDOM("<details open></details>");
const { document } = dom.window;
const el = (name, css, text) => {
  const node = document.createElement(name);
  if (css) node.className = css;
  if (text) node.textContent = text;
  return node;
};
const requests = [];
const build = new Function("el", "_", "kdeMedienAnfordern", `${source.slice(begin, end)}\nreturn baueTelefonBildschirm;`)(
  el, value => value, (cmd, args) => new Promise(resolve => requests.push({cmd, args, resolve})));
const tick = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  const root = document.querySelector("details");
  build(root);
  const panel = document.querySelector("#telefon-bildschirm");
  const [start, stop, refresh] = panel.querySelectorAll("button");
  assert(panel.hidden && start.disabled);
  requests.shift().resolve({ok: true, screen: {included: false}});
  await tick();
  assert(panel.hidden);
  root.dispatchEvent(new dom.window.Event("toggle"));
  assert.equal(requests[0].cmd, "telefon_screen_stand");
  requests.shift().resolve({ok: true, screen: {included: true, active: false, peers: []}});
  await tick();
  assert(!panel.hidden && start.disabled && stop.hidden);
  refresh.click();
  requests.shift().resolve({ok: true, screen: {included: true, active: false, peers: [{id: "exact", name: "Test Notes"}]}});
  await tick();
  assert(!start.disabled);
  start.click();
  start.click();
  assert.equal(requests.length, 1);
  const request = requests.shift();
  assert.equal(request.cmd, "telefon_screen_start");
  assert.deepEqual(request.args, {peer: "exact"});
  request.resolve({ok: true, screen: {included: true, active: true, peers: []}});
  await tick();
  assert(start.hidden && !stop.hidden);
  stop.click();
  assert.equal(requests[0].cmd, "telefon_screen_stop");
  requests.shift().resolve({ok: true, screen: {included: true, active: false, peers: []}});
  await tick();
  assert(start.disabled && stop.hidden);
  console.log("Advanced phone-screen DOM: OFF, availability, explicit start, exact peer and stop passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());
