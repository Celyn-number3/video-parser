"""Validated local llama.cpp launch settings; safe argv construction shared by CLI and local web startup."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import os
import socket
import subprocess

from video_parser.core.paths import ROOT

DEFAULTS = {
    'server_path': 'runtimes/llama.cpp/b11429-cuda12.4/llama-server.exe',
    'model_path': 'runtimes/models/qwen3-vl-8b-instruct/Qwen3VL-8B-Instruct-Q4_K_M.gguf',
    'vision_path': 'runtimes/models/qwen3-vl-8b-instruct/mmproj-Qwen3VL-8B-Instruct-F16.gguf',
    'port': 8888, 'context_size': 32768, 'gpu_layers': 99, 'threads': 0,
    'parallel': 1, 'show_console': True, 'flash_attention': True, 'image_max_tokens': 1024, 'max_output_tokens': 4096,
}
BOUNDS = {
    'port': (1024, 65535, '服务端口'), 'context_size': (512, 131072, '上下文长度'),
    'gpu_layers': (-1, 999, '显卡层数'), 'threads': (0, 256, 'CPU 线程数'),
    'parallel': (1, 4, '同时处理数'), 'image_max_tokens': (128, 4096, '每张图像上限'),
    'max_output_tokens': (128, 32768, '单次回复上限'),
}
PATH_LABELS = {'server_path': '运行程序', 'model_path': '模型文件', 'vision_path': '视觉文件'}
PINNED = {
    'model_path': (5027784800, '67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2'),
    'vision_path': (1159029824, 'ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38'),
}


def normalize(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('启动配置包含不支持的选项，请重新加载设置。')
    result = {**DEFAULTS, **value}
    for field, label in PATH_LABELS.items():
        path = result[field]
        if not isinstance(path, str) or len(path) > 2048 or any(ord(ch) < 32 for ch in path):
            raise ValueError(f'{label}路径格式不正确。')
        path = path.strip()
        if not path and field == 'vision_path':
            result[field] = ''
            continue
        suffix = '.exe' if field == 'server_path' else '.gguf'
        if not path or not path.lower().endswith(suffix) or '://' in path or path.startswith(('\\\\', '//')):
            raise ValueError(f'{label}需要本机的 {suffix} 文件路径。')
        result[field] = path
    for field, (low, high, label) in BOUNDS.items():
        number = result[field]
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f'{label}需要 {low} 到 {high} 之间的整数。')
    for field, label in [('flash_attention', '显卡加速'), ('show_console', '命令行窗口')]:
        if type(result[field]) is not bool:
            raise ValueError(f'{label}开关格式不正确。')
    if result['max_output_tokens'] > result['context_size']:
        raise ValueError('单次回复上限不能大于上下文长度。')
    return result


def effective(settings):
    return normalize(settings.get('startup'))


def local_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def endpoint(config):
    return f"http://127.0.0.1:{config['port']}/v1"


def arguments(config, model):
    config = normalize(config)
    if not isinstance(model, str) or not model.strip() or len(model) > 200 or any(ord(ch) < 32 for ch in model):
        raise ValueError('请填写不含换行的模型 ID。')
    result = ['--model', str(local_path(config['model_path'])), '--host', '127.0.0.1',
              '--port', str(config['port']), '--alias', model.strip(),
              '--n-gpu-layers', str(config['gpu_layers']), '--ctx-size', str(config['context_size']),
              '--parallel', str(config['parallel']), '--flash-attn', 'on' if config['flash_attention'] else 'off',
              '--batch-size', '512', '--ubatch-size', '256', '--n-predict', str(config['max_output_tokens']), '--no-webui']
    if config['vision_path']:
        result.extend(['--mmproj', str(local_path(config['vision_path'])), '--image-max-tokens', str(config['image_max_tokens'])])
    if config['threads']:
        result.extend(['--threads', str(config['threads'])])
    return result


def quote_powershell(value):
    return "'" + str(value).replace("'", "''") + "'"


def launcher_command():
    return '& ' + quote_powershell(ROOT / 'start-ai.cmd')


def inspect(value, model, verify_files=False):
    """Only inspect paths/parameters. Never launch, kill, download or write a file."""
    config = normalize(value)
    args = arguments(config, model)
    checks = []
    warnings = []
    for field, label in PATH_LABELS.items():
        if field == 'vision_path' and not config[field]:
            warnings.append('未配置视觉文件：只能使用支持的纯文本模式，不能分析视频画面。')
            continue
        path = local_path(config[field])
        try:
            valid = path.is_file()
            message = '文件存在' if valid else '未找到文件，请检查路径'
            # Preserve the installed model's size/hash checks; custom files are not claimed verified.
            if valid and field in PINNED:
                is_pinned = path.resolve() == local_path(DEFAULTS[field]).resolve()
                if is_pinned:
                    size, digest = PINNED[field]
                    valid = path.stat().st_size == size
                    message = '文件大小正确' if valid else '文件不完整或与已安装版本不匹配'
                    if valid and verify_files:
                        with path.open('rb') as stream:
                            valid = hashlib.file_digest(stream, 'sha256').hexdigest() == digest
                        message = 'SHA-256 校验通过' if valid else 'SHA-256 校验失败'
                elif verify_files:
                    warnings.append(f'{label}是自选文件，没有已知校验值；仅检查存在性。')
        except OSError:
            valid, message = False, '无法读取文件，请检查路径和权限'
        checks.append({'field': field, 'label': label, 'ok': valid, 'message': message})
    port_in_use = occupied(config['port'])
    if port_in_use:
        warnings.append(f"端口 {config['port']} 正在使用：若是当前模型，可继续使用；修改启动配置后需手动重启。不会停止现有服务。")
    return {'ok': all(item['ok'] for item in checks), 'checks': checks, 'warnings': warnings, 'port_in_use': port_in_use,
            'base_url': endpoint(config), 'launcher_command': launcher_command(),
            'command': '& ' + ' '.join(quote_powershell(value) for value in [str(local_path(config['server_path'])), *args])}


def occupied(port):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def same_running_model(port, model, token, timeout=5):
    # No redirects or system proxy: a local token must never be forwarded elsewhere.
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', '/v1/models', headers={'Authorization': 'Bearer ' + token})
        response = connection.getresponse()
        if response.status != 200:
            return False
        payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            return False
        data = json.loads(payload)
        return isinstance(data, dict) and any(isinstance(item, dict) and item.get('id') == model for item in data.get('data', []))
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def run(settings, check_only=False, verify_files=False, port=None):
    config = effective(settings)
    if port is not None:
        config = normalize({**config, 'port': port})
    model = settings.get('model', '')
    if settings.get('provider') != 'llamacpp' or settings.get('base_url', '').rstrip('/') != endpoint(config):
        raise ValueError('启动配置与 AI 接口地址不一致，请在“设置 → AI 模型”保存本机 llama.cpp 配置。')
    token = settings.get('api_key') or ''
    if not token or any(ch.isspace() for ch in token):
        raise ValueError('请先在“设置 → AI 模型”保存启动配置，程序会自动生成本机访问令牌。')
    report = inspect(config, model, verify_files)
    if not report['ok']:
        failed = '；'.join(item['label'] + '：' + item['message'] for item in report['checks'] if not item['ok'])
        raise ValueError(failed)
    if check_only:
        print(f"Preflight OK: {model}; context={config['context_size']}; {endpoint(config)}")
        for warning in report['warnings']:
            print(warning)
        return 0
    if occupied(config['port']):
        if same_running_model(config['port'], model, token):
            print(f"Model already running: {endpoint(config)}. New launch settings apply after a manual restart.")
            return 0
        raise ValueError(f"端口 {config['port']} 已被占用或模型正在加载；未停止任何进程，请先检查现有窗口。")
    environment = os.environ.copy()
    environment['LLAMA_API_KEY'] = token
    print(f"Starting {model}: {endpoint(config)}. Keep this terminal open; Ctrl+C stops the model.", flush=True)
    result = subprocess.run([str(local_path(config['server_path'])), *arguments(config, model)],
                            cwd=ROOT, env=environment, shell=False, check=False)
    if result.returncode:
        raise RuntimeError(f'模型服务退出，代码 {result.returncode}；请查看上方模型输出。')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start the saved local AI configuration.')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--verify-files', action='store_true')
    parser.add_argument('--port', type=int)
    args = parser.parse_args(argv)
    from video_parser.services import ai_settings
    try:
        return run(ai_settings.current(), args.check, args.verify_files, args.port)
    except (OSError, ValueError, RuntimeError) as error:
        # OSError details can include the environment; report a generic message instead.
        message = '无法启动本机程序，请检查文件权限与运行环境。' if isinstance(error, OSError) else str(error)
        print('Local AI startup failed: ' + message)
        return 1
    except KeyboardInterrupt:
        return 130
