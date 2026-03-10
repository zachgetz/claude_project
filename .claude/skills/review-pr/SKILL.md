---
name: review PR
description: run review-PR agent.
user-invocable: true
---

activate agent for code-review

## Usage
The user will invoke this as: `/review-pr 123` 123 is the PR number.


## Process

### Step 1 — Identify the PR
you get it as an input.


### Step 2 — run the agent
read the agent prompt from /Users/tzachgetz/Projects/claude_project/agents/code-review-agent.md and pass the PR number to it.

### Step 3 — Mark as Done
 print the agent's verdict (APPROVED / BLOCKED).

