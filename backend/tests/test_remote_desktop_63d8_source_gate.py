"""CI-readable source controls when SQLModel is unavailable locally."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_control_and_video_keep_separate_bounded_lifecycle():
    broker = source("backend/service1/routers/remote_desktop_v2.py")
    assert "pending_frame: Optional[dict[str, Any]] = None" in broker
    assert "browser.pending_frame = payload" in broker
    assert "asyncio.create_task(_drain_browser_frames(browser))" in broker
    assert "await _send_browser_serialized(browser, payload)" in broker
    assert "browser.frame_sender.cancel()" in broker
    assert 'if payload.get("type") == "frame"' in broker
    assert "await _send_browser_serialized(browser, current)" in broker
    assert "_remote_desktop_browser_auth_state(browser)" in broker
    assert "validate_browser_auth_session_binding" in broker


def test_native_frame_geometry_avoids_database_reads():
    broker = source("backend/service1/routers/remote_desktop_v2.py")
    handler = broker.split('async def _handle_control_agent_message', 1)[1].split('async def _finalize_download',1)[0]
    assert "browser.geometry_fallback_attempted" in handler
    assert "_configured_resolution(client_id)" in handler
    assert handler.count("_configured_resolution(client_id)") == 1
    assert "if 0 < live_width <= 7680 and 0 < live_height <= 4320" in handler
    assert 'payload["screen_width"] = browser.screen_width' in handler
    assert 'payload["screen_height"] = browser.screen_height' in handler
    assert 'payload.setdefault("screen_width"' not in handler


def test_browser_does_not_put_jpeg_in_react_state_or_add_database_polling():
    page = source("frontend/src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx")
    painter = source("frontend/src/pages/clientdetailspage/remotedesktop/latestRemoteFramePainter.mjs")
    relay = source("frontend/src/api/httpRelaySocket.js")
    assert "setFrameSrc(" not in page
    assert "setHasRemoteFrame(true)" in page
    assert "framePainter.push(msg.data)" in page
    assert "pending = `data:image/jpeg;base64,${encodedJpeg}`" in painter
    assert 'getDiagnostics()' in relay
    assert "replacedMoves" in relay
    assert "CLIENTFLOW_1246_PILOT_CLIENT_ID" not in page


def test_operator_history_is_event_driven_not_periodic_db_reads():
    route = source("backend/service1/routers/clientflow_release_administration.py")
    history = source("frontend/src/pages/clientdetailspage/ClientFlowHistoryOnDemand.jsx")
    admin = source("frontend/src/pages/adminpages/ClientFlowReleaseAdministration.jsx")
    assert "recent_deployments" in route
    assert ".limit(20)" in route
    assert "get_current_superadmin_user" in route
    assert "setInterval" not in history
    assert "getClientflowDeployments(clientId, { limit: 10 })" in history
    assert "<ClientFlowDeploymentHistory" in admin
