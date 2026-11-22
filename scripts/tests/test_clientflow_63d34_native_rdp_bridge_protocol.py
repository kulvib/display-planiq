"""63D-34 protocol tests: pure bytes only, no sockets, secrets or RDP startup."""
import base64
import uuid

import pytest

from backend.service1.native_rdp_bridge_protocol import (
    MAX_CHUNK_BYTES, MAX_UNACKED_CHUNKS,
    NativeRdpProtocolError, NativeRdpSequenceWindow,
    decode_chunk, encode_chunk,
)

SESSION = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
STREAM = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
OTHER = str(uuid.UUID("33333333-3333-4333-8333-333333333333"))


def frame(seq=0, payload=b"rdp\x00"):
    return encode_chunk(session_id=SESSION, stream_id=STREAM, seq=seq, payload=payload)


def test_binary_roundtrip_and_allowed_limit():
    for length in (1, 4096, MAX_CHUNK_BYTES):
        original = bytes(i % 256 for i in range(length))
        wire = frame(payload=original)
        assert decode_chunk(wire, session_id=SESSION, stream_id=STREAM).payload == original


@pytest.mark.parametrize("payload", [b"", b"x" * (MAX_CHUNK_BYTES + 1), bytearray(b"a"), "secret"])
def test_invalid_payload_cannot_be_encoded(payload):
    with pytest.raises(NativeRdpProtocolError):
        frame(payload=payload)


def test_session_and_reconnect_stream_never_cross():
    wire = frame()
    for expected_session, expected_stream in ((OTHER, STREAM), (SESSION, OTHER)):
        with pytest.raises(NativeRdpProtocolError, match="mismatch"):
            decode_chunk(wire, session_id=expected_session, stream_id=expected_stream)


@pytest.mark.parametrize("change", [
    {"type": "native_rdp_credentials"},
    {"protocol": 2},
    {"seq": True},
    {"seq": -1},
    {"seq": 2**31},
    {"data": ""},
    {"data": "!!"},
    {"data": "YQ==\n"},
    {"data": "YQ="},
    {"data": "YR=="},
])
def test_fail_closed_on_bad_frames(change):
    wire = {**frame(), **change}
    with pytest.raises(NativeRdpProtocolError):
        decode_chunk(wire, session_id=SESSION, stream_id=STREAM)


def test_untrusted_extra_keys_are_rejected_including_credentials():
    wire = {**frame(), "password": "never-accept"}
    with pytest.raises(NativeRdpProtocolError, match="envelope"):
        decode_chunk(wire, session_id=SESSION, stream_id=STREAM)


def test_replay_reorder_credit_limit_and_ack():
    window = NativeRdpSequenceWindow(SESSION, STREAM)
    assert window.accept(frame(0)) == b"rdp\x00"
    with pytest.raises(NativeRdpProtocolError):
        window.accept(frame(0))
    with pytest.raises(NativeRdpProtocolError):
        window.accept(frame(2))
    for seq in range(1, MAX_UNACKED_CHUNKS):
        assert window.accept(frame(seq))
    with pytest.raises(NativeRdpProtocolError, match="credit"):
        window.accept(frame(MAX_UNACKED_CHUNKS))
    with pytest.raises(NativeRdpProtocolError):
        window.acknowledge(1)
    window.acknowledge(0)
    assert window.accept(frame(MAX_UNACKED_CHUNKS))
    window.close()
    with pytest.raises(NativeRdpProtocolError):
        window.accept(frame(MAX_UNACKED_CHUNKS + 1))


def test_acknowledgment_bool_and_missing_pending_rejected():
    window = NativeRdpSequenceWindow(SESSION, STREAM)
    for seq in (0, True):
        with pytest.raises(NativeRdpProtocolError):
            window.acknowledge(seq)


def test_noncanonical_ids_and_b64_fail():
    wire = frame()
    for id_value in (SESSION.upper(), SESSION.replace("-", ""), "x"):
        with pytest.raises(NativeRdpProtocolError):
            decode_chunk({**wire, "session_id": id_value}, session_id=SESSION, stream_id=STREAM)
    with pytest.raises(NativeRdpProtocolError):
        decode_chunk({**wire, "data": base64.urlsafe_b64encode(b"\xfb\xff").decode()}, session_id=SESSION, stream_id=STREAM)
