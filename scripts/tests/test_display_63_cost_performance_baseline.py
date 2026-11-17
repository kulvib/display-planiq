"""Fase 63: offline-only, no credential propagation, no unearned cost/performance claims."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import display_63_cost_performance_baseline as perf


def row(at, method="POST", path="/api/display-agent/clients/3/presence", code=200, ms=4):
    return {
        "timestamp": at,
        "message": f'clientIP="123.123.123.123" requestID="private" responseTimeMS={ms} userAgent="Private user"',
        "labels": [{"name": "type", "value": "request"},
                   {"name": "method", "value": method},
                   {"name": "statusCode", "value": str(code)},
                   {"name": "path", "value": path}],
    }


def sample():
    start = datetime(2026, 11, 17, tzinfo=timezone.utc)
    return [row(start.isoformat(), path="/api/display-agent/clients/3/status"),
            row((start + timedelta(seconds=310)).isoformat(), path="/api/display-agent/clients/3/presence"),
            row((start + timedelta(seconds=310)).isoformat(), method="HEAD", path="/health"),
            row((start + timedelta(seconds=310)).isoformat(), method="GET", path="/health/db", ms=17)]


def test_63_report_never_contains_identity_or_url_or_secrets():
    report = perf.analyze(sample())
    serialized = json.dumps(report)
    for forbidden in ('123.123.123.123', 'requestID', 'clients/3', 'Private user', 'api.display.planiq.dk'):
        assert forbidden not in serialized
    assert report["observed_distinct_clients_in_paths"] == 1
    assert report["observed_timestamped_requests"] == 4
    assert report["request_categories"]["backend_db_readiness"]["scales_with_clients"] is False
    assert report["request_categories"]["client_connectivity"]["scales_with_clients"] is True


def test_63_only_observed_data_models_are_linear_not_capacity_proofs():
    report = perf.analyze(sample())
    models = report["linear_traffic_scenarios"]
    assert [m["clients"] for m in models] == [1, 10, 50, 100]
    assert models[0]["projected_requests_per_day"] < models[3]["projected_requests_per_day"]
    assert all(m["projected_db_statements_per_day"] is None for m in models)
    assert all(m["capacity_test_passed"] is False for m in models)
    assert report["real_100_client_load_test_passed"] is False
    assert report["cost_savings_proven"] is False


def test_63_shared_token_without_client_identity_does_not_invent_client_count():
    rows = sample()
    rows[0]["labels"][-1]["value"] = "/api/client-auth/token"
    rows[1]["labels"][-1]["value"] = "/api/clientflow-update/token"
    report = perf.analyze(rows)
    assert report["observed_distinct_clients_in_paths"] == 0
    assert report["linear_traffic_scenarios"] == []


def test_63_correctly_counts_errors_and_latency_percentiles():
    rows = sample()
    rows[0]["labels"][-2]["value"] = "502"
    rows[1]["message"] = "responseTimeMS=50"
    result = perf.analyze(rows)
    assert result["request_categories"]["client_status"]["errors_502_503"] == 1
    assert result["request_categories"]["client_presence"]["p95_response_ms"] == 50


def test_63_minimum_sample_window_is_enforced():
    with pytest.raises(perf.PerformanceStop, match="sample_too_short"):
        perf.analyze([sample()[0], row("2026-11-17T00:00:20Z")])


def test_63_missing_request_records_stops():
    with pytest.raises(perf.PerformanceStop, match="no_timestamped_requests"):
        perf.analyze([{"message": "mysecret=123"}])


def test_63_plain_uvicorn_lines_and_query_are_sanitized():
    rows = [
        '2026-11-17T12:00:00Z INFO: "GET /api/status-agent/clients/3/status?token=PRIVATE HTTP/1.1" 200',
        '2026-11-17T12:08:00Z INFO: "HEAD /health HTTP/1.1" 405',
    ]
    report = perf.analyze(rows)
    assert report["observed_distinct_clients_in_paths"] == 1
    assert 'PRIVATE' not in json.dumps(report)
    assert report["request_categories"]["client_connectivity"]["errors_4xx"] == 1


def test_63_render_db_hotpath_aggregation_is_whitelisted_only():
    rows = sample()
    rows.append({"message": 'db_hotpath_summary {"categories":{"shared_presence":{"requests":10,"statements":0},"secret-token":{"requests":3}}}'})
    report = perf.analyze(rows)
    assert report["db_hotpath_windows_observed"] == 1
    assert report["db_hotpath_categories"]["shared_presence"]["requests"] == 10
    assert 'secret-token' not in json.dumps(report)


def test_63_export_json_array_object_and_ndjson(tmp_path):
    data = sample()
    for name, content in (("array.json", json.dumps(data)),
                          ("object.json", json.dumps({"logs": data}, indent=2)),
                          ("rows.ndjson", "\n".join(json.dumps(x) for x in data))):
        path = tmp_path / name
        path.write_text(content)
        assert len(list(perf._read_rows(path))) == 4


def test_63_non_request_app_logs_do_not_pollute_http_counts():
    records = sample()
    records.append({"timestamp": "2026-11-17T00:05:00Z", "message": "responseTimeMS=10", "labels": [{"name": "type", "value": "app"},
                                                                                           {"name": "statusCode", "value": "200"}]})
    assert perf.analyze(records)["observed_timestamped_requests"] == 4


def test_63_rejects_symlink_and_empty_export(tmp_path):
    path = tmp_path / "empty"
    path.touch()
    with pytest.raises(perf.PerformanceStop, match="unsafe"):
        list(perf._read_rows(path))
    target = tmp_path / "shortcut"
    target.symlink_to(path)
    with pytest.raises(perf.PerformanceStop, match="unsafe"):
        list(perf._read_rows(target))


def test_63_asset_sizes_do_not_claim_frontend_load_time(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "app.js").write_bytes(b"console.log('fine');" * 50)
    (root / "style.css").write_text("body{}" * 100)
    report = perf.frontend_baseline(root)
    assert report["groups"]["javascript"]["files"] == 1
    assert report["groups"]["javascript"]["gzip_bytes"] < report["groups"]["javascript"]["uncompressed_bytes"]
    assert report["frontend_p95_load_time_ms"] is None


def test_63_rejects_symlinked_frontend_asset(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "image.js").symlink_to(tmp_path / "outside")
    with pytest.raises(perf.PerformanceStop, match="symlinked"):
        perf.frontend_baseline(root)


def test_63_cli_does_not_echo_invalid_input_name(tmp_path, capsys):
    path = tmp_path / "secret_password_that_should_not_leak"
    path.write_text('invalid log')
    assert perf.main(["--input-file", str(path)]) == 2
    captured = capsys.readouterr()
    assert 'secret_password' not in captured.err
    assert 'no_timestamped_requests' in captured.err


def test_63_static_category_cardinality_is_bounded():
    values = {perf.category_for(f"/api/private-unique-path-{i}", "GET")[0] for i in range(1000)}
    assert values == {"admin_or_api"}
    assert perf.category_for("/api/client-auth/token", "POST") == ("client_token", True)
    assert perf.category_for("/health/db", "GET") == ("backend_db_readiness", False)
