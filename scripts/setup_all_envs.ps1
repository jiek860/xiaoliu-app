param(
    [switch]$Force,
    [switch]$WithOptional
)
$ErrorActionPreference = "Stop"
$Scripts = Split-Path -Parent $PSCommandPath
& (Join-Path $Scripts "setup_dev_env.ps1") -Force:$Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Scripts "setup_runtime_env.ps1") -Force:$Force -WithOptional:$WithOptional
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Scripts "setup_build_env.ps1") -Force:$Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "[OK] .venv / .runtime-venv / .build-venv 全部就绪"
& (Join-Path $Scripts "check_envs.ps1")
