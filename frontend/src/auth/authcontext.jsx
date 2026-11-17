// src/auth/authcontext.jsx
// Fælles PlanIQ-sessionpolitik:
// kort access token i memory, refresh-token i HttpOnly-cookie,
// 25+5 minutters idle-advarsel, servervalideret fortsættelse,
// cross-tab logout/aktivitet og absolut sessiongrænse.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { useNavigate } from "react-router-dom";
import {
  apiUrl,
  authHeaders,
  clearAuthToken,
  getSessionExpiresAt,
  getAuthSessionId,
  logout as apiLogout,
  isTerminalSessionRefreshError,
  performBootRefresh,
  refreshSession,
} from "../api";
import SessionTimeoutDialog from "./SessionTimeoutDialog";
import { broadcastSessionContextChanged, useSessionPolicy } from "./sessionPolicy";
import { getCanonicalUserRole, getRoleLabel, hasAdminOrSuperadminRole, hasSuperadminRole, isViewerRole } from "../utils/roleUtils";
import {
  listImpersonationCandidates as loadImpersonationCandidates,
  startImpersonationSession,
  stopImpersonationSession,
} from "./impersonationApi";

const AuthContext = createContext();

function normalizeUserData(userData) {
  if (!userData) return userData;
  const organizationId = userData.organization_id ?? userData.organizationId ?? null;
  const role = getCanonicalUserRole(userData);
  return {
    ...userData,
    organization_id: organizationId,
    role,
    role_display: userData.role_display || getRoleLabel(role),
  };
}

const PUBLIC_AUTH_PATHS = new Set([
  "/login",
  "/glemt-adgangskode",
  "/nulstil-adgangskode",
]);

