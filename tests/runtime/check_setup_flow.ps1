# Isolated installer control-flow checks. No real installs or model downloads.
$ErrorActionPreference = 'Stop'
$Project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Scratch = Join-Path ([IO.Path]::GetTempPath()) ('video-parser-setup-' + [guid]::NewGuid().ToString('N'))
$Chinese = -join ([char]0x4E2D, [char]0x6587)
$Fixture = Join-Path $Scratch ($Chinese + ' path')
$Scripts = Join-Path $Fixture 'scripts'
New-Item -ItemType Directory -Path $Scripts -Force | Out-Null
$Source = Get-Content -LiteralPath (Join-Path $Project 'scripts/setup-local-tools.ps1') -Raw
$Source = $Source.Replace('    & $Program @Arguments', '    $global:Calls.Add(($Program + " " + ($Arguments -join " "))) | Out-Null; $global:LASTEXITCODE = 0')
$Script = Join-Path $Scripts 'setup-local-tools.ps1'
[IO.File]::WriteAllText($Script, $Source, (New-Object Text.UTF8Encoding($true)))
$global:FixturePython = Join-Path $Fixture 'runtimes/python/cpython-3.12.13-windows-x86_64-none/python.exe'
New-Item -ItemType Directory -Path (Split-Path $global:FixturePython -Parent) -Force | Out-Null
New-Item -ItemType File -Path $global:FixturePython | Out-Null
function global:uv { $global:LASTEXITCODE = 0; if ($args[0] -eq 'python' -and $args[1] -eq 'find') { $global:FixturePython } }
$Initial = [Console]::OutputEncoding.CodePage
try {
    foreach ($Download in @($false, $true)) {
        $global:Calls = New-Object 'System.Collections.Generic.List[string]'
        & $Script -SkipFrontend -DownloadModel:$Download
        $ModelCalls = @($global:Calls | Where-Object { $_ -like '*verify-whisper-model.py*' })
        if ($Download -and ($ModelCalls.Count -ne 1 -or $ModelCalls[0] -notlike '*--download*')) { throw 'Explicit model download was not verified.' }
        if (!$Download -and $ModelCalls.Count -ne 0) { throw 'Optional model still blocks base install.' }
        if ([Console]::OutputEncoding.CodePage -ne $Initial) { throw 'Console encoding not restored.' }
    }
    $global:FixturePython = Join-Path $Scratch 'outside/python.exe'
    New-Item -ItemType Directory -Path (Split-Path $global:FixturePython -Parent) -Force | Out-Null
    New-Item -ItemType File -Path $global:FixturePython | Out-Null
    $Rejected = $false
    try { & $Script -SkipFrontend } catch { $Rejected = $_.Exception.Message -like '*inside this project*' }
    if (!$Rejected) { throw 'Outside-project Python was accepted.' }
    $Saved = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
        $env:VIDEO_PARSER_ENCODING_FIXTURE = $Fixture
        $NativeScript = Join-Path $Scratch 'native-path.py'
        [IO.File]::WriteAllText($NativeScript, 'import os; print(os.environ["VIDEO_PARSER_ENCODING_FIXTURE"])', (New-Object Text.UTF8Encoding($false)))
        $Actual = & (Join-Path $Project '.venv/Scripts/python.exe') -X utf8 $NativeScript
        if ($LASTEXITCODE -ne 0 -or $Actual -ne $Fixture) { throw 'Native UTF-8 path roundtrip failed.' }
    } finally { [Console]::OutputEncoding = $Saved; Remove-Item Env:VIDEO_PARSER_ENCODING_FIXTURE -ErrorAction SilentlyContinue }
    Write-Output 'PASS: Chinese/space paths, native UTF-8, optional/download branches, outside-root rejection, restored encoding. No downloads performed.'
} finally {
    Remove-Item Function:uv -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Scratch -Recurse -Force
}
