param(
    [string]$ShortcutName = "Pixel Light Autoplay"
)

$ErrorActionPreference = "Stop"

$StartupDir = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "$ShortcutName.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath
    Write-Host "Removed startup shortcut:"
    Write-Host $ShortcutPath
} else {
    Write-Host "Startup shortcut not found:"
    Write-Host $ShortcutPath
}
