"""Riskbot MCP server: tools, resources and prompts over ``RunService`` (CONTRACT.md 4.6 / 6.2).

Entry point (exact, per the contract)::

    create_server(service: RunService) -> mcp.server.mcpserver.MCPServer

The composition root (``riskbot/app.py``) wires a concrete ``RunService`` and launches the server
with ``python -m riskbot.app mcp``. See ``README.md`` in this package for the tool table and client
configuration.
"""

from .server import create_server

__all__ = ["create_server"]
