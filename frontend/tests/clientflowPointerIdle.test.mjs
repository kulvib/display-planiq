import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const source = fs.readFileSync(path.join(root, "client/runtime/clientflow_runtime/browser_guard.py"), "utf8");
const begin = source.indexOf("  if (!window.__clientflowCursorIdleInstalled) {");
const end = source.indexOf("\n  root.setAttribute('data-clientflow-browser-guard', VERSION)", begin);

test("pointer becomes hidden after inactivity, reappears on real movement, once per page", () => {
  assert.ok(begin >= 0 && end > begin, "Browser Guard must install the kiosk cursor-idle handler");
  // The guard now resolves document.documentElement to `root` before this block.
  // Execute the actual kiosk handler with that exact lexical binding.
  const script = `(() => {\nconst root = document.documentElement;\n${source.slice(begin, end)}\n})()`;
  const attrs = new Map();
  const handlers = new Map();
  const tasks = new Map();
  const cssNodes = [];
  let nextId = 0;
  let registrations = 0;
  const rootNode = {
    setAttribute(key, value) { attrs.set(key, value); },
    removeAttribute(key) { attrs.delete(key); },
    appendChild(node) { cssNodes.push(node); },
  };
  const sandbox = {
    document: {
      documentElement: rootNode,
      head: rootNode,
      createElement: () => ({ id: "", textContent: "" }),
    },
    window: {
      addEventListener(name, cb) {
        registrations += 1;
        assert.ok(!handlers.has(name), `duplicate listener: ${name}`);
        handlers.set(name, cb);
      },
    },
    setTimeout(fn, ms) {
      assert.equal(ms, 2000, "cursor inactivity threshold must remain 2 seconds");
      const id = ++nextId;
      tasks.set(id, fn);
      return id;
    },
    clearTimeout(id) { tasks.delete(id); },
  };

  vm.runInNewContext(script, sandbox);
  assert.equal(registrations, 3);
  assert.deepEqual([...handlers.keys()], ["pointermove", "pointerdown", "keydown"]);
  assert.equal(cssNodes.length, 1);
  assert.equal(cssNodes[0].id, "clientflow-idle-cursor");
  assert.match(cssNodes[0].textContent, /cursor: none !important/);
  assert.equal(attrs.has("data-clientflow-cursor-idle"), false);
  assert.equal(tasks.size, 1);

  for (const fn of [...tasks.values()]) fn();
  assert.equal(attrs.get("data-clientflow-cursor-idle"), "1");
  // Synthetic events must not keep a kiosk cursor visible.
  handlers.get("pointermove")({ isTrusted: false });
  assert.equal(attrs.get("data-clientflow-cursor-idle"), "1");
  handlers.get("pointermove")({ isTrusted: true });
  assert.equal(attrs.has("data-clientflow-cursor-idle"), false);
  assert.equal(tasks.size, 1);
  for (const fn of [...tasks.values()]) fn();
  assert.equal(attrs.get("data-clientflow-cursor-idle"), "1");

  vm.runInNewContext(script, sandbox);
  assert.equal(registrations, 3, "repeated guard polling must not add listeners");
  assert.equal(cssNodes.length, 1, "repeated guard polling must not add stylesheets");
});
