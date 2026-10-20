param(
    [switch]$Force,
    [switch]$WithOptional
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

Write-Host "=== 创建干净运行环境 .runtime-venv ==="
$Python = New-Venv ".runtime-venv"
& $Python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "安装核心运行依赖失败" }
if ($WithOptional) {
    Write-Host "=== 安装可选依赖（语音/浏览器/Office 解析等）==="
    & $Python -m pip install -r requirements-optional.txt
    if ($LASTEXITCODE -ne 0) { throw "安装可选依赖失败" }
    & $Python tools\check_optional_env.py
    if ($LASTEXITCODE -ne 0) { throw "可选依赖检查失败" }
    Write-Host "提示：浏览器还需运行一次 py -3 -m playwright install chromium"
}
& $Python tools/check_runtime_compat.py --allow-server
if ($LASTEXITCODE -ne 0) { throw "运行环境兼容性检查失败" }
Write-Host "[OK] .runtime-venv 已就绪"
Write-Host "     可选依赖可用 -WithOptional 安装"
