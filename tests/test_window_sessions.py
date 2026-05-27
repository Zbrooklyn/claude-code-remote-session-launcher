"""Tests for window_sessions: catalog, fuzzy match, and process-verified liveness.

All filesystem state lives in the isolated $CLAUDE_HOME (claude_home fixture).
Liveness is monkeypatched at running_claude_pids so we never touch the real
process table.
"""
import time

import window_sessions as ws
from _helpers import write_transcript, write_session, write_log

NOW = time.time()


# ---------- list_resumable ----------

def test_list_resumable_reads_cwd_perm_prompt(claude_home):
    write_transcript(claude_home, "C--work-foo", "abc12345-1111-2222-3333-444455556666",
                     cwd="C:/work/foo", first_prompt="Build the thing",
                     perm="bypassPermissions")
    cands = ws.list_resumable(max_age_days=14)
    assert len(cands) == 1
    c = cands[0]
    assert c.cwd == "C:/work/foo"
    assert c.permission_mode == "bypassPermissions"
    assert c.first_prompt == "Build the thing"


def test_list_resumable_age_cutoff(claude_home):
    write_transcript(claude_home, "C--w", "old-sid", cwd="C:/w", age_days=30)
    assert ws.list_resumable(max_age_days=14) == []
    assert len(ws.list_resumable(max_age_days=60)) == 1


def test_list_resumable_newest_first(claude_home):
    write_transcript(claude_home, "C--w", "older", cwd="C:/w", age_days=5)
    write_transcript(claude_home, "C--w", "newer", cwd="C:/w", age_days=1)
    cands = ws.list_resumable()
    assert [c.session_id for c in cands] == ["newer", "older"]


def test_list_resumable_labels_from_log(claude_home):
    write_transcript(claude_home, "C--w", "sid-aaaa1234", cwd="C:/w")
    write_log(claude_home, [{"session_id": "sid-aaaa1234", "label": "myproj"}])
    cands = ws.list_resumable()
    assert cands[0].labels == ["myproj"]


def test_list_resumable_empty_when_no_projects(claude_home):
    assert ws.list_resumable() == []


# ---------- find_by_name ----------

def test_find_by_name_sid_prefix():
    c = ws.Candidate(session_id="abcdef1234-xyz", transcript=None, cwd="", mtime=NOW)
    matches = ws.find_by_name("abcdef1234", [c])
    assert matches and matches[0][1] is c


def test_find_by_name_exact_label_beats_prompt():
    a = ws.Candidate("s1", None, "", NOW, labels=["telegram"])
    b = ws.Candidate("s2", None, "", NOW, first_prompt="set up telegram bot")
    matches = ws.find_by_name("telegram", [a, b])
    assert matches[0][1] is a


def test_find_by_name_no_match_is_empty():
    c = ws.Candidate("s1", None, "", NOW, labels=["alpha"])
    assert ws.find_by_name("zzzzz", [c]) == []


def test_is_ambiguous():
    a = ws.Candidate("s1", None, "", NOW)
    b = ws.Candidate("s2", None, "", NOW)
    assert ws.is_ambiguous([(10.0, a), (9.5, b)])
    assert not ws.is_ambiguous([(10.0, a), (2.0, b)])
    assert not ws.is_ambiguous([(10.0, a)])


# ---------- liveness (process-verified) ----------

def test_alive_only_when_process_running(claude_home, monkeypatch):
    write_session(claude_home, 4242, "live-sid")
    write_session(claude_home, 9999, "dead-sid")
    monkeypatch.setattr(ws, "running_claude_pids", lambda: {4242})
    alive = ws.alive_session_ids()
    assert "live-sid" in alive
    assert "dead-sid" not in alive


def test_alive_pid_for_session(claude_home, monkeypatch):
    write_session(claude_home, 4242, "live-sid")
    write_session(claude_home, 9999, "dead-sid")
    monkeypatch.setattr(ws, "running_claude_pids", lambda: {4242})
    assert ws.alive_pid_for_session("live-sid") == 4242
    assert ws.alive_pid_for_session("dead-sid") is None
    assert ws.alive_pid_for_session("unknown-sid") is None


# ---------- transcript readers / slug ----------

def test_read_cwd_normalizes_backslashes(claude_home):
    p = write_transcript(claude_home, "C--w", "sid", cwd="C:\\\\work\\\\foo")
    # write_transcript stores the cwd verbatim; reader should normalize slashes
    got = ws.read_cwd(p)
    assert "\\" not in got


def test_slug():
    assert ws.slug("My Proj!") == "my-proj"
    assert ws.slug("---") == "session"
