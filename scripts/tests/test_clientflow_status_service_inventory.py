"""Regression for Viborg1 1250: 50 unit files, 25 positional states."""
from types import SimpleNamespace

from clientflow_runtime import status_agent


def _record(unit, active="active", load="loaded"):
    return f"Id={unit}\nLoadState={load}\nActiveState={active}\n"


def test_named_service_collection_survives_partial_reordered_results(tmp_path, monkeypatch):
    units = [f"clientflow-test-{i}.service" for i in range(25)]
    templates = [f"clientflow-template-{i}@.service" for i in range(25)]
    for name in units + templates:
        (tmp_path / name).touch()
    monkeypatch.setattr(status_agent, "ACTIVE_SYSTEMD_ROOT", tmp_path)
    calls = []

    def fake_run(command, *, timeout):
        calls.append(command)
        assert timeout == 15
        return SimpleNamespace(
            returncode=1,
            stdout="\n".join(_record(name) for name in reversed(units[:-1])),
        )

    monkeypatch.setattr(status_agent, "_safe_run", fake_run)
    assert status_agent._service_status() == {name: "active" for name in units[:-1]}
    assert len(calls) == 1
    assert calls[0][:3] == ["/usr/bin/systemctl", "show", "--all"]
    assert calls[0][calls[0].index("--") + 1:] == sorted(units)


def test_service_properties_do_not_fabricate_health_or_failure():
    units = {"ok.service", "failed.service", "missing.socket", "unknown.service",
             "duplicate.service", "absent.service", "masked.service"}
    output = "\n".join([
        _record("failed.service", "failed"),
        _record("ok.service"),
        _record("outside.service"),
        _record("missing.socket", "inactive", "not-found"),
        _record("unknown.service", "unknown"),
        _record("duplicate.service", "active"),
        _record("duplicate.service", "failed"),
        _record("masked.service", "inactive", "masked"),
    ])
    assert status_agent._parse_service_properties(output, units) == {
        "failed.service": "failed", "ok.service": "active",
        "missing.socket": "not-found", "masked.service": "error",
    }


def test_empty_or_malformed_service_output_is_unknown():
    assert status_agent._parse_service_properties("", {"unit.service"}) == {}
    assert status_agent._parse_service_properties(
        "Id=unit.service\nActiveState=active\n", {"unit.service"}
    ) == {}
    assert status_agent._parse_service_properties(
        _record("unit.service") + "\n" + _record("unit.service", "unknown"),
        {"unit.service"},
    ) == {}
