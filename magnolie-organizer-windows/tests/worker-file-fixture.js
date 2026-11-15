"use strict";
// #664: real isolated threads with byte-identical product worker source, without
// Bun/Windows' crashing eval-worker path. No change to the browser's Blob worker.
const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
const assert = require("node:assert/strict");
const { Worker } = require("node:worker_threads");
const prelude = 'const { parentPort } = require("node:worker_threads"); globalThis.self = globalThis; self.postMessage = value => parentPort.postMessage(value); parentPort.on("message", data => self.onmessage({ data }));\n';

class WorkerFileFixture {
  constructor() { this.folder = null; this.threads = []; }
  start(source) {
    assert.equal(typeof source, "string"); assert.ok(source.length);
    this.folder ||= fs.mkdtempSync(path.join(os.tmpdir(), "magnolie-worker-664-"));
    const file = path.join(this.folder, "worker-" + this.threads.length + ".cjs");
    assert.ok(path.isAbsolute(file));
    fs.writeFileSync(file, prelude + source, { flag: "wx" });
    assert.equal(fs.readFileSync(file, "utf8"), prelude + source);
    const thread = new Worker(file); this.threads.push(thread); return thread;
  }
  async close() {
    await Promise.all(this.threads.map(thread => thread.terminate()));
    if (this.folder) {
      fs.rmSync(this.folder, { recursive: true });
      assert.equal(fs.existsSync(this.folder), false);
    }
  }
}

function linuxWeb() {
  const sibling = path.resolve(__dirname, "../../magnolie-organizer");
  const embedded = path.resolve(__dirname, "../shared/magnolie-organizer");
  return path.resolve(process.env.MAGNOLIE_LINUX_SOURCE ||
    (fs.existsSync(path.join(sibling, "web/index.html")) ? sibling : embedded), "web");
}
module.exports = { WorkerFileFixture, linuxWeb };
