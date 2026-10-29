# Start Switchboard + a Cloudflare quick tunnel for phone access.
# Usage (from the Switchboard folder):
#   powershell -ExecutionPolicy Bypass -File scripts/start-tunnel.ps1
# It prints ONE login link. Open it on your phone once; a 30-day cookie keeps you in.
# Anyone with that link can act as you — treat it like a password. Stop with Ctrl+C
# on the tunnel window (or close both processes).

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (-not $env:SWITCHBOARD_UI_TOKEN) {
    $env:SWITCHBOARD_UI_TOKEN = [guid]::NewGuid().ToString("N")
    Write-Host "Generated a new UI token for this session."
}

$backend = Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "switchboard.app" -WorkingDirectory $root -PassThru
Write-Host "Backend pid $($backend.Id) on http://127.0.0.1:8765 (UI token auth ON)"

Start-Sleep 3
Write-Host "Starting tunnel... your login link appears below:"
& "$root\.tools\cloudflared.exe" tunnel --url http://127.0.0.1:8765 --no-autoupdate 2>&1 |
    ForEach-Object {
        $_
        if ($_ -match "(https://[a-z0-9-]+\.trycloudflare\.com)") {
            Write-Host ""
            Write-Host "PHONE LOGIN LINK: $($Matches[1])/login?token=$env:SWITCHBOARD_UI_TOKEN"
            Write-Host "Open that on your phone. After login, bookmark the site (not the login link)."
        }
    }
