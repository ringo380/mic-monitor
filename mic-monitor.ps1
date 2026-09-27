# Toggle live Yeti -> Corsair headphone monitoring (Windows counterpart of
# the zsh `mic-monitor` wrapper).
# Usage: mic-monitor [start|stop|status|toggle] [worker args...]   (default: toggle)
#
# The worker runs under pythonw.exe (no console window) and writes its own
# log via --log. Start-Process must NOT redirect the worker's handles: with
# redirection the child inherits every inheritable handle, including a
# caller's capture pipe, so `mic-monitor start | ...` or the tray app's
# subprocess.run(capture_output=True) would block until the worker exited.
# Liveness is checked with Get-Process on the PID file, and the PID is only
# trusted when it still belongs to a pythonw process (guards PID reuse).
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = 'toggle',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$WorkerArgs = @()
)

$Py      = 'C:\Program Files\Python314\pythonw.exe'
$Script  = Join-Path $PSScriptRoot 'yeti-monitor.py'
$PidFile = Join-Path $env:TEMP 'mic-monitor.pid'
$Log     = Join-Path $env:TEMP 'mic-monitor.log'

function Get-WorkerPid {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not ($raw -match '^\d+$')) { return $null }
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq 'pythonw') { return [int]$raw }
    return $null
}

function Start-Monitor {
    $existing = Get-WorkerPid
    if ($existing) { Write-Output "Already running (pid $existing)."; return }
    $argList = @("`"$Script`"", '--log', "`"$Log`"") + $WorkerArgs
    $proc = Start-Process -FilePath $Py -ArgumentList $argList -PassThru
    Set-Content -LiteralPath $PidFile -Value $proc.Id -Encoding ascii
    Write-Output "Started mic monitor (pid $($proc.Id)). Log: $Log"
}

function Stop-Monitor {
    $existing = Get-WorkerPid
    if ($existing) {
        Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Output "Stopped."
    } else {
        Write-Output "Not running."
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }
}

switch ($Command) {
    'start'  { Start-Monitor }
    'stop'   { Stop-Monitor }
    'status' {
        $existing = Get-WorkerPid
        if ($existing) { Write-Output "Running (pid $existing)." } else { Write-Output "Not running." }
    }
    'toggle' { if (Get-WorkerPid) { Stop-Monitor } else { Start-Monitor } }
    default  { Write-Output "Usage: mic-monitor [start|stop|status|toggle]"; exit 1 }
}
exit 0
