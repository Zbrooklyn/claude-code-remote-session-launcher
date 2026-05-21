#!/usr/bin/env python3
"""
spawn-window.py — shared launcher for /window, /daemon families.

Invoked from .claude/commands/<mode>.md via:
  python spawn-window.py <mode> "$ARGUMENTS"

Modes:
  window               terminal, standard perms
  window-remote        terminal, standard perms, --remote-control
  window-yolo          terminal, --dangerously-skip-permissions
  window-yolo-remote   terminal, yolo + remote
  daemon               headless (hidden), --remote-control
  daemon-yolo          headless, yolo + remote

Arg shape (positional + flag):
  [workspace-path] ["first prompt"] [--worktree] [--name <label>]

If a positional path is given and exists, cd into it; else treat first
positional as the prompt. --worktree flag adds --worktree to claude.
--name <label> sets a friendly session name: {host_user}-{label}-{HHMMSS}
instead of the default {host}-{mode}-{HHMMSS}.
"""
from __future__ import annotations
import json
import os
import shlex
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CLAUDE_EXE = str(Path.home() / ".local" / "bin" / "claude.exe")
CONFIG_PATH = Path.home() / ".claude" / "window-config.json"
CLAUDE_GLOBAL_JSON = Path.home() / ".claude.json"
LOG_PATH = Path.home() / ".claude" / "window-log.jsonl"


def log_spawn(mode: str, workspace: str, sess_name: str, prompt: str | None, worktree: bool, label: str | None = None) -> None:
    """Append a JSONL record of every successful spawn."""
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "workspace": workspace,
        "session_name": sess_name if sess_name else None,
        "label": label,
        "prompt": prompt,
        "worktree": worktree,
    }
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # log failure shouldn't break the spawn


def load_config() -> dict | None:
    """Return the window-config dict, or None if missing/invalid."""
    if not CONFIG_PATH.is_file():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _normalize_path(p: str) -> str:
    """Normalize a path for trust-list comparison: forward slashes, no trailing slash, case-insensitive on Windows."""
    np = str(Path(p).resolve()).replace("\\", "/").rstrip("/")
    return np.lower() if os.name == "nt" else np


