import * as React from "react";
import { Box, Button, Chip, MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { fleetVersionStatus, summarizeReleaseFleet } from "./clientflowReleasePlan.mjs";
import { deploymentPresentation } from "./clientflowDeploymentHistory.mjs";

const STATES = {
  standard: {label:"Matcher standard", color:"success"},
  older: {label:"Ældre version", color:"warning"},
  newer: {label:"Nyere end standard", color:"info"},
  unknown: {label:"Version ukendt", color:"default"},
};
const panel = {p:{xs:2,md:2.5},borderRadius:2,bgcolor:"rgba(15,23,42,0.74)",border:"1px solid rgba(148,163,184,0.16)"};
function dateLabel(value) {
  if (!value) return "–";
  const raw = String(value);
  const date = new Date(/(?:Z|[+-]\d\d:?\d\d)$/i.test(raw) ? raw : `${raw}Z`);
  return Number.isNaN(date.getTime()) ? "–" : date.toLocaleString("da-DK", {timeZone:"Europe/Copenhagen"});
}

/** Read-only inventory, including clients which cannot be selected in a historical wave. */
export default function ClientFlowFleetOverview({clients, release, stableVersion, activeRows, activeComplete}) {
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState("all");
  const [page, setPage] = React.useState(0);
  const counts = React.useMemo(() => summarizeReleaseFleet(clients, stableVersion), [clients, stableVersion]);
  const active = React.useMemo(() => new Map(activeRows.map((row) => [row.client_id, row])), [activeRows]);
  const filtered = React.useMemo(() => clients.filter((row) => {
    const text = [row.name,row.id,row.locality,row.organization_name,row.reported_version].filter((v) => v != null).join(" ").toLocaleLowerCase("da");
    return (filter === "all" || fleetVersionStatus(row, stableVersion) === filter) && text.includes(query.trim().toLocaleLowerCase("da"));
  }), [clients,stableVersion,query,filter]);
  const safePage = Math.min(page, Math.max(0, Math.ceil(filtered.length / 25) - 1));
  return <Paper elevation={0} sx={panel}>
    <Stack spacing={2}>
      <Box>
        <Typography variant="caption" color="text.secondary">Godkendt standardrelease (ikke nødvendigvis installeret)</Typography>
        <Stack direction="row" alignItems="baseline" flexWrap="wrap" gap={1}>
          <Typography variant="h4" fontWeight={900}>ClientFlow {stableVersion}</Typography>
          <Typography variant="caption" color="text.secondary">Release {release?.release_id?.match(/-seq-(\d+)$/)?.[1] || "–"}</Typography>
        </Stack>
      </Box>
      <Box sx={{display:"grid",gridTemplateColumns:{xs:"repeat(2,minmax(0,1fr))",md:"repeat(5,minmax(0,1fr))"},gap:1}}>
        {[["Klienter",counts.total],["På standard",counts.standard],["Ældre",counts.older],["Nyere",counts.newer],["Ukendt",counts.unknown]].map(([label,count]) =>
          <Box key={label} sx={{p:1.5,border:1,borderColor:"divider",borderRadius:2,minWidth:0}}>
            <Typography variant="caption" color="text.secondary">{label}</Typography>
            <Typography variant="h5" fontWeight={800}>{count}</Typography>
          </Box>)}
      </Box>
      <Stack direction={{xs:"column",sm:"row"}} gap={1.5}>
        <TextField fullWidth size="small" label="Søg klient, organisation eller version" value={query} onChange={(event)=>{setQuery(event.target.value);setPage(0);}} />
        <TextField select size="small" label="Version" value={filter} onChange={(event)=>{setFilter(event.target.value);setPage(0);}} sx={{minWidth:170}}>
          <MenuItem value="all">Alle versioner</MenuItem>
          {Object.entries(STATES).map(([key,state])=><MenuItem key={key} value={key}>{state.label}</MenuItem>)}
        </TextField>
      </Stack>
      <TableContainer>
        <Table size="small" aria-label="ClientFlow klientoversigt">
          <TableHead><TableRow><TableCell>Klient</TableCell><TableCell>Rapporteret version</TableCell><TableCell>Versionsstatus</TableCell><TableCell>Opdatering</TableCell></TableRow></TableHead>
          <TableBody>
            {filtered.slice(safePage*25,safePage*25+25).map((row)=>{
              const versionState = STATES[fleetVersionStatus(row,stableVersion)];
              const deployment = active.get(row.id);
              const update = deployment ? deploymentPresentation(deployment.state) : null;
              return <TableRow key={row.id}>
                <TableCell><Typography fontWeight={750}>{row.name}</Typography><Typography variant="caption" color="text.secondary">{[row.organization_name,row.locality,`#${row.id}`].filter(Boolean).join(" · ")}</Typography></TableCell>
                <TableCell>{row.reported_version || "Ukendt"}<Typography component="span" variant="caption" color="text.secondary" sx={{display:"block"}}>{dateLabel(row.version_reported_at)}</Typography></TableCell>
                <TableCell><Chip size="small" variant="outlined" color={versionState.color} label={versionState.label} /></TableCell>
                <TableCell>{update ? <Chip size="small" variant="outlined" color={update.color} label={update.label} /> : activeComplete ? "Ingen aktiv" : "Ukendt"}</TableCell>
              </TableRow>;
            })}
            {filtered.length===0 && <TableRow><TableCell colSpan={4}>Ingen klienter matcher visningen.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </TableContainer>
      <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap" gap={1}>
        <Typography variant="caption" color="text.secondary">{filtered.length ? safePage*25+1 : 0}–{Math.min(filtered.length,(safePage+1)*25)} af {filtered.length}</Typography>
        <Box><Button size="small" disabled={safePage===0} onClick={()=>setPage(safePage-1)}>Forrige</Button><Button size="small" disabled={(safePage+1)*25>=filtered.length} onClick={()=>setPage(safePage+1)}>Næste</Button></Box>
      </Stack>
      <Typography variant="caption" color="text.secondary">Senest rapporterede versioner · ikke aktuel online- eller installationsstatus.</Typography>
    </Stack>
  </Paper>;
}
