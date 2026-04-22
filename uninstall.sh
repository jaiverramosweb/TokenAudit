#!/usr/bin/env bash
# TokenAudit — desinstalador.
#
# Uso:
#   ./uninstall.sh              -> quita instalación LOCAL (~/.claude/)
#   ./uninstall.sh --project    -> quita instalación PROYECTO (./.claude/)

set -euo pipefail

MODE="user"
for arg in "$@"; do
    case "$arg" in
        --project|-p) MODE="project" ;;
        -h|--help)
            echo "Uso: ./uninstall.sh [--project]"
            exit 0
            ;;
        *)
            echo "Argumento desconocido: $arg" >&2
            exit 1
            ;;
    esac
done

SKILL_NAME="token-usage"
if [ "${MODE}" = "project" ]; then
    BASE_DIR="$(pwd)/.claude"
    SCOPE_LABEL="proyecto ($(pwd))"
else
    BASE_DIR="${HOME}/.claude"
    SCOPE_LABEL="usuario (${HOME}/.claude)"
fi

TARGET_DIR="${BASE_DIR}/skills/${SKILL_NAME}"
SETTINGS_FILE="${BASE_DIR}/settings.json"

ok()   { printf "  \xE2\x9C\x94 %s\n" "$*"; }
warn() { printf "  ! %s\n" "$*"; }
err()  { printf "\nERROR: %s\n" "$*" >&2; exit 1; }

printf "\n=== TokenAudit :: desinstalando %s ===\n" "${SKILL_NAME}"
printf "    Modo: %s\n\n" "${SCOPE_LABEL}"

# ---- Python -----------------------------------------------------------------
PYTHON=""
for cmd in python python3 py; do
    if command -v "$cmd" >/dev/null 2>&1 \
       && "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
        PYTHON="$cmd"
        break
    fi
done
[ -n "${PYTHON}" ] || err "Python 3.8+ no encontrado."

# ---- borrar carpeta de la skill --------------------------------------------
if [ -d "${TARGET_DIR}" ]; then
    rm -rf "${TARGET_DIR}"
    ok "Eliminado ${TARGET_DIR}"
else
    warn "No existía ${TARGET_DIR} (nada para borrar)"
fi

# ---- quitar el hook del settings.json --------------------------------------
if [ -f "${SETTINGS_FILE}" ]; then
    "${PYTHON}" - "${SETTINGS_FILE}" <<'PYEOF'
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

settings_file = Path(sys.argv[1])
try:
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    print(f"\nERROR: {settings_file} tiene JSON inválido: {exc}", file=sys.stderr)
    sys.exit(1)

hooks = settings.get("hooks") or {}
post_tool_use = hooks.get("PostToolUse") or []
removed = 0

new_entries = []
for entry in post_tool_use:
    filtered_hooks = [
        h for h in entry.get("hooks", [])
        if "subagent_tokens_hook.py" not in (h.get("command") or "")
    ]
    removed += len(entry.get("hooks", [])) - len(filtered_hooks)
    if filtered_hooks:
        entry["hooks"] = filtered_hooks
        new_entries.append(entry)

if new_entries:
    hooks["PostToolUse"] = new_entries
elif "PostToolUse" in hooks:
    del hooks["PostToolUse"]

if hooks:
    settings["hooks"] = hooks
elif "hooks" in settings:
    del settings["hooks"]

settings_file.write_text(
    json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

if removed:
    print(f"  \u2714 Hook eliminado de {settings_file} ({removed} entrada(s))")
else:
    print(f"  ! No se encontró el hook en {settings_file} (ya estaba limpio)")
PYEOF
else
    warn "No existe ${SETTINGS_FILE}"
fi

cat <<EOF

=== Listo ===

Desinstalación completa. Reiniciá Claude Code para que deje de cargar el hook.

Nota: los archivos TOKEN_USAGE.md que la skill generó en tus proyectos siguen
ahí — son tuyos. Si los querés borrar, hacelo manualmente.

EOF
