# Run from this project or use the script's absolute path. Does not start Web services.
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}
& $python -m video_parser @args
exit $LASTEXITCODE
