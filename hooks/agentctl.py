#!/usr/bin/env python3
"""Short-lived safe native-console controller for launcher sessions."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent_identity import TargetError, list_power_shells, resolve_target, validate_target  # noqa: E402
from native_console import (ConsoleError, attached_console, console_modes, console_processes,
                            interrupt_console, read_screen, write_key, write_text)  # noqa: E402


def _result(**values):
    values.setdefault("ok", True)
    return values


def _validated(value: str, expected_start_time: str | None = None):
    try:
        ref = resolve_target(value)
    except TargetError as exc:
        if expected_start_time and exc.code == "NOT_FOUND":
            raise TargetError("STALE_TARGET", f"Target PID {value} disappeared after it was identified.") from exc
        raise
    if expected_start_time and ref.process_start_time != expected_start_time:
        raise TargetError("STALE_TARGET", f"Target PID {ref.pid} no longer has the expected start time.")
    return validate_target(ref)


def read(value: str, expected_start_time: str | None = None) -> dict:
    ref = _validated(value, expected_start_time)
    with attached_console(ref.pid) as handles:
        return _result(phase="RESPONSE_OBSERVED", target=ref.to_dict(), screen=read_screen(handles),
                       console_modes=console_modes(handles), console_processes=console_processes(handles))


def send(value: str, text: str, enter: bool, verify: str | None, timeout: float,
         expected_start_time: str | None = None) -> dict:
    ref = _validated(value, expected_start_time)
    with attached_console(ref.pid) as handles:
        before = read_screen(handles)
        prior_marker_count = before.count(verify) if verify else 0
        queued = write_text(handles, text)
        if enter:
            queued += write_key(handles, "enter")
        deadline = time.monotonic() + timeout
        screen, observed = before, False
        while time.monotonic() < deadline:
            screen = read_screen(handles)
            # A command marker appears once while PowerShell echoes the typed
            # command and a second time only after Write-Output executes it.
            # Do not call input echo command completion.
            observed = (screen.count(verify) >= prior_marker_count + 2) if verify else (screen != before or text in screen)
            if observed:
                break
            time.sleep(0.05)
        phase = "COMMAND_EXECUTED" if verify and observed else ("INPUT_OBSERVED" if observed else "INPUT_QUEUED")
        return _result(phase=phase, target=ref.to_dict(), records_written=queued,
                       input_observed=observed, verification_marker=verify,
                       screen=screen, console_modes=console_modes(handles))


def key(value: str, name: str, expected_start_time: str | None = None) -> dict:
    ref = _validated(value, expected_start_time)
    with attached_console(ref.pid) as handles:
        return _result(phase="INPUT_QUEUED", target=ref.to_dict(), records_written=write_key(handles, name))


def interrupt(value: str, expected_start_time: str | None = None) -> dict:
    ref = _validated(value, expected_start_time)
    return _result(phase="INTERRUPT_DELIVERED", target=ref.to_dict(), console_processes=interrupt_console(ref.pid))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentctl")
    sub = p.add_subparsers(dest="command", required=True)
    parsers = [sub.add_parser("list")]
    for name in ("inspect", "read", "interrupt"):
        q = sub.add_parser(name); q.add_argument("target"); parsers.append(q)
    q = sub.add_parser("send")
    q.add_argument("target"); q.add_argument("message")
    q.add_argument("--enter", action="store_true")
    q.add_argument("--verify", metavar="MARKER")
    q.add_argument("--timeout", type=float, default=3.0)
    parsers.append(q)
    q = sub.add_parser("key")
    q.add_argument("target"); q.add_argument("key", choices=("enter", "escape", "up", "down", "left", "right"))
    parsers.append(q)
    q = sub.add_parser("wait")
    q.add_argument("target"); q.add_argument("--timeout", type=float, default=300); q.add_argument("--poll", type=float, default=2)
    parsers.append(q)
    for child in parsers:
        child.add_argument("--json", action="store_true", help="machine-readable result")
        if child.prog.split()[-1] != "list":
            child.add_argument("--expect-start-time", help="reject a target that is not this original process instance")
    return p


def wait(value: str, timeout: float, poll: float) -> dict:
    ref = _validated(value)
    if not ref.remote_control_name:
        return _result(phase="NOT_EXPOSED", target=ref.to_dict(), detail="No Claude remote-control state is associated with this target.")
    from agents_state import by_remote_control_name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        agent = by_remote_control_name().get(ref.remote_control_name)
        if agent and agent.get("status") == "idle":
            return _result(phase="AGENT_COMPLETED", target=ref.to_dict(), status="idle")
        time.sleep(poll)
    return {"ok": False, "phase": "TIMEOUT", "target": ref.to_dict()}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            data = _result(phase="TARGET_VALID", targets=[x.to_dict() for x in list_power_shells()])
        elif args.command == "inspect": data = _result(phase="TARGET_VALID", target=_validated(args.target, args.expect_start_time).to_dict())
        elif args.command == "read": data = read(args.target, args.expect_start_time)
        elif args.command == "send": data = send(args.target, args.message, args.enter, args.verify, args.timeout, args.expect_start_time)
        elif args.command == "key": data = key(args.target, args.key, args.expect_start_time)
        elif args.command == "interrupt": data = interrupt(args.target, args.expect_start_time)
        else: data = wait(args.target, args.timeout, args.poll)
    except (TargetError, ConsoleError) as exc:
        data = {"ok": False, "code": getattr(exc, "code", "NATIVE_CONSOLE_ERROR"), "error": str(exc)}
    print(json.dumps(data, indent=2))
    return 0 if data.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
