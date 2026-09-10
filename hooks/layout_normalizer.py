"""Geometry-driven normalization for bridge-owned Windows Terminal panes."""
from __future__ import annotations
from terminal_control import resize_exact_pane
from terminal_topology import enumerate_topology

def measured(topology: dict) -> dict[str, tuple[float,float,float,float]]:
    panes=enumerate_topology(exhaustive=True,hwnds=[topology["window"]["hwnd"]])["panes"]
    return {p["runtime_id"]:tuple(p["bounds"]) for p in panes}

def ratio(first: dict, second: dict, axis: str) -> float:
    bounds=measured(first); index=3 if axis=="height" else 2
    a=bounds[first["pane"]["runtime_id"]][index]; b=bounds[second["pane"]["runtime_id"]][index]
    return a/(a+b)

def converge_pair(first: dict, second: dict, axis: str, target: float, tolerance: float=.03, steps: int=80) -> dict:
    for iteration in range(steps):
        current=ratio(first,second,axis)
        if abs(current-target)<=tolerance:
            return {"ratio":current,"iterations":iteration,"converged":True}
        if axis=="height": direction="down" if current<target else "up"
        else: direction="right" if current<target else "left"
        resize_exact_pane(first,direction,1)
    return {"ratio":ratio(first,second,axis),"iterations":steps,"converged":False}
