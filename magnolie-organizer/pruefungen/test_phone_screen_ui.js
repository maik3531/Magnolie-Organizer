/* Exact Advanced browser control, no profiles or phone access. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const windows = process.argv[2] === "windows";
const source = fs.readFileSync(path.join(__dirname, windows ? "../../magnolie-organizer-windows/app/web/anwendung.js" : "../web/anwendung.js"), "utf8");
const begin = source.indexOf("  function baueTelefonBildschirm(");
const end = source.indexOf(windows ? "  const kdeDateisystemAnsichten" : "  function baueTelefonWebcam(", begin);
assert(begin > 0 && end > begin);
assert.match(source, windows ? /baueTelefonBildschirm\(erweitert, tools, id, visible\);/ :
  /"notes-live-media"\); erweitert\.append\(tools\);[\s\S]{0,200}baueTelefonBildschirm\(erweitert, tools\);/);
const dom = new JSDOM("<details open></details>");
const { document } = dom.window;
const el = (name, css, text) => {
  const node = document.createElement(name);
  if (css) node.className = css;
  if (text) node.textContent = text;
  return node;
};
const requests = [];
const build = new Function("el", "_", "kdeMedienAnfordern", "gesperrt", `${source.slice(begin, end)}\nreturn baueTelefonBildschirm;`)(
  el, value => value, (cmd, args) => new Promise(resolve => requests.push({cmd, args, resolve})), false);
const tick = () => new Promise(resolve => setImmediate(resolve));
async function main() {
  // Let jsdom deliver the initial <details open> toggle before mounting.
  await new Promise(resolve => setTimeout(resolve, 0));
  const root = document.querySelector("details");
  build(root, root, "exact", () => root.isConnected && root.open);
  await Promise.resolve();
  const panel = document.querySelector("#telefon-bildschirm");
  const [start, stop, refresh] = panel.querySelectorAll("button");
  assert(!panel.hidden);
  assert(start.disabled);
  requests.shift().resolve({ok: true, screen: {included: false, peers: [{id: "unexpected", name: "Ignored"}]}});
  await tick();
  assert(!panel.hidden);
  {
    assert.equal(panel.querySelector("summary").textContent, "Phone screen mirroring");
    assert.equal(panel.querySelector("[aria-live]").textContent, "Unavailable");
    assert(start.hidden && start.disabled && stop.hidden && stop.disabled);
    start.click(); stop.click();
    assert.equal(requests.length, 0);
  }
  root.dispatchEvent(new dom.window.Event("toggle"));
  assert.equal(requests[0].cmd, "telefon_screen_stand");
  requests.shift().resolve({ok: true, screen: {included: true, active: false, peers: []}});
  await tick();
  assert(!panel.hidden && start.disabled && stop.hidden);
  refresh.click();
  const available = {included: true, active: false, peers: [{id: "exact", name: "Test Notes"}]};
  requests.shift().resolve({ok: true, screen: available});
  await tick();
  assert(!start.disabled);
  if (windows) {
    start.click();
    requests.shift().resolve({ok: false, screen: available});
    await tick();
    assert(!start.hidden && stop.hidden && requests.length === 0);
  }
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
  requests.shift().resolve({ok: true, screen: windows ? {...available, busy: true} : {included: true, active: false, peers: []}});
  await tick();
  assert(start.disabled && stop.hidden);
  if (windows) {
    assert(start.hidden);
    refresh.click();
    requests.shift().resolve({ok: true, screen: available});
    await tick();
    assert(!start.hidden && !start.disabled);
  }
  console.log(`Advanced phone-screen DOM (${windows ? "Windows" : "Linux"}): OFF, availability, explicit start, exact peer and stop passed`);
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());
