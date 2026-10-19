"""Tests for spawn-window.py: argument parsing + claude-command construction.

spawn-window.py has a hyphen in its name, so it's loaded via importlib rather
than a normal import. We register it in sys.modules so its @dataclass / module
internals resolve correctly.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _load_spawn():
    spec = importlib.util.spec_from_file_location("spawnwindow", HOOKS / "spawn-window.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spawnwindow"] = mod
    spec.loader.exec_module(mod)
    return mod


sw = _load_spawn()


# ---------- parse_args (5-tuple: workspace, prompt, worktree, name, resume_id) ----------

def test_parse_args_empty():
    assert sw.parse_args("") == (None, None, False, None, None)


def test_parse_args_resume_and_name():
    workspace, prompt, worktree, name, resume_id = sw.parse_args("--name foo --resume SID123")
    assert name == "foo"
    assert resume_id == "SID123"


def test_parse_args_worktree_flag():
    workspace, prompt, worktree, name, resume_id = sw.parse_args("--worktree")
    assert worktree is True


def test_parse_args_path_with_spaces(tmp_path):
    d = tmp_path / "a b"
    d.mkdir()
    fwd = str(d).replace("\\", "/")  # forward slashes: shlex-safe on Windows
    workspace, prompt, worktree, name, resume_id = sw.parse_args(f'"{fwd}" "do it"')
    assert Path(workspace) == d
    assert prompt == "do it"


# ---------- build_claude_args ----------

def test_build_claude_args_resume_yolo_remote(monkeypatch):
    import claude_env
    monkeypatch.setattr(claude_env, "find_claude_binary", lambda: "/x/claude")
    args = sw.build_claude_args("window-yolo-remote", sw.MODES["window-yolo-remote"],
                                None, False, "n", "SID")
    assert args[0] == "/x/claude"
    assert "--resume" in args and "SID" in args
    assert "--dangerously-skip-permissions" in args


def test_build_claude_args_fresh_has_no_resume(monkeypatch):
    import claude_env
    monkeypatch.setattr(claude_env, "find_claude_binary", lambda: "/x/claude")
    args = sw.build_claude_args("window-remote", sw.MODES["window-remote"],
                                "hi", False, "n")
    assert "--resume" not in args
    assert "--dangerously-skip-permissions" not in args


def test_build_claude_args_dies_without_binary(monkeypatch):
    import claude_env
    monkeypatch.setattr(claude_env, "find_claude_binary", lambda: None)
    with pytest.raises(SystemExit):
        sw.build_claude_args("window", sw.MODES["window"], None, False, "n")


# ---------- spawned sessions are top-level, not nested children ----------

def test_clean_spawn_env_strips_parent_session_markers():
    parent = {
        "PATH": "/bin",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_CHILD_SESSION": "1",
        "CLAUDE_CODE_SESSION_ID": "parent-sid",
        "CLAUDE_CODE_MESSAGING_TOKEN": "tok",
        "CLAUDE_PID": "123",
    }
    env = sw.clean_spawn_env(parent)
    for key in sw.PARENT_SESSION_ENV:
        assert key not in env
    assert env["PATH"] == "/bin"
    assert env["CLAUDE_CODE_FORCE_SESSION_PERSISTENCE"] == "1"


def test_clean_spawn_env_does_not_mutate_caller_env():
    parent = {"CLAUDE_CODE_CHILD_SESSION": "1"}
    sw.clean_spawn_env(parent)
    assert parent == {"CLAUDE_CODE_CHILD_SESSION": "1"}


def test_build_claude_args_label_sets_matching_local_name(monkeypatch):
    import claude_env
    monkeypatch.setattr(claude_env, "find_claude_binary", lambda: "/x/claude")
    args = sw.build_claude_args("window-yolo-remote", sw.MODES["window-yolo-remote"],
                                None, False, "host-foo-120000", label="foo")
    i = args.index("--name")
    assert args[i + 1] == "host-foo-120000"
    assert args[args.index("--remote-control") + 1] == "host-foo-120000"


def test_build_claude_args_no_label_no_name(monkeypatch):
    import claude_env
    monkeypatch.setattr(claude_env, "find_claude_binary", lambda: "/x/claude")
    args = sw.build_claude_args("window", sw.MODES["window"], None, False, "n")
    assert "--name" not in args


def test_existing_session_title_returns_latest(claude_home):
    proj = claude_home / "projects" / "C--work"
    proj.mkdir()
    (proj / "SID1.jsonl").write_text(
        '{"type":"custom-title","customTitle":"first"}\n'
        '{"type":"user","message":"hi"}\n'
        '{"type":"custom-title","customTitle":"host-foo-120000"}\n',
        encoding="utf-8",
    )
    assert sw.existing_session_title("SID1") == "host-foo-120000"


def test_existing_session_title_missing_is_none(claude_home):
    assert sw.existing_session_title("NOPE") is None
