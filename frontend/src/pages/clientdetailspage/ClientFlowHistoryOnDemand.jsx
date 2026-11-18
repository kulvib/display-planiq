import * as React from "react";
import { Alert, Box, Button, CircularProgress, Typography } from "@mui/material";
import { getClientflowDeployments } from "../../api";
import ClientFlowDeploymentHistory from "../adminpages/ClientFlowDeploymentHistory";
import { validateDeploymentHistory } from "../adminpages/clientflowDeploymentHistory.mjs";

/** A separate user-invoked history reader; never joins the client hot polling loop. */
export default function ClientFlowHistoryOnDemand({ clientId }) {
  const [open, setOpen] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [history, setHistory] = React.useState([]);
  const [error, setError] = React.useState("");
  const requestRef = React.useRef(0);

  React.useEffect(() => {
    requestRef.current += 1;
    setOpen(false);
    setLoading(false);
    setHistory([]);
    setError("");
    return () => { requestRef.current += 1; };
  }, [clientId]);

  const refresh = React.useCallback(async () => {
    if (!clientId) return;
    const token = ++requestRef.current;
    setLoading(true);
    setError("");
    try {
      const rows = validateDeploymentHistory(await getClientflowDeployments(clientId, { limit: 10 }), { limit: 10 });
      if (token === requestRef.current) setHistory(rows);
    } catch (err) {
      if (token === requestRef.current) {
        setHistory([]);
        setError(err?.message || "Kunne ikke hente ClientFlow-historik");
      }
    } finally {
      if (token === requestRef.current) setLoading(false);
    }
  }, [clientId]);

  return (
    <Box sx={{ mt: 1.5 }}>
      <Button size="small" variant="outlined" disabled={loading} onClick={() => {
        if (open) {
          requestRef.current += 1;
          setOpen(false);
        } else {
          setOpen(true);
          void refresh();
        }
      }}>{open ? "Skjul opdateringshistorik" : "Vis opdateringshistorik"}</Button>
      {open && <Box sx={{ mt: 1.5 }}>
        <Typography variant="caption" color="text.secondary">De seneste 10 faktiske deployments – kun hentet efter klik.</Typography>
        <Button size="small" sx={{ ml: 1 }} onClick={() => void refresh()} disabled={loading}>Opdater historik</Button>
        {loading && <CircularProgress size={16} sx={{ ml: 1 }} />}
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
        {!loading && !error && <ClientFlowDeploymentHistory rows={history} showClient={false} />}
      </Box>}
    </Box>
  );
}
