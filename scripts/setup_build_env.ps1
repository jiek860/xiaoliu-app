param(
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Select-SupportedPython {
    foreach ($v in @("3.12", "3.11", "3.10")) {
        & py "-$v" --version *> $null
        if ($LASTEXITCODE -eq 0) { return $v }
    }
    throw "找不到受支持的 Python（需要 3.10 / 3.11 / 3.12）"
}

$Version = Select-SupportedPython
Write-Host "[OK] 使用 Python $Version"

function New-Venv([string]$Path) {
    if ($Force -and (Test-Path $Path)) {
        Write-Host "[-] 删除旧环境: $Path"
        Remove-Item -Recurse -Force $Path
    }
    if (-not (Test-Path $Path)) {
        & py "-$Version" -m venv $Path
        if ($LASTEXITCODE -ne 0) { throw "创建虚拟环境失败: $Path" }
    }
    $Python = Join-Path $Path "Scripts\python.exe"
    if (-not (Test-Path $Python)) { throw "找不到环境解释器: $Python" }
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "升级 pip 失败" }
    return $Python
}

Write-Host "=== 创建打包环境 .build-venv ==="
$Python = New-Venv ".build-venv"
& $Python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "安装打包依赖失败" }
& $Python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 不可用" }
Write-Host "[OK] .build-venv 已就绪"
Write-Host "     .\.build-venv\Scripts\python.exe -m PyInstaller --clean --noconfirm xiao6.spec"
