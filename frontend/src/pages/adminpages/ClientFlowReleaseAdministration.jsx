import React from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, Paper,
  Stack, TextField, Typography,
} from "@mui/material";
import client from "../../api/client";
import AdminRefreshButton from "../../components/AdminRefreshButton";

const RELEASE_PATH = "/api/clientflow/release-administration";

function formatDate(value) {
  if (!value) return "–";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("da-DK") : "–";
}

/** Safe phase-A console; draft authorizations are inert until a reviewed cutover. */
export default function ClientFlowReleaseAdministration() {
  const [status, setStatus] = React.useState(null);
  const [error, setError] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [kind, setKind] = React.useState("pilot");
  const [clientIds, setClientIds] = React.useState("3");
  const [reason, setReason] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [expiry, setExpiry] = React.useState("24");
  const controllerRef = React.useRef(null);

  const refresh = React.useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const { data } = await client.get(RELEASE_PATH, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!data || data.phase !== "additive_draft_only" || data.authorization_active !== false) {
        throw new Error("Ukendt releaseadministrationskontrakt – adgang er lukket");
      }
      setStatus(data);
      setError("");
    } catch (err) {
      if (controller.signal.aborted || err?.name === "AbortError") return;
      setStatus(null);
      setError(err?.message || "Releaseadministrationen kunne ikke hentes");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  const createDraft = async (event) => {
    event.preventDefault();
    if (!status || submitting) return;
    const ids = clientIds.split(",").map((s) => Number(s.trim()));
    if (!ids.length || ids.some((v) => !Number.isSafeInteger(v) || v <= 0) || new Set(ids).size !== ids.length || ids.length > 25) {
      setError("Indtast 1–25 entydige positive klient-ID'er adskilt med komma");
      return;
    }
    if (kind === "pilot" && (ids.length !== 1 || ids[0] !== 3)) {
      setError("Første pilot er begrænset til Viborg1 (klient-ID 3)");
      return;
    }
    setSubmitting(true);
    setMessage("");
    setError("");
    try {
      await client.post(`${RELEASE_PATH}/drafts`, {
        kind,
        client_ids: ids,
        source_version: "1.3.43",
        reason: reason.trim(),
        expires_in_hours: Number(expiry),
        expected_revision: status.revision,
        password,
      });
      setPassword("");
      setReason("");
      setMessage("Kladde oprettet. Den giver IKKE udrulningstilladelse.");
      await refresh();
    } catch (err) {
      setError(err?.message || "Kunne ikke oprette kladden");
    } finally {
      setSubmitting(false);
    }
  };

  const cancelDraft = async (wave) => {
    if (!password || submitting || !status) {
      setError("Indtast adgangskode for at annullere kladden");
      return;
    }
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      await client.post(`${RELEASE_PATH}/drafts/${encodeURIComponent(wave.id)}/cancel`, {
        expected_revision: wave.revision, password,
      });
      setPassword("");
      setMessage("Kladde annulleret. Ingen installation blev bestilt.");
      await refresh();
    } catch (err) {
      setError(err?.message || "Kunne ikke annullere kladden");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={2}>
      <Paper elevation={0} sx={{ p: 2, borderRadius: 2, bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)" }}>
        <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, flexWrap: "wrap" }}>
          <Box>
            <Typography variant="h5" sx={{ fontWeight: 900 }}>ClientFlow · Releases og udrulning</Typography>
            <Typography sx={{ color: "rgba(203,213,225,0.75)", mt: 0.5 }}>
              Forbered udrulninger i databasen. Kun kladder er tilgængelige indtil den særskilte sikkerhedsgodkendelse.
            </Typography>
          </Box>
          <AdminRefreshButton onClick={() => void refresh()} loading={loading} disabled={submitting} ariaLabel="Opdater ClientFlow releaseadministration" />
        </Box>
      </Paper>
      {error && <Alert severity="error">{error}</Alert>}
      {message && <Alert severity="success">{message}</Alert>}
      {!status ? (loading ? <CircularProgress aria-label="Henter releaseadministration" /> : <Alert severity="error">Releaseadministration ikke verificeret – ingen handlinger er tilladt.</Alert>) : (
        <>
          <Alert severity="warning">Fase A: Alle klientopdateringer, nyinstallationer og pilotgodkendelser bruger fortsat eksisterende spærrer. En kladde starter aldrig en installation.</Alert>
          <Paper elevation={0} sx={{ p: 2, borderRadius: 2, bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)" }}>
            <Stack spacing={1.3}>
              <Typography fontWeight={900}>Én fælles stabil version</Typography>
              <Typography variant="h4" fontWeight={900}>{status.stable_version} <Typography component="span" variant="body2">/ 1245</Typography></Typography>
              <Typography sx={{ fontFamily: "monospace", overflowWrap: "anywhere", fontSize: 12 }}>{status.bundle_sha256}</Typography>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip label="Nyinstallation: suspenderet" color="warning" variant="outlined" />
                <Chip label="Fleet: spærret" color="warning" variant="outlined" />
                <Chip label="Fysisk pilot: afventer" color="warning" variant="outlined" />
                <Chip label="DB-cutover: ikke aktiveret" variant="outlined" />
              </Stack>
            </Stack>
          </Paper>
          <Paper elevation={0} sx={{ p: 2, borderRadius: 2, bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)" }}>
            <Box component="form" onSubmit={createDraft}>
              <Stack spacing={1.6}>
                <Typography variant="h6" fontWeight={900}>Opret udrulningskladde</Typography>
                <TextField select SelectProps={{ native: true }} label="Type" value={kind} onChange={(event) => { setKind(event.target.value); if (event.target.value === "pilot") setClientIds("3"); }}>
                  <option value="pilot">Fysisk pilot (kun Viborg1)</option>
                  <option value="controlled">Kontrolleret bølge (planlægning)</option>
                </TextField>
                <TextField required label="Klient-ID'er, adskilt med komma" value={clientIds} onChange={(event) => setClientIds(event.target.value)} helperText="Højst 25. Pilot: præcis klient 3." />
                <TextField label="Kildeversion" value="1.3.43" disabled />
                <TextField select SelectProps={{ native: true }} label="Kladde udløber efter" value={expiry} onChange={(event) => setExpiry(event.target.value)}>
                  <option value="1">1 time</option><option value="24">24 timer</option><option value="72">3 dage</option><option value="168">7 dage</option>
                </TextField>
                <TextField required multiline minRows={2} label="Begrundelse" value={reason} onChange={(event) => setReason(event.target.value)} inputProps={{ maxLength: 500 }} />
                <TextField required type="password" label="Genbekræft adgangskode" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
                <Button type="submit" variant="contained" disabled={submitting || reason.trim().length < 12 || !password}>
                  {submitting ? "Gemmer …" : "Gem kladde – starter ingen installation"}
                </Button>
              </Stack>
            </Box>
          </Paper>
          <Paper elevation={0} sx={{ p: 2, borderRadius: 2, bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)" }}>
            <Typography variant="h6" fontWeight={900}>Seneste kladder og historik</Typography>
            <Divider sx={{ my: 1.5, borderColor: "rgba(148,163,184,0.22)" }} />
            {!status.waves.length && <Typography sx={{ color: "text.secondary" }}>Ingen kladder registreret.</Typography>}
            <Stack spacing={1.5}>
              {status.waves.map((wave) => (
                <Box key={wave.id} sx={{ display: "flex", gap: 1.5, flexWrap: "wrap", justifyContent: "space-between" }}>
                  <Box>
                    <Typography fontWeight={800}>{wave.kind === "pilot" ? "Pilot" : "Bølge"} · {wave.client_ids.join(", ")}</Typography>
                    <Typography variant="body2" color="text.secondary">{wave.source_version} → 1.3.44 · Udløb: {formatDate(wave.expires_at)}</Typography>
                    <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>{wave.reason}</Typography>
                  </Box>
                  <Stack spacing={1} alignItems="flex-end">
                    <Chip label={wave.state === "draft" ? "Kun kladde" : wave.state} size="small" />
                    {wave.state === "draft" && <Button disabled={submitting} size="small" color="warning" onClick={() => void cancelDraft(wave)}>Annuller kladde</Button>}
                  </Stack>
                </Box>
              ))}
            </Stack>
          </Paper>
        </>
      )}
    </Stack>
  );
}
