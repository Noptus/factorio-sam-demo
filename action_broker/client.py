"""
Action Broker Client
====================
Thin async client used by all agents and the MCP server to communicate with
the Action Broker.  Agents should NEVER call env.step() directly.

Usage:
    from action_broker.client import execute, get_game_state

    result = await execute("print(inspect_inventory())")
    state  = await get_game_state()
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

_BROKER_URL: str = os.getenv("ACTION_BROKER_URL", "http://localhost:8765")
_DEFAULT_TIMEOUT: int = int(os.getenv("ACTION_TIMEOUT_S", "30"))
_POLL_INTERVAL: float = 0.5  # seconds between /result polls

# Shared async HTTP client (reuse connections across calls)
_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=_BROKER_URL,
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
        )
    return _http_client


# ─── Public API ───────────────────────────────────────────────────────────────

async def submit_action(
    code: str,
    priority: int = 2,
    timeout: int = _DEFAULT_TIMEOUT,
    agent_id: str = "anonymous",
) -> str:
    """Submit *code* to the broker queue.  Returns the ``action_id``."""
    client = _get_client()
    resp = await client.post(
        "/action",
        json={
            "agent_id": agent_id,
            "priority": priority,
            "code": code,
            "timeout": timeout,
        },
    )
    resp.raise_for_status()
    return resp.json()["action_id"]


async def await_result(
    action_id: str,
    poll_interval: float = _POLL_INTERVAL,
) -> dict[str, Any]:
    """Poll ``GET /result/{action_id}`` until status is ``done`` or ``error``."""
    client = _get_client()
    while True:
        resp = await client.get(f"/result/{action_id}")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data["status"] in ("done", "error"):
            return data
        await asyncio.sleep(poll_interval)


async def execute(
    code: str,
    priority: int = 2,
    timeout: int = _DEFAULT_TIMEOUT,
    agent_id: str = "anonymous",
) -> dict[str, Any]:
    """Submit *code* and block until the result is available.

    Returns a dict with keys: status, stdout, stderr, elapsed_ms, reward, done.
    """
    action_id = await submit_action(code, priority=priority, timeout=timeout, agent_id=agent_id)
    return await await_result(action_id)


async def get_game_state() -> dict[str, Any]:
    """Return the cached game state from the broker.

    This is an instant read (bypasses the action queue) and should be used
    for all read-only queries about the current game state.
    """
    client = _get_client()
    resp = await client.get("/game_state")
    resp.raise_for_status()
    return resp.json()


async def get_health() -> dict[str, Any]:
    """Return broker health info: queue depth, current agent, uptime."""
    client = _get_client()
    resp = await client.get("/health")
    resp.raise_for_status()
    return resp.json()


async def close() -> None:
    """Close the shared HTTP client (call at shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
