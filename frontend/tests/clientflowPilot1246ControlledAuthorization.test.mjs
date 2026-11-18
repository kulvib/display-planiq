import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
const panel = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowPilot1246Panel.jsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/service1/routers/clientflow_release_pilot_63d7.py", import.meta.url), "utf8");

test("63D-7 keeps inert waves and exposes one separately verified physical pilot", () => {
  assert.match(page, /<ClientFlowPilot1246Panel status=\{status\} onAuthorized=\{refresh\}/);
  assert.match(page, /Gennemgå og gem inaktiv plan/);
  assert.match(page, /Rollback til valgte klienter · spærret/);
  assert.match(page, /Installer på nye klienter · spærret/);
  assert.match(panel, /candidate\?\.active_catalog_promoted === true/);
  assert.match(panel, /candidate\.pilot_client_id === 3/);
  assert.match(panel, /device\?\.name === "Viborg1"/);
  assert.match(panel, /confirmed_single_pilot: true/);
  assert.match(panel, /expected_policy_revision: status\.revision/);
  assert.match(panel, /expected_current_version: device\.reported_version/);
  assert.match(panel, /Genbekræft superadministratorens adgangskode/);
  assert.match(panel, /Autoriser og start pilot/);
  assert.doesNotMatch(panel, /setInterval|setTimeout|useEffect\(|client\.get\(/);
});

test("63D-7 does not enable fleet, env-based grants or rollback", () => {
  assert.match(route, /@router.post\("\/authorize", status_code=201\)/);
  assert.match(route, /_reauth\(request, session, user, body\.password\)/);
  assert.match(route, /lock_system_client\(session, 3\)/);
  assert.match(route, /create_authorized_deployment\(/);
  assert.match(route, /session\.commit\(\)/);
  assert.match(route, /require_database_pilot_1246\(/);
  assert.match(route, /allow_downgrade=False/);
  assert.match(route, /ClientFlowUpdateCredential\.revoked_at\.is_\(None\)/);
  assert.doesNotMatch(route, /os\.environ\.setdefault|os\.environ\[/);
  assert.doesNotMatch(route, /fleet_open\s*=\s*True|cutover_enabled\s*=\s*True/);
});
