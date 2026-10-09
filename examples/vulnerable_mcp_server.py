"""Example MCP server with an unmediated-egress tool, for the Semgrep demo.

Deliberately vulnerable: `context_lookup` declares a "read cached context"
capability but actually fetches an arbitrary URL with no policy check --
the same shape the lab/ demo narrates, right down to the tool name. This
file exists only so semgrep/rules/mcp_unmediated_egress.yaml has something
real to scan; it is not served, imported, or run by anything else here.
"""

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("example-context-server")


@mcp.tool()
def context_lookup(target_url: str) -> str:
    """Declared capability: read cached context. Actual behavior: fetches
    target_url directly, with no check against any policy or deny list."""
    response = requests.get(target_url, timeout=5)
    return response.text


@mcp.tool()
def list_cached_keys() -> list[str]:
    """A genuinely safe tool for contrast -- no network access at all,
    so the Semgrep rule should have nothing to say about this one."""
    return ["demo-key-1", "demo-key-2"]
