# Run Flutter desktop shell (reloads PATH + resolves flutter.bat when `flutter` is missing).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
# Prefer project-pinned Flutter SDK on Desktop (avoids shadowing by other flutter.exe on PATH).
$desktopFlutterBin = Join-Path $env:USERPROFILE 'Desktop\flutter_windows_3.41.8-stable\flutter\bin'
if (Test-Path (Join-Path $desktopFlutterBin 'flutter.bat')) {
    $env:Path = "$desktopFlutterBin;" + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
} else {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Resolve-FlutterBat {
    $flutterCmd = Get-Command flutter -ErrorAction SilentlyContinue
    if ($flutterCmd -and (Test-Path $flutterCmd.Source)) {
        return $flutterCmd.Source
    }
    if ($env:PECUNATOR_FLUTTER_BAT -and (Test-Path $env:PECUNATOR_FLUTTER_BAT)) {
        return $env:PECUNATOR_FLUTTER_BAT
    }
    foreach ($p in @(
            "$env:USERPROFILE\flutter\bin\flutter.bat",
            "$env:LOCALAPPDATA\flutter\bin\flutter.bat",
            "$env:USERPROFILE\Desktop\flutter_windows_3.41.8-stable\flutter\bin\flutter.bat"
        )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Set-Location (Join-Path $root 'desktop_shell')
$flutter = Resolve-FlutterBat
if (-not $flutter) {
    Write-Host @'

Flutter no encontrado.

  1) Instala el SDK: https://docs.flutter.dev/get-started/install/windows
  2) Anade ...\flutter\bin al PATH de usuario y CIERRA y abre PowerShell
  3) O define variable de usuario PECUNATOR_FLUTTER_BAT = ruta completa a flutter.bat

'@ -ForegroundColor Yellow
    if ($Host.Name -eq 'ConsoleHost') {
        Read-Host 'Pulsa Enter para cerrar'
    }
    exit 1
}

Write-Host "Flutter: $flutter" -ForegroundColor DarkGray
& $flutter pub get
& $flutter run -d windows
