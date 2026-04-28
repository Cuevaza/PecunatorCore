# Bootstrap Flutter desktop app under desktop_shell/ (requires Flutter SDK).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$shell = Join-Path $root 'desktop_shell'

function Test-Flutter {
    return [bool](Get-Command flutter -ErrorAction SilentlyContinue)
}

if (-not (Test-Flutter)) {
    Write-Host "Flutter CLI not found. Install from https://docs.flutter.dev/get-started/install/windows" -ForegroundColor Yellow
    Write-Host "Then add Flutter to PATH and run: .\scripts\init_flutter_desktop.ps1" -ForegroundColor Yellow
    exit 1
}

$pubspec = Join-Path $shell 'pubspec.yaml'
if (Test-Path $pubspec) {
    Write-Host "desktop_shell already initialized (pubspec.yaml exists)." -ForegroundColor Green
    Set-Location $shell
    flutter pub get
    exit 0
}

# Scaffold into folder (Flutter creates the directory).

Push-Location $root
try {
    flutter create $shell --project-name pecunator_desktop --platforms=windows,linux,macos `
        --description "Pecunator desktop shell"
}
finally {
    Pop-Location
}

Write-Host "Done. cd desktop_shell && flutter run -d windows" -ForegroundColor Green
