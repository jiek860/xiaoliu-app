$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$rows = @()
foreach ($name in @(".venv", ".runtime-venv", ".build-venv")) {
    $python = Join-Path $name "Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $rows += [pscustomobject]@{Env=$name; OK=$false; Python=""; Detail="missing"}
        continue
    }
    $ver = (& $python --version 2>&1 | Out-String).Trim()
    $leaks = ""
    if ($name -in @(".runtime-venv", ".build-venv")) {
        $leaks = (& $python -c "import importlib.util; print(','.join(p for p in ['pytest','jupyter','jupyterlab','notebook','IPython','coverage'] if importlib.util.find_spec(p)))" 2>&1 | Out-String).Trim()
    }
    $ok = [string]::IsNullOrWhiteSpace($leaks)
    $detail = if ($ok) { $python } else { "dev package leaked: " + $leaks }
    $rows += [pscustomobject]@{Env=$name; OK=$ok; Python=$ver; Detail=$detail}
}
$rows | Format-Table -AutoSize
if ($rows | Where-Object { -not $_.OK }) { exit 1 }
