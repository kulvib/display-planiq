"""63D-43: synthetic RFB 3.8 whole-path and denial tests, NEVER real VNC."""
from __future__ import annotations

import asyncio
import os
import struct
from pathlib import Path

import pytest

from backend.service1.native_rdp_bridge_protocol import (
    NativeRdpProtocolError,
    encode_chunk,
)
from client.runtime.clientflow_runtime import native_rfb_local_gate as gate
from scripts import clientflow_63d43_synthetic_rfb38 as mock


def test_rfb38_protocol_fixture_binary_properties():
    assert mock.BANNER == b"RFB 003.008\n"
    assert len(mock.PIXEL_FORMAT) == 16
    assert len(mock.SERVER_INIT) == 29
    assert struct.unpack(">HH", mock.SERVER_INIT[:4]) == (2, 1)
    assert mock.SERVER_INIT[4:20] == mock.PIXEL_FORMAT
    assert mock.SERVER_FRAME.endswith(mock.PIXELS)
    assert len(mock.SERVER_FRAME) == 4 + 12 + 8
    assert len(mock.EXPECTED_INPUTS) == 4
    assert [len(x) for x in mock.EXPECTED_INPUTS] == [8, 8, 6, 6]
    assert mock.EXPECTED_INPUTS[0] != mock.EXPECTED_INPUTS[1]
    assert mock.EXPECTED_INPUTS[2] != mock.EXPECTED_INPUTS[3]


def test_genuine_af_unix_agent_broker_mock_browser_roundtrip():
    if os.geteuid() <= 0:
        pytest.skip("Unprivileged Linux runner only; no root tests")
    result = asyncio.run(asyncio.wait_for(mock.probe(), timeout=25))
    assert result["af_unix_real_os_socket"] is True
    assert result["private_socket_revalidated"] is True
    assert result["mouse_up_and_key_up_verified"] is True
    assert result["backend_session_bound_sequence_and_ack"] is True
    assert result["pixel_bytes_verified"] == 8
    assert result["input_events_verified"] == 4
    for key in (
        "actual_x11vnc_executed", "real_desktop_pixels_proven",
        "browser_novnc_render_proven", "producer_approved",
        "activation_permitted", "viborg1_changed",
    ):
        assert result[key] is False
    assert gate.PRODUCER_APPROVED is False


def test_browser_rejects_wrong_generation_even_with_valid_base64():
    class StubStream:
        async def receive(self, _packet):
            raise AssertionError("wrong generation must never reach RFB producer")

    class StubRelay:
        def accept_ack(self, *_args, **_kwargs):
            raise AssertionError("wrong generation must never get an ACK")

    async def scenario():
        inbound = asyncio.Queue()
        browser = mock.SyntheticBrowser(StubStream(), StubRelay(), inbound)
        wrong = encode_chunk(
            session_id=mock.SESSION,
            stream_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            seq=0, payload=b"RFB 003.008\n",
        )
        await inbound.put(wrong)
        with pytest.raises(NativeRdpProtocolError):
            await browser.readexactly(12)

    asyncio.run(scenario())


def test_browser_refuses_empty_oversized_inputs():
    class StubStream:
        async def receive(self, _packet):
            raise AssertionError("no data must reach producer")

    class StubRelay:
        def accept_chunk(self, *_args, **_kwargs):
            raise AssertionError("invalid data must never get broker credit")

    async def scenario():
        browser = mock.SyntheticBrowser(StubStream(), StubRelay(), asyncio.Queue())
        for value in (b"", b"x" * (16 * 1024 + 1)):
            with pytest.raises(mock.SyntheticRfbError):
                await browser.send(value)
        for n in (0, -1, 65537):
            with pytest.raises(mock.SyntheticRfbError):
                await browser.readexactly(n)

    asyncio.run(scenario())


def test_source_harness_does_not_run_or_approve_real_vnc():
    text = Path(mock.__file__).read_text()
    assert "from scripts import clientflow_63d41_rfb_source_gate" in text
    assert "subprocess" not in text
    assert "socket.socket(socket.AF_INET" not in text
    assert "gate.PRODUCER_APPROVED = True" not in text
    assert "local_gate.PRODUCER_APPROVED = True" not in text
    assert "await asyncio.start_unix_server(" in text
    assert "Only unprivileged ephemeral Ubuntu 26.04 GitHub CI" in text
    assert gate.PRODUCER_APPROVED is False


def test_fake_ci_environment_rejected():
    allowed = {
        "CI": "true", "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "kulvib/display-planiq",
    }
    os_release = 'ID=ubuntu\nVERSION_ID="26.04"\n'
    assert mock.ci_gate.authorized_ci(allowed, os_release, 1000)
    assert not mock.ci_gate.authorized_ci(allowed, os_release, 0)
    assert not mock.ci_gate.authorized_ci(
        dict(allowed, GITHUB_REPOSITORY="other"), os_release, 1000,
    )
    assert not mock.ci_gate.authorized_ci(
        allowed, os_release.replace("26.04", "24.04"), 1000,
    )
