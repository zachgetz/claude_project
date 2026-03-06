#!/usr/bin/env python3
"""
3-Agent Pipeline: Ideas → PM → Programmer

Chains all three agents end-to-end via the Anthropic SDK.
Usage: python agents/pipeline.py "your seed topic here"

Requirements:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-...
    export LINEAR_API_KEY=${LINEAR_API_KEY}...   (for Linear ticket creation)
    gh auth login                        (for GitHub PR creation)
"""

import os
import sys
import json
import subprocess
import argparse
import anthropic

MODEL = "claude-sonnet-4-6"

# ── Skill prompt loaders ─────────────────────────────────────────────────────

def load_skill(skill_name: str) -> str:
    """Load a skill prompt from .claude/skills/<skill_name>.md"""
    skill_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        ".claude", "skills", f"{skill_name}.md"
    )
    with open(skill_path) as f:
        content = f.read()
    # Strip frontmatter if present
    if content.startswith("---"):
        parts = content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else content
    return content


# ── Stage 1: Ideas Creator ───────────────────────────────────────────────────

def run_ideas_creator(client: anthropic.Anthropic, seed_topic: str) -> str:
    """Generate a product idea spec from a seed topic."""
    print("\n[Stage 1] Ideas Creator — generating idea spec...")

    system_prompt = load_skill("idea-creator")

    message = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Seed topic: {seed_topic}"
            }
        ]
    )

    idea_spec = message.content[0].text
    print("\n--- IDEA SPEC ---")
    print(idea_spec)
    print("--- END SPEC ---\n")
    return idea_spec


# ── Stage 2: PM Agent ────────────────────────────────────────────────────────

def run_pm_agent(client: anthropic.Anthropic, idea_spec: str) -> list[dict]:
    """
    Break idea spec into tasks. Returns a list of task dicts:
    [{"title": "...", "description": "..."}, ...]

    Note: In the full pipeline, tickets are created via Linear MCP.
    Here we extract structured tasks as JSON for programmatic use.
    """
    print("[Stage 2] PM Agent — breaking spec into tasks...")

    system_prompt = load_skill("pm-agent") + """

## Additional Instruction for Pipeline Mode
Instead of calling Linear MCP tools, output your ticket list as a JSON array
at the END of your response, wrapped in a ```json ... ``` code block.
Format:
```json
[
  {
    "title": "Ticket title",
    "description": "## What\\n...\\n\\n## Acceptance Criteria\\n- [ ] ...\\n\\n## Notes\\n..."
  }
]
```
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"Here is the idea spec to break into tasks:\n\n{idea_spec}"
            }
        ]
    )

    response_text = message.content[0].text
    print(response_text)

    # Extract JSON ticket list from the response
    tickets = []
    if "```json" in response_text:
        json_block = response_text.split("```json")[1].split("```")[0].strip()
        try:
            tickets = json.loads(json_block)
        except json.JSONDecodeError as e:
            print(f"Warning: could not parse ticket JSON: {e}")

    return tickets


# ── Stage 3: Programmer Agent ────────────────────────────────────────────────

def run_programmer_agent(
    client: anthropic.Anthropic,
    ticket: dict,
    repo_path: str = ".",
    github_repo: str | None = None
) -> str:
    """
    Implement a single ticket. Returns the PR URL.

    In pipeline mode this generates the implementation plan and outputs
    git commands. Actual git ops are run via subprocess.
    """
    print(f"\n[Stage 3] Programmer Agent — implementing: {ticket['title']}")

    system_prompt = load_skill("programmer") + """

