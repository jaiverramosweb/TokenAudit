#requires -Version 5.1
<#
.SYNOPSIS
    TokenAudit — bootstrap para PowerShell (Windows).

.DESCRIPTION
    Script bootstrap que instala TokenAudit desde cero. Detecta si hay
    bash.exe disponible y usa uno de dos caminos:

      Camino bash (preferido si hay Git for Windows):
        -> descarga y ejecuta bootstrap.sh + install.sh via bash.exe
        -> requiere: Python + Git for Windows

      Camino PowerShell nativo (fallback sin bash):
        -> descarga el repo como ZIP desde GitHub
        -> lo extrae a ~/TokenAudit
        -> ejecuta install.ps1
        -> requiere: solo Python (ni siquiera git.exe)

.EXAMPLE
    # Instalacion modo local (una linea)
    iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex

.EXAMPLE
    # Forzar camino PowerShell (aunque haya bash)
    $env:TOKENAUDIT_NO_BASH=1
    iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex

.EXAMPLE
    # Instalacion modo proyecto (no se puede pasar args con | iex)
    $env:TOKENAUDIT_PROJECT=1
    iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex
    Remove-Item Env:TOKENAUDIT_PROJECT

.NOTES
    Variables de entorno reconocidas:
      TOKENAUDIT_PROJECT        1 -> modo proyecto (sin flag)
      TOKENAUDIT_NO_BASH        1 -> saltea camino bash, va directo al ZIP
      TOKENAUDIT_REPO           URL alternativa del repo
      TOKENAUDIT_BRANCH         rama alternativa (default: main)
      TOKENAUDIT_DIR            carpeta alternativa (default: ~/TokenAudit)
      TOKENAUDIT_BOOTSTRAP_URL  URL alternativa del bootstrap.sh remoto
#>

$ErrorActionPreference = "Stop"

# Forzar TLS 1.2 para sistemas Windows viejos
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {}

# ---- config comun ----------------------------------------------------------
$RepoUrl    = if ($env:TOKENAUDIT_REPO)   { $env:TOKENAUDIT_REPO }   else { "https://github.com/jaiverramosweb/TokenAudit.git" }
$Branch     = if ($env:TOKENAUDIT_BRANCH) { $env:TOKENAUDIT_BRANCH } else { "main" }
$TargetDir  = if ($env:TOKENAUDIT_DIR)    { $env:TOKENAUDIT_DIR }    else { (Join-Path $HOME "TokenAudit") }
$ZipUrl     = $RepoUrl -replace '\.git$', '' -replace '^', '' | ForEach-Object { "$_/archive/refs/heads/$Branch.zip" }

Write-Host ""
Write-Host "=== TokenAudit :: bootstrap.ps1 ===" -ForegroundColor Cyan

# ---- detectar modo proyecto ------------------------------------------------
$installArgs = @()
$projectMode = $false

foreach ($arg in $args) {
    if ($arg -eq "--project" -or $arg -eq "-p") {
        $projectMode = $true
    } elseif ($arg) {
        $installArgs += $arg
    }
}

if ($env:TOKENAUDIT_PROJECT -eq "1" -and -not $projectMode) {
    $projectMode = $true
}

if ($projectMode) {
    $installArgs = @("--project") + $installArgs
    Write-Host "    modo:   PROYECTO (cwd = $PWD)" -ForegroundColor DarkGray
} else {
    Write-Host "    modo:   LOCAL (global al usuario)" -ForegroundColor DarkGray
}

# ---- localizar bash (opcional) --------------------------------------------
$bash = $null
if ($env:TOKENAUDIT_NO_BASH -ne "1") {
    $bashCandidates = @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files (x86)\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe",
        "$env:ProgramFiles\Git\bin\bash.exe"
    )
    foreach ($c in $bashCandidates) {
        if (Test-Path -LiteralPath $c) { $bash = $c; break }
    }
    if (-not $bash) {
        $found = Get-Command bash.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notmatch "System32" } |
            Select-Object -First 1
        if ($found) { $bash = $found.Source }
    }
}

