param(
    [string]$ShortcutName = "Pixel Light Autoplay"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "$ShortcutName.lnk"
$AutoplayScript = Join-Path $ScriptDir "autoplay.ps1"

if (-not (Test-Path $AutoplayScript)) {
    throw "Missing autoplay script: $AutoplayScript"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$AutoplayScript`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Start Pixel Light autoplay on Windows login"
$Shortcut.Save()

Write-Host "Installed startup shortcut:"
Write-Host $ShortcutPath
Write-Host "Place mode1.pixelbin, mode2.pixelbin, and black.pixelbin under:"
Write-Host (Join-Path $ScriptDir "autoplay")
