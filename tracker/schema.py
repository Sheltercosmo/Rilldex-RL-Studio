"""Canonical observations retain pointers into immutable source documents."""
from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "jev-trace/1"


class InputError(ValueError):
    pass


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def content_text(value: Any) -> tuple[str, list[dict]]:
    """Do not pretend a referenced image/audio was observed by a text inspector."""
    if value is None:
        return "", []
    if isinstance(value, str):
        return value, []
    if isinstance(value, list):
        texts, media = [], []
        for part in value:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text", "")))
            elif isinstance(part, dict):
                media.append(part)
        return "\n".join(texts), media
    raise InputError("Content must be text or a list of content parts")


def event(events: list, *, kind: str, text: str, pointer: str, actor: str = "agent", **extra) -> dict:
    result = {"id": f"e{len(events) + 1}", "index": len(events), "kind": kind,
              "actor": actor, "text": text, "source_pointer": pointer, **extra}
    events.append(result)
    return result


def metadata(values: dict | None) -> dict:
    values = dict(values or {})
    for key in ("checkpoint", "task_id", "environment", "environment_version", "experiment", "split", "seed"):
        if values.get(key) is not None:
            values[key] = str(values[key])
    if values.get("training_step") is not None:
        if isinstance(values["training_step"], bool) or not isinstance(values["training_step"], int):
            raise InputError("training_step must be an integer or null")
    return values

