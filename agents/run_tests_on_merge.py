import sys
import json
import subprocess

try:
    data = json.load(sys.stdin)
    repo = data["tool_input"]["repo"]

    if repo != "claude_project":
        sys.exit(0)

    print(f"[hook] PR merged in {repo}, running tests...")

    result = subprocess.run(
        ["python3.11", "manage.py", "test", "--settings=standup_bot.settings.dev"],
        cwd="/Users/tzachgetz/Projects/claude_project",
        capture_output=True,
        text=True
    )

    print(result.stdout)
    print(result.stderr)

    if result.returncode == 0:
        print("[hook] Tests passed ✓")
        sys.exit(0)

    print("[hook] Tests FAILED — creating Linear ticket...")
    description = result.stdout + result.stderr
    title = "[Auto] Tests failing after PR merge"

    payload = json.dumps({
        'query': '''mutation {
            issueCreate(input: {
                teamId: \"b2ef251a-01af-4aa8-bc3a-759fce5b5a2b\"
                projectId: \"4a6f308a-abe4-4243-8b04-4e1ed8ee8cc8\"
                title: ''' + json.dumps(title) + '''
                description: ''' + json.dumps(description) + '''
                stateId: \"5c9156d6-0e7a-46fc-9222-1e325443ff85\"
            }) {
                success
                issue { id identifier title }
            }
        }'''
    })
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', 'https://api.linear.app/graphql',
         '-H', 'Authorization: ${LINEAR_API_KEY}',
         '-H', 'Content-Type: application/json',
         '-d', payload],
        capture_output=True, text=True
    )
    result = json.loads(r.stdout)
    print(result['data']['issueCreate']['issue']['identifier'], '-', title)

except Exception as e:
    print(f"[hook error] {e}", file=sys.stderr)
    sys.exit(0)
