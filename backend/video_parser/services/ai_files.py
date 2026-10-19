"""Native model file selection. Returns a path only; never uploads, saves or starts a model."""
import base64
import json
from pathlib import Path
import subprocess
from subprocess import run
import sys

from video_parser.core.paths import ROOT
from video_parser.services import ai_settings, ai_startup, folders

FIELDS = {'model_path': ('选择主模型 GGUF 文件', 'GGUF 模型 (*.gguf)|*.gguf', '.gguf'),
          'vision_path': ('选择配套视觉 mmproj 文件', 'GGUF 视觉文件 (*.gguf)|*.gguf', '.gguf'),
          'server_path': ('选择 llama-server.exe', '运行程序 (*.exe)|*.exe', '.exe')}
DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$options = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__OPTIONS__')) | ConvertFrom-Json
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true; $owner.ShowInTaskbar = $false; $owner.Opacity = 0
$owner.StartPosition = 'CenterScreen'; $owner.Show(); $owner.Activate()
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = $options.title; $dialog.Filter = $options.filter
$dialog.InitialDirectory = $options.directory
$dialog.CheckFileExists = $true; $dialog.Multiselect = $false; $dialog.RestoreDirectory = $true
try {
  if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
    [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($dialog.FileName))
  }
} finally { $dialog.Dispose(); $owner.Close(); $owner.Dispose() }
'''


def pick(field):
    if field not in FIELDS:
        raise ValueError('不支持的模型文件类型。')
    if sys.platform != 'win32':
        raise RuntimeError('本机文件选择窗口目前支持 Windows；也可以直接填写文件路径。')
    if not folders.dialog_lock.acquire(blocking=False):
        raise BlockingIOError('已经打开了本机文件选择窗口，请先完成选择或取消。')
    try:
        title, filter_text, suffix = FIELDS[field]
        try:
            config = ai_startup.effective(ai_settings.current())
        except ValueError:
            config = ai_startup.normalize()
        initial = ai_startup.local_path(config[field]).parent if config[field] else ROOT / 'runtimes/models'
        if not initial.is_dir(): initial = ROOT
        options = base64.b64encode(json.dumps({'title': title, 'filter': filter_text, 'directory': str(initial)}, ensure_ascii=False).encode('utf-8')).decode('ascii')
        script = base64.b64encode(DIALOG.replace('__OPTIONS__', options).encode('utf-16-le')).decode('ascii')
        try:
            result = run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', script],
                         capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), shell=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError('文件选择窗口等待超时，请重新选择；原路径没有改变。') from None
        except OSError:
            raise RuntimeError('无法打开本机文件选择窗口；请检查 PowerShell，或直接填写路径。') from None
        if result.returncode:
            raise RuntimeError('文件选择窗口未正常完成；原路径没有改变，请重试。')
        output = (result.stdout or '').strip()
        if not output: return None
        try:
            chosen = base64.b64decode(output, validate=True).decode('utf-8')
        except (ValueError, UnicodeError):
            raise ValueError('无法读取所选文件路径，请重新选择。') from None
        # Reuse launch path restrictions, then validate the actual selection, including resolved targets.
        ai_startup.normalize({field: chosen})
        path = Path(chosen)
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() != suffix:
            raise ValueError('所选文件不存在或类型不正确，请重新选择。')
        path = path.resolve()
        ai_startup.normalize({field: str(path)})
        return path.relative_to(ROOT.resolve()).as_posix() if path.is_relative_to(ROOT.resolve()) else str(path)
    finally:
        folders.dialog_lock.release()
