# Phase 2: Becoming a Claude Code Master Engineer

Phase 1 was about **building a product** with Claude Code agents.
Phase 2 is about **mastering the tool itself** — understanding it deeply enough that you can engineer anything with it, debug it when it breaks, and bend it to your exact needs.

This is written for engineers. Not for PMs. The goal is fluency, not just usage.

---

## What "Mastery" Means Here

A junior user asks Claude to write code.
A master engineer uses Claude Code to **think, debug, architect, and automate** — the same way they'd use a terminal or an IDE.

Mastery means:
- You know exactly which tool Claude is calling and why
- You can diagnose why an agent failed and fix the prompt
- You can extend Claude Code with custom MCP servers
- You can automate your own workflow with hooks
- You understand the context window like memory management in systems programming
- You pick the right model for each task the way you pick O(n) vs O(log n)

---

## Chapter 1: How Claude Code Actually Works

Before mastering anything, understand the machine.

### The Tool Loop

Claude Code is a loop:
1. You send a message
2. Claude decides which tool(s) to call (Read, Bash, Grep, Edit, Task, etc.)
3. Tools execute and return results
4. Claude decides next action
5. Repeat until done

Every "thinking" step is an LLM call. Every tool call costs tokens. This matters for cost, speed, and reliability.

### The Context Window Is the Stack

Everything Claude knows in a session lives in the context window:
- Your messages
- Tool results
- File contents it has read
- Agent outputs

When the context fills up, old messages get compressed (summarized). **This means Claude can "forget" details from early in a long session.** Engineers treat this like RAM — be deliberate about what you load in.

**Practical rules:**
- Don't read large files unless you need them
- Start a new session for unrelated work
- Use `MEMORY.md` to persist facts across sessions (not the context)
- If an agent is making mistakes late in a long task, the context may be polluted — restart with a focused prompt

### The Difference Between Claude Code and the Claude API

Claude Code is a **stateful shell agent** running on your machine. It has:
- File system access (Read, Write, Edit, Glob)
- Shell execution (Bash)
- Network (WebFetch, WebSearch)
- Sub-agents (Task tool)
- MCP tools (GitHub, Linear, Slack, etc.)

The Claude API is stateless — you send a prompt, you get text back. Claude Code is what you get when you wrap an agent loop around that API with real tools attached.

---

## Chapter 2: Writing Agent Prompts Like an Engineer

In Phase 1, we wrote agents that work. In Phase 2, we write agents that are **reliable under pressure**.

### The Anatomy of a Production Agent Prompt

A weak prompt: "You are a programmer. Write code for each ticket."

A strong prompt has:

```
1. ROLE        — what this agent is, not just a title but its mental model
2. CONSTRAINTS — hard rules it cannot break (never touch main, always read before writing)
3. TOOLS       — which tools it has and when to use each one
4. LOOP        — the exact sequence of steps for its main task
5. ERROR PATHS — what to do when blocked, when tests fail, when an API is down
6. STOP RULES  — explicit conditions that cause it to stop and report back
```

### Example: Making the Programmer Agent More Reliable

Phase 1 programmer agent got confused when:
- There were merge conflicts it didn't expect
- A test failed that it didn't write
- It couldn't find a file it expected to exist

The fix is **explicit error paths**:

```markdown
## When Tests Fail
1. Read the failing test — understand what it expects
2. Read the implementation — understand what it does
3. Fix the implementation first (assume the test is correct)
4. If the test itself is wrong (tests a removed feature), check the ticket — if the ticket says to remove that feature, update the test
5. If you're still failing after 2 attempts → STOP. Email user with: failing test name, what you tried, what you need clarified

## When a File Doesn't Exist
Never create it blindly. First:
1. Use Glob to search for similar files (maybe it moved)
2. Check git log for the file (maybe it was deleted intentionally)
3. If you genuinely can't find it and the ticket depends on it → STOP and report
```

