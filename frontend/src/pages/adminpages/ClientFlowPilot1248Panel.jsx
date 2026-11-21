import * as React from "react";
import {
  Alert, Box, Button, Checkbox, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, FormControlLabel, Paper, Stack, TextField,
  Typography,
} from "@mui/material";
import client from "../../api/client";

const RELEASE_ID = "clientflow-1.3.47-seq-1248";
const PILOT_API = "/api/clientflow/release-pilot-1248/authorize";
const READY_VERSIONS = new Set(["1.3.46"]);

/** One superadmin-authenticated DB authorization only; physical systemd start is separate. */
export default function ClientFlowPilot1248Panel({ status, onAuthorized }) {
  const [open, setOpen] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [confirmed, setConfirmed] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [authorized, setAuthorized] = React.useState(null);

  const candidate = status?.staged_pilot_candidate;
  const device = status?.available_clients?.find((item) => item.id === 3);
  const alreadyKnown = status?.recent_deployments?.some((row) =>
    row?.client_id === 3 && row?.target_release_id === RELEASE_ID
  ) === true;
  const ready = !alreadyKnown && candidate?.active_catalog_promoted === true &&
    candidate.release_id === RELEASE_ID &&
    candidate.pilot_client_id === 3 &&
    candidate.github_artifact_approval_pinned === true &&
    candidate.deployment_authorized === false &&
    candidate.approved_bundle_sha256 === "9ca8852ba29153f2ec40b58d18007c738a03f9569f14762486fc1953c59eb6ff" &&
    candidate.source_commit === "c0d5a092efe0c4e8638866ad98621481d6f5d0e8" &&
    candidate.approval_reference === "CF-1.3.47-1248-20261121-c0d5a092-f8240014" &&
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
          data?.rollback_authorized !== false || data?.source_version !== "1.3.46" ||
          typeof data?.deployment_id !== "string" ||
          !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(data.deployment_id)) {
        throw new Error("Serverens svar på pilotautorisationen kunne ikke verificeres. Kontroller deploymenthistorikken.");
      }
      setAuthorized(data);
      setOpen(false);
      setPassword("");
      setConfirmed(false);
      await onAuthorized?.();
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "1248-autorisationen kunne ikke verificeres. Kontrollér deploymenthistorikken; forsøg ikke automatisk igen.");
    } finally {
      setPassword("");
      setSubmitting(false);
    }
  };

  if (candidate?.release_id !== RELEASE_ID || candidate?.active_catalog_promoted !== true) return null;

  return (
    <Paper elevation={0} sx={{ p: { xs: 2, md: 2.5 }, borderRadius: 2, border: "1px solid rgba(148,163,184,0.25)", bgcolor: "rgba(15,23,42,0.74)" }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography variant="h6" fontWeight={850}>Fysisk pilot · 1.3.47 / 1248</Typography>
          <Typography variant="body2" color="text.secondary">
            Enkeltstående backendautorisation kun for Viborg1 (ID 3) fra 1.3.46 til 1.3.47.
            Stable 1245 forbliver standard. Ingen fleet, nyinstallation, automatisk updater eller rollback.
          </Typography>
        </Box>
        <Alert severity="warning">
          Autorisationen opretter en faktisk 1248-deployment i databasen, men starter IKKE updater-servicen.
          Det nye deployment-ID skal først bindes til en gennemgået, midlertidig systemd-overstyring.
          Kontrollér fysisk adgang og recoverymulighed før autorisation.
        </Alert>
        <Typography variant="body2">
          Viborg1 · ID 3 · rapporteret version: <strong>{device?.reported_version || "ukendt"}</strong>
        </Typography>
        {!ready && <Alert severity="error">Pilotens katalog, klientidentitet eller versionsgrundlag kan ikke bekræftes i oversigten. Opdater siden. Der kan ikke autoriseres en pilot.</Alert>}
        {authorized && <Alert severity="success">
          Én backend-deployment til 1248 er autoriseret, men updateren er ikke startet. Deployment-ID: <strong>{authorized.deployment_id}</strong>.
          Verificér UUID i databasen før det fysiske handoff. Forsøg ikke automatisk igen.
        </Alert>}
        <Box>
          <Button variant="contained" color="warning" disabled={!ready || submitting || Boolean(authorized)}
            onClick={() => { setError(""); setPassword(""); setConfirmed(false); setOpen(true); }}>
            Autoriser 1248 i backend – start ikke updater
          </Button>
        </Box>
      </Stack>
      <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
        <Box component="form" onSubmit={authorize}>
          <DialogTitle>Backendautorisation – ClientFlow 1248 / Viborg1</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 0.5 }}>
              <Alert severity="warning">Bekræftelsen opretter en rigtig 1248-deployment for Viborg1, ID 3. Den starter ikke systemd-updateren. Ingen automatisk rollback; fysisk aktivering kræver en separat, kontrolleret engangsprocedure.</Alert>
              <Typography variant="body2">Fra {device?.reported_version} til 1.3.47/1248 · kun Viborg1.</Typography>
              <TextField required autoFocus fullWidth multiline minRows={2} label="Begrundelse (mindst 12 tegn)"
                value={reason} onChange={(event) => setReason(event.target.value)} inputProps={{ maxLength: 500 }} />
              <TextField required fullWidth type="password" label="Genbekræft superadministratorens adgangskode"
                autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <FormControlLabel control={<Checkbox checked={confirmed} onChange={(_, checked) => setConfirmed(checked)} />}
                label="Jeg har verificeret Viborg1 og recoverymuligheden og autoriserer kun én backend-deployment, ikke fysisk servicestart." />
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={close} disabled={submitting}>Fortryd</Button>
            <Button type="submit" color="warning" variant="contained"
              disabled={!ready || !confirmed || !password || reason.trim().length < 12 || submitting}>
              {submitting ? <CircularProgress size={18} /> : "Autoriser én backend-deployment"}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
    </Paper>
  );
}
