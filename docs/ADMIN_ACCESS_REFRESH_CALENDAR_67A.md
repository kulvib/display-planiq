# PlanIQ Display 67A: access visibility, aligned refresh headers and calendar selector

Source baseline: `display-planiq-main(20261025-154719).zip` / GitHub main `ce2d021b5d0d120bd0bd60923dcc4c966d70d191`.

## Findings

- **Calendar:** The MUI checkbox had `edge="start"` inside a rounded selected-client card. This adds a negative start margin; the provided screenshot confirms that the checkbox visually protrudes beyond its selected background. The client chooser also used five columns too early for long names.
- **Refresh headers:** The buttons use the same shared MUI `AdminRefreshButton` as Audit-log, but Driftsfejl and Vedligeholdelse used different top-level header composition (and Vedligeholdelse lacked a matching panel). This change brings these headings into the same top-right-aligned panel pattern, without changing callbacks or privileges.
- **Adgang:** The existing superadmin role check in frontend and `GET /api/users/` backend already allows superadmin. The user-reported inaccessibility cannot be attributed to a specific authentication fault from the screenshot (which shows Calendar only). Do **not** relax permissions. The access page now keeps a persistent API error with a retry action, explicit role-status messaging, and a section-scoped render error boundary; the exact runtime root cause must be confirmed using the rendered error / browser API response after deployment.

## Change limitations

Only frontend pages and their tests/documentation are changed. No network/streaming, authentication enforcement, backend, migrations, client runtime, signing keys, or release catalog changes. Calendar selected clients, all-marked bulk toggle, and marked-date saving remain unchanged. The revised selection markup uses a native label/checkbox pair for keyboard/mouse/touch support.

## Acceptance after green CI/deployment

1. Sign in as superadmin; click **Administration → Adgang**, verify users load and that user management still enforces roles; if not, capture persistent error and HTTP status from `/api/users/` (do not share tokens). Test a non-admin cannot gain access.
2. Compare **Audit-log**, **Driftsfejl** and **Vedligeholdelse** Opdater buttons: top-right position, identical appearance and loading behavior, and existing reload semantics.
3. Calendar: select/deselect via checkbox and row text, bulk **Markér alle/Fjern alle**, check focus/keyboard and disabled state; no checkbox outside its rounded row at 320 px through widescreen. Verify schedule save behavior unchanged.
4. Check all similar selection controls. Repository-wide audit found no other `edge="start"` checkboxes in a selected card; other round badges, day indicators and action chips intentionally retain their own shapes.

Passing source tests does not replace browser, role/API, or physical acceptance.
