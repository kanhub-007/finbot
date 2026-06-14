"""Convenience entry point — run with: python run_mcp.py

Starts the MCP server. Defaults to stdio transport.
Set FINBOT_TRANSPORT=http to run on port 8003.

All startup logic lives in finbot/startup/mcp.py (composition root).
"""

from finbot.startup.mcp import run

if __name__ == "__main__":
    run()
