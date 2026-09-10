from pathlib import Path

import pytest

from orchestration_store import Store


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