# ==========================================================================
# CAMINO 1: bash disponible -> delegar a bootstrap.sh (via bash.exe)
# ==========================================================================
if ($bash) {
    Write-Host "    camino: bash ($bash)" -ForegroundColor DarkGray
    Write-Host ""

    $bootstrapUrl = if ($env:TOKENAUDIT_BOOTSTRAP_URL) {
        $env:TOKENAUDIT_BOOTSTRAP_URL
    } else {
        "https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh"
    }

    $joinedArgs = ($installArgs -join ' ')

    $envExports = @()
    foreach ($var in @("TOKENAUDIT_REPO", "TOKENAUDIT_BRANCH", "TOKENAUDIT_DIR")) {
        $val = [Environment]::GetEnvironmentVariable($var)
        if ($val) {
            $envExports += "export $var='$val'"
        }
    }
    $envPrefix = if ($envExports.Count -gt 0) { ($envExports -join '; ') + '; ' } else { '' }

    # Usamos --ssl-no-revoke en caso de redes corporativas con schannel interception
    $bashCmd = "${envPrefix}curl --ssl-no-revoke -fsSL '$bootstrapUrl' | bash -s -- $joinedArgs"

    & $bash -c $bashCmd
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "TokenAudit instalado. Reinicia Claude Code para que cargue el hook." -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "ERROR: el bootstrap bash fallo (exit code: $exitCode)" -ForegroundColor Red
    }
    exit $exitCode
}

# ==========================================================================
# CAMINO 2: sin bash -> descarga ZIP + ejecuta install.ps1
# ==========================================================================
Write-Host "    camino: PowerShell nativo (sin bash)" -ForegroundColor DarkGray
Write-Host ""

# ---- verificar Python ------------------------------------------------------
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
    Write-Host "ERROR: Python 3.8+ no encontrado." -ForegroundColor Red
    Write-Host "Instala Python 3 desde https://www.python.org/downloads/ marcando 'Add Python to PATH'."
    exit 1
}
Write-Host "    python: $((& $python --version 2>&1) -join ' ')" -ForegroundColor DarkGray

# ---- descargar ZIP ---------------------------------------------------------
$repoForZip = $RepoUrl -replace '\.git$', ''
$zipUrl = "$repoForZip/archive/refs/heads/$Branch.zip"
$tempZip = Join-Path $env:TEMP "tokenaudit-$Branch-$PID.zip"
$tempExtract = Join-Path $env:TEMP "tokenaudit-extract-$PID"

Write-Host "    descargando $zipUrl ..." -ForegroundColor DarkGray
try {
    Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -UseBasicParsing
} catch {
    Write-Host ""
    Write-Host "ERROR: no se pudo descargar el ZIP." -ForegroundColor Red
    Write-Host ($_ | Out-String)
    Write-Host "Si es un error de certificado/revocacion en tu red corporativa,"
    Write-Host "proba desactivar revocation check:"
    Write-Host '  [Net.ServicePointManager]::CheckCertificateRevocationList = $false'
    exit 1
}

# ---- extraer y mover a $TargetDir ------------------------------------------
if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract }

# Si $TargetDir existe como repo git, no lo pisamos (el usuario usa el camino bash)
if ((Test-Path $TargetDir) -and (Test-Path (Join-Path $TargetDir ".git"))) {
    Write-Host ""
    Write-Host "ERROR: $TargetDir ya existe como repo git." -ForegroundColor Red
    Write-Host "Estas usando el camino PowerShell pero ya habias instalado con el camino bash."
    Write-Host "Borra $TargetDir o usa un TOKENAUDIT_DIR alternativo y volve a correr."
    exit 1
}

if (Test-Path $TargetDir) { Remove-Item -Recurse -Force $TargetDir }

Write-Host "    extrayendo..." -ForegroundColor DarkGray
Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

# El ZIP contiene una carpeta tipo "TokenAudit-main/" — la renombramos a $TargetDir
$extractedRoot = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
if (-not $extractedRoot) {
    Write-Host "ERROR: el ZIP descargado no contiene la estructura esperada." -ForegroundColor Red
    exit 1
}

Move-Item -Path $extractedRoot.FullName -Destination $TargetDir

Remove-Item $tempZip -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue

Write-Host "    repo extraido -> $TargetDir" -ForegroundColor DarkGray
Write-Host ""

# ---- ejecutar install.ps1 --------------------------------------------------
$installPs1 = Join-Path $TargetDir "install.ps1"
if (-not (Test-Path $installPs1)) {
    Write-Host "ERROR: no se encontro install.ps1 en $TargetDir" -ForegroundColor Red
    exit 1
}

# PowerShell: pasar args al script requiere un splat array
& $installPs1 @installArgs

$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "TokenAudit instalado (camino PowerShell nativo). Reinicia Claude Code para que cargue el hook." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "ERROR: install.ps1 fallo (exit code: $exitCode)" -ForegroundColor Red
}
exit $exitCode
