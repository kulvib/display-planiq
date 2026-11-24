"""Experimental binary queue/sequence proofs; no HTTP route or physical claim."""
import asyncio
import struct

import pytest

from service1.native_rdp_https_core import (
    BinaryHttpsPeer, BinaryPeerFault, CONTACT_SECONDS, MAX_BATCH, MAX_FRAME,
    MAX_QUEUE, QueueBudget, decode_batch, encode_batch,
)


def test_batch_integrity_and_defensive_framing():
    packets = [b"\x00\xff", bytes(range(256)) * 256, b"\x03\x00\x01"]
    assert decode_batch(encode_batch(packets)) == packets
    for bad in (b"", b"\x00", struct.pack(">I", 0), struct.pack(">I", MAX_FRAME + 1),
                struct.pack(">I", 2) + b"x", b"x" * (MAX_BATCH + 1),
                encode_batch([b"valid"]) + b"\x00"):
        with pytest.raises(BinaryPeerFault):
            decode_batch(bad)
    with pytest.raises(BinaryPeerFault):
        encode_batch([b"x" * MAX_FRAME] * 4)


def test_full_duplex_order_and_acknowledgements():
    async def exercise():
        budget = QueueBudget()
        peer = BinaryHttpsPeer(budget)
        incoming = [b"abc", bytes(range(256)) * 256, b"\xff"]
        assert peer.push(0, encode_batch(incoming)) == 1
        assert peer.push(1, encode_batch([b"last"])) == 2
        for packet in [*incoming, b"last"]:
            assert await peer.receive() == {"type": "websocket.receive", "bytes": packet}
        assert budget.used == 0
        outgoing = [bytes([n]) * MAX_FRAME for n in range(6)]
        for packet in outgoing:
            await peer.send_bytes(packet)
        first = await peer.poll(0)
        second = await peer.poll(1)
        assert first.sequence == 0 and second.sequence == 1
        assert decode_batch(first.body) + decode_batch(second.body) == outgoing
        assert budget.used == 0
        empty = await peer.poll(2, timeout=0.001)
        assert empty.sequence == 2 and empty.body == b"" and not empty.closed
        await peer.send_bytes(b"new")
        assert decode_batch((await peer.poll(2)).body) == [b"new"]
        await peer.close()
        assert budget.used == 0
    asyncio.run(exercise())


@pytest.mark.parametrize("sequence", [0, 2, -1, True, "1"])
def test_replay_gap_or_wrong_type_closes_and_releases(sequence):
    async def exercise():
        budget = QueueBudget()
        peer = BinaryHttpsPeer(budget)
        peer.push(0, encode_batch([b"queued"]))
        await peer.send_bytes(b"other direction")
        with pytest.raises(BinaryPeerFault):
            peer.push(sequence, encode_batch([b"not delivered"]))
        assert peer.closed.is_set() and budget.used == 0
        assert (await peer.receive())["type"] == "websocket.disconnect"
        assert (await peer.poll(0)).closed
    asyncio.run(exercise())


def test_download_replay_closes_new_queue():
    async def exercise():
        budget = QueueBudget()
        peer = BinaryHttpsPeer(budget)
        await peer.send_bytes(b"first")
        await peer.poll(0)
        await peer.send_bytes(b"second")
        with pytest.raises(BinaryPeerFault, match="acknowledgement"):
            await peer.poll(0)
        assert budget.used == 0 and peer.closed.is_set()
    asyncio.run(exercise())


def test_concurrent_polls_and_cancelled_poll_close_without_retaining_bytes():
    async def exercise():
        budget = QueueBudget()
        peer = BinaryHttpsPeer(budget)
        first = asyncio.create_task(peer.poll(0))
        await asyncio.sleep(0)
        with pytest.raises(BinaryPeerFault, match="concurrent"):
            await peer.poll(0)
        assert (await first).closed
        peer = BinaryHttpsPeer(budget)
        peer.push(0, encode_batch([b"buffered"]))
        pending = asyncio.create_task(peer.poll(0))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert peer.closed.is_set() and budget.used == 0
    asyncio.run(exercise())


def test_global_and_per_peer_capacity_fail_closed_without_touching_other_peer():
    async def exercise():
        budget = QueueBudget(limit=MAX_QUEUE)
        first, second = BinaryHttpsPeer(budget), BinaryHttpsPeer(budget)
        await first.send_bytes(b"a" * MAX_FRAME)
        for _ in range(30):
            await second.send_bytes(b"b" * MAX_FRAME)
        with pytest.raises(BinaryPeerFault, match="capacity"):
            await second.send_bytes(b"c" * MAX_FRAME)
        assert second.closed.is_set() and not first.closed.is_set()
        assert budget.used == MAX_FRAME + 4
        assert decode_batch((await first.poll(0)).body) == [b"a" * MAX_FRAME]
        assert budget.used == 0
        peer = BinaryHttpsPeer(QueueBudget())
        for _ in range(31):
            await peer.send_bytes(b"x" * MAX_FRAME)
        with pytest.raises(BinaryPeerFault, match="capacity"):
            await peer.send_bytes(b"x" * MAX_FRAME)
        assert peer.queued_bytes == 0
    asyncio.run(exercise())


def test_independent_supervision_clears_abandoned_peer():
    async def exercise():
        now = [100.0]
        budget = QueueBudget()
        peer = BinaryHttpsPeer(budget, clock=lambda: now[0])
        await peer.send_bytes(b"queued")
        peer.push(0, encode_batch([b"incoming"]))
        now[0] += CONTACT_SECONDS
        await peer.supervise()
        assert peer.closed.is_set() and budget.used == 0
        await peer.close()
        assert budget.used == 0
    asyncio.run(exercise())


def test_existing_native_pump_accepts_binary_peer_without_transforming_payload():
    from service1.routers import native_rdp_tunnel as relay

    async def exercise():
        class Agent:
            def __init__(self):
                self.sent = []
            async def send_bytes(self, packet):
                self.sent.append(packet)
            async def close(self, **_kwargs):
                pass

        budget = QueueBudget()
        browser, agent = BinaryHttpsPeer(budget), Agent()
        tunnel = relay.NativeRdpTunnel(
            client_id=3, session_id="session", tunnel_id="tunnel", user_id=42,
            browser=browser, agent=agent,
        )
        tunnel.authorized_browser = lambda: True
        tunnel.authorized_agent = lambda: True
        payloads = [b"\x00\xff", bytes(range(256)) * 256, b"last"]
        browser.push(0, encode_batch(payloads))
        pump = asyncio.create_task(relay._pump(tunnel, browser, browser_side=True))
        async def forwarded():
            while len(agent.sent) < len(payloads):
                await asyncio.sleep(0)
        await asyncio.wait_for(forwarded(), timeout=2)
        assert agent.sent == payloads
        assert tunnel.browser_to_agent.bytes == sum(map(len, payloads))
        await browser.close()
        await asyncio.wait_for(pump, timeout=2)
        assert budget.used == 0
    asyncio.run(exercise())
