"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const source = fs.readFileSync(path.join(__dirname, "../web/anwendung.js"), "utf8");
const begin = source.indexOf("  function baueTelefonWebcam(");
const end = source.indexOf("  const kdeDateisystemAnsichten", begin);
assert(begin > 0 && end > begin);
assert.match(source, /"notes-live-media"\); erweitert\.append\(tools\);\s*const webcam = baueTelefonWebcam\(erweitert, tools\);/);
const dom = new JSDOM("<details open></details>");
const { document } = dom.window;
const el = (tag, css, text) => {
  const node = document.createElement(tag);
  if (css) node.className = css;
  if (text) node.textContent = text;
  return node;
};
const knopf = (text, css, click) => { const node = el("button", css, text); node.addEventListener("click", click); return node; };
const requests = [], timers = new Map(), cancelled = [];
let timerId = 0;
const build = new Function("document", "el", "_", "knopf", "gesperrt", "kdeMedienAnfordern", "setTimeout", "clearTimeout", "Bruecke",
  source.slice(begin, end) + "\nreturn baueTelefonWebcam;")(
  document, el, text => text, knopf, false,
  (cmd, args) => new Promise(resolve => requests.push({cmd, args, resolve})),
  run => { timers.set(++timerId, run); return timerId; }, id => timers.delete(id), {sende: value => cancelled.push(value)});
const tick = () => new Promise(resolve => setImmediate(resolve));

async function main() {
  await new Promise(resolve => setTimeout(resolve, 0));
  const root = document.querySelector("details");
  const dispose = build(root, root);
  await Promise.resolve();
  const panel = document.querySelector("#telefon-webcam");
  const [enable, start, stop] = panel.querySelectorAll("button");
  const controls = panel.querySelector(".notes-webcam-controls"), status = panel.querySelector("[aria-live]");
  async function response(webcam) {
    assert.equal(requests.length, 1);
    const request = requests.shift();
    assert.equal(request.cmd, "telefon_webcam_stand");
    request.resolve({ok: true, webcam}); await tick();
  }
  function refresh() {
    assert.equal(timers.size, 1);
    const [id, run] = timers.entries().next().value;
    timers.delete(id); run();
  }
  assert.equal(panel.querySelector("h4").textContent, "Phone webcam");
  assert(!panel.hidden && controls.hidden && enable.disabled && start.disabled && stop.disabled);
  await response({included: false, visible: true});
  assert(!panel.hidden && controls.hidden && status.textContent === "Unavailable");
  refresh();
  await response({included: true, visible: false});
  assert(!panel.hidden && controls.hidden && status.textContent === "Connect Magnolie Notes over WLAN first.");
  enable.click(); start.click(); stop.click();
  assert.equal(requests.length, 0);
  refresh();
  await response({included: true, visible: true, enabled: false, phase: "off"});
  assert(!controls.hidden && !enable.disabled && start.disabled && stop.disabled && status.textContent === "Off");
  assert(start.hidden && stop.hidden);
  assert.equal(panel.querySelectorAll("select").length, 1, "No provider chooser in the Notes section");
  assert.equal(controls.querySelectorAll(".notes-webcam-options > label > input[type=checkbox]").length, 2);
  assert(!panel.querySelector('input[type="checkbox"]').checked);
  enable.click();
  const prepare = requests.shift();
  assert.deepEqual(prepare.args.request, {action: "prepare", provider: "notes"});
  prepare.resolve({ok: true, webcam: {included: true, visible: true, action: "choice-action", choices: [{device: "Fake", token: "choice"}]}});
  await tick(); assert(!start.disabled);
  refresh();
  await response({included: true, visible: false});
  assert(controls.hidden && start.disabled);
  assert.deepEqual(cancelled.map(value => value.request), [{action: "cancel", action_token: "choice-action"}]);
  dispose();
  assert.equal(timers.size, 0);
  root.dispatchEvent(new dom.window.Event("toggle"));
  assert.equal(requests.length, 0);
  console.log("Linux webcam DOM: discoverable, unavailable/WLAN states, default OFF and readiness withdrawal passed");
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => dom.window.close());
