param([switch]$DownloadModel, [switch]$SkipFrontend)
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
function Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program (exit $LASTEXITCODE)" }
}
$Names = @('UV_PYTHON_INSTALL_DIR','UV_PYTHON_BIN_DIR','UV_CACHE_DIR','PLAYWRIGHT_BROWSERS_PATH','PLAYWRIGHT_SKIP_BROWSER_GC')
$Saved = @{}
foreach ($Name in $Names) { $Saved[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process') }
Push-Location $Root
try {
    Get-Command uv -ErrorAction Stop | Out-Null
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'runtimes/python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $Root 'runtimes/bin'
    $env:UV_CACHE_DIR = Join-Path $Root 'cache/uv'
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root 'runtimes/browsers'
    $env:PLAYWRIGHT_SKIP_BROWSER_GC = '1'
    $Python = Join-Path $Root 'runtimes/python/cpython-3.12-windows-x86_64-none/python.exe'
    if (!(Test-Path $Python)) {
        Checked 'uv' @('python','install','3.12.13')
        $Python = (& uv python find --managed-python 3.12.13).Trim()
        if ($LASTEXITCODE -ne 0 -or !$Python.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Managed Python must be inside this project.' }
    }
    Checked $Python @('-c','import sys; assert sys.version_info[:3] == (3,12,13)')
    $Main = Join-Path $Root '.venv/Scripts/python.exe'
    $Whisper = Join-Path $Root 'runtimes/whisper/Scripts/python.exe'
    if (!(Test-Path $Main)) { Checked 'uv' @('venv','.venv','--python',$Python,'--seed') }
    if (!(Test-Path $Whisper)) { Checked 'uv' @('venv','runtimes/whisper','--python',$Python,'--seed') }
    # A copied virtual environment is not portable. Never silently overwrite it.
    Checked $Main @('-c',"import pathlib,sys; assert pathlib.Path(sys.prefix).resolve()==(pathlib.Path.cwd()/'.venv').resolve(), 'Recreate the moved main venv'")
    Checked $Whisper @('-c',"import pathlib,sys; assert pathlib.Path(sys.base_prefix).resolve().is_relative_to(pathlib.Path.cwd()), 'Recreate the moved Whisper venv'")
    Checked $Main @('-X','utf8','scripts/check-main-lock.py')
    Checked 'uv' @('pip','install','--python',$Main,'-r','requirements/windows-main.lock.txt','--index-url','https://pypi.org/simple')
    Checked 'uv' @('pip','install','--python',$Main,'--no-deps','-e','.','--index-url','https://pypi.org/simple')
    Checked 'uv' @('pip','install','--python',$Whisper,'-r','requirements/windows-whisper.lock.txt','--index-url','https://pypi.org/simple')
    Checked $Main @('-m','playwright','install','chromium')
    $ModelArgs = @('-X','utf8','scripts/verify-whisper-model.py')
    if ($DownloadModel) { $ModelArgs += '--download' }
    Checked $Whisper $ModelArgs
    Checked $Main @('-m','pip','check')
    Checked $Whisper @('-m','pip','check')
    if (!$SkipFrontend) {
        Push-Location (Join-Path $Root 'frontend')
        try { Checked 'npm.cmd' @('ci'); Checked 'npm.cmd' @('run','build') } finally { Pop-Location }
    }
    Write-Output 'Unified local tools ready. Start with start-web.ps1 or python -m video_parser.'
} finally {
    Pop-Location
    foreach ($Name in $Names) { [Environment]::SetEnvironmentVariable($Name, $Saved[$Name], 'Process') }
}
