import * as React from "react";
import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, Stack, TextField } from "@mui/material";
import client from "../../api/client";

export default function ClientFlow1252RestorationPanel({ status, onVerified }) {
  const row = status.recent_deployments?.[0];
  const device = status.available_clients?.[0];
  const ready = status.stable_release_id === "clientflow-1.4.1-seq-1251" && status.revision === 3 &&
    status.candidate_1252_review_available === true && status.client_inventory_complete === true &&
    status.available_clients?.length === 1 && device?.id === 3 && device.reported_version === "1.4.1" &&
    status.active_deployments_complete === true && status.active_deployments?.length === 0 &&
    row?.client_id === 3 && row.target_release_id === "clientflow-1.4.2-seq-1252" &&
    ["failed", "cancelled", "rolled_back"].includes(row.state);
  const [open, setOpen] = React.useState(false);
  const [confirmed, setConfirmed] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [verified, setVerified] = React.useState(false);
  const request = React.useRef(null);
  React.useEffect(() => () => request.current?.abort(), []);
  const close = () => { if (!busy) {setOpen(false);setPassword("");setConfirmed(false);} };
  const submit = async event => {
    event.preventDefault();
    if (!ready || !confirmed || !password || busy || verified || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);setMessage("");
    const body = {deployment_id:row.id,confirmed_local_recovery:true,password};
    setPassword("");
    try {
      const {data} = await client.post("/api/clientflow/standard-deployments/candidate-1252/verify-restoration",body,{signal:controller.signal});
      if (data?.deployment_id !== row.id || data.restored_version !== "1.4.1" || data.operator_attestation !== true)
        throw new Error("Resultatet kunne ikke verificeres.");
      if (!controller.signal.aborted) {setVerified(true);setMessage("Lokal genoprettelse registreret. Remote Desktop kontrollerer fortsat backendbeviserne.");}
    } catch (error) {
      if (!controller.signal.aborted) setMessage((error?.message || "Kontrollen blev afvist.") + " Kontrollér historikken før nyt forsøg.");
    } finally {
      body.password = "";
      request.current = null;
      if (!controller.signal.aborted) {setBusy(false);setOpen(false);setConfirmed(false);await onVerified?.();}
    }
  };
  if (!ready) return null;
  return <Alert severity={verified?"success":"warning"} action={<Button color="inherit" disabled={busy||verified} onClick={()=>setOpen(true)}>Verificér lokal genoprettelse</Button>}>
    {message || "1252 blev ikke gennemført. Genetablering af Remote Desktop kræver fysisk kontrol af 1251."}
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <form onSubmit={submit}>
        <DialogTitle>Bekræft genoprettet ClientFlow 1.4.1</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{mt:1}}>
          <Alert severity="warning">Kontrollér lokalt aktiv release-ID og symlink, ingen uafsluttet activation intent, NeedDaemonReload=no, raske tjenester og normal kioskdrift. Dette er en operatørattestation, ikke automatisk recovery eller nedgradering.</Alert>
          <FormControlLabel control={<Checkbox checked={confirmed} onChange={(_,checked)=>setConfirmed(checked)} disabled={busy}/>} label="Jeg har verificeret alle punkter fysisk på Viborg1."/>
          <TextField type="password" autoComplete="current-password" label="Genbekræft din adgangskode" value={password} onChange={e=>setPassword(e.target.value)} disabled={busy}/>
        </Stack></DialogContent>
        <DialogActions><Button onClick={close} disabled={busy}>Annullér</Button><Button type="submit" disabled={!ready||!confirmed||!password||busy}>Registrér kontrol</Button></DialogActions>
      </form>
    </Dialog>
  </Alert>;
}
