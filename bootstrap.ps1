#requires -Version 5.1
<#
.SYNOPSIS
    TokenAudit — bootstrap para PowerShell (Windows).

.DESCRIPTION
    Thin wrapper: localiza bash.exe de Git for Windows y delega al
    bootstrap.sh real. Funciona sin abrir Git Bash primero.

.EXAMPLE
    # Instalación modo local (una línea)
    iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex

.EXAMPLE
    # Instalación modo proyecto (requiere download + run porque iex no pasa args)
    $tmp = "$env:TEMP\tokenaudit-bootstrap.ps1"
    iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 -OutFile $tmp
    & $tmp --project
    Remove-Item $tmp

.NOTES
    Requiere:
      - Git for Windows instalado (para bash.exe)
      - Python 3.8+ en el PATH
#>

$ErrorActionPreference = "Stop"

# Forzar TLS 1.2 para sistemas Windows viejos
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

Write-Host ""
Write-Host "=== TokenAudit :: bootstrap.ps1 ===" -ForegroundColor Cyan

# ---- Localizar bash.exe de Git for Windows ---------------------------------
$bashCandidates = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files (x86)\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe",
    "$env:ProgramFiles\Git\bin\bash.exe"
)

$bash = $null
foreach ($candidate in $bashCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $bash = $candidate
        break
    }
}

if (-not $bash) {
    # Fallback: cualquier bash.exe del PATH que NO sea WSL (System32)
    $found = Get-Command bash.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch "System32" } |
        Select-Object -First 1
    if ($found) { $bash = $found.Source }
}

if (-not $bash) {
    Write-Host ""
    Write-Host "ERROR: no encontré bash.exe de Git for Windows." -ForegroundColor Red
    Write-Host ""
    Write-Host "TokenAudit necesita Git for Windows porque internamente el"
    Write-Host "install.sh y los hooks usan bash."
    Write-Host ""
    Write-Host "Soluciones:"
    Write-Host "  1) Instalar Git for Windows: https://git-scm.com/download/win"
    Write-Host "     (todas las opciones default están bien)"
    Write-Host "  2) Después de instalar, abrir una terminal nueva y volver a correr"
    Write-Host "     este comando."
    exit 1
}

Write-Host "    bash: $bash" -ForegroundColor DarkGray

# ---- Detectar modo proyecto (flag o env var) -------------------------------
$installArgs = @()
$projectMode = $false

# Parsear args explícitos
foreach ($arg in $args) {
    if ($arg -eq "--project" -or $arg -eq "-p") {
        $projectMode = $true
    } elseif ($arg) {
        $installArgs += $arg
    }
}

# Override vía env var (útil cuando se invoca con `iwr | iex`, que no pasa args)
if ($env:TOKENAUDIT_PROJECT -eq "1" -and -not $projectMode) {
    $projectMode = $true
}

if ($projectMode) {
    $installArgs = @("--project") + $installArgs
    Write-Host "    modo: PROYECTO (cwd = $PWD)" -ForegroundColor DarkGray
} else {
    Write-Host "    modo: LOCAL (global al usuario)" -ForegroundColor DarkGray
}

Write-Host ""

# ---- Delegar al bootstrap.sh remoto vía bash -------------------------------
$bootstrapUrl = if ($env:TOKENAUDIT_BOOTSTRAP_URL) {
    $env:TOKENAUDIT_BOOTSTRAP_URL
} else {
    "https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh"
}

$joinedArgs = ($installArgs -join ' ')

# Env vars de passthrough (TOKENAUDIT_REPO, TOKENAUDIT_BRANCH, TOKENAUDIT_DIR)
$envExports = @()
foreach ($var in @("TOKENAUDIT_REPO", "TOKENAUDIT_BRANCH", "TOKENAUDIT_DIR")) {
    $val = [Environment]::GetEnvironmentVariable($var)
    if ($val) {
        $envExports += "export $var='$val'"
    }
}
$envPrefix = if ($envExports.Count -gt 0) { ($envExports -join '; ') + '; ' } else { '' }

$bashCmd = "${envPrefix}curl -fsSL '$bootstrapUrl' | bash -s -- $joinedArgs"

# Ejecutar bash.exe -c "<comando>"
& $bash -c $bashCmd

$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "ERROR: el bootstrap falló (exit code: $exitCode)" -ForegroundColor Red
    exit $exitCode
}

Write-Host ""
Write-Host "TokenAudit instalado. Reiniciá Claude Code para que cargue el hook." -ForegroundColor Green
