"""Offline checks of the real action broker with a fake game environment."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import threading
import time

from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest

from action_broker import broker


class FakeGame:
    def step(self, code):
        return ({"last_code": code}, 1.0, False, False, {"stdout": code})


def test_http_lifecycle_and_request_validation(monkeypatch):
    monkeypatch.setattr(broker, "_init_fle_env", lambda: FakeGame())
    for _ in range(2):
        with TestClient(broker.app) as client:
            assert client.get("/health").json()["fle_ready"]
            assert client.get("/health").json()["total_actions_seen"] == 0
            assert client.get("/result/missing").status_code == 404
            for invalid in [{"code": ""}, {"priority": 4}, {"timeout": 0}]:
                payload = dict(agent_id="test", code="inspect()", **{})
                payload.update(invalid)
                assert client.post("/action", json=payload).status_code == 422
            response = client.post("/action", json={"agent_id": "test", "code": "inspect()"})
            assert response.status_code == 200
            action_id = response.json()["action_id"]
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result = client.get(f"/result/{action_id}").json()
                if result["status"] == "done":
                    break
                time.sleep(0.005)
            assert result["status"] == "done"
            assert result["stdout"] == "inspect()"
            assert client.get("/game_state").json()["last_code"] == "inspect()"


async def exercise(monkeypatch, step, requests):
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(broker, "_fle_executor", executor)
    monkeypatch.setattr(broker, "_queue", asyncio.PriorityQueue())
    monkeypatch.setattr(broker, "_results", {})
    monkeypatch.setattr(broker, "_game_state_cache", {})
    monkeypatch.setattr(broker, "_fle_step", step)
    responses = [await broker.submit_action(broker.ActionRequest(**request)) for request in requests]
    worker = asyncio.create_task(broker._worker())
    try:
        await asyncio.wait_for(broker._queue.join(), timeout=4)
        return [broker._results[response.action_id] for response in responses]
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        executor.shutdown(wait=True)


def result(code):
    return dict(stdout=code, stderr="", observation={"last": code}, reward=0, done=False)


def test_priority_and_fifo_order(monkeypatch):
    seen = []
    def step(code):
        seen.append(code)
        return result(code)
    requests = [dict(agent_id="test", code=code, priority=priority)
                for code, priority in [("low", 3), ("normal-a", 2), ("urgent", 0), ("normal-b", 2)]]
    results = asyncio.run(exercise(monkeypatch, step, requests))
    assert seen == ["urgent", "normal-a", "normal-b", "low"]
    assert all(row["status"] == "done" for row in results)


def test_failed_action_is_never_retried_and_worker_continues(monkeypatch):
    seen = []
    def step(code):
        seen.append(code)
        if code == "mutate_then_fail":
            raise RuntimeError("failure after possible side effect")
        return result(code)
    rows = asyncio.run(exercise(monkeypatch, step, [
        dict(agent_id="test", code="mutate_then_fail"), dict(agent_id="test", code="next")]))
    assert seen == ["mutate_then_fail", "next"]
    assert rows[0]["status"] == "error"
    assert rows[0]["execution_uncertain"]
    assert rows[1]["status"] == "done"


def test_timeout_does_not_repeat_or_overlap_execution(monkeypatch):
    seen = []
    running = threading.Event()
    def step(code):
        assert not running.is_set()
        running.set()
        seen.append(code)
        try:
            if code == "slow":
                time.sleep(1.1)
            return result(code)
        finally:
            running.clear()
    rows = asyncio.run(exercise(monkeypatch, step, [
        dict(agent_id="test", code="slow", timeout=1), dict(agent_id="test", code="next")]))
    assert seen == ["slow", "next"]
    assert rows[0]["status"] == "error"
    assert rows[0]["execution_uncertain"]
    assert rows[1]["status"] == "done"
    assert broker._game_state_cache["last"] == "next"


@pytest.mark.parametrize("raw,expected", [
    (({"x": 1}, 2, False, {"stdout": "ok"}), False),
    (({"x": 1}, 2, False, True, {"stdout": "ok"}), True),
])
def test_gym_result_normalization(monkeypatch, raw, expected):
    game = FakeGame()
    game.step = lambda code: raw
    monkeypatch.setattr(broker, "_env", game)
    assert broker._fle_step("test")["done"] is expected


def test_full_queue_rejects_before_creating_a_result(monkeypatch):
    async def scenario():
        monkeypatch.setattr(broker, "_queue", asyncio.PriorityQueue(maxsize=1))
        monkeypatch.setattr(broker, "_results", {})
        request = broker.ActionRequest(agent_id="test", code="mutate()")
        await broker.submit_action(request)
        with pytest.raises(HTTPException) as error:
            await broker.submit_action(request)
        assert error.value.status_code == 429
        assert len(broker._results) == 1
    asyncio.run(scenario())
