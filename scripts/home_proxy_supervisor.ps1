# Keeps scripts/home_proxy.py alive. It died silently once after ~14h and took
# arca/quasarzone/coolenjoy collection down with it, with no traceback because
# pythonw discards stderr. This relaunches it and keeps that stderr on disk.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$script = Join-Path $root "scripts\home_proxy.py"
$log = Join-Path $env:USERPROFILE "home_proxy_supervisor.log"
$crash = Join-Path $env:USERPROFILE "home_proxy_stderr.log"

function Write-Log([string]$msg) {
    "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg | Add-Content $log -Encoding utf8
}

Write-Log "supervisor started"
while ($true) {
    try {
        $p = Start-Process -FilePath $python -ArgumentList "`"$script`"" `
            -RedirectStandardError $crash -PassThru -WindowStyle Hidden
        $null = $p.Handle  # cache the handle or ExitCode comes back empty
        Write-Log "proxy started pid=$($p.Id)"
        $p.WaitForExit()
        Write-Log "proxy exited code=$($p.ExitCode) — restarting in 5s"
    } catch {
        Write-Log "launch failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 5
}
