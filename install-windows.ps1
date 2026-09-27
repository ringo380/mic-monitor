# Put the two Windows entry points on PATH as .cmd shims in ~\.local\bin
# (the Windows equivalent of the macOS `ln -sf ... ~/.local/bin` step).
# Shims call the repo scripts by absolute path, so the repo stays the source.
# Re-run after moving the repo.
$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$bin  = Join-Path $HOME '.local\bin'
if (-not (Test-Path -LiteralPath $bin)) { New-Item -ItemType Directory -Path $bin | Out-Null }

$cli = @(
    '@echo off',
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$repo\mic-monitor.ps1`" %*"
) -join "`r`n"
$tray = @(
    '@echo off',
    "start `"`" `"C:\Program Files\Python314\pythonw.exe`" `"$repo\mic-monitor-tray.py`""
) -join "`r`n"

# ASCII = no BOM. A BOM in front of @echo off makes cmd print an error line.
$ascii = New-Object System.Text.ASCIIEncoding
[IO.File]::WriteAllText((Join-Path $bin 'mic-monitor.cmd'), $cli + "`r`n", $ascii)
[IO.File]::WriteAllText((Join-Path $bin 'mic-monitor-tray.cmd'), $tray + "`r`n", $ascii)

Write-Output "Wrote $bin\mic-monitor.cmd and $bin\mic-monitor-tray.cmd"
$onPath = ($env:PATH -split ';') -contains $bin
if (-not $onPath) { Write-Output "NOTE: $bin is not on PATH in this shell." }
