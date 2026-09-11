"""A queued input in a one-row console is diagnosed as PANE_TOO_SHORT, and the
verification gate still refuses to call it executed."""
import agentctl


class _Handles:
    input = 1
    output = 2


class _Console:
    def __enter__(self):
        return _Handles()
    def __exit__(self, *exc):
        return False


def _patch(monkeypatch, *, window_rows, screen):
    # screen may be a single string (returned for every read) or a sequence of
    # screens returned in order (before, then after the input is typed).
    if isinstance(screen, (list, tuple)):
        it = iter(screen)
        last = [screen[0]]
        def _read(_h):
            try:
                last[0] = next(it)
            except StopIteration:
                pass
            return last[0]
    else:
        def _read(_h):
            return screen
    monkeypatch.setattr(agentctl, "attached_console", lambda pid: _Console())
    monkeypatch.setattr(agentctl, "read_screen", _read)
    monkeypatch.setattr(agentctl, "write_text", lambda h, t: len(t))
    monkeypatch.setattr(agentctl, "write_key", lambda h, k: 2)
    monkeypatch.setattr(agentctl, "console_modes", lambda h: {"input": 484, "output": 7})
    monkeypatch.setattr(agentctl, "console_dimensions", lambda h: {
        "buffer_cols": 53, "buffer_rows": window_rows, "window_cols": 53, "window_rows": window_rows})

    class _Ref:
        pid = 4242
        process_start_time = "s"
        def to_dict(self):
            return {"pid": self.pid, "process_start_time": self.process_start_time}
    monkeypatch.setattr(agentctl, "_validated", lambda value, expected=None: _Ref())


def test_one_row_console_reports_pane_too_short_and_not_executed(monkeypatch):
    # Screen never shows the marker twice: the command did not run.
    _patch(monkeypatch, window_rows=1, screen="PS>")
    result = agentctl.send("4242", "Write-Output 'x'; Write-Output 'ORCH_M'", True, "ORCH_M", 0.2)
    assert result["phase"] == "INPUT_QUEUED"
    assert result["queued_reason"] == "PANE_TOO_SHORT"
    assert result["console_dimensions"]["window_rows"] == 1


def test_tall_console_that_echoes_the_marker_twice_is_executed(monkeypatch):
    # before: no marker; after: the echo of the command plus its output = twice.
    _patch(monkeypatch, window_rows=20, screen=["PS>", "PS> ...ORCH_M\nx\nORCH_M\nPS>"])
    result = agentctl.send("4242", "Write-Output 'x'; Write-Output 'ORCH_M'", True, "ORCH_M", 0.2)
    assert result["phase"] == "COMMAND_EXECUTED"
    assert "queued_reason" not in result


def test_tall_console_without_the_marker_is_queued_but_not_pane_too_short(monkeypatch):
    _patch(monkeypatch, window_rows=20, screen="PS>")
    result = agentctl.send("4242", "Write-Output 'ORCH_M'", True, "ORCH_M", 0.2)
    assert result["phase"] == "INPUT_QUEUED"
    assert "queued_reason" not in result
