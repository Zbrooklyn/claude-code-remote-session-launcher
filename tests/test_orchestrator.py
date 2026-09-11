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


def test_role_lookup_rejects_ambiguous_workers(tmp_path: Path):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    _ready_worker(store, "frontend-one")
    _ready_worker(store, "frontend-two")
    store.conn.execute("update workers set role='frontend'")
    store.conn.commit()
    with pytest.raises(orchestrator.OrchestrationError, match="ROLE_NOT_UNIQUE"):
        control.worker_by_role("frontend")


def test_handoff_reassigns_task_and_releases_source_worker(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    source = _ready_worker(store, "frontend")
    reviewer = _ready_worker(store, "reviewer")
    task = control.create_task("review")
    store.assign(task["id"], source["id"])
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(reviewer["id"]))
    monkeypatch.setattr(orchestrator, "send_worker", lambda *_: {"phase": "COMMAND_EXECUTED"})

    control.handoff(source["id"], reviewer["id"], task["id"], "review it")

    assert store.task(task["id"])["owner_id"] == reviewer["id"]
    assert store.worker(source["id"])["state"] == "ready"
    assert store.worker(reviewer["id"])["state"] == "working"


def test_role_addressed_dispatch_resolves_one_ready_worker(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    worker = _ready_worker(store, "frontend")
    store.conn.execute("update workers set role='frontend'")
    store.conn.commit()
    task = control.create_task("build")
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda *_: store.worker(worker["id"]))
    monkeypatch.setattr(orchestrator, "send_worker", lambda *_: {"phase": "COMMAND_EXECUTED"})

    control.dispatch_role("frontend", task["id"], "Write-Output build")

    assert store.task(task["id"])["owner_id"] == worker["id"]


