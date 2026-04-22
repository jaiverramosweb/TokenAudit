#requires -Version 5.1
<#
.SYNOPSIS
    TokenAudit - desinstalador PowerShell.

.PARAMETER Project
    Desinstala scoped al directorio actual.
#>

param(
    [switch]$Project,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"

foreach ($arg in $Rest) {
    switch -Regex ($arg) {
        '^(--project|-p)$' { $Project = $true }
        '^(--help|-h)$'    { $Help = $true }
    }
}

if ($Help) {
    @"
Uso: .\uninstall.ps1 [--project]
"@
    exit 0
}

$skillName = "token-usage"
if ($Project) {
    $baseDir = Join-Path $PWD ".claude"
    $scopeLabel = "proyecto ($PWD)"
} else {
    $baseDir = Join-Path $HOME ".claude"
    $scopeLabel = "usuario ($baseDir)"
}

$targetDir = Join-Path $baseDir "skills\$skillName"
$settingsFile = Join-Path $baseDir "settings.json"

Write-Host ""
Write-Host "=== TokenAudit :: desinstalando $skillName (PowerShell) ===" -ForegroundColor Cyan
Write-Host "    Modo: $scopeLabel"
Write-Host ""

# ---- detectar Python -------------------------------------------------------
$python = $null
foreach ($candidate in @("python", "python3", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        & $candidate -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    } catch {}
}
if (-not $python) {
    Write-Host "ERROR: Python 3.8+ no encontrado (lo necesito para editar settings.json de forma segura)." -ForegroundColor Red
    exit 1
}

# ---- borrar carpeta de la skill --------------------------------------------
if (Test-Path $targetDir) {
    Remove-Item -Recurse -Force $targetDir
    Write-Host "  [OK] Eliminado $targetDir" -ForegroundColor Green
} else {
    Write-Host "  [!]  No existia $targetDir (nada para borrar)" -ForegroundColor Yellow
}

# ---- quitar hook de settings.json ------------------------------------------
if (Test-Path $settingsFile) {
    $removeScript = @'
import json, sys
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
    print(f"\nERROR: {settings_file} tiene JSON invalido: {exc}", file=sys.stderr)
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
    print(f"  [OK] Hook eliminado de {settings_file} ({removed} entrada(s))")
else:
    print(f"  [!]  No se encontro el hook en {settings_file} (ya estaba limpio)")
'@

    $tempPy = Join-Path $env:TEMP "tokenaudit-uninstall-$PID.py"
    Set-Content -Path $tempPy -Value $removeScript -Encoding UTF8 -NoNewline
    try {
        & $python $tempPy $settingsFile
    } finally {
        Remove-Item $tempPy -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "  [!]  No existe $settingsFile" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Listo ==="
Write-Host ""
Write-Host "Desinstalacion completa. Reinicia Claude Code para que deje de cargar el hook."
Write-Host ""
Write-Host "Nota: los archivos TOKEN_USAGE.md que la skill genero en tus proyectos"
Write-Host "siguen ahi. Si los queres borrar, hacelo manualmente."
Write-Host ""
