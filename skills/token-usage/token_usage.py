#!/usr/bin/env python3
"""Agregador unificado de uso de tokens (Claude Code + opencode).

Lee transcripts de ambas herramientas:
  - Claude Code: JSONL en ``~/.claude/projects/*/*.jsonl``
  - opencode:    SQLite en ``~/.local/share/opencode/opencode.db``

Produce una vista unificada con totales por día, proyecto, modelo y agente.
Mantiene un ``TOKEN_USAGE.md`` por proyecto (lifetime totals, desglose
diario, sesiones con títulos auto-detectados, historial de consultas).

Si una herramienta no está instalada, simplemente se omite.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- paths ------------------------------------------------------------------
PROJECTS_DIR = Path.home() / ".claude" / "projects"
OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
EXPORT_DIR = Path.home() / ".claude" / "token-usage"

REGISTRY_FILENAME = "TOKEN_USAGE.md"
LOG_MARKER_RE = re.compile(
    r"<!-- BEGIN:QUERY_LOG -->(.*?)<!-- END:QUERY_LOG -->", re.DOTALL
)
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
MAX_LOG_ENTRIES = 500
SESSIONS_LIMIT = 50


# =========================================================================
# Fuente 1: Claude Code (JSONL)
# =========================================================================


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def collect_records_claude_code():
    if not PROJECTS_DIR.exists():
        return
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        for jsonl_path in project_dir.glob("*.jsonl"):
            task_by_msg: dict[str, list[str]] = {}
            uuid_parent: dict[str, str | None] = {}
            records: list[dict] = []
            for rec in iter_jsonl(jsonl_path):
                rec["_project"] = project_name
                rec["_source"] = "claude-code"
                uid = rec.get("uuid")
                if uid:
                    uuid_parent[uid] = rec.get("parentUuid")
                msg = rec.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list) and not rec.get("isSidechain"):
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("name") in ("Task", "Agent")
                        ):
                            sub = (block.get("input") or {}).get("subagent_type") or "general-purpose"
                            task_by_msg.setdefault(uid, []).append(sub)
                records.append(rec)

            def attribute(rec: dict) -> str:
                cur = rec.get("parentUuid")
                seen = 0
                while cur and seen < 1000:
                    if cur in task_by_msg:
                        return task_by_msg[cur][0]
                    cur = uuid_parent.get(cur)
                    seen += 1
                return "unknown-subagent"

            for rec in records:
                rec["_subagent_type"] = attribute(rec) if rec.get("isSidechain") else "main"
                yield rec


# =========================================================================
# Fuente 2: opencode (SQLite)
# =========================================================================


def _opencode_connect():
    if not OPENCODE_DB.exists():
        return None
    try:
        uri = f"file:{OPENCODE_DB}?mode=ro&nolock=1&immutable=1"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None


def opencode_session_map() -> dict[str, dict]:
    """session_id -> {directory, title, parent_id, time_created, time_updated}."""
    con = _opencode_connect()
    if not con:
        return {}
    try:
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        return {
            row["id"]: dict(row)
            for row in cur.execute(
                "SELECT id, directory, title, parent_id, time_created, time_updated "
                "FROM session"
            )
        }
    finally:
        con.close()


def collect_records_opencode():
    """Emite records en shape compatible con Claude Code (fake JSONL)."""
    con = _opencode_connect()
    if not con:
        return
    try:
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        sessions = {}
        for s in cur.execute(
            "SELECT id, directory, title, parent_id, time_created "
            "FROM session"
        ):
            sessions[s["id"]] = dict(s)

        sql = (
            "SELECT p.data AS part_data, p.time_created AS ts, "
            "       p.session_id AS sid, p.message_id AS mid, "
            "       m.data AS message_data "
            "FROM part p JOIN message m ON p.message_id = m.id "
            "WHERE p.data LIKE '%\"type\":\"step-finish\"%' "
            "ORDER BY p.time_created"
        )
        for row in cur.execute(sql):
            try:
                part = json.loads(row["part_data"])
                msg = json.loads(row["message_data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if part.get("type") != "step-finish":
                continue

            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            cost = part.get("cost") or 0

            session = sessions.get(row["sid"]) or {}
            directory = session.get("directory") or ""

            # opencode guarda el modelo distinto según rol:
            #   user messages:      message.data.model = {providerID, modelID}
            #   assistant messages: message.data.providerID / modelID al nivel raíz
            model_nested = msg.get("model") or {}
            provider = msg.get("providerID") or model_nested.get("providerID") or "?"
            model_id = msg.get("modelID") or model_nested.get("modelID") or "?"
            model_label = f"{provider}/{model_id}" if provider != "?" or model_id != "?" else "opencode/unknown"

            agent = msg.get("agent") or "main"
            if session.get("parent_id"):
                agent = f"{agent}*"  # sub-agent marker

            project_label = Path(directory).name if directory else "unknown"

            ts_ms = row["ts"] or session.get("time_created")
            ts_iso = (
                datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
                if ts_ms
                else None
            )

            yield {
                "timestamp": ts_iso,
                "sessionId": row["sid"],
                "uuid": row["mid"],
                "parentUuid": None,
                "isSidechain": False,
                "cwd": directory,
                "type": "assistant",
                "message": {
                    "model": model_label,
                    "usage": {
                        "input_tokens": tokens.get("input", 0) or 0,
                        "output_tokens": tokens.get("output", 0) or 0,
                        "cache_creation_input_tokens": cache.get("write", 0) or 0,
                        "cache_read_input_tokens": cache.get("read", 0) or 0,
                        "_reasoning_tokens": tokens.get("reasoning", 0) or 0,
                        "_cost_usd": float(cost),
                    },
                },
                "_project": project_label,
                "_subagent_type": agent,
                "_source": "opencode",
            }
    finally:
        con.close()


# =========================================================================
# Fuente unificada
# =========================================================================


def collect_records():
    yield from collect_records_claude_code()
    yield from collect_records_opencode()


# =========================================================================
# Utilidades compartidas
# =========================================================================


def record_usage(rec: dict):
    msg = rec.get("message") or {}
    usage = msg.get("usage") or {}
    if not usage:
        return None
    return {
        "timestamp": rec.get("timestamp"),
        "project": rec.get("_project"),
        "source": rec.get("_source", "claude-code"),
        "model": msg.get("model", "unknown"),
        "subagent_type": rec.get("_subagent_type", "main"),
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "reasoning_tokens": usage.get("_reasoning_tokens", 0) or 0,
        "cost_usd": float(usage.get("_cost_usd", 0) or 0),
        "session_id": rec.get("sessionId"),
    }


def parse_ts(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_human(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %I:%M:%S %p")


def fmt_cost(v: float) -> str:
    return f"${v:.4f}"


def extract_user_text(msg: dict) -> str | None:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(parts) if parts else None
    return None


def is_tool_result_message(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return True
    return False


def clean_title(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = SYSTEM_REMINDER_RE.sub("", text).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def human_duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return ""
    total = int((end - start).total_seconds())
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def new_session():
    return {
        "title": None,
        "source": None,
        "parent_id": None,
        "first_ts": None,
        "last_ts": None,
        "tokens": new_bucket(),
        "resets": 0,
        "user_msg_count": 0,
    }


def date_range(period: str):
    today = datetime.now(timezone.utc).date()
    if period == "today":
        return today, today
    if period == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if period == "week":
        return today - timedelta(days=6), today
    if period == "month":
        return today - timedelta(days=29), today
    if period == "all":
        return None, None
    raise ValueError(f"unknown period: {period}")


# =========================================================================
# Agregación
# =========================================================================


def new_bucket():
    return {
        "input": 0,
        "output": 0,
        "cache_create": 0,
        "cache_read": 0,
        "reasoning": 0,
        "cost_usd": 0.0,
        "messages": 0,
    }


def add_usage(bucket: dict, u: dict):
    bucket["input"] += u["input_tokens"]
    bucket["output"] += u["output_tokens"]
    bucket["cache_create"] += u["cache_creation_input_tokens"]
    bucket["cache_read"] += u["cache_read_input_tokens"]
    bucket["reasoning"] += u.get("reasoning_tokens", 0)
    bucket["cost_usd"] += u.get("cost_usd", 0.0)
    bucket["messages"] += 1


def compute(period: str, project_filter: str | None):
    start, end = date_range(period)
    per_day = defaultdict(lambda: defaultdict(new_bucket))
    totals = new_bucket()
    per_project_filtered = defaultdict(new_bucket)
    all_time_per_project = defaultdict(lambda: defaultdict(lambda: defaultdict(new_bucket)))
    sessions_per_project: dict[str, dict[str, dict]] = defaultdict(dict)
    cwds: dict[str, tuple[datetime, str]] = {}

    for rec in collect_records():
        ts = parse_ts(rec.get("timestamp"))
        if not ts:
            continue
        proj = rec.get("_project")
        source = rec.get("_source", "claude-code")

        cwd = rec.get("cwd")
        if cwd:
            prev = cwds.get(proj)
            if prev is None or ts > prev[0]:
                cwds[proj] = (ts, cwd)

        matches_project = not project_filter or project_filter.lower() in (proj or "").lower()

        sid = rec.get("sessionId")
        if sid and matches_project:
            sess = sessions_per_project[proj].setdefault(sid, new_session())
            if sess["source"] is None:
                sess["source"] = source
            if sess["first_ts"] is None or ts < sess["first_ts"]:
                sess["first_ts"] = ts
            if sess["last_ts"] is None or ts > sess["last_ts"]:
                sess["last_ts"] = ts

            # Title / resets detection: solo para Claude Code (opencode se enriquece luego)
            if source == "claude-code" and rec.get("type") == "user" and not rec.get("isSidechain"):
                msg = rec.get("message") or {}
                if not is_tool_result_message(msg):
                    cleaned = clean_title(extract_user_text(msg))
                    if cleaned and not cleaned.startswith("/"):
                        if rec.get("parentUuid") is None and sess["user_msg_count"] > 0:
                            sess["resets"] += 1
                        sess["user_msg_count"] += 1
                        if sess["title"] is None and len(cleaned) > 5:
                            sess["title"] = cleaned[:120]

        u = record_usage(rec)
        if not u:
            continue

        if sid and matches_project:
            add_usage(sessions_per_project[proj][sid]["tokens"], u)

        if matches_project:
            date_key = ts.date().isoformat()
            group_key = (u["source"], u["model"], u["subagent_type"])
            add_usage(all_time_per_project[proj][date_key][group_key], u)

        d = ts.date()
        if start and d < start:
            continue
        if end and d > end:
            continue
        if not matches_project:
            continue

        add_usage(per_day[d.isoformat()][(proj, u["source"], u["model"], u["subagent_type"])], u)
        add_usage(totals, u)
        add_usage(per_project_filtered[proj], u)

    # Enriquecemos sesiones de opencode con title / parent_id del DB
    enrich_opencode_sessions(sessions_per_project)

    return {
        "per_day": per_day,
        "totals": totals,
        "per_project_filtered": per_project_filtered,
        "all_time_per_project": all_time_per_project,
        "sessions_per_project": sessions_per_project,
        "cwds": {k: v[1] for k, v in cwds.items()},
    }


def enrich_opencode_sessions(sessions_per_project: dict) -> None:
    """Completa title/parent_id para sesiones de opencode consultando la DB."""
    meta = opencode_session_map()
    if not meta:
        return
    for _, sessions in sessions_per_project.items():
        for sid, sess in sessions.items():
            if sess.get("source") != "opencode":
                continue
            m = meta.get(sid)
            if not m:
                continue
            if not sess.get("title"):
                title = (m.get("title") or "").strip()
                if title:
                    sess["title"] = title[:120]
            sess["parent_id"] = m.get("parent_id")


# =========================================================================
# Reporte consola
# =========================================================================


def print_report(per_day, totals, period):
    if not per_day:
        print(f"Sin datos de uso para el período: {period}")
        return
    print()
    print(f"Uso de tokens - período: {period}")
    print(f"Generado:      {fmt_human(datetime.now())}")
    print("=" * 148)
    for date_key in sorted(per_day):
        print(f"\n--- {date_key} (UTC) ---")
        header = (
            f"{'Proyecto':<34} {'Src':<5} {'Modelo':<24} {'Agente':<20} "
            f"{'Input':>11} {'Output':>11} {'CacheCr':>11} {'CacheRd':>11} "
            f"{'Msjs':>5} {'Costo':>10}"
        )
        print(header)
        print("-" * len(header))
        rows = sorted(
            per_day[date_key].items(),
            key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_create"]),
        )
        for (proj, source, model, sub), b in rows:
            src_short = "CC" if source == "claude-code" else "OC"
            print(
                f"{(proj or '')[:34]:<34} {src_short:<5} "
                f"{(model or '')[:24]:<24} {(sub or '')[:20]:<20} "
                f"{b['input']:>11,} {b['output']:>11,} "
                f"{b['cache_create']:>11,} {b['cache_read']:>11,} "
                f"{b['messages']:>5,} {fmt_cost(b['cost_usd']):>10}"
            )
    print()
    print("=" * 148)
    billed = totals["input"] + totals["output"] + totals["cache_create"]
    print(
        f"TOTAL  input={totals['input']:,}  output={totals['output']:,}  "
        f"cache_create={totals['cache_create']:,}  cache_read={totals['cache_read']:,}  "
        f"reasoning={totals['reasoning']:,}  mensajes={totals['messages']:,}"
    )
    print(f"Tokens FACTURADOS (input + output + cache_create): {billed:,}")
    print(f"Costo total estimado (opencode reporta USD; Claude Code = 0): {fmt_cost(totals['cost_usd'])}")


def build_payload(per_day, totals, period):
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": period,
        "totals": dict(totals),
        "per_day": {
            date_key: [
                {
                    "project": p,
                    "source": src,
                    "model": m,
                    "subagent_type": s,
                    "input_tokens": b["input"],
                    "output_tokens": b["output"],
                    "cache_creation_input_tokens": b["cache_create"],
                    "cache_read_input_tokens": b["cache_read"],
                    "reasoning_tokens": b["reasoning"],
                    "cost_usd": round(b["cost_usd"], 6),
                    "messages": b["messages"],
                }
                for (p, src, m, s), b in sorted(
                    per_day[date_key].items(),
                    key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_create"]),
                )
            ]
            for date_key in sorted(per_day)
        },
    }


def export_json(per_day, totals, period):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(per_day, totals, period)
    snapshot_path = EXPORT_DIR / f"snapshot-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for date_key, rows in payload["per_day"].items():
        daily_path = EXPORT_DIR / f"daily-{date_key}.json"
        daily_path.write_text(
            json.dumps({"date": date_key, "entries": rows}, indent=2),
            encoding="utf-8",
        )
    print(f"\nSnapshot          -> {snapshot_path}")
    print(f"Resúmenes diarios -> {EXPORT_DIR}{Path('/').anchor or ''}daily-*.json")


# =========================================================================
# Registro markdown por proyecto
# =========================================================================


def format_daily_totals_md(project_daily: dict) -> str:
    if not project_daily:
        return "_Aún no hay datos de uso._"
    lines = [
        "| Fecha (UTC) | Src | Modelo | Agente | Input | Output | CacheCr | CacheRd | Msjs | Facturado | Costo USD |",
        "|-------------|-----|--------|--------|------:|-------:|--------:|--------:|-----:|----------:|----------:|",
    ]
    for date_key in sorted(project_daily.keys(), reverse=True):
        rows = sorted(
            project_daily[date_key].items(),
            key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_create"]),
        )
        for (source, model, sub), b in rows:
            billed = b["input"] + b["output"] + b["cache_create"]
            src_short = "CC" if source == "claude-code" else "OC"
            lines.append(
                f"| {date_key} | `{src_short}` | `{model}` | `{sub}` | "
                f"{b['input']:,} | {b['output']:,} | "
                f"{b['cache_create']:,} | {b['cache_read']:,} | "
                f"{b['messages']:,} | {billed:,} | {fmt_cost(b['cost_usd'])} |"
            )
    return "\n".join(lines)


def format_sessions_md(sessions: dict, limit: int = SESSIONS_LIMIT) -> str:
    if not sessions:
        return "_Aún no hay sesiones._"
    items = sorted(
        sessions.items(),
        key=lambda kv: kv[1]["last_ts"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:limit]
    lines = [
        "| Sesión | Src | Título | Inicio | Duración | Msjs | Facturado | Costo USD | Reinicios |",
        "|--------|-----|--------|--------|---------:|-----:|----------:|----------:|----------:|",
    ]
    for sid, s in items:
        title_raw = s["title"] or "_(sin título detectado)_"
        if s.get("parent_id"):
            title_raw = "↳ " + title_raw
        title = title_raw.replace("|", "\\|")
        if len(title) > 70:
            title = title[:67] + "..."
        src = "CC" if s.get("source") == "claude-code" else "OC"
        inicio = fmt_human(s["first_ts"].astimezone()) if s["first_ts"] else ""
        dur = human_duration(s["first_ts"], s["last_ts"])
        billed = s["tokens"]["input"] + s["tokens"]["output"] + s["tokens"]["cache_create"]
        cost = fmt_cost(s["tokens"]["cost_usd"])
        lines.append(
            f"| `{sid[:8]}` | `{src}` | {title} | {inicio} | {dur} | "
            f"{s['tokens']['messages']:,} | {billed:,} | {cost} | {s['resets']} |"
        )
    return "\n".join(lines)


def format_log_entry(ts: str, period: str, project_filter: str | None, b: dict) -> str:
    billed = b["input"] + b["output"] + b["cache_create"]
    filt = f", filtro=`{project_filter}`" if project_filter else ""
    return (
        f"- **{ts}** — período=`{period}`{filt} — "
        f"facturado=`{billed:,}` | costo=`{fmt_cost(b['cost_usd'])}` | "
        f"input=`{b['input']:,}` | output=`{b['output']:,}` | "
        f"cache_create=`{b['cache_create']:,}` | cache_read=`{b['cache_read']:,}` | "
        f"mensajes=`{b['messages']:,}`"
    )


def lifetime_totals(project_daily: dict) -> dict:
    t = new_bucket()
    for _, rows in project_daily.items():
        for _, b in rows.items():
            for k in t:
                t[k] += b[k]
    return t


def build_registry_content(
    project_name: str,
    project_daily: dict,
    project_sessions: dict,
    log_entries: list[str],
) -> str:
    now = fmt_human(datetime.now())
    t = lifetime_totals(project_daily)
    billed = t["input"] + t["output"] + t["cache_create"]
    # Contar sesiones por source
    sources_count = defaultdict(int)
    for s in project_sessions.values():
        sources_count[s.get("source") or "claude-code"] += 1
    src_summary = " · ".join(
        f"{k}={v}" for k, v in sorted(sources_count.items())
    ) or "—"
    body = [
        f"# Registro de uso de tokens — `{project_name}`",
        "",
        f"_Autogenerado por `/token-usage`. Última actualización: {now}_",
        "",
        "> Todo lo que está entre los marcadores `<!-- BEGIN -->` / `<!-- END -->` se reescribe en cada corrida.",
        "> Las notas fuera de esos bloques se preservan — podés dejar comentarios ahí.",
        "",
        "## Totales históricos (Claude Code + opencode)",
        "",
        f"- **Tokens facturados** (input + output + cache_create): `{billed:,}`",
        f"- **Costo estimado**: `{fmt_cost(t['cost_usd'])}` "
        f"_(opencode reporta USD; Claude Code suma 0 — agregar pricing por modelo es un TODO)_",
        f"- Input: `{t['input']:,}`",
        f"- Output: `{t['output']:,}`",
        f"- Reasoning: `{t['reasoning']:,}`",
        f"- Creación de caché: `{t['cache_create']:,}`",
        f"- Lectura de caché: `{t['cache_read']:,}`",
        f"- Mensajes: `{t['messages']:,}`",
        f"- Sesiones: `{len(project_sessions):,}` ({src_summary})",
        "",
        "## Desglose diario",
        "",
        "<!-- BEGIN:DAILY_TOTALS -->",
        format_daily_totals_md(project_daily),
        "<!-- END:DAILY_TOTALS -->",
        "",
        f"## Sesiones (últimas {SESSIONS_LIMIT})",
        "",
        "> **Src**: `CC` = Claude Code, `OC` = opencode.",
        "> **↳** indica sub-agente delegado (opencode usa `session.parent_id`).",
        "> **Reinicios**: heurística de `parentUuid=null` en user messages — solo aplica a Claude Code.",
        "> La señal más fuerte de contexto optimizado es **muchas sesiones cortas con títulos claros** en vez de una gigante.",
        "",
        "<!-- BEGIN:SESSIONS -->",
        format_sessions_md(project_sessions),
        "<!-- END:SESSIONS -->",
        "",
        "## Historial de consultas",
        "",
        "<!-- BEGIN:QUERY_LOG -->",
        "\n".join(log_entries) if log_entries else "_Aún no hay consultas._",
        "<!-- END:QUERY_LOG -->",
        "",
    ]
    return "\n".join(body)


def update_registry_md(
    cwd_str: str,
    project_name: str,
    project_daily: dict,
    project_sessions: dict,
    log_entry: str,
):
    try:
        cwd = Path(cwd_str)
    except (ValueError, OSError):
        return None
    if not cwd.exists() or not cwd.is_dir():
        return None
    md_path = cwd / REGISTRY_FILENAME

    existing_log: list[str] = []
    if md_path.exists():
        try:
            existing = md_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        m = LOG_MARKER_RE.search(existing)
        if m:
            raw = m.group(1).strip()
            if raw and raw not in ("_No queries yet._", "_Aún no hay consultas._"):
                existing_log = [ln for ln in raw.splitlines() if ln.strip()]

    existing_log.append(log_entry)
    if len(existing_log) > MAX_LOG_ENTRIES:
        existing_log = existing_log[-MAX_LOG_ENTRIES:]

    try:
        md_path.write_text(
            build_registry_content(project_name, project_daily, project_sessions, existing_log),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"No se pudo escribir {md_path}: {exc}", file=sys.stderr)
        return None
    return md_path


# =========================================================================
# main
# =========================================================================


def _project_cwd_matches(session_cwd: str, target_cwd: Path) -> bool:
    if not session_cwd:
        return False
    try:
        return Path(session_cwd).resolve() == target_cwd.resolve()
    except (OSError, ValueError):
        return False


def group_projects_by_cwd(data: dict) -> dict[Path, dict]:
    """Une proyectos que apuntan al mismo cwd (Claude Code + opencode).

    Devuelve {resolved_cwd: {
        'label': nombre legible,
        'daily': {...},
        'sessions': {...},
        'totals': bucket filtered,
    }}
    """
    grouped: dict[Path, dict] = {}
    cwds = data["cwds"]
    for proj, cwd_str in cwds.items():
        if not cwd_str:
            continue
        try:
            key = Path(cwd_str).resolve()
        except (OSError, ValueError):
            continue
        entry = grouped.setdefault(
            key,
            {
                "label": key.name,
                "daily": defaultdict(lambda: defaultdict(new_bucket)),
                "sessions": {},
                "totals": new_bucket(),
            },
        )
        # merge daily
        for date_key, row_dict in data["all_time_per_project"].get(proj, {}).items():
            for group_key, bucket in row_dict.items():
                dest = entry["daily"][date_key][group_key]
                for k in dest:
                    dest[k] += bucket[k]
        # merge sessions
        entry["sessions"].update(data["sessions_per_project"].get(proj, {}))
        # merge totals (filtered, already respects period)
        src_totals = data["per_project_filtered"].get(proj)
        if src_totals:
            for k in entry["totals"]:
                entry["totals"][k] += src_totals[k]
    return grouped


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(
        description="Agregador unificado de uso de tokens (Claude Code + opencode)"
    )
    parser.add_argument(
        "--period", "-p",
        default="today",
        choices=["today", "yesterday", "week", "month", "all"],
        help="ventana de tiempo (UTC)",
    )
    parser.add_argument("--project", help="filtrar por substring del nombre del proyecto")
    parser.add_argument(
        "--export", action="store_true",
        help="escribe snapshot + resúmenes diarios en ~/.claude/token-usage/",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="imprime JSON en stdout en vez de la tabla",
    )
    parser.add_argument(
        "--no-registry", action="store_true",
        help="omitir la actualización del TOKEN_USAGE.md por proyecto",
    )
    args = parser.parse_args()

    if not PROJECTS_DIR.exists() and not OPENCODE_DB.exists():
        print(
            "No se encontraron datos ni de Claude Code (~/.claude/projects) "
            "ni de opencode (~/.local/share/opencode/opencode.db)",
            file=sys.stderr,
        )
        sys.exit(1)

    data = compute(args.period, args.project)
    per_day = data["per_day"]
    totals = data["totals"]

    if args.json:
        print(json.dumps(build_payload(per_day, totals, args.period), indent=2))
    else:
        print_report(per_day, totals, args.period)

    if args.export:
        export_json(per_day, totals, args.period)

    if args.no_registry:
        return

    # Agrupamos por cwd real — un solo TOKEN_USAGE.md por proyecto físico,
    # aunque haya datos de Claude Code Y opencode mezclados.
    grouped = group_projects_by_cwd(data)
    ts_human = fmt_human(datetime.now())
    updated: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for cwd_path, info in grouped.items():
        if info["totals"]["messages"] == 0:
            continue  # sin actividad en el período → no tocar su .md
        if not cwd_path.exists() or not cwd_path.is_dir():
            skipped.append((info["label"], f"cwd no existe en disco: {cwd_path}"))
            continue
        log_entry = format_log_entry(ts_human, args.period, args.project, info["totals"])
        md_path = update_registry_md(
            str(cwd_path), info["label"], info["daily"], info["sessions"], log_entry
        )
        if md_path:
            updated.append(md_path)
        else:
            skipped.append((info["label"], f"no se pudo escribir en {cwd_path}"))

    if not args.json:
        if updated:
            print("\nRegistro actualizado:")
            for p in updated:
                print(f"  - {p}")
        if skipped:
            print("\nRegistro omitido:")
            for proj, reason in skipped:
                print(f"  - {proj} ({reason})")


if __name__ == "__main__":
    main()
