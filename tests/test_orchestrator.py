from pathlib import Path

import pytest

import orchestrator
from orchestration_store import Store


def _ready_worker(store: Store, name: str) -> dict:
    worker = store.create_worker(name, "test", "powershell")
    return store.update_worker(worker["id"], state="ready", ref={"pid": 1}, topology={"certificate": "test"})


def test_dispatch_requires_dependency_and_records_verified_delivery(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    worker = _ready_worker(store, "worker")
    prerequisite = control.create_task("first")
    task = control.create_task("second")
    control.add_dependency(task["id"], prerequisite["id"])
    with pytest.raises(orchestrator.OrchestrationError, match="DEPENDENCIES_PENDING"):
        control.dispatch(worker["id"], task["id"], "Write-Output 'second'")
    store.complete_task(prerequisite["id"], {"ok": True}, True)
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(worker["id"]))
    calls = {}
    def fake_send(_store, worker_id, command, marker):
        calls.update(worker_id=worker_id, command=command, marker=marker)
        return {"phase": "COMMAND_EXECUTED"}
    monkeypatch.setattr(orchestrator, "send_worker", fake_send)
    result = control.dispatch(worker["id"], task["id"], "Write-Output 'second'")
    assert result["marker"] in calls["command"]
    assert calls["worker_id"] == worker["id"]
    assert store.task(task["id"])["owner_id"] == worker["id"]


def test_monitor_never_claims_completion_from_quiescence(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    worker = _ready_worker(store, "worker")
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(worker["id"]))
    monkeypatch.setattr(orchestrator, "read_worker", lambda *_: {"screen": "PS C:\\>"})
    result = control.monitor(worker["id"])
    assert result["completion"] == "UNPROVEN"
    assert result["state"] == "ready"


def test_failed_delivery_marks_task_blocked(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    worker = _ready_worker(store, "worker")
    task = control.create_task("task")
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(worker["id"]))
    monkeypatch.setattr(orchestrator, "send_worker", lambda *_: (_ for _ in ()).throw(RuntimeError("native failure")))
    with pytest.raises(orchestrator.OrchestrationError, match="DELIVERY_FAILED"):
        control.dispatch(worker["id"], task["id"], "Write-Output nope")
    assert store.task(task["id"])["state"] == "blocked"


def test_agent_prompt_delivery_is_not_misreported_as_shell_execution(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    worker = store.create_worker("claude", "worker", "claude")
    worker = store.update_worker(worker["id"], state="ready", ref={"pid": 1}, topology={"certificate": "test"})
    task = control.create_task("agent task")
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(worker["id"]))
    observed = {}
    def fake_input(_store, worker_id, message):
        observed.update(worker_id=worker_id, message=message)
        return {"phase": "INPUT_OBSERVED"}
    monkeypatch.setattr(orchestrator, "send_worker_input", fake_input)
    result = control.dispatch(worker["id"], task["id"], "review the change")
    assert result["marker"] is None
    assert result["delivery"]["phase"] == "INPUT_OBSERVED"
    assert observed == {"worker_id": worker["id"], "message": "review the change"}
