"""
Factorio Action Broker
======================
A FastAPI server that acts as the SINGLE serialization point for all FLE
env.step() calls.  Multiple SAM agents submit Python code snippets via HTTP;
the broker executes them one at a time from an asyncio.PriorityQueue, caches
the game state, and returns structured results.

Start:  uvicorn action_broker.broker:app --port 8765 --host 0.0.0.0
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .priority import Priority

load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=_LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/broker.log"),
    ],
)
log = logging.getLogger("action_broker")


# ─── FLE Environment ──────────────────────────────────────────────────────────
_env: Any = None  # FactorioEnv instance, initialised at startup
_fle_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fle-worker")


def _init_fle_env() -> Any:
    """Initialise the Factorio Learning Environment (blocking, runs in thread)."""
    try:
        from factorio_learning_environment.env import FactorioEnv  # type: ignore
    except ImportError as exc:
        log.warning("factorio-learning-environment not installed: %s", exc)
        log.warning("Broker will start but execute_code will fail until FLE is available.")
        return None

    host = os.getenv("FACTORIO_HOST", "localhost")
    port = int(os.getenv("FACTORIO_PORT", "34197"))
    log.info("Connecting to Factorio at %s:%d …", host, port)
    env = FactorioEnv(host=host, port=port)
    env.reset()
    log.info("FLE environment ready.")
    return env


def _fle_step(code: str) -> dict[str, Any]:
    """Execute *code* via env.step() in the FLE executor thread.

    Returns a normalised dict:
        {stdout, stderr, observation, reward, done}
    """
    if _env is None:
        raise RuntimeError("FLE environment not initialised.  Is Factorio running?")

    raw = _env.step(code)

    # Gym ≥0.26 returns (obs, reward, terminated, truncated, info)
    # Older gym returns (obs, reward, done, info)
    if len(raw) == 5:
        observation, reward, terminated, truncated, info = raw
        done = bool(terminated or truncated)
    elif len(raw) == 4:
        observation, reward, done, info = raw  # type: ignore[misc]
    else:
        raise ValueError(f"Unexpected env.step() return length: {len(raw)}")

    return {
        "stdout": str(info.get("stdout", "")),
        "stderr": str(info.get("stderr", "")),
        "observation": observation if isinstance(observation, dict) else {},
        "reward": float(reward),
        "done": bool(done),
    }


# ─── Queue item ───────────────────────────────────────────────────────────────
@dataclasses.dataclass(order=True)
class _QueueItem:
    priority: int
    sequence: int  # Tie-breaker: FIFO within same priority
    action_id: str = dataclasses.field(compare=False)
    agent_id: str = dataclasses.field(compare=False)
    code: str = dataclasses.field(compare=False)
    timeout: int = dataclasses.field(compare=False)


# ─── Shared state ─────────────────────────────────────────────────────────────
_queue: asyncio.PriorityQueue[_QueueItem]
_results: dict[str, dict[str, Any]] = {}
_game_state_cache: dict[str, Any] = {}
_sequence_counter: int = 0
_start_time: float = 0.0
_current_agent: str = "idle"
_worker_task: Optional[asyncio.Task[None]] = None


# ─── Worker coroutine ─────────────────────────────────────────────────────────
async def _worker() -> None:
    """Single async worker that serialises all env.step() calls."""
    global _current_agent, _game_state_cache
    loop = asyncio.get_running_loop()

    while True:
        item: _QueueItem = await _queue.get()
        _current_agent = item.agent_id
        _results[item.action_id]["status"] = "running"

        log.info(
            "EXEC | agent=%-20s priority=%d action=%s code=%.80r",
            item.agent_id,
            item.priority,
            item.action_id,
            item.code,
        )

        t0 = time.monotonic()
        last_exc: Exception | None = None

        # Exponential backoff retry: 0 s, 1 s, 2 s, 4 s (max 3 retries)
        for attempt, backoff in enumerate([0, 1, 2, 4]):
            if backoff:
                log.warning("Retry %d for action %s after %ds backoff", attempt, item.action_id, backoff)
                await asyncio.sleep(backoff)
            try:
                step_future = loop.run_in_executor(
                    _fle_executor,
                    _fle_step,
                    item.code,
                )
                step_result = await asyncio.wait_for(step_future, timeout=item.timeout)
                break  # success
            except asyncio.TimeoutError:
                last_exc = TimeoutError(f"FLE step timed out after {item.timeout}s")
                log.error("Timeout on action %s (attempt %d)", item.action_id, attempt)
                # Cancel the underlying thread if possible (best-effort)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                log.error("Error on action %s attempt %d: %s", item.action_id, attempt, exc)
                if attempt == 3:
                    break
        else:
            step_result = None

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if step_result is not None and last_exc is None:
            # Update game state cache with latest observation
            if step_result.get("observation"):
                _game_state_cache.update(step_result["observation"])

            _results[item.action_id] = {
                "status": "done",
                "stdout": step_result["stdout"],
                "stderr": step_result["stderr"],
                "reward": step_result["reward"],
                "done": step_result["done"],
                "elapsed_ms": elapsed_ms,
            }
            log.info("DONE | action=%s elapsed=%dms", item.action_id, elapsed_ms)
        else:
            error_msg = str(last_exc) if last_exc else "Unknown error"
            _results[item.action_id] = {
                "status": "error",
                "stdout": "",
                "stderr": error_msg,
                "reward": 0.0,
                "done": False,
                "elapsed_ms": elapsed_ms,
                "traceback": traceback.format_exc(),
            }
            log.error("FAIL | action=%s error=%s elapsed=%dms", item.action_id, error_msg, elapsed_ms)

        _current_agent = "idle"
        _queue.task_done()


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _env, _queue, _start_time, _worker_task
    _start_time = time.time()
    _queue = asyncio.PriorityQueue()

    # Initialise FLE in the dedicated executor thread
    loop = asyncio.get_running_loop()
    _env = await loop.run_in_executor(_fle_executor, _init_fle_env)

    # Start the single worker coroutine
    _worker_task = asyncio.create_task(_worker(), name="fle-worker")
    log.info("Action Broker ready on port 8765")

    yield  # ── server runs ──

    _worker_task.cancel()
    _fle_executor.shutdown(wait=False)
    log.info("Action Broker shut down.")


app = FastAPI(title="Factorio Action Broker", lifespan=lifespan)


# ─── Request / Response models ────────────────────────────────────────────────
class ActionRequest(BaseModel):
    agent_id: str = Field(..., description="Identifier of the submitting agent")
    priority: int = Field(Priority.NORMAL, ge=0, le=3, description="0=EMERGENCY … 3=LOW")
    code: str = Field(..., description="Python code to execute inside FLE")
    timeout: int = Field(30, ge=1, le=300, description="Per-action timeout in seconds")


class ActionResponse(BaseModel):
    action_id: str
    status: str
    position: int


class ResultResponse(BaseModel):
    status: str
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: int = 0
    reward: float = 0.0
    done: bool = False


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.post("/action", response_model=ActionResponse)
async def submit_action(req: ActionRequest) -> ActionResponse:
    """Enqueue a Python code action for serialised execution."""
    global _sequence_counter

    action_id = str(uuid.uuid4())
    _sequence_counter += 1
    seq = _sequence_counter

    item = _QueueItem(
        priority=req.priority,
        sequence=seq,
        action_id=action_id,
        agent_id=req.agent_id,
        code=req.code,
        timeout=req.timeout,
    )

    _results[action_id] = {"status": "queued", "stdout": "", "stderr": "", "elapsed_ms": 0}
    await _queue.put(item)

    position = _queue.qsize()
    log.info(
        "QUEUE | agent=%-20s priority=%d action=%s queue_depth=%d",
        req.agent_id,
        req.priority,
        action_id,
        position,
    )
    return ActionResponse(action_id=action_id, status="queued", position=position)


@app.get("/result/{action_id}", response_model=ResultResponse)
async def get_result(action_id: str) -> ResultResponse:
    """Poll the result of a previously submitted action."""
    if action_id not in _results:
        raise HTTPException(status_code=404, detail=f"Action {action_id!r} not found")
    data = _results[action_id]
    return ResultResponse(
        status=data.get("status", "unknown"),
        stdout=data.get("stdout", ""),
        stderr=data.get("stderr", ""),
        elapsed_ms=data.get("elapsed_ms", 0),
        reward=data.get("reward", 0.0),
        done=data.get("done", False),
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Live health endpoint for liveness probes and monitoring."""
    return JSONResponse({
        "queue_depth": _queue.qsize() if _queue else 0,
        "current_agent": _current_agent,
        "uptime_s": int(time.time() - _start_time) if _start_time else 0,
        "fle_ready": _env is not None,
        "total_actions_seen": _sequence_counter,
    })


@app.get("/game_state")
async def game_state() -> JSONResponse:
    """
    Return the cached game state (last observation from env.step()).
    This is a READ operation that bypasses the queue and returns instantly.
    """
    return JSONResponse(_game_state_cache)


@app.get("/metrics")
async def metrics() -> JSONResponse:
    """Basic metrics: counts by result status."""
    counts: dict[str, int] = {}
    for r in _results.values():
        s = r.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    return JSONResponse({"result_counts": counts, "queue_depth": _queue.qsize() if _queue else 0})


# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("action_broker.broker:app", host="0.0.0.0", port=8765, reload=False)
