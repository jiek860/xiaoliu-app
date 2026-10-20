param(
    [switch]$SkipSetup,
    [int]$LaunchSeconds = 10,
    [string]$Dist = "dist"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipSetup) {
    & (Join-Path $PSScriptRoot "setup_build_env.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$Python = Join-Path $Root ".build-venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "缺少 .build-venv，先运行 scripts\setup_build_env.ps1" }

if (Test-Path $Dist) { Remove-Item -Recurse -Force $Dist }
& $Python -m PyInstaller --clean --noconfirm --distpath $Dist --workpath build xiao6.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败" }
& $Python tools\check_pyinstaller_output.py --dist $Dist --launch-seconds $LaunchSeconds
if ($LASTEXITCODE -ne 0) { throw "打包产物检查失败" }
& $Python tools\check_pyinstaller_warnings.py --warn build\xiao6\warn-xiao6.txt
if ($LASTEXITCODE -ne 0) { throw "PyInstaller warning 分类失败" }
Write-Host "[OK] Windows 打包检查通过: $Dist"
