import * as React from "react";
import { Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import client from "../../api/client";
import { BASELINE_ID, BASELINE_VERSION, MAX_ORDER_CLIENTS, eligibleOrderClients, prepareOrderTargets, validateOrderAvailability, verifyOrderResult } from "./clientflowStandardOrders.mjs";

const ORDER_PATH = "/api/clientflow/standard-deployments";

export default function ClientFlowStandardOrderPanel({status, onAuthorized}) {
  const [query, setQuery] = React.useState("");
  const [organization, setOrganization] = React.useState("all");
  const [selected, setSelected] = React.useState([]);
  const [intent, setIntent] = React.useState(null);
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [message, setMessage] = React.useState("");
  const request = React.useRef(null);
  const mounted = React.useRef(false);
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; request.current?.abort(); };
  }, []);
  const eligible = React.useMemo(() => eligibleOrderClients(status), [status]);
  const ids = React.useMemo(() => new Set(eligible.map((row) => row.id)), [eligible]);
  React.useEffect(() => {
    setSelected((previous) => previous.filter((id) => ids.has(id)));
  }, [ids]);
  const organizations = React.useMemo(() => {
    const groups = new Map();
    for (const row of eligible) {
      const key = String(row.organization_id ?? "none");
      groups.set(key, row.organization_name || (key === "none" ? "Ingen organisation" : "Organisation #" + key));
    }
    return [...groups].sort((a,b) => a[1].localeCompare(b[1], "da"));
  }, [eligible]);
  const filtered = eligible.filter((row) => (
    (organization === "all" || String(row.organization_id ?? "none") === organization) &&
    [row.name, row.id, row.locality, row.organization_name].filter(Boolean).join(" ").toLocaleLowerCase("da").includes(query.trim().toLocaleLowerCase("da"))
  ));
  const allowed = status.standard_order_review_available === true && status.active_deployments_complete === true;
  const toggle = (id) => setSelected((previous) => previous.includes(id) ? previous.filter((value) => value !== id) :
    previous.length < MAX_ORDER_CLIENTS && ids.has(id) ? [...previous,id] : previous);
  const close = () => { if (!busy) {setIntent(null);setPassword("");} };
  const review = async () => {
    if (busy || request.current || !allowed) return;
    let targets;
    try { targets = prepareOrderTargets(status, selected); }
    catch (err) {setError(err.message);return;}
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);setError("");setMessage("");
    try {
      const {data} = await client.get(ORDER_PATH + "/availability", {signal:controller.signal});
      const authority = validateOrderAvailability(data);
      if (!mounted.current || controller.signal.aborted) return;
      setIntent({authority, targets, names:targets.map((target)=>eligible.find((row)=>row.id===target.client_id)?.name || "#" + target.client_id)});
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError(err?.message || "Kunne ikke kontrollere releaseautorisation");
    } finally {
      if (request.current === controller) request.current = null;
      if (mounted.current) setBusy(false);
    }
  };
  const confirm = async (event) => {
    event.preventDefault();
    if (busy || request.current || !intent || !password || !allowed) return;
    let targets;
    try {
      targets = prepareOrderTargets(status, intent.targets.map((row)=>row.client_id));
      if (JSON.stringify(targets)!==JSON.stringify(intent.targets)) throw new Error("Klientvalget er ændret");
    } catch (err) {setError(err.message);setIntent(null);setPassword("");return;}
    const controller = new AbortController();
    request.current = controller;
    const body = {target_release_id:BASELINE_ID, expected_bundle_sha256:intent.authority.bundle_sha256,
      expected_revision:intent.authority.revision, targets, confirmed:true, password};
    setPassword("");setBusy(true);setError("");
    try {
      const {data} = await client.post(ORDER_PATH, body, {signal:controller.signal});
      verifyOrderResult(data, targets);
      if (!mounted.current || controller.signal.aborted) return;
      setSelected([]);setMessage(targets.length + " opdatering(er) bestilt. Følg den faktiske status nedenfor.");
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError((err?.message || "Bestillingens resultat er ukendt") + " Hent status før et nyt forsøg.");
    } finally {
      body.password = "";
      if (request.current === controller) request.current = null;
      if (mounted.current) {
        setIntent(null);setBusy(false);
        // A request interrupted after commit is not safe to retry blindly.
        await onAuthorized?.();
      }
    }
  };
  return <Paper elevation={0} sx={{p:{xs:2,md:2.5},borderRadius:2,bgcolor:"rgba(15,23,42,0.74)",border:"1px solid rgba(148,163,184,0.16)"}}>
    <Stack spacing={2}>
      <Typography variant="h6" fontWeight={850}>Installer standardrelease</Typography>
      <Typography color="text.secondary">Vælg klienter enkeltvis eller efter organisation. Backend kontrollerer den præcise releasepakke, online-version og samtidige opdateringer inden bestilling.</Typography>
      {!allowed && <Alert severity="warning">Udrulning er lukket, eller klientstatus er ufuldstændig. Ingen installation kan bestilles.</Alert>}
      <Stack direction={{xs:"column",sm:"row"}} gap={1.5}>
        <TextField fullWidth size="small" label="Søg klient" value={query} onChange={(event)=>setQuery(event.target.value)} />
        <TextField select size="small" label="Organisation" value={organization} onChange={(event)=>setOrganization(event.target.value)} sx={{minWidth:200}}>
          <MenuItem value="all">Alle organisationer</MenuItem>
          {organizations.map(([key,name])=><MenuItem key={key} value={key}>{name}</MenuItem>)}
        </TextField>
      </Stack>
      <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
        <Chip label={selected.length + " / " + MAX_ORDER_CLIENTS + " valgt"} />
        <Button size="small" disabled={!allowed || busy || selected.length>=MAX_ORDER_CLIENTS || !filtered.length}
          onClick={()=>setSelected((previous)=>[...new Set([...previous,...filtered.map((row)=>row.id)])].slice(0,MAX_ORDER_CLIENTS))}>Vælg fra søgning</Button>
        <Button size="small" disabled={busy || !selected.length} onClick={()=>setSelected([])}>Ryd valg</Button>
      </Stack>
      <Box sx={{maxHeight:340,overflowY:"auto",border:1,borderColor:"divider",borderRadius:2}}>
        {filtered.map((row)=><Box key={row.id} component="label" sx={{display:"flex",alignItems:"center",gap:1,p:1,borderBottom:1,borderColor:"divider"}}>
          <Checkbox checked={selected.includes(row.id)} disabled={!allowed || busy || (!selected.includes(row.id) && selected.length>=MAX_ORDER_CLIENTS)}
            onChange={()=>toggle(row.id)} inputProps={{"aria-label":"Vælg " + row.name}}/>
          <Box sx={{minWidth:0}}><Typography fontWeight={750}>{row.name}</Typography>
            <Typography variant="caption" color="text.secondary">{[row.organization_name,row.locality,"v"+row.reported_version].filter(Boolean).join(" · ")}</Typography></Box>
        </Box>)}
        {!filtered.length && <Typography sx={{p:2}} color="text.secondary">Ingen kompatible klienter i visningen.</Typography>}
      </Box>
      <Typography variant="caption" color="text.secondary">1.4.0 er den nye baseline. Der er ingen tidligere godkendt 1.4-version at vælge til manuel rollback.</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {message && <Alert severity="success">{message}</Alert>}
      <Button variant="contained" disabled={!allowed || busy || !selected.length} onClick={review}>Gennemgå installation af ClientFlow {BASELINE_VERSION}</Button>
    </Stack>
    <Dialog open={Boolean(intent)} onClose={close} fullWidth maxWidth="sm">
      <Box component="form" onSubmit={confirm}>
        <DialogTitle>Bekræft ClientFlow-opdatering</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{mb:2}}>Kioskbrowseren kan blive lukket, og klienterne genstarter under opdateringen.</Alert>
          <Typography fontWeight={750}>{intent?.targets.length || 0} klienter → {BASELINE_VERSION}</Typography>
          <Typography sx={{mb:2}} color="text.secondary">{intent?.names.join(", ")}</Typography>
          <TextField autoFocus fullWidth type="password" autoComplete="current-password" label="Genbekræft din adgangskode" value={password}
            onChange={(event)=>setPassword(event.target.value)} disabled={busy} />
        </DialogContent>
        <DialogActions><Button disabled={busy} onClick={close}>Tilbage</Button>
          <Button type="submit" variant="contained" disabled={!allowed || !password || busy}>Bestil opdatering</Button></DialogActions>
      </Box>
    </Dialog>
  </Paper>;
}
