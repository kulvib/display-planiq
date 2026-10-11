import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("Display browser branding uses approved SVG variants", () => {
  const brand = read("src/branding.js");
  assert.match(brand, /planiq-display-logo-primary\.svg/);
  assert.match(brand, /planiq-display-logo-reversed\.svg/);
  assert.match(brand, /planiq-display-logo-white\.svg/);
  assert.match(read("src/Dashboard.jsx"), /PRODUCT_BRAND\.logo\.nav/);
  for (const screen of ["LoginPage", "ForgotPasswordPage", "ResetPasswordPage", "ChangePassword"]) {
    assert.match(read(`src/${screen}.jsx`), /PRODUCT_BRAND\.logo\.dark/);
  }
});

test("Copyright is shared across routes, maintenance errors, and login", () => {
  const root = read("src/main.jsx");
  const footer = read("src/components/PlanIQFooter.jsx");
  assert.equal(root.split("<PlanIQFooter />").length - 1, 1);
  assert.ok(root.indexOf("<PlanIQFooter />") > root.indexOf("</MaintenanceGate>"));
  assert.match(footer, /new Date\(\)\.getFullYear\(\)/);
  assert.match(footer, /Alle rettigheder forbeholdes/);
});

test("Full HD and 4K use same intact source with proportional GNOME scaling", () => {
  const bootstrap = read("../client/bootstrap/clientflow_bootstrap_common.py");
  const policy = read("../client/runtime/clientflow_runtime/kiosk_session_policy.py");
  const image = "planiq-display-desktop-wallpaper-3840x2160.png";
  assert.ok(bootstrap.includes(image));
  assert.ok(policy.includes(image));
  assert.match(bootstrap, /picture-options", "'scaled'"/);
  assert.match(policy, /picture-options", "'scaled'"/);
});
