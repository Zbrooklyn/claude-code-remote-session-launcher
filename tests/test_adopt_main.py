"""Adopting an already-running pane host as the certified MAIN controller."""
from pathlib import Path

import pytest

import orchestrator
import worker_runtime
from orchestration_store import Store


class _FakeConsole:
    """Stands in for the attached console of one exact PID."""

    def __init__(self, title: str = "user title"):
        self.title = title
        self.history: list[str] = [title]

    def set(self, text: str) -> None:
        self.title = text
        self.history.append(text)


def _snapshot(tab_title: str, pane_titles: list[str], hwnd: int = 591044, extra_tabs: int = 0) -> dict:
    windows = [{"bridge_id": "win_1", "hwnd": hwnd, "pid": 11092, "runtime_id": "w1", "title": tab_title, "active": True}]
    tabs = [{"bridge_id": "tab_1", "window_id": "win_1", "runtime_id": "t1", "index": 0, "title": tab_title, "active": True}]
    for extra in range(extra_tabs):
        tabs.append({"bridge_id": f"tab_x{extra}", "window_id": "win_1", "runtime_id": f"tx{extra}", "index": extra + 1,
                     "title": tab_title, "active": False})
    panes = [{"bridge_id": f"pane_{i}", "tab_id": "tab_1", "runtime_id": f"p{i}", "index": i, "title": title,
              "bounds": (0, i * 100, 100, 100), "certificate": None} for i, title in enumerate(pane_titles)]
    return {"windows": windows, "tabs": tabs, "panes": panes}


@pytest.fixture
def adopt_env(monkeypatch):
    console = _FakeConsole()
    calls = {"attached": []}

    class _Attached:
        def __init__(self, pid):
            calls["attached"].append(pid)
        def __enter__(self):
            return object()
        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker_runtime, "attached_console", _Attached)
    monkeypatch.setattr(worker_runtime, "console_title", lambda: console.title)
    monkeypatch.setattr(worker_runtime, "set_console_title", console.set)
    monkeypatch.setattr(worker_runtime, "reference_for_pid", lambda pid: type("Ref", (), {
        "to_dict": lambda self: {"pid": pid, "process_start_time": "20260910225903", "process_image": "powershell.exe",
                                 "command_line": 'powershell.exe -NoExit -Command "claude --remote-control"'}})())
    return console, calls


def test_adopt_main_binds_console_title_certificate_to_the_single_pane_tab(tmp_path: Path, monkeypatch, adopt_env):
    console, calls = adopt_env
    store = Store(tmp_path / "orchestration.db")
    seen = {}

    def fake_enumerate(exhaustive=False, hwnds=None, **_):
        assert not exhaustive
        seen["hwnds"] = hwnds
        return _snapshot(console.title, ["Brain Claude Yolo"])

    monkeypatch.setattr(worker_runtime, "enumerate_topology", fake_enumerate)
    main = worker_runtime.adopt_main(store, "main", 25316)
    topology = main["topology_json"]
    assert main["state"] == "ready" and main["role"] == "controller"
    assert topology["adopted"] is True
    assert topology["certificate"].startswith("ORCH_MAIN_")
    assert topology["pane"]["runtime_id"] == "p0" and topology["pane_title"] == "Brain Claude Yolo"
    assert topology["window"]["hwnd"] == 591044 and topology["window_name"] == "last"
    assert main["ref_json"]["pid"] == 25316
    # The certificate went to the exact PID's console and the user's title came back.
    assert calls["attached"] and all(pid == 25316 for pid in calls["attached"])
    assert console.history[1].startswith("ORCH_MAIN_") and console.title == "user title"


def test_adopt_main_refuses_ambiguous_tab_or_multi_pane_tab(tmp_path: Path, monkeypatch, adopt_env):
    console, _ = adopt_env
    store = Store(tmp_path / "orchestration.db")
    monkeypatch.setattr(worker_runtime, "enumerate_topology",
                        lambda **_: _snapshot(console.title, ["Brain Claude Yolo"], extra_tabs=1))
    monkeypatch.setattr(worker_runtime, "_ADOPT_TIMEOUT", 0.3)
    with pytest.raises(worker_runtime.WorkerRuntimeError, match="ADOPT_UNPROVEN"):
        worker_runtime.adopt_main(store, "main-a", 25316)
    monkeypatch.setattr(worker_runtime, "enumerate_topology",
                        lambda **_: _snapshot(console.title, ["Brain Claude Yolo", "other pane"]))
    with pytest.raises(worker_runtime.WorkerRuntimeError, match="ADOPT_UNPROVEN"):
        worker_runtime.adopt_main(store, "main-b", 25316)
    assert console.title == "user title"


def _adopted_main(store: Store) -> dict:
    main = store.create_worker("main", "controller", "claude")
    return store.update_worker(main["id"], state="ready",
                               ref={"pid": 25316, "process_start_time": "20260910225903",
                                    "command_line": 'powershell.exe -NoExit -Command "claude"'},
                               topology={"adopted": True, "certificate": "ORCH_MAIN_x", "pane_title": "Brain Claude Yolo",
                                         "window_name": "last", "window": {"bridge_id": "win_1", "hwnd": 591044},
                                         "tab": {"bridge_id": "tab_1", "runtime_id": "t1"},
                                         "pane": {"bridge_id": "pane_0", "runtime_id": "p0", "title": "Brain Claude Yolo"}})


