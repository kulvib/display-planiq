"""68N-B5: mixed synthetic media/wake capacity, no physical or Render claim.

Actual relay/pump/budget implementations; deliberately fake socket boundaries
and authorization, no production DB, actual RDP/fMP4 codec, network or GPU.
Existing independently authenticated HTTP fleet gate remains unchanged.
"""
from __future__ import annotations

import asyncio
import json
from time import perf_counter

import pytest

from service1 import realtime_wakeup as wake
from service1.livestream_wss_admission import Admission, MAX_PUBLISHERS, MAX_VIEWERS
from service1.livestream_wss_core import FRAGMENT, INIT, LiveRelay, MediaFault, encode_frame
from service1.native_rdp_https_core import (
    BinaryHttpsPeer, BinaryPeerFault, MAX_FRAME, MAX_GLOBAL_QUEUE, QueueBudget,
    decode_batch, encode_batch,
)
from service1.routers import native_rdp_https_http as http
from service1.routers import native_rdp_tunnel as native


class MemorySocket:
    """Bounded test transport, not a network socket or production queue."""
    def __init__(self, packets):
        self.incoming = asyncio.Queue(maxsize=len(packets) + 1)
        self.sent = []
        for packet in packets:
            self.incoming.put_nowait({"type": "websocket.receive", "bytes": packet})
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})

    async def receive(self):
        return await self.incoming.get()

    async def send_bytes(self, packet):
        self.sent.append(packet)
        await asyncio.sleep(0)


def test_mixed_100_native_pumps_300_wakes_and_bounded_livestream(monkeypatch):
    async def exercise():
        start = perf_counter()
        domains = ("display", "system", "livestream")
        clients = list(range(880001, 880101))
        assert native.MAX_TUNNELS >= len(clients)
        # Isolate all process-local test keys from the rest of the suite.
        from collections import defaultdict
        monkeypatch.setattr(wake, "_GENERATIONS", defaultdict(int))
        monkeypatch.setattr(wake, "_ASYNC_WAITERS", defaultdict(set))
        waiters = {}
        for cid in clients:
            for domain in domains:
                after = wake.current_generation(domain, cid)
                waiters[(domain, cid)] = asyncio.create_task(
                    wake.wait_for_change_async(domain, cid, after, 55)
                )
        await asyncio.sleep(0)
        assert len(wake._ASYNC_WAITERS) == 300
        assert all(not task.done() for task in waiters.values())

        admission = Admission()
        live = LiveRelay(max_channels=MAX_PUBLISHERS)
        epochs = {}
        viewer_handles = []
        for cid in clients:
            if admission.admit_publisher(cid):
                epochs[cid] = live.open(cid, f"generation-{cid}")
        assert len(epochs) == MAX_PUBLISHERS == 4
        for cid in epochs:
            for _ in range(3):
                handle = admission.admit_viewer(cid)
                if handle is not None:
                    viewer_handles.append(handle)
        assert len(viewer_handles) == MAX_VIEWERS == 8
        for cid, epoch in epochs.items():
            live.publish(epoch, encode_frame(INIT, 0, 0, f"init-{cid}".encode()))

        async def rd(cid):
            inputs = [f"input-{cid}-{n}".encode() for n in range(12)]
            outputs = [f"screen-{cid}-{n}".encode() + b"x" * 4096 for n in range(12)]
            browser, agent = MemorySocket(inputs), MemorySocket(outputs)
            tunnel = native.NativeRdpTunnel(
                client_id=cid, session_id=f"session-{cid}", tunnel_id=f"tunnel-{cid}",
                user_id=1, browser=browser, agent=agent,
            )
            # Auth itself is covered by the existing independent route tests.
            tunnel.authorized_browser = lambda: True
            tunnel.authorized_agent = lambda: True
            await asyncio.gather(native._pump(tunnel, browser, browser_side=True),
                                 native._pump(tunnel, agent, browser_side=False))
            assert agent.sent == inputs and browser.sent == outputs
            assert tunnel.browser_to_agent.frames == tunnel.agent_to_browser.frames == 12
            assert tunnel.browser_to_agent.bytes == sum(map(len, inputs))
            assert tunnel.agent_to_browser.bytes == sum(map(len, outputs))
            return sum(map(len, inputs + outputs))

        async def video():
            latest = {}
            for seq in range(1, 21):
                for cid, epoch in epochs.items():
                    packet = encode_frame(FRAGMENT, seq, seq * 1000,
                                          f"video-{cid}-{seq}".encode() + b"v" * 8192)
                    live.publish(epoch, packet)
                    latest[cid] = packet
                await asyncio.sleep(0)
            for cid, epoch in epochs.items():
                result = live.latest(epoch, 1)
                assert result.sequence == 20 and result.reset_decoder
                assert result.frames[-1].wire == latest[cid]
            return live.retained

        async def notifications():
            # Only a single generation on every client/domain key, deliberately
            # staggered while media runs. No DB or thread pool is involved.
            selected = {(domain, cid) for domain in domains for cid in clients[::10]}
            for domain, cid in sorted(selected):
                assert wake.notify_command_available(domain, cid) == 1
                await asyncio.sleep(0)
            await asyncio.gather(*(waiters[key] for key in selected))
            assert all(waiters[key].result() == 1 for key in selected)
            assert all(not task.done() for key, task in waiters.items() if key not in selected)
            # Cancel idle subscriptions and verify exact cleanup.
            for key, task in waiters.items():
                if key not in selected:
                    task.cancel()
            await asyncio.gather(*waiters.values(), return_exceptions=True)
            assert not wake._ASYNC_WAITERS
            return len(selected)

        try:
            traffic, retained, notified = await asyncio.wait_for(
                asyncio.gather(asyncio.gather(*(rd(cid) for cid in clients)),
                               video(), notifications()), timeout=20)
            assert 0 < retained <= live.max_retained
            assert notified == 30
            print("FLEET_MIXED_MEDIA_CI " + json.dumps({
                "synthetic_clients": len(clients), "native_pumps": 200,
                "rd_frames": len(clients) * 24, "rd_payload_bytes": sum(traffic),
                "wake_subscriptions": len(waiters), "targeted_wakes": notified,
                "video_publishers": len(epochs), "viewer_handles": len(viewer_handles),
                "video_fragments": len(epochs) * 20,
                "retained_video_bytes": retained,
                "elapsed_seconds": round(perf_counter() - start, 3),
                "production_capacity_verified": False,
            }, sort_keys=True))
        finally:
            for task in waiters.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*waiters.values(), return_exceptions=True)
            for handle in viewer_handles:
                admission.release_viewer(handle)
            for cid, epoch in epochs.items():
                assert live.close(epoch)
                admission.release_publisher(cid)
        assert live.retained == 0 and not admission.publishers and not admission.viewers
        assert not wake._ASYNC_WAITERS

    asyncio.run(exercise())


