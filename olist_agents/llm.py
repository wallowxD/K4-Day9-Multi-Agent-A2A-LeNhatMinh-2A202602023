from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import MODEL_NAME


class ModelUnavailableError(RuntimeError):
    pass


@dataclass
class LlamaRuntime:
    """Minimal Ollama client used for bounded semantic review at each handoff."""

    model: str = MODEL_NAME
    host: str = "http://127.0.0.1:11434"
    mode: str = "auto"  # auto, required, off
    timeout_seconds: int = 60
    _unavailable_reason: str | None = None
    calls: int = 0
    completed_calls: int = 0
    failed_calls: int = 0

    def review(self, agent_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "off":
            return {"status": "disabled", "model": self.model}
        self.calls += 1
        if self._unavailable_reason and self.mode == "auto":
            self.failed_calls += 1
            return {"status": "unavailable", "model": self.model, "reason": self._unavailable_reason}

        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        prompt = (
            "You are the semantic reviewer inside an e-commerce dispute agent. "
            "Never change amounts, timestamps, IDs, or policy rules. Review the structured handoff "
            f"from {agent_name}. Return only whether the handoff is internally consistent. "
            f"Handoff: {compact}"
        )
        body = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": {
                    "type": "object",
                    "properties": {"validated": {"type": "boolean"}},
                    "required": ["validated"],
                    "additionalProperties": False,
                },
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0, "num_predict": 16},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = raw.get("message", {}).get("content", "{}")
            try:
                review = json.loads(content)
            except json.JSONDecodeError:
                review = {"validated": None, "parse_status": "unstructured_model_response"}
            self.completed_calls += 1
            return {"status": "completed", "model": self.model, "review": review}
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self._unavailable_reason = reason
            self.failed_calls += 1
            if self.mode == "required":
                raise ModelUnavailableError(
                    f"Cannot call required model {self.model} at {self.host}: {reason}"
                ) from exc
            return {"status": "unavailable", "model": self.model, "reason": reason}
