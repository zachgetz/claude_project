---
name: assign-to-project
description: Assign one or more Linear tickets to a Linear project using the GraphQL API.
user-invocable: true
---

Assign Linear issues to a specific Linear project using the Linear GraphQL API.

## What You Need

- **Issue IDs**: One or more Linear issue UUIDs (not identifiers like TZA-5, but internal UUIDs)
- **Project name**: The name of the Linear project (e.g., "TzachClaude")
- **API key**: `${LINEAR_API_KEY}`
- **API endpoint**: `https://api.linear.app/graphql`

## Process

### Step 1 — Find the project ID by name

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: ${LINEAR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ projects { nodes { id name } } }"}'
```

Parse the response to find the `id` of the target project.

### Step 2 — Find the issue UUID from its identifier (e.g. TZA-5)

If you only have the issue identifier (e.g. TZA-5), resolve it to a UUID first:

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: ${LINEAR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ issue(id: \"TZA-5\") { id title } }"}'
```

### Step 3 — Assign the issue to the project

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: ${LINEAR_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { issueUpdate(id: \"ISSUE_UUID\", input: { projectId: \"PROJECT_UUID\" }) { success issue { id title project { name } } } }"
  }'
```

### Step 4 — Confirm

After each assignment, confirm: `"✓ TZA-X assigned to [Project Name]"`

If assigning multiple issues, loop through all of them and report a summary table at the end:

| Ticket | Title | Project | Status |
|--------|-------|---------|--------|
| TZA-5  | ...   | TzachClaude | ✓ |

## Notes

- The Linear `issue()` query accepts both UUID and identifier (e.g. `"TZA-5"`) as the `id` argument.
- If the project is not found, list all available projects and ask the user to confirm the name.
- Never hardcode UUIDs in responses — always resolve them dynamically.
