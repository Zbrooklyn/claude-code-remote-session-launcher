import pytest

import layout_normalizer
from terminal_topology import TopologyError, bind_certificate, enumerate_topology, resolve_pane
import terminal_control


def test_certificate_binding_requires_two_channels():
    pane = {"bridge_id": "pane_1", "title": "cert", "certificate": None}
    topology = {"panes": [pane]}
    result = bind_certificate(topology, "cert", {"pid": 7, "process_start_time": "s", "process_image": "pwsh"}, "cert output")
    assert result["bridge_id"] == "pane_1"


def test_certificate_binding_rejects_ambiguous_title():
    with pytest.raises(TopologyError, match="2 panes"):
        bind_certificate({"panes": [{"title": "cert"}, {"title": "cert"}]}, "cert", {"pid": 7, "process_start_time": "s", "process_image": "pwsh"}, "cert")


def test_resolve_pane_rejects_stale_id():
    with pytest.raises(TopologyError, match="STALE_PANE"):
        resolve_pane({"panes": []}, "pane_missing")


def test_global_inactive_scan_is_refused_before_uia():
    with pytest.raises(TopologyError, match="OWNED_HWND"):
        enumerate_topology(exhaustive=True)


def test_focus_retries_a_transient_uia_tree_failure(monkeypatch):
    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    attempts = iter((Result(1, stderr="ElementNotAvailableException"), Result(0, stdout="OK\n")))
    monkeypatch.setattr(terminal_control.subprocess, "run", lambda *_, **__: next(attempts))
    monkeypatch.setattr(terminal_control.time, "sleep", lambda _: None)

    terminal_control._focus("certified-runtime", "pane")


def test_resize_retries_a_stale_runtime_within_the_owned_window(monkeypatch):
    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    attempts = iter((Result(1, stderr="STALE_UIA_ELEMENT"), Result(0, stdout="OK\n")))
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return next(attempts)

    monkeypatch.setattr(terminal_control.subprocess, "run", run)
    monkeypatch.setattr(terminal_control.time, "sleep", lambda _: None)
    topology = {
        "window": {"hwnd": 77},
        "pane": {"runtime_id": "stale-runtime"},
        "certificate": "unique-certificate",
    }

    terminal_control.resize_exact_pane(topology, "right", 2)

    assert len(calls) == 2
    assert calls[0][1]["env"]["ORCH_UIA_HWND"] == "77"
    assert calls[0][1]["env"]["ORCH_UIA_CERTIFICATE"] == "unique-certificate"


def test_three_column_normalization_corrects_a_two_percent_neighbor_skew(monkeypatch):
    # A 2% pair skew compounds across a three-column row into a >6% outer
    # width difference, so the normalizer must not accept it as balanced.
    measurements = iter(((0.52, 1000), (0.50, 1000)))
    actions = []
    monkeypatch.setattr(layout_normalizer, "_pair_measurement", lambda *_: next(measurements))
    monkeypatch.setattr(layout_normalizer, "resize_exact_pane", lambda *args: actions.append(args))

    result = layout_normalizer.converge_pair({"pane": {}}, {"pane": {}}, "width", 0.5)

    assert result["converged"]
    assert len(actions) == 1
    assert actions[0][1] == "left"
    assert actions[0][2] >= 1


def test_normalizer_batches_a_measured_large_pane_skew(monkeypatch):
    first = {"pane": {"runtime_id": "left"}}
    second = {"pane": {"runtime_id": "right"}}
    measurements = iter((
        {"left": (0, 0, 753, 687), "right": (753, 0, 696, 687)},
        {"left": (0, 0, 725, 687), "right": (725, 0, 724, 687)},
    ))
    actions = []
    monkeypatch.setattr(layout_normalizer, "measured", lambda _: next(measurements))
    monkeypatch.setattr(layout_normalizer, "resize_exact_pane", lambda *args: actions.append(args))

    result = layout_normalizer.converge_pair(first, second, "width", 0.5)

    assert result["converged"]
    assert actions == [(first, "left", 4)]


def test_split_restores_the_prior_foreground_window_when_wt_fails(monkeypatch):
    events = []
    monkeypatch.setattr(terminal_control, "_foreground_window", lambda: 42)
    monkeypatch.setattr(terminal_control, "_restore_foreground", lambda hwnd: events.append(("restore", hwnd)))
    monkeypatch.setattr(terminal_control, "focus_worker", lambda _: events.append(("focus",)))
    monkeypatch.setattr(terminal_control, "_wt", lambda *_: (_ for _ in ()).throw(terminal_control.TerminalControlError("wt failed")))
    topology = {"window_name": "owned"}

    with pytest.raises(terminal_control.TerminalControlError, match="wt failed"):
        terminal_control.split_relative(topology, "powershell.exe", "worker", "Write-Output worker")

    assert events == [("focus",), ("restore", 42)]


def test_verified_pane_close_rejects_a_pane_that_remains_after_the_action(monkeypatch):
    topology = {"window": {"hwnd": 7}, "pane": {"runtime_id": "pane-old"}}
    monkeypatch.setattr(terminal_control, "enumerate_topology", lambda **_: {"panes": [{"runtime_id": "pane-old"}]})
    monkeypatch.setattr(terminal_control, "_close_pane_hotkey", lambda _: None)

    with pytest.raises(terminal_control.TerminalControlError, match="PANE_CLOSE_UNPROVEN"):
        terminal_control.close_pane_and_verify(topology)


def test_verified_pane_close_uses_the_certified_pane_hotkey_when_wt_action_does_not_close(monkeypatch):
    topology = {"window": {"hwnd": 7}, "pane": {"runtime_id": "pane-old"}}
    snapshots = iter((
        {"panes": [{"runtime_id": "pane-old"}]},
        {"panes": []},
    ))
    fallback = []
    monkeypatch.setattr(terminal_control, "enumerate_topology", lambda **_: next(snapshots))
    monkeypatch.setattr(terminal_control, "_close_pane_hotkey", lambda value: fallback.append(value))

    terminal_control.close_pane_and_verify(topology)

    assert fallback == [topology]


def test_verified_pane_close_rebinds_a_uniquely_certified_redraw(monkeypatch):
    topology = {"window": {"hwnd": 7}, "pane": {"runtime_id": "pane-old"}, "certificate": "cert"}
    snapshots = iter((
        {"panes": [{"runtime_id": "pane-redrawn", "title": "cert"}]},
        {"panes": []},
    ))
    focused = []
    monkeypatch.setattr(terminal_control, "enumerate_topology", lambda **_: next(snapshots))
    monkeypatch.setattr(terminal_control, "_close_pane_hotkey", lambda value: focused.append(value))

    terminal_control.close_pane_and_verify(topology)

    assert focused[0]["pane"]["runtime_id"] == "pane-redrawn"