## Pipeline Mode
You are running in fully automated pipeline mode. There is no interactive user.
- Output the implementation as a diff or set of file contents to create/modify.
- After describing the implementation, output a JSON block with git metadata:
```json
{
  "branch": "feat/pipeline-<slug>",
  "commit_message": "feat: <ticket title>",
  "files": [
    {"path": "relative/path/to/file.py", "content": "...full file content..."}
  ],
  "pr_title": "feat: <ticket title>",
  "pr_body": "## Summary\\n...\\n\\n## Ticket\\n<title>"
}
```
"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Implement this ticket:\n\n"
                    f"**{ticket['title']}**\n\n"
                    f"{ticket['description']}"
                )
            }
        ]
    )

    response_text = message.content[0].text
    print(response_text)

    # Extract implementation metadata
    pr_url = None
    if "```json" in response_text:
        json_block = response_text.split("```json")[1].split("```")[0].strip()
        try:
            impl = json.loads(json_block)
            pr_url = _apply_implementation(impl, repo_path, github_repo)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: could not apply implementation automatically: {e}")
            print("Review the output above and apply changes manually.")

    return pr_url or "(manual implementation required)"


def _apply_implementation(impl: dict, repo_path: str, github_repo: str | None) -> str | None:
    """Write files, commit, push, and open a PR. Returns PR URL."""
    branch = impl.get("branch", "feat/pipeline-auto")
    commit_msg = impl.get("commit_message", "feat: implement ticket")
    files = impl.get("files", [])
    pr_title = impl.get("pr_title", commit_msg)
    pr_body = impl.get("pr_body", "Auto-generated PR from pipeline.")

    if not files:
        print("No files to write — skipping git ops.")
        return None

    # Create branch
    subprocess.run(["git", "-C", repo_path, "checkout", "-b", branch], check=True)

    # Write files
    for file_info in files:
        file_path = os.path.join(repo_path, file_info["path"])
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w") as f:
            f.write(file_info["content"])
        print(f"  Wrote: {file_info['path']}")

    # Commit
    subprocess.run(["git", "-C", repo_path, "add"] + [f["path"] for f in files], check=True)
    subprocess.run(["git", "-C", repo_path, "commit", "-m", commit_msg], check=True)

    # Push
    subprocess.run(
        ["git", "-C", repo_path, "push", "-u", "origin", branch],
        check=True
    )

    # Open PR via gh CLI
    repo_flag = ["-R", github_repo] if github_repo else []
    result = subprocess.run(
        ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "main"]
        + repo_flag,
        capture_output=True,
        text=True,
        cwd=repo_path
    )
    if result.returncode == 0:
        pr_url = result.stdout.strip()
        print(f"  PR created: {pr_url}")
        return pr_url
    else:
        print(f"  PR creation failed: {result.stderr}")
        return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run the 3-agent pipeline: Ideas → PM → Programmer"
    )
    parser.add_argument("topic", help="Seed topic for the Ideas Creator agent")
    parser.add_argument(
        "--repo", default=".", help="Path to the git repo (default: current directory)"
    )
    parser.add_argument(
        "--github-repo",
        help="GitHub repo in owner/repo format (optional, inferred from git remote if omitted)"
    )
    parser.add_argument(
        "--tickets-only",
        action="store_true",
        help="Stop after PM stage — only generate tickets, don't implement"
    )
    parser.add_argument(
        "--ticket-index",
        type=int,
        default=0,
        help="Which ticket to implement (0-indexed, default: 0 = first ticket)"
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Stage 1
    idea_spec = run_ideas_creator(client, args.topic)

    # Stage 2
    tickets = run_pm_agent(client, idea_spec)
    if not tickets:
        print("No tickets extracted — check PM Agent output above.")
        sys.exit(1)

    print(f"\nExtracted {len(tickets)} ticket(s):")
    for i, t in enumerate(tickets):
        print(f"  [{i}] {t['title']}")

    if args.tickets_only:
        print("\nStopping after PM stage (--tickets-only).")
        sys.exit(0)

    # Stage 3 — implement the selected ticket
    ticket = tickets[args.ticket_index]
    pr_url = run_programmer_agent(client, ticket, args.repo, args.github_repo)

    print(f"\nPipeline complete.")
    print(f"  Ticket implemented: {ticket['title']}")
    print(f"  PR: {pr_url}")


if __name__ == "__main__":
    main()
