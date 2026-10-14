"""AI model settings kept on this machine (.local/ai/settings.json).

The settings page writes here, so changing the model or key needs no restart. The API key
never leaves this module through the API: callers only learn whether one is saved.
Without a settings file the older QWEN_* variables from .env are used.
"""
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

from video_parser.core.paths import ROOT

SETTINGS_PATH = Path(os.getenv('VIDEO_PARSER_AI_SETTINGS', ROOT / '.local/ai/settings.json'))

PRESETS = {
    'modelscope': {
        'name': '魔搭社区 ModelScope', 'base_url': 'https://api-inference.modelscope.cn/v1',
        'model': 'Qwen/Qwen3-VL-8B-Instruct', 'key_required': True,
        'models': ['Qwen/Qwen3-VL-8B-Instruct', 'Qwen/Qwen3-VL-30B-A3B-Instruct', 'Qwen/Qwen3-VL-235B-A22B-Instruct'],
        'hint': '在 modelscope.cn 的“访问令牌”页面创建密钥；有每日免费调用额度。',
    },
    'dashscope': {
        'name': '阿里云百炼', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen3-vl-plus', 'key_required': True,
        'models': ['qwen3-vl-plus', 'qwen3-vl-flash', 'qwen-vl-max'],
        'hint': '在百炼控制台创建 API Key；按调用量计费。',
    },
    'ollama': {
        'name': '本机 Ollama', 'base_url': 'http://127.0.0.1:11434/v1',
        'model': 'qwen2.5vl:7b', 'key_required': False,
        'models': ['qwen2.5vl:7b', 'qwen3-vl:8b'],
        'hint': '模型在本机运行，画面和字幕不会发到外部；需先安装 Ollama 并下载模型。',
    },
    'llamacpp': {
        'name': '本机 llama.cpp', 'base_url': 'http://127.0.0.1:8888/v1',
        'model': 'local-model', 'key_required': False, 'models': ['local-model'],
        'hint': '用 llama-server 在本机运行 GGUF 模型，画面和字幕不会发到外部；分析画面需带 --mmproj 视觉文件启动。模型名可随意填写；启动时设置了 --api-key 的话，在下面填同一个值。',
    },
    'custom': {
        'name': '其他 OpenAI 兼容服务', 'base_url': '', 'model': '', 'key_required': False, 'models': [],
        'hint': '填写兼容 OpenAI Chat Completions 接口的地址；分析画面需要支持图片输入的模型。',
    },
}


def is_local(url):
    try:
        return (urlsplit(url).hostname or '').lower() in {'127.0.0.1', 'localhost', '::1'}
    except ValueError:
        return False


def _from_env():
    key = os.getenv('QWEN_API_KEY', '').strip()
    base = os.getenv('QWEN_API_BASE_URL', '').strip() or PRESETS['modelscope']['base_url']
    model = os.getenv('QWEN_MODEL_ID', '').strip() or PRESETS['modelscope']['model']
    provider = next((name for name, item in PRESETS.items() if item['base_url'] == base), 'custom')
    return {'provider': provider, 'base_url': base, 'model': model, 'api_key': key,
            'price_input': None, 'price_output': None, 'consented_endpoint': '', 'source': 'env' if key else 'none'}


def current():
    """Effective settings including the key (local use only)."""
    try:
        if SETTINGS_PATH.is_file() and not SETTINGS_PATH.is_symlink() and SETTINGS_PATH.stat().st_size < 64_000:
            data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            if isinstance(data, dict) and data.get('base_url'):
                result = {**_from_env(), **{key: data.get(key) for key in (
                    'provider', 'base_url', 'model', 'api_key', 'price_input', 'price_output', 'consented_endpoint')}}
                result['api_key'] = result.get('api_key') or ''
                result['source'] = 'settings'
                return result
    except (OSError, ValueError):
        pass
    return _from_env()


def configured(settings=None):
    settings = settings or current()
    return bool(settings['base_url'] and settings['model'] and (settings['api_key'] or is_local(settings['base_url'])))


def consented(settings=None):
    settings = settings or current()
    return is_local(settings['base_url']) or settings.get('consented_endpoint') == settings['base_url']


def public():
    settings = current()
    key = settings['api_key']
    provider = settings['provider'] if settings['provider'] in PRESETS else 'custom'
    return {'provider': provider, 'provider_name': PRESETS[provider]['name'], 'base_url': settings['base_url'],
            'model': settings['model'], 'key_saved': bool(key), 'key_hint': ('••••' + key[-4:]) if len(key) >= 8 else ('已保存' if key else ''),
            'price_input': settings.get('price_input'), 'price_output': settings.get('price_output'),
            'configured': configured(settings), 'local': is_local(settings['base_url']),
            'consented': consented(settings), 'source': settings['source'],
            'storage': '.local/ai/settings.json（仅保存在本机，页面不会显示密钥）',
            'presets': {name: {key: value for key, value in item.items()} for name, item in PRESETS.items()}}


