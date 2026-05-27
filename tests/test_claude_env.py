"""Tests for claude_env: config-dir resolution + claude binary discovery."""
from pathlib import Path

import claude_env


def test_claude_home_default(monkeypatch):
    monkeypatch.delenv("CLAUDE_HOME", raising=False)
    assert claude_env.claude_home() == Path.home() / ".claude"


def test_claude_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path))
    assert claude_env.claude_home() == tmp_path


def test_find_binary_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "claude.exe"
    fake.write_text("x")
    monkeypatch.setenv("CLAUDE_BINARY", str(fake))
    assert claude_env.find_claude_binary() == str(fake)


def test_find_binary_on_path(monkeypatch):
    monkeypatch.delenv("CLAUDE_BINARY", raising=False)
    monkeypatch.setattr(claude_env.shutil, "which",
                        lambda n: "/usr/bin/claude" if n == "claude" else None)
    assert claude_env.find_claude_binary() == "/usr/bin/claude"


def test_find_binary_none(monkeypatch):
    monkeypatch.delenv("CLAUDE_BINARY", raising=False)
    monkeypatch.setattr(claude_env.shutil, "which", lambda n: None)
    monkeypatch.setattr(claude_env.Path, "exists", lambda self: False)
    assert claude_env.find_claude_binary() is None
