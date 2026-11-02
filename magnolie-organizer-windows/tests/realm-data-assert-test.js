"use strict";
const assert = require("node:assert/strict"), vm = require("node:vm");
const realmAssert = require("./realm-data-assert");
const foreign = source => vm.runInNewContext(source);
realmAssert.deepStrictEqual(foreign('({ version: 3, modules: [] })'), { version: 3, modules: [] });
realmAssert.deepStrictEqual(foreign('({ a: undefined, b: NaN, c: -0, d: [,,3] })'),
  { a: undefined, b: NaN, c: -0, d: [,,3] });
const cycle = {}; cycle.self = cycle;
realmAssert.deepStrictEqual(foreign('(()=>{const a={};a.self=a;return a;})()'), cycle);
realmAssert.deepStrictEqual(foreign('Object.assign(Object.create(null), {a:1})'), Object.assign(Object.create(null), {a:1}));
const protoKey = JSON.parse('{"__proto__":{"value":1}}');
realmAssert.deepStrictEqual(foreign('JSON.parse(\'{"__proto__":{"value":1}}\')'), protoKey);
for (const [actual, expected] of [
  [foreign('({version:2,modules:[]})'), { version: 3, modules: [] }],
  [foreign('({version:"3",modules:[]})'), { version: 3, modules: [] }],
  [foreign('({modules:[]})'), { version: 3, modules: [] }],
  [foreign('({a:undefined})'), {}], [foreign('({a:null})'), { a: undefined }],
  [foreign('({a:-0})'), { a: 0 }], [foreign('[,]'), [undefined]],
  [foreign('Object.create(null)'), {}], [foreign('new (class Data {constructor(){this.a=1}})()'), { a: 1 }],
  [foreign('new Date(0)'), new Date(1)], [foreign('({[Symbol.for("key")]:1})'), {}]
]) assert.throws(() => realmAssert.deepStrictEqual(actual, expected), assert.AssertionError);
assert.throws(() => realmAssert.strictEqual("3", 3), assert.AssertionError);
console.log("PASS strict cross-realm plain-data equality and real value/type/shape mismatch rejection");
