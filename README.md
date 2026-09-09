# Factorio SAM Demo - Multi-Agent FLE Benchmark System

**Status: multi-agent integration prototype.** This repository explores coordination through Solace Agent Mesh, an MCP bridge, and a priority queue for actions in a shared Factorio world.

Start with [the action broker](action_broker/broker.py) and [the MCP bridge](mcp_server/factorio_mcp.py). Model access and a compatible, licensed Factorio/FLE installation are external requirements. Running agents can incur model charges.

No completed benchmark report or automated test suite is included in this checkout. Score targets and latency estimates below are development assumptions, not verified results from this system.


A multi-agent Factorio playing system built with **Solace Agent Mesh (SAM)**
and **LiteLLM**, targeting the FLE lab-play benchmark of **7/24 tasks** (best
published single-agent result) with a design goal of **15+ tasks**.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          SOLACE PUBSUB+ BROKER                          │
│                     (ws://localhost:8080, VPN: default)                 │
│                                                                          │
│  Topics:                                                                 │
│  factorio-demo/orchestrator/task            ← task runner input         │
│  factorio-demo/agents/{agent}/subtask       ← orchestrator → agent      │
│  factorio-demo/orchestrator/agent_report/>  ← agent → orchestrator      │
└──────────────────────┬─────────────────────────────────────────────────┘
                       │  Solace AMQP/SMF
         ┌─────────────┴──────────────────────────────────┐
         │           SAM AGENT PROCESSES                    │
         │                                                   │
         │  ┌─────────────────┐   ┌──────────────────────┐ │
         │  │  orchestrator   │◄──│  reflection_agent    │ │
         │  │  (Opus/Sonnet)  │   │  (error recovery)    │ │
         │  └────────┬────────┘   └──────────────────────┘ │
         │           │ assigns subtasks                      │
         │  ┌────────┼────────────────────────────┐         │
         │  ▼        ▼         ▼         ▼        │         │
         │ resource  blueprint  logistics  research │         │
         │  agent     agent      agent      agent   │         │
         └──────────┬────────────────────────────────┘
                    │  HTTP POST /tools/*
                    ▼
         ┌──────────────────────────────────────────┐
         │       MCP SERVER  :8766                   │
         │  (FastAPI, JSON-RPC + REST)               │
         │                                           │
         │  tools: get_game_state                    │
         │         execute_code        ─────────┐   │
         │         get_lab_tasks                 │   │
         │         get_few_shot_example          │   │
         │         get_task_progress             │   │
         └───────────────────────────────────────┼───┘
                                                 │ HTTP POST /action
                                                 ▼
         ┌────────────────────────────────────────────────────┐
         │        ACTION BROKER  :8765  (FastAPI)             │
         │                                                      │
         │  asyncio.PriorityQueue  (EMERGENCY→LOW)             │
         │  Single async worker  →  env.step(code)             │
         │  ThreadPoolExecutor(max_workers=1)                   │
         │  Exponential backoff retry (1s,2s,4s)               │
         │  Cached game state (updated after every step)       │
         └───────────────────────────────────────┬──────────────┘
                                                 │ Python call (blocked thread)
                                                 ▼
         ┌────────────────────────────────────────────────────┐
         │     FACTORIO LEARNING ENVIRONMENT (FLE)            │
         │     FactorioEnv(host=localhost, port=34197)        │
         │     env.step(python_code_string)                   │
         └────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
         ┌────────────────────────────────────────────────────┐
         │     FACTORIO GAME SERVER (headless)                │
         │     localhost:34197 (UDP/TCP)                      │
         └────────────────────────────────────────────────────┘
```

---

## Coordination hypotheses

| Problem with single agents | Our solution |
|---|---|
| Serial planning is slow | 5 specialist agents work in parallel |
| Code errors cascade and kill the run | `reflection_agent` analyses & fixes errors on every failure |
| One bad action corrupts game state | Action Broker serialises all writes, no race conditions |
| Agents forget working patterns | `get_few_shot_example()` injects verified code before each new category |
| Wasted tokens re-reading state | Cached `/game_state` is instant; agents read it freely |
| Research planning is ad hoc | `research_agent` owns the tech tree and monitors progress |

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10.16+ | `python --version` |
| Factorio game license | Required by FLE (headless server) |
| Docker or Podman | For the Solace broker |
| LiteLLM-compatible API key | OpenAI, Anthropic, Azure, etc. |

---

## Quick Start

### 1. Clone and set up

```bash
git clone <this-repo>
cd factorio-sam-demo
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in your LITELLM_API_KEY and other values
```

### 2. Start the Solace PubSub+ broker

```bash
docker run -d \
  -p 8080:8080 -p 55555:55555 -p 8008:8008 \
  -p 1883:1883 -p 5672:5672 -p 9000:9000 -p 2222:2222 \
  --shm-size=2g \
  --env username_admin_globalaccesslevel=admin \
  --env username_admin_password=admin \
  --name=solace solace/solace-pubsub-standard
```

Wait ~30 seconds, then verify: http://localhost:8080 (admin/admin)

### 3. Start the Factorio headless server

```bash
# Follow FLE setup instructions to install and start the headless server
# Typically:
./factorio --start-server my_save.zip --port 34197
```

### 4. Start the Action Broker

```bash
# In terminal 1
source .venv/bin/activate
uvicorn action_broker.broker:app --port 8765 --host 0.0.0.0
```

Verify: `curl http://localhost:8765/health`

### 5. Start the MCP Server

```bash
# In terminal 2
source .venv/bin/activate
uvicorn mcp_server.factorio_mcp:app --port 8766 --host 0.0.0.0
```

Verify: `curl http://localhost:8766/health`

### 6. Launch SAM Agents

```bash
# In terminal 3
source .venv/bin/activate
source .env   # or: export $(cat .env | xargs)

# Launch all agents (one process per agent, or use SAM CLI)
solace-agent-mesh run configs/sam_config.yaml

# OR launch agents individually:
sam run agents/orchestrator.yaml &
sam run agents/resource_agent.yaml &
sam run agents/blueprint_agent.yaml &
sam run agents/logistics_agent.yaml &
sam run agents/research_agent.yaml &
sam run agents/reflection_agent.yaml &
```

### 7. Submit a task to the orchestrator

```bash
# Publish a task via the Solace REST API
curl -X POST http://localhost:9000/TOPIC/${NAMESPACE}/orchestrator/task \
  -H "Content-Type: application/json" \
  -H "Solace-delivery-mode: direct" \
  -u admin:admin \
  -d '{"task_id": "gather_iron_ore", "run_all": false}'
```

To run all 24 lab-play tasks in sequence:
```bash
curl -X POST http://localhost:9000/TOPIC/${NAMESPACE}/orchestrator/task \
  -H "Content-Type: application/json" \
  -H "Solace-delivery-mode: direct" \
  -u admin:admin \
  -d '{"run_all": true, "strategy": "sequential_by_complexity"}'
```

---

## Service Reference

| Service | Port | Start command |
|---|---|---|
| Solace broker (Web UI) | 8080 | docker run (see above) |
| Solace broker (AMQP/SMF) | 55555 | (auto-started with broker) |
| Action Broker | 8765 | `uvicorn action_broker.broker:app --port 8765` |
| MCP Server | 8766 | `uvicorn mcp_server.factorio_mcp:app --port 8766` |
| Factorio game server | 34197 | `./factorio --start-server` |

### Action Broker API

| Endpoint | Method | Description |
|---|---|---|
| `/action` | POST | Queue a code action |
| `/result/{action_id}` | GET | Poll for result |
| `/health` | GET | Queue depth, current agent, uptime |
| `/game_state` | GET | Cached FLE observation (instant) |
| `/metrics` | GET | Result counts by status |

### MCP Server API

| Endpoint | Method | Description |
|---|---|---|
| `/mcp` | POST | MCP JSON-RPC 2.0 endpoint |
| `/tools/get_game_state` | POST | Current game state |
| `/tools/execute_code` | POST | Execute FLE code via broker |
| `/tools/get_lab_tasks` | POST | All 24 task definitions |
| `/tools/get_few_shot_example` | POST | Working code examples |
| `/tools/get_task_progress` | POST | Progress toward a task |
| `/health` | GET | MCP + broker health |

---

## Project Structure

```
factorio-sam-demo/
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
├── action_broker/
│   ├── broker.py             # FastAPI server with asyncio.PriorityQueue
│   ├── priority.py           # Priority enum (EMERGENCY→LOW)
│   └── client.py             # Thin async HTTP client for agents
├── mcp_server/
│   └── factorio_mcp.py       # MCP JSON-RPC + REST tool server
├── agents/
│   ├── orchestrator.yaml     # Master coordinator
│   ├── resource_agent.yaml   # Mining, smelting, crafting
│   ├── blueprint_agent.yaml  # Entity placement & layout
│   ├── logistics_agent.yaml  # Belts, inserters, power
│   ├── research_agent.yaml   # Science packs & research
│   └── reflection_agent.yaml # Error recovery
├── tasks/
│   └── lab_play_tasks.yaml   # 24 FLE lab-play task definitions
├── few_shot/
│   ├── mining.py             # Mine iron ore, coal, stone, copper
│   ├── smelting.py           # Smelt iron, copper, steel
│   ├── crafting.py           # Gear wheels, cables, circuits
│   ├── placement.py          # Drills, assemblers, electric poles
│   └── logistics.py          # Belts, inserters, steam power
├── configs/
│   └── sam_config.yaml       # SAM master config
└── logs/                     # Per-agent and broker log files
```

---

## Adding a New Agent

1. Copy an existing agent YAML (e.g., `agents/resource_agent.yaml`)
2. Change `component_name`, log file, subscription topics, and system prompt
3. Register the new agent in `configs/sam_config.yaml`
4. Start the agent: `sam run agents/my_new_agent.yaml`

---

## Topic Design

All topics follow the pattern:

```
{NAMESPACE}/{destination}/{message_type}
```

| Topic | Publisher | Subscriber |
|---|---|---|
| `factorio-demo/orchestrator/task` | Task runner / human | orchestrator |
| `factorio-demo/agents/{name}/subtask` | orchestrator | specialist agent |
| `factorio-demo/agents/reflection_agent/analyse` | orchestrator | reflection_agent |
| `factorio-demo/orchestrator/agent_report/{name}` | specialist agent | orchestrator |

---

## FLE Code Rules (IMPORTANT)

All code submitted via `execute_code` runs inside the FLE Python context.
The following globals are available:

```python
# Navigation
get_position()                       # → Position(x, y)
move_to(position: Position)

# Resources
get_resource_patches(resource: str, radius: float) → List[ResourcePatch]
harvest_resource(position: Position, quantity: int)

# Inventory
inspect_inventory(entity=None) → dict[str, int]
craft_item(prototype: Prototype, quantity: int)

# Entities
place_entity(prototype, position, direction) → Entity
get_entities(prototype=None, position=None, radius=None) → List[Entity]
insert_item(entity, prototype, quantity)
extract_item(entity, prototype, quantity)
set_entity_recipe(entity, recipe: str)

# Time / Research
sleep(seconds: float)
get_research_progress() → dict

# Imports available in context
from factorio_learning_environment.entities import Prototype, Direction, Position
```

---

## Troubleshooting

### Action Broker won't start
- Check `logs/broker.log`
- Ensure Factorio is running on port 34197 before starting the broker
- Verify FLE is installed: `python -c "from factorio_learning_environment.env import FactorioEnv"`

### Agents not receiving messages
- Verify Solace is running: `curl http://localhost:8080`
- Check SOLACE_* env vars match your broker config
- Look at Solace Web UI → Try Me! tab to publish test messages

### `Cannot place entity` errors
- This is the most common failure - the reflection_agent handles it
- Ensure blueprint_agent calls `get_game_state()` before placing to check for collisions

### LiteLLM 401 errors
- Verify `LITELLM_API_KEY` and `LITELLM_API_BASE` in `.env`
- Test: `litellm --test --model ${LITELLM_MODEL_ORCHESTRATOR}`

### Queue backed up (many pending actions)
- Check `/health` on the broker for `queue_depth`
- The single FLE worker may be stuck - check `broker.log` for timeout errors
- Restart the broker to clear stuck state

---

## Performance Notes

### Benchmark target
| System | Score |
|---|---|
| FLE baseline (rule-based) | 4/24 |
| Best published single agent | 7/24 |
| **This system (target)** | **15+/24** |

### Hypotheses to test
1. **Parallel specialization**: Resource, blueprint, logistics, and research work concurrently on independent subtasks of the same task.
2. **Error recovery loop**: The reflection_agent fixes code errors in-flight rather than failing the whole task.
3. **Few-shot injection**: Agents receive tested, working code patterns before generating new code, drastically reducing syntax and API errors.
4. **Prioritised queue**: EMERGENCY and HIGH priority actions from the orchestrator always run before background polling.
5. **Game state cache**: Agents can call `get_game_state()` without queuing an action, reducing latency for planning decisions.

### Latency profile
| Operation | Typical latency |
|---|---|
| `get_game_state()` (read) | <10 ms |
| Simple mining action | 2–5 s |
| Smelting (20 iron plates) | 70–90 s |
| Research (Automation) | 3–8 min (depends on science pack rate) |

---

## License

No standalone LICENSE file is included in this checkout. Confirm reuse terms before redistribution. Factorio requires a valid game license for FLE use.
