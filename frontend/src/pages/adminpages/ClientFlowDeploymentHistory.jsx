import * as React from "react";
import { Alert, Box, Button, Chip, Divider, Stack, Typography } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import ScheduleIcon from "@mui/icons-material/Schedule";
import { CANCELLABLE_STATES, DEPLOYMENT_STEPS, deploymentPresentation } from "./clientflowDeploymentHistory.mjs";

function dateLabel(value) {
  if (!value) return "–";
  const raw = String(value);
  const date = new Date(/(?:Z|[+-]\d\d:?\d\d)$/i.test(raw) ? raw : `${raw}Z`);
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleString("da-DK", { timeZone: "Europe/Copenhagen", day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Pure view of canonical backend state. No network calls, timers or synthetic percentages. */
export default function ClientFlowDeploymentHistory({ rows = [], showClient = true, onCancel, busy = false, compact = false }) {
  if (!rows.length) return <Typography color="text.secondary">Ingen ClientFlow-deployments registreret.</Typography>;
  return (
    <Stack spacing={compact ? 1 : 2}>
      {rows.map((item) => {
        const state = deploymentPresentation(item.state);
        if (compact && state.terminal) {
          return <Box key={item.id} sx={{ borderBottom: 1, borderColor: "divider", pb: 1 }}>
            <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
              <Typography fontWeight={750}>{showClient ? `${item.client_name || `Klient #${item.client_id}`} · ` : ""}ClientFlow {item.target_version}</Typography>
              <Chip size="small" color={state.color} label={state.label} variant="outlined" />
              <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>{dateLabel(item.completed_at)}</Typography>
            </Stack>
            {state.color === "error" && <Alert severity="error" sx={{ mt: 1 }}>{item.failure_message || item.failure_code || "Opdateringen fejlede."}</Alert>}
            <Box component="details" sx={{ mt: 0.5, color: "text.secondary", fontSize: "0.8rem" }}>
              <Box component="summary" sx={{ cursor: "pointer", width: "fit-content" }}>Detaljer</Box>
              <Typography variant="caption" display="block">Bestilt {dateLabel(item.requested_at)} · senest ændret {dateLabel(item.state_updated_at)}</Typography>
              <Typography variant="caption" display="block" sx={{ overflowWrap: "anywhere" }}>Deployment-ID: {item.id}{item.observed_release_id ? ` · rapporteret: ${item.observed_release_id}` : ""}</Typography>
            </Box>
          </Box>;
        }
        return (
          <Box key={item.id} sx={{ border: 1, borderColor: "divider", borderRadius: 3, p: { xs: 1.5, sm: 2.5 }, bgcolor: "action.hover" }}>
            <Stack direction="row" spacing={1.25} alignItems="flex-start" useFlexGap flexWrap="wrap">
              {item.state === "succeeded" ? <CheckCircleIcon color="success" sx={{ fontSize: 32 }} /> :
                state.color === "error" ? <ErrorOutlineIcon color="error" sx={{ fontSize: 32 }} /> :
                <ScheduleIcon color={state.color === "warning" ? "warning" : "action"} sx={{ fontSize: 32 }} />}
              <Box sx={{ flex: "1 1 160px", minWidth: 0 }}>
                <Typography variant="h6" fontWeight={850}>ClientFlow {item.target_version}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {[showClient ? item.client_name || `Klient #${item.client_id}` : null, item.target_release_id?.match(/-seq-(\d+)$/)?.[1] ? `Release ${item.target_release_id.match(/-seq-(\d+)$/)[1]}` : null].filter(Boolean).join(" · ")}
                </Typography>
              </Box>
              <Chip size="small" color={state.color} label={state.label} />
              {onCancel && CANCELLABLE_STATES.has(item.state) && (
                <Button size="small" color="warning" disabled={busy} onClick={() => onCancel(item)}>Annullér opdatering</Button>
              )}
            </Stack>
            <Stack direction="row" spacing={0.5} sx={{ my: 2 }} role="group" aria-label="Faktiske deploymenttrin">
              {DEPLOYMENT_STEPS.map((step, index) => {
                const done = state.step === 6 || (state.step >= 0 && index < state.step);
                const active = index === state.step;
                return <Box key={step.state} title={step.label} aria-label={`${step.label}: ${done ? "passeret" : active ? "aktuelt" : "ikke bekræftet"}`}
                  sx={{ flex: 1, height: 8, borderRadius: 999, bgcolor: done ? "success.main" : active ? "info.main" : "action.disabledBackground" }} />;
              })}
            </Stack>
            {state.color === "error" && <Alert severity="error" sx={{ mt: 1 }}>
              {item.failure_message || item.failure_code || "Deploymenten fejlede. Se klientens recoveryhistorik."}
            </Alert>}
            {item.state === "rolling_back" && <Alert severity="warning">Recovery pågår – start ikke en ny deployment.</Alert>}
            <Divider sx={{ my: 1.5 }} />
            <Stack spacing={1}>
              <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={0.5}>
                <Typography color="text.secondary" variant="body2">{item.completed_at ? "Afsluttet" : "Bestilt"}</Typography>
                <Typography fontWeight={750} variant="body2">{dateLabel(item.completed_at || item.requested_at)}</Typography>
              </Stack>
              {item.observed_release_id && <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={0.5}>
                <Typography color="text.secondary" variant="body2">Rapporteret release</Typography>
                <Typography fontWeight={750} variant="body2" sx={{ overflowWrap: "anywhere", minWidth: 0 }}>{item.observed_release_id}</Typography>
              </Stack>}
            </Stack>
            <Box component="details" sx={{ mt: 1, color: "text.secondary", fontSize: "0.8rem" }}>
              <Box component="summary" sx={{ cursor: "pointer", width: "fit-content" }}>Detaljer</Box>
              <Typography variant="caption" display="block">Bestilt {dateLabel(item.requested_at)} · senest ændret {dateLabel(item.state_updated_at)}</Typography>
              <Typography variant="caption" display="block" sx={{ overflowWrap: "anywhere" }}>Deployment-ID: {item.id}</Typography>
            </Box>
          </Box>
        );
      })}
    </Stack>
  );
}
