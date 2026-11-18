from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from service1.http_ws_relay import close_relay, create_relay, get_relay, require_relay_scope


def test_https_relay_reuses_websocket_shape_with_scope_and_bounded_lifecycle() -> None:
    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            raw = await socket.receive_text()
            payload = json.loads(raw)
            await socket.send_text(json.dumps({"type": "echo", "value": payload["value"]}))

        relay = await create_relay(
            handler,
            headers={"authorization": "Bearer test"},
            scope={"kind": "test", "client_id": 7},
        )
        require_relay_scope(relay, kind="test", client_id=7)
        with pytest.raises(HTTPException):
            require_relay_scope(relay, kind="test", client_id=8)

        await relay.push_from_http(json.dumps({"value": "ok"}))
        messages = [json.loads(value) for value in await relay.poll_to_http(2)]
        assert messages[0] == {"type": "echo", "value": "ok"}

        # The handler has completed, so the relay publishes its bounded close
        # marker rather than leaving a hanging long-poll resource behind. It may
        # be drained in the same HTTP poll as the final application message.
        if not any(value.get("type") == "relay_closed" for value in messages):
            messages.extend(json.loads(value) for value in await relay.poll_to_http(2))
        assert any(value.get("type") == "relay_closed" for value in messages)
        await close_relay(relay.relay_id, reason="test_done")

    asyncio.run(scenario())


def test_https_relay_explicit_close_has_bounded_drain_grace() -> None:
    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            await socket.receive_text()

        relay = await create_relay(handler, scope={"kind": "test", "client_id": 8})
        assert await get_relay(relay.relay_id) is relay
        await close_relay(relay.relay_id, reason="test_close")
        drained = await get_relay(relay.relay_id)
        assert drained.closed is True
        messages = [json.loads(value) for value in await drained.poll_to_http(1)]
        assert any(value.get("type") == "relay_closed" for value in messages)

    asyncio.run(scenario())


def test_https_relay_global_byte_budget_fails_closed(monkeypatch) -> None:
    import service1.http_ws_relay as relay_module

    async def scenario() -> None:
        async def handler(socket) -> None:
            await socket.accept()
            await asyncio.Event().wait()

        monkeypatch.setattr(relay_module, "MAX_TOTAL_QUEUE_BYTES", 12)
        relay = await create_relay(
            handler, scope={"kind": "budget-test", "client_id": 9, "user_id": 1}
        )
        relay._put_outgoing("12345678")
        with pytest.raises(RuntimeError, match="global byte-backpressure"):
            relay._put_outgoing("12345678")
        await close_relay(relay.relay_id, reason="budget_test_done")

    asyncio.run(scenario())


def test_remote_desktop_browser_relay_keeps_only_latest_waiting_frame() -> None:
    """Under a slow browser poll, keep controls but discard stale JPEGs."""
    import service1.http_ws_relay as module

    async def scenario() -> None:
        initial = module._TOTAL_QUEUED_BYTES
        relay = module.HttpWebSocketRelay(
            relay_id="rd-test", headers={}, query_params={}, cookies={}, client_host=None,
            scope={"kind": "rd_browser", "client_id": 3},
        )
        relay._put_outgoing('{"type":"frame","session_id":"s","data":"old"}')
        relay._put_outgoing('{"type":"stream_mode_updated","fps":6}')
        relay._put_outgoing('{"type":"frame","session_id":"s","data":"new"}')
        relay._put_outgoing('{"type":"input_result","ok":true}')
        assert [json.loads(value) for value in await relay.poll_to_http(1)] == [
            {"type": "stream_mode_updated", "fps": 6},
            {"type": "frame", "session_id": "s", "data": "new"},
            {"type": "input_result", "ok": True},
        ]
        assert relay.outgoing_bytes == 0
        assert module._TOTAL_QUEUED_BYTES == initial

    asyncio.run(scenario())


def test_file_and_unrelated_relays_do_not_drop_frames() -> None:
    import service1.http_ws_relay as module

    async def scenario() -> None:
        for kind in ("rd_agent", "terminal_browser", "rd_files"):
            relay = module.HttpWebSocketRelay(
                relay_id=kind, headers={}, query_params={}, cookies={}, client_host=None,
                scope={"kind": kind},
            )
            for n in range(3):
                relay._put_outgoing(json.dumps({"type": "frame", "data": str(n)}, separators=(",", ":")))
            received = [json.loads(value) for value in await relay.poll_to_http(1)]
            assert [item["data"] for item in received] == ["0", "1", "2"]

    asyncio.run(scenario())


def test_remote_desktop_byte_limit_still_rejects_oversized_latest_frame(monkeypatch) -> None:
    import service1.http_ws_relay as module

    async def scenario() -> None:
        relay = module.HttpWebSocketRelay(
            relay_id="cap", headers={}, query_params={}, cookies={}, client_host=None,
            scope={"kind": "rd_browser"},
        )
        monkeypatch.setattr(module, "MAX_QUEUE_BYTES", 64)
        with pytest.raises(RuntimeError, match="byte-backpressure"):
            relay._put_outgoing('{"type":"frame","data":"' + ("x" * 200) + '"}')
        assert relay.outgoing_bytes == 0

    asyncio.run(scenario())


def test_remote_desktop_large_stale_frames_cannot_fill_browser_queue() -> None:
    import service1.http_ws_relay as module

    async def scenario() -> None:
        initial = module._TOTAL_QUEUED_BYTES
        relay = module.HttpWebSocketRelay(
            relay_id="large", headers={}, query_params={}, cookies={}, client_host=None,
            scope={"kind": "rd_browser"},
        )
        for n in range(40):
            payload = json.dumps(
                {"type": "frame", "session_id": "s", "serial": n, "data": "a" * 200000},
                separators=(",", ":"),
            )
            relay._put_outgoing(payload)
        assert relay.outgoing.qsize() == 1
        assert relay.outgoing_bytes < 250000
        messages = [json.loads(x) for x in await relay.poll_to_http(1)]
        assert [x["serial"] for x in messages] == [39]
        assert module._TOTAL_QUEUED_BYTES == initial

    asyncio.run(scenario())
