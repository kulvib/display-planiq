"""63D-42 end-to-end byte counters. No RDP secrets, server or physical claims."""
import asyncio
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "runtime"))

from clientflow_runtime import native_rdp_forwarder as forwarder  # noqa: E402
from service1.routers import native_rdp_tunnel as relay  # noqa: E402


class SocketStub:
    def __init__(self):
        self.rx = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def receive(self):
        return await self.rx.get()

    async def send_bytes(self, packet):
        self.sent.append(packet)

    async def close(self, **_kwargs):
        self.closed = True


def test_render_relay_counts_only_forwarded_binary_bytes(caplog):
    async def exercise():
        browser, agent = SocketStub(), SocketStub()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        tunnel.authorized_browser = lambda: True
        tunnel.authorized_agent = lambda: True
        payloads = [b"top-secret-mock-pdu", bytes(range(256)) * 200]
        for payload in payloads:
            await browser.rx.put({"type": "websocket.receive", "bytes": payload})
        await browser.rx.put({"type": "websocket.disconnect"})
        await relay._pump(tunnel, browser, browser_side=True)
        await agent.rx.put({"type": "websocket.receive", "bytes": b"\x03\x00\x00\x0b"})
        await agent.rx.put({"type": "websocket.disconnect"})
        await relay._pump(tunnel, agent, browser_side=False)
        assert agent.sent == payloads
        assert browser.sent == [b"\x03\x00\x00\x0b"]
        assert tunnel.browser_to_agent.frames == 2
        assert tunnel.browser_to_agent.bytes == sum(map(len, payloads))
        assert tunnel.agent_to_browser.frames == 1
        assert tunnel.agent_to_browser.bytes == 4
        await relay._cleanup(tunnel)
        assert browser.closed and agent.closed
    with caplog.at_level(logging.INFO):
        asyncio.run(exercise())
    assert "native_rdp_flow" in caplog.text
    assert "browser_to_agent_frames=2" in caplog.text
    assert "agent_to_browser_bytes=4" in caplog.text
    assert "top-secret-mock-pdu" not in caplog.text
    assert "bd29ed7a" not in caplog.text


def test_invalid_relay_frame_does_not_count_payload(caplog):
    async def exercise():
        browser, agent = SocketStub(), SocketStub()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        tunnel.authorized_browser = lambda: True
        tunnel.authorized_agent = lambda: True
        await browser.rx.put({"type": "websocket.receive", "bytes": b"X" * (relay.MAX_BINARY_PACKET + 1)})
        await relay._pump(tunnel, browser, browser_side=True)
        assert tunnel.browser_to_agent.bytes == 0
        assert agent.sent == []
    with caplog.at_level(logging.WARNING):
        asyncio.run(exercise())
    assert "class=oversized" in caplog.text
    assert "XXXXX" not in caplog.text


def test_agent_counts_both_socket_boundaries_without_logging_credentials(monkeypatch, caplog):
    class Reader:
        def __init__(self):
            self.sent_once = False

        async def read(self, _length):
            if not self.sent_once:
                self.sent_once = True
                return b"MOCK-GNOME-REPLY"
            await asyncio.Future()

    class Writer:
        def __init__(self):
            self.written = []
            self.closed = False

        def write(self, packet):
            self.written.append(packet)

        async def drain(self):
            return None

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

    class Wss:
        def __init__(self):
            self.sent = []

        async def send(self, packet):
            self.sent.append(packet)

        def __aiter__(self):
            async def messages():
                yield b"MOCK-BROWSER-HANDSHAKE"
                await asyncio.Future()
            return messages()

    class Connected:
        async def __aenter__(self):
            return websocket

        async def __aexit__(self, *_):
            return False

    class Transport:
        def websocket_url(self, path):
            assert path.endswith("/ws")
            return "wss://backend.example.test" + path

        def websocket_headers(self):
            return {"Authorization": "Bearer IN_MEMORY_DO_NOT_LOG"}

    reader, writer, websocket = Reader(), Writer(), Wss()

    async def open_local(host, port):
        assert (host, port) == ("127.0.0.1", 3389)
        return reader, writer

    monkeypatch.setattr(forwarder, "ensure_native_rdp_guard", lambda **_: None)
    monkeypatch.setattr(forwarder.asyncio, "open_connection", open_local)
    connect_kwargs = {}

    def connect_without_compression(*_args, **kwargs):
        connect_kwargs.update(kwargs)
        return Connected()

    monkeypatch.setattr(forwarder.websockets, "connect", connect_without_compression)

    async def exercise():
        task = asyncio.create_task(forwarder.forward_native_rdp(
            transport=Transport(), client_id=3,
            session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            ssl_context=object(),
        ))
        for _ in range(100):
            if writer.written and websocket.sent:
                break
            await asyncio.sleep(0.002)
        assert writer.written == [b"MOCK-BROWSER-HANDSHAKE"]
        assert websocket.sent == [b"MOCK-GNOME-REPLY"]
        assert connect_kwargs["compression"] is None
        assert connect_kwargs["max_queue"] == 4
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert writer.closed

    with caplog.at_level(logging.INFO):
        asyncio.run(exercise())
    assert "native_rdp_agent_flow" in caplog.text
    assert "tcp_to_wss_frames=1" in caplog.text
    assert "wss_to_tcp_frames=1" in caplog.text
    for forbidden in ("MOCK-BROWSER-HANDSHAKE", "MOCK-GNOME-REPLY", "IN_MEMORY_DO_NOT_LOG", "bd29ed7a"):
        assert forbidden not in caplog.text


