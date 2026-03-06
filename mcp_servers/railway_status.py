import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
import requests

server = Server("railway-status")
base_url = "https://claudeproject-production.up.railway.app"
@server.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="check_railway_status",
            description="Check if the Railway deployment is up",
            inputSchema={
                "type": "object",
                "properties": {},  # no inputs needed
                "required": []
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "check_railway_status":
        res = requests.get(f"{base_url}/health")
        return [types.TextContent(
          type="text",
          text=f"Status: {res.status_code} | Response time: {res.elapsed.total_seconds():.2f}s"
      )]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())