function isPublicAuthPath(pathname = "") {
  return PUBLIC_AUTH_PATHS.has(pathname);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpiresAt, setSessionExpiresAtState] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [bootUnavailable, setBootUnavailable] = useState(false);
  const [bootAttempt, setBootAttempt] = useState(0);
  const navigate = useNavigate();
  const [bootPathname] = useState(() => window.location.pathname);

  const endLocalSession = useCallback(async () => {
    // Start server-logout mens det nuværende access-token stadig er tilgængeligt.
    const serverLogout = apiLogout().catch(() => {
      // Lokal session ryddes under alle omstændigheder.
    });

    setUser(null);
    setLoading(false);
    setSessionExpiresAtState(null);
    setSessionId(null);
    localStorage.removeItem("user");
    clearAuthToken();
    navigate("/login", { replace: true });

    await serverLogout;
  }, [navigate]);

  const applySessionUser = useCallback((userData, nextSessionExpiresAt = null, nextSessionId = null) => {
    const normalized = normalizeUserData(userData);
    setUser(normalized);
    setLoading(false);
    setSessionExpiresAtState(nextSessionExpiresAt || getSessionExpiresAt() || null);
    setSessionId(nextSessionId || getAuthSessionId() || null);
    localStorage.setItem("user", JSON.stringify(normalized));
    return normalized;
  }, []);

  const validateCurrentSession = useCallback(async () => {
    const refreshed = await refreshSession();
    const nextExpiry = refreshed?.session_expires_at || getSessionExpiresAt() || null;
    setSessionExpiresAtState(nextExpiry);
    setSessionId(refreshed?.session_id || getAuthSessionId() || null);
    if (refreshed?.user) applySessionUser(refreshed.user, nextExpiry, refreshed?.session_id);
    return refreshed;
  }, [applySessionUser]);

  const sessionPolicy = useSessionPolicy({
    active: Boolean(user),
    sessionExpiresAt,
    sessionId,
    validateSession: validateCurrentSession,
    onSessionEnd: endLocalSession,
    onSessionContextChanged: validateCurrentSession,
  });

  const loginUser = useCallback((userData, nextSessionExpiresAt = null, nextSessionId = null) => {
    applySessionUser(userData, nextSessionExpiresAt, nextSessionId);
  }, [applySessionUser]);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      setLoading(true);

      // Login/nulstil-adgangskode er offentlige sider. Her skal en manglende
      // refresh-cookie ikke skabe et forventet 401-kald i baggrunden.
      if (isPublicAuthPath(bootPathname)) {
        if (!cancelled) {
          setBootUnavailable(false);
          setUser(null);
          setSessionExpiresAtState(null);
          setSessionId(null);
          localStorage.removeItem("user");
          clearAuthToken();
          setLoading(false);
        }
        return;
      }

      try {
        const refreshed = await performBootRefresh();
        if (!refreshed) {
          if (!cancelled) {
            setUser(null);
            setSessionExpiresAtState(null);
            setSessionId(null);
            setBootUnavailable(false);
            localStorage.removeItem("user");
          }
          return;
        }

        const res = await fetch(`${apiUrl}/api/auth/me`, {
          headers: authHeaders(),
          credentials: "include",
        });
        if (!res.ok) {
          const failure = new Error(res.status === 401 || res.status === 403
            ? "Sessionen er ikke længere gyldig" : "Backend er midlertidigt utilgængelig");
          failure.status = res.status;
          throw failure;
        }
        const data = normalizeUserData(await res.json());
        if (!cancelled) {
          setUser(data);
          setBootUnavailable(false);
          setSessionExpiresAtState(refreshed?.session_expires_at || getSessionExpiresAt() || null);
          setSessionId(refreshed?.session_id || getAuthSessionId() || null);
          localStorage.setItem("user", JSON.stringify(data));
        }
      } catch (error) {
        if (!cancelled) {
          setUser(null);
          if (isTerminalSessionRefreshError(error)) {
            setSessionExpiresAtState(null);
            setSessionId(null);
            setBootUnavailable(false);
            localStorage.removeItem("user");
            clearAuthToken();
          } else {
            // Render edge failure is NOT proof of an invalid session.
            // Keep the HttpOnly refresh-cookie and in-memory auth state;
            // show a fail-closed retry view instead of redirecting to login.
            setBootUnavailable(true);
          }
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    boot();
    return () => { cancelled = true; };
  }, [bootPathname, bootAttempt]);

  const listImpersonationCandidates = useCallback((signal) => {
    return loadImpersonationCandidates(signal);
  }, []);

  const startImpersonation = useCallback(async (targetUserId) => {
    const result = await startImpersonationSession(targetUserId);
    const normalized = applySessionUser(result.user, result.session_expires_at, result.session_id);
    broadcastSessionContextChanged();
    return normalized;
  }, [applySessionUser]);

  const stopImpersonation = useCallback(async () => {
    const result = await stopImpersonationSession();
    const normalized = applySessionUser(result.user, result.session_expires_at, result.session_id);
    broadcastSessionContextChanged();
    return normalized;
  }, [applySessionUser]);

  const isSuperadmin = hasSuperadminRole(user);
  const isViewer = isViewerRole(user);
  const isAdministrator = getCanonicalUserRole(user) === "admin";
  const isAdmin = hasAdminOrSuperadminRole(user);
  const canReadAll = isSuperadmin || isViewer;

  return (
    <AuthContext.Provider value={{
      user,
      me: user,
      loading,
      loginUser,
      logoutUser: sessionPolicy.logoutNow,
      logout: sessionPolicy.logoutNow,
      isAdmin,
      isSuperadmin,
      isViewer,
      isAdministrator,
      canReadAll,
      isImpersonating: user?.impersonation_active === true,
      actorUserId: user?.actor_user_id ?? null,
      actorUsername: user?.actor_username ?? null,
      actorFullName: user?.actor_full_name ?? null,
      actorRole: user?.actor_role ?? null,
      listImpersonationCandidates,
      startImpersonation,
      stopImpersonation,
    }}>
      {bootUnavailable ? (
        <Box sx={{ minHeight: "100dvh", display: "grid", placeItems: "center", p: 3 }}>
          <Stack spacing={2} sx={{ maxWidth: 480, width: "100%" }}>
            <Typography variant="h5" component="h1">Forbindelsen til PlanIQ Display er afbrudt</Typography>
            <Alert severity="warning">Vi kunne ikke bekræfte sessionen hos serveren. Ingen beskyttede sider vises, før forbindelsen fungerer igen.</Alert>
            <Button variant="contained" disabled={loading} onClick={() => setBootAttempt((previous) => previous + 1)}>
              {loading ? <CircularProgress size={18} /> : "Prøv igen"}
            </Button>
          </Stack>
        </Box>
      ) : children}
      {!bootUnavailable && <SessionTimeoutDialog
        type={sessionPolicy.dialogType}
        secondsRemaining={sessionPolicy.secondsRemaining}
        continuePending={sessionPolicy.continuePending}
        continueError={sessionPolicy.continueError}
        onContinue={sessionPolicy.continueSession}
        onLogout={sessionPolicy.logoutNow}
        onLoginAgain={sessionPolicy.loginAgain}
        onDismissAbsolute={sessionPolicy.dismissAbsoluteWarning}
      />}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
