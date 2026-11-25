"""63D-74 negative admission tests; physical playback is a separate gate."""
import pytest

from service1.livestream_wss_admission import (
    Admission, MAX_PUBLISHERS, MAX_VIEWERS, MAX_VIEWERS_PER_CLIENT,
    TICKET_PROTOCOL, TICKET_TTL, TicketCapacity, TicketStore, ViewerBinding,
    canonical_generation, offered_ticket,
)

GEN = "62b641a3-bdad-4454-a5fd-cfb8e6774582"
OTHER = "7d32b769-b480-4dd3-8828-0f05267486a5"


def binding(client=3, generation=GEN):
    return ViewerBinding(client, generation, "viewer-1", 7, 2, "login-binding")


def test_ticket_expiry_capacity_and_replay():
    now = [0.]
    store = TicketStore(clock=lambda: now[0], capacity=1)
    raw = store.issue(binding())
    assert offered_ticket(TICKET_PROTOCOL + ", " + raw) == raw
    with pytest.raises(TicketCapacity):
        store.issue(binding())
    assert store.consume(raw, client_id=3, generation_id=GEN) == binding()
    assert store.consume(raw, client_id=3, generation_id=GEN) is None
    raw = store.issue(binding())
    now[0] = TICKET_TTL
    assert store.consume(raw, client_id=3, generation_id=GEN) is None
    assert store.issue(binding()) != raw


@pytest.mark.parametrize("client,generation", [(4, GEN), (3, OTHER)])
def test_wrong_target_also_consumes_ticket(client, generation):
    store = TicketStore()
    raw = store.issue(binding())
    assert store.consume(raw, client_id=client, generation_id=generation) is None
    assert store.consume(raw, client_id=3, generation_id=GEN) is None


def test_exact_protocol_and_generation():
    raw = TicketStore().issue(binding())
    for value in ("", raw, TICKET_PROTOCOL, TICKET_PROTOCOL + ", " + raw + ", extra",
                  "other, " + raw, TICKET_PROTOCOL + ", " + raw + "="):
        assert offered_ticket(value) is None
    assert canonical_generation(GEN)
    assert not canonical_generation(GEN.upper())
    assert not canonical_generation("x")
    with pytest.raises(ValueError):
        TicketStore().issue(binding(generation="bad"))


def test_admission_budgets_and_release():
    a = Admission()
    for cid in range(1, MAX_PUBLISHERS + 1):
        assert a.admit_publisher(cid)
    assert not a.admit_publisher(1)
    assert not a.admit_publisher(100)
    a.release_publisher(1)
    assert a.admit_publisher(100)
    handles = [a.admit_viewer(3) for _ in range(MAX_VIEWERS_PER_CLIENT)]
    assert all(h is not None for h in handles)
    assert a.admit_viewer(3) is None
    for cid in range(10, 10 + MAX_VIEWERS - MAX_VIEWERS_PER_CLIENT):
        handles.append(a.admit_viewer(cid))
    assert all(h is not None for h in handles)
    assert a.admit_viewer(99) is None
    a.release_viewer(handles[0])
    assert a.admit_viewer(99) is not None
