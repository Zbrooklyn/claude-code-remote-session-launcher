"""Bridge-owned MAIN/worker layout construction and measured normalization."""
from __future__ import annotations

from layout_normalizer import converge_pair, measured
import secrets

from worker_runtime import spawn_worker, refresh_worker_topology


def create_workers(store, main_id: str, roles: list[str], engine: str = "powershell.exe",
                   agent_type: str = "claude", cwd: str | None = None,
                   agent_command: str | None = None) -> list[dict]:
    """Create a balanced worker topology below an unchanged MAIN controller."""
    main=store.worker(main_id); workers=[]
    if not roles:return workers
    if any(not role.strip() for role in roles) or len({role.lower() for role in roles}) != len(roles):
        raise ValueError("ROLE_NAMES_MUST_BE_UNIQUE")
    def launch(role: str, parent_id: str, direction: str, size: float | None = None) -> dict:
        name = f"{main['name']}-{role}-{secrets.token_hex(3)}"
        extra = {"agent_command": agent_command} if agent_command else {}
        return spawn_worker(store, name, role, engine, parent_id, agent_type, cwd, direction, size, **extra)
    # First split creates the lower worker region. Subsequent vertical splits
    # create columns; for 4/6, horizontal splits turn those columns into rows.
    first=launch(roles[0], main_id, "right"); workers.append(first)
    columns=2 if len(roles)==4 else 3 if len(roles)>=3 else len(roles)
    for index, role in enumerate(roles[1:columns], start=1):
        # ``--size`` applies to the new pane as a fraction of the pane being
        # split.  Reserve the remaining fraction for the uncreated siblings,
        # so the nested 3-column topology starts equal instead of 1/2,1/4,1/4.
        remaining = columns - index
        workers.append(launch(role, workers[-1]["id"], "down", remaining / (remaining + 1)))
    if len(roles)>columns:
        for index,role in enumerate(roles[columns:]):
            workers.append(launch(role, workers[index]["id"], "right"))
    return workers


def refresh_all(store, ids: list[str]) -> list[dict]:
    return [refresh_worker_topology(store, worker_id) for worker_id in ids]


def normalize_main_and_workers(store, main_id: str, worker_ids: list[str], tolerance: float=.01) -> dict:
    """Converge MAIN height and equivalent sibling columns/rows from UIA geometry."""
    main=refresh_worker_topology(store,main_id)
    workers=refresh_all(store,worker_ids)
    # use a worker sharing MAIN's first horizontal splitter
    main_result=converge_pair(main["topology_json"],workers[0]["topology_json"],"height",.5,tolerance)
    # Equalize panes by repeatedly compare every worker to the first in its row.
    for _ in range(8):
        workers=refresh_all(store,worker_ids)
        bounds=measured(main["topology_json"])
        adjusted = False
        rows={}
        for worker in workers:
            p=bounds[worker["topology_json"]["pane"]["runtime_id"]]
            rows.setdefault(round(p[1]),[]).append(worker)
        for row in rows.values():
            row.sort(key=lambda x:bounds[x["topology_json"]["pane"]["runtime_id"]][0])
            # Neighbour relaxation converges an N-pane row toward equal widths
            # without assuming a particular Windows Terminal split tree.
            for left,right in zip(row,row[1:]):
                result = converge_pair(left["topology_json"],right["topology_json"],"width",.5,tolerance)
                adjusted = adjusted or result["iterations"] > 0
        if not adjusted:
            break
    workers=refresh_all(store,worker_ids)
    return {"main":main_result,"bounds":measured(main["topology_json"]),"workers":workers}
