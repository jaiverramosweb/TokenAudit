#requires -Version 5.1
<#
.SYNOPSIS
    TokenAudit - instalador PowerShell (sin dependencia de bash).

.DESCRIPTION
    Equivalente de install.sh en PowerShell nativo. Detecta Python, copia
    los archivos de la skill, mergea el hook PostToolUse en settings.json
    y corre un smoke test. Idempotente.

.PARAMETER Project
    Instala scoped al directorio actual (./.claude/) en vez de global al
    usuario (~/.claude/).

.PARAMETER NoSmoke
    Saltea el smoke test final.

.PARAMETER Help
    Muestra esta ayuda.

.EXAMPLE
    .\install.ps1              # instalacion global al usuario
    .\install.ps1 --project    # instalacion scoped al proyecto actual
#>

param(
    [Parameter()]
    [switch]$Project,
    [switch]$NoSmoke,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"

# Aceptar tambien --project / -p al estilo bash (no solo -Project)
foreach ($arg in $Rest) {
    switch -Regex ($arg) {
        '^(--project|-p)$' { $Project = $true }
        '^(--no-smoke)$'   { $NoSmoke = $true }
        '^(--help|-h)$'    { $Help = $true }
    }
}

if ($Help) {
    @"
TokenAudit - instalador PowerShell

  .\install.ps1              Instala global al usuario (~/.claude/).
                             Aplica a TODOS los proyectos del usuario.
  .\install.ps1 --project    Instala scoped al directorio actual (./.claude/).
                             Aplica solo a ESE proyecto.

Idempotente: podes correrlo mas de una vez sin duplicar nada.
"@
    exit 0
}

$skillName = "token-usage"
$repoRoot = $PSScriptRoot
$sourceDir = Join-Path $repoRoot "skills\$skillName"

if ($Project) {
    $baseDir = Join-Path $PWD ".claude"
    $hookPath = '${CLAUDE_PROJECT_DIR}/.claude/skills/token-usage/subagent_tokens_hook.py'
    $scopeLabel = "proyecto ($PWD)"
} else {
    $baseDir = Join-Path $HOME ".claude"
    $scopeLabel = "usuario ($baseDir)"
}

$targetDir = Join-Path $baseDir "skills\$skillName"
$settingsFile = Join-Path $baseDir "settings.json"

# Para modo local, el hook usa path absoluto con forward slashes
if (-not $Project) {
    $absTarget = ($targetDir -replace '\\', '/')
    $hookPath = "$absTarget/subagent_tokens_hook.py"
}

# ---- helpers ---------------------------------------------------------------
function Write-Ok    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn2 { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "`nERROR: $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== TokenAudit :: instalando $skillName (PowerShell) ===" -ForegroundColor Cyan
Write-Host "    Modo: $scopeLabel"
Write-Host ""

# ---- detectar Python 3.8+ --------------------------------------------------
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    } catch {}
}

if (-not $python) {
    Write-Err "Python 3.8+ no encontrado en el PATH. Instalalo desde https://www.python.org/downloads/ marcando 'Add Python to PATH'."
}

$pythonVersion = (& $python --version 2>&1) -join ' '
Write-Ok "Python detectado: $pythonVersion (comando: $python)"

# ---- verificar archivos fuente ---------------------------------------------
foreach ($f in @("SKILL.md", "token_usage.py", "subagent_tokens_hook.py")) {
    if (-not (Test-Path (Join-Path $sourceDir $f))) {
        Write-Err "Archivo faltante: $(Join-Path $sourceDir $f)"
    }
}
Write-Ok "Archivos fuente verificados"

# ---- copiar archivos -------------------------------------------------------
if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}
Copy-Item (Join-Path $sourceDir "SKILL.md")                 $targetDir -Force
Copy-Item (Join-Path $sourceDir "token_usage.py")           $targetDir -Force
Copy-Item (Join-Path $sourceDir "subagent_tokens_hook.py")  $targetDir -Force
Write-Ok "Copiado a $targetDir"

# ---- mergear hook en settings.json (via Python para reusar logica) --------
$mergeScript = @'
import json, sys
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
        print(f"\nERROR: {settings_file} tiene JSON invalido: {exc}", file=sys.stderr)
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
print(f"  [OK] Hook {label} en {settings_file}")
'@

$tempPy = Join-Path $env:TEMP "tokenaudit-merge-$PID.py"
Set-Content -Path $tempPy -Value $mergeScript -Encoding UTF8 -NoNewline
try {
    & $python $tempPy $settingsFile $python $hookPath
    if ($LASTEXITCODE -ne 0) { Write-Err "Fallo el merge de settings.json" }
} finally {
    Remove-Item $tempPy -ErrorAction SilentlyContinue
}

# ---- smoke test ------------------------------------------------------------
if (-not $NoSmoke) {
    Write-Host ""
    Write-Host "    Smoke test: ejecutando la skill..."
    $script = Join-Path $targetDir "token_usage.py"
    & $python $script -p today --no-registry *>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Smoke test pasado"
    } else {
        Write-Warn2 "Smoke test fallo - corre manualmente: $python $script -p today"
    }
}

# ---- cierre ----------------------------------------------------------------
$uninstallArg = if ($Project) { " --project" } else { "" }

Write-Host ""
Write-Host "=== Listo ==="
Write-Host ""
Write-Host "Scope de esta instalacion: $scopeLabel"
Write-Host ""
Write-Host "Proximos pasos:"
Write-Host "  1. Reinicia Claude Code para que tome el hook."
Write-Host "  2. Proba la skill:  /token-usage"
Write-Host "  3. Cuando delegues a un sub-agente, vas a ver abajo del resultado:"
Write-Host "     [token-usage] Sub-agente <tipo> - total_tokens=N | tool_uses=M | duration_ms=D"
Write-Host ""
Write-Host "Que se instalo:"
Write-Host "  - $targetDir\SKILL.md"
Write-Host "  - $targetDir\token_usage.py"
Write-Host "  - $targetDir\subagent_tokens_hook.py"
Write-Host "  - entrada en $settingsFile"
Write-Host "    (hooks.PostToolUse con matcher 'Agent|Task')"
Write-Host ""
Write-Host "Para desinstalar: .\uninstall.ps1$uninstallArg"
Write-Host ""
