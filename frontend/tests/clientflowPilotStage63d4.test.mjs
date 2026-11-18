import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {validateStagedPilotCandidate} from '../src/pages/adminpages/clientflowReleasePlan.mjs';

const candidate = {
  schema_version:1,phase:'approved_github_archive_source_staged_only',
  release_id:'clientflow-1.3.45-seq-1246',version:'1.3.45',sequence:1246,
  source_commit:'bc7adef9fec4f4f4bc8382a5a9d212b71b9a9085',
  approved_bundle_sha256:'e37de3250d58d313d57ad7bcbf59682cee342f2727c6ad5b188c8782342d4c78',
  approved_bundle_size:223682560,
  approval_reference:'CF-1.3.45-1246-20261118-bc7adef-f36bcd0b',
  active_release_id:'clientflow-1.3.44-seq-1245', pilot_client_id:3,
  github_artifact_approval_pinned:true,
  render_store_publication_verified:false,active_catalog_promoted:false,
  physical_pilot_accepted:false,deployment_authorized:false,
  fleet_authorized:false,fresh_install_authorized:false,database_cutover_authorized:false,
};

test('approved 1246 archive is explicitly separate from installed 1245',()=>{
  assert.equal(validateStagedPilotCandidate(candidate,'clientflow-1.3.44-seq-1245'),candidate);
  assert.throws(()=>validateStagedPilotCandidate(candidate,'clientflow-1.3.45-seq-1246'));
});

test('active update-only pilot catalog is informational, never a deployment authorization',()=>{
  const pilotCatalog = {...candidate,active_catalog_promoted:true};
  assert.equal(validateStagedPilotCandidate(pilotCatalog,candidate.active_release_id),pilotCatalog);
  for(const k of ['render_store_publication_verified','physical_pilot_accepted',
    'deployment_authorized','fleet_authorized','fresh_install_authorized','database_cutover_authorized']){
    assert.throws(()=>validateStagedPilotCandidate({...pilotCatalog,[k]:true},candidate.active_release_id),k);
    assert.throws(()=>validateStagedPilotCandidate({...candidate,[k]:undefined},candidate.active_release_id),k);
  }
  assert.throws(()=>validateStagedPilotCandidate({...candidate,active_catalog_promoted:undefined},candidate.active_release_id));
});

test('unexpected source, checksum, reference or version is refused',()=>{
  for(const [k,v] of [['release_id','clientflow-1.3.44-seq-1245'],['version','1.3.44'],
    ['sequence',1245],['source_commit','xyz'],['approved_bundle_sha256','xyz'],
    ['approved_bundle_size',0],['approval_reference','no'],['pilot_client_id',2],
    ['github_artifact_approval_pinned',false],['phase','installed']]){
    assert.throws(()=>validateStagedPilotCandidate({...candidate,[k]:v},candidate.active_release_id),k);
  }
});

test('UI is information-only and retains no deployment action in admin',()=>{
  const ui=fs.readFileSync(new URL('../src/pages/adminpages/ClientFlowReleaseAdministration.jsx',import.meta.url),'utf8');
  assert.match(ui,/Godkendt GitHub-arkiv/);
  assert.match(ui,/ikke verificeret som<\/strong> publiceret/);
  assert.match(ui,/Fysisk Viborg1-pilot/);
  assert.doesNotMatch(ui,/client\.post\(.*(?:pilot-candidate|staged_pilot)/);
  const api=fs.readFileSync(new URL('../src/pages/adminpages/clientflowReleasePlan.mjs',import.meta.url),'utf8');
  assert.match(api,/validateStagedPilotCandidate\(data\.staged_pilot_candidate/);
});
