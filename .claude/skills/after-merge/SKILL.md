---
name: after-merge
description: Mark a Linear ticket as Done after its PR has been merged. Usage: /after-merge TZA-5
user-invocable: true
---

Mark a Linear ticket as Done after the user has merged its PR.

## Usage
The user will invoke this as: `/after-merge TZA-5` (or provide the ticket ID in the message)

## Team & Project Info
- Team ID: `b2ef251a-01af-4aa8-bc3a-759fce5b5a2b`
- Linear Project ID: `4a6f308a-abe4-4243-8b04-4e1ed8ee8cc8` (TzachClaude)

## Process

### Step 1 — Identify the ticket
Extract the ticket identifier from the user's message (e.g. `TZA-5`).
If no identifier is provided, ask: "Which ticket was merged? (e.g. TZA-5)"

### Step 2 — Fetch ticket details
Use `linear_search_issues` to find the ticket and confirm:
- Its current status (should be "In Review")
- Its title
- Which phase it belongs to

If the ticket is not in "In Review", warn the user:
> "TZA-X is currently in [status], not In Review. Are you sure you want to mark it Done?"
Ask for confirmation before proceeding.

### Step 3 — Mark as Done
Use `linear_update_issue` to set the ticket status to **Done**.

Confirm: **"✓ TZA-X — [title] marked as Done."**

### Step 4 — Check phase completion
After marking Done, check if all tickets in the same phase are now Done:
- Use `linear_search_issues` to find all tickets in the same phase
- If any are still Todo, In Progress, or In Review — list them:
  > "Phase X still has [N] open tickets: [list]"
- If any are still open, list them and stop.
- If all are Done:
  1. Post a project update via GraphQL (Python + curl):
     ```
     ## Phase X Complete ✅
     All Phase X tickets are merged and done.
     [list of completed tickets]
     ```
  2. Promote next phase tickets from Backlog → Todo via GraphQL
  3. Say: **"🎉 Phase X is complete! Programmer agent is being launched for Phase X+1."**
  4. **Launch the programmer agent** using the Task tool with subagent_type=general-purpose.
     Use subagent_type=programmer and tell it: "Phase X is done. Start working on Phase X+1 tickets (now in Todo). Work fully autonomously — implement, merge, and continue to Phase X+2 when done."

## Notes
- Phase is determined by reading the ticket title or description for patterns like "Phase 1", "[Phase 2]", "Phase: 3"
- Multiple tickets can be passed: `/after-merge TZA-5 TZA-6 TZA-7` — process each one
