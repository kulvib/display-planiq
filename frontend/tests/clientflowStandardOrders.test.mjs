import test from "node:test";
import assert from "node:assert/strict";
import {BASELINE_ID, BASELINE_VERSION, validateStandardBaselineResponse, eligibleOrderClients, prepareOrderTargets, validateOrderAvailability, verifyOrderResult} from "../src/pages/adminpages/clientflowStandardOrders.mjs";

const base = {
  phase:"standard_baseline",stable_release_id:BASELINE_ID,stable_version:BASELINE_VERSION,
  authorization_active:false, rollback_available:false,fresh_install_open:false,
  standard_order_review_available:true,client_inventory_complete:true,
  available_releases:[{release_id:BASELINE_ID,version:BASELINE_VERSION,status:"stable",deployment_authorized:false}],
  available_clients:[{id:3,name:"Viborg1",reported_version:"1.3.47"},{id:4,name:"Ny",reported_version:"1.4.0"},
    {id:5,name:"Ældre",reported_version:"1.3.46"},{id:7,name:"Test",reported_version:"1.3.47"}],
  active_deployments:[],active_deployments_complete:true,recent_deployments:[],waves:[],
};
test("standard baseline is a read-only inventory, not an authorization",()=>{
  assert.equal(validateStandardBaselineResponse(base),base);
  for(const delta of [{authorization_active:true},{rollback_available:true},{fresh_install_open:true},
    {stable_release_id:"other"},{client_inventory_complete:false},{available_releases:[]}]) {
    assert.throws(()=>validateStandardBaselineResponse({...base,...delta}));
  }
});
test("explicit compatible selection excludes active, unknown and wrong versions",()=>{
  assert.deepEqual(eligibleOrderClients(base).map(row=>row.id),[3,7]);
  assert.deepEqual(prepareOrderTargets(base,[7,3]),[
    {client_id:3,expected_source_version:"1.3.47"},{client_id:7,expected_source_version:"1.3.47"}]);
  for(const ids of [[3,3],[4],[5],[],[9]]) assert.throws(()=>prepareOrderTargets(base,ids));
  assert.deepEqual(eligibleOrderClients({...base,standard_order_review_available:false}),[]);
  assert.deepEqual(eligibleOrderClients({...base,active_deployments_complete:false}),[]);
});
test("order requires fresh exact authority and verifies every response",()=>{
  const authority={available:true,target_release_id:BASELINE_ID,target_version:BASELINE_VERSION,bundle_sha256:"a".repeat(64),revision:2,max_clients:25,rollback_available:false};
  assert.equal(validateOrderAvailability(authority),authority);
  for(const delta of [{available:false},{revision:0},{bundle_sha256:"bad"},{rollback_available:true}]) {
    assert.throws(()=>validateOrderAvailability({...authority,...delta}));
  }
  const targets=prepareOrderTargets(base,[3]);
  const result={target_release_id:BASELINE_ID,deployments:[{client_id:3,deployment_id:"07aba6a1-9454-4563-8ae3-4dd05c3d6bd4",state:"authorized"}]};
  assert.equal(verifyOrderResult(result,targets),result);
  assert.throws(()=>verifyOrderResult({...result,deployments:[]},targets));
  assert.throws(()=>verifyOrderResult({...result,deployments:[{...result.deployments[0],client_id:7}]},targets));
});

test("closed 1251 standard displays exact transition without any order authority",()=>{
  for(const pending of [true,false]){
    const closed={...base,stable_release_id:"clientflow-1.4.1-seq-1251",stable_version:"1.4.1",
      cutover_enabled:false,fleet_open:false,standard_order_review_available:false,
      successor_pilot_review_available:false,closed_standard_transition_pending:pending,revision:pending?2:3,
      available_releases:[{release_id:"clientflow-1.4.1-seq-1251",version:"1.4.1",status:"stable",deployment_authorized:false}],
      available_clients:[{id:3,name:"Viborg1",reported_version:"1.4.1"}]};
    assert.equal(validateStandardBaselineResponse(closed),closed);
    assert.deepEqual(eligibleOrderClients(closed),[]);
    assert.throws(()=>prepareOrderTargets(closed,[3]));
    for(const delta of [{fleet_open:true},{cutover_enabled:true},{fresh_install_open:true},
      {successor_pilot_review_available:true},{standard_order_review_available:true},
      {rollback_available:true},{revision:1},{closed_standard_transition_pending:!pending},
      {stable_version:"1.4.0"}]){
      assert.throws(()=>validateStandardBaselineResponse({...closed,...delta}));
    }
  }
});
