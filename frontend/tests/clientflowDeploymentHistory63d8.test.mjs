import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { deploymentPresentation, validateDeploymentHistory } from "../src/pages/adminpages/clientflowDeploymentHistory.mjs";
import { validateReleasePlanningResponse } from "../src/pages/adminpages/clientflowReleasePlan.mjs";

const good = {
  id: "07aba6a1-9454-4563-8ae3-4dd05c3d6bd4", client_id: 3,
  client_name: "Viborg1", target_version: "1.3.45",
  target_release_id: "clientflow-1.3.45-seq-1246", state: "succeeded",
  requested_at: "2026-11-18T21:10:19Z", state_updated_at: "2026-11-18T21:11:31Z",
  completed_at: "2026-11-18T21:11:31Z", observed_release_id: "clientflow-1.3.45-seq-1246",
};

test("63D-8 renders only observed deployment states; no invented download percentage", () => {
  assert.equal(validateDeploymentHistory([good]).length, 1);
  assert.deepEqual(deploymentPresentation("succeeded"), { label: "Gennemført", color: "success", step: 6, terminal: true });
  assert.equal(deploymentPresentation("downloading").step, 1);
  assert.equal(deploymentPresentation("recovery_failed").color, "error");
  assert.equal(deploymentPresentation("rolling_back").terminal, false);
  const ui = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowDeploymentHistory.jsx", import.meta.url), "utf8");
  assert.match(ui, /Bestilt/);
  assert.match(ui, /DEPLOYMENT_STEPS/);
  assert.match(ui, /failure_message/);
  assert.doesNotMatch(ui, /setInterval|setTimeout|client\.get/);
});

test("63D-8 malformed or widened deployment history fails closed", () => {
  for (const changed of [
    {state: "new_unapproved_state"}, {state:"failed",completed_at:null},
    {state:"downloading",completed_at:good.completed_at},
    {client_id: -1}, {target_version:"bad"},
    {target_release_id:"arbitrary"}, {id:"bad"},
    {failure_message:"X".repeat(501)},
  ]) assert.throws(() => validateDeploymentHistory([{...good,...changed}]));
  assert.throws(() => validateDeploymentHistory([good,good]));
  assert.throws(() => validateDeploymentHistory(Array.from({length:21}, (_,i)=>({...good,id:`00000000-0000-0000-0000-${String(i).padStart(12,"0")}`}))));
});

test("63D-8 release admin uses the existing manual refresh; details history only on demand", () => {
  const admin = fs.readFileSync(new URL("../src/pages/adminpages/ClientFlowReleaseAdministration.jsx", import.meta.url), "utf8");
  const details = fs.readFileSync(new URL("../src/pages/clientdetailspage/ClientDetailsInfoSection.jsx", import.meta.url), "utf8");
  const api = fs.readFileSync(new URL("../../backend/service1/routers/clientflow_release_administration.py", import.meta.url), "utf8");
  assert.match(admin, /status\.recent_deployments/);
  assert.match(admin, /onClick=\{\(\) => void refresh\(\)\}/);
  assert.match(details, /ClientFlowHistoryOnDemand/);
  const history = fs.readFileSync(new URL("../src/pages/clientdetailspage/ClientFlowHistoryOnDemand.jsx", import.meta.url), "utf8");
  assert.match(history, /Vis opdateringshistorik/);
  assert.match(history, /getClientflowDeployments\(clientId, \{ limit: 10 \}\)/);
  assert.doesNotMatch(history, /setInterval/);
  assert.match(api, /\.limit\(20\)/);
  assert.match(api, /recent_deployments/);
  assert.match(api, /get_current_superadmin_user/);
  assert.doesNotMatch(api, /@router\.post\("\/?recent/);
});
