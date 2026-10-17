import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const py = readFileSync(new URL("../../client/runtime/clientflow_runtime/browser_guard.py", import.meta.url), "utf8");
const extract = (begin, end) => py.split(begin)[1]?.split(end)[0];

function fakeDOM() {
  const elements = new Map();
  const attrs = new Map();
  const makeElement = () => ({ id: "", textContent: "", style: { setProperty() {} }, removeAttribute() {}, remove() {} });
  const root = { setAttribute(k, v) { attrs.set(k, v); }, removeAttribute(k) { attrs.delete(k); }, appendChild(el) { elements.set(el.id, el); } };
  const document = {
    documentElement: root, body: root, readyState: "complete",
    head: { appendChild(el) { elements.set(el.id, el); } },
    createElement: makeElement, getElementById: (id) => elements.get(id) || null,
    querySelector: () => null,
  };
  return { document, root, elements, attrs };
}

test("guard uses shared CMP-only CSS without changing native dialogs or legitimate content", () => {
  const script = extract('HIDE_JS = r"""', '""".replace("__COOKIE_MODE__"')
    .replace("__COOKIE_MODE__", "hide")
    .replace("__CONSENT_CSS__", JSON.stringify("#coiOverlay { display:none!important; }"));
  assert.ok(script);
  const dom = fakeDOM();
  const originalConfirm = () => false;
  const originalOpen = () => null;
  const originalAlert = () => {};
  const window = { confirm: originalConfirm, open: originalOpen, alert: originalAlert, addEventListener() {} };
  const context = { document: dom.document, window, setTimeout: () => 1, clearTimeout() {}, location: {href: "https://site.example/s?sig=secret"} };
  const result = vm.runInNewContext(script, context);
  assert.equal(result.marker, "1.7.0");
  assert.equal(result.css, true);
  assert.equal(window.confirm, originalConfirm);
  assert.equal(window.open, originalOpen);
  assert.equal(window.alert, originalAlert);
  assert.match(dom.elements.get("clientflow-browser-guard-css").textContent, /#coiOverlay/);
  assert.doesNotMatch(dom.elements.get("clientflow-browser-guard-css").textContent, /dashboard|cookie-banner/);
  assert.equal(dom.attrs.get("data-clientflow-browser-guard"), "1.7.0");
});

test("refresh leaves signed URL unchanged", () => {
  const source = extract('COUNTDOWN_JS = r"""', '"""\n\n\nasync def evaluate_js');
  assert.ok(source);
  const script = source.replace("__REFRESH_SEC__", "60").replace("__START_DELAY_SEC__", "0");
  const dom = fakeDOM();
  let now = 1_000_000;
  let reloads = 0;
  const location = {href: "https://site.example/screen?signature=abc%2Fdef#overview", reload() { reloads++; }};
  const window = {};
  const Date = {now: () => now};
  const context = {document: dom.document, window, location, Date, setInterval() {return 1;}, screen:{height:1080,width:1920,availHeight:1080,availWidth:1920}, outerHeight:800,innerHeight:800, outerWidth:1200,innerWidth:1200};
  vm.runInNewContext(script, context);
  now += 61_000;
  vm.runInNewContext(script, context);
  assert.equal(reloads, 1);
  assert.equal(location.href, "https://site.example/screen?signature=abc%2Fdef#overview");
});
