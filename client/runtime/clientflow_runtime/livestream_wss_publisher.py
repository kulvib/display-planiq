"""Independent credential-bearing publisher worker; no HLS upload blocking.

Only the latest fresh, atomic pair is sent. On transport loss, stale media,
capture reset or generation change, close the socket and retry with backoff.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import time
from uuid import UUID

from .config import DomainCredential
from .constants import Domain
from .livestream_fmp4 import HEADER, read_latest
from .livestream_paths import DESIRED_PATH, GENERATIONS_DIR
from .net import DomainTransport, backoff_seconds


def desired_generation():
    try:
        data = json.loads(DESIRED_PATH.read_text(encoding="utf-8"))
        generation = data.get("generation_id")
        if data.get("desired") == "running" and str(UUID(generation)) == generation:
            return generation
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def latest(generation):
    try:
        return read_latest(GENERATIONS_DIR / generation / "out", max_age_seconds=3)
    except (OSError, ValueError):
        return None


async def publish_once(transport, generation, connect, tls, stopping):
    pair = latest(generation)
    if pair is None:
        return
    path = f"/api/livestream-agent/clients/{transport.credential.client_id}/generations/{generation}/media/ws"
    headers = await asyncio.to_thread(transport.websocket_headers)
    if stopping.is_set() or desired_generation() != generation:
        return
    async with connect(transport.websocket_url(path), extra_headers=headers, ssl=tls,
                       open_timeout=5, close_timeout=1, ping_interval=15,
                       ping_timeout=5, max_size=4096, max_queue=2,
                       compression=None, write_limit=65536) as ws:
        # Only a demand signal from the authenticated TLS endpoint permits
        # media upload. Keep no in-flight media during idle. A close after
        # demand ends causes a fresh epoch on reconnect.
        while not stopping.is_set() and desired_generation() == generation:
            try:
                control = await asyncio.wait_for(ws.recv(), 0.5)
            except asyncio.TimeoutError:
                continue
            if control != "media:on":
                return
            break
        else:
            return
        previous = None
        while not stopping.is_set() and desired_generation() == generation:
            pair = latest(generation)
            if pair is None:
                return
            init, fragment = pair
            fields = HEADER.unpack_from(fragment)
            sequence, timestamp = fields[4], fields[5]
            if previous is None:
                await asyncio.wait_for(ws.send(init), 2)
            elif init != previous[0] or sequence < previous[1] or timestamp < previous[2]:
                return
            if previous is None or sequence > previous[1]:
                await asyncio.wait_for(ws.send(fragment), 2)
                previous = (init, sequence, timestamp)
            elif timestamp != previous[2]:
                return
            if ws.closed:
                return
            await asyncio.sleep(0.2)


async def run(stopping):
    # Legacy client API matches the hash-locked 12.0 runtime.
    from websockets.legacy.client import connect
    credential = DomainCredential.load(Domain.LIVESTREAM)
    transport = DomainTransport(credential)
    tls = ssl.create_default_context(cafile=credential.tls_ca_file)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    attempt = 0
    while not stopping.is_set():
        generation = desired_generation()
        if generation is None or latest(generation) is None:
            attempt = 0
            await asyncio.sleep(1)
            continue
        start = time.monotonic()
        try:
            await publish_once(transport, generation, connect, tls, stopping)
        except Exception:
            # No credentials, URLs or media payload in logs.
            pass
        if time.monotonic() - start > 15:
            attempt = 0
        delay = backoff_seconds(attempt)
        attempt += 1
        until = time.monotonic() + delay
        while (not stopping.is_set() and desired_generation() == generation
               and time.monotonic() < until):
            await asyncio.sleep(0.5)


def worker(stopping):
    try:
        asyncio.run(run(stopping))
    except Exception:
        # This optional transport must never terminate the HLS uploader.
        return
