#!/bin/bash
cd /Users/tzachgetz/Projects/claude_project
output=$(/Users/tzachgetz/.pyenv/versions/3.11.1/bin/python manage.py test apps.standup.tests 2>&1)
failures=$(echo "$output" | grep -E "^(FAIL|ERROR): ")
ran=$(echo "$output" | grep -oE "Ran [0-9]+ test")

if [ -n "$failures" ]; then
  echo "Failed tests:"
  echo "$failures"
  exit 1
else
  echo "All tests passed! ($ran)"
  exit 0
fi
