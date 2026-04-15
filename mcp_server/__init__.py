"""
MCP Server package.

Exposes Factorio game tools via the Model Context Protocol (MCP).
All tools route through the Action Broker -- env.step() is NEVER called here.
"""
