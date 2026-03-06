#!/usr/bin/env python3
"""
PostToolUse hook: auto-assigns newly created Linear issues to the TzachClaude project.
Fires after mcp__linear__linear_create_issue.
"""
import json
import re
import subprocess
import sys

API_KEY = "${LINEAR_API_KEY}"
API_URL = "https://api.linear.app/graphql"
PROJECT_ID = "4a6f308a-abe4-4243-8b04-4e1ed8ee8cc8"  # TzachClaude project


def graphql(query):
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", API_URL,
         "-H", f"Authorization: {API_KEY}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"query": query})],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)


data = json.loads(sys.stdin.read())
tool_response = data.get("tool_response", "")

# Extract text from response (MCP returns list of content blocks or plain string)
if isinstance(tool_response, list):
    response_text = " ".join(item.get("text", "") for item in tool_response if isinstance(item, dict))
else:
    response_text = str(tool_response)

# Find the issue identifier (e.g. TZA-6)
match = re.search(r'TZA-\d+', response_text)
if not match:
    sys.exit(0)

identifier = match.group(0)

# Resolve identifier to UUID
result = graphql(f'{{ issue(id: "{identifier}") {{ id }} }}')
issue_id = result["data"]["issue"]["id"]

# Assign to TzachClaude project
result = graphql(
    f'mutation {{ issueUpdate(id: "{issue_id}", input: {{ projectId: "{PROJECT_ID}" }}) {{ success }} }}'
)

if result["data"]["issueUpdate"]["success"]:
    print(f"✓ {identifier} assigned to TzachClaude project")
else:
    print(f"✗ Failed to assign {identifier}", file=sys.stderr)
    sys.exit(1)