def _price(value):
    if value in (None, ''):
        return None
    number = float(value)
    if not 0 <= number <= 10_000:
        raise ValueError('价格应在 0 到 10000 元之间。')
    return round(number, 4)


def _write(data):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.is_symlink():
        raise RuntimeError('设置文件路径不安全，未保存。')
    temporary = SETTINGS_PATH.with_name('.' + uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, SETTINGS_PATH)
    except OSError:
        raise RuntimeError('无法保存 AI 设置，请检查工具目录写入权限。') from None
    finally:
        temporary.unlink(missing_ok=True)


def save(provider, base_url, model, api_key=None, clear_key=False, price_input=None, price_output=None):
    base_url = (base_url or '').strip().rstrip('/')
    model = (model or '').strip()
    parts = urlsplit(base_url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('接口地址需要以 http:// 或 https:// 开头。')
    if parts.scheme == 'http' and not is_local(base_url):
        raise ValueError('外部服务请使用 https 地址，避免密钥明文传输。')
    if not model or len(model) > 200:
        raise ValueError('请填写模型 ID。')
    previous = current()
    # A key belongs to one service: switching the address drops it unless a new one is given.
    key = previous['api_key'] if previous['base_url'] == base_url else ''
    if api_key is not None and api_key.strip():
        key = api_key.strip()
        if len(key) > 500 or any(ch.isspace() for ch in key):
            raise ValueError('密钥格式不对：不能包含空格或换行。')
    if clear_key:
        key = ''
    data = {'provider': provider if provider in PRESETS else 'custom', 'base_url': base_url, 'model': model,
            'api_key': key, 'price_input': _price(price_input), 'price_output': _price(price_output),
            # A different service must be agreed to again before anything is sent to it.
            'consented_endpoint': previous.get('consented_endpoint') if previous.get('consented_endpoint') == base_url else '',
            'updated_at': int(time.time())}
    _write(data)
    return public()


def remember_consent():
    settings = current()
    if consented(settings):
        return
    data = {key: settings.get(key) for key in ('provider', 'base_url', 'model', 'api_key', 'price_input', 'price_output')}
    data['consented_endpoint'] = settings['base_url']
    data['updated_at'] = int(time.time())
    _write(data)


def client(settings=None, timeout=None):
    from openai import OpenAI
    settings = settings or current()
    # Models on this machine read long prompts (subtitles plus frames) slower than cloud services.
    timeout = timeout or (900 if is_local(settings['base_url']) else 180)
    if not configured(settings):
        raise RuntimeError('尚未配置 AI 模型，请在“设置 → AI 模型”里填写。')
    extra = {}
    if is_local(settings['base_url']):
        # A system proxy must not intercept calls to a model running on this machine.
        from openai import DefaultHttpxClient
        extra['http_client'] = DefaultHttpxClient(trust_env=False, timeout=timeout)
    return OpenAI(base_url=settings['base_url'], api_key=settings['api_key'] or 'local', max_retries=0, timeout=timeout, **extra)


def explain(error):
    """A short, key-free message for a failed model call."""
    name = type(error).__name__
    status = getattr(error, 'status_code', None)
    if status in (401, 403) or name in ('AuthenticationError', 'PermissionDeniedError'):
        return '模型服务拒绝了请求：密钥无效或没有该模型的权限。'
    if status == 404 or name == 'NotFoundError':
        return '找不到这个模型或接口地址，请检查模型 ID 和地址。'
    if status == 429 or name == 'RateLimitError':
        return '调用太频繁或额度已用完，请稍后再试。'
    if status == 400 or name == 'BadRequestError':
        return '模型服务不接受这次请求（可能不支持图片输入，或内容太长）。'
    if name in ('APIConnectionError', 'APITimeoutError', 'ConnectError', 'Timeout'):
        return '连不上模型服务，请检查网络或接口地址。'
    if isinstance(status, int):
        return f'模型服务返回错误（HTTP {status}）。'
    return '模型调用失败，请检查 AI 设置后重试。'


def test():
    settings = current()
    started = time.monotonic()
    try:
        response = client(settings, timeout=120 if is_local(settings['base_url']) else 30).chat.completions.create(
            model=settings['model'], messages=[{'role': 'user', 'content': '只回复两个字母：OK'}], max_tokens=8)
        reply = (response.choices[0].message.content or '').strip()
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(explain(error)) from None
    return {'ok': True, 'latency_ms': int((time.monotonic() - started) * 1000), 'reply': reply[:40], 'model': settings['model']}
