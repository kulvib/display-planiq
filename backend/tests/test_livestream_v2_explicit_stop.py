from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "ci-only-secret-key-with-at-least-thirty-two-characters")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:5173")

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from service1.models import Client
from service1.livestream_v2_models import LivestreamV2Command, LivestreamV2Generation, LivestreamV2Viewer
from service1 import livestream_v2, display_control
from service1.client_domain_models import ClientCommand
from service1.routers import livestream_v2 as livestream_v2_router


class LivestreamV2ExplicitStopTests(unittest.TestCase):
    CLIENT_ID = 23
    GENERATION_ID = "11111111-1111-1111-1111-111111111111"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.safe_dir_patch = patch.object(
            livestream_v2,
            "safe_client_dir",
            side_effect=lambda client_id: str(Path(self.temp_dir.name) / str(client_id)),
        )
        self.safe_dir_patch.start()
        self.addCleanup(self.safe_dir_patch.stop)

    @staticmethod
    def principal():
        return SimpleNamespace(id=7, role="admin", is_client=False)

    def seed_running_with_viewer(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Client(
                    id=self.CLIENT_ID,
                    name="Pilot 23",
                    status="approved",
                    livestream_status="running",
                    livestream_process_status="running",
                    livestream_desired_state="running",
                )
            )
            session.add(
                LivestreamV2Generation(
                    id=self.GENERATION_ID,
                    client_id=self.CLIENT_ID,
                    state="running",
                    requested_action="start",
                )
            )
            session.add(
                LivestreamV2Viewer(
                    client_id=self.CLIENT_ID,
                    viewer_id="viewer-a",
                    principal_key="admin:7",
                    source="test",
                )
            )
            session.commit()

    def request_explicit_stop(self, session: Session) -> None:
        generation, command = livestream_v2.request_stop(
            session,
            self.CLIENT_ID,
            source="browser_manual_stop",
            explicit=True,
        )
        self.assertIsNotNone(generation)
        self.assertIsNotNone(command)
        self.assertEqual(generation.state, "stopping")
        client = session.get(Client, self.CLIENT_ID)
        self.assertEqual(client.livestream_stop_reason, "explicit_stop:browser_manual_stop")
        self.assertEqual(client.livestream_desired_state, "stopped")

        livestream_v2.request_stop(
            session,
            self.CLIENT_ID,
            source="viewer_grace_expired",
        )
        self.assertEqual(client.livestream_stop_reason, "explicit_stop:browser_manual_stop")

    def test_explicit_stop_blocks_active_viewer_until_manual_start(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            livestream_v2.generation_stopped(
                session,
                client_id=self.CLIENT_ID,
                generation_id=self.GENERATION_ID,
                error_code=None,
            )
            session.commit()

        with Session(self.engine) as session:
            viewer, generation, command = livestream_v2.viewer_heartbeat(
                session,
                client_id=self.CLIENT_ID,
                principal=self.principal(),
                viewer_id="viewer-a",
                source="test-heartbeat",
            )
            self.assertIsNotNone(viewer)
            self.assertIsNone(generation)
            self.assertIsNone(command)
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertIsNone(livestream_v2.reconcile_viewer_lifecycle(session, self.CLIENT_ID))
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))

            generation, command = livestream_v2.request_start(
                session,
                self.CLIENT_ID,
                source="browser_manual_start",
            )
            self.assertEqual(generation.state, "starting")
            self.assertIsNotNone(command)
            client = session.get(Client, self.CLIENT_ID)
            self.assertIsNone(client.livestream_stop_reason)
            self.assertEqual(client.livestream_desired_state, "running")

    def test_agent_stop_ack_does_not_restart_active_viewer_after_explicit_stop(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            session.commit()

        with (
            patch.object(livestream_v2_router, "engine", self.engine),
            patch.object(livestream_v2_router, "require_agent_token"),
        ):
            livestream_v2_router.agent_generation_stopped(
                self.CLIENT_ID,
                self.GENERATION_ID,
                livestream_v2_router.StoppedBody(error_code=None),
                authorization="Bearer test",
            )

        with Session(self.engine) as session:
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))

    def test_status_recovery_does_not_restart_after_explicit_stop(self) -> None:
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            recovered = livestream_v2.reconcile_stopping_generation_from_agent_status(
                session,
                client_id=self.CLIENT_ID,
                status_payload={
                    "producer": {
                        "state": "stopped",
                        "pid": None,
                        "generation_id": self.GENERATION_ID,
                    },
                    "uploader": {
                        "state": "idle",
                        "generation_id": self.GENERATION_ID,
                    },
                },
            )
            self.assertTrue(recovered)
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))


    def _seed_cancelled_start_stop(self, session, *, completed=True):
        old = session.get(LivestreamV2Generation, self.GENERATION_ID)
        old.state = "stopped"
        old.stopped_at = livestream_v2._now()
        session.add(old)
        target = LivestreamV2Generation(
            id="22222222-2222-2222-2222-222222222222",
            client_id=self.CLIENT_ID,
            state="stopping",
            requested_action="start",
            created_at=old.created_at + timedelta(seconds=1),
        )
        session.add(target)
        client = session.get(Client, self.CLIENT_ID)
        client.livestream_desired_state = "stopped"
        client.livestream_status = "stopped"
        client.livestream_process_status = "stopped"
        client.livestream_stop_reason = "viewer_grace_expired"
        session.add(client)
        session.add(LivestreamV2Command(
            id="33333333-3333-3333-3333-333333333333",
            client_id=self.CLIENT_ID,
            command_type="start",
            payload={"generation_id": target.id},
            state="cancelled",
            attempts=0,
            error_code="superseded_intent",
        ))
        session.add(LivestreamV2Command(
            id="44444444-4444-4444-4444-444444444444",
            client_id=self.CLIENT_ID,
            command_type="stop",
            payload={"generation_id": target.id},
            state="completed" if completed else "leased",
            attempts=1,
            result={"stopped": True} if completed else None,
        ))
        session.flush()
        return target, {
            "producer": {"state": "stopped", "pid": None, "generation_id": old.id},
            "uploader": {"state": "idle", "generation_id": old.id},
        }

    def test_cancelled_unclaimed_start_recovers_from_previous_stopped_producer(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            target, payload = self._seed_cancelled_start_stop(session)
            self.assertTrue(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            self.assertEqual(target.state, "stopped")
            current = livestream_v2.current_generation(session, self.CLIENT_ID)
            self.assertIsNotNone(current)
            self.assertEqual(current.state, "starting")
            self.assertNotEqual(current.id, target.id)
            self.assertFalse(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            self.assertEqual(livestream_v2.current_generation(session, self.CLIENT_ID).id, current.id)

    def test_mismatched_producer_requires_completed_stop_and_unclaimed_start(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            target, payload = self._seed_cancelled_start_stop(session, completed=False)
            self.assertFalse(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            stop = session.get(LivestreamV2Command, "44444444-4444-4444-4444-444444444444")
            stop.state = "completed"
            stop.result = {"stopped": True}
            session.add(stop)
            start = session.get(LivestreamV2Command, "33333333-3333-3333-3333-333333333333")
            start.attempts = 1
            session.add(start)
            self.assertFalse(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            self.assertEqual(target.state, "stopping")

    def test_mismatch_cannot_reconcile_live_capture_or_explicit_stop_restart(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            target, payload = self._seed_cancelled_start_stop(session)
            payload["producer"]["pid"] = 123
            self.assertFalse(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            payload["producer"]["pid"] = None
            payload["uploader"]["state"] = "uploading"
            self.assertFalse(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            payload["uploader"]["state"] = "idle"
            client = session.get(Client, self.CLIENT_ID)
            client.livestream_stop_reason = "explicit_stop:browser_manual_stop"
            session.add(client)
            self.assertTrue(livestream_v2.reconcile_stopping_generation_from_agent_status(
                session, client_id=self.CLIENT_ID, status_payload=payload,
            ))
            self.assertEqual(target.state, "stopped")
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))

    def test_duplicate_old_stop_ack_does_not_clear_new_generation(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            target, _ = self._seed_cancelled_start_stop(session)
            target.state = "starting"
            client = session.get(Client, self.CLIENT_ID)
            client.livestream_desired_state = "running"
            client.livestream_status = "starting"
            session.add(target)
            session.add(client)
            with patch.object(livestream_v2, "_clear_hls_media") as clear_media:
                livestream_v2.generation_stopped(
                    session, client_id=self.CLIENT_ID,
                    generation_id=self.GENERATION_ID, error_code=None,
                )
                clear_media.assert_not_called()
            self.assertEqual(client.livestream_desired_state, "running")
            self.assertEqual(client.livestream_status, "starting")
            self.assertEqual(target.state, "starting")

    def _complete_resolution(self, session, *, width=1920, height=1080, command_type="apply_resolution", ok=True):
        import uuid
        now = display_control.utcnow()
        command_id = str(uuid.uuid4())
        session.add(ClientCommand(
            id=command_id, client_id=self.CLIENT_ID, domain="display",
            command_type=command_type, status="succeeded",
            idempotency_key=command_id, requested_at=now, available_at=now,
            expires_at=now + timedelta(seconds=120), completed_at=now,
            result={"ok": ok, "output": "HDMI-1", "width": width, "height": height},
        ))
        session.flush()
        display_control.apply_display_command_completion(
            session, client_id=self.CLIENT_ID, command_id=command_id,
        )

    def test_confirmed_resize_restarts_once_without_browser_command(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            client = session.get(Client, self.CLIENT_ID)
            client.display_resolution_current_output = "HDMI-1"
            client.display_resolution_current_width = 2560
            client.display_resolution_current_height = 1080
            session.add(client)
            session.flush()
            self._complete_resolution(session)
            session.flush()
            current = livestream_v2.current_generation(session, self.CLIENT_ID)
            self.assertNotEqual(current.id, self.GENERATION_ID)
            self.assertEqual(current.state, "starting")
            self.assertEqual(session.get(LivestreamV2Generation, self.GENERATION_ID).state, "superseded")
            self._complete_resolution(session)
            session.flush()
            self.assertEqual(livestream_v2.current_generation(session, self.CLIENT_ID).id, current.id)
            self.assertEqual(client.display_resolution_current_width, 1920)
            self._complete_resolution(session, width=2560)
            session.flush()
            self.assertNotEqual(livestream_v2.current_generation(session, self.CLIENT_ID).id, current.id)

    def test_resize_never_revives_explicit_stop(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self.request_explicit_stop(session)
            self._complete_resolution(session)
            self.assertTrue(livestream_v2.explicit_stop_latched(session, self.CLIENT_ID))
            self.assertEqual(livestream_v2.current_generation(session, self.CLIENT_ID).state, "stopping")
            livestream_v2.generation_stopped(session, client_id=self.CLIENT_ID,
                generation_id=self.GENERATION_ID, error_code=None)
            self._complete_resolution(session, width=2560)
            self.assertIsNone(livestream_v2.current_generation(session, self.CLIENT_ID))

    def test_initial_detect_and_failed_resize_are_not_restart_events(self):
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            self._complete_resolution(session, command_type="detect_resolution")
            self._complete_resolution(session, width=2560, ok=False)
            self.assertEqual(livestream_v2.current_generation(session, self.CLIENT_ID).id, self.GENERATION_ID)

    def test_manifest_generation_is_bound_to_authenticated_upload(self):
        import hashlib
        from service1.routers.livestream_media import manifest_generation
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            payload = b"#EXTM3U\n#PLANIQ-GENERATION:11111111-2222-3333-4444-555555555555\n#EXTINF:1,\nsegment-000000000.ts\n"
            media = b"fixture-media"
            livestream_v2.write_hls_file(session, client_id=self.CLIENT_ID, generation_id=self.GENERATION_ID,
                filename="segment-000000000.ts", payload=media, sha256=hashlib.sha256(media).hexdigest(), sequence=0)
            path = livestream_v2.write_hls_file(
                session, client_id=self.CLIENT_ID, generation_id=self.GENERATION_ID,
                filename="index.m3u8", payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(), sequence=0,
            )
            self.assertEqual(manifest_generation(path.read_bytes()), self.GENERATION_ID)
            self.assertEqual(path.read_bytes().count(b"#PLANIQ-GENERATION:"), 1)
            self.assertIn(f"g-{self.GENERATION_ID}-segment-000000000.ts".encode(), path.read_bytes())

    def test_generation_media_names_cannot_alias_after_restart(self):
        import hashlib
        from fastapi import HTTPException
        from service1.routers.livestream_media import manifest_generation, is_public_hls_filename
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            def upload(generation, name, data):
                return livestream_v2.write_hls_file(
                    session, client_id=self.CLIENT_ID, generation_id=generation,
                    filename=name, payload=data, sha256=hashlib.sha256(data).hexdigest(),
                    sequence=0,
                )

            segment = "segment-000000000.ts"
            manifest = b"#EXTM3U\n#EXTINF:1,\nsegment-000000000.ts\n"
            old_file = upload(self.GENERATION_ID, segment, b"old media")
            index = upload(self.GENERATION_ID, "index.m3u8", manifest)
            old_playlist = index.read_bytes()
            new, _ = livestream_v2.request_restart(
                session, self.CLIENT_ID, source="test_resolution_change",
            )
            session.flush()
            new_file = upload(new.id, segment, b"new media")
            upload(new.id, "index.m3u8", manifest)
            self.assertNotEqual(old_file, new_file)
            self.assertEqual(old_file.read_bytes(), b"old media")
            self.assertEqual(new_file.read_bytes(), b"new media")
            self.assertIn(old_file.name.encode(), old_playlist)
            self.assertIn(new_file.name.encode(), index.read_bytes())
            self.assertEqual(manifest_generation(index.read_bytes()), new.id)
            self.assertTrue(is_public_hls_filename(new_file.name))
            self.assertFalse(is_public_hls_filename(".stream_generation.json"))
            self.assertFalse(is_public_hls_filename("../" + new_file.name))
            with self.assertRaises(HTTPException) as stale:
                upload(self.GENERATION_ID, segment, b"late old upload")
            self.assertEqual(stale.exception.status_code, 409)
            self.assertEqual(new_file.read_bytes(), b"new media")
            livestream_v2._clear_hls_media(self.CLIENT_ID)
            self.assertFalse(old_file.exists())
            self.assertFalse(new_file.exists())
            self.assertFalse(index.exists())

    def test_rolling_retention_preserves_current_playlist_and_grace(self):
        import hashlib
        from fastapi import HTTPException
        self.seed_running_with_viewer()
        with Session(self.engine) as session:
            def upload(name, payload):
                return livestream_v2.write_hls_file(session, client_id=self.CLIENT_ID,
                    generation_id=self.GENERATION_ID, filename=name, payload=payload,
                    sha256=hashlib.sha256(payload).hexdigest(), sequence=0)
            current = upload("segment-000000001.ts", b"current")
            old = upload("segment-000000002.ts", b"old")
            recent = upload("segment-000000003.ts", b"recent")
            index = upload("index.m3u8", b"#EXTM3U\n#EXTINF:1,\nsegment-000000001.ts\n")
            os.utime(current, (1, 1))
            os.utime(old, (1, 1))
            unrelated = current.parent / "operator-file"
            unrelated.write_bytes(b"untouched")
            newest = upload("segment-000000004.ts", b"new")
            self.assertTrue(current.exists())
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(newest.exists())
            self.assertEqual(unrelated.read_bytes(), b"untouched")
            original = index.read_bytes()
            with self.assertRaises(HTTPException) as missing:
                upload("index.m3u8", b"#EXTM3U\n#EXTINF:1,\nsegment-000000099.ts\n")
            self.assertEqual(missing.exception.status_code, 409)
            self.assertEqual(index.read_bytes(), original)
            with patch.object(livestream_v2, "MAX_HLS_CLIENT_FILES", 4):
                with self.assertRaises(HTTPException) as capacity:
                    upload("segment-000000005.ts", b"new")
                self.assertEqual(capacity.exception.status_code, 507)
            self.assertTrue(current.exists())
            self.assertTrue(recent.exists())


    def test_upload_reservations_bound_concurrent_clients_and_bytes(self):
        from fastapi import HTTPException
        route = livestream_v2_router
        with patch.object(route, "_upload_reservations", {}):
            for cid in range(1, 9):
                route._reserve_upload(cid, 1024)
            for cid in (1, 9):
                with self.assertRaises(HTTPException) as denied:
                    route._reserve_upload(cid, 1024)
                self.assertEqual(denied.exception.status_code, 429)
            route._upload_reservations.clear()
            route._reserve_upload(1, route.MAX_HLS_UPLOAD_RESERVED_BYTES)
            with self.assertRaises(HTTPException):
                route._reserve_upload(2, 1)


    def test_manifest_initialization_reference_is_generation_bound(self):
        from service1.routers.livestream_media import namespace_manifest_media
        content = b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1,\nsegment-000000000.m4s\n'
        result = namespace_manifest_media(content, self.GENERATION_ID)
        self.assertIn(f'URI="g-{self.GENERATION_ID}-init.mp4"'.encode(), result)
        self.assertIn(f"g-{self.GENERATION_ID}-segment-000000000.m4s".encode(), result)
        for tag in (
            b'#EXT-X-MAP:URI="../init.mp4"',
            b'#EXT-X-KEY:METHOD=AES-128,URI="https://invalid.example/key"',
            b'#EXT-X-MEDIA:TYPE=AUDIO,URI="https://invalid.example/audio"',
        ):
            with self.assertRaises(ValueError):
                namespace_manifest_media(b"#EXTM3U\n" + tag + b"\nsegment-000000000.ts\n", self.GENERATION_ID)


if __name__ == "__main__":
    unittest.main()
