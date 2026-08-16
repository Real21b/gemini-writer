"""
The event stream produced by an agent run.

The runner never prints. It yields events, and every interface - the CLI
renderer today, the SSE endpoint in phase 2 - is just a different consumer of
this stream. Events carry a monotonic ``seq`` so a client can resume from
``Last-Event-ID`` without gaps or duplicates.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    ITERATION_STARTED = "iteration.started"

    THINKING_DELTA = "thinking.delta"
    TEXT_DELTA = "text.delta"

    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    FILE_WRITTEN = "file.written"

    USAGE_UPDATED = "usage.updated"
    CONTEXT_COMPRESSED = "context.compressed"
    SNAPSHOT_SAVED = "snapshot.saved"

    WARNING = "warning"
    RUN_NEEDS_INPUT = "run.needs_input"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


TERMINAL_EVENTS = frozenset(
    {EventType.RUN_COMPLETED, EventType.RUN_FAILED, EventType.RUN_NEEDS_INPUT}
)


@dataclass
class Event:
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts.isoformat(),
            "type": self.type.value,
            "data": self.data,
        }


class EventEmitter:
    """Stamps events with an increasing sequence number."""

    def __init__(self) -> None:
        self._seq = 0

    def emit(self, event_type: EventType, **data: Any) -> Event:
        self._seq += 1
        return Event(type=event_type, data=data, seq=self._seq)