def test_relay_reuses_one_receive_across_idle_authorization_checks(monkeypatch):
    """No idle cancellation/restart, and close stops a still-pending receiver."""
    monkeypatch.setattr(relay, "CHECK_INTERVAL", 0.005)

    class CountingSocket(SocketStub):
        def __init__(self):
            super().__init__()
            self.receive_calls = 0

        async def receive(self):
            self.receive_calls += 1
            return await super().receive()

    async def exercise():
        browser, agent = CountingSocket(), SocketStub()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        checks = []
        tunnel.authorized_browser = lambda: checks.append(1) or True
        tunnel.authorized_agent = lambda: True
        task = asyncio.create_task(relay._pump(tunnel, browser, browser_side=True))
        await asyncio.sleep(0.045)
        assert len(checks) >= 2
        assert browser.receive_calls == 1, "do not recreate idle receive task on each check"

        payloads = [bytes([i % 251]) for i in range(150)]
        for packet in payloads:
            await browser.rx.put({"type": "websocket.receive", "bytes": packet})
        for _ in range(100):
            if len(agent.sent) == len(payloads):
                break
            await asyncio.sleep(0.005)
        assert agent.sent == payloads
        assert tunnel.browser_to_agent.frames == len(payloads)
        assert tunnel.browser_to_agent.bytes == len(payloads)

        tunnel.closed.set()
        await asyncio.wait_for(task, timeout=0.4)
        assert browser.receive_calls <= len(payloads) + 1

    asyncio.run(exercise())


def test_relay_send_timeout_closes_stalled_path_without_counting_bytes(monkeypatch):
    """A slow downstream cannot cause unbounded buffering or fake delivered frames."""
    monkeypatch.setattr(relay, "SEND_TIMEOUT", 0.02)

    class StalledPeer(SocketStub):
        async def send_bytes(self, _packet):
            await asyncio.Future()

    async def exercise():
        browser, agent = SocketStub(), StalledPeer()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        tunnel.authorized_browser = lambda: True
        tunnel.authorized_agent = lambda: True
        await browser.rx.put({"type": "websocket.receive", "bytes": b"PRIVATE-MOCK"})
        try:
            await relay._pump(tunnel, browser, browser_side=True)
        except TimeoutError:
            pass
        else:
            raise AssertionError("stalled peer must time out")
        assert tunnel.browser_to_agent.bytes == 0
        assert tunnel.browser_to_agent.frames == 0

    asyncio.run(exercise())


def test_flow_logging_falls_back_to_uvicorn_without_sensitive_values(monkeypatch):
    """Render's Uvicorn INFO handler must receive bounded, secret-free counters."""
    emitted = []
    uvicorn_logger = logging.getLogger("uvicorn.error")
    with monkeypatch.context() as patch:
        patch.setattr(relay.logger, "isEnabledFor", lambda _level: False)
        patch.setattr(uvicorn_logger, "info", lambda template, *args: emitted.append(template % args))
        browser, agent = SocketStub(), SocketStub()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="bd29ed7a-ad54-4f15-8028-5728fffe2156",
            tunnel_id="8457d398-2e89-4292-995b-54a67983623a",
            user_id=42, browser=browser, agent=agent,
        )
        tunnel.browser_to_agent.record(42)
        tunnel.agent_to_browser.record(120)
        relay._traffic_summary(tunnel, "active")
    assert len(emitted) == 1
    assert "native_rdp_flow client_id=3 phase=active" in emitted[0]
    assert "browser_to_agent_bytes=42" in emitted[0]
    assert "agent_to_browser_bytes=120" in emitted[0]
    assert "bd29ed7a" not in emitted[0]
    assert "8457d398" not in emitted[0]
    assert "PRIVATE-MOCK" not in emitted[0]
