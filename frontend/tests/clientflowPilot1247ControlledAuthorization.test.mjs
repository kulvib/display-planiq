import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import {validateStagedPilotCandidate} from '../src/pages/adminpages/clientflowReleasePlan.mjs';

const base = {
  schema_version:1,phase:'approved_github_archive_source_staged_only',
  release_id:'clientflow-1.3.46-seq-1247',version:'1.3.46',sequence:1247,
  source_commit:'22a8a873899fe736018e8238f4b2ec4bb896f6a2',
  approved_bundle_sha256:'3d6df5ec096a5713866943a67d9f88bba3fc6287458d0ea2f616bd41e42db150',
  approved_bundle_size:223692800,
  approval_reference:'CF-1.3.46-1247-20261119-22a8a873-d60d63ba',
  active_release_id:'clientflow-1.3.44-seq-1245',pilot_client_id:3,
  github_artifact_approval_pinned:true,
  render_store_publication_verified:false,active_catalog_promoted:false,
  physical_pilot_accepted:false,deployment_authorized:false,
  fleet_authorized:false,fresh_install_authorized:false,database_cutover_authorized:false,
};

test('1247 source approval is pinned but cannot be inferred as deployment permission',()=>{
  assert.equal(validateStagedPilotCandidate(base,base.active_release_id),base);
  const promoted={...base,active_catalog_promoted:true};
  assert.equal(validateStagedPilotCandidate(promoted,base.active_release_id),promoted);
  for(const field of ['approved_bundle_sha256','source_commit','approved_bundle_size','approval_reference',
    'version','sequence','pilot_client_id','active_release_id']){
    assert.throws(()=>validateStagedPilotCandidate({...base,[field]:field==='approved_bundle_size'?1:'wrong'},base.active_release_id));
  }
  for(const field of ['fleet_authorized','fresh_install_authorized','deployment_authorized','physical_pilot_accepted',
    'render_store_publication_verified','database_cutover_authorized']){
    assert.throws(()=>validateStagedPilotCandidate({...base,[field]:true},base.active_release_id));
  }
});

test('UI only exposes 1247 after exact staged catalog and retains reauthentication',()=>{
  const root=new URL('../src/pages/adminpages/',import.meta.url);
  const panel=fs.readFileSync(new URL('ClientFlowPilot1247Panel.jsx',root),'utf8');
  const old=fs.readFileSync(new URL('ClientFlowPilot1246Panel.jsx',root),'utf8');
  const admin=fs.readFileSync(new URL('ClientFlowReleaseAdministration.jsx',root),'utf8');
  assert.match(panel,/release-pilot-1247\/authorize/);
  assert.match(panel,/new Set\(\["1\.3\.45"\]\)/);
  assert.match(panel,/candidate\?\.release_id !== RELEASE_ID/);
  assert.match(panel,/confirmed_single_pilot: true/);
  assert.match(panel,/Genbekræft superadministratorens adgangskode/);
  assert.match(panel,/device\?\.name === "Viborg1"/);
  assert.match(old,/candidate\?\.release_id !== RELEASE_ID/);
  assert.match(admin,/<ClientFlowPilot1247Panel status=\{status\} onAuthorized=\{refresh\}/);
  assert.doesNotMatch(panel,/setInterval|setTimeout|useEffect\(/);
});
