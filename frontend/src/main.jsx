import React from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider, CssBaseline, Box } from "@mui/material";
import App from "./App";
import PlanIQFooter from "./components/PlanIQFooter";
import { AuthProvider } from "./auth/AuthProvider";
import MaintenanceGate from "./auth/MaintenanceGate";
import { BrowserRouter } from "react-router-dom";
import theme from "./theme";
import { AppSnackbarProvider } from "./components/AppSnackbar";

const container = document.getElementById("root");
const root = createRoot(container);
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <AppSnackbarProvider>
          <AuthProvider>
            <Box sx={{ minHeight: "100dvh", display: "flex", flexDirection: "column", minWidth: 0 }}>
              <Box sx={{ flex: "1 0 auto", minWidth: 0, display: "flex", flexDirection: "column" }}>
                <MaintenanceGate>
                  <App />
                </MaintenanceGate>
              </Box>
              <PlanIQFooter />
            </Box>
          </AuthProvider>
        </AppSnackbarProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