def test_close_team_refuses_tab_with_a_foreign_pane(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    topology = {
        "window": {"hwnd": 7}, "tab": {"bridge_id": "tab_1", "runtime_id": "tab-runtime"},
        "pane": {"runtime_id": "main-pane"}, "certificate": "main-cert", "window_name": "owned",
    }
    main = store.create_worker("main", "controller", "powershell")
    main = store.update_worker(main["id"], state="ready", ref={"pid": 1}, topology=topology)
    child_topology = {**topology, "pane": {"runtime_id": "worker-pane"}, "certificate": "worker-cert"}
    child = store.create_worker("frontend", "frontend", "powershell", parent_id=main["id"])
    child = store.update_worker(child["id"], state="ready", ref={"pid": 2}, topology=child_topology)
    monkeypatch.setattr(control, "refresh", lambda worker_id: store.worker(worker_id))
    monkeypatch.setattr(orchestrator, "enumerate_topology", lambda **_: {"tabs": [{"bridge_id": "tab_1", "runtime_id": "tab-runtime"}], "panes": [
        {"tab_id": "tab_1", "runtime_id": "main-pane", "title": "main-cert"},
        {"tab_id": "tab_1", "runtime_id": "worker-pane", "title": "worker-cert"},
        {"tab_id": "tab_1", "runtime_id": "foreign-pane", "title": "foreign-cert"},
    ]})

    with pytest.raises(orchestrator.OrchestrationError, match="REFUSE_TEAM_TAB_WITH_FOREIGN_PANE"):
        control.close_team(main["id"])


def test_close_team_stops_all_members_then_closes_the_exact_tab(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    topology = {
        "window": {"hwnd": 7}, "tab": {"bridge_id": "tab_1", "runtime_id": "tab-runtime"},
        "pane": {"runtime_id": "main-pane"}, "certificate": "main-cert", "window_name": "owned",
    }
    main = store.create_worker("main", "controller", "powershell")
    main = store.update_worker(main["id"], state="ready", ref={"pid": 1}, topology=topology)
    child_topology = {**topology, "pane": {"runtime_id": "worker-pane"}, "certificate": "worker-cert"}
    child = store.create_worker("frontend", "frontend", "powershell", parent_id=main["id"])
    child = store.update_worker(child["id"], state="ready", ref={"pid": 2}, topology=child_topology)
    monkeypatch.setattr(control, "refresh", lambda worker_id: store.worker(worker_id))
    monkeypatch.setattr(orchestrator, "enumerate_topology", lambda **_: {"tabs": [{"bridge_id": "tab_1", "runtime_id": "tab-runtime"}], "panes": [
        {"tab_id": "tab_1", "runtime_id": "main-pane", "title": "main-cert"},
        {"tab_id": "tab_1", "runtime_id": "worker-pane", "title": "worker-cert"},
    ]})
    stopped, closed = [], []
    monkeypatch.setattr(orchestrator, "terminate_worker", lambda _store, worker_id: stopped.append(worker_id))
    monkeypatch.setattr(orchestrator, "close_exact_tab", lambda value: closed.append(value))

    result = control.close_team(main["id"])

    assert set(stopped) == {main["id"], child["id"]}
    assert closed[0]["tab"]["runtime_id"] == "tab-runtime"
    assert closed[0]["pane"]["runtime_id"] == "main-pane"
    assert result["closed"] == 2


def test_close_team_uses_certificate_panes_when_console_refresh_is_unavailable(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    topology = {
        "window": {"hwnd": 7}, "tab": {"bridge_id": "old-tab", "runtime_id": "old-runtime"},
        "pane": {"runtime_id": "old-main-pane"}, "certificate": "main-cert", "window_name": "owned",
    }
    main = store.create_worker("main", "controller", "powershell")
    main = store.update_worker(main["id"], state="ready", ref={"pid": 1}, topology=topology)
    child_topology = {**topology, "pane": {"runtime_id": "old-worker-pane"}, "certificate": "worker-cert"}
    child = store.create_worker("frontend", "frontend", "powershell", parent_id=main["id"])
    child = store.update_worker(child["id"], state="ready", ref={"pid": 2}, topology=child_topology)
    monkeypatch.setattr(control, "refresh", lambda _: (_ for _ in ()).throw(RuntimeError("console text unavailable")))
    monkeypatch.setattr(orchestrator, "enumerate_topology", lambda **_: {
        "tabs": [{"bridge_id": "fresh-tab", "runtime_id": "fresh-runtime"}],
        "panes": [
            {"tab_id": "fresh-tab", "runtime_id": "fresh-main-pane", "title": "main-cert"},
            {"tab_id": "fresh-tab", "runtime_id": "fresh-worker-pane", "title": "worker-cert"},
        ],
    })
    stopped, closed = [], []
    monkeypatch.setattr(orchestrator, "terminate_worker", lambda _store, worker_id: stopped.append(worker_id))
    monkeypatch.setattr(orchestrator, "close_exact_tab", lambda value: closed.append(value))

    result = control.close_team(main["id"])

    assert set(stopped) == {main["id"], child["id"]}
    assert closed[0]["tab"]["runtime_id"] == "fresh-runtime"
    assert closed[0]["pane"]["runtime_id"] == "fresh-main-pane"
    assert result["closed"] == 2


def test_cli_exposes_team_role_routing_and_coordinated_close():
    parser = orchestrator.build_parser()

    team = parser.parse_args(["team", "wrk_main", "frontend", "backend", "reviewer", "--agent-type", "claude"])
    dispatch = parser.parse_args(["dispatch-role", "frontend", "tsk_build", "build the feature"])
    handoff = parser.parse_args(["handoff-role", "frontend", "reviewer", "tsk_build", "review the feature"])
    close = parser.parse_args(["close-team", "wrk_main"])

    assert (team.command, team.agent_type) == ("team", "claude")
    assert dispatch.command == "dispatch-role"
    assert handoff.command == "handoff-role"
    assert close.command == "close-team"


def test_recovery_renormalizes_the_surviving_team(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    main = store.create_worker("main", "controller", "powershell")
    main = store.update_worker(main["id"], state="ready", topology={"window_name": "owned"})
    worker = store.create_worker("frontend", "frontend", "powershell", parent_id=main["id"])
    worker = store.update_worker(worker["id"], state="failed")
    def fake_restart(_store, worker_id, _engine):
        store.update_worker(worker_id, state="recovering")
        return store.update_worker(worker_id, state="ready")
    monkeypatch.setattr(orchestrator, "restart_worker", fake_restart)
    observed = {}
    monkeypatch.setattr(orchestrator, "normalize_main_and_workers", lambda _store, main_id, workers: observed.update(main=main_id, workers=workers) or {})

    control.recover(worker["id"])

    assert observed == {"main": main["id"], "workers": [worker["id"]]}
