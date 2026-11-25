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
from service1 import livestream_v2
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


if __name__ == "__main__":
    unittest.main()
