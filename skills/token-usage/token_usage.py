#!/usr/bin/env python3
"""Aggregate Claude Code token usage from local JSONL transcripts.

In addition to printing/exporting, maintains a per-project
``TOKEN_USAGE.md`` registry inside each project's working directory.
The registry keeps lifetime totals, an all-time daily breakdown, and an
append-only query log so every run is recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
EXPORT_DIR = Path.home() / ".claude" / "token-usage"
REGISTRY_FILENAME = "TOKEN_USAGE.md"
LOG_MARKER_RE = re.compile(
    r"<!-- BEGIN:QUERY_LOG -->(.*?)<!-- END:QUERY_LOG -->", re.DOTALL
)
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
MAX_LOG_ENTRIES = 500
SESSIONS_LIMIT = 50


# ---------- transcript reading ---------------------------------------------


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


def collect_records():
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
                            and block.get("name") == "Task"
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


def record_usage(rec: dict):
    msg = rec.get("message") or {}
    usage = msg.get("usage") or {}
    if not usage:
        return None
    return {
        "timestamp": rec.get("timestamp"),
        "project": rec.get("_project"),
        "model": msg.get("model", "unknown"),
        "subagent_type": rec.get("_subagent_type", "main"),
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
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
    """Formato legible: '22/04/2026 10:45:01 AM' (fecha ES + reloj 12h)."""
    return dt.strftime("%d/%m/%Y %I:%M:%S %p")


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


# ---------- aggregation -----------------------------------------------------


def new_bucket():
    return {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0, "messages": 0}


def add_usage(bucket: dict, u: dict):
    bucket["input"] += u["input_tokens"]
    bucket["output"] += u["output_tokens"]
    bucket["cache_create"] += u["cache_creation_input_tokens"]
    bucket["cache_read"] += u["cache_read_input_tokens"]
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
            u = record_usage(rec)
            if not u:
                continue
            ts = parse_ts(u["timestamp"])
            if not ts:
                continue
        proj = rec.get("_project")

        cwd = rec.get("cwd")
        if cwd:
            prev = cwds.get(proj)
            if prev is None or ts > prev[0]:
                cwds[proj] = (ts, cwd)

        matches_project = not project_filter or project_filter.lower() in (proj or "").lower()

        sid = rec.get("sessionId")
        if sid and matches_project:
            sess = sessions_per_project[proj].setdefault(sid, new_session())
            if sess["first_ts"] is None or ts < sess["first_ts"]:
                sess["first_ts"] = ts
            if sess["last_ts"] is None or ts > sess["last_ts"]:
                sess["last_ts"] = ts

            if rec.get("type") == "user" and not rec.get("isSidechain"):
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
            key = (u["model"], u["subagent_type"])
            add_usage(all_time_per_project[proj][date_key][key], u)

        d = ts.date()
        if start and d < start:
            continue
        if end and d > end:
            continue
        if not matches_project:
            continue

        add_usage(per_day[d.isoformat()][(proj, u["model"], u["subagent_type"])], u)
        add_usage(totals, u)
        add_usage(per_project_filtered[proj], u)

    return {
        "per_day": per_day,
        "totals": totals,
        "per_project_filtered": per_project_filtered,
        "all_time_per_project": all_time_per_project,
        "sessions_per_project": sessions_per_project,
        "cwds": {k: v[1] for k, v in cwds.items()},
    }


# ---------- reporting -------------------------------------------------------


def print_report(per_day, totals, period):
    if not per_day:
        print(f"Sin datos de uso para el período: {period}")
        return
    print()
    print(f"Uso de tokens - período: {period}")
    print(f"Generado:      {fmt_human(datetime.now())}")
    print("=" * 138)
    for date_key in sorted(per_day):
        print(f"\n--- {date_key} (UTC) ---")
        header = (
            f"{'Proyecto':<42} {'Modelo':<22} {'Agente':<22} "
            f"{'Input':>12} {'Output':>12} {'CacheCr':>12} {'CacheRd':>12} {'Msjs':>6}"
        )
        print(header)
        print("-" * len(header))
        rows = sorted(
            per_day[date_key].items(),
            key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_create"]),
        )
        for (proj, model, sub), b in rows:
            print(
                f"{(proj or '')[:42]:<42} "
                f"{(model or '')[:22]:<22} "
                f"{(sub or '')[:22]:<22} "
                f"{b['input']:>12,} {b['output']:>12,} "
                f"{b['cache_create']:>12,} {b['cache_read']:>12,} "
                f"{b['messages']:>6,}"
            )
    print()
    print("=" * 138)
    billed = totals["input"] + totals["output"] + totals["cache_create"]
    print(
        f"TOTAL  input={totals['input']:,}  output={totals['output']:,}  "
        f"cache_create={totals['cache_create']:,}  cache_read={totals['cache_read']:,}  "
        f"mensajes={totals['messages']:,}"
    )
    print(f"Tokens FACTURADOS (input + output + cache_create): {billed:,}")


def build_payload(per_day, totals, period):
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": period,
        "totals": dict(totals),
        "per_day": {
            date_key: [
                {
                    "project": p,
                    "model": m,
                    "subagent_type": s,
                    "input_tokens": b["input"],
                    "output_tokens": b["output"],
                    "cache_creation_input_tokens": b["cache_create"],
                    "cache_read_input_tokens": b["cache_read"],
                    "messages": b["messages"],
                }
                for (p, m, s), b in sorted(
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


# ---------- per-project registry markdown -----------------------------------


def format_daily_totals_md(project_daily: dict) -> str:
    if not project_daily:
        return "_Aún no hay datos de uso._"
    lines = [
        "| Fecha (UTC) | Modelo | Agente | Input | Output | CacheCr | CacheRd | Msjs | Facturado |",
        "|-------------|--------|--------|------:|-------:|--------:|--------:|-----:|----------:|",
    ]
    for date_key in sorted(project_daily.keys(), reverse=True):
        rows = sorted(
            project_daily[date_key].items(),
            key=lambda x: -(x[1]["input"] + x[1]["output"] + x[1]["cache_create"]),
        )
        for (model, sub), b in rows:
            billed = b["input"] + b["output"] + b["cache_create"]
            lines.append(
                f"| {date_key} | `{model}` | `{sub}` | "
                f"{b['input']:,} | {b['output']:,} | "
                f"{b['cache_create']:,} | {b['cache_read']:,} | "
                f"{b['messages']:,} | {billed:,} |"
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
        "| Sesión | Título | Inicio | Duración | Msjs | Facturado | Reinicios |",
        "|--------|--------|--------|---------:|-----:|----------:|----------:|",
    ]
    for sid, s in items:
        title = (s["title"] or "_(sin título detectado)_").replace("|", "\\|")
        if len(title) > 80:
            title = title[:77] + "..."
        inicio = fmt_human(s["first_ts"].astimezone()) if s["first_ts"] else ""
        dur = human_duration(s["first_ts"], s["last_ts"])
        billed = s["tokens"]["input"] + s["tokens"]["output"] + s["tokens"]["cache_create"]
        lines.append(
            f"| `{sid[:8]}` | {title} | {inicio} | {dur} | "
            f"{s['tokens']['messages']:,} | {billed:,} | {s['resets']} |"
        )
    return "\n".join(lines)


def format_log_entry(ts: str, period: str, project_filter: str | None, b: dict) -> str:
    billed = b["input"] + b["output"] + b["cache_create"]
    filt = f", filtro=`{project_filter}`" if project_filter else ""
    return (
        f"- **{ts}** — período=`{period}`{filt} — "
        f"facturado=`{billed:,}` | input=`{b['input']:,}` | "
        f"output=`{b['output']:,}` | cache_create=`{b['cache_create']:,}` | "
        f"cache_read=`{b['cache_read']:,}` | mensajes=`{b['messages']:,}`"
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
    body = [
        f"# Registro de uso de tokens — `{project_name}`",
        "",
        f"_Autogenerado por `/token-usage`. Última actualización: {now}_",
        "",
        "> Todo lo que está entre los marcadores `<!-- BEGIN -->` / `<!-- END -->` se reescribe en cada corrida.",
        "> Las notas fuera de esos bloques se preservan — podés dejar comentarios ahí.",
        "",
        "## Totales históricos",
        "",
        f"- **Tokens facturados** (input + output + cache_create): `{billed:,}`",
        f"- Input: `{t['input']:,}`",
        f"- Output: `{t['output']:,}`",
        f"- Creación de caché: `{t['cache_create']:,}`",
        f"- Lectura de caché: `{t['cache_read']:,}`",
        f"- Mensajes: `{t['messages']:,}`",
        f"- Sesiones: `{len(project_sessions):,}`",
        "",
        "## Desglose diario",
        "",
        "<!-- BEGIN:DAILY_TOTALS -->",
        format_daily_totals_md(project_daily),
        "<!-- END:DAILY_TOTALS -->",
        "",
        f"## Sesiones (últimas {SESSIONS_LIMIT})",
        "",
        "> La columna **Reinicios** cuenta los mensajes de usuario con `parentUuid=null` después del primero.",
        "> Es una heurística: si `/clear` deja ese rastro, lo detecta; si no, siempre va a mostrar `0`.",
        "> La señal más fuerte de contexto optimizado es tener **muchas sesiones cortas con títulos claros** en vez de una sesión gigante.",
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


# ---------- main ------------------------------------------------------------


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description="Agregador de uso de tokens de Claude Code")
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

    if not PROJECTS_DIR.exists():
        print(f"No se encontró el directorio de transcripciones en {PROJECTS_DIR}", file=sys.stderr)
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

    ts_human = fmt_human(datetime.now())
    updated: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for proj, proj_totals in data["per_project_filtered"].items():
        cwd = data["cwds"].get(proj)
        if not cwd:
            skipped.append((proj, "cwd desconocido en las transcripciones"))
            continue
        daily = data["all_time_per_project"].get(proj, {})
        project_sessions = data["sessions_per_project"].get(proj, {})
        log_entry = format_log_entry(ts_human, args.period, args.project, proj_totals)
        md_path = update_registry_md(cwd, proj, daily, project_sessions, log_entry)
        if md_path:
            updated.append(md_path)
        else:
            skipped.append((proj, f"cwd no existe en disco: {cwd}"))

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
