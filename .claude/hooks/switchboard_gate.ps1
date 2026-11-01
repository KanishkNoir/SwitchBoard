$hookInput = [Console]::In.ReadToEnd()
$hookInput | python "$PSScriptRoot\switchboard_gate.py"
exit $LASTEXITCODE
