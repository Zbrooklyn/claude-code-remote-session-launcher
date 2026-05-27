"""Pytest config + fixtures.

Every test runs against an isolated $CLAUDE_HOME (a temp dir), so the suite
never reads or writes the real ~/.claude. The hooks resolve paths at call time
via claude_env.claude_home(), which honors $CLAUDE_HOME — that refactor is what
makes this isolation possible.
"""
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))


@pytest.fixture
def claude_home(tmp_path, monkeypatch):
    """An isolated ~/.claude in a temp dir, wired up via $CLAUDE_HOME."""
    home = tmp_path / "dotclaude"
    (home / "projects").mkdir(parents=True)
    (home / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def _clear_binary_cache():
    """find_claude_binary() is lru_cached; clear it around every test so env
    changes (CLAUDE_BINARY) and monkeypatches take effect deterministically."""
    import claude_env
    claude_env.find_claude_binary.cache_clear()
    yield
    claude_env.find_claude_binary.cache_clear()
