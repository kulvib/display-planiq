import React, { useCallback, useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, MenuItem,
  Paper, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import TroubleshootIcon from "@mui/icons-material/Troubleshoot";
import client from "../../api/client";
import AdminRefreshButton from "../../components/AdminRefreshButton";

const paper = {
  p: { xs: 1.5, md: 2 },
  borderRadius: 2,
  color: "#f8fafc",
  border: "1px solid rgba(148,163,184,0.20)",
  background: "rgba(15,23,42,0.76)",
};

const TIMELINE = {
  opened: "Fejl observeret",
  reboot_observed: "Ny opstart observeret (ikke en løsning)",
  recovered: "Ny fejlfri rapport observeret",
};
const statusLabel = (row) => row.resolved_at
  ? "Observeret løst"
  : row.verification === "stale" ? "Aktiv · ikke aktuelt bekræftet" : "Aktiv fejl";
const dateText = (date) => date ? new Date(date).toLocaleString("da-DK") : "—";

export default function OperationalIncidents() {
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [clientId, setClientId] = useState("");
  const [page, setPage] = useState(0);
  const [result, setResult] = useState({ items: [], total: 0 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [events, setEvents] = useState({});
  const [operations, setOperations] = useState([]);
  const [operationError, setOperationError] = useState("");
  const [coverage, setCoverage] = useState(null);
  const [coverageError, setCoverageError] = useState("");
  const [detailsError, setDetailsError] = useState("");

  const reload = useCallback(() => setRefreshKey((key) => key + 1), []);
  useEffect(() => {
    const timer = window.setInterval(reload, 60_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({ status, limit: "50", offset: String(page * 50) });
    if (severity) params.set("severity", severity);
    if (/^[1-9]\d*$/.test(clientId.trim())) params.set("client_id", clientId.trim());
    client.get(`/api/superadmin/operational-incidents?${params}`, { signal: abort.signal, headers: { "Cache-Control": "no-cache" } })
      .then(({ data }) => { if (!abort.signal.aborted) { setResult(data); setError(""); } })
      .catch((err) => { if (!abort.signal.aborted) setError(err.response?.data?.detail || "Fejlhistorikken kunne ikke hentes."); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [status, severity, clientId, page, refreshKey]);

  useEffect(() => {
    const abort = new AbortController();
    client.get("/api/superadmin/operational-incidents/report-coverage", { signal: abort.signal })
      .then(({ data }) => { if (!abort.signal.aborted) { setCoverage(data); setCoverageError(""); } })
      .catch(() => { if (!abort.signal.aborted) { setCoverage(null); setCoverageError("Rapportdækningen kunne ikke hentes."); } });
    return () => abort.abort();
  }, [refreshKey]);

  useEffect(() => {
    const abort = new AbortController();
    client.get("/api/superadmin/operational-incidents/operation-outcomes", { signal: abort.signal })
      .then(({ data }) => { if (!abort.signal.aborted) { setOperations(data.items || []); setOperationError(""); } })
      .catch(() => { if (!abort.signal.aborted) setOperationError("Opdaterings- og rollbackhistorik kunne ikke hentes."); });
    return () => abort.abort();
  }, [refreshKey]);

  async function toggleTimeline(id) {
    if (events[id]) { setEvents((old) => ({ ...old, [id]: null })); return; }
    setDetailsError("");
    try {
      const { data } = await client.get(`/api/superadmin/operational-incidents/${encodeURIComponent(id)}/events`, {
        headers: { "Cache-Control": "no-cache" },
      });
      setEvents((old) => ({ ...old, [id]: data.items || [] }));
    } catch {
      setDetailsError("Hændelserne kunne ikke hentes. Prøv igen.");
    }
  }

  const change = (setter) => (event) => { setter(event.target.value); setPage(0); };

  return (
    <Stack spacing={2}>
      <Paper sx={paper}>
        <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, flexWrap: "wrap" }}>
          <Box sx={{ minWidth: 0, flex: "1 1 280px" }}>
            <Typography variant="h5" fontWeight={900} display="flex" gap={1} alignItems="center">
              <TroubleshootIcon /> Driftsfejl og genopretning
            </Typography>
            <Typography variant="body2" sx={{ color: "#cbd5e1", mt: 0.8 }}>
              Historik over verificerede fejlrapporter fra Status, Display og System. En genstart løser aldrig automatisk en fejl.
            </Typography>
          </Box>
          <AdminRefreshButton
            onClick={reload}
            loading={loading}
            ariaLabel="Opdater driftsfejl"
          />
        </Box>
        <Divider sx={{ my: 2, borderColor: "rgba(148,163,184,.17)" }} />
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
          <TextField size="small" select label="Status" value={status} onChange={change(setStatus)} sx={{ minWidth: 185 }}>
            <MenuItem value="active">Aktive fejl</MenuItem>
            <MenuItem value="resolved">Observeret løst</MenuItem>
            <MenuItem value="all">Alle forløb</MenuItem>
          </TextField>
          <TextField size="small" select label="Alvorlighed" value={severity} onChange={change(setSeverity)} sx={{ minWidth: 175 }}>
            <MenuItem value="">Alle</MenuItem>
            <MenuItem value="error">Fejl</MenuItem>
            <MenuItem value="critical">Kritisk</MenuItem>
          </TextField>
          <TextField size="small" label="Klient-ID" value={clientId} onChange={change(setClientId)} placeholder="Alle klienter" />
        </Stack>
      </Paper>
      <Paper sx={paper}>
        <Typography fontWeight={800} mb={0.7}>Dækning af klientrapporter</Typography>
        <Typography variant="body2" sx={{ color: "#cbd5e1", mb: 1.5 }}>
          Viser modtagne rapporter fra godkendte klienter (frisk: højst 180 sekunder).
          Manglende rapporter er ikke i sig selv en registreret fejl. Denne kontrol beviser ikke, at fejldetektorens baggrundsscanner kører.
        </Typography>
        {coverageError && <Alert severity="warning">{coverageError}</Alert>}
        {coverage && <>
          <Typography variant="body2" sx={{ mb: 1 }}>
            Godkendte klienter: <strong>{coverage.approved_clients}</strong>
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {(coverage.domains || []).map((domain) => <Chip
              key={domain.domain}
              color={!coverage.approved_clients || domain.missing || domain.stale ? "warning" : "success"}
              variant="outlined"
              label={`${domain.domain}: ${domain.fresh} friske · ${domain.stale} forsinkede · ${domain.missing} mangler`}
            />)}
          </Stack>
        </>}
      </Paper>
      {error && <Alert severity="error">{error}</Alert>}
      {detailsError && <Alert severity="warning">{detailsError}</Alert>}
      <Paper sx={paper}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" mb={1.5}>
          <Typography fontWeight={800}>Fejlforløb ({result.total ?? 0})</Typography>
          {loading && <CircularProgress size={18} aria-label="Henter fejlhistorik" />}
        </Stack>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" aria-label="Driftsfejlhistorik">
            <TableHead><TableRow>
              <TableCell>Klient og organisation</TableCell>
              <TableCell>Fejl og område</TableCell>
              <TableCell>Alvorlighed</TableCell>
              <TableCell>Først observeret</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Historik</TableCell>
            </TableRow></TableHead>
            <TableBody>
              {result.items?.map((row) => (
                <React.Fragment key={row.id}>
                  <TableRow>
                    <TableCell>{row.client_name} (#{row.client_id})<Typography variant="caption" display="block" sx={{ color: "#cbd5e1" }}>{row.organization_name || "Ingen organisation"}</Typography></TableCell>
                    <TableCell>{row.title}<Typography variant="caption" display="block" sx={{ color: "#cbd5e1" }}>{row.domain}</Typography></TableCell>
                    <TableCell><Chip size="small" label={row.severity === "critical" ? "Kritisk" : "Fejl"} color={row.severity === "critical" ? "error" : "warning"} /></TableCell>
                    <TableCell>{dateText(row.started_at)}</TableCell>
                    <TableCell><Chip size="small" variant="outlined" color={row.resolved_at ? "success" : row.verification === "stale" ? "warning" : "error"} label={statusLabel(row)} />
                      {row.resolved_at && <Typography display="block" variant="caption" sx={{ mt: 0.5, color: "#cbd5e1" }}>{dateText(row.resolved_at)}</Typography>}
                    </TableCell>
                    <TableCell><Button size="small" onClick={() => toggleTimeline(row.id)}>{events[row.id] ? "Skjul" : "Vis"}</Button></TableCell>
                  </TableRow>
                  {events[row.id] && <TableRow><TableCell colSpan={6}>
                    <Typography fontWeight={700} mb={1}>Tidslinje</Typography>
                    {events[row.id].map((event, index) => <Typography key={`${event.observed_at}-${index}`} variant="body2" sx={{ mb: 0.6 }}>
                      {dateText(event.observed_at)} – {TIMELINE[event.kind] || "Systemhændelse"}
                    </Typography>)}
                    {row.resolution_evidence === "healthy_after_reboot" && <Alert severity="info" sx={{ mt: 1 }}>Fejlen blev observeret løst efter en genstart. Det dokumenterer ikke, at genstarten var årsagen.</Alert>}
                  </TableCell></TableRow>}
                </React.Fragment>
              ))}
              {!loading && !result.items?.length && <TableRow><TableCell colSpan={6}>Ingen registrerede fejlforløb med disse filtre. Historikken starter ved aktivering af denne funktion.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </TableContainer>
        <Stack direction="row" justifyContent="flex-end" alignItems="center" spacing={2} mt={2}>
          <Typography variant="caption" sx={{ color: "#cbd5e1" }}>Side {page + 1}</Typography>
          <Button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>Forrige</Button>
          <Button disabled={(page + 1) * 50 >= (result.total || 0)} onClick={() => setPage((p) => p + 1)}>Næste</Button>
        </Stack>
      </Paper>
      <Paper sx={paper}>
        <Typography variant="h6" fontWeight={900}>ClientFlow-opdateringer og signerede rollbacks</Typography>
        <Typography variant="body2" sx={{ color: "#cbd5e1", mt: 0.7, mb: 1.5 }}>
          Seneste afsluttede handlinger fra den eksisterende autoritative hændelsesjournal (90 dage).
          En senere vellykket handling ophæver ikke automatisk en tidligere registreret fejl.
        </Typography>
        {operationError && <Alert severity="warning">{operationError}</Alert>}
        <TableContainer><Table size="small" aria-label="Opdaterings- og rollbackhistorik">
          <TableHead><TableRow><TableCell>Klient</TableCell><TableCell>Handling</TableCell><TableCell>Resultat</TableCell><TableCell>Modtaget</TableCell></TableRow></TableHead>
          <TableBody>
            {operations.map((row) => <TableRow key={`${row.category}:${row.id}`}>
              <TableCell>{row.client_name} (#{row.client_id})</TableCell>
              <TableCell>{row.category === "signed_rollback" ? "Signeret rollback" : "ClientFlow-opdatering"}</TableCell>
              <TableCell><Chip size="small" color={row.outcome === "succeeded" ? "success" : row.outcome === "rolled_back" ? "warning" : "error"} label={row.outcome === "succeeded" ? "Gennemført" : row.outcome === "rolled_back" ? "Tilbageført" : "Fejl"} /></TableCell>
              <TableCell>{dateText(row.occurred_at)}</TableCell>
            </TableRow>)}
            {!operations.length && <TableRow><TableCell colSpan={4}>Ingen afsluttede handlinger i de seneste 90 dage.</TableCell></TableRow>}
          </TableBody>
        </Table></TableContainer>
      </Paper>
    </Stack>
  );
}
