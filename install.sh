#!/usr/bin/env bash
# TokenAudit — instalador de skills para agentes de IA.
#
# Uso:
#   ./install.sh              -> modo LOCAL (global al usuario, en ~/.claude/)
#   ./install.sh --project    -> modo PROYECTO (scoped al directorio actual)
#   ./install.sh -h           -> ayuda
#
# Funciona en Windows (Git Bash), macOS y Linux.

set -euo pipefail

# ---- args -------------------------------------------------------------------
MODE="user"
for arg in "$@"; do
    case "$arg" in
        --project|-p)
            MODE="project"
            ;;
        -h|--help)
            cat <<'HELP'
TokenAudit — instalador

  ./install.sh              Instala global al usuario (~/.claude/).
                            Aplica a TODOS los proyectos del usuario.
  ./install.sh --project    Instala scoped al directorio actual (./.claude/).
                            Aplica solo a ESE proyecto.

Idempotente: podés correrlo más de una vez sin duplicar nada.
HELP
            exit 0
            ;;
        *)
            echo "Argumento desconocido: $arg" >&2
            echo "Usá ./install.sh --help" >&2
            exit 1
            ;;
    esac
done

# ---- paths según modo -------------------------------------------------------
SKILL_NAME="token-usage"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${REPO_ROOT}/skills/${SKILL_NAME}"

if [ "${MODE}" = "project" ]; then
    BASE_DIR="$(pwd)/.claude"
    HOOK_COMMAND_PATH='${CLAUDE_PROJECT_DIR}/.claude/skills/token-usage/subagent_tokens_hook.py'
    SCOPE_LABEL="proyecto ($(pwd))"
else
    BASE_DIR="${HOME}/.claude"
    HOOK_COMMAND_PATH='$HOME/.claude/skills/token-usage/subagent_tokens_hook.py'
    SCOPE_LABEL="usuario (${HOME}/.claude)"
fi

TARGET_DIR="${BASE_DIR}/skills/${SKILL_NAME}"
SETTINGS_FILE="${BASE_DIR}/settings.json"

# ---- helpers ----------------------------------------------------------------
ok()   { printf "  \xE2\x9C\x94 %s\n" "$*"; }
warn() { printf "  ! %s\n" "$*"; }
err()  { printf "\nERROR: %s\n" "$*" >&2; exit 1; }
info() { printf "    %s\n" "$*"; }

printf "\n=== TokenAudit :: instalando %s ===\n" "${SKILL_NAME}"
printf "    Modo: %s\n\n" "${SCOPE_LABEL}"

# ---- detectar Python 3.8+ ---------------------------------------------------
PYTHON=""
check_python() {
    local cmd="$1"
    if command -v "$cmd" >/dev/null 2>&1; then
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
            PYTHON="$cmd"
            return 0
        fi
    fi
    return 1
}

check_python python || check_python python3 || check_python py || true

if [ -z "${PYTHON}" ]; then
    err "Python 3.8+ no encontrado en el PATH. Instalalo desde https://www.python.org/downloads/ y marcá 'Add Python to PATH'."
fi

ok "Python detectado: $(${PYTHON} --version 2>&1) (comando: ${PYTHON})"

# ---- verificar archivos fuente ---------------------------------------------
for f in SKILL.md token_usage.py subagent_tokens_hook.py; do
    [ -f "${SOURCE_DIR}/${f}" ] || err "Archivo faltante: ${SOURCE_DIR}/${f}"
done
ok "Archivos fuente verificados"

# ---- copiar a destino -------------------------------------------------------
mkdir -p "${TARGET_DIR}"
cp "${SOURCE_DIR}/SKILL.md" "${TARGET_DIR}/"
cp "${SOURCE_DIR}/token_usage.py" "${TARGET_DIR}/"
cp "${SOURCE_DIR}/subagent_tokens_hook.py" "${TARGET_DIR}/"
ok "Copiado a ${TARGET_DIR}"

# ---- mergear hook en settings.json -----------------------------------------
"${PYTHON}" - "${SETTINGS_FILE}" "${PYTHON}" "${HOOK_COMMAND_PATH}" <<'PYEOF'
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

settings_file = Path(sys.argv[1])
python_cmd = sys.argv[2]
hook_path = sys.argv[3]

settings_file.parent.mkdir(parents=True, exist_ok=True)

if settings_file.exists():
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"\nERROR: {settings_file} tiene JSON inválido: {exc}", file=sys.stderr)
        sys.exit(1)
else:
    settings = {}

hooks = settings.setdefault("hooks", {})
post_tool_use = hooks.setdefault("PostToolUse", [])

desired_command = f'{python_cmd} "{hook_path}"'

replaced = False
for entry in post_tool_use:
    for h in entry.get("hooks", []):
        cmd = h.get("command") or ""
        if "subagent_tokens_hook.py" in cmd:
            h["command"] = desired_command
            h["type"] = "command"
            h["timeout"] = 30
            entry["matcher"] = "Agent|Task"
            replaced = True
            break
    if replaced:
        break

if not replaced:
    post_tool_use.append({
        "matcher": "Agent|Task",
        "hooks": [{
            "type": "command",
            "command": desired_command,
            "timeout": 30,
        }],
    })

settings_file.write_text(
    json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

label = "actualizado" if replaced else "registrado"
print(f"  \u2714 Hook {label} en {settings_file}")
PYEOF

# ---- smoke test ------------------------------------------------------------
printf "\n"
info "Smoke test: ejecutando la skill..."
if "${PYTHON}" "${TARGET_DIR}/token_usage.py" -p today --no-registry >/dev/null 2>&1; then
    ok "Smoke test pasado"
else
    warn "Smoke test falló — corré manualmente para ver el error:"
    warn "  ${PYTHON} ${TARGET_DIR}/token_usage.py -p today"
fi

# ---- cierre ----------------------------------------------------------------
cat <<EOF

=== Listo ===

Scope de esta instalación: ${SCOPE_LABEL}

Próximos pasos:
  1. Reiniciá Claude Code para que tome el hook.
  2. Probá la skill:  /token-usage
  3. Cuando delegues a un sub-agente, vas a ver abajo del resultado:
     [token-usage] Sub-agente \`<tipo>\` — total_tokens=N | tool_uses=M | duration_ms=D

Qué se instaló:
  - ${TARGET_DIR}/SKILL.md
  - ${TARGET_DIR}/token_usage.py
  - ${TARGET_DIR}/subagent_tokens_hook.py
  - entrada en ${SETTINGS_FILE}
    (hooks.PostToolUse con matcher "Agent|Task")

Para desinstalar: ./uninstall.sh $( [ "${MODE}" = "project" ] && echo "--project" )

EOF
