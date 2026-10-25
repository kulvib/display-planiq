import React from "react";
import { Alert, Button, Stack } from "@mui/material";

/** Contain errors in this administration subsection; never modify access rights. */
export default class AccessErrorBoundary extends React.Component {
  state = { failed: false, retry: 0 };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    // No user records or authentication tokens are written to the log.
    console.error("Access administration rendering failed", error?.name || "Error");
  }

  retry = () => this.setState((previous) => ({ failed: false, retry: previous.retry + 1 }));

  render() {
    if (this.state.failed) {
      return (
        <Stack spacing={2}>
          <Alert severity="error">Adgang-siden kunne ikke vises. Prøv igen. Hvis fejlen fortsætter, kontrollér browserkonsollen og API-kaldet til brugerlisten.</Alert>
          <Button onClick={this.retry} variant="outlined" sx={{ alignSelf: "flex-start" }}>Prøv igen</Button>
        </Stack>
      );
    }
    return <React.Fragment key={this.state.retry}>{this.props.children}</React.Fragment>;
  }
}
