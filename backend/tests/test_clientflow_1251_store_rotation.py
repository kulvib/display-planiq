"""68K-E4 offline regression: exact source promotion and resumable store rotation."""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import pytest

from service1.clientflow_pilot_1251 import archive_inventory, RETAINED_IDS, SUCCESSOR_ID, closed_baseline_catalog
from service1.clientflow_releases import load_catalog
from scripts.clientflow_63d6_active_catalog_contract import verified_mode, projected_stable_1245
from scripts.reconcile_clientflow_1251_store import remaining_rotation, verify_archive, RotationDenied, REMOVE


def snapshot(ids):
    inventory = archive_inventory()
    rows = [{"release_id": i, "size_bytes": inventory[i]["size"], "sha256": inventory[i]["sha256"]}
            for i in sorted(ids, key=lambda identifier: inventory[identifier]["sequence"], reverse=True)]
    return dict(protected_latest=rows[:3], older_review_only=rows[3:],
                approved_count=len(rows), invalid_artifacts=[])


def test_closed_active_catalog_and_historical_projection():
    root = Path(__file__).resolve().parents[2]
    from service1.clientflow_closed_standard_1251 import closed_standard_catalog
    assert closed_baseline_catalog()["catalog_sequence"] == 1250
    assert load_catalog() == closed_standard_catalog()
    assert verified_mode(root) == "closed_1251_standard"
    assert projected_stable_1245(root)["releases"][0]["release_id"] == REMOVE[0]


def test_rotation_resumes_only_from_exact_oldest_first_states():
    keep = RETAINED_IDS - {SUCCESSOR_ID}
    for index in range(4):
        ids = keep | set(REMOVE[index:])
        assert remaining_rotation(snapshot(ids), archive_inventory()) == (list(REMOVE[index:]), False)
    assert remaining_rotation(snapshot(RETAINED_IDS), archive_inventory()) == ([], True)
    for ids in (keep | {REMOVE[0], REMOVE[2]}, keep | {SUCCESSOR_ID, REMOVE[2]},
                {SUCCESSOR_ID}, {REMOVE[0]}):
        with pytest.raises(RotationDenied):
            remaining_rotation(snapshot(ids), archive_inventory())
    bad = deepcopy(snapshot(keep))
    bad["protected_latest"][0]["sha256"] = "0"*64
    with pytest.raises(RotationDenied):
        remaining_rotation(bad, archive_inventory())


class Response(io.BytesIO):
    def __init__(self, value, url):
        super().__init__(value)
        self.url = url

    def geturl(self):
        return self.url


def test_archive_byte_gate_checks_size_hash_and_https_redirect():
    raw = b"fixture"
    pin = dict(archive_url="https://github.com/kulvib/display-planiq/releases/download/test/test.tar",
               size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    def fake(value, url="https://release-assets.githubusercontent.com/test"):
        return lambda *_args, **_kw: Response(value, url)
    target = io.BytesIO()
    assert verify_archive(pin, destination=target, opener=fake(raw)) == len(raw)
    assert target.getvalue() == raw
    for value, url in [(b"wrong!!", "https://release-assets.githubusercontent.com/test"),
                       (raw+b"x", "https://release-assets.githubusercontent.com/test"),
                       (raw[:-1], "https://release-assets.githubusercontent.com/test"),
                       (raw, "http://release-assets.githubusercontent.com/test"),
                       (raw, "https://example.com/test")]:
        with pytest.raises(RotationDenied):
            verify_archive(pin, opener=fake(value, url))
