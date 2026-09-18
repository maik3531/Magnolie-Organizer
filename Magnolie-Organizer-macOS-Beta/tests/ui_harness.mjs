import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const { JSDOM } = createRequire(import.meta.url)(process.env.MACOS_BETA_JSDOM || "../../magnolie-organizer-windows/node_modules/jsdom/lib/api.js");

export const tick = () => new Promise(resolve => setTimeout(resolve, 1));
export async function boot(root, instant = Date.now()) {
  const web = path.join(root, "web");
  const dom = new JSDOM(fs.readFileSync(path.join(web, "index.html"), "utf8"), {
    runScripts: "outside-only", url: "https://macos-beta-host-test.invalid/web/index.html", pretendToBeVisual: true
  });
  const w = dom.window, messages = [], timers = [];
  let now = instant;
  const RealDate = w.Date;
  w.Date = class extends RealDate {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  };
  w.structuredClone = structuredClone;
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.setTimeout = (fn, delay) => { const t = { fn, delay }; timers.push(t); return t; };
  w.clearTimeout = timer => { if (timer) timer.cancelled = true; };
  w.setInterval = () => 0; w.requestAnimationFrame = () => 0;
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.__MAGNOLIE_BRUECKE__ = "hostTest";
  w.webkit = { messageHandlers: { hostTest: { postMessage(raw) { messages.push(JSON.parse(raw)); } } } };
  for (const script of w.document.querySelectorAll("script[src]")) {
    w.eval(fs.readFileSync(path.join(web, script.getAttribute("src")), "utf8"));
  }
  await tick();
  assert.equal(messages.filter(m => m.cmd === "bereit").length, 1);
  return { w, messages, timers, t: w.OrganizerTest, at: value => { now = Date.parse(value); }, close: () => w.close() };
}
