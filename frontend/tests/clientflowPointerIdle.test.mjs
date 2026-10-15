import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(root, "client/runtime/clientflow_runtime/browser_guard.py"), "utf8");
const begin = source.indexOf("  if (document.documentElement && !window.__clientflowCursorIdleInstalled)");
const end = source.indexOf("  // v1.5.2:", begin);

test("pointer becomes hidden after inactivity, reappears on real movement, once per page", () => {
  assert.ok(begin > 0 && end > begin);
  const script = source.slice(begin, end);
  const attrs = new Map();
  const handlers = new Map();
  const tasks = new Map();
  let nextId = 0;
  const rootNode = {
    setAttribute(key, value) { attrs.set(key, value); },
    removeAttribute(key) { attrs.delete(key); },
    appendChild() {},
  };
  const sandbox = {
    document: {documentElement: rootNode, head: rootNode,
      createElement: () => ({id:"", textContent:""})},
    window: {addEventListener: (name, cb) => handlers.set(name, cb)},
    setTimeout: (fn) => {const id=++nextId; tasks.set(id,fn); return id;},
    clearTimeout: (id) => tasks.delete(id),
  };
  vm.runInNewContext(script, sandbox);
  assert.equal(handlers.size, 3);
  for (const fn of tasks.values()) fn();
  assert.equal(attrs.get("data-clientflow-cursor-idle"), "1");
  handlers.get("pointermove")({isTrusted:true});
  assert.equal(attrs.has("data-clientflow-cursor-idle"), false);
  for (const fn of tasks.values()) fn();
  assert.equal(attrs.get("data-clientflow-cursor-idle"), "1");
  vm.runInNewContext(script, sandbox);
  assert.equal(handlers.size, 3);
});
