from __future__ import annotations

import agentctl
from agent_identity import AgentRef


def test_send_reports_command_executed_after_marker(monkeypatch):
    target = AgentRef(77, "start", "powershell.exe")
    monkeypatch.setattr(agentctl, "_validated", lambda *_: target)
    class H: input = 1; output = 2
    class Context:
        def __enter__(self): return H()
        def __exit__(self, *args): return False
    monkeypatch.setattr(agentctl, "attached_console", lambda _: Context())
    monkeypatch.setattr(agentctl, "read_screen", lambda _: "before\nMARKER\nMARKER\nafter")
    monkeypatch.setattr(agentctl, "write_text", lambda *_: 12)
    monkeypatch.setattr(agentctl, "write_key", lambda *_: 2)
    monkeypatch.setattr(agentctl, "console_modes", lambda _: {"input": 7, "output": 3})
    result = agentctl.send("77", "Write-Output MARKER", True, "MARKER", 0.1)
    assert result["phase"] == "COMMAND_EXECUTED"
    assert result["records_written"] == 14


def test_send_without_screen_change_does_not_claim_delivery(monkeypatch):
    target = AgentRef(77, "start", "powershell.exe")
    monkeypatch.setattr(agentctl, "_validated", lambda *_: target)
    class H: input = 1; output = 2
    class Context:
        def __enter__(self): return H()
        def __exit__(self, *args): return False
    monkeypatch.setattr(agentctl, "attached_console", lambda _: Context())
    monkeypatch.setattr(agentctl, "read_screen", lambda _: "unchanged")
    monkeypatch.setattr(agentctl, "write_text", lambda *_: 4)
    monkeypatch.setattr(agentctl, "console_modes", lambda _: {})
    result = agentctl.send("77", "text", False, None, 0.01)
    assert result["phase"] == "INPUT_QUEUED"
    assert not result["input_observed"]
