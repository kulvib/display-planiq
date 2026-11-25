"""Continuous video relay contracts. No network or physical playback claim."""
import struct

import pytest

from service1.livestream_wss_core import (
    Epoch, FRAGMENT, HEADER, INIT, MAX_FRAGMENT, MAX_INIT,
    LiveRelay, MediaFault, decode_frame, encode_frame,
)


def init(payload=b"init"):
    return encode_frame(INIT, 0, 0, payload)


def fragment(sequence, timestamp=None, payload=b"fragment"):
    return encode_frame(FRAGMENT, sequence, sequence * 1000 if timestamp is None else timestamp, payload)


def test_wire_golden_vector_and_length_validation():
    packet = fragment(1, 1000, b"abc")
    assert packet.hex() == "43464c5301020000000000000000000100000000000003e800000003616263"
    assert decode_frame(packet).wire is packet
    for bad in (b"", packet[:-1], packet + b"x", b"NOPE" + packet[4:],
                packet[:4] + b"\x02" + packet[5:],
                packet[:6] + b"\x00\x01" + packet[8:],
                packet[:5] + b"\x03" + packet[6:],
                packet[:8] + struct.pack(">Q", 1 << 53) + packet[16:]):
        with pytest.raises(MediaFault):
            decode_frame(bad)
    for args in ((INIT, 1, 0, b"x"), (INIT, 0, 1, b"x"), (INIT, 0, 0, b"x" * (MAX_INIT + 1)),
                 (FRAGMENT, 0, 0, b"x"), (FRAGMENT, True, 0, b"x"),
                 (FRAGMENT, 1, 1, b"x" * (MAX_FRAGMENT + 1)), (FRAGMENT, 1, 1, b"")):
        with pytest.raises(MediaFault):
            encode_frame(*args)


def test_late_and_slow_readers_receive_latest_not_history():
    relay = LiveRelay()
    epoch = relay.open(3, "generation-a")
    assert relay.latest(epoch) is None
    relay.publish(epoch, init())
    assert relay.latest(epoch) is None
    relay.publish(epoch, fragment(1))
    first = relay.latest(epoch)
    assert first.reset_decoder and [frame.kind for frame in first.frames] == [INIT, FRAGMENT]
    assert relay.latest(epoch, 1) is None
    relay.publish(epoch, fragment(2))
    next_one = relay.latest(epoch, 1)
    assert not next_one.reset_decoder and len(next_one.frames) == 1
    for n in range(3, 100):
        relay.publish(epoch, fragment(n))
    slow = relay.latest(epoch, 2)
    assert slow.reset_decoder and slow.sequence == 99
    assert [frame.sequence for frame in slow.frames] == [0, 99]
    assert relay.retained == len(init()) + len(fragment(99))
    assert relay.close(epoch) and relay.retained == 0


def test_generation_and_client_isolation():
    relay = LiveRelay()
    old = relay.open(3, "old")
    other = relay.open(4, "other")
    relay.publish(other, init())
    relay.publish(other, fragment(1))
    with pytest.raises(MediaFault):
        relay.open(3, "new")
    assert relay.current(3, "new") is None
    assert relay.close(old)
    new = relay.open(3, "new")
    for stale in (old, Epoch(3, "new"), Epoch(4, "other")):
        with pytest.raises(MediaFault):
            relay.publish(stale, init())
        with pytest.raises(MediaFault):
            relay.latest(stale)
        assert not relay.close(stale)
    assert relay.latest(other).sequence == 1
    assert relay.current(3, "new") is new
    assert relay.latest(new) is None


@pytest.mark.parametrize("bad", [fragment(1), b"bad"])
def test_invalid_publisher_clears_only_its_channel(bad):
    relay = LiveRelay()
    first = relay.open(3, "one")
    second = relay.open(4, "two")
    relay.publish(second, init())
    relay.publish(second, fragment(1))
    with pytest.raises(MediaFault):
        relay.publish(first, bad)
    assert relay.current(3, "one") is None
    assert relay.latest(second).sequence == 1


@pytest.mark.parametrize("bad", [init(), fragment(1), fragment(2, 999), fragment(2, 1000)])
def test_duplicate_or_nonmonotonic_publisher_is_closed(bad):
    relay = LiveRelay()
    epoch = relay.open(3, "one")
    relay.publish(epoch, init())
    relay.publish(epoch, fragment(1))
    with pytest.raises(MediaFault):
        relay.publish(epoch, bad)
    assert relay.retained == 0 and relay.current(3, "one") is None


def test_budgets_and_invalid_reader_cursor_are_isolated():
    relay = LiveRelay(max_channels=2, max_retained=4 * HEADER.size + 20)
    first = relay.open(3, "one")
    second = relay.open(4, "two")
    with pytest.raises(MediaFault):
        relay.open(5, "three")
    relay.publish(first, init())
    relay.publish(first, fragment(1))
    relay.publish(second, init())
    with pytest.raises(MediaFault):
        relay.publish(second, fragment(1, payload=b"x" * 32))
    assert relay.current(4, "two") is None
    assert relay.retained == len(init()) + len(fragment(1))
    for cursor in (2, -1, True, "0"):
        with pytest.raises(MediaFault):
            relay.latest(first, cursor)
    assert relay.latest(first).sequence == 1
