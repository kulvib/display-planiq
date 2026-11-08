"""Operator CLI refuses maintenance bypass and never modifies source releases."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts import preflight_clientflow_1243_transitional_publication as cli
from scripts.tests.test_clientflow_1243_transitional_publication import _setup


def test_missing_quiescence_reports_blocker(tmp_path, monkeypatch, capsys):
    directory = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", raising=False)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert cli.main(["--artifact-dir", str(directory)]) == 1
    assert "CLIENTFLOW_1243_TRANSITION_PREFLIGHT=BLOCKED" in capsys.readouterr().err
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_successful_preflight_is_readonly_and_not_deployment_authorization(tmp_path, monkeypatch, capsys):
    directory = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIENTFLOW_FRESH_INSTALL_SUSPENDED", "1")
    for flag in ("CLIENTFLOW_1241_PILOT_CLIENT_ID", "CLIENTFLOW_1242_PILOT_CLIENT_ID",
                 "CLIENTFLOW_1243_PILOT_CLIENT_ID"):
        monkeypatch.delenv(flag, raising=False)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert cli.main(["--artifact-dir", str(directory)]) == 0
    report = capsys.readouterr().out
    assert "CLIENTFLOW_1243_TRANSITION_PREFLIGHT=READ_ONLY_PASS" in report
    assert "NOT verified here" in report
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
