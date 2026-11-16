PlanIQ DISPLAY 61B-2D + 61B-2E — ONE COHERENT SOURCE PATCH

BASE: display-planiq-main(20261116-154328).zip
COMMIT: 8e197c4df5079d509b98390bcd96e578a9cc1c53
BRANCH: feature/display-61b2de-durable-install-lock-host-screen-20261116

Upload source files at exact relative locations. Do NOT upload unrelated files.
Do NOT change release 1.3.44 / 1245 or open new-install, fleet, pilot, cutover gates.
Run ALL GitHub CI jobs and inspect regression tests before merge.
Render redeploy cannot physically update client runtime.

Includes two combined workstreams: durable cross-plane install lock for canonical
automated operations, plus stable offline host-screen with runtime fallback.
Refer to docs/CLIENTFLOW_61B2DE_DURABLE_INSTALL_LOCK_HOST_SCREEN_20261116.md
for explicit physical pilot STOP gates and remaining manual root recovery scope.
