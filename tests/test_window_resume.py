"""Regression tests for window-resume's spawn/verify loop.

The defect these guard against: on a slow machine, claude cold-boot can take
longer than the first liveness timeout, so the prior spawn registers late. The
loop must RE-CHECK liveness before re-spawning -- otherwise it opens a second
window onto the same session (two windows, one resume). Observed live on the
author's machine (25s timeout < ~30s cold boot).
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _load():
    spec = importlib.util.spec_from_file_location("windowresume", HOOKS / "window-resume.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["windowresume"] = mod
    spec.loader.exec_module(mod)
    return mod


wr = _load()


def _ok_spawn():
    """A fake spawn-window.py result that reports a successful launch."""
    return types.SimpleNamespace(
        returncode=0,
        stdout="Resumed terminal (window-yolo-remote) in C:/x. Remote session: h-x-1",
        stderr="",
    )


@pytest.fixture
def stub_loop(monkeypatch):
    """Stub everything the loop touches except the logic under test, and count
    how many times a window is actually spawned."""
    calls = {"spawn": 0}

    def fake_run(*a, **k):
        calls["spawn"] += 1
        return _ok_spawn()

    monkeypatch.setattr(wr.subprocess, "run", fake_run)
    monkeypatch.setattr(wr.time, "sleep", lambda *_: None)
    monkeypatch.setattr(wr, "_verify_permission_mode_from_process",
                        lambda pid: "bypassPermissions")
    return calls


def test_no_double_spawn_when_first_boot_is_slow(stub_loop, monkeypatch):
    """First spawn registers LATE: _await_liveness misses it on attempt 0, but
    the pre-retry liveness re-check finds it. Must NOT spawn a second window."""
    monkeypatch.setattr(wr, "_await_liveness", lambda sid, t: None)   # attempt-0 wait misses
    monkeypatch.setattr(wr, "alive_pid_for_session", lambda sid: 4242)  # recheck finds it

    rc = wr._spawn_and_verify("window-yolo-remote", "args", "sid-123", True, True,
                              first_timeout=0.01, retry_timeout=0.01)

    assert rc == 0
    assert stub_loop["spawn"] == 1   # the fix: one window, not two


def test_happy_path_single_spawn(stub_loop, monkeypatch):
    """Liveness seen on attempt 0 -> one spawn, no recheck needed."""
    monkeypatch.setattr(wr, "_await_liveness", lambda sid, t: 4242)
    monkeypatch.setattr(wr, "alive_pid_for_session", lambda sid: None)

    rc = wr._spawn_and_verify("window-yolo-remote", "args", "sid-123", True, True,
                              first_timeout=0.01, retry_timeout=0.01)

    assert rc == 0
    assert stub_loop["spawn"] == 1


def test_genuinely_dead_resume_retries_once_then_warns(stub_loop, monkeypatch):
    """Never registers anywhere: spawns on attempt 0 and again on attempt 1
    (the legitimate single retry), then returns WARN."""
    monkeypatch.setattr(wr, "_await_liveness", lambda sid, t: None)
    monkeypatch.setattr(wr, "alive_pid_for_session", lambda sid: None)

    rc = wr._spawn_and_verify("window-yolo-remote", "args", "sid-123", True, True,
                              first_timeout=0.01, retry_timeout=0.01)

    assert rc == 1
    assert stub_loop["spawn"] == 2   # one real retry is still allowed


def test_skip_verify_returns_immediately(stub_loop, monkeypatch):
    """--no-verify: spawn once and return without waiting for liveness."""
    monkeypatch.setattr(wr, "_await_liveness", lambda sid, t: pytest.fail("should not wait"))
    monkeypatch.setattr(wr, "alive_pid_for_session", lambda sid: None)

    rc = wr._spawn_and_verify("window-yolo-remote", "args", "sid-123", True, False)

    assert rc == 0
    assert stub_loop["spawn"] == 1
