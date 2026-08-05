from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._lock = threading.Lock()

    def emit(
        self,
        case_id: str,
        agent: str,
        event: str,
        *,
        handoff_to: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "agent": agent,
            "event": event,
        }
        if handoff_to:
            record["handoff_to"] = handoff_to
        if details:
            record["details"] = details
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")

