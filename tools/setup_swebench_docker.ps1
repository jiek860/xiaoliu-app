<#
.SYNOPSIS
    一步装好 SWE-bench 判分环境：WSL2 + Docker Desktop + 国内镜像加速。

.DESCRIPTION
    本机实测（2026-10-27）：
      · 当前会话是 UAC 过滤令牌（BUILTIN\Administrators 为 deny-only），
        所有安装动作都必须提权；没提权时脚本会自动弹 UAC 重新拉起自己；
      · WSL 未安装、Docker Desktop 未安装、docker 命令不存在；
      · Docker Hub（registry-1.docker.io / auth.docker.io）与 163、中科大、
        dockerproxy、swr 等加速器的 443 全部不通；实测只有
        docker.1ms.run / hub.rat.dev / docker.xuanyuan.me / docker.nju.edu.cn
        能连上，所以不写 registry-mirrors 的话，harness 连基础镜像都拉不到；
      · C 盘只剩约 10 GB，镜像必须放 E 盘（装完在 Docker Desktop 里改磁盘镜像位置）。

    脚本只做需要管理员的三件事，不重启、不自动跑评测：
      1. 打开 WSL + 虚拟机平台（DISM，需重启生效）
      2. winget 安装 Docker Desktop
      3. 写 registry-mirrors 到 C:\ProgramData\Docker\config\daemon.json

.PARAMETER SkipWsl
    跳过 WSL/虚拟机平台开关（已经开过时用）。

.PARAMETER SkipDocker
    跳过 Docker Desktop 安装（已经装好、只想更新镜像加速时用）。

.PARAMETER Reboot
    脚本跑完后直接重启（默认不动，需自己重启）。

.EXAMPLE
    # 右键“以管理员身份运行 PowerShell”，然后：
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_swebench_docker.ps1

.EXAMPLE
    # 只补镜像加速配置：
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup_swebench_docker.ps1 -SkipWsl -SkipDocker
#>
param(
    [switch]$SkipWsl,
    [switch]$SkipDocker,
    [switch]$Reboot
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Mirrors = @(
    "https://docker.1ms.run",
    "https://hub.rat.dev",
    "https://docker.xuanyuan.me",
    "https://docker.nju.edu.cn"
)

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host ("== " + $Text) -ForegroundColor Cyan
}

function Write-Ok([string]$Text) {
    Write-Host ("   [OK] " + $Text) -ForegroundColor Green
}

function Write-Warn2([string]$Text) {
    Write-Host ("   [!] " + $Text) -ForegroundColor Yellow
}

# ---------------------------------------------------------------- 提权
if (-not (Test-Elevated)) {
    Write-Host "需要管理员权限，正在弹 UAC 重新拉起本脚本..." -ForegroundColor Yellow
    $launchArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $PSCommandPath + '"'))
    if ($SkipWsl) { $launchArgs += "-SkipWsl" }
    if ($SkipDocker) { $launchArgs += "-SkipDocker" }
    if ($Reboot) { $launchArgs += "-Reboot" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $launchArgs -Verb RunAs
    exit 0
}

Write-Host "小6 - SWE-bench 判分环境安装" -ForegroundColor Cyan
Write-Host ("项目根：" + $ProjectRoot)
Write-Host ("时间：" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
$needReboot = $false

# ---------------------------------------------------------------- 1. WSL
if (-not $SkipWsl) {
    Write-Step "1/3 打开 WSL 与虚拟机平台（DISM）"
    foreach ($feature in @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform")) {
        $out = & dism.exe /online /enable-feature /featurename:$feature /all /norestart 2>&1
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            Write-Ok ("$feature 已启用")
        } elseif ($code -eq 3010) {
            Write-Ok ("$feature 已启用（需要重启生效）")
            $needReboot = $true
        } else {
            Write-Warn2 ("$feature 启用失败（dism 退出码 $code）：" + ($out | Select-Object -Last 3))
        }
    }
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & wsl.exe --set-default-version 2 *> $null
    $ErrorActionPreference = $old
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "WSL 默认版本已设为 2"
    } else {
        Write-Warn2 "wsl --set-default-version 2 暂未成功（装完重启后再跑一次即可）"
        $needReboot = $true
    }
} else {
    Write-Step "1/3 跳过 WSL 开关（-SkipWsl）"
}

# ---------------------------------------------------------------- 2. Docker
if (-not $SkipDocker) {
    Write-Step "2/3 安装 Docker Desktop（winget）"
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Warn2 "找不到 winget；请手动装 Docker Desktop：https://www.docker.com/products/docker-desktop/"
    } else {
        & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "Docker Desktop 安装命令返回成功"
        } else {
            Write-Warn2 ("winget 返回 $LASTEXITCODE；可重试或改用官网安装包")
        }
    }
    Write-Warn2 "C 盘仅约 10 GB：装完请在 Docker Desktop → Settings → Resources → Advanced 把磁盘镜像位置改到 E:\Docker\data"
} else {
    Write-Step "2/3 跳过 Docker 安装（-SkipDocker）"
}

# ---------------------------------------------------------------- 3. 镜像加速
Write-Step "3/3 写 Docker 镜像加速（registry-mirrors）"
$cfgDir = "C:\ProgramData\Docker\config"
$cfgFile = Join-Path $cfgDir "daemon.json"
$data = @{}
if (Test-Path $cfgFile) {
    try {
        $obj = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $obj.PSObject.Properties) { $data[$p.Name] = $p.Value }
        Copy-Item $cfgFile ($cfgFile + ".bak") -Force
    } catch {
        Write-Warn2 ("现有 daemon.json 解析失败，已备份为 daemon.json.bak：" + $_.Exception.Message)
        Copy-Item $cfgFile ($cfgFile + ".bak") -Force
        $data = @{}
    }
}
$data["registry-mirrors"] = $Mirrors
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$json = $data | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($cfgFile, $json, (New-Object Text.UTF8Encoding($false)))
Write-Ok ("已写入 " + $cfgFile)
$Mirrors | ForEach-Object { Write-Host ("      " + $_) }

# ---------------------------------------------------------------- 收尾
$rebootNote = if ($needReboot) { "（必须：WSL 开关要重启才生效）" } else { "" }
Write-Step "下一步（按顺序）"
Write-Host ("   1. 重启电脑" + $rebootNote)
Write-Host "   2. 启动 Docker Desktop，等托盘图标变绿"
Write-Host "   3. Settings → Resources → Advanced：磁盘镜像位置改到 E:\Docker\data"
Write-Host "   4. 回来验证（普通 PowerShell 即可）："
Write-Host "        docker run --rm hello-world"
Write-Host ("        " + (Join-Path $ProjectRoot ".swebench-venv\Scripts\python.exe") + " tools\swebench_verified.py --check --dataset data\swebench\swebench_verified.jsonl")
Write-Host "   5. 自检全绿后再跑 1 题 smoke（命令见 docs\95）"

if ($Reboot) {
    Write-Warn2 "按 -Reboot 参数，10 秒后重启..."
    Start-Sleep -Seconds 10
    Restart-Computer -Force
}
