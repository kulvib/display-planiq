import * as React from "react";
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Dialog,
  DialogActions, DialogContent, DialogTitle, Divider, MenuItem, Paper,
  Stack, TextField, Typography,
} from "@mui/material";
import client from "../../api/client";
import AdminRefreshButton from "../../components/AdminRefreshButton";
import {
  MAX_PLAN_CLIENTS, planVersionGroups, preparePlan,
  validateReleasePlanningResponse,
} from "./clientflowReleasePlan.mjs";

const RELEASE_PATH = "/api/clientflow/release-administration";
const panelSx = {
  p: { xs: 2, md: 2.5 }, borderRadius: 2,
  bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)",
};
const ACTIONS = {
  review: { label: "Gennemgå plan", message: "Planen er gennemgået. Ingen installation er autoriseret." },
  pause: { label: "Sæt planen på pause", message: "Planen er pauset. Ingen installation kan starte." },
  resume: { label: "Genoptag planlægningen", message: "Planlægningen er genoptaget. Ingen installation er autoriseret." },
  cancel: { label: "Annullér planen", message: "Planen er annulleret. Ingen installation blev bestilt." },
};

function formatDate(value) {
  if (!value) return "–";
  const iso = String(value);
  const parsed = new Date(/(?:Z|[+-]\d\d:\d\d)$/i.test(iso) ? iso : `${iso}Z`);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString("da-DK") : "–";
}

function clientLabel(value) {
  return [value.name, value.locality].filter(Boolean).join(" · ");
}

