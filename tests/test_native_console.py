from __future__ import annotations

import sys
import os

import pytest

import native_console as console


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 structure contract")
def test_complete_key_event_records_have_expected_shape():
    record = console._input_record("X", True)
    assert record.EventType == console.KEY_EVENT
    assert record.Event.KeyEvent.bKeyDown
    assert record.Event.KeyEvent.uChar == "X"
    assert record.Event.KeyEvent.wRepeatCount == 1
    # Windows INPUT_RECORD has a 4-byte EventType/union boundary and a
    # complete 16-byte KEY_EVENT_RECORD. This guards the old partial-record bug.
    assert __import__("ctypes").sizeof(console.INPUT_RECORD) >= 20


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 key contract")
def test_enter_is_a_complete_down_up_pair():
    down = console._input_record("\r", True, 0x0D)
    up = console._input_record("\r", False, 0x0D)
    assert down.Event.KeyEvent.wVirtualKeyCode == up.Event.KeyEvent.wVirtualKeyCode == 0x0D
    assert down.Event.KeyEvent.bKeyDown and not up.Event.KeyEvent.bKeyDown


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 interrupt safety contract")
def test_interrupt_refuses_a_console_with_an_unrelated_process(monkeypatch):
    class Handles:
        input = 1
        output = 2
    class Context:
        def __enter__(self): return Handles()
        def __exit__(self, *args): return False
    monkeypatch.setattr(console, "attached_console", lambda _pid: Context())
    monkeypatch.setattr(console, "console_processes", lambda _handles: [77, os.getpid(), 88])
    with pytest.raises(console.ConsoleError, match="REFUSE_UNSAFE_INTERRUPT"):
        console.interrupt_console(77)
