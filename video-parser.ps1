# Run from this project or use the script's absolute path. Does not start Web services.
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}
& $python (Join-Path $PSScriptRoot 'cli.py') @args
exit $LASTEXITCODE
