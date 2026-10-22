"""Check the local bridge without a game, broker or hosted model."""

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from mcp_server import factorio_mcp
from mcp_server.factorio_mcp import app


def test_tool_discovery_and_unknown_method():
    with TestClient(app) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert {"execute_code", "get_game_state", "get_lab_tasks"} <= names
        unknown = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "missing"})
        assert unknown.json()["error"]["code"] == -32601


def test_bad_json_is_reported():
    with TestClient(app) as client:
        response = client.post("/mcp", content="{bad", headers={"content-type": "application/json"})
        assert response.json()["error"]["code"] == -32700


def test_invalid_envelope_is_a_protocol_error():
    with TestClient(app) as client:
        for body in [[], {"method": "tools/list"}, {"jsonrpc": "2.0", "params": []}]:
            assert client.post("/mcp", json=body).json()["error"]["code"] == -32600


def test_execution_uncertainty_reaches_tool_caller(monkeypatch):
    monkeypatch.setattr(factorio_mcp.broker, "execute", AsyncMock(return_value={
        "status": "error", "stderr": "timeout", "execution_uncertain": True}))
    with TestClient(app) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                             "params": {"name": "execute_code", "arguments": {"code": "mutate()"}}})
    result = response.json()["result"]
    assert result["isError"]
    assert '"execution_uncertain": true' in result["content"][0]["text"]
