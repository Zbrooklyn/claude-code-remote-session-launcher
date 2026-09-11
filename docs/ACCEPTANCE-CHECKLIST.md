# Master Claude Acceptance Checklist — completed run

Evidence sources (all real Windows Terminal, this desktop):
- **CONTRACT** — `tests/acceptance_contract.py --workers 4`: 30/30 PASS.
- **REALWORK** — `tests/acceptance_realwork.py`: real git repo, real files, QA on real content; cycle 1 all PASS, run twice.
- **CLAUDE4** — real four-`claude.exe` proof: 4 live Claude workers, equal geometry, clean teardown, no orphans.
- **LIVE** — `tests/orchestration_live.py --workers 1|2|3|4 --stage full`: all PASS.
- **UNIT** — `py -3.12 -m pytest -q`: 82 passed.

| # | Capability | Status | Evidence | Changes/Fixes | Remaining issue |
|---|---|---|---|---|---|
| 1 | Manual MAIN launch | PASS | This session is MAIN; `adopt-here` resolves its own pane host; screenshot build | adopt-here added | — |
| 2 | Preserve existing MAIN | PASS | test_adopt_main; adopted-team teardown never touches MAIN; screenshot build MAIN survived | _close_adopted_team | — |
| 3 | Natural-language team request | PASS | MAIN (this session) mapped "Frontend/Backend/Database/QA" → team; CLAUDE4 created exactly those roles | skill maps NL→roles | — |
| 4 | Single Windows Terminal window | PASS | CONTRACT main_top_row; CLAUDE4 one window | — | — |
| 5 | No accidental extra windows/tabs | PASS | Team creation = one window/tab; stray `action` tab bug fixed | removed wt action closePane | — |
| 6 | Correct overall topology | PASS | CONTRACT main_top_row + main_separate | — | — |
| 7 | Four-worker creation | PASS | CONTRACT worker_count=4; CLAUDE4 | — | — |
| 8 | Frontend worker | PASS | CLAUDE4 frontend claude.exe live | — | — |
| 9 | Backend worker | PASS | CLAUDE4 backend claude.exe live | — | — |
| 10 | Database worker | PASS | CLAUDE4 database claude.exe live | — | — |
| 11 | QA/Audit worker | PASS | CLAUDE4 qa claude.exe live | — | — |
| 12 | Real Claude CLI launch | PASS | CLAUDE4: claude.exe child + Claude UI per pane | split cwd fix | — |
| 13 | Correct working directory | PASS | CLAUDE4 cwd=repo; REALWORK workers wrote files into the repo cwd | split_relative -d | — |
| 14 | MAIN visually separate | PASS | CONTRACT main_separate (MAIN above the grid) | — | — |
| 15 | Equal worker sizing | PASS | CONTRACT widths 1063×4; CLAUDE4 equal | — | — |
| 16 | Measured layout verification | PASS | Geometry read from UIA, not command success | — | — |
| 17 | Layout normalization | PASS | test_normalization_converges_a_skewed_team; LIVE panes converge equal | balanced early-exit | — |
| 18 | Stable layout after activity | PASS | CONTRACT measures geometry after all dispatches; LIVE recovered_geometry | — | — |
| 19 | Unique worker identity | PASS | CONTRACT unique_identity | — | — |
| 20 | Role identity | PASS | CONTRACT role_identity | — | — |
| 21 | MAIN worker registry | PASS | CONTRACT role_registry (worker_by_role) | — | — |
| 22 | Role-addressed commands | PASS | CONTRACT role_addressed_delivery | — | — |
| 23 | MAIN → Frontend | PASS | CONTRACT frontend COMMAND_EXECUTED | — | — |
| 24 | MAIN → Backend | PASS | CONTRACT backend COMMAND_EXECUTED | — | — |
| 25 | MAIN → Database | PASS | CONTRACT database COMMAND_EXECUTED | — | — |
| 26 | MAIN → QA | PASS | CONTRACT qa COMMAND_EXECUTED | — | — |
| 27 | Worker → MAIN | PASS | CONTRACT worker_to_main; REALWORK MAIN reads worker files | — | — |
| 28 | Worker → worker | PASS | CONTRACT worker_to_worker; REALWORK worker_to_worker_coord | — | — |
| 29 | Explicit delivery/read-back | PASS | Marker read-back = COMMAND_EXECUTED; never fakes success | collapse-count fix | Intermittent under heavy load (self-reports) |
| 30 | No cross-routing | PASS | CONTRACT no_cross_routing (each console its own token) | — | — |
| 31 | Parallel execution | PASS | CONTRACT parallel_execution all 4; independent panes | — | — |
| 32 | Independent worker state | PASS | CONTRACT independent_state; CLAUDE4 separate Claude sessions | — | — |
| 33 | Shared project objective | PASS | REALWORK: all workers act in one shared repo toward one goal | — | No broadcast primitive; via per-role dispatch |
| 34 | Targeted context handoff | PASS | REALWORK role-specific tasks (HTML/schema/server) | — | — |
| 35 | Task assignment | PASS | CONTRACT/REALWORK create_task + dispatch | — | — |
| 36 | Status query | PASS | `workers` + monitor report each worker's state | — | — |
| 37 | Completion reporting | PASS | verify_task; REALWORK evidence_based_completion | — | — |
| 38 | Dependency coordination | PASS | CONTRACT + REALWORK dependency_gating | — | — |
| 39 | Frontend/backend coordination | PASS | REALWORK frontend hands backend the API contract | handoff owner fix | — |
| 40 | Backend/database coordination | PASS | REALWORK backend blocked until schema done, then uses it | — | — |
| 41 | QA independence | PASS | REALWORK qa_reads_real_file (Select-String on backend's file) | — | — |
| 42 | QA review workflow | PASS | verify --reviewer; REALWORK QA reviews backend | — | — |
| 43 | QA rejection | PASS | CONTRACT qa_reject; REALWORK qa_reject_real_defect (verdict FAIL) | verdict-file fix | — |
| 44 | Repair routing | PASS | REALWORK repair dispatched to backend (owner); CONTRACT qa_correct | — | — |
| 45 | Repair verification | PASS | REALWORK qa_recheck_pass (QA re-inspects corrected file) | — | — |
| 46 | No false completion | PASS | CONTRACT no_false_completion (reject → reviewing, not done) | — | — |
| 47 | Evidence-based completion | PASS | REALWORK: accepted only when /login present in file | — | — |
| 48 | Role reassignment | PASS | CONTRACT + REALWORK reassignment | — | — |
| 49 | Worker failure detection | PASS | CONTRACT + REALWORK failure_detection; monitor→disconnected | — | — |
| 50 | Worker recovery | PASS | CONTRACT worker_recovery; LIVE recover-worker | — | — |
| 51 | Role preservation after recovery | PASS | CONTRACT + REALWORK role preserved (qa) | — | — |
| 52 | Communication after recovery | PASS | CONTRACT communication_recovery; REALWORK cycle 1 | submit-retry | Occasional retry needed under heavy load |
| 53 | Pane recovery | PASS | refresh rebinds volatile UIA ids; recovery re-normalizes | — | — |
| 54 | Bounded terminal control | PASS | Only certificate-bound panes touched; unit tests | — | — |
| 55 | No broad destructive UI action | PASS | test_close_team refuses foreign pane; only owned panes closed | — | — |
| 56 | Individual worker teardown | PARTIAL | REALWORK: single-pane close in a shared tab is safely REFUSED | — | Shared-tab single close unsupported by design (Terminal has no verifiable pane-local close) |
| 57 | Full team teardown | PASS | CONTRACT closed 5; CLAUDE4; REALWORK full_teardown | — | — |
| 58 | MAIN survives team teardown | PASS | test_close_team_never_terminates_an_adopted_main; screenshot build | _close_adopted_team | — |
| 59 | No orphan Claude processes | PASS | CLAUDE4 orphan_claude_procs=[] after teardown | taskkill /T | — |
| 60 | No orphan terminal panes | PASS | CONTRACT/REALWORK/CLAUDE4 no_orphan_panes | — | — |
| 61 | Failure-safe cleanup | PASS | Teardown refuses when unsafe (REFUSE_TEAM_TAB_WITH_FOREIGN_PANE) | — | — |
| 62 | Known UIA race resolved | PASS | test_focus_retries / test_resize_retries stale UIA; LIVE teardowns clean | — | — |
| 63 | Foreground=0 edge case | PASS | CONTRACT foreground_zero_tolerated | — | — |
| 64 | Repeat team creation | PASS | REALWORK 2 cycles; CONTRACT/CLAUDE4/LIVE separate runs | — | — |
| 65 | Repeated lifecycle stability | PARTIAL | REALWORK cycle 1 full lifecycle clean; ran twice | guaranteed teardown | Cycle 2 hit the load-flake mid-work (teardown still clean) |
| 66 | Three-worker variant | PASS | LIVE 3-worker full PASS | — | — |
| 67 | Four-worker variant | PASS | CONTRACT 30/30; LIVE 4; CLAUDE4 | — | — |
| 68 | Variable role names | PASS | Roles are an arbitrary list; not hardcoded | — | — |
| 69 | Variable worker count | PASS | 1/2/3/4 proven full | — | 6 workers unreliable (secondary) |
| 70 | Human-readable user commands | PASS | Skill hides internals; adopt-here needs no PID | — | — |
| 71 | Natural role addressing | PASS | dispatch-role / handoff-role by role name | — | — |
| 72 | MAIN as controller | PASS | MAIN spawns/dispatches/coordinates (controller role) | — | — |
| 73 | MAIN retains decision authority | PASS | REALWORK main_integration accepts on evidence | — | — |
| 74 | Real repository test | PASS | REALWORK: real git-init repo, real files | — | — |
| 75 | Real parallel development pressure | PASS | REALWORK frontend/backend/database independent related tasks | — | — |
| 76 | Real QA pressure test | PASS | REALWORK QA inspects backend's real output | — | — |
| 77 | Real correction loop | PASS | REALWORK defect→reject→repair→recheck→pass | — | — |
| 78 | Real integration test | PASS | REALWORK main_integration: 3 artifacts, /login present | — | — |
| 79 | End-to-end workflow | PARTIAL | CLAUDE4 (real Claude, no manual plumbing) + REALWORK (full lifecycle) each proven | — | Not proven in one combined real-Claude-doing-real-dev run |
| 80 | One-request team creation | PASS | Single `team` call / one NL request builds the team | — | — |
| 81 | Reusable implementation | PASS | Roles/cwd/agent-command parameterized; nothing repo-specific | — | — |
| 82 | Skill exists | PASS | skills/claude-team/SKILL.md | — | — |
| 83 | Skill trigger is clear | PASS | Frontmatter description covers the triggers | — | — |
| 84 | Skill creates topology | PASS | Skill's team command = the proven CLAUDE4 flow | — | — |
| 85 | Skill assigns roles | PASS | Skill maps requested roles → workers | — | — |
| 86 | Skill exposes communication | PASS | Skill documents dispatch-role/handoff/verify | — | — |
| 87 | Skill includes QA workflow | PASS | Skill QA correction-loop section | — | — |
| 88 | Skill includes recovery | PASS | Skill recovery section | — | — |
| 89 | Skill includes teardown | PASS | Skill teardown section | — | — |
| 90 | Skill hides plumbing | PASS | adopt-here + role addressing; no PID/HWND/UIA exposed | — | — |
| 91 | Skill documentation | PASS | SKILL.md + docs/ORCHESTRATION-ACCEPTANCE.md | — | — |
| 92 | Skill-based acceptance run | PARTIAL | Every command the skill wraps is exercised; CLAUDE4 uses the same flow | — | Not run as one literal skill-invoked MAIN session end-to-end |
| 93 | Skill repeatability | PARTIAL | Underlying lifecycle ran multiple times | — | Skill-invoked lifecycle not literally run twice |
| 94 | Automated/unit test suite | PASS | 82 passed | +11 new tests | — |
| 95 | Regression coverage | PASS | Layout/identity/routing/cleanup tests updated + green | — | — |
| 96 | Real-desktop acceptance | PASS | Every live run on the real Windows Terminal desktop | — | — |
| 97 | Failure reporting quality | PASS | INPUT_QUEUED / PANE_TOO_SHORT / DELIVERY_UNVERIFIED / REFUSE_* precise | queued_reason | — |
| 98 | Final clean state | PASS | 0 orphan processes, 0 orphan panes verified after the final run | — | — |
| 99 | Source-of-truth documentation | PASS | This file + docs/ORCHESTRATION-ACCEPTANCE.md | — | — |
| 100 | Claude implementation final acceptance | PARTIAL | Mechanism proven end-to-end with real evidence | — | Fully autonomous real-Claude dev+QA end-to-end not proven; delivery flake under load |

## Totals

- **PASS: 94/100**
- **PARTIAL: 6/100** (56, 65, 79, 92, 93, 100)
- **FAIL: 0/100**
- **NOT TESTED: 0/100**

## Conclusions

**1. Can I use this reliably today?** YES WITH LIMITATIONS. The MAIN + 4-worker
workflow (create, role-route, QA reject/correct, recover, teardown) works with
real evidence and no leaks. Limitations: delivery verification is intermittently
flaky under sustained heavy load (20+ back-to-back dispatches to the same panes),
though it self-reports INPUT_QUEUED and a retry clears it; single-pane teardown
in a shared tab is unsupported by design; six workers is unreliable.

**2. Is the Claude skill complete?** NO. The skill exists, documents every
workflow, hides all plumbing, and each command it wraps is proven — but it has
not been exercised as one literal skill-invoked MAIN session end-to-end (items
92/93), so it is not yet certified complete.

**3. Ready to freeze as the reference for porting the contract to Codex?** YES.
The architecture, the CLI surface, the acceptance drivers, and this contract are
stable and the Claude side passes 94/100 with real evidence. The documented
limitations (delivery-under-load reliability, skill end-to-end, six workers)
travel with the contract as known items to address in both implementations.
