"""
Factorio Action Broker
======================
A FastAPI server that acts as the SINGLE serialization point for all FLE
env.step() calls.  Multiple SAM agents submit Python code snippets via HTTP;
the broker executes them one at a time from an asyncio.PriorityQueue, caches
the game state, and returns structured results.

Start:  uvicorn action_broker.broker:app --port 8765 --host 127.0.0.1
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .priority import Priority

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
_LOG_DIR = _ROOT / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Logging ──────────────────────────────────────────────────────────────────
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=_LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_DIR / "broker.log"),
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
_queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
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
        # A game action is not idempotent. Never retry automatically: an
        # exception or timeout does not establish that no effects occurred.
        step_result = None
        last_exc: Exception | None = None
        uncertain = False
        step_future = loop.run_in_executor(_fle_executor, _fle_step, item.code)
        try:
            step_result = await asyncio.wait_for(asyncio.shield(step_future), timeout=item.timeout)
        except asyncio.TimeoutError:
            uncertain = True
            last_exc = TimeoutError(
                f"Action exceeded {item.timeout}s; execution may still complete. Not retried."
            )
            _results[item.action_id] = {
                "status": "error", "stderr": str(last_exc), "execution_uncertain": True,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }
            # Cancelling an asyncio wrapper cannot stop the blocking game call.
            # Drain it before taking another command so state access stays serial.
            try:
                completed = await asyncio.shield(step_future)
                if completed.get("observation"):
                    _game_state_cache.update(completed["observation"])
            except Exception:
                log.exception("Timed-out action eventually failed: %s", item.action_id)
        except Exception as exc:
            last_exc = exc
            uncertain = True
            log.exception("Action failed without retry: %s", item.action_id)

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
                "execution_uncertain": uncertain,
            }
            log.error("FAIL | action=%s error=%s elapsed=%dms", item.action_id, error_msg, elapsed_ms)

        _current_agent = "idle"
        _queue.task_done()


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    global _env, _queue, _start_time, _worker_task, _fle_executor
    global _results, _game_state_cache, _sequence_counter, _current_agent
    _start_time = time.time()
    capacity = int(os.getenv("MAX_QUEUE_DEPTH", "100"))
    if capacity <= 0:
        raise ValueError("MAX_QUEUE_DEPTH must be positive")
    _queue = asyncio.PriorityQueue(maxsize=capacity)
    _results = {}
    _game_state_cache = {}
    _sequence_counter = 0
    _current_agent = "idle"
    _fle_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fle-worker")

    # Initialise FLE in the dedicated executor thread
    loop = asyncio.get_running_loop()
    _env = await loop.run_in_executor(_fle_executor, _init_fle_env)

    # Start the single worker coroutine
    _worker_task = asyncio.create_task(_worker(), name="fle-worker")
    log.info("Action Broker ready on port 8765")

    try:
        yield
    finally:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task
        _fle_executor.shutdown(wait=False, cancel_futures=True)
        log.info("Action Broker shut down.")


app = FastAPI(title="Factorio Action Broker", lifespan=lifespan)


# ─── Request / Response models ────────────────────────────────────────────────
class ActionRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=128, description="Identifier of the submitting agent")
    priority: int = Field(Priority.NORMAL, ge=0, le=3, description="0=EMERGENCY … 3=LOW")
    code: str = Field(..., min_length=1, max_length=100_000, description="Python code to execute inside FLE")
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
    execution_uncertain: bool = False


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

    try:
        _queue.put_nowait(item)
    except asyncio.QueueFull as exc:
        raise HTTPException(status_code=429, detail="Action queue is full; no action was accepted") from exc
    _results[action_id] = {"status": "queued", "stdout": "", "stderr": "", "elapsed_ms": 0}

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
        execution_uncertain=data.get("execution_uncertain", False),
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
    uvicorn.run("action_broker.broker:app", host="127.0.0.1", port=8765, reload=False)