### Precision > Length

Agent prompts that are too long get ignored in spirit — Claude will follow the first few rules carefully and skim the rest. Keep prompts focused. Every sentence should earn its place.

**Test your prompt:** run the agent on a simple case and watch the tool calls. If Claude is doing something you didn't intend, the prompt is ambiguous.

---

## Chapter 3: MCP Servers — Extending Claude Code

MCP (Model Context Protocol) is how you give Claude Code new tools. In Phase 1 we used GitHub and Linear MCPs. In Phase 2 we **build our own**.

### What an MCP Server Is

An MCP server is a process (any language) that exposes tools over a protocol. Claude Code spawns it, discovers its tools, and can call them like any other tool.

```
Claude Code → MCP protocol → your server → your API/DB/service
```

### When to Build a Custom MCP

Build one when you find yourself writing the same Bash commands over and over. Signs you need a custom MCP:
- Every debugging session starts with the same 5 Railway CLI commands
- You keep asking Claude to query your DB with the same patterns
- You have an internal API that Claude needs to call frequently

### A Real Example: Railway MCP for This Project

Today we debugged a Railway deployment by copy-pasting logs from the browser. A Railway MCP would let Claude:
- Fetch live Railway logs directly in the conversation
- Read env vars (to catch the `WEBHOOK_BASE_URL` bug immediately)
- Trigger redeploys
- Query service status

Instead of: "here are the logs, can you read them"
You get: Claude calls `railway_get_logs(service='claude_project', lines=50)` on its own

### Building a Minimal MCP Server (Python)

```python
# mcp_railway.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
import subprocess

server = Server("railway-tools")

@server.tool()
def get_recent_logs(service: str, lines: int = 50) -> str:
    """Get recent Railway logs for a service."""
    result = subprocess.run(
        ["railway", "logs", "--service", service, "-n", str(lines)],
        capture_output=True, text=True
    )
    return result.stdout or result.stderr

@server.tool()
def get_env_vars(service: str) -> str:
    """List env var names (not values) for a Railway service."""
    result = subprocess.run(
        ["railway", "variables", "--service", service],
        capture_output=True, text=True
    )
    return result.stdout

if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(server))
```

Register it in `.mcp.json`:
```json
{
  "mcpServers": {
    "railway": {
      "command": "python",
      "args": ["mcp_railway.py"]
    }
  }
}
```

Now Claude can check Railway logs without you having to open a browser.

---

## Chapter 4: Hooks — Automating Your Workflow

Hooks are shell commands that run automatically in response to Claude Code events. They are the engineering equivalent of git hooks, but for your AI agent.

### What Hooks Can Do

```
PostToolUse  → runs after every tool call
PreToolUse   → runs before a tool call (can block it)
Notification → runs when Claude wants your attention
```

### Real Engineering Uses

**Automatically run tests after every file edit:**
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "command": "cd /path/to/project && python manage.py test --failfast -q 2>&1 | tail -5"
    }]
  }
}
```
Now every file Claude writes is instantly tested. Claude sees the output and self-corrects.

**Block dangerous commands:**
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "command": "echo '$CLAUDE_TOOL_INPUT' | grep -q 'DROP TABLE\\|rm -rf\\|git push --force' && echo 'BLOCKED: dangerous command' && exit 1 || exit 0"
    }]
  }
}
```

**Log every Bash command for auditing:**
```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Bash",
      "command": "echo \"$(date): $CLAUDE_TOOL_INPUT\" >> ~/.claude/audit.log"
    }]
  }
}
```

### The Engineering Mindset for Hooks

Hooks make Claude Code **opinionated**. You're encoding your engineering standards directly into the tool:
- "Always test after editing" is now automatic, not a reminder
- "Never drop tables" is enforced at the tool level, not just in the prompt
- "Log all shell commands" gives you an audit trail for free

---

## Chapter 5: Model Selection — Cost and Performance

