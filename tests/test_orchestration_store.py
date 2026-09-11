from pathlib import Path

import pytest

from orchestration_store import Store
import worker_runtime


def test_worker_task_dependency_and_persistence(tmp_path: Path):
    path = tmp_path / "orchestration.db"
    store = Store(path)
    worker = store.create_worker("alpha", "builder", "powershell")
    worker = store.update_worker(worker["id"], state="ready", ref={"pid": 7}, topology={"pane": "p"}, health={"reachable": True})
    parent = store.create_task("parent")
    child = store.create_task("child", parent_id=parent["id"])
    store.add_dependency(child["id"], parent["id"])
    assert not store.ready_for_work(child["id"])
    store.assign(parent["id"], worker["id"])
    store.complete_task(parent["id"], {"marker": "ok"}, verified=True)
    assert store.ready_for_work(child["id"])
    store.close()
    restored = Store(path)
    assert restored.worker(worker["id"])["state"] == "ready"
    assert any(event["kind"] == "task_completed" for event in restored.audit())


def test_invalid_worker_transition_is_rejected(tmp_path: Path):
    store = Store(tmp_path / "orchestration.db")
    worker = store.create_worker("alpha", "builder", "powershell")
    with pytest.raises(ValueError):
        store.update_worker(worker["id"], state="done")


def test_worker_parent_is_durable_for_layout_recovery(tmp_path: Path):
    store = Store(tmp_path / "orchestration.db")
    main = store.create_worker("main", "controller", "powershell")
    worker = store.create_worker("frontend", "frontend", "claude", parent_id=main["id"])

    assert store.worker(worker["id"])["parent_id"] == main["id"]


def test_recovery_rejoins_the_persisted_parent_layout(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    main = store.create_worker("main", "controller", "powershell")
    main = store.update_worker(main["id"], state="ready", topology={"window_name": "owned"})
    worker = store.create_worker("frontend", "frontend", "powershell", parent_id=main["id"])
    worker = store.update_worker(worker["id"], state="failed")
    observed = {}
    monkeypatch.setattr(worker_runtime, "refresh_worker_topology", lambda _store, worker_id: observed.setdefault("refreshed", worker_id) and store.worker(worker_id))
    monkeypatch.setattr(worker_runtime, "_launch_worker", lambda _store, recovered, _engine, parent=None: observed.setdefault("parent", parent) or recovered)

    worker_runtime.restart_worker(store, worker["id"])

    assert observed["parent"]["id"] == main["id"]
    assert observed["refreshed"] == main["id"]


def test_pid_rendezvous_accepts_only_a_complete_positive_pid(tmp_path: Path):
    rendezvous = tmp_path / "worker.pid"
    assert worker_runtime._read_pid_rendezvous(rendezvous) is None
    rendezvous.write_text("not-ready")
    assert worker_runtime._read_pid_rendezvous(rendezvous) is None
    rendezvous.write_text("-4")
    assert worker_runtime._read_pid_rendezvous(rendezvous) is None
    rendezvous.write_text("1234\n")
    assert worker_runtime._read_pid_rendezvous(rendezvous) == 1234


def test_startup_command_restores_the_certificate_as_the_terminal_title(tmp_path: Path):
    command = worker_runtime._startup_command("ORCH_certificate", tmp_path / "worker.pid")

    assert ";" not in command
    assert command.endswith("# ORCH_certificate")
    assert "FromBase64String" in command
