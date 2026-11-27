import * as React from "react";
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControlLabel, Paper, Stack, TextField,
  Typography,
} from "@mui/material";
import client from "../../api/client";

const RELEASE_ID = "clientflow-1.3.45-seq-1246";
const PILOT_API = "/api/clientflow/release-pilot-1246/authorize";
const READY_VERSIONS = new Set(["1.3.43", "1.3.44"]);

/** One explicit physical pilot. The legacy multi-client planning UI stays inert. */
export default function ClientFlowPilot1246Panel({ status, onAuthorized }) {
  const [open, setOpen] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [confirmed, setConfirmed] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [authorized, setAuthorized] = React.useState(null);

  const candidate = status?.staged_pilot_candidate;
  const device = status?.available_clients?.find((item) => item.id === 3);
  const ready = candidate?.active_catalog_promoted === true &&
    candidate.release_id === RELEASE_ID &&
    candidate.pilot_client_id === 3 &&
    candidate.github_artifact_approval_pinned === true &&
    candidate.deployment_authorized === false &&
    status?.fresh_install_open === false &&
    status?.fleet_open === false &&
    status?.cutover_enabled === false &&
    device?.name === "Viborg1" &&
    READY_VERSIONS.has(device.reported_version) &&
    Number.isSafeInteger(status?.revision) && status.revision >= 1;

  const close = () => {
    if (submitting) return;
    setOpen(false);
    setPassword("");
    setConfirmed(false);
    setError("");
  };
  const authorize = async (event) => {
    event.preventDefault();
    if (!ready || !confirmed || reason.trim().length < 12 || !password || submitting || authorized) return;
    setSubmitting(true);
    setError("");
    try {
      const { data } = await client.post(PILOT_API, {
        client_id: 3,
        target_release_id: RELEASE_ID,
        expected_current_version: device.reported_version,
        expected_policy_revision: status.revision,
        reason: reason.trim(), password,
        confirmed_single_pilot: true,
      });
      if (data?.client_id !== 3 || data?.target_release_id !== RELEASE_ID ||
          data?.state !== "authorized" || data?.fleet_authorized !== false ||
          data?.rollback_authorized !== false || !data?.deployment_id) {
        throw new Error("Serverens svar på pilotautorisationen kunne ikke verificeres. Kontroller deploymenthistorikken.");
      }
      setAuthorized(data);
      setOpen(false);
      setPassword("");
      setConfirmed(false);
      await onAuthorized?.();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "Pilotautorisationen kunne ikke gennemføres");
    } finally {
      setSubmitting(false);
    }
  };

  if (candidate?.release_id !== RELEASE_ID || candidate?.active_catalog_promoted !== true) return null;

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, md: 2.5 }, borderRadius: 2, border: "1px solid rgba(148,163,184,0.30)", bgcolor: "rgba(15,23,42,0.74)" }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography variant="h6" fontWeight={850}>Fysisk pilot · 1.3.45 / 1246</Typography>
          <Typography variant="body2" color="text.secondary">
            Databaseautoriseret pilot kun for Viborg1 (ID 3). Stable 1245 forbliver standard.
            Ingen ændring i Render Environment, nyinstallation, fleet eller rollback.
          </Typography>
        </Box>
        <Alert severity="warning">
          Dette er en faktisk opdateringshandling, ikke en inaktiv plan. Når den autoriseres,
          kan Viborg1 begynde at hente og installere 1246. Kontrollér først fysisk adgang og recoverymulighed.
        </Alert>
        <Typography variant="body2">
          Viborg1 · ID 3 · rapporteret version: <strong>{device?.reported_version || "ukendt"}</strong>
        </Typography>
        {!ready && <Alert severity="error">Pilotens katalog, klientidentitet eller versionsgrundlag kan ikke bekræftes i oversigten. Opdater siden. Der kan ikke autoriseres en pilot.</Alert>}
        {authorized && <Alert severity="success">
          Én pilotdeployment er bestilt til Viborg1. Deployment-ID: <strong>{authorized.deployment_id}</strong>.
          Følg opdaterings- og recoveryhistorikken. Denne pilot kan ikke bestilles igen fra panelet.
        </Alert>}
        <Box>
          <Button variant="contained" color="warning" disabled={!ready || submitting || Boolean(authorized)}
            onClick={() => { setError(""); setPassword(""); setConfirmed(false); setOpen(true); }}>
            Autoriser og start pilot på Viborg1
          </Button>
        </Box>
      </Stack>
      <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
        <Box component="form" onSubmit={authorize}>
          <DialogTitle>Endelig godkendelse – ClientFlow 1246</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 0.5 }}>
              <Alert severity="warning">Bekræftelsen opretter en rigtig deployment til Viborg1, ID 3, og klienten kan påbegynde installationen. Der er ingen automatisk rollback.</Alert>
              <Typography variant="body2">Fra {device?.reported_version} til 1.3.45/1246 · kun Viborg1.</Typography>
              <TextField required autoFocus fullWidth multiline minRows={2} label="Begrundelse (mindst 12 tegn)"
                value={reason} onChange={(event) => setReason(event.target.value)} inputProps={{ maxLength: 500 }} />
              <TextField required fullWidth type="password" label="Genbekræft superadministratorens adgangskode"
                autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <FormControlLabel control={<Checkbox checked={confirmed} onChange={(_, checked) => setConfirmed(checked)} />}
                label="Jeg har verificeret Viborg1 og recoverymuligheden og ønsker at starte netop denne pilot." />
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={close} disabled={submitting}>Fortryd</Button>
            <Button type="submit" color="warning" variant="contained"
              disabled={!ready || !confirmed || !password || reason.trim().length < 12 || submitting}>
              {submitting ? <CircularProgress size={18} /> : "Autoriser og start pilot"}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
    </Paper>
  );
}