def trusted_canonical(workspace: str, extra_allow: list[str] | None = None) -> str | None:
    """Return the canonical trusted-path string for this workspace, or None if not trusted.

    Returns the EXACT string from Claude's trust list (or extra_allow) so the
    spawned terminal's cwd matches a known key — avoiding the trust dialog.
    """
    nw = _normalize_path(workspace)
    if extra_allow:
        for a in extra_allow:
            if _normalize_path(a) == nw:
                return a
    if not CLAUDE_GLOBAL_JSON.is_file():
        return None
    try:
        data = json.loads(CLAUDE_GLOBAL_JSON.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    projects = data.get("projects", {}) or {}
    for path, info in projects.items():
        if not isinstance(info, dict):
            continue
        if not info.get("hasTrustDialogAccepted"):
            continue
        if _normalize_path(path) == nw:
            return path
    return None


def is_trusted(workspace: str, extra_allow: list[str] | None = None) -> bool:
    return trusted_canonical(workspace, extra_allow) is not None

MODES = {
    "window":             {"remote": False, "yolo": False, "headless": False},
    "window-remote":      {"remote": True,  "yolo": False, "headless": False},
    "window-yolo":        {"remote": False, "yolo": True,  "headless": False},
    "window-yolo-remote": {"remote": True,  "yolo": True,  "headless": False},
    "daemon":             {"remote": True,  "yolo": False, "headless": True},
    "daemon-yolo":        {"remote": True,  "yolo": True,  "headless": True},
}


def parse_args(raw: str) -> tuple[str | None, str | None, bool, str | None]:
    """Return (workspace, first_prompt, worktree_flag, name_label).

    Handles paths with spaces by trying progressively longer joins of the
    positional tokens until one resolves to an existing directory. If no
    prefix is a valid dir but the first token looks path-like (starts with
    drive letter, ~, /, .), treat the longest prefix that looks path-like
    as the workspace.

    --name <label> consumes the next token as the session label.
    """
    if not raw.strip():
        return (None, None, False, None)
    try:
        toks = shlex.split(raw)
    except ValueError:
        toks = raw.split()

    worktree = False
    name_label: str | None = None
    positional: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "--worktree":
            worktree = True
        elif t == "--name":
            # Only consume next token as the label if it's not itself a flag.
            # This prevents "--name --worktree" from eating --worktree.
            if i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                name_label = toks[i + 1]
                i += 1
            else:
                # --name with no value, or followed by another flag
                print(
                    "ERROR: --name needs a non-empty label as the next argument.",
                    file=sys.stderr,
                )
                sys.exit(2)
        elif t.startswith("--"):
            pass  # unknown flag — ignore for now
        else:
            positional.append(t)
        i += 1

    if not positional:
        return (None, None, worktree, name_label)

    def _looks_pathlike(s: str) -> bool:
        return s.startswith((".", "/", "~")) or (len(s) >= 2 and s[1] == ":")

    workspace: str | None = None
    prompt: str | None = None
    # Try longest prefix as path: positional[:N], positional[:N-1], ..., positional[:1]
    for n in range(len(positional), 0, -1):
        candidate_str = " ".join(positional[:n])
        candidate = Path(candidate_str).expanduser()
        if candidate.is_dir():
            workspace = str(candidate)
            if n < len(positional):
                prompt = " ".join(positional[n:])
            return (workspace, prompt, worktree, name_label)

    # Nothing existed — but if the first token looks path-like, treat the
    # longest path-like prefix as a workspace anyway (so we can produce a
    # proper "not trusted" message instead of treating it as a prompt).
    if _looks_pathlike(positional[0]):
        # Take all consecutive tokens that don't look like prompts (no quotes etc.)
        workspace = " ".join(positional)
        return (workspace, None, worktree, name_label)

    # All positionals are a prompt
    return (None, " ".join(positional), worktree, name_label)


def session_name(mode: str, label: str | None = None) -> str:
    host = socket.gethostname().lower()
    ts = datetime.now().strftime("%H%M%S")
    if label:
        host_user = host.split("-")[0]
        return f"{host_user}-{label}-{ts}"
    return f"{host}-{mode}-{ts}"


def build_claude_args(mode: str, cfg: dict, prompt: str | None, worktree: bool, sess_name: str) -> list[str]:
    args = [CLAUDE_EXE]
    if cfg["yolo"]:
        args.append("--dangerously-skip-permissions")
    if cfg["remote"]:
        args.extend(["--remote-control", sess_name])
    if worktree:
        args.append("--worktree")
    if prompt:
        args.append(prompt)
    return args


def launch(mode: str, workspace: str | None, prompt: str | None, worktree: bool, label: str | None = None) -> int:
    cfg = MODES[mode]
    cwd = workspace or os.getcwd()
    if not Path(cwd).is_dir():
        print(f"ERROR: workspace dir does not exist: {cwd}", file=sys.stderr)
        return 1

    # Generate session name ONCE so the print matches what was passed to claude.exe.
    sess_name = session_name(mode, label)
    claude_args = build_claude_args(mode, cfg, prompt, worktree, sess_name)
    title = f"{mode}: {Path(cwd).name}"
    profile = "Claude Code (Yolo)" if cfg["yolo"] else "Claude Code"

    if cfg["headless"]:
        # Spawn wt.exe with -w new so the daemon runs in its own separate
        # window (not crowding your current WT tabs). claude.exe needs a
        # real console for --remote-control to register with Anthropic;
        # the headless-no-console approach (Start-Process -WindowStyle
        # Hidden) silently fails the handshake. So the daemon's window IS
        # visible at first — minimize it manually if you don't want to see it.
        wt_args = [
            "wt.exe", "-w", "new",
            "--profile", profile,
            "--title", f"DAEMON: {Path(cwd).name}",
            "-d", cwd,
            "--", *claude_args,
        ]
        try:
            subprocess.Popen(wt_args, close_fds=True)
            print(f"Launched daemon ({mode}) in {cwd}. Remote session: {sess_name}")
            print("Reach it at claude.ai/code or the official mobile app.")
            print("A new Windows Terminal window opened — minimize it manually if you want it out of sight.")
            log_spawn(mode, cwd, sess_name, prompt, worktree, label)
            return 0
        except FileNotFoundError:
            print("ERROR: wt.exe not found. Daemon mode requires Windows Terminal.", file=sys.stderr)
            return 1

    # Terminal mode — use Windows Terminal, fall back to cmd start
    wt_args = [
        "wt.exe", "-w", "0", "nt",
        "--profile", profile,
        "--title", title,
        "-d", cwd,
        "--", *claude_args,
    ]
    try:
        subprocess.Popen(wt_args, close_fds=True)
        msg = f"Launched terminal ({mode}) in {cwd}"
        if cfg["remote"]:
            msg += f". Remote session: {sess_name}"
        print(msg)
        log_spawn(mode, cwd, sess_name if cfg["remote"] else "", prompt, worktree, label)
        return 0
    except FileNotFoundError:
        # WT not installed — fall back to cmd /k
        claude_cmd = " ".join(shlex.quote(a) for a in claude_args)
        fallback = ["cmd", "/c", "start", "cmd", "/k", f'cd /d "{cwd}" && {claude_cmd}']
        try:
            subprocess.Popen(fallback, close_fds=True)
            print(f"Launched ({mode}) via cmd fallback in {cwd}")
            log_spawn(mode, cwd, sess_name if cfg["remote"] else "", prompt, worktree, label)
            return 0
        except Exception as e:
            print(f"ERROR: fallback launch failed: {e}", file=sys.stderr)
            return 1


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        print(f"Usage: spawn-window.py <mode> [args]\nModes: {', '.join(MODES)}", file=sys.stderr)
        return 2
    mode = sys.argv[1]
    raw = sys.argv[2] if len(sys.argv) > 2 else ""

    config = load_config()
    if config is None:
        print(
            "ERROR: window-config.json not found at "
            f"{CONFIG_PATH}. Run /window-setup first to configure defaults "
            "and enable the workspace trust check.",
            file=sys.stderr,
        )
        return 3

    workspace, prompt, worktree, label = parse_args(raw)

    # If --name was passed, validate the label before going any further.
    # Bad labels would either become broken --remote-control values or
    # collide with CLI flag parsing downstream.
    if label is not None:
        sys.path.insert(0, str(Path(__file__).parent))
        from window_aliases import validate_label  # noqa: E402
        ok, err = validate_label(label)
        if not ok:
            print(f"ERROR: invalid --name value: {err}", file=sys.stderr)
            return 2

    if workspace is None:
        workspace = config.get("default_workspace") or os.getcwd()

    extra_allow = config.get("extra_allow_list") or []
    canonical = trusted_canonical(workspace, extra_allow)
    if canonical is None:
        print(
            f"REFUSED: workspace not trusted — {workspace}\n\n"
            "This directory hasn't been opened in Claude Code locally, so spawning "
            "remotely is blocked for safety (Claude Code's trust dialog would block "
            "the new session anyway).\n\n"
            "To fix: open Claude Code locally in this directory once, accept the "
            "trust dialog, then retry. Or add the path to extra_allow_list in "
            f"{CONFIG_PATH} if you've vetted it.",
            file=sys.stderr,
        )
        return 4

    return launch(mode, canonical, prompt, worktree, label)


if __name__ == "__main__":
    sys.exit(main())
