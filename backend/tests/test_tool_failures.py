"""Missing tools, timeouts, subprocess sandboxing and generic error responses."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from conftest import job_dirs, upload

from app.errors import timeout_error
from app.tools import ToolRunner


def test_missing_exiftool_reports_degraded_health_and_503(apps, samples):
    client = apps.client(EXIFTOOL_PATH="definitely-not-a-real-binary")
    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    assert health["tools"]["exiftool"]["available"] is False
    assert health["accepts_uploads"] is False

    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tool_unavailable"
    assert response.headers["Retry-After"] == "30"
    assert "not a real binary" not in response.text


def test_missing_exiftool_does_not_leave_scratch_data(apps, samples):
    client = apps.client(EXIFTOOL_PATH="definitely-not-a-real-binary")
    upload(client, samples["jpeg"], endpoint="sanitize")
    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []
    assert apps.created[0].state.jobs.stats()["jobs"] == 0


def test_exiftool_timeout_returns_504_and_cleans_up(apps, samples, monkeypatch):
    client = apps.client(EXIFTOOL_TIMEOUT_SECONDS="1")

    async def slow_write(*args, **kwargs):
        await asyncio.sleep(0.05)
        raise timeout_error("Sanitization timed out.")

    monkeypatch.setattr("app.service.exiftool.write", slow_write)
    response = upload(client, samples["jpeg"], endpoint="sanitize")
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "processing_timeout"

    root = Path(apps.created[0].state.settings.temp_root)
    assert job_dirs(root) == []


def test_inspection_timeout_returns_504(apps, samples, monkeypatch):
    client = apps.client()

    async def slow_inspect(*args, **kwargs):
        raise timeout_error("Metadata inspection timed out.")

    monkeypatch.setattr("app.service.exiftool.inspect", slow_inspect)
    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 504


def test_tool_runner_kills_a_hung_process(tmp_path):
    runner = ToolRunner(tmp_path / "toolroot")
    started = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            runner.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout=1,
                tool="sleep-test",
            )
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 15, f"timeout handling took {elapsed:.1f}s"


def test_tool_runner_passes_a_minimal_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEANSLATE_FAKE_SECRET", "should-not-be-passed")
    runner = ToolRunner(tmp_path / "toolroot")
    env = runner._env(tmp_path)
    assert "CLEANSLATE_FAKE_SECRET" not in env
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "SYSTEMROOT"}
    assert env["HOME"] == str(runner._home)
    assert env["LANG"] == "C.UTF-8"


def test_tool_runner_uses_argv_arrays_without_a_shell(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        raise RuntimeError("stop before spawning")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    runner = ToolRunner(tmp_path / "toolroot")
    with pytest.raises(RuntimeError):
        asyncio.run(runner.run(["./exiftool", "-ver"], timeout=5, tool="test"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_exec)

    argv = captured["argv"]
    kwargs = captured["kwargs"]
    assert isinstance(argv, tuple) and all(isinstance(item, str) for item in argv)
    assert argv[0] == "./exiftool"
    assert "shell" not in kwargs
    assert kwargs["stdin"] is asyncio.subprocess.DEVNULL


def test_error_responses_never_include_stack_traces(client, samples, monkeypatch):
    async def explode(*args, **kwargs):
        raise ValueError("internal detail that must not leak")

    monkeypatch.setattr("app.service.exiftool.inspect", explode)
    response = upload(client, samples["jpeg"], endpoint="inspect")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "internal detail" not in response.text
    assert "ValueError" not in response.text
    assert "Traceback" not in response.text
    assert body["request_id"]


def test_tool_errors_are_scrubbed_before_logging(tmp_path, caplog):
    from app.logging_utils import scrub_tool_error

    scrubbed = scrub_tool_error(
        "Error: File not found - /tmp/cleanslate-jobs/abc123/original.jpg", limit=300
    )
    assert "/tmp/cleanslate-jobs" not in scrubbed
    assert "original.jpg" not in scrubbed
    assert "<path>" in scrubbed


def test_qpdf_missing_still_returns_a_pdf_and_flags_history(apps, samples):
    client = apps.client(QPDF_PATH="definitely-not-a-real-qpdf")
    response = upload(client, samples["pdf"], endpoint="sanitize")
    assert response.status_code == 200
    body = response.json()
    assert body["verification"]["revision_history_rewritten"] is False
    assert any("qpdf is not installed" in note for note in body["engine_notes"])
    assert any("revision" in risk.lower() for risk in body["verification"]["residual_risks"])
