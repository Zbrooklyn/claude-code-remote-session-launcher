import team_layout


class _Store:
    def worker(self, _worker_id):
        return {"id": "main", "name": "main"}


def test_three_worker_row_reserves_equal_nested_split_fractions(monkeypatch):
    calls = []

    def spawn(_store, name, role, engine, parent_id, agent_type, cwd, direction, size=None):
        calls.append((role, parent_id, direction, size))
        return {"id": f"worker-{len(calls)}"}

    monkeypatch.setattr(team_layout, "spawn_worker", spawn)

    team_layout.create_workers(_Store(), "main", ["frontend", "backend", "reviewer"], agent_type="powershell")

    assert calls == [
        ("frontend", "main", "right", None),
        ("backend", "worker-1", "down", 2 / 3),
        ("reviewer", "worker-2", "down", 1 / 2),
    ]


def test_normalization_stops_after_the_first_already_converged_measurement(monkeypatch):
    main = {"id": "main", "topology_json": {"pane": {"runtime_id": "main"}}}
    workers = [
        {"id": "one", "topology_json": {"pane": {"runtime_id": "one"}}},
        {"id": "two", "topology_json": {"pane": {"runtime_id": "two"}}},
        {"id": "three", "topology_json": {"pane": {"runtime_id": "three"}}},
    ]
    by_id = {worker["id"]: worker for worker in [main, *workers]}
    refreshes, converges = [], []
    monkeypatch.setattr(team_layout, "refresh_worker_topology", lambda _store, worker_id: refreshes.append(worker_id) or by_id[worker_id])
    monkeypatch.setattr(team_layout, "measured", lambda _: {
        "main": (0, 0, 100, 100), "one": (0, 100, 100, 100),
        "two": (100, 100, 100, 100), "three": (200, 100, 100, 100),
    })
    monkeypatch.setattr(team_layout, "converge_pair", lambda *_: converges.append(True) or {"iterations": 0, "converged": True})

    result = team_layout.normalize_main_and_workers(object(), "main", [worker["id"] for worker in workers])

    # An already-balanced fresh team (equal cells here) hits the early-exit and
    # does no convergence work at all -- the change that keeps foreground runs fast.
    assert len(converges) == 0
    assert result["main"].get("skipped") == "already balanced"
    assert len(refreshes) == 4  # main + three workers, then the balance check; no convergence rounds.


def test_normalization_converges_a_skewed_team(monkeypatch):
    main = {"id": "main", "topology_json": {"pane": {"runtime_id": "main"}}}
    workers = [
        {"id": "one", "topology_json": {"pane": {"runtime_id": "one"}}},
        {"id": "two", "topology_json": {"pane": {"runtime_id": "two"}}},
    ]
    by_id = {w["id"]: w for w in [main, *workers]}
    converges = []
    monkeypatch.setattr(team_layout, "refresh_worker_topology", lambda _s, wid: by_id[wid])
    # MAIN 50/50 in height, but the two workers are 60/40 in width -> not balanced.
    monkeypatch.setattr(team_layout, "measured", lambda _: {
        "main": (0, 0, 1000, 500), "one": (0, 500, 600, 500), "two": (600, 500, 400, 500)})
    monkeypatch.setattr(team_layout, "converge_pair", lambda *a, **k: converges.append(True) or {"iterations": 1, "converged": True})

    team_layout.normalize_main_and_workers(object(), "main", ["one", "two"])

    assert len(converges) >= 1  # a skewed team is actually converged, not skipped.