/** Deliberately INERT planning UI. No release approval, client update or rollback API is invoked. */
export default function ClientFlowReleaseAdministration() {
  const [status, setStatus] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [sourceVersion, setSourceVersion] = React.useState("");
  const [selectedIds, setSelectedIds] = React.useState([]);
  const [query, setQuery] = React.useState("");
  const [organization, setOrganization] = React.useState("all");
  const [visibleCount, setVisibleCount] = React.useState(40);
  const [expiry, setExpiry] = React.useState("24");
  const [intent, setIntent] = React.useState(null);
  const [password, setPassword] = React.useState("");
  const [dialogError, setDialogError] = React.useState("");
  const controllerRef = React.useRef(null);

  const refresh = React.useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    try {
      const { data } = await client.get(RELEASE_PATH, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const checked = validateReleasePlanningResponse(data);
      setStatus(checked);
      setError("");
      const groups = planVersionGroups(checked.available_clients, checked.stable_version);
      setSourceVersion((previous) => groups.some((g) => g.version === previous) ? previous : (groups[0]?.version || ""));
      setSelectedIds((previous) => previous.filter((id) => checked.available_clients.some(
        (value) => value.id === id && value.reported_version !== checked.stable_version,
      )));
    } catch (err) {
      if (controller.signal.aborted || err?.name === "AbortError") return;
      setStatus(null); // Any unavailable or unexpected policy is a HARD STOP.
      setError(err?.message || "Releaseadministrationen kunne ikke hentes");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  const available = status?.available_clients || [];
  const groups = React.useMemo(() => planVersionGroups(available, status?.stable_version), [available, status?.stable_version]);
  const candidates = React.useMemo(() => available.filter((value) => value.reported_version === sourceVersion), [available, sourceVersion]);
  const organizations = React.useMemo(() => [...new Set(candidates.map(
    (value) => value.organization_name || `Organisation #${value.organization_id ?? "ukendt"}`,
  ))].sort((a, b) => a.localeCompare(b, "da")), [candidates]);
  const filtered = React.useMemo(() => candidates.filter((value) => {
    const org = value.organization_name || `Organisation #${value.organization_id ?? "ukendt"}`;
    const haystack = `${value.name} ${value.locality || ""} ${value.id} ${org}`.toLocaleLowerCase("da");
    return (organization === "all" || org === organization) && haystack.includes(query.trim().toLocaleLowerCase("da"));
  }), [candidates, organization, query]);
  const selectedSet = React.useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedClients = selectedIds.map((id) => available.find((value) => value.id === id)).filter(Boolean);
  const allVisibleSelected = filtered.length > 0 && filtered.every((value) => selectedSet.has(value.id));
  const unknownCount = available.filter((value) => !value.reported_version).length;
  const release = status?.available_releases[0];
  const seq = status?.stable_release_id?.match(/-seq-(\d+)$/)?.[1] || "–";

  const changeVersion = (value) => {
    setSourceVersion(value);
    setSelectedIds([]);
    setQuery("");
    setOrganization("all");
    setVisibleCount(40);
    setMessage("");
  };
  const toggleClient = (id) => {
    setError("");
    setSelectedIds((previous) => previous.includes(id)
      ? previous.filter((item) => item !== id)
      : previous.length < MAX_PLAN_CLIENTS ? [...previous, id] : previous);
  };
  const toggleVisible = () => {
    setError("");
    if (allVisibleSelected) {
      const remove = new Set(filtered.map((value) => value.id));
      setSelectedIds((previous) => previous.filter((id) => !remove.has(id)));
    } else {
      setSelectedIds((previous) => [...new Set([
        ...previous, ...filtered.map((value) => value.id),
      ])].slice(0, MAX_PLAN_CLIENTS));
    }
  };

  const openCreateDialog = () => {
    if (!status || submitting) return;
    try {
      preparePlan(available, selectedIds, sourceVersion, status.stable_version, expiry);
      setError("");
      setDialogError("");
      setPassword("");
      setIntent({ action: "create" });
    } catch (err) { setError(err.message); }
  };
  const openPlanDialog = (wave, action) => {
    if (!status || submitting || !ACTIONS[action]) return;
    setDialogError("");
    setPassword("");
    setIntent({ action, wave });
  };
  const closeDialog = () => {
    if (submitting) return;
    setIntent(null);
    setPassword("");
    setDialogError("");
  };
  const confirmAction = async (event) => {
    event.preventDefault();
    if (!status || submitting || !intent || !password) return;
    setSubmitting(true);
    setDialogError("");
    setMessage("");
    try {
      if (intent.action === "create") {
        const data = preparePlan(available, selectedIds, sourceVersion, status.stable_version, expiry);
        await client.post(`${RELEASE_PATH}/drafts`, {
          ...data, expected_revision: status.revision, password,
        });
        setMessage("Inaktiv plan gemt. Ingen klientopdatering er bestilt eller startet.");
        setSelectedIds([]);
      } else {
        const action = intent.action;
        await client.post(`${RELEASE_PATH}/drafts/${encodeURIComponent(intent.wave.id)}/${action}`, {
          expected_revision: intent.wave.revision, password,
        });
        setMessage(ACTIONS[action].message);
      }
      setIntent(null);
      setPassword("");
      await refresh();
    } catch (err) {
      setDialogError(err?.message || "Handlingen kunne ikke gennemføres");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Stack spacing={2.2}>
      <Paper elevation={0} sx={panelSx}>
        <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} justifyContent="space-between" spacing={2}>
          <Box>
            <Typography variant="h5" fontWeight={900}>ClientFlow · Releases</Typography>
            <Typography color="text.secondary" sx={{ mt: 0.5 }}>
              Overblik over godkendte releases og klienter. Planlæg i grupper uden at starte installationer.
            </Typography>
          </Box>
          <AdminRefreshButton onClick={() => void refresh()} loading={loading} disabled={submitting} ariaLabel="Opdater ClientFlow releaseadministration" />
        </Stack>
      </Paper>
      {error && <Alert severity="error">{error}</Alert>}
      {message && <Alert severity="success">{message}</Alert>}
      {!status ? (loading ? <Box sx={{ p: 3 }}><CircularProgress aria-label="Henter releaseadministration" /></Box>
        : <Alert severity="error">Release- og klientdata er ikke verificeret. Alle handlinger er spærret.</Alert>) : (
        <>
          <Alert severity="info">
            <strong>Planlægning – ikke udrulning.</strong> Ingen handling på denne side godkender, installerer eller tilbageruller en release.
            Fysisk pilot, nyinstallation, fleet og DB-cutover er fortsat spærret.
          </Alert>
          <Paper elevation={0} sx={panelSx}>
            <Stack spacing={1.4}>
              <Typography variant="h6" fontWeight={850}>1. Release og sikkerhedsstatus</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Eneste godkendte stabile release</Typography>
                  <Typography variant="h4" fontWeight={900}>{release?.version} <Typography component="span" variant="body2">/ {seq}</Typography></Typography>
                  <Typography variant="caption" sx={{ fontFamily: "monospace", overflowWrap: "anywhere", color: "text.secondary" }}>SHA256: {release?.bundle_sha256}</Typography>
                </Box>
                <Box>
                  <Typography fontWeight={750}>Hvad kan jeg gøre her?</Typography>
                  <Typography variant="body2" color="text.secondary">Vælge registrerede klienter, oprette og gennemgå planer. Usignerede kildekandidater er ikke installationsklare releases.</Typography>
                </Box>
              </Box>
              <Stack direction="row" flexWrap="wrap" useFlexGap gap={1}>
                <Chip size="small" color="warning" variant="outlined" label="Nyinstallation: lukket" />
                <Chip size="small" color="warning" variant="outlined" label="Flere klienter: udrulning lukket" />
                <Chip size="small" color="warning" variant="outlined" label="Fysisk pilot: afventer" />
                <Chip size="small" variant="outlined" label="DB-cutover: lukket" />
              </Stack>
            </Stack>
          </Paper>
          <Paper elevation={0} sx={panelSx}>
            <Stack spacing={2}>
              <Box>
                <Typography variant="h6" fontWeight={850}>2. Vælg release og klienter</Typography>
                <Typography variant="body2" color="text.secondary">Klienternes versioner er senest rapporterede værdier, ikke en live-godkendelse. Kontroller dem igen før en senere fysisk udrulning.</Typography>
              </Box>
              <TextField select fullWidth label="Planlagt målrelease" value={release?.release_id || ""} disabled helperText="Kun godkendte releases vises. Nye kandidater kommer først efter separat signering og godkendelse.">
                <MenuItem value={release?.release_id}>{release?.version} / {seq} · stabil</MenuItem>
              </TextField>
              <TextField select fullWidth label="Klienternes senest rapporterede version" value={sourceVersion} onChange={(event) => changeVersion(event.target.value)} helperText="Gruppering sikrer, at én plan kun har én kildeversion. Ingen manuel versionsindtastning.">
                {groups.length === 0 && <MenuItem value="" disabled>Ingen kendte, ældre klientversioner</MenuItem>}
                {groups.map((group) => <MenuItem key={group.version} value={group.version}>{group.version} · {group.count} klient(er)</MenuItem>)}
              </TextField>
              {unknownCount > 0 && <Alert severity="warning">{unknownCount} godkendt(e) klient(er) mangler en gyldigt rapporteret version og kan ikke vælges til en plan endnu.</Alert>}
              {groups.length === 0 ? <Alert severity="info">Der er ingen godkendte klienter med en kendt, ældre ClientFlow-version. Opdater klienternes status, og prøv igen.</Alert> : (
                <>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                    <TextField label="Søg efter navn, placering eller klient-ID" value={query} onChange={(event) => { setQuery(event.target.value); setVisibleCount(40); }} fullWidth />
                    <TextField select label="Organisation" value={organization} onChange={(event) => { setOrganization(event.target.value); setVisibleCount(40); }} sx={{ minWidth: { md: 220 } }}>
                      <MenuItem value="all">Alle organisationer</MenuItem>
                      {organizations.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}
                    </TextField>
                  </Stack>
                  <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} gap={1}>
                    <Typography fontWeight={750}>{selectedIds.length} af højst {MAX_PLAN_CLIENTS} valgt · {filtered.length} matcher søgningen</Typography>
                    <Stack direction="row" gap={1}>
                      <Button variant="outlined" size="small" disabled={!filtered.length} onClick={toggleVisible}>{allVisibleSelected ? "Fravælg viste" : "Vælg viste (maks. 25)"}</Button>
                      <Button size="small" onClick={() => setSelectedIds([])} disabled={!selectedIds.length}>Ryd valg</Button>
                    </Stack>
                  </Stack>
                  <Box sx={{ maxHeight: 440, overflowY: "auto", border: "1px solid rgba(148,163,184,0.20)", borderRadius: 2 }}>
                    {filtered.slice(0, visibleCount).map((device) => {
                      const checked = selectedSet.has(device.id);
                      const disabled = !checked && selectedIds.length >= MAX_PLAN_CLIENTS;
                      return (
                        <Box key={device.id} component="label" sx={{ display: "flex", gap: 1.5, alignItems: "center", px: 1.5, py: 1, borderBottom: "1px solid rgba(148,163,184,0.11)", cursor: disabled ? "not-allowed" : "pointer", "&:hover": { bgcolor: "rgba(148,163,184,0.06)" } }}>
                          <Checkbox checked={checked} disabled={disabled} onChange={() => toggleClient(device.id)} inputProps={{ "aria-label": `Vælg ${device.name} (ID ${device.id})` }} />
                          <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Typography fontWeight={750}>{clientLabel(device)} <Typography component="span" variant="caption" color="text.secondary">#{device.id}</Typography></Typography>
                            <Typography variant="caption" color="text.secondary">{device.organization_name || `Organisation #${device.organization_id ?? "ukendt"}`} · v{device.reported_version} · rapporteret {formatDate(device.version_reported_at)}</Typography>
                          </Box>
                        </Box>
                      );
                    })}
                    {filtered.length === 0 && <Typography sx={{ p: 2 }} color="text.secondary">Ingen klienter matcher de valgte filtre.</Typography>}
                  </Box>
                  {visibleCount < filtered.length && <Button variant="outlined" onClick={() => setVisibleCount((previous) => previous + 40)}>Vis flere klienter ({filtered.length - visibleCount} tilbage)</Button>}
                  <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.8 }}>
                    {selectedClients.map((device) => <Chip key={device.id} label={clientLabel(device)} onDelete={() => toggleClient(device.id)} />)}
                  </Box>
                  <Typography variant="body2" color="text.secondary">
                    {selectedIds.length === 1 ? "1 klient → pilotplan" : selectedIds.length > 1 ? `${selectedIds.length} klienter → kontrolleret bølgeplan` : "Vælg klienter for at planlægge."}
                    {" "}Type vælges automatisk. Begrundelse registreres automatisk i auditloggen.
                  </Typography>
                  <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} spacing={2}>
                    <TextField select label="Planens gyldighed" value={expiry} onChange={(event) => setExpiry(event.target.value)} sx={{ minWidth: 185 }}>
                      <MenuItem value="1">1 time</MenuItem><MenuItem value="24">24 timer</MenuItem>
                      <MenuItem value="72">3 dage</MenuItem><MenuItem value="168">7 dage</MenuItem>
                    </TextField>
                    <Button variant="contained" disabled={submitting || loading || !selectedIds.length} onClick={openCreateDialog} sx={{ minHeight: 44 }}>
                      Gennemgå og gem inaktiv plan
                    </Button>
                  </Stack>
                </>
              )}
            </Stack>
          </Paper>
          <Paper elevation={0} sx={panelSx}>
            <Typography variant="h6" fontWeight={850}>3. Udrulning og rollback</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Dette bliver kontrolstedet for pilot, bølgeudrulning og tilbageførsel til tidligere godkendte releases. De nuværende sikkerhedsgates tillader endnu ikke disse handlinger.
            </Typography>
            <Stack direction={{ xs: "column", sm: "row" }} gap={1.5}>
              <Button variant="contained" disabled>Start opdatering til valgte klienter · spærret</Button>
              <Button color="warning" variant="outlined" disabled>Rollback til valgte klienter · spærret</Button>
              <Button variant="outlined" disabled>Installer på nye klienter · spærret</Button>
            </Stack>
            <Alert severity="warning" sx={{ mt: 2 }}>En plan er aldrig en installationsgodkendelse. Signeret release, særskilt fysisk pilotaccept, klientkontrol og de eksisterende autorisationsgates skal være på plads før udrulning eller rollback.</Alert>
          </Paper>
          <Paper elevation={0} sx={panelSx}>
            <Typography variant="h6" fontWeight={850}>4. Planer og historik</Typography>
            <Divider sx={{ my: 1.5 }} />
            {!status.waves.length && <Typography color="text.secondary">Ingen planer registreret.</Typography>}
            <Stack spacing={1.6}>
              {status.waves.map((wave) => {
                const names = (wave.client_ids || []).map((id) => available.find((c) => c.id === id)?.name || `Klient #${id}`);
                const expired = Number.isFinite(Date.parse(wave.expires_at)) && Date.parse(wave.expires_at) <= Date.now();
                return (
                  <Box key={wave.id} sx={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 1.5, py: 1 }}>
                    <Box sx={{ flex: "1 1 250px" }}>
                      <Typography fontWeight={850}>{wave.kind === "pilot" ? "Pilotplan" : "Bølgeplan"} · {names.join(", ")}</Typography>
                      <Typography variant="body2" color="text.secondary">{wave.source_version} → {release.version} · Udløb {formatDate(wave.expires_at)}</Typography>
                      <Typography variant="caption" color="text.secondary">Revision {wave.revision} · {wave.reviewed_for_planning ? `Gennemgået ${formatDate(wave.reviewed_at)}` : "Ikke gennemgået"} · ingen udrulning autoriseret</Typography>
                    </Box>
                    <Stack direction="row" alignItems="center" flexWrap="wrap" gap={1}>
                      <Chip size="small" label={wave.state === "cancelled" ? "Annulleret" : expired ? "Udløbet" : wave.state === "paused" ? "Pauset" : wave.reviewed_for_planning ? "Gennemgået · inaktiv" : "Kladde"} />
                      {wave.state === "draft" && !wave.reviewed_for_planning && !expired && <Button size="small" disabled={submitting} onClick={() => openPlanDialog(wave, "review")}>Gennemgå</Button>}
                      {wave.state === "draft" && wave.reviewed_for_planning && !expired && <Button size="small" disabled={submitting} onClick={() => openPlanDialog(wave, "pause")}>Pause</Button>}
                      {wave.state === "paused" && !expired && <Button size="small" disabled={submitting} onClick={() => openPlanDialog(wave, "resume")}>Genoptag</Button>}
                      {["draft", "paused"].includes(wave.state) && <Button size="small" color="warning" disabled={submitting} onClick={() => openPlanDialog(wave, "cancel")}>Annullér</Button>}
                    </Stack>
                  </Box>
                );
              })}
            </Stack>
          </Paper>
        </>
      )}
      <Dialog open={Boolean(intent)} onClose={closeDialog} fullWidth maxWidth="sm">
        <Box component="form" onSubmit={confirmAction}>
          <DialogTitle>{intent?.action === "create" ? "Bekræft inaktiv plan" : ACTIONS[intent?.action]?.label}</DialogTitle>
          <DialogContent>
            {intent?.action === "create" && status && (
              <Stack sx={{ mt: 0.5, mb: 2 }} spacing={0.6}>
                <Typography fontWeight={750}>{selectedIds.length} klient(er) · {sourceVersion} → {status.stable_version}</Typography>
                <Typography variant="body2" color="text.secondary">{selectedClients.map(clientLabel).join(", ")}</Typography>
                <Typography variant="body2" color="text.secondary">{selectedIds.length === 1 ? "Pilotplan" : "Kontrolleret bølgeplan"} · udløber om {expiry} time(r)</Typography>
              </Stack>
            )}
            <Alert severity="info" sx={{ mb: 2 }}>Kun administrativ planlægning. Ingen installation, releasegodkendelse eller rollback.</Alert>
            {dialogError && <Alert severity="error" sx={{ mb: 2 }}>{dialogError}</Alert>}
            <TextField autoFocus fullWidth type="password" label="Genbekræft din adgangskode" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </DialogContent>
          <DialogActions>
            <Button onClick={closeDialog} disabled={submitting}>Tilbage</Button>
            <Button type="submit" variant="contained" disabled={!password || submitting}>{submitting ? "Gemmer …" : "Bekræft planhandling"}</Button>
          </DialogActions>
        </Box>
      </Dialog>
    </Stack>
  );
}
