# How We Built This: AI Agents in Claude Code

This file explains how we used Claude Code to build a real product — a WhatsApp calendar bot — using a team of specialized AI agents working together.

---

## The Big Idea

Instead of asking Claude "write me an app", we split the work into **roles**, just like a real team:

| Role | What they do |
|------|--------------|
| **PM Agent** | Reads a spec, breaks it into small tickets in Linear |
| **Programmer Agent** | Picks up tickets, writes code, opens PRs, merges them |
| **QA Agent** | Reviews all merged code, finds bugs, creates bug tickets |
| **UX Agent** | Decides what the bot says and which emojis to use |
| **Translator Agent** | Translates English strings to natural Hebrew |

Each agent is just a markdown file with a clear role description. Claude Code reads it and acts accordingly.

---

## How a Feature Gets Built

1. **You describe a feature** → PM Agent creates 8–12 small Linear tickets
2. **Programmer Agent picks up the first Todo ticket** → reads existing code, creates a branch, pushes the code, opens a PR, merges it, marks the ticket Done
3. **Repeat** until all tickets in the phase are done
4. **QA Agent reviews** the merged code → creates bug tickets
5. **Next phase starts**

Every step is tracked in Linear. Every code change goes through a GitHub PR. No one touches `main` directly.

---

## The Agents

### Programmer Agent (`agents/prompts/programmer.md`)
The workhorse. Fully autonomous. For each ticket:
- Moves it to "In Progress" in Linear
- Reads the relevant files from GitHub (never writes blind)
- Creates a branch: `feat/TZA-5-short-slug`
- Pushes all files in one commit
- Opens a PR, reviews it against acceptance criteria
- Merges (squash) to `main`
- Marks the ticket Done
- Moves to the next ticket

**Key rule:** if blocked, it emails you and stops. It never guesses and keeps going.

### PM Agent (`agents/prompts/pm-agent.md`)
Reads your feature spec and breaks it into Linear tickets. Each ticket has: what to build, acceptance criteria, and tech notes. Tickets are small (1–2 hours each).

### QA Agent (`agents/prompts/qa-agent.md`)
After a phase ships, QA reads all merged code and checks for bugs, security issues, edge cases, and missing tests. Creates one Linear ticket per finding with severity: CRITICAL / HIGH / MEDIUM / LOW. Emails you a summary.

### UX Agent (`agents/prompts/ux-agent.md`)
Owns all user-facing text. Every emoji must be semantically related (no decoration). Writes Hebrew natively — warm, casual, like a message from a smart friend. The programmer asks UX before writing any string.

### Translator Agent (`agents/prompts/translator-agent.md`)
Translates English bot strings to natural Israeli Hebrew. Understands RTL rules and preserves emojis, placeholders (`{name}`), and Twilio formatting.

---

## The Skills (Slash Commands)

Skills are shortcuts you type in Claude Code. Each one lives in `.claude/skills/<name>/SKILL.md`.

### `/after-merge TZA-5`
After you merge a PR, run this. It:
1. Marks the ticket Done in Linear
2. Checks if the whole phase is complete
3. If yes → posts a project update, promotes next-phase tickets, launches the Programmer Agent automatically

### `/next-phase`
Manually promote the next phase from Backlog → Todo when you're ready to start it.

### `/assign-to-project TZA-5`
Assigns a ticket to a Linear project (useful when tickets are created outside the project).

---

## Background Agents

Some tasks are slow (the programmer implements multiple tickets sequentially). We run them in the background so they don't block you.

```
Task tool with run_in_background=True
```

For tickets with dependencies (TZA-95 needs TZA-94 to finish first), we launch a **chainer agent**: it polls Linear every 30 seconds, waits until the dependency is Done, then starts working on the next ticket.

---

## How Linear Is Used

- **Backlog** = not started yet (future phases)
- **Todo** = ready to work (current phase)
- **In Progress** = agent is working on it right now
- **In Review** = PR is open
- **Done** = merged and shipped

State transitions happen via GraphQL curl commands (not the MCP tool — it hangs).

---

## The Tech Stack

- **Django** — the app framework
- **Twilio WhatsApp** — bot messaging
- **Google Calendar API** — fetching events
- **Railway** — hosting (auto-deploys on push to `main`)
- **Celery + Redis** — morning digest scheduler
- **Linear** — ticket tracking
- **GitHub** — code and PRs
- **Claude Code** — the AI orchestrator running everything

---

## Key Lessons

1. **Small tickets win.** 1–2 hour tickets are easier for the agent to implement correctly than big ones.
2. **Read before you write.** The programmer agent always reads existing files before touching anything.
3. **One ticket = one branch = one PR.** Never mix tickets in a single PR.
4. **Agents need guardrails.** Tell the agent when to stop (blocked → email user). Without this, it makes bad assumptions and keeps going.
5. **UX is a first-class role.** Having a dedicated UX agent prevented generic, cold bot text.
6. **RTL is a display issue, not a code issue.** Hebrew looks "backward" in terminals — that's the tool, not the code. WhatsApp renders it correctly.
7. **Background agents + Linear polling = async pipelines.** You can chain agents without blocking your conversation.
