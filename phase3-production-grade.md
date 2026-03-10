# Phase 3: Production-Grade Claude Code

Phase 1 was about **building a product**.
Phase 2 was about **mastering the tool**.
Phase 3 is about **making it reliable** — agents that don't break under pressure, debugging that works in real production, and engineering decisions that save time and money.

---

## What "Production-Grade" Means Here

A Phase 2 engineer builds agents that work on the happy path.
A Phase 3 engineer builds agents that:
- Handle failures gracefully
- Don't degrade in long sessions
- Cost the right amount to run
- Chain together without manual intervention
- Can diagnose and fix live production issues

---

## Chapter 1: Context Window Management

### The Problem
Claude's context window is finite. In a long session:
- Early tool results get compressed (summarized)
- Claude starts "forgetting" details
- Agents make mistakes they wouldn't make in a fresh session

### The Signs of a Polluted Context
- Agent repeats a step it already did
- Agent contradicts an earlier decision
- Agent asks for information it already has
- Output quality degrades late in a long task

### The Pattern
1. **Recognize the signal** — if an agent is making unexpected mistakes late in a long task, suspect context pollution first
2. **Start fresh** — new session, focused prompt
3. **Use MEMORY.md as the bridge** — write the current state to memory before ending the session, read it at the start of the next
4. **Surgical reads** — use Grep to find exact lines before reading whole files. Don't load what you don't need.
5. **Subagents for isolation** — spawn a subagent for tasks that would pollute your main context (large file analysis, long searches)

### Practical Rules
- Never read large files unless you need them
- Start a new session for unrelated work
- If an agent is wrong late in a session → restart before debugging the prompt
- Write state to MEMORY.md before ending any session with work in progress

---

## Chapter 2: Model Selection

### The Model Tiers

| Model | Best for | Cost |
|-------|----------|------|
| `claude-haiku-4-5` | Simple lookups, formatting, routine checks | Low |
| `claude-sonnet-4-6` | Most engineering work — coding, debugging, analysis | Medium |
| `claude-opus-4-6` | Hard architecture decisions, complex reasoning | High |

### The Rule
Use the **cheapest model that can do the job reliably**.

### How to Apply It in Agents
When spawning subagents via the Task tool, specify the model:

```python
Task(
    subagent_type="general-purpose",
    model="haiku",   # cheap — just fetching a file
    prompt="Find all files that import CalendarToken"
)

Task(
    subagent_type="general-purpose",
    model="opus",    # expensive — worth it for hard decisions
    prompt="Design a retry strategy for the Twilio message queue that handles rate limits, partial outages, and duplicate delivery"
)
```

### Real Example: Monitoring Agent
- **Haiku** — fetch Railway status, check queue depth, count Twilio failures (routine data fetching)
- **Sonnet** — analyze the data and decide if something is wrong (reasoning)
- **Opus** — only if you need deep diagnosis of a complex failure (rarely needed)

---

## Chapter 3: Agent Chaining

### The Problem
Today, the workflow is manual:
1. Programmer agent finishes a phase
2. You manually run `/after-merge`
3. You manually trigger QA agent
4. You manually promote the next phase

### The Chainer Pattern
A chainer agent polls for a condition and triggers the next agent when it's met:

```python
# chainer.py
import time
import subprocess

def wait_for_condition(check_fn, interval=30):
    while True:
        if check_fn():
            return
        time.sleep(interval)

def is_phase_complete():
    # Query Linear — are all tickets in current phase Done?
    ...

wait_for_condition(is_phase_complete)
subprocess.run(["claude", "-p", QA_AGENT_PROMPT, "--allowedTools", "Bash,Read"])
```

### When to Use Chaining
- After programmer agent finishes → auto-trigger QA agent
- After QA creates tickets → auto-promote next phase
- After monitoring detects an issue → auto-trigger diagnosis agent

### Key Rule
Chaining is powerful but fragile. Always define what happens when the condition is never met — add a timeout and a fallback alert.

---

## Chapter 4: Live Production Debugging

### The Pattern
When something breaks in production:

```
1. Get the error — from Railway logs, Sentry, or a user report
2. Describe the symptom to Claude (not "fix this", but "users are getting X when they do Y")
3. Claude traces the data path: logs → code → config → root cause
4. Agree on hypothesis before touching any code
5. Fix → redeploy → verify
```

### Tools for Production Debugging
- **Railway MCP** — fetch live logs without leaving Claude Code
- **`git log -S "symbol"`** — find when a function/variable was added or removed
- **Grep + Read** — trace the data path through code
- **Bash** — run Django shell commands to test hypotheses live

### The Golden Rule
**Never fix before you understand the root cause.**

Fixing the symptom → bug returns.
Fixing the root cause → actually solved.

### Real Example from Phase 2
Symptom: `WEBHOOK_BASE_URL is not configured`
Naive fix: hardcode the URL
Real fix: Django settings never read the env var from Railway

The difference: tracing the full data path (env var → settings → code) instead of jumping to a fix.

---

## Chapter 5: Prompt Hardening

### The Problem
An agent prompt that works on the happy path will fail in production when:
- An API is down
- A file doesn't exist
- A tool times out
- Data is in an unexpected format

### The Hardening Process
1. **Run the agent on the happy path** — verify it works
2. **Identify all external dependencies** — every API call, file read, tool invocation
3. **Break each one intentionally** — what happens when Railway is down? When Twilio returns 500?
4. **Fix the prompt** — add explicit error paths for each failure mode
5. **Repeat** until every failure produces a graceful, informative response

### Error Path Template
For every check in your agent:
```
If [check] fails:
- What does failure look like? (timeout, non-200, empty response, exception)
- What should the agent do? (mark as failed, skip, alert, stop)
- What should it report? (specific error message, not generic "something went wrong")
```

### Signs of a Hardened Prompt
- Every external call has a failure case defined
- The agent never silently succeeds when something is wrong
- Stop rules are explicit — the agent knows exactly when to stop
- Error messages are specific enough to act on

---

## Chapter 9: Phase 3 Exercises

### Exercise 1: Context Window Management
**Goal:** Deliberately run a long session until you see degradation. Practice the recovery pattern.
**Done when:** You can identify context pollution from agent behavior and recover without losing work.

### Exercise 2: Model Selection
**Goal:** Rewrite the monitoring agent to use Haiku for data fetching and Sonnet for the decision. Compare output quality and cost.
**Done when:** You can justify the model choice for each step of an agent.

### Exercise 3: Agent Chaining
**Goal:** After the programmer agent finishes a phase, automatically trigger the QA agent without manual intervention.
**Done when:** A full phase (implement → QA → promote) runs end-to-end without you touching it.

### Exercise 4: Live Production Debug
**Goal:** Next time something breaks on Railway, diagnose and fix it entirely inside Claude Code. No browser, no copy-pasting.
**Done when:** You fix a production bug faster with Claude Code than you would have manually.

### Exercise 5: Prompt Hardening
**Goal:** Take the monitoring agent and break it intentionally — bad Railway response, Celery timeout, Twilio API down. Fix the prompt until it handles every failure gracefully.
**Done when:** The monitoring agent produces a useful, specific alert for every failure mode, and never silently fails.

---

## The Phase 3 Checklist

You're production-grade when:

- [ ] You can identify context pollution from agent behavior and recover cleanly
- [ ] You pick models deliberately for every subagent based on task complexity
- [ ] You have at least one chained agent pipeline running without manual intervention
- [ ] You've diagnosed and fixed a live production bug entirely inside Claude Code
- [ ] Your agent prompts have explicit error paths for every external dependency
- [ ] Your agents never silently fail — every error produces a specific, actionable message
