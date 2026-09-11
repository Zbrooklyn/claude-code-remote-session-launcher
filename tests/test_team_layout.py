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

    team_layout.normalize_main_and_workers(object(), "main", [worker["id"] for worker in workers])

    assert len(converges) == 3  # MAIN plus two adjacent worker pairs.
    assert len(refreshes) == 10  # initial 4, one measured round of 3, final 3.
