param(
    [ValidateRange(1024, 65535)][int]$Port,
    [switch]$CheckOnly,
    [switch]$VerifyFiles
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root '.venv\Scripts\python.exe'
$launcher = Join-Path $root 'scripts\start-local-ai.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project .venv not found. Please prepare the local environment first.' }
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'Local AI launcher not found.' }

# Settings, paths and access token are read by the local launcher, not passed through a shell string.
# Without -Port, use the port saved in Settings > AI model. Existing switches remain supported.
$launchArgs = @()
if ($PSBoundParameters.ContainsKey('Port')) { $launchArgs += @('--port', [string]$Port) }
if ($CheckOnly) { $launchArgs += '--check' }
if ($VerifyFiles) { $launchArgs += '--verify-files' }
& $python -X utf8 $launcher @launchArgs
if ($LASTEXITCODE -ne 0) { throw "Local AI startup failed (exit $LASTEXITCODE). See the message above." }
