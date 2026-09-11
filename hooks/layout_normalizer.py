"""Geometry-driven normalization for bridge-owned Windows Terminal panes."""
from __future__ import annotations
from terminal_control import resize_exact_pane
from terminal_topology import enumerate_topology


def measured(topology: dict) -> dict[str, tuple[float,float,float,float]]:
    # Normalization follows a freshly focused relative split, so the owned
    # team tab is active.  Do not select inactive tabs merely to measure it.
    panes=enumerate_topology(exhaustive=False,hwnds=[topology["window"]["hwnd"]])["panes"]
    return {p["runtime_id"]:tuple(p["bounds"]) for p in panes}


def _pair_measurement(first: dict, second: dict, axis: str) -> tuple[float, float]:
    bounds=measured(first); index=3 if axis=="height" else 2
    a=bounds[first["pane"]["runtime_id"]][index]; b=bounds[second["pane"]["runtime_id"]][index]
    return a/(a+b), a+b


def ratio(first: dict, second: dict, axis: str) -> float:
    return _pair_measurement(first, second, axis)[0]


def converge_pair(first: dict, second: dict, axis: str, target: float, tolerance: float=.01, steps: int=80) -> dict:
    for iteration in range(steps):
        current, span=_pair_measurement(first,second,axis)
        if abs(current-target)<=tolerance:
            return {"ratio":current,"iterations":iteration,"converged":True}
        if axis=="height": direction="down" if current<target else "up"
        else: direction="right" if current<target else "left"
        # Terminal resizes in character-cell increments.  Estimate the needed
        # cell count from the measured pixel skew, then measure again; this
        # avoids a fresh PowerShell/UIA launch for every single cell.
        amount=max(1,min(16,round(abs(current-target)*span/8)))
        resize_exact_pane(first,direction,amount)
    return {"ratio":ratio(first,second,axis),"iterations":steps,"converged":False}
