param(
    [Parameter(Mandatory=$true)][string]$DistPath,
    [Parameter(Mandatory=$true)][string]$PfxBase64,
    [Parameter(Mandatory=$true)][string]$PfxPassword,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kits) {
        $found = Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    throw "signtool.exe not found (install Windows SDK signing tools)"
}

$root = (Resolve-Path $DistPath).Path
$tmpPfx = Join-Path $env:RUNNER_TEMP ("x6-sign-" + [guid]::NewGuid().ToString("N") + ".pfx")
try {
    [IO.File]::WriteAllBytes($tmpPfx, [Convert]::FromBase64String($PfxBase64))
    $signTool = Find-SignTool
    $targets = Get-ChildItem -Path $root -Recurse -File -Include *.exe
    if (-not $targets) { throw "No .exe files found under $root" }
    foreach ($file in $targets) {
        & $signTool sign /fd SHA256 /f $tmpPfx /p $PfxPassword /tr $TimestampUrl /td SHA256 $file.FullName
        if ($LASTEXITCODE -ne 0) { throw "signtool failed: $($file.FullName)" }
    }
    $bad = @()
    foreach ($file in $targets) {
        $sig = Get-AuthenticodeSignature -FilePath $file.FullName
        if ($sig.Status -ne "Valid") {
            $bad += "$($file.FullName): $($sig.Status)"
        }
    }
    if ($bad.Count -gt 0) { throw ("Authenticode validation failed:`n" + ($bad -join "`n")) }
    Write-Host "Signed and verified $($targets.Count) executable(s)."
}
finally {
    if (Test-Path $tmpPfx) { Remove-Item -Force $tmpPfx }
}
