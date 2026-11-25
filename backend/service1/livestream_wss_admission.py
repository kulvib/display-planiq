"""Independent, bounded Livestream WSS admission and one-use ticket store.

No dependency on Remote Desktop, terminal, DB, or web framework. The caller
must check the active browser login, viewer lease and current generation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import secrets
import threading
import time
from uuid import UUID

TICKET_PROTOCOL = "clientflow-livestream-v1"
TICKET_TTL = 30
MAX_TICKETS = 128
MAX_PUBLISHERS = 4
MAX_VIEWERS = 8
MAX_VIEWERS_PER_CLIENT = 3
_TICKET_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def canonical_generation(value: str) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


@dataclass(frozen=True)
class ViewerBinding:
    client_id: int
    generation_id: str
    viewer_id: str
    user_id: int
    token_version: int
    auth_session_binding: str


class TicketCapacity(RuntimeError):
    pass


class TicketStore:
    def __init__(self, *, clock=time.monotonic, capacity=MAX_TICKETS):
        if type(capacity) is not int or not 1 <= capacity <= MAX_TICKETS:
            raise ValueError("invalid ticket capacity")
        self._clock = clock
        self._capacity = capacity
        self._lock = threading.Lock()
        self._tickets = {}

    @staticmethod
    def _key(ticket):
        return hashlib.sha256(ticket.encode("ascii")).digest()

    def _prune(self, now):
        for key, (expiry, _) in list(self._tickets.items()):
            if expiry <= now:
                del self._tickets[key]

    def issue(self, binding: ViewerBinding) -> str:
        if (type(binding.client_id) is not int or binding.client_id < 1
                or type(binding.user_id) is not int or binding.user_id < 1
                or not canonical_generation(binding.generation_id)
                or not isinstance(binding.viewer_id, str)
                or not 1 <= len(binding.viewer_id) <= 120
                or binding.viewer_id.strip() != binding.viewer_id
                or not binding.auth_session_binding):
            raise ValueError("invalid viewer binding")
        with self._lock:
            now = self._clock()
            self._prune(now)
            if len(self._tickets) >= self._capacity:
                raise TicketCapacity("ticket capacity")
            raw = secrets.token_urlsafe(32)
            self._tickets[self._key(raw)] = (now + TICKET_TTL, binding)
            return raw

    def consume(self, raw, *, client_id, generation_id):
        if not isinstance(raw, str) or not _TICKET_RE.fullmatch(raw):
            return None
        with self._lock:
            now = self._clock()
            self._prune(now)
            record = self._tickets.pop(self._key(raw), None)
        if record is None:
            return None
        _, binding = record
        if binding.client_id != client_id or binding.generation_id != generation_id:
            return None
        return binding


def offered_ticket(header: str):
    """No cookie, URL or general access-token fallback."""
    if not isinstance(header, str) or len(header) > 128:
        return None
    protocols = [part.strip() for part in header.split(",")]
    if (len(protocols) != 2 or protocols[0] != TICKET_PROTOCOL
            or not _TICKET_RE.fullmatch(protocols[1])):
        return None
    return protocols[1]


class Admission:
    """Single event-loop owner; includes pending auth and in-flight sends."""
    def __init__(self):
        self.publishers = set()
        self.viewers = {}

    def admit_publisher(self, client_id):
        if client_id in self.publishers or len(self.publishers) >= MAX_PUBLISHERS:
            return False
        self.publishers.add(client_id)
        return True

    def release_publisher(self, client_id):
        self.publishers.discard(client_id)

    def admit_viewer(self, client_id):
        if (len(self.viewers) >= MAX_VIEWERS
                or sum(cid == client_id for cid in self.viewers.values()) >= MAX_VIEWERS_PER_CLIENT):
            return None
        handle = object()
        self.viewers[handle] = client_id
        return handle

    def release_viewer(self, handle):
        self.viewers.pop(handle, None)
