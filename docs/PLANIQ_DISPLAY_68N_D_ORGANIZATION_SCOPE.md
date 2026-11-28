# 68N-D — reusable organization selection and server-side binding

The operator requested a normal forward-update path for all compatible clients, not a new special Viborg1 pilot per release, plus an organization dropdown.

This preparatory batch reuses the existing standard-order panel and route without changing release authority. It extracts version-independent organization filtering and selected-client binding, includes all/unassigned/specific organization scopes, clears hidden selections on filter changes, checks explicit selected IDs and their organization under existing client row locks and records scope in the audit. The old unscoped request remains compatible. The existing limit of 25 per transaction is explicit; this is not yet a durable multi-batch scheduler or 100-client deployment authorization. The 1250 historical route remains closed on current main; the new reusable selection contract is to be used by the forthcoming general rollout path.

Remaining: release-policy registry and transition, 1252 generic order/activation and authenticated download, recovery/RDP eligibility per client, normal Control Room update, bounded multi-batch orchestration, tests and actual Render storage/physical acceptance. No special 1252 pilot restored, no catalog/control changes or deployment. The PR remains draft; the approved 1252 client bytes stay unchanged.
