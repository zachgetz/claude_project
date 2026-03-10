---
name: next-phase
description: Promote the next phase of Linear tickets from Backlog to Todo so the programmer agent can start working on them.
user-invocable: true
---

Advance the project to the next phase by moving the appropriate tickets from Backlog → Todo in Linear.

## Team & Project Info
- Team ID: `b2ef251a-01af-4aa8-bc3a-759fce5b5a2b`
- Linear Project ID: `4a6f308a-abe4-4243-8b04-4e1ed8ee8cc8` (TzachClaude)

## Process

### Step 1 — Find the current active phase
Use `linear_search_issues` to fetch all non-Backlog, non-Done tickets (status: Todo, In Progress, In Review) for the team.
- Look at their titles/descriptions to identify which phase number they belong to (e.g. "Phase 1", "[Phase 1]", "Phase: 1")
- The current phase is the lowest phase number that still has active tickets

### Step 2 — Check if current phase is complete
If there are ANY tickets in Todo, In Progress, or In Review for the current phase — stop and warn the user:
> "Phase X is not yet complete. The following tickets are still active: [list]. Run /next-phase again once all are merged and marked Done."

### Step 3 — Find next phase tickets
Use `linear_search_issues` to find all Backlog tickets for the team.
- Identify which ones belong to Phase N+1 (next phase) by reading their titles/descriptions
- List them for the user to confirm before proceeding

### Step 4 — Promote tickets
For each next-phase ticket, use `linear_update_issue` to set its status to **Todo**.

After updating all tickets, report:

| Ticket | Title | Phase | New Status |
|--------|-------|-------|------------|
| TZA-X  | ...   | 2     | Todo       |

End with: **"Phase [N+1] is now active. Programmer agent can start working."**

### Step 5 — Post project update
Post an update to the TzachClaude Linear project using the GraphQL API:
```python
mutation {
  projectUpdateCreate(input: {
    projectId: "4a6f308a-abe4-4243-8b04-4e1ed8ee8cc8",
    body: "## Phase N+1 Active\n\n**Phase N+1 — [phase name]** is now active.\n\n### Active tickets (Todo)\n- TZA-X: ...\n\n### Completed (Phase N)\n- TZA-X: ... ✅\n\n### Up next (Backlog)\n- Phase N+2 — ..."
  }) { success }
}
```
Use Python + curl to build the request (to avoid GraphQL string escaping issues with newlines).

## Notes
- Never promote tickets if the current phase still has open work
- If there is no next phase, tell the user: "All phases are complete. The project is done!"
- Phase number is read from the ticket title or description — look for patterns like "Phase 1", "[Phase 2]", "Phase: 3"
