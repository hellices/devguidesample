"""Private MCP + Entra delegated-OBO lab service.

Owns one isolated component of the Azure MCP live lab: the ASGI application
in `service.app`, its Entra token verification, and the three read-only MCP
tools. Infra, deployment, evidence collection and documentation live outside
this package.
"""
