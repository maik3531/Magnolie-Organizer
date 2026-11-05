"use strict";
const nativeAssert = require("node:assert");
const nullPrototype = Symbol("cross-realm null prototype");

// jsdom's plain data objects have a different Object.prototype. Normalize only
// genuine plain objects/arrays, never custom classes or other builtin types.
// Unlike a JSON roundtrip this preserves undefined, NaN, -0, sparse arrays,
// symbol keys, null prototypes and cycles. All other assertion behavior stays
// strict and is delegated to Node's original assertion implementation.
function hostData(value, seen = new Map()) {
  if (value === null || typeof value !== "object") return value;
  if (seen.has(value)) return seen.get(value);
  const prototype = Object.getPrototypeOf(value);
  const constructor = prototype && Object.getOwnPropertyDescriptor(prototype, "constructor")?.value;
  const nativeConstructor = name => typeof constructor === "function" &&
    Function.prototype.toString.call(constructor) === Function.prototype.toString.call(name);
  const array = Array.isArray(value) && nativeConstructor(Array);
  const plain = prototype === null || (Object.getPrototypeOf(prototype) === null && nativeConstructor(Object));
  if (!array && !plain) return value;
  const result = array ? new Array(value.length) : Object.create(prototype === null ? null : Object.prototype);
  // Bun's Node-compatible assertion currently ignores a null-vs-Object
  // prototype difference. Keep that distinction as data too, without changing
  // inputs or weakening Node's original deep-strict comparison.
  if (prototype === null) Object.defineProperty(result, nullPrototype, { value: true, enumerable: true });
  seen.set(value, result);
  for (const key of Reflect.ownKeys(value)) {
    if (!Object.prototype.propertyIsEnumerable.call(value, key)) continue;
    Object.defineProperty(result, key, { value: hostData(value[key], seen),
      enumerable: true, writable: true, configurable: true });
  }
  return result;
}

module.exports = Object.assign(Object.create(nativeAssert), nativeAssert, {
  deepStrictEqual(actual, expected, message) {
    nativeAssert.deepStrictEqual(hostData(actual), hostData(expected), message);
  }
});
