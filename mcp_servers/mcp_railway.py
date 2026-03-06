import subprocess

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("railway-tools")

RAILWAY_BIN = "/Users/tzachgetz/.nvm/versions/node/v18.20.8/bin/railway"

@mcp.tool()
def get_recent_logs(service: str, lines: int = 50) -> str:
    """Get recent logs for a Railway service."""
    result = subprocess.run([RAILWAY_BIN, "logs", "--service", service, "--lines", str(lines)], capture_output=True, text=True)
    return result.stdout


@mcp.tool()
def get_env_vars(service: str) -> str:
    """Get environment variables for a Railway service."""
    result = subprocess.run([RAILWAY_BIN, "variable","list", "--service", service], capture_output=True, text=True)
    return "\n".join([env.split("=")[0] for env in result.stdout.split("\n")])

@mcp.tool()
def redeploy_service(service: str) -> str:
    """ReDeploy the environment for a Railway service."""
    result = subprocess.run([RAILWAY_BIN, "redeploy", "--service", service], capture_output=True, text=True)
    return result.stdout


if __name__ == "__main__":
      mcp.run()
