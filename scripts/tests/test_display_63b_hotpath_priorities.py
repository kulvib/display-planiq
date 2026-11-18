"""Identity-safe offline hotpath ranking is not an estimate of real cost."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_63b_hotpath_priorities as prioritizer
import display_63_cost_performance_baseline as baseline


def example():
    return {
        "schema": baseline.SCHEMA,
        "db_hotpath_windows_observed": 3,
        "log_export_complete": False,
        "db_hotpath_categories": {
            "shared_status": {"requests": 30, "statements": 90, "selects": 30,
                              "checkouts": 60, "cursor_ms": 540},
            "shared_presence": {"requests": 300, "statements": 0, "selects": 0,
                                "checkouts": 0, "cursor_ms": 0},
            "remote_desktop_ws_recheck": {"requests": 0, "websocket_rechecks": 20,
                                          "statements": 20, "selects": 20,
                                          "checkouts": 20, "cursor_ms": 200},
            "token private and IP": {"requests": 100, "statements": 500000},
        },
    }


def test_63b_rank_sql_work_with_aggregate_verified_categories():
    output = prioritizer.priorities(example())
    assert output["status"] == "MEASURED_PRIORITIES_NOT_COST_PROOF"
    assert [row["category"] for row in output["hotpaths_descending_observed_statements"]] == [
        "shared_status", "remote_desktop_ws_recheck", "shared_presence",
    ]
    assert output["measured_hotpath_statements"] == 110
    assert output["hotpaths_descending_observed_statements"][0]["statements_per_operation"] == 3
    assert output["hotpaths_descending_observed_statements"][1]["security_sensitive_revocation_path"] is True
    assert output["measured_money_savings"] is None
    assert "token private" not in json.dumps(output)


def test_63b_missing_data_never_proves_zero_sql():
    item = example()
    item["db_hotpath_windows_observed"] = 0
    item["db_hotpath_categories"] = {}
    output = prioritizer.priorities(item)
    assert output["status"] == "INSUFFICIENT_DB_EVIDENCE"
    assert "no_valid_db_hotpath_rows" in output["warnings"]
    assert "insufficient_db_summary_windows" in output["warnings"]


def test_63b_invalid_and_infinite_metrics_are_discarded():
    item = example()
    item["db_hotpath_categories"]["shared_status"]["cursor_ms"] = float("nan")
    output = prioritizer.priorities(item)
    assert "shared_status" not in [x["category"] for x in output["hotpaths_descending_observed_statements"]]


def test_63b_cli_requires_real_db_observation(tmp_path, capsys):
    report = tmp_path / "baseline.json"
    item = example()
    item["db_hotpath_windows_observed"] = 0
    report.write_text(json.dumps(item))
    assert prioritizer.main(["--baseline", str(report)]) == 2
    assert "INSUFFICIENT_DB_EVIDENCE" in capsys.readouterr().out
    item["db_hotpath_windows_observed"] = 3
    report.write_text(json.dumps(item))
    assert prioritizer.main(["--baseline", str(report)]) == 0


def test_63b_errors_never_include_local_secrets(tmp_path, capsys):
    bogus = tmp_path / "contains-my-secret-credential.json"
    bogus.write_text("bogus")
    assert prioritizer.main(["--baseline", str(bogus)]) == 2
    assert "contains-my-secret-credential" not in capsys.readouterr().err
