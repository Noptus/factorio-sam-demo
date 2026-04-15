"""
Factorio MCP Server
===================
Exposes Factorio game tools via the Model Context Protocol (MCP) and as plain
REST endpoints.  SAM agents call these tools; the MCP server forwards every
write operation through the Action Broker -- env.step() is NEVER called here.

Start:  uvicorn mcp_server.factorio_mcp:app --port 8766 --host 0.0.0.0

MCP JSON-RPC endpoint:  POST /mcp
REST tool endpoints:
    POST /tools/get_game_state
    POST /tools/execute_code
    POST /tools/get_lab_tasks
    POST /tools/get_few_shot_example
    POST /tools/get_task_progress
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import textwrap
from contextlib import asynccontextmanager
from typing import Any

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from action_broker import client as broker

load_dotenv()

log = logging.getLogger("factorio_mcp")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/mcp_server.log"),
    ],
)

# ─── Paths ────────────────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).parent.parent
_TASKS_FILE = _ROOT / "tasks" / "lab_play_tasks.yaml"

# ─── Cache tasks at module level ──────────────────────────────────────────────
_tasks_cache: list[dict[str, Any]] | None = None


def _load_tasks() -> list[dict[str, Any]]:
    global _tasks_cache
    if _tasks_cache is None:
        if _TASKS_FILE.exists():
            raw = yaml.safe_load(_TASKS_FILE.read_text())
            _tasks_cache = raw.get("tasks", [])
        else:
            _tasks_cache = []
            log.warning("Tasks file not found: %s", _TASKS_FILE)
    return _tasks_cache


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    _load_tasks()  # warm cache
    log.info("Factorio MCP Server ready on port 8766")
    yield
    await broker.close()
    log.info("MCP Server shut down.")


app = FastAPI(title="Factorio MCP Server", lifespan=lifespan)

# ─── Tool definitions (for MCP tools/list) ────────────────────────────────────
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_game_state",
        "description": (
            "Return the current cached Factorio game state from the broker.  "
            "Includes: inventory, research_progress, entities_near_player (radius 20), "
            "production_stats_per_minute, player_position, map_dimensions.  "
            "This is instant — it does NOT queue an action."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "execute_code",
        "description": (
            "Execute arbitrary Python code inside the Factorio Learning Environment.  "
            "Code runs in the game context and has access to all FLE APIs "
            "(get_resource_patches, move_to, harvest_resource, craft_item, place_entity, "
            "insert_item, extract_item, inspect_inventory, get_entities, sleep, etc.).  "
            "Returns stdout, stderr, and a success flag.  "
            "On error the 'hint' field suggests the fix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute in the FLE game context.",
                },
                "priority": {
                    "type": "integer",
                    "description": "0=EMERGENCY, 1=HIGH, 2=NORMAL (default), 3=LOW",
                    "default": 2,
                    "minimum": 0,
                    "maximum": 3,
                },
                "agent_id": {
                    "type": "string",
                    "description": "Identifier of the calling agent (for logging).",
                    "default": "mcp_client",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_lab_tasks",
        "description": "Return all 24 FLE lab-play task definitions including task_id, target_entity, target_count, time_limit_s, complexity_tier.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_few_shot_example",
        "description": (
            "Return verified working FLE Python code for a given category.  "
            "Call this BEFORE writing code for a new action category.  "
            "Categories: mining, smelting, crafting, placement, logistics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["mining", "smelting", "crafting", "placement", "logistics"],
                    "description": "The code category to retrieve examples for.",
                }
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_task_progress",
        "description": "Return current progress toward a specific lab-play task goal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID from get_lab_tasks().",
                }
            },
            "required": ["task_id"],
        },
    },
]


# ─── Tool implementations ─────────────────────────────────────────────────────

async def _tool_get_game_state() -> dict[str, Any]:
    raw = await broker.get_game_state()

    # Enrich with derived fields that agents care about
    return {
        "inventory": raw.get("inventory", {}),
        "player_position": raw.get("player", {}).get("position", {}),
        "map_dimensions": raw.get("map", {}).get("dimensions", {}),
        "entities_near_player": raw.get("nearby_entities", []),
        "research_progress": raw.get("research", {}),
        "production_stats_per_minute": raw.get("production_stats", {}),
        "raw": raw,  # Full observation for agents that need it
    }


async def _tool_execute_code(
    code: str,
    priority: int = 2,
    agent_id: str = "mcp_client",
) -> dict[str, Any]:
    try:
        result = await broker.execute(code, priority=priority, agent_id=agent_id)
    except Exception as exc:
        log.error("Broker communication error: %s", exc)
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_ms": 0,
            "hint": "The Action Broker may be down.  Run: uvicorn action_broker.broker:app --port 8765",
        }

    if result["status"] == "error":
        stderr = result.get("stderr", "")
        hint = _generate_hint(code, stderr)
        return {
            "success": False,
            "stdout": result.get("stdout", ""),
            "stderr": stderr,
            "elapsed_ms": result.get("elapsed_ms", 0),
            "hint": hint,
        }

    return {
        "success": True,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "reward": result.get("reward", 0.0),
        "done": result.get("done", False),
        "hint": "",
    }


def _generate_hint(code: str, stderr: str) -> str:
    """Produce a human-readable fix hint from a stderr message."""
    stderr_lower = stderr.lower()

    if "not enough" in stderr_lower or "insufficient" in stderr_lower:
        return "Gather more resources first: use get_game_state() to check inventory, then mine/smelt what you need."
    if "no entity" in stderr_lower or "entity not found" in stderr_lower:
        return "The entity was not found.  Use get_game_state() to list nearby entities and verify positions."
    if "cannot place" in stderr_lower or "invalid placement" in stderr_lower:
        return "Placement failed.  Check for collisions with existing entities using get_entities() before placing."
    if "prototype" in stderr_lower:
        return "Unknown Prototype name.  Import from factorio_learning_environment.entities and verify spelling."
    if "timeout" in stderr_lower:
        return "The action timed out.  The game may be paused or the server unresponsive.  Try again or restart."
    if "attributeerror" in stderr_lower:
        return "Attribute error: check the FLE API docs.  Common mistake: using wrong field names on Entity objects."
    if "syntaxerror" in stderr_lower or "indentationerror" in stderr_lower:
        return "Python syntax error in the submitted code.  Fix indentation or syntax before resubmitting."
    if "inventory" in stderr_lower or "item" in stderr_lower:
        return "Item not found in inventory.  Call inspect_inventory() and verify item names match Factorio item IDs."

    return "Review stderr for details.  Fetch a few-shot example with get_few_shot_example() for the relevant category."


async def _tool_get_lab_tasks() -> list[dict[str, Any]]:
    return _load_tasks()


async def _tool_get_few_shot_example(category: str) -> str:
    try:
        from few_shot import get_example_source  # noqa: PLC0415
        return get_example_source(category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Example file not found: {exc}") from exc


async def _tool_get_task_progress(task_id: str) -> dict[str, Any]:
    tasks = _load_tasks()
    task = next((t for t in tasks if t.get("task_id") == task_id), None)
    if task is None:
        return {"error": f"Task '{task_id}' not found", "known_ids": [t["task_id"] for t in tasks]}

    # Read current game state for progress computation
    state = await broker.get_game_state()
    inventory = state.get("inventory", {})
    research = state.get("research", {})
    production = state.get("production_stats", {})

    target_entity: str = task.get("target_entity", "")
    target_count: int = task.get("target_count", 0)
    task_type: str = task.get("type", "craft")

    current_count = 0
    if task_type in ("gather", "craft", "smelt"):
        current_count = inventory.get(target_entity, 0)
    elif task_type == "research":
        tech = research.get("researched_technologies", [])
        current_count = 1 if target_entity in tech else 0
        target_count = 1
    elif task_type == "place":
        entities_nearby = state.get("nearby_entities", [])
        placed = [e for e in entities_nearby if e.get("type") == target_entity]
        current_count = len(placed)
    elif task_type == "automate":
        current_count = int(production.get(target_entity, 0))

    pct = (current_count / target_count * 100) if target_count > 0 else 0
    return {
        "task_id": task_id,
        "name": task.get("name", ""),
        "target_entity": target_entity,
        "target_count": target_count,
        "current_count": current_count,
        "progress_pct": round(pct, 1),
        "complete": current_count >= target_count,
        "complexity_tier": task.get("complexity_tier", 1),
    }


# ─── REST endpoints ───────────────────────────────────────────────────────────

@app.post("/tools/get_game_state")
async def rest_get_game_state() -> JSONResponse:
    return JSONResponse(await _tool_get_game_state())


class ExecuteCodeRequest(BaseModel):
    code: str
    priority: int = Field(2, ge=0, le=3)
    agent_id: str = "mcp_client"


@app.post("/tools/execute_code")
async def rest_execute_code(req: ExecuteCodeRequest) -> JSONResponse:
    return JSONResponse(await _tool_execute_code(req.code, req.priority, req.agent_id))


@app.post("/tools/get_lab_tasks")
async def rest_get_lab_tasks() -> JSONResponse:
    return JSONResponse(await _tool_get_lab_tasks())


class FewShotRequest(BaseModel):
    category: str


@app.post("/tools/get_few_shot_example")
async def rest_get_few_shot_example(req: FewShotRequest) -> JSONResponse:
    text = await _tool_get_few_shot_example(req.category)
    return JSONResponse({"category": req.category, "source": text})


class TaskProgressRequest(BaseModel):
    task_id: str


@app.post("/tools/get_task_progress")
async def rest_get_task_progress(req: TaskProgressRequest) -> JSONResponse:
    return JSONResponse(await _tool_get_task_progress(req.task_id))


# ─── MCP JSON-RPC endpoint ────────────────────────────────────────────────────

@app.post("/mcp")
async def mcp_jsonrpc(request: Request) -> JSONResponse:
    """Handle MCP JSON-RPC 2.0 requests."""
    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
        )

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "factorio-mcp", "version": "1.0.0"},
            }

        elif method == "tools/list":
            result = {"tools": TOOL_DEFINITIONS}

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            if tool_name == "get_game_state":
                tool_result = await _tool_get_game_state()
            elif tool_name == "execute_code":
                tool_result = await _tool_execute_code(
                    args.get("code", ""),
                    args.get("priority", 2),
                    args.get("agent_id", "mcp_client"),
                )
            elif tool_name == "get_lab_tasks":
                tool_result = await _tool_get_lab_tasks()
            elif tool_name == "get_few_shot_example":
                source = await _tool_get_few_shot_example(args.get("category", ""))
                tool_result = {"category": args.get("category"), "source": source}
            elif tool_name == "get_task_progress":
                tool_result = await _tool_get_task_progress(args.get("task_id", ""))
            else:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {tool_name}"},
                    "id": req_id,
                })

            result = {
                "content": [{"type": "text", "text": json.dumps(tool_result, indent=2)}],
                "isError": False,
            }

        elif method == "notifications/initialized":
            # Client acknowledgement, no response needed
            return JSONResponse({"jsonrpc": "2.0", "result": None, "id": req_id})

        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
                "id": req_id,
            })

        return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

    except Exception as exc:  # noqa: BLE001
        log.error("MCP handler error [%s]: %s", method, exc, exc_info=True)
        return JSONResponse({
            "jsonrpc": "2.0",
            "error": {"code": -32603, "message": f"Internal error: {exc}"},
            "id": req_id,
        })


@app.get("/health")
async def health() -> JSONResponse:
    broker_health = {}
    try:
        broker_health = await broker.get_health()
    except Exception as exc:  # noqa: BLE001
        broker_health = {"error": str(exc)}
    return JSONResponse({"mcp_server": "ok", "broker": broker_health})


# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mcp_server.factorio_mcp:app", host="0.0.0.0", port=8766, reload=False)
