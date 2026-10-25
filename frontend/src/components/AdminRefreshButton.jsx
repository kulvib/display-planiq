import React from "react";
import { Button } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";

/**
 * Shared manual refresh action. Matches the Audit-log header action exactly:
 * contained MUI button, leading refresh icon, loading spinner and stable label.
 * Placement is owned by each page's header layout, not by this component.
 */
export default function AdminRefreshButton({ onClick, loading = false, disabled = false, ariaLabel = "Opdater" }) {
  return (
    <Button
      variant="contained"
      startIcon={<RefreshIcon />}
      loading={loading}
      loadingPosition="start"
      onClick={onClick}
      disabled={disabled || loading}
      aria-label={ariaLabel}
    >
      Opdater
    </Button>
  );
}
