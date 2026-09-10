#!/usr/bin/env python3
"""One tested Win32 implementation for PID-targeted console control.

This module owns the value-type-sensitive INPUT_RECORD construction.  Callers
must never recreate the nested KEY_EVENT_RECORD structures themselves.
"""
from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass


class ConsoleError(RuntimeError):
    pass


if sys.platform == "win32":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    DWORD = wintypes.DWORD
    WORD = wintypes.WORD
    SHORT = ctypes.c_short
    HANDLE = wintypes.HANDLE
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE = 0x00000001, 0x00000002
    OPEN_EXISTING = 3
    KEY_EVENT, CTRL_C_EVENT = 0x0001, 0

    class COORD(ctypes.Structure):
        _fields_ = [("X", SHORT), ("Y", SHORT)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [("Left", SHORT), ("Top", SHORT), ("Right", SHORT), ("Bottom", SHORT)]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", WORD),
                   ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", WORD),
                   ("wVirtualKeyCode", WORD), ("wVirtualScanCode", WORD),
                   ("uChar", wintypes.WCHAR), ("dwControlKeyState", DWORD)]

    class INPUT_EVENT_UNION(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", WORD), ("Event", INPUT_EVENT_UNION)]

    kernel32.AttachConsole.argtypes = [DWORD]
    kernel32.AttachConsole.restype = wintypes.BOOL
    kernel32.FreeConsole.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE]
    kernel32.CreateFileW.restype = HANDLE
    kernel32.WriteConsoleInputW.argtypes = [HANDLE, ctypes.POINTER(INPUT_RECORD), DWORD, ctypes.POINTER(DWORD)]
    kernel32.WriteConsoleInputW.restype = wintypes.BOOL
    kernel32.ReadConsoleOutputCharacterW.argtypes = [HANDLE, wintypes.LPWSTR, DWORD, COORD, ctypes.POINTER(DWORD)]
    kernel32.ReadConsoleOutputCharacterW.restype = wintypes.BOOL
    kernel32.GetConsoleScreenBufferInfo.argtypes = [HANDLE, ctypes.POINTER(CONSOLE_SCREEN_BUFFER_INFO)]
    kernel32.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    kernel32.GetConsoleMode.argtypes = [HANDLE, ctypes.POINTER(DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL
    kernel32.GetConsoleProcessList.argtypes = [ctypes.POINTER(DWORD), DWORD]
    kernel32.GetConsoleProcessList.restype = DWORD
    kernel32.GenerateConsoleCtrlEvent.argtypes = [DWORD, DWORD]
    kernel32.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    kernel32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel32.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass
class ConsoleHandles:
    input: int
    output: int


def _require_windows() -> None:
    if sys.platform != "win32":
        raise ConsoleError("Native console control is available only on Windows.")


def _last_error(action: str) -> ConsoleError:
    return ConsoleError(f"{action} failed (Win32 error {ctypes.get_last_error()}).")


@contextlib.contextmanager
def attached_console(pid: int):
    """Attach only for this operation, close handles, then detach."""
    _require_windows()
    kernel32.FreeConsole()  # controller may have inherited a console
    if not kernel32.AttachConsole(int(pid)):
        raise _last_error(f"AttachConsole({pid})")
    inp = out = None
    try:
        inp = kernel32.CreateFileW("CONIN$", GENERIC_READ | GENERIC_WRITE,
                                   FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        out = kernel32.CreateFileW("CONOUT$", GENERIC_READ | GENERIC_WRITE,
                                   FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        if inp == INVALID_HANDLE_VALUE:
            raise _last_error("Open CONIN$")
        if out == INVALID_HANDLE_VALUE:
            raise _last_error("Open CONOUT$")
        yield ConsoleHandles(inp, out)
    finally:
        if inp not in (None, INVALID_HANDLE_VALUE):
            kernel32.CloseHandle(inp)
        if out not in (None, INVALID_HANDLE_VALUE):
            kernel32.CloseHandle(out)
        kernel32.FreeConsole()


def _input_record(character: str, down: bool, vk: int = 0) -> "INPUT_RECORD":
    # Assign a complete value type into the union.  Do not mutate a nested
    # ctypes/PowerShell field; doing so is the Phase 5 marshaling failure.
    key = KEY_EVENT_RECORD(bool(down), 1, vk, 0, character, 0)
    record = INPUT_RECORD()
    record.EventType = KEY_EVENT
    record.Event.KeyEvent = key
    return record


_KEYS = {"enter": ("\r", 0x0D), "escape": ("\x1b", 0x1B),
         "up": ("\x00", 0x26), "down": ("\x00", 0x28),
         "left": ("\x00", 0x25), "right": ("\x00", 0x27)}


def write_text(handles: ConsoleHandles, text: str) -> int:
    """Queue real key-down/key-up records and return records accepted by Windows."""
    _require_windows()
    records = []
    for char in text:
        vk = 0x0D if char in ("\r", "\n") else 0
        char = "\r" if char == "\n" else char
        records.extend((_input_record(char, True, vk), _input_record(char, False, vk)))
    if not records:
        return 0
    array = (INPUT_RECORD * len(records))(*records)
    written = DWORD()
    if not kernel32.WriteConsoleInputW(handles.input, array, len(records), ctypes.byref(written)):
        raise _last_error("WriteConsoleInputW")
    return int(written.value)


def write_key(handles: ConsoleHandles, name: str) -> int:
    try:
        char, vk = _KEYS[name.lower()]
    except KeyError as exc:
        raise ConsoleError(f"Unsupported key {name!r}.") from exc
    records = (INPUT_RECORD * 2)(_input_record(char, True, vk), _input_record(char, False, vk))
    written = DWORD()
    if not kernel32.WriteConsoleInputW(handles.input, records, 2, ctypes.byref(written)):
        raise _last_error("WriteConsoleInputW")
    return int(written.value)


def read_screen(handles: ConsoleHandles) -> str:
    """Read the visible current screen buffer (not UIA scrollback)."""
    _require_windows()
    info = CONSOLE_SCREEN_BUFFER_INFO()
    if not kernel32.GetConsoleScreenBufferInfo(handles.output, ctypes.byref(info)):
        raise _last_error("GetConsoleScreenBufferInfo")
    width, height = int(info.dwSize.X), int(info.dwSize.Y)
    if width <= 0 or height <= 0:
        return ""
    chars = width * height
    buf = ctypes.create_unicode_buffer(chars + 1)
    got = DWORD()
    if not kernel32.ReadConsoleOutputCharacterW(handles.output, buf, chars, COORD(0, 0), ctypes.byref(got)):
        raise _last_error("ReadConsoleOutputCharacterW")
    return buf[:got.value]


def console_modes(handles: ConsoleHandles) -> dict[str, int | None]:
    answer: dict[str, int | None] = {}
    for name, handle in (("input", handles.input), ("output", handles.output)):
        mode = DWORD()
        answer[name] = int(mode.value) if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) else None
    return answer


def console_processes(handles: ConsoleHandles) -> list[int]:
    size = 16
    while size <= 4096:
        values = (DWORD * size)()
        count = kernel32.GetConsoleProcessList(values, size)
        if count <= size:
            return [int(values[i]) for i in range(count)]
        size = int(count) + 8
    raise _last_error("GetConsoleProcessList")


def interrupt_console(pid: int) -> list[int]:
    """Deliver CTRL+C only after caller checked the console membership."""
    _require_windows()
    with attached_console(pid) as handles:
        members = console_processes(handles)
        # The attached controller itself is expected. Any other process makes
        # console-wide Ctrl+C unsafe without an explicit override at the CLI.
        others = set(members) - {int(pid), os.getpid()}
        if others:
            raise ConsoleError("REFUSE_UNSAFE_INTERRUPT: console also contains " + ", ".join(map(str, sorted(others))))
        if not kernel32.SetConsoleCtrlHandler(None, True):
            raise _last_error("SetConsoleCtrlHandler")
        try:
            if not kernel32.GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0):
                raise _last_error("GenerateConsoleCtrlEvent")
            time.sleep(0.15)
        finally:
            kernel32.SetConsoleCtrlHandler(None, False)
        return members
