#!/usr/bin/env bash
# TokenAudit — bootstrap: clona el repo y ejecuta install.sh.
#
# Ejemplos de uso (una línea):
#
#   # Instalación local (global al usuario)
#   curl -fsSL https://raw.githubusercontent.com/<USER>/TokenAudit/main/bootstrap.sh | bash
#
#   # Instalación por proyecto — parate primero en el proyecto
#   cd /ruta/a/tu/proyecto
#   curl -fsSL https://raw.githubusercontent.com/<USER>/TokenAudit/main/bootstrap.sh | bash -s -- --project
#
# Overrides vía variables de entorno:
#   TOKENAUDIT_REPO    URL del repo git (default: la hardcodeada abajo)
#   TOKENAUDIT_BRANCH  rama a usar        (default: main)
#   TOKENAUDIT_DIR     dónde clonar       (default: ~/TokenAudit)

set -euo pipefail

# ==============================================================================
# EDITÁ ESTA URL antes del primer push a GitHub — apuntala a tu repo real.
# ==============================================================================
DEFAULT_REPO="https://github.com/CHANGEME/TokenAudit.git"
# ==============================================================================

REPO_URL="${TOKENAUDIT_REPO:-$DEFAULT_REPO}"
BRANCH="${TOKENAUDIT_BRANCH:-main}"
TARGET_DIR="${TOKENAUDIT_DIR:-$HOME/TokenAudit}"

printf "\n=== TokenAudit :: bootstrap ===\n"
printf "    Repo:   %s\n" "$REPO_URL"
printf "    Branch: %s\n" "$BRANCH"
printf "    Dest:   %s\n\n" "$TARGET_DIR"

# ---- prerequisitos -----------------------------------------------------------
command -v git >/dev/null 2>&1 || {
    printf "ERROR: git no está en el PATH. Instalalo y volvé a intentar.\n" >&2
    exit 1
}

if [[ "$REPO_URL" == *CHANGEME* ]]; then
    printf "ERROR: bootstrap.sh todavía tiene la URL del repo sin configurar (CHANGEME).\n" >&2
    printf "       Editá bootstrap.sh y reemplazá la URL por la tuya, o\n" >&2
    printf "       pasá TOKENAUDIT_REPO=<url> como variable de entorno.\n" >&2
    exit 1
fi

# ---- clonar o actualizar -----------------------------------------------------
if [ -d "$TARGET_DIR/.git" ]; then
    printf "  -> %s ya existe, actualizando...\n" "$TARGET_DIR"
    git -C "$TARGET_DIR" fetch --depth=1 origin "$BRANCH"
    git -C "$TARGET_DIR" checkout "$BRANCH" >/dev/null 2>&1 || true
    if ! git -C "$TARGET_DIR" pull --ff-only origin "$BRANCH"; then
        printf "\nERROR: no se pudo hacer fast-forward en %s.\n" "$TARGET_DIR" >&2
        printf "       Hay cambios locales que divergen del remote. Resolvelos y volvé a correr.\n" >&2
        exit 1
    fi
elif [ -e "$TARGET_DIR" ]; then
    printf "ERROR: %s existe pero no es un repo git. Movelo o borralo antes de continuar.\n" "$TARGET_DIR" >&2
    exit 1
else
    printf "  -> clonando %s -> %s\n" "$REPO_URL" "$TARGET_DIR"
    git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR"
fi

# ---- ejecutar install.sh con los args originales -----------------------------
printf "\n  -> ejecutando install.sh %s\n" "$*"
exec bash "$TARGET_DIR/install.sh" "$@"
