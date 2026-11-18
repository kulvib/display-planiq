import * as React from "react";
import { Alert, Box, Chip, Divider, Stack, Typography } from "@mui/material";
import { DEPLOYMENT_STEPS, deploymentPresentation } from "./clientflowDeploymentHistory.mjs";

function dateLabel(value) {
  if (!value) return "–";
  const raw = String(value);
  const date = new Date(/(?:Z|[+-]\d\d:?\d\d)$/i.test(raw) ? raw : `${raw}Z`);
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleString("da-DK", { timeZone: "Europe/Copenhagen" });
}

/** Pure view of canonical backend state. No network calls, timers or synthetic percentages. */
export default function ClientFlowDeploymentHistory({ rows = [], showClient = true }) {
  if (!rows.length) return <Typography color="text.secondary">Ingen ClientFlow-deployments registreret.</Typography>;
  return (
    <Stack spacing={2}>
      {rows.map((item) => {
        const state = deploymentPresentation(item.state);
        return (
          <Box key={item.id} sx={{ border: "1px solid rgba(148,163,184,0.2)", borderRadius: 2, p: 1.5 }}>
            <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
              <Typography fontWeight={850}>
                {showClient ? `${item.client_name || `Klient #${item.client_id}`} · ` : ""}ClientFlow {item.target_version}
              </Typography>
              <Chip size="small" color={state.color} label={state.label} variant="outlined" />
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", my: 0.5 }}>
              Bestilt {dateLabel(item.requested_at)} · senest ændret {dateLabel(item.state_updated_at)}
              {item.completed_at ? ` · afsluttet ${dateLabel(item.completed_at)}` : ""}
            </Typography>
            <Stack direction="row" spacing={0.4} sx={{ my: 1 }} role="group" aria-label="Faktiske deploymenttrin">
              {DEPLOYMENT_STEPS.map((step, index) => {
                const done = state.step === 6 || (state.step >= 0 && index < state.step);
                const active = index === state.step;
                return <Box key={step.state} title={step.label} aria-label={`${step.label}: ${done ? "passeret" : active ? "aktuelt" : "ikke bekræftet"}`}
                  sx={{ flex: 1, height: 7, borderRadius: 2, bgcolor: done ? "success.main" : active ? "info.main" : "action.disabledBackground" }} />;
              })}
            </Stack>
            {state.color === "error" && <Alert severity="error" sx={{ mt: 1 }}>
              {item.failure_message || item.failure_code || "Deploymenten fejlede. Se klientens recoveryhistorik."}
            </Alert>}
            {item.state === "rolling_back" && <Alert severity="warning">Recovery pågår – start ikke en ny deployment.</Alert>}
            <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1, overflowWrap: "anywhere" }}>
              Deployment-ID: {item.id}{item.observed_release_id ? ` · rapporteret: ${item.observed_release_id}` : ""}
            </Typography>
          </Box>
        );
      })}
    </Stack>
  );
}
