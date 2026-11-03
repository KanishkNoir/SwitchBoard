$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = 'utf-8'
$hookInput = [Console]::In.ReadToEnd()
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Switchboard Python runtime is unavailable.'
    exit 2
}
$hookInput | & $pythonPath "$PSScriptRoot\switchboard_gate.py"
exit $LASTEXITCODE