def _child(store: Store, main: dict, name: str, certificate: str) -> dict:
    worker = store.create_worker(name, name, "claude", parent_id=main["id"])
    return store.update_worker(worker["id"], state="ready",
                               ref={"pid": 100, "process_start_time": "x", "command_line": f"pwsh # {certificate}"},
                               topology={"certificate": certificate, "window_name": "last",
                                         "window": {"bridge_id": "win_1", "hwnd": 591044},
                                         "tab": {"bridge_id": "tab_1", "runtime_id": "t1"},
                                         "pane": {"bridge_id": "pane_1", "runtime_id": "p1", "title": certificate}})


def test_adopted_main_refresh_rebinds_by_elimination_inside_the_owned_tab(tmp_path: Path, monkeypatch, adopt_env):
    store = Store(tmp_path / "orchestration.db")
    main = _adopted_main(store)
    _child(store, main, "worker-a", "ORCH_a")
    monkeypatch.setattr(worker_runtime, "enumerate_topology",
                        lambda **kw: _snapshot("◐ session", ["Brain Claude Yolo", "ORCH_a"]))
    refreshed = worker_runtime.refresh_worker_topology(store, main["id"])
    assert refreshed["topology_json"]["pane"]["runtime_id"] == "p0"
    assert refreshed["topology_json"]["adopted"] is True
    # Two uncertified panes in the owned tab is not a proof.
    monkeypatch.setattr(worker_runtime, "enumerate_topology",
                        lambda **kw: _snapshot("◐ session", ["Brain Claude Yolo", "Brain Claude Yolo", "ORCH_a"]))
    with pytest.raises(worker_runtime.WorkerRuntimeError, match="REFRESH_MAIN_PANE_UNPROVEN"):
        worker_runtime.refresh_worker_topology(store, main["id"])
    # A tab that does not hold the live child certificate is not the owned tab.
    store.update_worker(main["id"], state="recovering")
    store.update_worker(main["id"], state="ready")
    monkeypatch.setattr(worker_runtime, "enumerate_topology",
                        lambda **kw: _snapshot("◐ session", ["Brain Claude Yolo"]))
    with pytest.raises(worker_runtime.WorkerRuntimeError, match="REFRESH_MAIN_PANE_UNPROVEN"):
        worker_runtime.refresh_worker_topology(store, main["id"])


def test_close_team_never_terminates_an_adopted_main_and_closes_only_worker_panes(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    main = _adopted_main(store)
    worker = _child(store, main, "worker-a", "ORCH_a")
    terminated, closed = [], []
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda _s, wid: store.worker(wid))
    monkeypatch.setattr(orchestrator, "enumerate_topology",
                        lambda **kw: _snapshot("◐ session", ["Brain Claude Yolo", "ORCH_a"]))
    monkeypatch.setattr(orchestrator, "terminate_worker", lambda _s, wid: terminated.append(wid))
    monkeypatch.setattr(orchestrator, "close_pane_and_verify", lambda topology: closed.append(topology["pane"]["runtime_id"]))
    monkeypatch.setattr(orchestrator, "close_exact_tab", lambda *_: (_ for _ in ()).throw(AssertionError("tab must stay open")))
    result = control.close_team(main["id"])
    assert terminated == [worker["id"]] and closed == ["p1"]
    assert result["main_preserved"] is True
    assert store.worker(main["id"])["state"] == "ready"


def test_close_team_with_adopted_main_refuses_a_foreign_pane(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    main = _adopted_main(store)
    _child(store, main, "worker-a", "ORCH_a")
    monkeypatch.setattr(orchestrator, "refresh_worker_topology", lambda _s, wid: store.worker(wid))
    monkeypatch.setattr(orchestrator, "enumerate_topology",
                        lambda **kw: _snapshot("◐ session", ["Brain Claude Yolo", "ORCH_a", "Edward's own pane"]))
    monkeypatch.setattr(orchestrator, "terminate_worker", lambda *_: (_ for _ in ()).throw(AssertionError("must not terminate")))
    with pytest.raises(orchestrator.OrchestrationError, match="REFUSE_TEAM_TAB_WITH_FOREIGN_PANE"):
        control.close_team(main["id"])


def test_terminate_worker_kills_the_certified_process_tree(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    worker = store.create_worker("w", "worker", "claude")
    store.update_worker(worker["id"], state="ready", ref={"pid": 4242, "process_start_time": "s", "command_line": "pwsh # ORCH_z"},
                        topology={"certificate": "ORCH_z"})
    monkeypatch.setattr(worker_runtime, "reference_for_pid", lambda pid: type("Ref", (), {
        "to_dict": lambda self: {"pid": pid, "process_start_time": "s", "command_line": "pwsh # ORCH_z"}})())
    commands = []
    monkeypatch.setattr(worker_runtime.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    worker_runtime.terminate_worker(store, worker["id"])
    assert commands and "/T" in commands[0] and "4242" in commands[0]


def test_team_passes_the_agent_command_to_each_worker(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "orchestration.db")
    control = orchestrator.Orchestrator(store)
    main = _adopted_main(store)
    typed = []
    import team_layout

    def fake_launch(_store, worker, engine, parent, cwd, direction, size):
        return _store.update_worker(worker["id"], state="ready", ref={"pid": 7}, topology={"certificate": "c", "window_name": "last"})

    monkeypatch.setattr(worker_runtime, "_launch_worker", fake_launch)
    monkeypatch.setattr(worker_runtime, "send_worker_input", lambda _s, wid, text: typed.append(text) or {"phase": "INPUT_OBSERVED"})
    monkeypatch.setattr(orchestrator, "normalize_main_and_workers", lambda *_: {"bounds": {}, "workers": [], "main": {}})
    control.team(main["id"], ["worker-a", "worker-b"], agent_type="claude",
                 agent_command="claude --dangerously-skip-permissions --remote-control")
    assert typed == ["claude --dangerously-skip-permissions --remote-control"] * 2
