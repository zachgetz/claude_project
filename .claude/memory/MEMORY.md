# Project Memory

## Phase 2: Engineer Mastery Progress

Reference file: `phase2-engineer-mastery.md` in both `claude_project` and `TzachClaude` roots.

Teaching approach: user does the work, I guide. No giving answers in autocomplete/inline hints.

### Exercise 1: Railway MCP Server — COMPLETE
- Built `mcp_railway.py` in `/Users/tzachgetz/Projects/TzachClaude/mcp_servers/`
- 3 tools: `get_recent_logs(service, lines)`, `get_env_vars(service)` (names only, not values), `redeploy_service(service)`
- Uses `RAILWAY_BIN = "/Users/tzachgetz/.nvm/versions/node/v18.20.8/bin/railway"` (full path needed — nvm not on Claude's PATH)
- Registered in `/Users/tzachgetz/Projects/TzachClaude/.mcp.json` as `"railway"`
- Also moved `railway_status.py` from `agents/mcp_servers/` to `mcp_servers/` (restructured for clarity)
- MCP tools only available when Claude Code started from `TzachClaude` directory

### Exercise 2: Hook-Based Test Runner — DONE BUT USER UNHAPPY
- Created `/Users/tzachgetz/Projects/claude_project/.claude/settings.json`
- Hook fires on `PostToolUse` for `Edit` and `Write` tools
- Command: `cd /Users/tzachgetz/Projects/claude_project && /Users/tzachgetz/.pyenv/versions/3.11.1/bin/python manage.py test apps.standup.tests`
- Hook IS working — confirmed via `/tmp/hook_debug.txt`
- Issue: feedback is invisible. Only signal is `PostToolUse:Edit hook error` (non-zero exit) or silence (pass)
- User finds this unsatisfying — can't tell if it's working without tailing a log file
- TODO: improve hook to pipe output to Claude's context so I can self-correct visibly
- Pre-existing test failures: 2 ImportErrors in `test_tasks.py` and `test_twilio_status_callback.py` — `send_morning_checkin` not importable from `apps.standup.tasks`

### Exercise 3: Monitoring Agent — IN PROGRESS
- Agent prompt: `claude_project/agents/monitoring-agent.md`
- Celery task: `apps/bot/tasks.py` → `run_monitoring_agent()`
- Scheduled at 6am UTC (8am Israel) in `standup_bot/settings/base.py`
- Checks: Railway health (HTTP ping), Celery queue depth, Twilio failure rate
- Sends WhatsApp alert to owner only if something is broken

## Agents — Concepts Learned

### What an agent is
A prompt + tools + a trigger, running autonomously. Claude drives — you don't confirm each step.

### Skills vs Agents vs Hooks
- **Skill** — you trigger it, runs once, you're in control
- **Agent** — drives itself through multiple steps/decisions, you're not in the loop
- **Hook** — fires automatically on a tool event (PostToolUse, PreToolUse)
- They compose: Hook → launches Agent → agent runs its loop

### Hook types (Claude Code)
- `command` — runs shell command, only exit code reaches Claude, output invisible
- `prompt` — static instruction to Claude for yes/no decision, no shell execution
- `agent` — spawns subagent with tools (NOT working in Claude Code v2.1.68)
- `http` — POSTs JSON to a URL
- Field names: `command` type uses `"command"` key, `prompt`/`agent` types use `"prompt"` key

### How to build any agent
1. Write `agents/<name>.md` — role, loop, decisions, tools, error paths, stop rules
2. Choose trigger: manual CLI / skill / hook / Celery schedule
3. Change relevant files:
   - Manual: just the `.md`
   - Skill: `.claude/skills/<name>/SKILL.md`
   - Schedule: `apps/<app>/tasks.py` + `standup_bot/settings/base.py`
   - Hook: `.claude/settings.json`
4. Call it: `claude -p "$(cat agents/my-agent.md)" --allowedTools Bash,WebFetch,Read`

### Agent prompt structure
- ROLE — mental model of the agent
- LOOP/CHECKS — exact steps in order
- DECISION LOGIC — if X then Y
- TOOLS — which tools and when
- ERROR PATHS — what to do when something fails
- STOP RULES — explicit exit conditions
### Exercise 4: Code Review Agent — COMPLETE
- Agent prompt: `claude_project/agents/code-review-agent.md`
- Skill: `TzachClaude/.claude/skills/review-pr/SKILL.md`
- Trigger: `/review-pr 123` (manual skill, PR number as input)
- Checks: test coverage, run tests, security scan, best practices, Jira acceptance criteria
- Verdict: APPROVED or BLOCKED printed to terminal
- Tools: Bash, GitHub MCP, Jira MCP
### Exercise 5: Master the Debugger Pattern — COMPLETE
- Debugged `send_morning_checkin` ImportError in 2 test files
- Root cause: function was intentionally deleted (commit 8b0d101) but tests weren't cleaned up
- Fixed: removed `SendMorningCheckinTests` class from `test_tasks.py` + orphaned test + imports from both files
- All 144 tests pass
- Key tool used: `git log -S "function_name" --oneline` (pickaxe search) to trace when a symbol was added/removed

## Phase 3: Current State
- Exercise 1: Context Window Management — COMPLETE
- Loaded all test files (~18 files) to stress context, then tested recall — no pollution detected
- Key lesson: pollution is a risk, not guaranteed. Know the signs (repeating steps, contradictions, wrong details). Recovery = fresh session + MEMORY.md bridge.

- Exercise 2: Model Selection — COMPLETE
- Three tiers: Haiku (cheap, simple), Sonnet (most engineering), Opus (hard reasoning/architecture)
- Rule: cheapest model that can do the job reliably
- Split monitoring agent: collector (Haiku) fetches data → outputs JSON → decision (Sonnet) reasons on it
- Model selected in code via `--model` flag, not in the prompt file
- Handoff: collector stdout injected into decision prompt via string concatenation

- Exercise 3: Agent Chaining — COMPLETE
- Pattern: Agent A finishes → Agent B starts automatically, no human in the loop
- Key design: the trigger owner is the agent with the full picture (poller), not the one doing the work
- Added Phase Chaining logic to `.claude/agents/pm-agent.md`
- PM agent polls Linear: if no tickets in Todo/In Progress/In Review → promote next phase → trigger programmer agent
- Always need: timeout + fallback alert, or chains get stuck forever
- Important lesson: full automation is dangerous — keep humans at decision gates (merges, deploys, irreversible actions). Automate the boring, checkpoint the risky.

- Exercise 4: Live Production Debug — COMPLETE (pattern learned, no code)
- Pattern: symptom first → trace data path → hypothesis before touching code → one change at a time → verify fix
- Tools: Railway MCP for live logs, git log -S for symbol history, Bash for Django shell hypotheses

- Exercise 5: Prompt Hardening — COMPLETE
- Hardened `agents/monitoring-collector.md`: specific error paths per failure mode, added `unknown` status, explicit JSON output format, never exit silently
- Key principle: silent failure is worse than no monitoring at all

## Self-Healing Chain (bonus — built during Ex5)
Full autonomous monitoring pipeline:
1. `monitoring-collector.md` (Haiku) — fetches health data, outputs JSON
2. `monitoring-decision.md` (Sonnet) — reasons on JSON, if failures → triggers diagnosis agent
3. `monitoring-diagnosis.md` (Sonnet) — investigates logs, determines root cause, opens Linear ticket with `[Auto]` prefix, assesses complexity
4. `health-bug-fixer.md` (Sonnet or Opus based on complexity) — fixes exactly one ticket, merges, marks Done

All agent files live in `claude_project/agents/`.

Key decisions:
- `health-bug-fixer.md` is separate from `programmer.md` — focused, can't accidentally pick up manual work
- Complexity drives model: simple → Sonnet, complex → Opus
- Ticket ID passed explicitly to fixer — not "take all Todo tickets"
- Human still approves merges (not fully automated) — auto-implement but human at the gate

## Phase 3 Summary — COMPLETE
All 5 exercises done. Phase 3 checklist largely covered.

## Phase 2 Summary — Saved
Full summary written in session 2026-03-05. All 5 exercises complete.
Remaining gaps:
- Hook agent type broken (v2.1.68) — revisit when fixed
- Monitoring agent not tested end-to-end
- No Phase 3 defined yet

## Project Structure
- `claude_project` — Single source of truth. Django app, Railway deployment, agents, skills, MCP servers, hooks. TzachClaude deleted 2026-03-06.

- `.mcp.json` lives in `claude_project` root
- MCP servers live in `claude_project/mcp_servers/`

## Key Facts
- Railway project: `intelligent-growth`, service: `claude_project`
- Railway CLI: `/Users/tzachgetz/.nvm/versions/node/v18.20.8/bin/railway`
- Python: `/Users/tzachgetz/.pyenv/versions/3.11.1/bin/python`
- Run tests: `python manage.py test apps.standup.tests` from `claude_project`

## Project Consolidation (2026-03-06)
- TzachClaude deleted — everything moved to claude_project
- All agents: `.claude/agents/` (programmer, pm-agent, qa-agent, health-bug-fixer, etc.)
- All skills: `.claude/skills/` (after-merge, assign-to-project, next-phase, review-pr)
- MCP servers: `mcp_servers/` (mcp_railway.py, railway_status.py)
- Agent scripts: `agents/` (notify_phase_complete.py, ask_user_email.py, pipeline.py, etc.)
- settings.json merged — includes mcp__linear__*, mcp__github__*, Bash permissions + all hooks
- Linear API key replaced with ${LINEAR_API_KEY} placeholder throughout
- .gitignore added — ignores __pycache__, .env, db.sqlite3, .DS_Store, .idea/, venv/
- All pushed to GitHub on branch feat/main-menu-greeting
- .env in git history was all fake/test values — no rotation needed

## Skills & $ARGUMENTS (2026-03-06)
- Skill files live at `.claude/skills/<command-name>/SKILL.md`
- Directory name = command name (e.g. `after-merge/` → `/after-merge`)
- `user-invocable: true` in frontmatter makes it a slash command
- `$ARGUMENTS` = everything typed after the command name, as one string
- Claude parses multiple args from $ARGUMENTS based on instructions in the skill
- Updated `after-merge/SKILL.md` to use $ARGUMENTS explicitly

## Tomorrow
- Build a new skill with $ARGUMENTS from scratch
- SDK section (programmatic Claude Code calls vs subprocess)
