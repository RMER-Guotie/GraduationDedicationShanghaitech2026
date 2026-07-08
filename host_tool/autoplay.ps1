param(
    [string]$ModeDir = "autoplay",
    [int]$Baud = 115200,
    [double]$ChunkDelayMs = 0.25,
    [double]$RcPollInterval = 0.1
)

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$Host.UI.RawUI.WindowTitle = "Pixel Light Autoplay"

$Python = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Pixel Light Autoplay"
Write-Host "Working directory: $ScriptDir"
Write-Host "Python: $Python"
Write-Host "Mode directory: $ModeDir"

while ($true) {
    & $Python -m tools.autoplay `
        --mode-dir $ModeDir `
        --baud $Baud `
        --chunk-delay-ms $ChunkDelayMs `
        --rc-poll-interval $RcPollInterval

    $ExitCode = $LASTEXITCODE
    Write-Host "tools.autoplay exited with code $ExitCode; restarting in 5 seconds."
    Start-Sleep -Seconds 5
}
