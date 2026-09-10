"""Bridge-owned MAIN/worker layout construction and measured normalization."""
from __future__ import annotations

from layout_normalizer import converge_pair, measured
from worker_runtime import spawn_worker, refresh_worker_topology


def create_workers(store, main_id: str, roles: list[str], engine: str = "powershell.exe") -> list[dict]:
    """Create a balanced worker topology below an unchanged MAIN controller."""
    main=store.worker(main_id); workers=[]
    if not roles:return workers
    # First split creates the lower worker region. Subsequent vertical splits
    # create columns; for 4/6, horizontal splits turn those columns into rows.
    first=spawn_worker(store, roles[0], roles[0], engine, main_id, direction="right"); workers.append(first)
    columns=2 if len(roles)==4 else 3 if len(roles)>=3 else len(roles)
    for role in roles[1:columns]:
        workers.append(spawn_worker(store,role,role,engine,workers[-1]["id"],direction="down"))
    if len(roles)>columns:
        for index,role in enumerate(roles[columns:]):
            workers.append(spawn_worker(store,role,role,engine,workers[index]["id"],direction="right"))
    return workers


def refresh_all(store, ids: list[str]) -> list[dict]:
    return [refresh_worker_topology(store, worker_id) for worker_id in ids]


def normalize_main_and_workers(store, main_id: str, worker_ids: list[str], tolerance: float=.03) -> dict:
    """Converge MAIN height and equivalent sibling columns/rows from UIA geometry."""
    main=refresh_worker_topology(store,main_id)
    workers=refresh_all(store,worker_ids)
    # use a worker sharing MAIN's first horizontal splitter
    main_result=converge_pair(main["topology_json"],workers[0]["topology_json"],"height",.5,tolerance)
    # Equalize panes by repeatedly compare every worker to the first in its row.
    for _ in range(8):
        workers=refresh_all(store,worker_ids)
        bounds=measured(main["topology_json"])
        rows={}
        for worker in workers:
            p=bounds[worker["topology_json"]["pane"]["runtime_id"]]
            rows.setdefault(round(p[1]),[]).append(worker)
        for row in rows.values():
            row.sort(key=lambda x:bounds[x["topology_json"]["pane"]["runtime_id"]][0])
            # Neighbour relaxation converges an N-pane row toward equal widths
            # without assuming a particular Windows Terminal split tree.
            for left,right in zip(row,row[1:]):
                converge_pair(left["topology_json"],right["topology_json"],"width",.5,tolerance)
    workers=refresh_all(store,worker_ids)
    return {"main":main_result,"bounds":measured(main["topology_json"]),"workers":workers}
