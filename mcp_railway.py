"""
Railway MCP Server
Gives Claude Code direct access to Railway logs, env vars, and service status.
"""

import subprocess
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("railway-tools")

RAILWAY_BIN = "/Users/tzachgetz/.nvm/versions/node/v18.20.8/bin/railway"


def _run(args: list[str]) -> str:
    result = subprocess.run(
        [RAILWAY_BIN] + args,
        capture_output=True,
        text=True,
        cwd="/Users/tzachgetz/Projects/claude_project",
    )
    return result.stdout or result.stderr


@mcp.tool()
def get_recent_logs(service: str = "claude_project", lines: int = 50) -> str:
    """Get recent Railway logs for a service. Use this to diagnose errors and crashes."""
    return _run(["logs", "--service", service, "-n", str(lines)])


@mcp.tool()
def get_env_var_names(service: str = "claude_project") -> str:
    """List the names of env vars set on a Railway service (not their values)."""
    output = _run(["variables", "--service", service])
    # Strip values — return only the variable names for safety
    lines = []
    for line in output.splitlines():
        if "=" in line:
            lines.append(line.split("=")[0].strip())
        else:
            lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def get_service_status() -> str:
    """Get the current deployment status of the Railway project."""
    return _run(["status"])


if __name__ == "__main__":
    mcp.run()
