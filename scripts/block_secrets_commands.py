"""
PreToolUse hook: blocks Bash commands that would print secrets to the screen.
Reads tool input JSON from stdin, exits with code 2 if a secrets-exposing command is detected.

Only inspects actual command tokens (splits on shell operators), not string arguments,
to avoid false positives on commit messages or comments that mention these commands.
"""
import sys
import json
import re

data = json.load(sys.stdin)
command = data.get('tool_input', {}).get('command', '') or ''

# Strip heredoc / quoted string content to avoid matching inside commit messages etc.
# Remove everything between <<'EOF' ... EOF and "$(cat ...)" style constructs
stripped = re.sub(r'\$\(cat\s*<<.*?EOF\s*\)', '', command, flags=re.DOTALL)
stripped = re.sub(r'"[^"]{50,}"', '""', stripped)  # remove long quoted strings

# Split on shell operators to get individual command invocations
tokens = re.split(r'&&|\|\||;|\|', stripped)

for token in tokens:
    token = token.strip()
    # Block: railway variables (but allow --set which writes, not reads)
    if re.match(r'railway\s+variables(?!\s+--set)', token):
        print(
            'BLOCKED: "railway variables" prints secrets. Run it yourself in your terminal.',
            file=sys.stderr,
        )
        sys.exit(2)
    # Block: bare printenv or env (dumps all env vars)
    if re.match(r'(?:printenv|env)\s*$', token):
        print(
            'BLOCKED: command dumps all environment variables (secrets). Run it yourself.',
            file=sys.stderr,
        )
        sys.exit(2)
