import * as React from "react";
import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Paper, Stack, TextField, Typography } from "@mui/material";
import client from "../../api/client";
const SUCCESSOR_ID = "clientflow-1.4.1-seq-1251";
const BUNDLE_SHA256 = "835610b0a59510b2119601468ad47c0aa1fb418b96c4cfaaa8cdd81042dc1ab6";

const PATH = "/api/clientflow/standard-deployments/successor-pilot";

function validateAuthority(value, revision) {
  if (value?.available !== true || value.client_id !== 3 ||
      value.target_release_id !== SUCCESSOR_ID || value.source_version !== "1.4.0" ||
      value.bundle_sha256 !== BUNDLE_SHA256 ||
      !Number.isSafeInteger(revision) || revision < 1 || value.revision !== revision ||
      value.fleet_authorized !== false || value.fresh_install_authorized !== false ||
      value.rollback_authorized !== false) {
    throw new Error(value?.available === false ? "Pilot afventer godkendt releasepakke og verificeret klientstatus." : "Pilotautorisation kunne ikke verificeres.");
  }
  return value;
}

export default function ClientFlowSuccessorPilotPanel({ status, onAuthorized }) {
  const [authority, setAuthority] = React.useState(null);
  const [password, setPassword] = React.useState("");
  const [prepared, setPrepared] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [ordered, setOrdered] = React.useState(false);
  const pending = React.useRef(null);
  const mounted = React.useRef(false);
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; pending.current?.abort(); pending.current = null; };
  }, []);
  const device = status.available_clients?.find((row) => row.id === 3);
  const ready = status.phase === "standard_baseline" && status.successor_pilot_review_available === true &&
    status.available_clients?.length === 1 && status.active_deployments_complete === true &&
    status.active_deployments?.length === 0 && status.cutover_enabled === false &&
    status.fleet_open === false && status.fresh_install_open === false &&
    device?.name === "Viborg1" && device.reported_version === "1.4.0" &&
    Number.isSafeInteger(status.revision) && status.revision >= 1;
  const close = () => { if (!busy) {setAuthority(null);setPassword("");setPrepared(false);} };
  const review = async () => {
    if (!ready || busy || pending.current || ordered) return;
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);setError("");setPassword("");setPrepared(false);
    try {
      const {data} = await client.get(PATH + "/availability", {signal:controller.signal});
      const verified = validateAuthority(data, status.revision);
      if (mounted.current && !controller.signal.aborted) setAuthority(verified);
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError(err?.message || "Pilotstatus kunne ikke kontrolleres.");
    } finally {
      if (pending.current === controller) pending.current = null;
      if (mounted.current) setBusy(false);
    }
  };
  const confirm = async (event) => {
    event.preventDefault();
    if (!ready || !authority || authority.revision !== status.revision || !prepared || !password || busy || pending.current || ordered) return;
    const controller = new AbortController();
    pending.current = controller;
    const body = {client_id:3,target_release_id:SUCCESSOR_ID,expected_source_version:"1.4.0",
      expected_bundle_sha256:authority.bundle_sha256,expected_revision:authority.revision,
      confirmed_prepared:true,password};
    setPassword("");setBusy(true);setError("");
    try {
      const {data} = await client.post(PATH + "/authorize", body, {signal:controller.signal});
      if (data?.client_id !== 3 || data.target_release_id !== SUCCESSOR_ID || data.state !== "authorized" ||
          data.fleet_authorized !== false || data.fresh_install_authorized !== false || data.rollback_authorized !== false ||
          !/^[0-9a-f]{36}$/i.test(data.deployment_id || "")) {
        throw new Error("Resultatet kunne ikke verificeres.");
      }
      if (mounted.current && !controller.signal.aborted) setOrdered(true);
    } catch (err) {
      if (mounted.current && !controller.signal.aborted) setError((err?.message || "Pilotbestillingens resultat er ukendt.") + " Kontrollér deploymenthistorikken inden et nyt forsøg.");
    } finally {
      body.password = "";
      if (pending.current === controller) pending.current = null;
      if (mounted.current) {
        setAuthority(null);setPrepared(false);setBusy(false);
        await onAuthorized?.();
      }
    }
  };
  return <Paper elevation={0} sx={{p:{xs:2,md:2.5},borderRadius:2,bgcolor:"rgba(15,23,42,0.74)",border:"1px solid rgba(148,163,184,0.30)"}}>
    <Stack spacing={1.5}>
      <Typography variant="h6" fontWeight={850}>ClientFlow 1.4.1 · fysisk accept</Typography>
      <Typography color="text.secondary">Engangstest af 1251 på Viborg1. 1250 bevares til installationsrecovery. De tre eksakte releasepakker på Render og den lukkede releasepolitik verificeres før bestilling.</Typography>
      {!ready && <Alert severity="info">Afventer Viborg1 på 1.4.0 og lukket releasepolitik.</Alert>}
      {error && <Alert severity="warning">{error}</Alert>}
      {ordered && <Alert severity="success">Pilot bestilt. Følg deploymentstatus og gennemfør fysisk accept efter genstart.</Alert>}
      <Button variant="outlined" disabled={!ready || busy || ordered} onClick={review}>Kontrollér 1.4.1-pilot</Button>
    </Stack>
    <Dialog open={Boolean(authority)} onClose={close} fullWidth maxWidth="sm">
      <Box component="form" onSubmit={confirm}>
        <DialogTitle>Installer 1.4.1 på Viborg1</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{mt:1}}>
            <Alert severity="warning">Dette bestiller en reel engangsopdatering og kan genstarte Viborg1. Automatisk installationsrecovery er ikke det samme som en godkendt manuel nedgradering.</Alert>
            <FormControlLabel control={<Checkbox checked={prepared} onChange={(_,checked)=>setPrepared(checked)} disabled={busy}/>}
              label="Jeg har fysisk adgang, afsluttet den verificerede lokale forberedelse og kontrolleret recoverymuligheden."/>
            <TextField fullWidth type="password" autoComplete="current-password" label="Genbekræft din adgangskode" value={password}
              onChange={(event)=>setPassword(event.target.value)} disabled={busy}/>
          </Stack>
        </DialogContent>
        <DialogActions><Button disabled={busy} onClick={close}>Annullér</Button>
          <Button type="submit" variant="contained" color="warning" disabled={!ready || authority?.revision!==status.revision || !prepared || !password || busy}>Bestil engangspilot</Button></DialogActions>
      </Box>
    </Dialog>
  </Paper>;
}
