# 68N-B4 – closed 1252 transition preparation

Base: green unsigned candidate source 11d9af69539bb921b1f8488d682c6508323cc798. Current approved standard and physical client remain 1251, revision 3. No new artifact approval or route, deployment grant, migration, catalog rebind, real backup, deletion or runtime client change in this stage.

## Observation and recovery contract

The existing state machine validates a success target but historically does not bind the predecessor or automatic rollback event payload to an exact successor. The 1252-only constraint checks the complete target identity and client 3 (no downgrade), the previous release on success and the failed/restored identities on rollback. A terminal rollback requires exactly one matching start event under the same authenticated update credential. Identical event retries remain idempotent; altered candidate payloads are refused. This validates reported provenance, not physical health, an approved artifact or independent acceptance. Historical release events are unchanged.

## Three-release policy

The non-executable planner accepts only the pinned closed 1251 catalog and revision 3 with all interlocks closed and the exact pinned current inventory 1248/1250/1251. It proposes a 3→2→3 sequence: independently recover and hash-check the external 1248 archive, verify the live store and its dependencies under the reviewed operator lock, remove only 1248 using the separately authorized existing prune contract, then publish the exact reviewed 1252 artifact. Retain 1250 and 1251 throughout. The plan does not check remote bytes, claim external recovery, or authorize removal/publication. Never perform a destructive step to test the plan. Recovery profile 1251-r3 remains unchanged.

## Critical controller-version boundary

`client/systemd/clientflow-update-controller.service` starts the launcher under /opt/clientflow/active; `client/libexec/update-controller` resolves that symlink once and executes its own runtime Python and release/lib. During the first 1251→1252 activation the running process therefore comes from 1251, even after the symlink has switched. Do not claim that a physical failure before or during this first activation proves the new 1252 journal implementation. Do not modify the approved 1251 artifact or run unreviewed root code to inject a failure.

Required next proof: verify reproducible candidate bytes, executable Ubuntu candidate contracts, and exercise the candidate's actual transaction library in isolated test roots with deterministic failures. Physical pilot must prove 1251→1252 transition, reboot, exact successful provenance and original credentials. A failure during that transition can prove predecessor recovery, not the new controller's future update behavior. An independent real-host test of the new transaction implementation requires a separately reviewed bounded test arrangement after 1252 is active (or an isolated representative host); it must not be conflated with a successful upgrade or require fabricating a deployment. No test arrangement or physical authority is provided by this PR.

## Admission plan (not wired)

The current closed-standard RD admission requires latest completed 1251 provenance and is deliberately not changed. Before an artifact-bound pilot can be ordered, a separate reviewed backend-only change must pin exact approved 1252 bytes/source/reference and validate the 1251 predecessor, current sole client, fresh canonical presence, exact active update credential, absence of competing authority, recovery preparedness and the exact three-archive store. Only the exact successful 1252 order may support physical-test admission; if recovery to 1251 is claimed, require matching terminal events, fresh 1251 presence, exact earlier succeeded 1251 provenance and independently verified local recovery before restoring admission. Reject active deployment, ambiguous history, arbitrary older version, unacknowledged recovery_failed and revoked credentials. No bypass or fleet-wide admission is staged. No user-facing UI or new polling.

Fresh installation, expanded media/fleet capacity and real offsite backup/restore remain separate outstanding gates. Existing Ubuntu preclaim/platform CI was green at the base but does not prove a new physical installation.
