"""63D-34: no RDP/network invocation, no database, no privileged session."""
from __future__ import annotations

import uuid

import pytest

from service1.native_rdp_session_bridge import (
    MAX_NATIVE_RDP_SESSION_SECONDS, NativeRdpRelaySession,
)
from service1.native_rdp_bridge_protocol import (
    MAX_UNACKED_CHUNKS, NativeRdpProtocolError, encode_chunk,
)

SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STREAM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OTHER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def make():
    return NativeRdpRelaySession(SESSION, 3, stream_id=STREAM, created_at=10.0)


def state(kind, *, session=SESSION, stream=STREAM):
    return {"type":kind,"protocol":1,"session_id":session,"stream_id":stream}


def frame(seq, payload=b"\x00\xffrdp"):
    return encode_chunk(session_id=SESSION, stream_id=STREAM,
                        seq=seq, payload=payload)


def ack(seq):
    return {**state("native_rdp_ack"), "seq":seq}


def test_handshake_is_explicit_and_requires_real_agent_ack():
    rd = make()
    assert rd.open_request(now=11.0) == state("native_rdp_open")
    with pytest.raises(NativeRdpProtocolError, match="not ready"):
        rd.accept_chunk(frame(0), origin="browser", now=11.0)
    assert rd.agent_ready(state("native_rdp_ready"), now=11.0) == state("native_rdp_ready")
    with pytest.raises(NativeRdpProtocolError, match="duplicate"):
        rd.agent_ready(state("native_rdp_ready"), now=11.0)
    assert rd.accept_chunk(frame(0), origin="browser", now=11.0) == frame(0)


def test_directional_windows_acknowledge_only_opposite_stream():
    rd = make()
    rd.agent_ready(state("native_rdp_ready"), now=10.0)
    first = frame(0)
    assert rd.accept_chunk(first, origin="browser", now=11.0) == first
    assert rd.accept_chunk(first, origin="agent", now=11.0) == first
    assert rd.accept_ack(ack(0), origin="browser", now=11.0) == ack(0)
    assert rd.accept_ack(ack(0), origin="agent", now=11.0) == ack(0)
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_ack(ack(0), origin="browser", now=11.0)
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_chunk(first, origin="agent", now=11.0)


def test_excessive_unacked_payloads_rejected_without_drops():
    rd = make()
    rd.agent_ready(state("native_rdp_ready"), now=10.0)
    for i in range(MAX_UNACKED_CHUNKS):
        rd.accept_chunk(frame(i), origin="agent", now=11.0)
    with pytest.raises(NativeRdpProtocolError, match="credit"):
        rd.accept_chunk(frame(MAX_UNACKED_CHUNKS), origin="agent", now=11.0)
    rd.accept_ack(ack(0), origin="browser", now=11.0)
    rd.accept_chunk(frame(MAX_UNACKED_CHUNKS), origin="agent", now=11.0)


@pytest.mark.parametrize("message", [
    state("native_rdp_ready", session=OTHER),
    state("native_rdp_ready", stream=OTHER),
    {**state("native_rdp_ready"), "password":"no"},
    {**state("native_rdp_ready"), "protocol":True},
])
def test_ready_rejects_forged_session_or_extra_fields(message):
    with pytest.raises(NativeRdpProtocolError):
        make().agent_ready(message, now=11.0)


def test_expiry_and_stop_revoke_all_pending_bytes():
    rd = make()
    rd.agent_ready(state("native_rdp_ready"), now=10.0)
    rd.accept_chunk(frame(0), origin="agent", now=10.0)
    assert rd.stop(state("native_rdp_close"), now=11.0) == state("native_rdp_close")
    assert rd.closed
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_ack(ack(0), origin="browser", now=11.0)
    expiring = make()
    with pytest.raises(NativeRdpProtocolError, match="expired"):
        expiring.agent_ready(state("native_rdp_ready"),
                             now=10.0 + MAX_NATIVE_RDP_SESSION_SECONDS)
    assert expiring.closed


def test_generation_replay_and_unknown_origin_fail_closed():
    rd = make()
    rd.agent_ready(state("native_rdp_ready"), now=11.0)
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_chunk(frame(0), origin="unknown", now=11.0)
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_chunk({**frame(0), "stream_id":OTHER}, origin="agent", now=11.0)
    with pytest.raises(NativeRdpProtocolError):
        rd.accept_ack({**ack(0), "session_id":OTHER}, origin="agent", now=11.0)
    assert rd.fail_closed() == state("native_rdp_close")
    assert rd.closed


def test_backend_rejects_boolean_client_id():
    for invalid in (True, 0, -1, "3"):
        with pytest.raises(NativeRdpProtocolError):
            NativeRdpRelaySession(SESSION, invalid, stream_id=STREAM)


def test_stream_generation_is_unique_and_uuid_typed():
    a = NativeRdpRelaySession(SESSION, 3)
    b = NativeRdpRelaySession(SESSION, 3)
    assert uuid.UUID(a.stream_id).version == 4
    assert a.stream_id != b.stream_id