def test_https_fallback_peer_budget_pressure_disconnect_and_reconnect():
    async def exercise():
        # The HTTP router caps endpoints, not client pairs. No claim that all
        # 100 clients may use fallback simultaneously.
        budget = QueueBudget()
        peers = [BinaryHttpsPeer(budget) for _ in range(http.MAX_PEERS)]
        assert len(peers) == 16 and budget.limit == MAX_GLOBAL_QUEUE
        try:
            for i, peer in enumerate(peers):
                packet = bytes([i]) * MAX_FRAME
                for seq in range(15):
                    assert peer.push(seq, encode_batch([packet])) == seq + 1
                    await peer.send_bytes(packet)
            assert budget.used == len(peers) * 30 * (MAX_FRAME + 4)
            assert budget.used <= budget.limit
            victim = peers[0]
            # An ambiguous upload replay closes only this peer and frees both
            # directions; all others must retain their exact queued payload.
            with pytest.raises(BinaryPeerFault, match="sequence"):
                victim.push(14, encode_batch([b"replay"]))
            assert victim.closed.is_set() and victim.queued_bytes == 0
            assert not any(peer.closed.is_set() for peer in peers[1:])
            for i, peer in enumerate(peers[1:], 1):
                packet = bytes([i]) * MAX_FRAME
                assert [(await peer.receive())["bytes"] for _ in range(15)] == [packet] * 15
                received = []
                for seq in range(5):
                    batch = await peer.poll(seq)
                    assert batch.sequence == seq
                    received += decode_batch(batch.body)
                assert received == [packet] * 15
            assert budget.used == 0
            replacement = BinaryHttpsPeer(budget)
            peers[0] = replacement
            assert replacement.push(0, encode_batch([b"new-session"])) == 1
            assert (await replacement.receive())["bytes"] == b"new-session"
            assert budget.used == 0
        finally:
            await asyncio.gather(*(peer.close() for peer in peers))
        assert budget.used == 0

    asyncio.run(exercise())


def test_livestream_publisher_reconnect_fences_old_generation_at_capacity():
    admission = Admission()
    relay = LiveRelay(max_channels=MAX_PUBLISHERS)
    epochs = {cid: relay.open(cid, f"generation-{cid}") for cid in range(1, MAX_PUBLISHERS + 1)
              if admission.admit_publisher(cid)}
    assert len(epochs) == MAX_PUBLISHERS
    assert not admission.admit_publisher(MAX_PUBLISHERS + 1)
    for cid, epoch in epochs.items():
        relay.publish(epoch, encode_frame(INIT, 0, 0, b"init"))
        relay.publish(epoch, encode_frame(FRAGMENT, 1, 1000, str(cid).encode()))
    old = epochs[1]
    assert relay.close(old)
    admission.release_publisher(1)
    assert admission.admit_publisher(1)
    new = relay.open(1, "new-generation")
    epochs[1] = new
    with pytest.raises(MediaFault, match="stale"):
        relay.publish(old, encode_frame(FRAGMENT, 2, 2000, b"old"))
    assert not relay.close(old)
    assert relay.latest(new) is None
    relay.publish(new, encode_frame(INIT, 0, 0, b"new-init"))
    relay.publish(new, encode_frame(FRAGMENT, 1, 1000, b"new-data"))
    assert relay.latest(new).frames[-1].wire == encode_frame(FRAGMENT, 1, 1000, b"new-data")
    for cid in range(2, MAX_PUBLISHERS + 1):
        assert relay.latest(epochs[cid]).frames[-1].wire == encode_frame(FRAGMENT, 1, 1000, str(cid).encode())
    for cid, epoch in epochs.items():
        assert relay.close(epoch)
        admission.release_publisher(cid)
    assert relay.retained == 0 and not admission.publishers
