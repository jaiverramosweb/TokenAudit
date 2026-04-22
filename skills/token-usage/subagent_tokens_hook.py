#!/usr/bin/env python3
"""PostToolUse hook — reporta el uso de tokens de un sub-agente al main agent.

Registrado en `~/.claude/settings.json` bajo `hooks.PostToolUse` con
`matcher: "Agent|Task"`. Claude Code lo invoca después de cada delegación a un
sub-agente y pasa el payload por stdin.

Estrategia dual (porque distintos harnesses de Claude Code exponen el
consumo del sub-agente de forma distinta):

1. Si el `tool_response` trae un bloque `<usage>total_tokens: N ...</usage>`
   (formato observado en el harness con tool `Agent`), parsea esos
   números directamente.
2. Si no, cae al método clásico: lee el transcript JSONL, encuentra los
   registros `isSidechain: true` hijos del `tool_use_id`, suma
   `message.usage` (formato del Claude Code CLI estándar con tool `Task`).

Falla silencioso si algo sale mal — no rompe el flujo del main agent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_CHAIN_DEPTH = 1000
USAGE_BLOCK_RE = re.compile(
    r"<usage>\s*(?P<body>.*?)\s*</usage>", re.DOTALL
)


# ---------- hook I/O --------------------------------------------------------


def emit(additional_context: str | None = None) -> None:
    if not additional_context:
        sys.stdout.write("{}")
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": additional_context,
        }
    }
    sys.stdout.write(json.dumps(payload))


# ---------- strategy 1: parse <usage> from tool_response --------------------


def _collect_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        parts = []
        for item in obj:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", "") or "")
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(_collect_text(item))
        return "\n".join(parts)
    if isinstance(obj, dict):
        if "content" in obj:
            return _collect_text(obj["content"])
        if "text" in obj and isinstance(obj["text"], str):
            return obj["text"]
        return ""
    return ""


def parse_usage_block(text: str) -> dict | None:
    """Busca `<usage>...</usage>` y extrae claves `k: v` de su contenido."""
    if not text:
        return None
    m = USAGE_BLOCK_RE.search(text)
    if not m:
        return None
    body = m.group("body")
    fields = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields or None


# ---------- strategy 2: sum sidechain usage from JSONL ----------------------


def read_transcript(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records


def find_tool_use_message_uuid(records: list[dict], tool_use_id: str) -> str | None:
    for rec in records:
        msg = rec.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id") == tool_use_id
            ):
                return rec.get("uuid")
    return None


def chains_to(start_parent: str | None, target: str, uuid_parent: dict) -> bool:
    cur = start_parent
    for _ in range(MAX_CHAIN_DEPTH):
        if cur is None:
            return False
        if cur == target:
            return True
        cur = uuid_parent.get(cur)
    return False


def sum_sidechain_usage(records: list[dict], root_uuid: str) -> dict:
    totals = {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0, "messages": 0}
    uuid_parent = {r["uuid"]: r.get("parentUuid") for r in records if r.get("uuid")}
    for rec in records:
        if not rec.get("isSidechain"):
            continue
        if not chains_to(rec.get("parentUuid"), root_uuid, uuid_parent):
            continue
        usage = (rec.get("message") or {}).get("usage") or {}
        if not usage:
            continue
        totals["input"] += usage.get("input_tokens", 0) or 0
        totals["output"] += usage.get("output_tokens", 0) or 0
        totals["cache_create"] += usage.get("cache_creation_input_tokens", 0) or 0
        totals["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
        totals["messages"] += 1
    return totals


# ---------- formatting ------------------------------------------------------


def format_from_usage_block(
    subagent_type: str, description: str, fields: dict
) -> str | None:
    total = fields.get("total_tokens")
    if not total:
        return None
    desc = f" — {description}" if description else ""
    parts = [f"total_tokens={total}"]
    for key in ("tool_uses", "duration_ms"):
        if key in fields:
            parts.append(f"{key}={fields[key]}")
    return (
        f"[token-usage] Sub-agente `{subagent_type}`{desc}\n"
        f"  {' | '.join(parts)}"
    )


def format_from_sidechain_totals(
    subagent_type: str, description: str, totals: dict
) -> str | None:
    if totals["messages"] == 0:
        return None
    billed = totals["input"] + totals["output"] + totals["cache_create"]
    desc = f" — {description}" if description else ""
    return (
        f"[token-usage] Sub-agente `{subagent_type}`{desc}\n"
        f"  Mensajes: {totals['messages']:,} | "
        f"FACTURADOS: {billed:,} "
        f"(input={totals['input']:,} · output={totals['output']:,} · "
        f"cache_create={totals['cache_create']:,}) | "
        f"cache_read: {totals['cache_read']:,}"
    )


# ---------- main ------------------------------------------------------------


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        emit()
        return

    if payload.get("tool_name") not in ("Task", "Agent"):
        emit()
        return

    tool_input = payload.get("tool_input") or {}
    subagent_type = tool_input.get("subagent_type") or "unknown"
    description = (tool_input.get("description") or "").strip()

    # Strategy 1: parse <usage> block from tool_response
    response_text = _collect_text(payload.get("tool_response"))
    fields = parse_usage_block(response_text)
    if fields:
        ctx = format_from_usage_block(subagent_type, description, fields)
        if ctx:
            emit(ctx)
            return

    # Strategy 2: scan JSONL for sidechain usage
    tool_use_id = payload.get("tool_use_id")
    transcript_path = payload.get("transcript_path")
    if not tool_use_id or not transcript_path:
        emit()
        return
    transcript = Path(transcript_path)
    if not transcript.exists():
        emit()
        return
    records = read_transcript(transcript)
    if not records:
        emit()
        return
    root_uuid = find_tool_use_message_uuid(records, tool_use_id)
    if not root_uuid:
        emit()
        return
    totals = sum_sidechain_usage(records, root_uuid)
    ctx = format_from_sidechain_totals(subagent_type, description, totals)
    if ctx:
        emit(ctx)
    else:
        emit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit()
