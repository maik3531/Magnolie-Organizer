// Exercise the Windows Advanced panel with a controlled native bridge.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {JSDOM} = require("jsdom");
const source = fs.readFileSync(path.join(__dirname, "../../magnolie-organizer-windows/app/web/anwendung.js"), "utf8");
const begin = source.indexOf("  function baueTelefonWebcam(");
const end = source.indexOf("  function baueTelefonBildschirm(", begin);
assert(begin > 0 && end > begin);
assert.match(source, /baueTelefonWebcam\(erweitert, tools, id, visible\);/);
const dom = new JSDOM("<details></details>");
const {document} = dom.window;
const root = document.querySelector("details");
const requests = [];
const el = (tag, cls, text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text) element.textContent = text;
  return element;
};
const build = new Function("el", "_", "kdeMedienAnfordern", `${source.slice(begin, end)}\nreturn baueTelefonWebcam;`)(
  el, value => value, (cmd, args) => new Promise(resolve => requests.push({cmd, args, resolve})));
const tick = () => new Promise(resolve => setImmediate(resolve));

async function check() {
  let current = true;
  build(root, root, "b", () => current && root.isConnected && root.open);
  const panel = document.querySelector("#telefon-webcam");
  const [start, stop, refresh] = panel.querySelectorAll("button");
  const picker = panel.querySelector("select");
  const reply = async (cmd, args, webcam, ok = true) => {
    const request = requests.shift();
    assert.deepEqual([request?.cmd, request?.args], [cmd, args]);
    request.resolve({ok, webcam});
    await tick();
  };
  assert(!panel.hidden && start.disabled && requests.length === 0, "Initial UI cannot request capture");
  root.open = true;
  await tick();
  if (!requests.length) root.dispatchEvent(new dom.window.Event("toggle"));
  await reply("telefon_webcam_stand", {}, {included: false, phase: "off"});
  assert(!panel.hidden && start.hidden && start.disabled);
  assert.equal(panel.querySelector('[aria-live]').textContent, 'Unavailable');
  const choose = {included: true, phase: "off", peers: [{id: "a", name: "Phone A"}, {id: "b", name: "Phone B"}]};
  await tick();
  if (!requests.length) refresh.click();
  await reply("telefon_webcam_stand", {}, choose);
  assert.deepEqual([...picker.options].map(option => option.value), ["b"]);
  picker.value = "b";
  start.click(); start.click();
  await reply("telefon_webcam_start", {peer: "b"}, choose, false);
  assert(!panel.hidden && requests.length === 0 && picker.value === "b");
  start.click();
  await reply("telefon_webcam_start", {peer: "b"}, {included: true, phase: "starting", run: "original"});
  assert(stop.hidden === false && start.hidden);
  stop.click();
  await reply("telefon_webcam_stop", {run: "original"}, {included: true, phase: "stopping", run: "original"});
  assert(start.hidden && stop.hidden);
  refresh.click();
  await reply("telefon_webcam_stand", {}, choose);
  assert(!start.hidden && !start.disabled && stop.hidden);
  current = false;
  start.click(); refresh.click();
  assert.equal(requests.length, 0, "An obsolete Notes presentation cannot dispatch");
  console.log("Windows webcam DOM: default off, explicit peer, denial, exact stop and confirmed drain");
}

check().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());
