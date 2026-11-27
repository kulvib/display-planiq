# PlanIQ Display – 68J-8 professional quality review

Date: 2026-11-27. Reviewed baseline: main `6b2e2091064986f4141cb7033d99bbcdd4d6cece`, PR 441, CI run [46015156520](https://github.com/kulvib/display-planiq/actions/runs/46015156520). Both active Render services were live on that commit when checked. Scope: repository checksum inventory (970 entries before this tranche), selected critical sources, nine manifest-listed workflows, previous physical acceptance and a short read-only Render sample. This is not a full-file security certification, accessibility audit or a fleet load test.

## Decisions and changes in this tranche

- README and Blueprint comments distinguish actual Docker/local PostgreSQL from historical external-database infrastructure. Blueprint resource configuration is unchanged; do not apply either Blueprint to the live workspace.
- All seven previously mutable action references in the nine inventoried workflows are pinned to resolved upstream v4 commit SHAs. Existing v4 major versions are retained; no dependency upgrade implied.
- CI checkout credentials are disabled where unnecessary. Historic PR 411 integration authority remains scoped and unchanged.
- FreeRDP compile recipe is intentionally **not** reapproved. Previously approved recipe hash remains `8abeb743dba723f5dba1e00fb2a498703ca904a72a4a667050950ef710b393e6`; pending pinned recipe hash is `ee2d166fc21f366119374da9698d003ddc3c7f4fb3ac694184646c57b6fc547d`. Full build and Chromium proof are required; compare rebuilt JS/WASM/provenance with checked-in bytes before any fast-path reapproval. Different bytes require separate review and explicit integration. The negative tests prove the former exact recipe can be reused only with exact assets and that the new recipe forces a build.
- No changes to application runtime, physical client, release identity, catalog, credentials, permissions, database or Render settings.

## Evidence and risk register

| Priority | Finding | Evidence / next acceptance |
| --- | --- | --- |
| Release gate | 1251 requires exact artifact-bound native RDP successor authorization and recovery | Candidate-stage document; preserve 1250. Build, approve and physically verify before publication. |
| High | Single-node persistent storage is a shared failure domain | Startup script and Docker topology; CI fixture restore is not a live-data off-host restore. Define recovery objectives, verify an encrypted independent backup and isolated restore without copying production data to CI. No backup retention change in this tranche. |
| High | Redeploy interrupts requests | Read-only Render sample, 13:31–14:31 UTC (14:31–15:31 Copenhagen); 5-minute buckets, one physical client, redeploys included. HTTP 502 occurred in two buckets (50 and 55); HTTP 500 in those buckets (3 and 2). Correlation is not causal proof. Review sanitized logs and reconnect behavior; do not promise zero downtime on this topology. |
| Medium | Resource headroom with one client | Render sample peak of reported 5-minute average CPU points 0.0571 CPU against 0.5 limit (~11.4%); memory point max 188.9 MB against 536.9 MB (~35.2%). Not an instantaneous peak or 100-client sizing proof. Aggregate HTTP latency mixes intentional long waits and other traffic; use route-specific measurement. |
| Medium | Workflow supply chain | Seven mutable Actions tags pinned in this tranche; container base image tags and package-install provenance still require separate verified digest review. Do not silently bless a modified build recipe. |
| Medium | Maintainability | clients.py and ClientDetailsInfoSection.jsx exceed 3500 lines; Livestream section ~2957. File size is a signal, not a bug. Extract cohesive responsibilities with characterization tests, not blanket rewrites of working media/control code. |
| Medium | Future compatibility | Node module-type warnings, Uvicorn legacy WebSocket deprecation, SQLite adapter warnings in CI. Audit CommonJS/ESM usage before changing package type; prove WSS/HTTPS/Terminal/Livestream on actual client before changing transport implementation. |
| Medium | UI quality | PR 441 shared theme and target filtering, CI 476 tests passed. Browser acceptance of revised UI, mobile and keyboard navigation remain open; physical 68J-6 passed on the preceding build. |
| Medium | Fleet performance | Earlier PR 441 backend CI reported 100 synthetic clients, 2200 requests, zero errors and p95 279.65 ms. Isolated control traffic, not 100 simultaneous video streams. Preserve existing DB/realtime budgets; use realistic mixed workloads and bounded media concurrency before capacity certification. |
| Medium | Repository organization | Historical release/decommission evidence is retained deliberately and checked by tests. Build a clear index; remove or relocate only after tracing manifest and test references. |
| Medium | Auth and access | Existing JWT/session/role controls and isolated runtime credentials need a targeted authorization matrix and session/revocation review. CI dependency scans are not proof that all security flaws are absent. Common identity work remains a separate integration decision. |

## Exit gates

1. All applicable CI, full FreeRDP build and Chromium proof, and single-node smoke/isolated restore pass. Verify rebuilt artifact bytes before reauthorizing reuse. Retain the old checked-in browser assets unless separately accepted.
2. Operator accepts shared UI from PR 441 (desktop/mobile, keyboard, Livestream text, update selector, media and Terminal).
3. Review the remaining risk register with measured evidence; do not refactor or modify live environment only to silence warnings.
4. Only then freeze the exact successor source for the canonical 1251 build and implement/verify the scoped pilot authorization. One physical client, Viborg1, remains the test authority.

Historical evidence, backups and external logs are not covered by the completed old-client database purge.

## 68J-8B – pinned recipe proof and acceptance update

PR 442 head `b9bbf3eb696a704e8859f0f37204962e7f487f20`: canonical CI [46016976737](https://github.com/kulvib/display-planiq/actions/runs/46016976737), single-node smoke [46016976666](https://github.com/kulvib/display-planiq/actions/runs/46016976666) and full WASM workflow [46016976607](https://github.com/kulvib/display-planiq/actions/runs/46016976607) all completed successfully. Compile log reports 146/146 native tests. Chromium log reports PINNED_WASM_BROWSER_WEBSOCKET_PROOF=PASS, 1280×800 monitor, outgoing upgrade and no browser errors. The isolated probe intentionally has no live RDP server; physical media control is not proven by this test.

| File | Rebuilt SHA-256 from compile log | Bytes |
| --- | --- | ---: |
| sdl-freerdp.js | `c7d0a7e20a7b6473c5743892086b00dfb096807b8386adf992ab294867ad8112` | 269234 |
| sdl-freerdp.wasm | `f5cfa907421b47c3ed6acdee329f5ebda7e9279c4a5972e02139dc8e2fe6f315` | 11086426 |

Both hashes and byte counts exactly match checked-in provenance. The ZIP digest reported by upload and Chromium download also matches the artifact metadata: `7763f883774598e891d76ca11960f5fe10a0cada40b10fc50ac9702512c8ce40`. Verified from GitHub logs and repository provenance, not a local independent download/extraction. No asset, source or provenance JSON replacement is made. The approved recipe hash is now `ee2d166fc21f366119374da9698d003ddc3c7f4fb3ac694184646c57b6fc547d`; the previous recipe and any drift require a rebuild. The next PR CI must pass and the browser proof must run with the pinned repository bytes before merge.

68J-7 operator acceptance: seven of eight points passed, no failures. Desktop panel hierarchy, selector, text removal, Remote Desktop, Livestream, Terminal/files accepted. Mobile not tested; keyboard accessibility remains open. Production backup/restore, authorization matrix, transport-deprecation work and full fleet workload proof remain open. No release 1251 approval.
