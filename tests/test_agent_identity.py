from __future__ import annotations

import pytest

import agent_identity as identity


def ref(pid=42, started="start", image="C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"):
    return identity.AgentRef(pid, started, image)


def test_validate_rejects_reused_pid(monkeypatch):
    monkeypatch.setattr(identity, "reference_for_pid", lambda _pid: ref(started="new-start"))
    with pytest.raises(identity.TargetError, match="reused") as exc:
        identity.validate_target(ref())
    assert exc.value.code == "STALE_TARGET"


def test_validate_rejects_changed_image(monkeypatch):
    monkeypatch.setattr(identity, "reference_for_pid", lambda _pid: ref(image="C:/other.exe"))
    with pytest.raises(identity.TargetError, match="executable") as exc:
        identity.validate_target(ref())
    assert exc.value.code == "STALE_TARGET"


def test_validate_preserves_enrichment(monkeypatch):
    monkeypatch.setattr(identity, "reference_for_pid", lambda _pid: ref())
    checked = identity.validate_target(identity.AgentRef(42, "start", ref().process_image, wt_session="saved"))
    assert checked.wt_session == "saved"
