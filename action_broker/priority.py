"""Priority levels for the Action Broker queue."""
from enum import IntEnum


class Priority(IntEnum):
    """Lower value = higher priority (asyncio.PriorityQueue is min-heap)."""

    EMERGENCY = 0  # Resource depletion, game-breaking errors
    HIGH = 1       # Orchestrator-commanded actions
    NORMAL = 2     # Standard agent actions
    LOW = 3        # Background monitoring, stats polling
