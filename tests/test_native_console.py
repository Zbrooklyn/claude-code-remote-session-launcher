from __future__ import annotations

import sys

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
