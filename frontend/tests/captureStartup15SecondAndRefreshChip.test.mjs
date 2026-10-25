import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const overview = read('src/pages/adminpages/LivestreamOverview.jsx');
const controlRoom = read('src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx');
const incidents = read('src/pages/adminpages/OperationalIncidents.jsx');

test('Livestream overview warns at 15 seconds without delaying startup or stopping the producer', () => {
  assert.match(overview, /HEALTH_STARTUP_WARNING_MS\s*=\s*15_000/);
  assert.match(overview, /window\.setTimeout\(\(\) =>\s*\{[\s\S]*?startupWarned = true;[\s\S]*?\}, HEALTH_STARTUP_WARNING_MS\)/);
  assert.match(overview, /void heartbeat\(\)/);
  assert.match(overview, /window\.clearTimeout\(startupWarning\)/);
  assert.match(overview, /health\?\.has_segments && !health\?\.is_stale/);
  assert.doesNotMatch(overview, /\/api\/livestream-v2\/clients\/\$\{client\.id\}\/command/);
});

test('Control Room surfaces 15-second warning while continuing to observe stream state', () => {
  assert.match(controlRoom, /HEALTH_STARTUP_WARNING_MS\s*=\s*15_000/);
  assert.match(controlRoom, /setStartupWarningVisible\(true\)/);
  assert.match(controlRoom, /window\.clearTimeout\(timer\)/);
  assert.match(controlRoom, /startupWarningVisible && !manifestReady/);
  assert.match(controlRoom, /Livestream er endnu ikke klar/);
  assert.match(controlRoom, /setStartupWarningVisible\(false\)/);
  assert.doesNotMatch(controlRoom, /HEALTH_STARTUP_POLL_MS\s*=\s*15_000/);
});

test('Driftsfejl Opdater is an accessible clickable compact chip', () => {
  assert.match(incidents, /compactDarkChipSx/);
  assert.match(incidents, /<Chip\s+label="Opdater"/);
  assert.match(incidents, /clickable\s+onClick=\{reload\}/);
  assert.match(incidents, /disabled=\{loading\}/);
  assert.match(incidents, /aria-label="Opdater driftsfejl"/);
  assert.doesNotMatch(incidents, /<Button startIcon=\{<RefreshIcon/);
});