Claude Code can run sub-agents on different models. This matters in two ways: **cost** and **quality**.

### The Model Tiers (as of 2026)

| Model | Best for | Relative cost |
|-------|----------|---------------|
| `claude-haiku-4-5` | Simple searches, lookups, formatting, routine tasks | Low |
| `claude-sonnet-4-6` | Most engineering work — coding, debugging, analysis | Medium |
| `claude-opus-4-6` | Complex architecture, hard bugs, nuanced reasoning | High |

### The Engineering Rule

Use the **cheapest model that can do the job reliably**.

- Fetching a file and summarizing it → Haiku
- Writing a Django view with tests → Sonnet
- Designing a caching architecture with tradeoffs → Opus

In practice for this project:
- Routine ticket implementation (CRUD, boilerplate) → Haiku or Sonnet
- Complex debugging sessions (like today's Railway + settings chain) → Sonnet or Opus
- Architecture decisions (how should we structure the notification pipeline?) → Opus

### How to Set Model in Task Calls

```python
Task(
    subagent_type="general-purpose",
    model="haiku",  # cheap for simple research
    prompt="Find all files that import CalendarToken"
)

Task(
    subagent_type="general-purpose",
    model="opus",   # expensive but worth it for hard problems
    prompt="Design a retry strategy for the Twilio message queue that handles rate limits, failures, and partial outages"
)
```

---

## Chapter 6: Debugging Claude Code Itself

When agents fail, most engineers blame the model. Masters blame the prompt first.

### The Debugging Hierarchy

When an agent does something wrong, ask in order:

1. **Was the context corrupted?**
   - Did it read the wrong file version?
   - Was there a stale result from an earlier tool call?
   - Is the session too long and early context was compressed?

2. **Was the prompt ambiguous?**
   - Could the instruction be interpreted two ways?
   - Did you specify WHAT but not HOW?
   - Did you handle the error case that just occurred?

3. **Was the tool result wrong?**
   - Did a GitHub API call return stale data?
   - Did a Bash command silently fail (exit code 0 but wrong output)?
   - Did an MCP tool time out and return empty?

4. **Is it a model limitation?**
   - Last resort. Usually it's one of the above.

### A Real Example from This Project

**Today's bug:** `WEBHOOK_BASE_URL is not configured` even though the env var was set in Railway.

Debugging chain:
1. Checked Railway env vars — looked correct ✓
2. Checked the error source — `sync.py` calls `getattr(settings, 'WEBHOOK_BASE_URL', None)`
3. Read `base.py` — `WEBHOOK_BASE_URL` is **never loaded** from env vars
4. Root cause: the env var existed in Railway but Django settings never read it

**The lesson:** when debugging, always trace the full data path. "The env var is set" and "the app can see it" are two different things. Read the code.

This is what makes a Claude Code master different from a user — they read the code that the agent is looking at, not just the error message.

---

## Chapter 7: Context as a First-Class Engineering Concern

Context management is the closest thing to memory management in Claude Code. Get it wrong and agents become unreliable.

### What Pollutes Context

- Reading large files you don't need
- Long bash outputs that aren't relevant
- Repeated tool failures that fill the window with noise
- Running multiple unrelated tasks in the same session

### Strategies

**Surgical reads:** Instead of reading an entire file, use Grep first to find the exact lines you need, then Read with offset/limit.

**Fresh sessions for fresh problems:** If you're debugging a Railway issue and then want to implement a new feature, start a new session. The Railway debugging context will only confuse the implementation.

**MEMORY.md as external state:** Anything that needs to survive across sessions goes in MEMORY.md. Don't rely on Claude remembering it from earlier in the conversation.

**Subagents for isolation:** When you use the Task tool to spawn a subagent, it gets a clean context. Use this deliberately — give the subagent only what it needs, nothing more.

---

## Chapter 8: The Engineering Workflow in Practice

This is the workflow we actually used to build this project, now formalized.

### For a New Feature

```
1. Write the spec (2-3 sentences of what it does and why)
2. PM Agent → breaks it into tickets (5-10 min)
3. Review tickets — push back on anything vague or too big
4. Programmer Agent → implements tickets sequentially
   - Watch the first ticket carefully (sets the pattern)
   - Let it run autonomously after that
5. QA Agent → reviews after the phase ships
6. You → review QA tickets, promote the important ones to next phase
```

### For a Bug

```
1. Reproduce it — understand exactly what triggers it
2. Read the relevant code before asking Claude anything
3. Form a hypothesis about the root cause
4. Ask Claude to verify your hypothesis (don't ask it to guess)
5. Fix → test → done
```

The mistake most engineers make: they paste the error into Claude and ask "what's wrong?" without reading the code first. Claude can generate plausible-sounding wrong answers. If you've already read the code, you can tell the difference.

### For a Deployment Issue

```
1. Check logs first — what is the actual error message?
2. Trace the data path (env var → settings → code → runtime)
3. Don't assume — verify each step
```

Today's example: "WEBHOOK_BASE_URL not reaching the app" had three possible causes — Railway not redeploying, wrong var name, var not loaded into settings. We verified each step and found it in settings.

---

## Chapter 9: What to Build in Phase 2

Concrete engineering exercises to build mastery, using this project as the base.

### Exercise 1: Build a Railway MCP Server
**Goal:** Claude can query live logs and env var names without browser copy-paste.
**Skills practiced:** MCP server development, tool design, subprocess handling.
**Done when:** Claude can independently diagnose a Railway deployment issue by calling MCP tools.

### Exercise 2: Add Hook-Based Test Runner
**Goal:** Every file Claude edits triggers the test suite automatically.
**Skills practiced:** Hooks, feedback loops, self-correcting agents.
**Done when:** The programmer agent catches its own test failures without you telling it.

### Exercise 3: Write a Monitoring Agent
**Goal:** An agent that runs on a schedule, checks Railway health + Celery queues + Twilio delivery rates, and sends you a WhatsApp summary if anything is wrong.
**Skills practiced:** Scheduled agents, multi-tool orchestration, alerting patterns.
**Done when:** You get a WhatsApp message when something is broken before you notice it yourself.

### Exercise 4: Build a Code Review Agent
**Goal:** Before any PR merges, an agent reads the diff and checks: are there tests? is there a security issue? does it match the ticket spec?
**Skills practiced:** GitHub MCP, code analysis, structured output.
**Done when:** The programmer agent and the reviewer agent disagree on something and you have to adjudicate — that's when you know both are working.

### Exercise 5: Master the Debugger Pattern
**Goal:** The next time something is broken in production, diagnose and fix it entirely through Claude Code — no browser, no manual SSH, no copy-pasting logs.
**Skills practiced:** Full-stack debugging, MCP tool chaining, log analysis.
**Done when:** You fix a production bug faster with Claude Code than you would have manually.

---

## The Master's Checklist

You're a Claude Code master engineer when:

- [ ] You have written at least one custom MCP server
- [ ] You use hooks to automate at least one repetitive check
- [ ] You can explain why an agent failed without running it again
- [ ] You pick models deliberately based on task complexity
- [ ] You treat `MEMORY.md` as a real engineering artifact — structured, up to date, useful
- [ ] You've debugged a production issue end-to-end without leaving Claude Code
- [ ] Your agent prompts have explicit error paths, not just happy paths
- [ ] You've built an agent that finds a bug you introduced — and you trust it

---

## The One Thing

If Phase 1 taught you to **use** Claude Code, Phase 2 teaches you to **own** it.

The difference: a user is surprised when Claude does something unexpected. A master sees exactly which tool call caused the unexpected behavior, knows why, and knows how to prevent it next time.

That's the goal.
