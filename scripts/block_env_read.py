"""
PreToolUse hook: blocks Read and Grep tool calls targeting .env files,
including via path traversal (../.env, ../../.env, etc.).
Reads tool input JSON from stdin, exits with code 2 if .env access detected.
"""
import sys
import json
import os

data = json.load(sys.stdin)
tool_input = data.get('tool_input', {})

# Paths to check (Read uses file_path, Grep uses path)
paths_to_check = [
    tool_input.get('file_path', '') or '',
    tool_input.get('path', '') or '',
]

for raw_path in paths_to_check:
    if not raw_path:
        continue

    # Resolve the path to eliminate ../ traversal tricks
    resolved = os.path.realpath(os.path.abspath(raw_path))
    basename = os.path.basename(resolved)

    # Also check the raw (unresolved) basename in case realpath can't resolve
    raw_basename = os.path.basename(raw_path.rstrip('/'))

    for name in (basename, raw_basename):
        # Block .env exactly, or .env.local / .env.production etc — but NOT .env.example
        if name == '.env' or (name.startswith('.env.') and name != '.env.example'):
            print(
                f'BLOCKED: access to "{raw_path}" is not allowed (secrets file).',
                file=sys.stderr,
            )
            sys.exit(2)
