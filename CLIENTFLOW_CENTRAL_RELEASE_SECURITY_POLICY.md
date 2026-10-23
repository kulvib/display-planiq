# PlanIQ Display – central release security admission (phase 1)

This phase is a **backend-only admission gate**, not end-to-end manual rollback authorization.

The canonical code-reviewed file `backend/service1/clientflow_release_security_policy.json`
contains `revision`, `minimum_safe_release_sequence`, and `revoked_release_ids`.
The loader validates its schema and rejects malformed/missing policies. Policy changes
must be committed, reviewed, and deployed through normal CI; editing the runtime
file on Render is not an approved procedure. No environment variable overrides exist.

Enforcement points:
- Creating an update order or resolving the default fresh-install target.
- Minting an enrollment bootstrap authorization, downloading a fresh-install
  artifact using an existing authorization, and consuming its initial claim.
  Already-committed receipt resume is exempt to avoid orphaning an installed client.
- Minting an artifact access token and validating an already-issued token for download.
- Transitioning a staged deployment into activation; a target newly blocked after
  staging cannot be newly activated through the canonical update API.

Existing local releases, immutable approved bundle bytes and historical deployment
results remain untouched. An in-flight activation that already crossed the
activation-start boundary is **not retroactively halted**, because that would risk
an unsafe halfway release swap. A policy edit requires a controlled backend deploy.

**Explicit limitations:** A root-triggered manual rollback on the device remains
local and is not authorized by this policy. There is no signed rollback permit,
no enforced offline freshness, no centralized manual rollback audit, and no
client-side revocation enforcement in this phase. Do not treat central admission
as fleet-wide downgrade safety. To protect local rollback, a separate signed
permit/revocation protocol, key provisioning, authenticated client identity,
revocation freshness and break-glass strategy must be designed and physically tested
before broad deployment. Do not promote 1.3.40 or enable global updater rollout.

For emergency revocation: commit a revision increase and the exact release ID,
run all GitHub CI checks, deploy backend, verify new downloads/activation
orders are denied, and separately assess already-installed and offline clients.
For emergency minimum-floor increase: avoid blocking the currently sole stable
fresh-install release until a replacement is immutably approved and deployable.
