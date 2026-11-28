import test from "node:test";
import assert from "node:assert/strict";
import {organizationOptions, organizationScope, filterRolloutClients, visibleSelection, bindOrganizationTargets} from "../src/pages/adminpages/clientflowRolloutSelection.mjs";

const rows = [
  {id:3,name:"Viborg1",organization_id:10,organization_name:"Kulturskole"},
  {id:7,name:"Klient B",organization_id:20,organization_name:"Skole"},
  {id:8,name:"Klient C",organization_id:10,organization_name:"Kulturskole"},
  {id:9,name:"Klient D",organization_id:null},
];
test("organization dropdown groups actual IDs and includes unassigned clients",()=>{
  assert.equal(organizationOptions(rows).length,3);
  assert.deepEqual(filterRolloutClients(rows,"10").map(row=>row.id),[3,8]);
  assert.deepEqual(filterRolloutClients(rows,"none").map(row=>row.id),[9]);
  assert.equal(filterRolloutClients(rows,"all").length,4);
  assert.deepEqual(filterRolloutClients(rows,"10","viborg").map(row=>row.id),[3]);
  assert.throws(()=>organizationScope("010"));
  assert.throws(()=>organizationScope("invalid"));
});
test("hidden and duplicate selections cannot survive the visible selection boundary",()=>{
  const visible=filterRolloutClients(rows,"10");
  assert.deepEqual(visibleSelection([3,3,7,8,9],visible,25),[3,8]);
  assert.throws(()=>visibleSelection([3,8],visible,1));
  assert.deepEqual(visibleSelection([3,8],filterRolloutClients(rows,"20"),25),[]);
});
test("order binds each selected client's organization even for all organizations",()=>{
  const target={client_id:7,expected_source_version:"1.4.1"};
  assert.deepEqual(bindOrganizationTargets([target],rows,"all"),[{...target,expected_organization_id:20}]);
  assert.throws(()=>bindOrganizationTargets([target],rows,"10"));
  assert.throws(()=>bindOrganizationTargets([target],filterRolloutClients(rows,"10"),"all"));
  assert.deepEqual(bindOrganizationTargets([{...target,client_id:9}],rows,"none"),[
    {...target,client_id:9,expected_organization_id:null}]);
});
