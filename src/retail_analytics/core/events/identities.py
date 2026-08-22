"""Deterministic event identity helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def event_identity(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def stable_json(payload: object) -> str:
    return json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
